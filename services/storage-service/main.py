#!/usr/bin/env python3
"""
FinBase Storage Service

Consumes validated messages from clean_data_queue and persists them into
TimescaleDB (PostgreSQL) using efficient batch inserts with idempotency.

Features:
- RabbitMQ consumer with manual acks
- Batch buffer with size/time triggers (BATCH_SIZE, BATCH_TIMEOUT_SECONDS)
- Idempotent upsert via ON CONFLICT (timestamp, ticker) DO UPDATE
- Robust reconnection to RabbitMQ and DB with backoff
- Graceful shutdown (SIGTERM/SIGINT)
"""
from __future__ import annotations

import json
import logging
import os
import random
import signal
import sys
import time
from threading import Event
from typing import Any, Dict, List, Tuple

import pika
from pika.exceptions import AMQPConnectionError, ChannelClosedByBroker, StreamLostError
from dotenv import load_dotenv
import psycopg2
import psycopg2.extras

# Structured UTC logging
logging.Formatter.converter = time.gmtime
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)sZ %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("storage-service")

stop_event = Event()


# ----------------------
# Config
# ----------------------

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
    cfg["INPUT_QUEUE"] = os.getenv("INPUT_QUEUE", "clean_data_queue")
    cfg["PREFETCH_COUNT"] = int(os.getenv("PREFETCH_COUNT", os.getenv("BATCH_SIZE", "1000")))

    # DB
    cfg["DB_HOST"] = os.getenv("DB_HOST", "finbase-db")
    cfg["DB_PORT"] = int(os.getenv("DB_PORT", "5432"))
    cfg["DB_NAME"] = os.getenv("DB_NAME", "finbase")
    cfg["DB_USER"] = os.getenv("DB_USER", "finbase")
    cfg["DB_PASSWORD"] = os.getenv("DB_PASSWORD", "supersecretpassword")

    # Batching
    cfg["BATCH_SIZE"] = int(os.getenv("BATCH_SIZE", "1000"))
    cfg["BATCH_TIMEOUT_SECONDS"] = float(os.getenv("BATCH_TIMEOUT_SECONDS", "1"))

    # Retry policy
    cfg["MAX_CONNECTION_ATTEMPTS"] = int(os.getenv("MAX_CONNECTION_ATTEMPTS", "0"))  # 0 => unlimited

    logger.info(
        "Config: in_queue=%s batch=%s timeout=%ss prefetch=%s db=%s@%s:%s/%s",
        cfg["INPUT_QUEUE"], cfg["BATCH_SIZE"], cfg["BATCH_TIMEOUT_SECONDS"], cfg["PREFETCH_COUNT"],
        cfg["DB_USER"], cfg["DB_HOST"], cfg["DB_PORT"], cfg["DB_NAME"],
    )
    return cfg


# ----------------------
# Connections
# ----------------------

def connect_rabbitmq(cfg) -> Tuple[pika.BlockingConnection, pika.adapters.blocking_connection.BlockingChannel]:
    credentials = pika.PlainCredentials(cfg["RABBITMQ_USER"], cfg["RABBITMQ_PASSWORD"])
    parameters = pika.ConnectionParameters(
        host=cfg["RABBITMQ_HOST"],
        port=cfg["RABBITMQ_PORT"],
        credentials=credentials,
        heartbeat=cfg["RABBITMQ_HEARTBEAT"],
        blocked_connection_timeout=cfg["RABBITMQ_BLOCKED_TIMEOUT"],
        connection_attempts=1,
        retry_delay=0,
        client_properties={"connection_name": "storage-service"},
    )

    attempt = 0
    max_attempts = cfg["MAX_CONNECTION_ATTEMPTS"]
    while not stop_event.is_set():
        attempt += 1
        try:
            logger.info("Connecting to RabbitMQ (%s:%s) attempt %s...", cfg["RABBITMQ_HOST"], cfg["RABBITMQ_PORT"], attempt)
            connection = pika.BlockingConnection(parameters)
            channel = connection.channel()
            channel.queue_declare(queue=cfg["INPUT_QUEUE"], durable=True)
            channel.basic_qos(prefetch_count=cfg["PREFETCH_COUNT"])
            logger.info("RabbitMQ connected and queue ensured: %s", cfg["INPUT_QUEUE"])
            return connection, channel
        except AMQPConnectionError as e:
            backoff = min(60, (2 ** min(attempt, 6))) + random.uniform(0, 1)
            logger.error("RabbitMQ connection failed: %s (retrying %.1fs)", str(e), backoff)
            stop_event.wait(backoff)
        except Exception as e:
            backoff = min(60, (2 ** min(attempt, 6))) + random.uniform(0, 1)
            logger.exception("Unexpected error connecting to RabbitMQ: %s (retrying %.1fs)", str(e), backoff)
            stop_event.wait(backoff)
        if max_attempts > 0 and attempt >= max_attempts:
            raise SystemExit("Max RabbitMQ connection attempts exceeded")
    raise SystemExit("Shutdown requested before RabbitMQ connection established")


def connect_db(cfg) -> psycopg2.extensions.connection:
    attempt = 0
    max_attempts = cfg["MAX_CONNECTION_ATTEMPTS"]
    while not stop_event.is_set():
        attempt += 1
        try:
            logger.info("Connecting to DB %s@%s:%s/%s (attempt %s)...", cfg["DB_USER"], cfg["DB_HOST"], cfg["DB_PORT"], cfg["DB_NAME"], attempt)
            conn = psycopg2.connect(
                host=cfg["DB_HOST"],
                port=cfg["DB_PORT"],
                dbname=cfg["DB_NAME"],
                user=cfg["DB_USER"],
                password=cfg["DB_PASSWORD"],
                connect_timeout=10,
            )
            conn.autocommit = False
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            logger.info("DB connection ready")
            return conn
        except Exception as e:
            backoff = min(60, (2 ** min(attempt, 6))) + random.uniform(0, 1)
            logger.error("DB connection failed: %s (retrying %.1fs)", str(e), backoff)
            stop_event.wait(backoff)
        if max_attempts > 0 and attempt >= max_attempts:
            raise SystemExit("Max DB connection attempts exceeded")
    raise SystemExit("Shutdown requested before DB connection established")


# ----------------------
# Batch Insert Logic
# ----------------------

def build_row(record: Dict[str, Any]) -> Tuple[Any, ...]:
    """Map canonical JSON record to DB row tuple.
    Returns a tuple: (timestamp, ticker, open, high, low, close, volume, source)
    """
    ts = record.get("timestamp_utc")
    ticker = record.get("ticker_symbol")
    o = record.get("open")
    h = record.get("high")
    l = record.get("low")
    c = record.get("close")
    v = record.get("volume")
    meta = record.get("metadata") or {}
    source = meta.get("source") if isinstance(meta, dict) else None
    if ts is None or ticker is None:
        raise ValueError("Missing timestamp_utc or ticker_symbol")
    return (ts, ticker, o, h, l, c, v, source)


def flush_batch(cfg, db_conn, channel, deliveries: List[Tuple[int, bytes]]) -> None:
    """Insert buffered records into DB and ack messages on success.

    deliveries: list of (delivery_tag, body_bytes)
    """
    if not deliveries:
        return

    parsed: List[Tuple[Any, ...]] = []
    ok_indices: List[int] = []
    # Parse messages and build rows, but don't ack yet
    for idx, (tag, body) in enumerate(deliveries):
        try:
            payload = json.loads(body.decode("utf-8"))
            row = build_row(payload)
            parsed.append(row)
            ok_indices.append(idx)
        except Exception as e:
            # Poison/invalid in clean queue shouldn't happen; log and ack to prevent blocking
            logger.error("Dropping invalid message at batch index %s: %s", idx, str(e))
            try:
                channel.basic_ack(delivery_tag=tag)
            except Exception:
                pass

    if not parsed:
        return

    # Deduplicate by primary key (timestamp, ticker) within the batch to avoid
    # PostgreSQL error: "ON CONFLICT DO UPDATE command cannot affect row a second time".
    # Keep the last occurrence for each key (last message wins).
    dedup_map: Dict[Tuple[Any, Any], Tuple[Any, ...]] = {}
    for row in parsed:
        ts, ticker = row[0], row[1]
        dedup_map[(ts, ticker)] = row
    rows: List[Tuple[Any, ...]] = list(dedup_map.values())

    sql = (
        "INSERT INTO financial_data (\"timestamp\", ticker, \"open\", \"high\", \"low\", \"close\", volume, source) "
        "VALUES %s "
        "ON CONFLICT (\"timestamp\", ticker) DO UPDATE SET "
        "\"open\" = EXCLUDED.\"open\", "
        "\"high\" = EXCLUDED.\"high\", "
        "\"low\" = EXCLUDED.\"low\", "
        "\"close\" = EXCLUDED.\"close\", "
        "volume = EXCLUDED.volume, "
        "source = EXCLUDED.source"
    )

    try:
        with db_conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                sql,
                rows,
                page_size=min(len(rows), max(100, cfg["BATCH_SIZE"]))
            )
        db_conn.commit()
        # Ack only after successful commit
        for idx in ok_indices:
            tag = deliveries[idx][0]
            channel.basic_ack(delivery_tag=tag)
        logger.info("Flushed %d records to DB (acked=%d, deduped_from=%d)", len(rows), len(ok_indices), len(parsed))
    except Exception as e:
        try:
            db_conn.rollback()
        except Exception:
            pass
        logger.exception("DB insert failed for batch of %d (after dedup from %d): %s", len(rows), len(parsed), str(e))
        # Raise to outer loop so connection resets and messages get requeued when channel/connection closes
        raise


# ----------------------
# Runner
# ----------------------

def run():
    cfg = load_config()

    def _handle_signal(signum, frame):
        logger.info("Received signal %s. Stopping...", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    while not stop_event.is_set():
        rmq_conn = None
        channel = None
        db_conn = None
        deliveries: List[Tuple[int, bytes]] = []  # (delivery_tag, body)
        last_flush = time.monotonic()
        try:
            rmq_conn, channel = connect_rabbitmq(cfg)
            db_conn = connect_db(cfg)

            # Use generator consumption with inactivity timeout for periodic flush
            consumer = channel.consume(queue=cfg["INPUT_QUEUE"], inactivity_timeout=0.25, auto_ack=False)

            while not stop_event.is_set():
                item = next(consumer)
                now = time.monotonic()

                if item is None:
                    # timeout tick: check time-based flush
                    if deliveries and (now - last_flush >= cfg["BATCH_TIMEOUT_SECONDS"]):
                        flush_batch(cfg, db_conn, channel, deliveries)
                        deliveries.clear()
                        last_flush = now
                    continue

                method, properties, body = item
                
                # Validate that method is not None (can happen with corrupted messages)
                if method is None or not hasattr(method, 'delivery_tag'):
                    logger.warning("Received invalid message with None method, skipping...")
                    continue
                    
                deliveries.append((method.delivery_tag, body))

                # Size-based flush
                if len(deliveries) >= cfg["BATCH_SIZE"]:
                    flush_batch(cfg, db_conn, channel, deliveries)
                    deliveries.clear()
                    last_flush = now

                # Time-based flush safeguard
                elif now - last_flush >= cfg["BATCH_TIMEOUT_SECONDS"]:
                    flush_batch(cfg, db_conn, channel, deliveries)
                    deliveries.clear()
                    last_flush = now

            # Final flush on shutdown
            if deliveries:
                flush_batch(cfg, db_conn, channel, deliveries)
                deliveries.clear()

        except SystemExit:
            logger.info("SystemExit received, exiting run loop.")
            break
        except (ChannelClosedByBroker, StreamLostError, AMQPConnectionError) as e:
            logger.error("RabbitMQ error: %s. Will reconnect...", str(e))
            # On channel close, unacked messages are requeued by broker
            time.sleep(1.0)
        except Exception as e:
            logger.exception("Unexpected error in main loop: %s", str(e))
            # Let connections reset; unacked messages will be requeued
            time.sleep(1.0)
        finally:
            # Close channel/connection to requeue any unacked and release resources
            try:
                if channel and channel.is_open:
                    try:
                        channel.stop_consuming()
                    except Exception:
                        pass
                    channel.close()
            except Exception:
                pass
            try:
                if rmq_conn and rmq_conn.is_open:
                    rmq_conn.close()
            except Exception:
                pass
            try:
                if db_conn:
                    db_conn.close()
            except Exception:
                pass

    logger.info("Storage service shut down cleanly.")


if __name__ == "__main__":
    try:
        logger.info("Starting FinBase Storage Service...")
        run()
    except SystemExit as e:
        logger.info("Exiting: %s", str(e))
        sys.exit(0)
    except Exception as e:
        logger.exception("Fatal error: %s", str(e))
        sys.exit(1)

