#!/usr/bin/env python3
"""
Simplified collector test script to verify RabbitMQ publishing works.
This version doesn't use publisher confirms to avoid the confirmation issue.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone

import pika
import yfinance as yf
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("test-collector")

def load_config():
    """Load configuration from environment."""
    load_dotenv()
    
    cfg = {}
    cfg["RABBITMQ_HOST"] = os.getenv("RABBITMQ_HOST", "localhost")
    cfg["RABBITMQ_PORT"] = int(os.getenv("RABBITMQ_PORT", "5672"))
    cfg["RABBITMQ_USER"] = os.getenv("RABBITMQ_USER", "guest")
    cfg["RABBITMQ_PASSWORD"] = os.getenv("RABBITMQ_PASSWORD", "guest")
    cfg["RAW_QUEUE_NAME"] = os.getenv("RAW_QUEUE_NAME", "raw_data_queue")
    cfg["TICKERS"] = ["AAPL", "MSFT", "GOOGL"]
    
    return cfg

def connect_rabbitmq(cfg):
    """Connect to RabbitMQ without publisher confirms."""
    credentials = pika.PlainCredentials(cfg["RABBITMQ_USER"], cfg["RABBITMQ_PASSWORD"])
    parameters = pika.ConnectionParameters(
        host=cfg["RABBITMQ_HOST"],
        port=cfg["RABBITMQ_PORT"],
        credentials=credentials,
        heartbeat=30,
        connection_attempts=3,
        retry_delay=2,
    )
    
    connection = pika.BlockingConnection(parameters)
    channel = connection.channel()
    
    # Declare durable queue
    channel.queue_declare(queue=cfg["RAW_QUEUE_NAME"], durable=True)
    
    logger.info(f"Connected to RabbitMQ and queue ensured: {cfg['RAW_QUEUE_NAME']}")
    return connection, channel

def fetch_simple_data(ticker):
    """Fetch simple data for a ticker."""
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="1d", interval="1m", auto_adjust=False, prepost=False, repair=True)
        
        if df is None or df.empty:
            return None
            
        last = df.tail(1)
        index = last.index[0]
        
        # Convert to UTC
        if hasattr(index, "to_pydatetime"):
            dt = index.to_pydatetime()
        else:
            dt = datetime.fromtimestamp(index.timestamp())
            
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
            
        return {
            "ticker_symbol": ticker,
            "timestamp_utc": dt.isoformat().replace("+00:00", "Z"),
            "open": float(last["Open"].iloc[0]),
            "high": float(last["High"].iloc[0]),
            "low": float(last["Low"].iloc[0]),
            "close": float(last["Close"].iloc[0]),
            "volume": int(last["Volume"].iloc[0]) if not last["Volume"].isna().iloc[0] else 0,
            "metadata": {
                "source": "yfinance",
                "fetch_timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        }
    except Exception as e:
        logger.error(f"Failed to fetch data for {ticker}: {e}")
        return None

def publish_simple(channel, queue_name, message):
    """Publish without confirms for testing."""
    payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    properties = pika.BasicProperties(
        content_type="application/json",
        delivery_mode=2,  # persistent
    )
    
    channel.basic_publish(
        exchange="",
        routing_key=queue_name,
        body=payload,
        properties=properties,
    )

def main():
    """Main test function."""
    print("=== Simplified Collector Test ===")
    print("Testing RabbitMQ publishing without confirms...")
    
    cfg = load_config()
    logger.info(f"Config: {cfg['RABBITMQ_HOST']}:{cfg['RABBITMQ_PORT']} -> {cfg['RAW_QUEUE_NAME']}")
    
    try:
        connection, channel = connect_rabbitmq(cfg)
        
        for ticker in cfg["TICKERS"]:
            print(f"\nTesting {ticker}...")
            
            # Fetch data
            data = fetch_simple_data(ticker)
            if data is None:
                print(f"   ❌ Failed to fetch data for {ticker}")
                continue
                
            # Publish data
            try:
                publish_simple(channel, cfg["RAW_QUEUE_NAME"], data)
                print(f"   ✅ Published {ticker} data: {data['close']} @ {data['timestamp_utc']}")
                logger.info(f"Published {ticker} @ {data['timestamp_utc']} to {cfg['RAW_QUEUE_NAME']}")
            except Exception as e:
                print(f"   ❌ Failed to publish {ticker}: {e}")
                
            time.sleep(1)  # Small delay between tickers
            
        print(f"\n🎉 Test completed! Check RabbitMQ queue '{cfg['RAW_QUEUE_NAME']}' for messages.")
        
    except Exception as e:
        print(f"❌ Connection error: {e}")
        logger.error(f"Connection error: {e}")
    finally:
        try:
            if 'channel' in locals() and channel.is_open:
                channel.close()
        except:
            pass
        try:
            if 'connection' in locals() and connection.is_open:
                connection.close()
        except:
            pass

if __name__ == "__main__":
    main()
