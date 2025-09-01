#!/usr/bin/env python3
"""
Backfill Worker Service

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
from datetime import datetime
from threading import Event
from typing import Any, Callable, Dict, Iterable, Tuple

import pika
from pika.exceptions import AMQPConnectionError, ChannelClosedByBroker, StreamLostError
from dotenv import load_dotenv

# Providers
from providers.yfinance_provider import fetch_yfinance

# Logging (UTC ISO timestamps)
logging.Formatter.converter = time.gmtime
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)sZ %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("backfill-worker")

stop_event = Event()


def load_config() -> Dict[str, Any]:
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

    logger.info(
        "Config: jobs_queue=%s raw_queue=%s rmq=%s:%s prefetch=%s interval=%s chunk_months=%s",
        cfg["BACKFILL_JOBS_QUEUE"], cfg["RAW_QUEUE_NAME"], cfg["RABBITMQ_HOST"], cfg["RABBITMQ_PORT"],
        cfg["PREFETCH_COUNT"], cfg["BACKFILL_INTERVAL"], cfg["CHUNK_MONTHS"],
    )
    return cfg


def connect_rabbit(cfg) -> Tuple[pika.BlockingConnection, pika.adapters.blocking_connection.BlockingChannel]:
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
    # Relax publisher confirms in local/dev to avoid spurious failures
    payload = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    props = pika.BasicProperties(content_type="application/json", delivery_mode=2)
    channel.basic_publish(exchange="", routing_key=queue_name, body=payload, properties=props, mandatory=False)


def dispatch_provider(job: dict, cfg: Dict[str, Any]) -> Iterable[dict]:
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
    try:
        try:
            body_str = body.decode("utf-8")
        except UnicodeDecodeError:
            body_str = body.decode("utf-8", errors="replace")
        job = json.loads(body_str)
        logger.info("Processing backfill job: %s", body_str)

        for record in dispatch_provider(job, cfg):
            publish_raw(channel, cfg["RAW_QUEUE_NAME"], record)
        channel.basic_ack(delivery_tag=method.delivery_tag)
        logger.info("Job completed: ticker=%s provider=%s", job.get("ticker"), job.get("provider"))
    except (ChannelClosedByBroker, StreamLostError, AMQPConnectionError) as e:
        logger.error("Channel/connection error during job: %s", str(e))
        try:
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        except Exception:
            pass
        raise
    except Exception as e:
        logger.exception("Job failed; nack+requeue: %s", str(e))
        try:
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        except Exception:
            pass


def run():
    cfg = load_config()

    def _handle_signal(signum, frame):
        logger.info("Received signal %s. Stopping...", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    while not stop_event.is_set():
        conn = None
        ch = None
        try:
            conn, ch = connect_rabbit(cfg)
            def _cb(channel, method, properties, body):
                return process_job(cfg, channel, method, properties, body)
            ch.basic_consume(queue=cfg["BACKFILL_JOBS_QUEUE"], on_message_callback=_cb, auto_ack=False)
            logger.info("Waiting for backfill jobs on %s...", cfg["BACKFILL_JOBS_QUEUE"])
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

