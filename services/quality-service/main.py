#!/usr/bin/env python3
"""
FinBase Quality Service.

Consumes messages from raw_data_queue, validates payloads against business rules,
and routes them to clean_data_queue (valid) or invalid_data_queue (invalid).

Reliability features:
- Durable queues, persistent messages
- Publisher confirms with ack-after-publish semantics
- Manual acknowledgments and requeue on failures
- Exponential backoff reconnects
- Graceful shutdown on SIGTERM/SIGINT
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
from typing import Optional, Tuple

import pika
from pika.exceptions import AMQPConnectionError, ChannelClosedByBroker, StreamLostError
from dotenv import load_dotenv
import psycopg2

from rules import validate_data

# Structured UTC logging
logging.Formatter.converter = time.gmtime
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)sZ %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("quality-service")

stop_event = Event()

# Global DB connection
_db_conn = None


def load_config():
    """Load configuration from environment with sensible defaults."""
    load_dotenv()
    cfg = {}

    # RabbitMQ connection
    cfg["RABBITMQ_HOST"] = os.getenv("RABBITMQ_HOST", "localhost")
    cfg["RABBITMQ_PORT"] = int(os.getenv("RABBITMQ_PORT", "5672"))
    cfg["RABBITMQ_USER"] = os.getenv("RABBITMQ_USER", "guest")
    cfg["RABBITMQ_PASSWORD"] = os.getenv("RABBITMQ_PASSWORD", "guest")
    cfg["RABBITMQ_HEARTBEAT"] = int(os.getenv("RABBITMQ_HEARTBEAT", "30"))
    cfg["RABBITMQ_BLOCKED_TIMEOUT"] = int(os.getenv("RABBITMQ_BLOCKED_TIMEOUT", "60"))

    # Queues
    cfg["INPUT_QUEUE"] = os.getenv("INPUT_QUEUE", "raw_data_queue")
    cfg["VALID_QUEUE"] = os.getenv("VALID_QUEUE", "clean_data_queue")
    cfg["INVALID_QUEUE"] = os.getenv("INVALID_QUEUE", "invalid_data_queue") # TEMPORAL. Hay que dar tratamiento a la cola de datos inválidos.

    # Consumer tuning
    cfg["PREFETCH_COUNT"] = int(os.getenv("PREFETCH_COUNT", "50"))

    # Retry policy
    cfg["MAX_CONNECTION_ATTEMPTS"] = int(os.getenv("MAX_CONNECTION_ATTEMPTS", "0"))  # 0 => unlimited

    logger.info(
        "Config: host=%s port=%s in=%s out_valid=%s out_invalid=%s prefetch=%s",
        cfg["RABBITMQ_HOST"],
        cfg["RABBITMQ_PORT"],
        cfg["INPUT_QUEUE"],
        cfg["VALID_QUEUE"],
        cfg["INVALID_QUEUE"],
        cfg["PREFETCH_COUNT"],
    )
    return cfg


def connect_rabbitmq(cfg) -> Tuple[pika.BlockingConnection, pika.adapters.blocking_connection.BlockingChannel]:
    """Establish RabbitMQ connection and channel with retry/backoff.

    Declares required queues (durable) and enables publisher confirms and QoS.
    """
    credentials = pika.PlainCredentials(cfg["RABBITMQ_USER"], cfg["RABBITMQ_PASSWORD"])
    parameters = pika.ConnectionParameters(
        host=cfg["RABBITMQ_HOST"],
        port=cfg["RABBITMQ_PORT"],
        credentials=credentials,
        heartbeat=cfg["RABBITMQ_HEARTBEAT"],
        blocked_connection_timeout=cfg["RABBITMQ_BLOCKED_TIMEOUT"],
        connection_attempts=1,  # manual backoff retry loop
        retry_delay=0,
        client_properties={"connection_name": "quality-service"},
    )

    attempt = 0
    max_attempts = cfg["MAX_CONNECTION_ATTEMPTS"]
    logger.info(
        "Connecting to RabbitMQ (max_attempts=%s)...",
        max_attempts if max_attempts > 0 else "unlimited",
    )

    while not stop_event.is_set():
        attempt += 1
        try:
            logger.info(
                "RabbitMQ connect attempt %s to %s:%s",
                attempt,
                cfg["RABBITMQ_HOST"],
                cfg["RABBITMQ_PORT"],
            )
            connection = pika.BlockingConnection(parameters)
            channel = connection.channel()

            # Ensure queues (durable)
            channel.queue_declare(queue=cfg["INPUT_QUEUE"], durable=True)
            channel.queue_declare(queue=cfg["VALID_QUEUE"], durable=True)
            channel.queue_declare(queue=cfg["INVALID_QUEUE"], durable=True)

            # Enable publisher confirms and tune prefetch
            channel.confirm_delivery()
            channel.basic_qos(prefetch_count=cfg["PREFETCH_COUNT"])

            logger.info(
                "Connected and queues ready: in=%s, valid=%s, invalid=%s",
                cfg["INPUT_QUEUE"], cfg["VALID_QUEUE"], cfg["INVALID_QUEUE"]
            )
            return connection, channel
        except AMQPConnectionError as e:
            backoff = min(60, (2 ** min(attempt, 6))) + random.uniform(0, 1)
            logger.error("RabbitMQ connection failed: %s (retrying in %.1fs)", str(e), backoff)
            stop_event.wait(backoff)
        except Exception as e:
            backoff = min(60, (2 ** min(attempt, 6))) + random.uniform(0, 1)
            logger.exception("Unexpected connection error: %s (retrying in %.1fs)", str(e), backoff)
            stop_event.wait(backoff)

        if max_attempts > 0 and attempt >= max_attempts:
            raise SystemExit(f"Max connection attempts ({max_attempts}) exceeded.")

    raise SystemExit("Shutdown requested before RabbitMQ connection established.")


def publish_raw(channel, queue_name: str, body: bytes) -> None:
    """Publish raw bytes (original message) with persistence. Relax confirms in test env."""
    properties = pika.BasicProperties(
        content_type="application/json",
        delivery_mode=2,  # persistent
    )
    channel.basic_publish(
        exchange="",
        routing_key=queue_name,
        body=body,
        properties=properties,
        mandatory=False,
    )


def publish_json(channel, queue_name: str, message: dict) -> None:
    """Publish a JSON object using compact encoding, persistent."""
    payload = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    publish_raw(channel, queue_name, payload)


def _connect_db() -> psycopg2.extensions.connection:
    host = os.getenv("DB_HOST", "localhost")
    port = int(os.getenv("DB_PORT", "5432"))
    db = os.getenv("DB_NAME", "finbase")
    user = os.getenv("DB_USER", "finbase")
    password = os.getenv("DB_PASSWORD", "supersecretpassword")
    conn = psycopg2.connect(host=host, port=port, dbname=db, user=user, password=password)
    conn.autocommit = True
    return conn


def _bump_quality_issue(provider_name: str) -> None:
    global _db_conn
    try:
        if _db_conn is None or getattr(_db_conn, "closed", 1):
            _db_conn = _connect_db()
        with _db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO provider_reputation (provider_name, data_quality_issues, last_seen_active)
                VALUES (%s, 1, NOW())
                ON CONFLICT (provider_name) DO UPDATE SET
                    data_quality_issues = provider_reputation.data_quality_issues + 1,
                    last_seen_active = NOW()
                """,
                (provider_name,)
            )
    except Exception:
        logger.exception("Failed to bump data_quality_issues for provider=%s", provider_name)


def process_message(cfg, channel, method, properties, body: bytes):
    """Process a consumed message.

    - Valid -> route original body to VALID_QUEUE, then ack
    - Invalid -> build envelope with original_message and validation_error, route to INVALID_QUEUE, then ack
    - On publish failure -> nack with requeue=True
    """
    try:
        # Preserve original body exactly for routing and invalid envelope
        try:
            body_str = body.decode("utf-8")
        except UnicodeDecodeError:
            body_str = body.decode("utf-8", errors="replace")

        # Attempt to parse JSON for validation
        try:
            data = json.loads(body_str)
        except json.JSONDecodeError as je:
            reason = f"Invalid JSON: {je.msg} at pos {je.pos}"
            invalid_msg = {"original_message": body_str, "validation_error": reason}
            publish_json(channel, cfg["INVALID_QUEUE"], invalid_msg)
            channel.basic_ack(delivery_tag=method.delivery_tag)
            logger.warning("Routed invalid JSON to %s: %s", cfg["INVALID_QUEUE"], reason)
            return

        # Apply validation rules
        is_valid, reason = validate_data(data)
        if is_valid:
            # Route original, unchanged
            publish_raw(channel, cfg["VALID_QUEUE"], body)
            channel.basic_ack(delivery_tag=method.delivery_tag)
            logger.info(
                "Valid message routed to %s (ticker=%s ts=%s)",
                cfg["VALID_QUEUE"], data.get("ticker_symbol"), data.get("timestamp_utc")
            )
        else:
            # Attempt to extract provider from metadata and update reputation
            try:
                meta = (data or {}).get("metadata") or {}
                provider_name = meta.get("provider") or meta.get("source")
                if provider_name:
                    _bump_quality_issue(str(provider_name))
            except Exception:
                logger.exception("Failed to update provider reputation for invalid message")
            invalid_msg = {"original_message": body_str, "validation_error": reason}
            publish_json(channel, cfg["INVALID_QUEUE"], invalid_msg)
            channel.basic_ack(delivery_tag=method.delivery_tag)
            logger.warning(
                "Invalid message routed to %s: %s", cfg["INVALID_QUEUE"], reason
            )

    except (ChannelClosedByBroker, StreamLostError, AMQPConnectionError) as e:
        logger.error("Channel/connection error during processing: %s", str(e))
        try:
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        except Exception:
            # If channel is gone, the broker will requeue when connection drops
            pass
        # Let outer loop reconnect
        raise
    except Exception as e:
        logger.exception("Unexpected error in message processing: %s", str(e))
        try:
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        except Exception:
            pass


def run():
    """Start consumption loop and handle reconnections."""
    cfg = load_config()

    def _handle_signal(signum, frame):
        logger.info("Received signal %s. Stopping consumption...", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    backoff_attempt = 0
    connection = None
    channel = None

    # Connect to DB on startup (best-effort)
    global _db_conn
    try:
        _db_conn = _connect_db()
        logger.info("Connected to DB for quality feedback updates")
    except Exception as e:
        logger.error("Failed to connect to DB on startup: %s (will retry on first use)", str(e))

    while not stop_event.is_set():
        try:
            connection, channel = connect_rabbitmq(cfg)
            backoff_attempt = 0  # reset backoff on successful connect

            def _callback(ch, method, properties, body):
                return process_message(cfg, ch, method, properties, body)

            channel.basic_consume(
                queue=cfg["INPUT_QUEUE"], on_message_callback=_callback, auto_ack=False
            )
            logger.info("Starting consumption from %s...", cfg["INPUT_QUEUE"])
            channel.start_consuming()
        except SystemExit:
            logger.info("SystemExit received, shutting down...")
            break
        except Exception as e:
            if stop_event.is_set():
                break
            backoff_attempt += 1
            sleep_s = min(60, (2 ** min(backoff_attempt, 6))) + random.uniform(0, 1)
            logger.error("Consumption loop error: %s. Reconnecting in %.1fs...", str(e), sleep_s)
            stop_event.wait(sleep_s)
        finally:
            try:
                if channel and channel.is_open:
                    try:
                        # Attempt to stop consuming gracefully
                        channel.stop_consuming()
                    except Exception:
                        pass
                    channel.close()
            except Exception:
                pass
            try:
                if connection and connection.is_open:
                    connection.close()
            except Exception:
                pass

    logger.info("Quality service shut down cleanly.")


if __name__ == "__main__":
    try:
        logger.info("Starting FinBase Quality Service...")
        run()
    except SystemExit as e:
        logger.info("Exiting: %s", str(e))
        sys.exit(0)
    except Exception as e:
        logger.exception("Fatal error: %s", str(e))
        sys.exit(1)

