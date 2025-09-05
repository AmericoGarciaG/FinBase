#!/usr/bin/env python3
"""
FinBase Collector - Yahoo Finance Data Source.

This microservice fetches financial data from Yahoo Finance using the yfinance library
and publishes it to RabbitMQ in the FinBase canonical format.

Part of the FinBase - The Open Ledger project.
"""

import json
import logging
import os
import random
import signal
import sys
import time
from datetime import datetime, timezone
from threading import Event
from typing import Optional, Tuple

import pika
import yfinance as yf
from dotenv import load_dotenv
from pika.exceptions import AMQPConnectionError, ChannelClosedByBroker, StreamLostError

# Ensure log timestamps are in UTC and ISO-like
logging.Formatter.converter = time.gmtime
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)sZ %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("collector-yfinance")

# Global stop event set by signal handlers for graceful shutdown
stop_event = Event()


def isoformat_utc(dt: datetime, milliseconds: bool = True) -> str:
    """
    Return an ISO-8601 string in UTC with a 'Z' suffix.
    
    Args:
        dt: The datetime object to format
        milliseconds: Whether to include millisecond precision
        
    Returns:
        ISO-8601 formatted UTC timestamp string
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    if milliseconds:
        return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def load_config():
    """Load configuration from environment with defaults.

    Only the required variables need to be present in .env; others are optional with defaults.

    Returns:
        dict: Configuration dictionary
    """
    load_dotenv()

    cfg = {}
    cfg["RABBITMQ_HOST"] = os.getenv("RABBITMQ_HOST", "localhost")
    cfg["RABBITMQ_PORT"] = int(os.getenv("RABBITMQ_PORT", "5672"))
    cfg["RABBITMQ_USER"] = os.getenv("RABBITMQ_USER", "guest")
    cfg["RABBITMQ_PASSWORD"] = os.getenv("RABBITMQ_PASSWORD", "guest")
    cfg["RAW_QUEUE_NAME"] = os.getenv("RAW_QUEUE_NAME", "raw_data_queue")

    tickers_env = os.getenv("TICKERS", "AAPL,MSFT")
    cfg["TICKERS"] = [t.strip().upper() for t in tickers_env.split(",") if t.strip()]

    cfg["FETCH_INTERVAL_SECONDS"] = int(os.getenv("FETCH_INTERVAL_SECONDS", "60"))
    cfg["TICKER_DELAY_SECONDS"] = float(os.getenv("TICKER_DELAY_SECONDS", "2.0"))  # Delay between ticker requests
    cfg["RETRY_DELAY_SECONDS"] = int(os.getenv("RETRY_DELAY_SECONDS", "300"))  # Wait 5 minutes on repeated failures

    # Connection tuning
    cfg["RABBITMQ_HEARTBEAT"] = int(os.getenv("RABBITMQ_HEARTBEAT", "30"))
    cfg["RABBITMQ_BLOCKED_TIMEOUT"] = int(os.getenv("RABBITMQ_BLOCKED_TIMEOUT", "60"))
    cfg["MAX_CONNECTION_ATTEMPTS"] = int(os.getenv("MAX_CONNECTION_ATTEMPTS", "0"))  # 0 = unlimited

    logger.info(
        "Loaded config: host=%s port=%s queue=%s tickers=%s interval=%ss",
        cfg["RABBITMQ_HOST"],
        cfg["RABBITMQ_PORT"],
        cfg["RAW_QUEUE_NAME"],
        ",".join(cfg["TICKERS"]),
        cfg["FETCH_INTERVAL_SECONDS"],
    )
    return cfg


def connect_rabbitmq(cfg) -> Tuple[pika.BlockingConnection, pika.adapters.blocking_connection.BlockingChannel]:
    """Establish a RabbitMQ connection and channel with retry/backoff.

    Ensures the target queue exists and enables publisher confirms.
    
    Args:
        cfg: Configuration dictionary
        
    Returns:
        tuple: (connection, channel) objects
        
    Raises:
        SystemExit: If shutdown is requested during connection attempts
    """
    credentials = pika.PlainCredentials(cfg["RABBITMQ_USER"], cfg["RABBITMQ_PASSWORD"])
    parameters = pika.ConnectionParameters(
        host=cfg["RABBITMQ_HOST"],
        port=cfg["RABBITMQ_PORT"],
        credentials=credentials,
        heartbeat=cfg["RABBITMQ_HEARTBEAT"],
        blocked_connection_timeout=cfg["RABBITMQ_BLOCKED_TIMEOUT"],
        connection_attempts=1,  # manual retry loop below
        retry_delay=0,
        client_properties={"connection_name": "collector-yfinance"},
    )

    attempt = 0
    max_attempts = cfg["MAX_CONNECTION_ATTEMPTS"]
    
    logger.info("Starting RabbitMQ connection attempts (max_attempts=%s, 0=unlimited)...", max_attempts if max_attempts > 0 else "unlimited")
    
    while not stop_event.is_set():
        try:
            attempt += 1
            logger.info("Connecting to RabbitMQ (attempt=%s/%s) to %s:%s...", 
                       attempt, max_attempts if max_attempts > 0 else "∞", 
                       cfg["RABBITMQ_HOST"], cfg["RABBITMQ_PORT"])
            connection = pika.BlockingConnection(parameters)
            channel = connection.channel()

            # Declare durable queue. No auto-delete; let consumers manage lifecycles.
            channel.queue_declare(queue=cfg["RAW_QUEUE_NAME"], durable=True)

            # Enable publisher confirms for reliability
            channel.confirm_delivery()

            logger.info("Connected to RabbitMQ and queue ensured: %s", cfg["RAW_QUEUE_NAME"])
            return connection, channel
        except AMQPConnectionError as e:
            backoff = min(60, (2 ** min(attempt, 6))) + random.uniform(0, 1)
            logger.error("RabbitMQ connection failed: %s (retrying in %.1fs)", str(e), backoff)
            stop_event.wait(backoff)
        except Exception as e:
            backoff = min(60, (2 ** min(attempt, 6))) + random.uniform(0, 1)
            logger.exception("Unexpected error while connecting to RabbitMQ: %s (retrying in %.1fs)", str(e), backoff)
            stop_event.wait(backoff)
        
        # Check if we've exceeded max attempts
        if max_attempts > 0 and attempt >= max_attempts:
            logger.error("Failed to connect to RabbitMQ after %d attempts. Exiting.", attempt)
            raise SystemExit(f"Max connection attempts ({max_attempts}) exceeded.")

    # If we get here, we were asked to stop
    raise SystemExit("Shutdown requested before RabbitMQ connection established.")


def fetch_latest_candle(ticker: str) -> Optional[dict]:
    """Fetch the latest 1-minute candle and return canonical JSON.

    Args:
        ticker: Stock ticker symbol
        
    Returns:
        dict: Canonical format data or None if no data is available
    """
    try:
        logger.debug("Fetching data for ticker=%s", ticker)
        
        # Create ticker object with additional error handling
        ticker_obj = yf.Ticker(ticker)
        
        # Try to get basic info first to validate ticker
        try:
            info = ticker_obj.info
            if not info or 'regularMarketPrice' not in info:
                logger.warning("Ticker %s may be invalid or delisted - no market data in info", ticker)
        except Exception as info_e:
            logger.warning("Could not fetch info for %s: %s", ticker, str(info_e))
        
        # yfinance history: period=1d and interval=1m gives the latest minute bars for today
        logger.debug("Calling yfinance history for %s", ticker)
        df = ticker_obj.history(period="1d", interval="1m", auto_adjust=False, prepost=False, repair=True)
        
        if df is None:
            logger.warning("yfinance returned None for ticker=%s", ticker)
            return None
            
        if df.empty:
            logger.warning("yfinance returned empty DataFrame for ticker=%s", ticker)
            return None

        last = df.tail(1) # TEMPORAL. Tiene que evolucionar para cuando haya escalamiento con cientos de microservicios. 
        index = last.index[0]

        # Convert index timestamp to UTC
        if hasattr(index, "to_pydatetime"):
            dt = index.to_pydatetime()
        else:
            # Fallback in rare cases
            dt = datetime.fromtimestamp(index.timestamp())

        if dt.tzinfo is None:
            candle_ts_utc = dt.replace(tzinfo=timezone.utc)
        else:
            candle_ts_utc = dt.astimezone(timezone.utc)

        open_v = float(last["Open"].iloc[0])
        high_v = float(last["High"].iloc[0])
        low_v = float(last["Low"].iloc[0])
        close_v = float(last["Close"].iloc[0])
        vol_v = int(last["Volume"].iloc[0]) if not (last["Volume"].isna().iloc[0]) else 0

        # Build canonical format according to FinBase specification
        canonical = {
            "ticker_symbol": ticker,
            "timestamp_utc": isoformat_utc(candle_ts_utc, milliseconds=False),
            "open": open_v,
            "high": high_v,
            "low": low_v,
            "close": close_v,
            "volume": vol_v,
            "metadata": {
                "source": "yfinance",
                "fetch_timestamp_utc": isoformat_utc(datetime.now(timezone.utc), milliseconds=True),
            },
        }
        return canonical
    except Exception as e:
        error_msg = str(e)
        if "Expecting value: line 1 column 1" in error_msg:
            logger.error("yfinance returned invalid JSON for ticker=%s. This usually means Yahoo Finance is blocking requests or ticker is invalid. Error: %s", ticker, error_msg)
        elif "possibly delisted" in error_msg.lower():
            logger.error("Ticker %s appears to be delisted or invalid: %s", ticker, error_msg)
        elif "No data found" in error_msg:
            logger.error("No historical data available for ticker=%s: %s", ticker, error_msg)
        else:
            logger.exception("Failed to fetch/transform data for ticker=%s: %s", ticker, error_msg)
        return None


def publish_json(channel, queue_name: str, message: dict) -> None:
    """
    Publish a JSON message to the given queue with delivery persistence and publisher confirms.
    
    Args:
        channel: RabbitMQ channel object
        queue_name: Target queue name
        message: Message dictionary to publish
        
    Raises:
        RuntimeError: If the message is not confirmed by broker
    """
    payload = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    properties = pika.BasicProperties(
        content_type="application/json",
        delivery_mode=2,  # make message persistent
    )
    ok = channel.basic_publish(
        exchange="",
        routing_key=queue_name,
        body=payload,
        properties=properties,
        mandatory=False,  # queue is declared; set True if you want unroutable error callback
    )
    if not ok:
        raise RuntimeError("Publish not confirmed by broker")


def run():
    """Run main application loop.

    Loads configuration, connects to RabbitMQ,
    and continuously fetches and publishes financial data.
    """
    cfg = load_config()

    # Register signal handlers for graceful shutdown
    def _handle_signal(signum, frame):
        logger.info("Received signal %s. Initiating graceful shutdown...", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    connection = None
    channel = None

    try:
        connection, channel = connect_rabbitmq(cfg)

        # Main loop: periodically fetch and publish for each ticker
        logger.info("Starting data collection loop...")
        consecutive_failures = 0
        
        while not stop_event.is_set():
            cycle_start = time.monotonic()
            successful_fetches = 0
            
            for i, ticker in enumerate(cfg["TICKERS"]):
                if stop_event.is_set():
                    break

                data = fetch_latest_candle(ticker)
                if data is None:
                    # Add a small delay between failed requests to avoid hammering the API
                    if i < len(cfg["TICKERS"]) - 1:  # Don't delay after the last ticker
                        stop_event.wait(cfg["TICKER_DELAY_SECONDS"])
                    continue
                    
                successful_fetches += 1

                try:
                    publish_json(channel, cfg["RAW_QUEUE_NAME"], data)
                    logger.info(
                        "Published %s @ %s to queue=%s",
                        data["ticker_symbol"],
                        data["timestamp_utc"],
                        cfg["RAW_QUEUE_NAME"],
                    )
                except (ChannelClosedByBroker, StreamLostError, AMQPConnectionError) as e:
                    logger.error("Channel/connection error during publish: %s. Will attempt to reconnect.", str(e))
                    # Close existing connection and reconnect
                    try:
                        if connection and not connection.is_closed:
                            connection.close()
                    except Exception:
                        pass
                    connection, channel = connect_rabbitmq(cfg)
                    # Retry the publish after reconnection
                    try:
                        publish_json(channel, cfg["RAW_QUEUE_NAME"], data)
                        logger.info(
                            "Published %s @ %s to queue=%s (after reconnect)",
                            data["ticker_symbol"],
                            data["timestamp_utc"],
                            cfg["RAW_QUEUE_NAME"],
                        )
                    except Exception as retry_e:
                        logger.exception("Failed to publish after reconnection for %s: %s", ticker, str(retry_e))
                except Exception as e:
                    logger.exception("Unexpected error during publish for %s: %s", ticker, str(e))
                    
                # Add delay between ticker requests to respect rate limits
                if i < len(cfg["TICKERS"]) - 1:  # Don't delay after the last ticker
                    stop_event.wait(cfg["TICKER_DELAY_SECONDS"])
            
            # Handle consecutive failures with backoff
            if successful_fetches == 0:
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    backoff_delay = cfg["RETRY_DELAY_SECONDS"]
                    logger.warning("No successful fetches in %d cycles. Backing off for %d seconds...", 
                                 consecutive_failures, backoff_delay)
                    stop_event.wait(backoff_delay)
            else:
                consecutive_failures = 0

            # Sleep until next interval, with stop-aware wait
            elapsed = time.monotonic() - cycle_start
            remaining = max(0, cfg["FETCH_INTERVAL_SECONDS"] - elapsed)
            if remaining > 0:
                logger.debug("Cycle completed in %.2fs, sleeping %.2fs until next cycle", elapsed, remaining)
                stop_event.wait(remaining)

    finally:
        # Attempt clean shutdown
        logger.info("Shutting down connections...")
        try:
            if channel and not channel.is_closed:
                channel.close()
        except Exception:
            pass
        try:
            if connection and not connection.is_closed:
                connection.close()
        except Exception:
            pass
        logger.info("Collector shut down cleanly.")


import threading


class YFinanceCollector:
    """YFinance collector with remote pause/resume control via RabbitMQ."""

    def __init__(self) -> None:
        self.cfg = load_config()
        self.is_paused = False
        # Reuse the global stop_event for existing helpers
        self.stop_event = stop_event
        self._control_thread: Optional[threading.Thread] = None

    def _start_control_consumer(self) -> None:
        """Start a background thread consuming collector control commands.

        Binds an exclusive anonymous queue to the 'collector_control' fanout exchange and
        toggles self.is_paused based on incoming messages.
        """
        exchange_name = os.getenv("RABBITMQ_COLLECTOR_CONTROL_EXCHANGE", "collector_control")

        def _thread_func():
            credentials = pika.PlainCredentials(self.cfg["RABBITMQ_USER"], self.cfg["RABBITMQ_PASSWORD"])
            params = pika.ConnectionParameters(
                host=self.cfg["RABBITMQ_HOST"],
                port=self.cfg["RABBITMQ_PORT"],
                credentials=credentials,
                heartbeat=self.cfg["RABBITMQ_HEARTBEAT"],
                blocked_connection_timeout=self.cfg["RABBITMQ_BLOCKED_TIMEOUT"],
                connection_attempts=1,
                retry_delay=0,
                client_properties={"connection_name": "collector-yfinance-control"},
            )

            conn = None
            ch = None
            while not self.stop_event.is_set():
                try:
                    conn = pika.BlockingConnection(params)
                    ch = conn.channel()
                    ch.exchange_declare(exchange=exchange_name, exchange_type="fanout", durable=True)
                    q = ch.queue_declare(queue="", exclusive=True, auto_delete=True)
                    qname = q.method.queue
                    ch.queue_bind(exchange=exchange_name, queue=qname)

                    logger.info("Control consumer connected. Waiting for pause/resume commands...")
                    for method, properties, body in ch.consume(qname, inactivity_timeout=0.5, auto_ack=True):
                        if self.stop_event.is_set():
                            break
                        if method is None:
                            continue
                        try:
                            payload = json.loads(body or b"{}")
                            cmd = str(payload.get("command", "")).lower()
                            if cmd == "pause":
                                if not self.is_paused:
                                    logger.warning("Received PAUSE command. Pausing data collection.")
                                self.is_paused = True
                            elif cmd == "resume":
                                if self.is_paused:
                                    logger.warning("Received RESUME command. Resuming data collection.")
                                self.is_paused = False
                        except Exception as e:
                            logger.error("Invalid control message: %s", str(e))
                    try:
                        ch.cancel()
                    except Exception:
                        pass
                    try:
                        ch.close()
                    except Exception:
                        pass
                    try:
                        conn.close()
                    except Exception:
                        pass
                except Exception as e:
                    logger.error("Control consumer error: %s (will retry)", str(e))
                    # Simple backoff
                    self.stop_event.wait(1.0)
            # Final cleanup (if any open)
            try:
                if ch and ch.is_open:
                    ch.close()
            except Exception:
                pass
            try:
                if conn and conn.is_open:
                    conn.close()
            except Exception:
                pass

        self._control_thread = threading.Thread(target=_thread_func, name="collector-control-consumer", daemon=True)
        self._control_thread.start()

    def run(self) -> None:
        # Register signal handlers for graceful shutdown
        def _handle_signal(signum, frame):
            logger.info("Received signal %s. Initiating graceful shutdown...", signum)
            self.stop_event.set()

        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

        connection = None
        channel = None

        try:
            # Start control consumer thread
            self._start_control_consumer()

            connection, channel = connect_rabbitmq(self.cfg)

            # Main loop: periodically fetch and publish for each ticker
            logger.info("Starting data collection loop...")
            consecutive_failures = 0

            while not self.stop_event.is_set():
                cycle_start = time.monotonic()
                successful_fetches = 0

                for i, ticker in enumerate(self.cfg["TICKERS"]):
                    if self.stop_event.is_set():
                        break

                    # Pause gate before fetching data
                    if self.is_paused:
                        time.sleep(1)
                        continue

                    data = fetch_latest_candle(ticker)
                    if data is None:
                        # Add a small delay between failed requests to avoid hammering the API
                        if i < len(self.cfg["TICKERS"]) - 1:  # Don't delay after the last ticker
                            self.stop_event.wait(self.cfg["TICKER_DELAY_SECONDS"])
                        continue

                    successful_fetches += 1

                    try:
                        publish_json(channel, self.cfg["RAW_QUEUE_NAME"], data)
                        logger.info(
                            "Published %s @ %s to queue=%s",
                            data["ticker_symbol"],
                            data["timestamp_utc"],
                            self.cfg["RAW_QUEUE_NAME"],
                        )
                    except (ChannelClosedByBroker, StreamLostError, AMQPConnectionError) as e:
                        logger.error("Channel/connection error during publish: %s. Will attempt to reconnect.", str(e))
                        # Close existing connection and reconnect
                        try:
                            if connection and not connection.is_closed:
                                connection.close()
                        except Exception:
                            pass
                        connection, channel = connect_rabbitmq(self.cfg)
                        # Retry the publish after reconnection
                        try:
                            publish_json(channel, self.cfg["RAW_QUEUE_NAME"], data)
                            logger.info(
                                "Published %s @ %s to queue=%s (after reconnect)",
                                data["ticker_symbol"],
                                data["timestamp_utc"],
                                self.cfg["RAW_QUEUE_NAME"],
                            )
                        except Exception as retry_e:
                            logger.exception("Failed to publish after reconnection for %s: %s", ticker, str(retry_e))
                    except Exception as e:
                        logger.exception("Unexpected error during publish for %s: %s", ticker, str(e))

                    # Add delay between ticker requests to respect rate limits
                    if i < len(self.cfg["TICKERS"]) - 1:  # Don't delay after the last ticker
                        self.stop_event.wait(self.cfg["TICKER_DELAY_SECONDS"])

                # Handle consecutive failures with backoff
                if successful_fetches == 0:
                    consecutive_failures += 1
                    if consecutive_failures >= 3:
                        backoff_delay = self.cfg["RETRY_DELAY_SECONDS"]
                        logger.warning(
                            "No successful fetches in %d cycles. Backing off for %d seconds...",
                            consecutive_failures,
                            backoff_delay,
                        )
                        self.stop_event.wait(backoff_delay)
                else:
                    consecutive_failures = 0

                # Sleep until next interval, with stop-aware wait
                elapsed = time.monotonic() - cycle_start
                remaining = max(0, self.cfg["FETCH_INTERVAL_SECONDS"] - elapsed)
                if remaining > 0:
                    logger.debug("Cycle completed in %.2fs, sleeping %.2fs until next cycle", elapsed, remaining)
                    self.stop_event.wait(remaining)

        finally:
            # Attempt clean shutdown
            logger.info("Shutting down connections...")
            try:
                if channel and not channel.is_closed:
                    channel.close()
            except Exception:
                pass
            try:
                if connection and not connection.is_closed:
                    connection.close()
            except Exception:
                pass
            # Stop control thread
            if self._control_thread and self._control_thread.is_alive():
                try:
                    self._control_thread.join(timeout=2.0)
                except Exception:
                    pass
            logger.info("Collector shut down cleanly.")


if __name__ == "__main__":
    try:
        logger.info("Starting FinBase YFinance Collector...")
        YFinanceCollector().run()
    except SystemExit as e:
        logger.info("Exiting: %s", str(e))
        sys.exit(0)
    except Exception as e:
        logger.exception("Fatal error: %s", str(e))
        sys.exit(1)
