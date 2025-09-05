#!/usr/bin/env python3
"""
Backfill Worker Service.

- Consumes backfill jobs from BACKFILL_JOBS_QUEUE (RabbitMQ)
- Dispatches to provider implementation (providers/*)
- Each provider fetches historical data in chunks and yields canonical
  FinBase records which are published into RAW_QUEUE_NAME.

Message format (JSON):
{
  "ticker": "NVDA",
  "provider": "yfinance",
  "start_date": "2000-01-01",
  "end_date": "2023-12-31",
  // Optional:
  // "interval": "1d" | "1h" | "1m" (provider-specific)
}
"""
from __future__ import annotations

import json
import logging
import os
import random
import signal
import sys
import time
from datetime import datetime, timedelta
from threading import Event
from typing import Any, Callable, Dict, Iterable, Tuple

import pika
from pika.exceptions import AMQPConnectionError, ChannelClosedByBroker, StreamLostError
from dotenv import load_dotenv
import psycopg2

# Providers
from providers.yfinance_provider import fetch_yfinance
from providers.alpaca_provider import fetch_alpaca

# Logging (UTC ISO timestamps)
logging.Formatter.converter = time.gmtime
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)sZ %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("backfill-worker")

stop_event = Event()

# Global DB connection (reused across jobs)
db_conn = None


def load_config() -> Dict[str, Any]:
    """Load environment-based configuration for the backfill worker.

    Returns:
        Dict[str, Any]: Configuration including RabbitMQ, DB, and worker tuning.
    """
    load_dotenv()
    cfg: Dict[str, Any] = {}
    # RabbitMQ
    cfg["RABBITMQ_HOST"] = os.getenv("RABBITMQ_HOST", "localhost")
    cfg["RABBITMQ_PORT"] = int(os.getenv("RABBITMQ_PORT", "5672"))
    cfg["RABBITMQ_USER"] = os.getenv("RABBITMQ_USER", "guest")
    cfg["RABBITMQ_PASSWORD"] = os.getenv("RABBITMQ_PASSWORD", "guest")
    cfg["RABBITMQ_HEARTBEAT"] = int(os.getenv("RABBITMQ_HEARTBEAT", "30"))
    cfg["RABBITMQ_BLOCKED_TIMEOUT"] = int(os.getenv("RABBITMQ_BLOCKED_TIMEOUT", "60"))

    # Queues
    cfg["BACKFILL_JOBS_QUEUE"] = os.getenv("BACKFILL_JOBS_QUEUE", "backfill_jobs_queue")
    cfg["RAW_QUEUE_NAME"] = os.getenv("RAW_QUEUE_NAME", "raw_data_queue")

    # Worker behavior
    cfg["PREFETCH_COUNT"] = int(os.getenv("PREFETCH_COUNT", "1"))
    cfg["MAX_CONNECTION_ATTEMPTS"] = int(os.getenv("MAX_CONNECTION_ATTEMPTS", "0"))

    # Provider defaults
    cfg["BACKFILL_INTERVAL"] = os.getenv("BACKFILL_INTERVAL", "1d")
    cfg["CHUNK_MONTHS"] = int(os.getenv("CHUNK_MONTHS", "1"))
    cfg["SLEEP_BETWEEN_CHUNKS_SECONDS"] = float(os.getenv("SLEEP_BETWEEN_CHUNKS_SECONDS", "0.2"))

    # Database (TimescaleDB / PostgreSQL)
    cfg["DB_HOST"] = os.getenv("DB_HOST", "localhost")
    cfg["DB_PORT"] = int(os.getenv("DB_PORT", "5432"))
    cfg["DB_NAME"] = os.getenv("DB_NAME", "finbase")
    cfg["DB_USER"] = os.getenv("DB_USER", "finbase")
    cfg["DB_PASSWORD"] = os.getenv("DB_PASSWORD", "supersecretpassword")

    logger.info(
        "Config: jobs_queue=%s raw_queue=%s rmq=%s:%s prefetch=%s interval=%s chunk_months=%s db=%s:%s/%s",
        cfg["BACKFILL_JOBS_QUEUE"], cfg["RAW_QUEUE_NAME"], cfg["RABBITMQ_HOST"], cfg["RABBITMQ_PORT"],
        cfg["PREFETCH_COUNT"], cfg["BACKFILL_INTERVAL"], cfg["CHUNK_MONTHS"],
        cfg["DB_HOST"], cfg["DB_PORT"], cfg["DB_NAME"],
    )
    return cfg


def connect_rabbit(cfg) -> Tuple[pika.BlockingConnection, pika.adapters.blocking_connection.BlockingChannel]:
    """Connect to RabbitMQ with retry/backoff and ensure queues exist.

    Returns a tuple (connection, channel) with QoS configured.
    """
    credentials = pika.PlainCredentials(cfg["RABBITMQ_USER"], cfg["RABBITMQ_PASSWORD"])
    parameters = pika.ConnectionParameters(
        host=cfg["RABBITMQ_HOST"],
        port=cfg["RABBITMQ_PORT"],
        credentials=credentials,
        heartbeat=cfg["RABBITMQ_HEARTBEAT"],
        blocked_connection_timeout=cfg["RABBITMQ_BLOCKED_TIMEOUT"],
        connection_attempts=1,  # use outer retry loop
        retry_delay=0,
        client_properties={"connection_name": "backfill-worker"},
    )

    attempt = 0
    max_attempts = cfg["MAX_CONNECTION_ATTEMPTS"]

    while not stop_event.is_set():
        attempt += 1
        try:
            logger.info("Connecting to RabbitMQ attempt %s...", attempt)
            conn = pika.BlockingConnection(parameters)
            ch = conn.channel()
            # Ensure queues
            ch.queue_declare(queue=cfg["BACKFILL_JOBS_QUEUE"], durable=True)
            ch.queue_declare(queue=cfg["RAW_QUEUE_NAME"], durable=True)
            ch.basic_qos(prefetch_count=cfg["PREFETCH_COUNT"])
            logger.info("Backfill worker connected. Queues ready: jobs=%s raw=%s", cfg["BACKFILL_JOBS_QUEUE"], cfg["RAW_QUEUE_NAME"])
            return conn, ch
        except AMQPConnectionError as e:
            backoff = min(60, (2 ** min(attempt, 6))) + random.uniform(0, 1)
            logger.error("RabbitMQ connection failed: %s (retry in %.1fs)", str(e), backoff)
            stop_event.wait(backoff)
        except Exception as e:
            backoff = min(60, (2 ** min(attempt, 6))) + random.uniform(0, 1)
            logger.exception("Unexpected RMQ connect error: %s (retry in %.1fs)", str(e), backoff)
            stop_event.wait(backoff)
        if max_attempts > 0 and attempt >= max_attempts:
            raise SystemExit("Max RMQ connection attempts exceeded")
    raise SystemExit("Shutdown requested before RMQ connection established")


def publish_raw(channel, queue_name: str, message: dict) -> None:
    """Publish a JSON-serializable message as persistent to the given queue."""
    # Relax publisher confirms in local/dev to avoid spurious failures
    payload = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    props = pika.BasicProperties(content_type="application/json", delivery_mode=2)
    channel.basic_publish(exchange="", routing_key=queue_name, body=payload, properties=props, mandatory=False)


def connect_db(cfg) -> psycopg2.extensions.connection:
    """Open a PostgreSQL connection for job metadata operations (autocommit)."""
    conn = psycopg2.connect(
        host=cfg["DB_HOST"],
        port=cfg["DB_PORT"],
        dbname=cfg["DB_NAME"],
        user=cfg["DB_USER"],
        password=cfg["DB_PASSWORD"],
    )
    conn.autocommit = True
    return conn


def dispatch_provider(job: dict, cfg: Dict[str, Any]) -> Iterable[dict]:
    """Dispatch a backfill job to the provider implementation and return its iterator.

    Raises:
        ValueError: If the job is missing required fields or provider unknown.
    """
    provider = (job.get("provider") or "").lower().strip()
    ticker = (job.get("ticker") or "").upper().strip()
    start_date = job.get("start_date")
    end_date = job.get("end_date")
    interval = job.get("interval") or cfg["BACKFILL_INTERVAL"]

    if not ticker or not provider or not start_date or not end_date:
        raise ValueError("Invalid job: ticker/provider/start_date/end_date required")

    # Provider registry
    providers: Dict[str, Callable[..., Iterable[dict]]] = {
        "yfinance": fetch_yfinance,
        "alpaca": fetch_alpaca,
    }

    fn = providers.get(provider)
    if not fn:
        raise ValueError(f"Unknown provider: {provider}")

    return fn(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        interval=interval,
        chunk_months=cfg["CHUNK_MONTHS"],
        sleep_between_chunks_s=cfg["SLEEP_BETWEEN_CHUNKS_SECONDS"],
    )


def process_job(cfg: Dict[str, Any], channel, method, properties, body: bytes) -> None:
    """Process a single job message: resolve sub-job or legacy job, stream records, and update status."""
    global db_conn
    try:
        try:
            body_str = body.decode("utf-8")
        except UnicodeDecodeError:
            body_str = body.decode("utf-8", errors="replace")
        msg = json.loads(body_str)

        # Ensure DB connection
        if db_conn is None or getattr(db_conn, "closed", 1):
            logger.info("(Re)connecting to DB...")
            db_conn = connect_db(cfg)

        def _wait_for_persistence(ticker: str, start_date_str: str, end_date_str: str, timeout_s: float = 10.0) -> None:
            """Wait until storage-service has persisted expected daily rows (inclusive).

            Only applied when BACKFILL_INTERVAL is daily or ticker starts with 'TEST.'
            """
            try:
                with db_conn.cursor() as curp:
                    start_dt = datetime.fromisoformat(start_date_str + "T00:00:00+00:00")
                    end_dt = datetime.fromisoformat(end_date_str + "T00:00:00+00:00")
                    expected = int((end_dt - start_dt).days) + 1
                    if expected <= 0:
                        return
                    deadline = time.time() + timeout_s
                    while time.time() < deadline:
                        curp.execute(
                            "SELECT COUNT(*) FROM financial_data WHERE ticker=%s AND \"timestamp\">=%s AND \"timestamp\"<%s",
                            (ticker, start_dt, end_dt + timedelta(days=1)),
                        )
                        cnt = curp.fetchone()[0]
                        if cnt >= expected:
                            return
                        time.sleep(0.2)
            except Exception:
                # Best-effort; do not fail the job
                pass

        cur = db_conn.cursor()
        try:
            records_published = 0
            
            # Check if this is a new-style sub-job or legacy job
            if isinstance(msg, dict) and "sub_job_id" in msg:
                # New architecture: sub-job processing
                sub_job_id = msg["sub_job_id"]
                logger.info("Processing sub-job sub_job_id=%s", sub_job_id)
                
                # Fetch sub-job details
                cur.execute(
                    "SELECT id, master_job_id, ticker, provider, start_date, end_date FROM sub_backfill_jobs WHERE id = %s",
                    (sub_job_id,),
                )
                row = cur.fetchone()
                if not row:
                    logger.error("Sub-job id not found in DB: %s", sub_job_id)
                    try:
                        cur.execute(
                            "UPDATE sub_backfill_jobs SET status='FAILED', completed_at=NOW(), error_message=%s WHERE id=%s",
                            ("Sub-job not found", sub_job_id),
                        )
                    except Exception:
                        pass
                    channel.basic_ack(delivery_tag=method.delivery_tag)
                    return

                sub_id, master_job_id, ticker, provider, start_date, end_date = row
                
                # Determine providers to try (primary + fallbacks)
                providers_to_try = []
                primary_provider = msg.get("primary_provider")
                fallback_providers = msg.get("fallback_providers") or []
                if primary_provider:
                    providers_to_try = [str(primary_provider).lower()] + [str(p).lower() for p in fallback_providers if p]
                else:
                    providers_to_try = [str(provider).lower()]
                
                # Mark sub-job as RUNNING
                cur.execute(
                    "UPDATE sub_backfill_jobs SET status='RUNNING', started_at=NOW() WHERE id = %s",
                    (sub_job_id,),
                )
                
                success = False
                last_error = None
                total_published_any = 0
                
                for prov in providers_to_try:
                    # Build job for this attempt
                    job = {
                        "ticker": ticker,
                        "provider": prov,
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                    }
                    
                    # Bump total_requests and last_seen_active for this provider
                    try:
                        with db_conn.cursor() as currep:
                            currep.execute(
                                """
                                INSERT INTO provider_reputation (provider_name, total_requests, last_seen_active)
                                VALUES (%s, 1, NOW())
                                ON CONFLICT (provider_name) DO UPDATE SET
                                    total_requests = provider_reputation.total_requests + 1,
                                    last_seen_active = NOW()
                                """,
                                (prov,)
                            )
                    except Exception:
                        logger.exception("Failed to bump total_requests for provider=%s", prov)
                    
                    records_this_attempt = 0
                    try:
                        for record in dispatch_provider(job, cfg):
                            # Ensure provider metadata is present
                            try:
                                md = record.setdefault("metadata", {})
                                if not md.get("provider"):
                                    md["provider"] = prov
                            except Exception:
                                pass
                            publish_raw(channel, cfg["RAW_QUEUE_NAME"], record)
                            records_published += 1
                            records_this_attempt += 1
                        # Success for this provider
                        total_published_any += records_this_attempt
                        try:
                            with db_conn.cursor() as currep2:
                                currep2.execute(
                                    """
                                    INSERT INTO provider_reputation (provider_name, successful_requests, total_records_published, last_seen_active)
                                    VALUES (%s, 1, %s, NOW())
                                    ON CONFLICT (provider_name) DO UPDATE SET
                                        successful_requests = provider_reputation.successful_requests + 1,
                                        total_records_published = provider_reputation.total_records_published + EXCLUDED.total_records_published,
                                        last_seen_active = NOW()
                                    """,
                                    (prov, records_this_attempt)
                                )
                        except Exception:
                            logger.exception("Failed to bump success metrics for provider=%s", prov)
                        success = True
                        break
                    except Exception as e_attempt:
                        last_error = str(e_attempt)
                        logger.exception("Provider attempt failed for provider=%s sub_job_id=%s", prov, sub_job_id)
                        # Bump failed_requests
                        try:
                            with db_conn.cursor() as currep3:
                                currep3.execute(
                                    """
                                    INSERT INTO provider_reputation (provider_name, failed_requests, last_seen_active)
                                    VALUES (%s, 1, NOW())
                                    ON CONFLICT (provider_name) DO UPDATE SET
                                        failed_requests = provider_reputation.failed_requests + 1,
                                        last_seen_active = NOW()
                                    """,
                                    (prov,)
                                )
                        except Exception:
                            logger.exception("Failed to bump failed_requests for provider=%s", prov)
                        # Try next fallback provider
                        continue
                
                if not success:
                    # All providers failed
                    try:
                        cur.execute(
                            "UPDATE sub_backfill_jobs SET status='FAILED', completed_at=NOW(), error_message=%s WHERE id = %s",
                            (last_error or "All providers failed", sub_job_id),
                        )
                    except Exception:
                        logger.exception("Failed to set sub-job FAILED for sub_job_id=%s", sub_job_id)
                    channel.basic_ack(delivery_tag=method.delivery_tag)
                    return
                
                # Wait for persistence if applicable
                try:
                    if job.get("ticker") and (cfg.get("BACKFILL_INTERVAL") == "1d" or str(job.get("ticker")).upper().startswith("TEST.")):
                        _wait_for_persistence(job["ticker"], job["start_date"], job["end_date"], timeout_s=10.0)
                except Exception:
                    pass

                # Mark sub-job as COMPLETED with record count
                try:
                    cur.execute(
                        "UPDATE sub_backfill_jobs SET status='COMPLETED', completed_at=NOW(), error_message=NULL, records_published=%s WHERE id = %s",
                        (records_published, sub_job_id),
                    )
                    
                    # Check if master job should be marked as completed
                    # (when all sub-jobs are in COMPLETED or FAILED state)
                    cur.execute(
                        "SELECT COUNT(*) as total, " 
                        "SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) as completed, "
                        "SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) as failed "
                        "FROM sub_backfill_jobs WHERE master_job_id = %s",
                        (master_job_id,)
                    )
                    summary = cur.fetchone()
                    if summary:
                        total, completed, failed = summary
                        if (completed + failed) == total:
                            # All sub-jobs are done
                            if failed == 0:
                                # All completed successfully
                                cur.execute(
                                    "UPDATE master_backfill_jobs SET status='COMPLETED', completed_at=NOW() WHERE id = %s",
                                    (master_job_id,)
                                )
                            else:
                                # Some failed
                                cur.execute(
                                    "UPDATE master_backfill_jobs SET status='PARTIALLY_COMPLETED', completed_at=NOW(), "
                                    "error_message=%s WHERE id = %s",
                                    (f"{failed} of {total} sub-jobs failed", master_job_id)
                                )
                        elif completed > 0 or failed > 0:
                            # Some sub-jobs have started/finished, mark master as running
                            cur.execute(
                                "UPDATE master_backfill_jobs SET status='RUNNING', started_at=COALESCE(started_at, NOW()) WHERE id = %s",
                                (master_job_id,)
                            )
                            
                except Exception:
                    logger.exception("Failed to update sub-job COMPLETED for sub_job_id=%s", sub_job_id)

                channel.basic_ack(delivery_tag=method.delivery_tag)
                logger.info("Sub-job completed: sub_job_id=%s, records_published=%d", sub_job_id, records_published)
                
            elif isinstance(msg, dict) and "job_id" in msg:
                # Legacy architecture: master job processing (for backwards compatibility)
                job_id = msg["job_id"]
                logger.info("Processing legacy backfill job_id=%s", job_id)
                
                # Check first in master_backfill_jobs, then fall back to legacy tables if they exist
                cur.execute(
                    "SELECT ticker, provider, start_date, end_date FROM master_backfill_jobs WHERE id = %s",
                    (job_id,),
                )
                row = cur.fetchone()
                
                if not row:
                    # Try legacy backfill_jobs table if it still exists
                    try:
                        cur.execute(
                            "SELECT ticker, provider, start_date, end_date FROM backfill_jobs WHERE id = %s",
                            (job_id,),
                        )
                        row = cur.fetchone()
                        if row:
                            # Update legacy table
                            ticker, provider, start_date, end_date = row
                            cur.execute(
                                "UPDATE backfill_jobs SET status='RUNNING', started_at=NOW() WHERE id = %s",
                                (job_id,),
                            )
                    except Exception:
                        # Legacy table doesn't exist, that's ok
                        pass
                
                if not row:
                    logger.error("Job id not found in any table: %s", job_id)
                    try:
                        cur.execute(
                            "UPDATE master_backfill_jobs SET status='FAILED', completed_at=NOW(), error_message=%s WHERE id=%s",
                            ("Job not found", job_id),
                        )
                    except Exception:
                        pass
                    channel.basic_ack(delivery_tag=method.delivery_tag)
                    return

                ticker, provider, start_date, end_date = row
                
                # Mark as RUNNING
                cur.execute(
                    "UPDATE master_backfill_jobs SET status='RUNNING', started_at=NOW() WHERE id = %s",
                    (job_id,),
                )
                
                job = {
                    "ticker": ticker,
                    "provider": provider,
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                }
                
                for record in dispatch_provider(job, cfg):
                    publish_raw(channel, cfg["RAW_QUEUE_NAME"], record)
                    records_published += 1

                # For daily backfills or test tickers, wait briefly until rows are visible
                try:
                    if job.get("ticker") and (cfg.get("BACKFILL_INTERVAL") == "1d" or str(job.get("ticker")).upper().startswith("TEST.")):
                        _wait_for_persistence(job["ticker"], job["start_date"], job["end_date"], timeout_s=10.0)
                except Exception:
                    pass

                try:
                    cur.execute(
                        "UPDATE master_backfill_jobs SET status='COMPLETED', completed_at=NOW(), error_message=NULL WHERE id = %s",
                        (job_id,),
                    )
                except Exception:
                    logger.exception("Failed to update job COMPLETED for job_id=%s", job_id)

                channel.basic_ack(delivery_tag=method.delivery_tag)
                logger.info("Legacy job completed: job_id=%s, records_published=%d", job_id, records_published)
                
            else:
                # Very old format carried full job payload
                job = msg
                logger.info("Processing very legacy backfill job payload: %s", body_str)
                
                for record in dispatch_provider(job, cfg):
                    publish_raw(channel, cfg["RAW_QUEUE_NAME"], record)
                    records_published += 1

                channel.basic_ack(delivery_tag=method.delivery_tag)
                logger.info("Very legacy job completed: ticker=%s provider=%s, records_published=%d", 
                          job.get('ticker'), job.get('provider'), records_published)
                
        finally:
            try:
                cur.close()
            except Exception:
                pass

    except (ChannelClosedByBroker, StreamLostError, AMQPConnectionError) as e:
        logger.error("Channel/connection error during job: %s", str(e))
        try:
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        except Exception:
            pass
        raise
    except Exception as e:
        logger.exception("Job failed: %s", str(e))
        # Try to mark FAILED if we have a job id in the body
        try:
            if isinstance(msg, dict):
                err = str(e)
                if db_conn is None or getattr(db_conn, "closed", 1):
                    db_conn = connect_db(cfg)
                    
                with db_conn.cursor() as cur2:
                    if "sub_job_id" in msg:
                        # Failed sub-job
                        cur2.execute(
                            "UPDATE sub_backfill_jobs SET status='FAILED', completed_at=NOW(), error_message=%s WHERE id = %s",
                            (err[:1000], msg["sub_job_id"]),
                        )
                    elif "job_id" in msg:
                        # Failed master job or legacy job
                        cur2.execute(
                            "UPDATE master_backfill_jobs SET status='FAILED', completed_at=NOW(), error_message=%s WHERE id = %s",
                            (err[:1000], msg["job_id"]),
                        )
        except Exception:
            logger.exception("Failed to update job FAILED state")
        # Acknowledge to avoid infinite requeue loops on logical failures
        try:
            channel.basic_ack(delivery_tag=method.delivery_tag)
        except Exception:
            pass


def run():
    """Worker entrypoint: maintain RMQ consumption and DB connection lifecycle."""
    global db_conn
    cfg = load_config()

    def _handle_signal(signum, frame):
        logger.info("Received signal %s. Stopping...", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # Establish DB connection with retry
    attempt = 0
    while not stop_event.is_set():
        attempt += 1
        try:
            logger.info("Connecting to DB attempt %s...", attempt)
            db_conn = connect_db(cfg)
            logger.info("Connected to DB %s:%s/%s", cfg["DB_HOST"], cfg["DB_PORT"], cfg["DB_NAME"])
            break
        except Exception as e:
            backoff = min(60, (2 ** min(attempt, 6))) + random.uniform(0, 1)
            logger.error("DB connection failed: %s (retry in %.1fs)", str(e), backoff)
            stop_event.wait(backoff)

    if db_conn is None:
        logger.error("Could not connect to DB; exiting")
        return

    while not stop_event.is_set():
        conn = None
        ch = None
        try:
            conn, ch = connect_rabbit(cfg)
            def _cb(channel, method, properties, body):
                return process_job(cfg, channel, method, properties, body)
            ch.basic_consume(queue=cfg["BACKFILL_JOBS_QUEUE"], on_message_callback=_cb, auto_ack=False)
            logger.info("Waiting for backfill jobs on %s... (prefetch=%s)", cfg["BACKFILL_JOBS_QUEUE"], cfg["PREFETCH_COUNT"]) 
            ch.start_consuming()
        except SystemExit:
            logger.info("SystemExit; stopping run loop")
            break
        except Exception as e:
            if stop_event.is_set():
                break
            backoff = min(60, (2 ** 3)) + random.uniform(0, 1)
            logger.error("Worker loop error: %s (reconnect in %.1fs)", str(e), backoff)
            stop_event.wait(backoff)
        finally:
            try:
                if ch and ch.is_open:
                    try:
                        ch.stop_consuming()
                    except Exception:
                        pass
                    ch.close()
            except Exception:
                pass
            try:
                if conn and conn.is_open:
                    conn.close()
            except Exception:
                pass

    try:
        if db_conn and getattr(db_conn, "closed", 0) == 0:
            db_conn.close()
    except Exception:
        pass

    logger.info("Backfill worker shut down cleanly.")


if __name__ == "__main__":
    try:
        logger.info("Starting FinBase Backfill Worker...")
        run()
    except SystemExit as e:
        logger.info("Exiting: %s", str(e))
        sys.exit(0)
    except Exception as e:
        logger.exception("Fatal error: %s", str(e))
        sys.exit(1)

