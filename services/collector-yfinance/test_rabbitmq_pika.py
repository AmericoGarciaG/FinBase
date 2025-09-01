#!/usr/bin/env python3
"""
RabbitMQ connectivity test script using pika.
Tests basic operations: connect, declare queue, publish, consume, cleanup.
"""

import os
import sys
import time
import json
import pika

def env(name, default):
    return os.environ.get(name, default)

RABBITMQ_HOST = env("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(env("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = env("RABBITMQ_USER", "guest")
RABBITMQ_PASS = env("RABBITMQ_PASS", "guest")
RABBITMQ_VHOST = env("RABBITMQ_VHOST", "/")
QUEUE_NAME = env("RABBITMQ_TEST_QUEUE", "test.yfinance.connectivity")

print("=== RabbitMQ Connectivity Test ===")
print(f"Host: {RABBITMQ_HOST}:{RABBITMQ_PORT}")
print(f"User: {RABBITMQ_USER}")
print(f"VHost: {RABBITMQ_VHOST}")
print(f"Test Queue: {QUEUE_NAME}")
print()

credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
params = pika.ConnectionParameters(
    host=RABBITMQ_HOST,
    port=RABBITMQ_PORT,
    virtual_host=RABBITMQ_VHOST,
    credentials=credentials,
    heartbeat=30,
    blocked_connection_timeout=10,
    connection_attempts=3,
    retry_delay=2,
    socket_timeout=10,
)

connection = None
channel = None

try:
    print(f"1. Connecting to amqp://{RABBITMQ_USER}@{RABBITMQ_HOST}:{RABBITMQ_PORT}{RABBITMQ_VHOST}")
    connection = pika.BlockingConnection(params)
    channel = connection.channel()
    print("   ✅ Connected successfully!")
    
    print(f"2. Declaring test queue: {QUEUE_NAME}")
    channel.queue_declare(queue=QUEUE_NAME, durable=False, auto_delete=False)
    print("   ✅ Queue declared!")
    
    msg = {"timestamp": time.time(), "message": "pika test OK", "test_id": int(time.time() * 1000)}
    body = json.dumps(msg, indent=2).encode("utf-8")
    
    print("3. Publishing test message...")
    channel.basic_publish(
        exchange="",
        routing_key=QUEUE_NAME,
        body=body,
        properties=pika.BasicProperties(content_type="application/json"),
    )
    print("   ✅ Message published!")
    
    print("4. Consuming message via basic_get...")
    method_frame, header_frame, body_in = channel.basic_get(queue=QUEUE_NAME, auto_ack=False)
    assert method_frame is not None, "No message retrieved from queue"
    received_msg = json.loads(body_in.decode("utf-8"))
    print(f"   ✅ Received: {received_msg}")
    channel.basic_ack(method_frame.delivery_tag)
    
    print("5. Cleaning up: purging and deleting test queue...")
    channel.queue_purge(QUEUE_NAME)
    channel.queue_delete(QUEUE_NAME)
    print("   ✅ Cleanup completed!")
    
    print("\n🎉 SUCCESS: RabbitMQ connectivity test passed!")
    sys.exit(0)
    
except Exception as e:
    print(f"\n❌ ERROR: {repr(e)}")
    print("\nPossible issues:")
    print("- RabbitMQ container not running")
    print("- Wrong credentials or connection parameters")
    print("- Network connectivity issues")
    print("- Port mapping problems")
    sys.exit(1)
    
finally:
    try:
        if channel and channel.is_open:
            channel.close()
    except Exception:
        pass
    try:
        if connection and connection.is_open:
            connection.close()
    except Exception:
        pass
