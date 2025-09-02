#!/usr/bin/env python3
"""
FinBase API Service (read-only)

FastAPI + asyncpg service providing historical data from TimescaleDB.
Exposes: GET /v1/data/history/{ticker}

Key features:
- Async connection pool (created on startup, closed on shutdown)
- Input validation with Pydantic v2
- Time-series aggregation in DB using time_bucket for 1hour/1day intervals
- Clean JSON responses and robust error handling
- WebSocket real-time streaming integrated with RabbitMQ fanout exchange 'data_events'
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from datetime import datetime, timedelta, date
from typing import Annotated, Dict, Iterable, List, Literal, Optional, Set, Tuple

import asyncpg
import pika
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, status, Depends, Security
from fastapi import Body
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel, field_validator
import psycopg2
import uuid

# Load environment from .env if present
load_dotenv()

logger = logging.getLogger("api-service")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())

app = FastAPI(title="FinBase API", version="0.2.0")

# Security: API Key required for backfill job creation
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def require_api_key(api_key: Optional[str] = Security(api_key_header)) -> bool:
    expected = os.getenv("BACKFILL_API_KEY")
    if not expected:
        # If no key configured, deny by default
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    if not api_key or api_key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    return True


class Interval(BaseModel):
    value: Literal["1min", "1hour", "1day"]

    @property
    def bucket(self) -> Optional[timedelta]:
        if self.value == "1min":
            return None  # no aggregation
        return {"1hour": timedelta(hours=1), "1day": timedelta(days=1)}[self.value]


class HistoryQuery(BaseModel):
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    interval: Interval
    limit: int = 1000

    @field_validator("limit")
    @classmethod
    def _limit_bounds(cls, v: int) -> int:
        if v <= 0 or v > 10000:
            raise ValueError("limit must be between 1 and 10000")
        return v

    @field_validator("end_date")
    @classmethod
    def _check_range(cls, v: Optional[datetime], info):
        # The Pydantic v2 validator gets only one field at a time; cross-field check below in model-level validation
        return v

    @field_validator("start_date")
    @classmethod
    def _check_start(cls, v: Optional[datetime], info):
        return v

    def validate_range(self) -> None:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must be <= end_date")


class Candle(BaseModel):
    timestamp: datetime
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[int] = None


class HistoryResponse(BaseModel):
    ticker: str
    interval: str
    count: int
    data: list[Candle]


class SymbolsResponse(BaseModel):
    symbols: List[str]


class BackfillJobRequest(BaseModel):
    ticker: str
    provider: Literal["yfinance"]
    start_date: str  # YYYY-MM-DD
    end_date: str    # YYYY-MM-DD
    interval: Optional[Literal["1d", "1h", "1m"]] = None

    @field_validator("ticker")
    @classmethod
    def _upcase(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if not v:
            raise ValueError("ticker required")
        return v

    def validate_range(self) -> None:
        try:
            sd = datetime.fromisoformat(self.start_date + "T00:00:00")
            ed = datetime.fromisoformat(self.end_date + "T00:00:00")
        except Exception:
            raise ValueError("start_date/end_date must be YYYY-MM-DD")
        if sd > ed:
            raise ValueError("start_date must be <= end_date")


async def _make_pool() -> asyncpg.Pool:
    host = os.getenv("DB_HOST", "localhost")
    port = int(os.getenv("DB_PORT", "5432"))
    db = os.getenv("DB_NAME", "finbase")
    user = os.getenv("DB_USER", "finbase")
    password = os.getenv("DB_PASSWORD", "supersecretpassword")

    min_size = int(os.getenv("DB_POOL_MIN_SIZE", "1"))
    max_size = int(os.getenv("DB_POOL_MAX_SIZE", "10"))

    dsn = f"postgresql://{user}:{password}@{host}:{port}/{db}"
    return await asyncpg.create_pool(dsn=dsn, min_size=min_size, max_size=max_size, command_timeout=60)


# ----------------------
# WebSocket connection manager
# ----------------------
class ConnectionManager:
    def __init__(self) -> None:
        self._active: Set[WebSocket] = set()
        # Per-connection subscriptions: websocket -> {ticker: interval}
        self._subs: Dict[WebSocket, Dict[str, str]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._active.add(websocket)
            self._subs.setdefault(websocket, {})
        logger.info("WebSocket connected. Active=%d", len(self._active))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._active.discard(websocket)
            self._subs.pop(websocket, None)
        logger.info("WebSocket disconnected. Active=%d", len(self._active))

    async def subscribe(self, websocket: WebSocket, tickers: Iterable[str], interval: str = "1min") -> None:
        tickers = [t.upper() for t in tickers]
        async with self._lock:
            wsmap = self._subs.setdefault(websocket, {})
            for t in tickers:
                wsmap[t] = interval
        logger.info("WS %s subscribed: %s @ %s", id(websocket), ",".join(tickers), interval)

    async def unsubscribe(self, websocket: WebSocket, tickers: Iterable[str]) -> None:
        tickers = [t.upper() for t in tickers]
        async with self._lock:
            wsmap = self._subs.get(websocket, {})
            for t in tickers:
                wsmap.pop(t, None)

    async def get_unique_subscriptions(self) -> Set[Tuple[str, str]]:
        async with self._lock:
            pairs: Set[Tuple[str, str]] = set()
            for wsmap in self._subs.values():
                for t, interval in wsmap.items():
                    pairs.add((t, interval))
            return pairs

    async def get_clients_for(self, ticker: str, interval: str) -> List[WebSocket]:
        async with self._lock:
            out: List[WebSocket] = []
            for ws, wsmap in self._subs.items():
                if wsmap.get(ticker.upper()) == interval:
                    out.append(ws)
            return out


manager = ConnectionManager()


# ----------------------
# Startup/shutdown
# ----------------------
async def _start_rabbitmq_listener(app_ref: FastAPI) -> None:
    """Start a blocking pika consumer in a background thread.
    It posts event tokens into an asyncio.Queue consumed by an async dispatcher.
    """
    loop = asyncio.get_running_loop()
    app_ref.state.rmq_event_queue = asyncio.Queue()
    app_ref.state.rmq_stop_event = threading.Event()

    def rmq_thread() -> None:
        host = os.getenv("RABBITMQ_HOST", "localhost")
        port = int(os.getenv("RABBITMQ_PORT", "5672"))
        user = os.getenv("RABBITMQ_USER", "guest")
        password = os.getenv("RABBITMQ_PASSWORD", "guest")
        exchange_name = os.getenv("RABBITMQ_DATA_EVENTS_EXCHANGE", "data_events")

        creds = pika.PlainCredentials(user, password)
        params = pika.ConnectionParameters(
            host=host,
            port=port,
            credentials=creds,
            heartbeat=int(os.getenv("RABBITMQ_HEARTBEAT", "30")),
            blocked_connection_timeout=int(os.getenv("RABBITMQ_BLOCKED_TIMEOUT", "60")),
            connection_attempts=1,
            retry_delay=0,
            client_properties={"connection_name": "api-service-stream"},
        )

        connection: Optional[pika.BlockingConnection] = None
        channel: Optional[pika.adapters.blocking_connection.BlockingChannel] = None

        while not app_ref.state.rmq_stop_event.is_set():
            try:
                connection = pika.BlockingConnection(params)
                channel = connection.channel()
                channel.exchange_declare(exchange=exchange_name, exchange_type="fanout", durable=True)
                res = channel.queue_declare(queue="", exclusive=True, auto_delete=True)
                qname = res.method.queue
                channel.queue_bind(exchange=exchange_name, queue=qname)

                for method, properties, body in channel.consume(qname, inactivity_timeout=0.5, auto_ack=True):
                    if app_ref.state.rmq_stop_event.is_set():
                        break
                    if method is None:
                        continue
                    # Push a token/event to the async queue
                    try:
                        loop.call_soon_threadsafe(app_ref.state.rmq_event_queue.put_nowait, body or b"{}")
                    except Exception:
                        pass
                try:
                    channel.cancel()
                except Exception:
                    pass
                try:
                    channel.close()
                except Exception:
                    pass
                try:
                    connection.close()
                except Exception:
                    pass
            except Exception as e:
                logger.error("RabbitMQ listener error: %s (reconnecting soon)", str(e))
                # Backoff a bit before retrying
                app_ref.state.rmq_stop_event.wait(1.0)

    t = threading.Thread(target=rmq_thread, name="rmq-listener", daemon=True)
    app_ref.state.rmq_thread = t
    t.start()

    async def dispatcher() -> None:
        # Wait for events and on each, query for latest candles per subscription and push to clients
        while True:
            try:
                _ = await app_ref.state.rmq_event_queue.get()
                pairs = await manager.get_unique_subscriptions()
                if not pairs:
                    continue
                # Fetch latest candle per (ticker, interval)
                latest: Dict[Tuple[str, str], Candle] = {}
                pool: asyncpg.Pool = app_ref.state.pool
                async with pool.acquire() as conn:
                    for ticker, interval in pairs:
                        candle = await _fetch_latest_candle(conn, ticker, interval)
                        if candle:
                            latest[(ticker, interval)] = candle
                # Broadcast
                for (ticker, interval), candle in latest.items():
                    payload = {
                        "type": "candle",
                        "ticker": ticker,
                        "interval": interval,
                        "data": {
                            "timestamp": candle.timestamp.isoformat(),
                            "open": candle.open,
                            "high": candle.high,
                            "low": candle.low,
                            "close": candle.close,
                            "volume": candle.volume,
                        },
                    }
                    clients = await manager.get_clients_for(ticker, interval)
                    dead: List[WebSocket] = []
                    for ws in clients:
                        try:
                            await ws.send_json(payload)
                        except Exception:
                            dead.append(ws)
                    for ws in dead:
                        try:
                            await manager.disconnect(ws)
                        except Exception:
                            pass
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Dispatcher error: %s", str(e))
                await asyncio.sleep(0.2)

    app_ref.state.rmq_dispatcher_task = asyncio.create_task(dispatcher())


async def _fetch_latest_candle(conn: asyncpg.Connection, ticker: str, interval: str) -> Optional[Candle]:
    ticker = ticker.upper()
    if interval == "1min":
        row = await conn.fetchrow(
            "SELECT \"timestamp\" AS ts, open, high, low, close, volume\n"
            "FROM financial_data\n"
            "WHERE ticker = $1\n"
            "ORDER BY ts DESC\n"
            "LIMIT 1",
            ticker,
        )
    else:
        bucket = {"1hour": "1 hour", "1day": "1 day"}[interval]
        row = await conn.fetchrow(
            "WITH agg AS (\n"
            "  SELECT\n"
            "    time_bucket($2::interval, \"timestamp\") AS ts,\n"
            "    (ARRAY_AGG(open  ORDER BY \"timestamp\" ASC))[1]   AS open,\n"
            "    MAX(high)                                         AS high,\n"
            "    MIN(low)                                          AS low,\n"
            "    (ARRAY_AGG(close ORDER BY \"timestamp\" DESC))[1]  AS close,\n"
            "    SUM(volume)                                       AS volume\n"
            "  FROM financial_data\n"
            "  WHERE ticker = $1\n"
            "  GROUP BY ts\n"
            ")\n"
            "SELECT ts, open, high, low, close, volume FROM agg ORDER BY ts DESC LIMIT 1",
            ticker,
            bucket,
        )
    if not row:
        return None
    return Candle(
        timestamp=row["ts"], open=row.get("open"), high=row.get("high"), low=row.get("low"), close=row.get("close"), volume=row.get("volume")
    )


@app.on_event("startup")
async def on_startup():
    app.state.pool = await _make_pool()
    await _start_rabbitmq_listener(app)


@app.on_event("shutdown")
async def on_shutdown():
    # Stop RMQ
    try:
        if getattr(app.state, "rmq_dispatcher_task", None):
            app.state.rmq_dispatcher_task.cancel()
    except Exception:
        pass
    try:
        if getattr(app.state, "rmq_stop_event", None):
            app.state.rmq_stop_event.set()
    except Exception:
        pass
    # Close pool
    pool: asyncpg.Pool = app.state.pool
    if pool:
        await pool.close()


# ----------------------
# REST Endpoints
# ----------------------
@app.post("/v1/backfill/jobs", status_code=status.HTTP_202_ACCEPTED)
async def create_backfill_job(job: BackfillJobRequest = Body(...), _: bool = Depends(require_api_key)):
    try:
        job.validate_range()
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    # Create backfill job in DB with status PENDING (sync psycopg2)
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = int(os.getenv("DB_PORT", "5432"))
    db_name = os.getenv("DB_NAME", "finbase")
    db_user = os.getenv("DB_USER", "finbase")
    db_password = os.getenv("DB_PASSWORD", "supersecretpassword")

    job_id: Optional[uuid.UUID] = None
    conn_db = None
    try:
        conn_db = psycopg2.connect(host=db_host, port=db_port, dbname=db_name, user=db_user, password=db_password)
        conn_db.autocommit = True
        with conn_db.cursor() as cur:
            cur.execute(
                "INSERT INTO backfill_jobs (ticker, provider, start_date, end_date, status) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (
                    job.ticker,
                    job.provider,
                    date.fromisoformat(job.start_date),
                    date.fromisoformat(job.end_date),
                    "PENDING",
                ),
            )
            row = cur.fetchone()
            if not row or not row[0]:
                raise RuntimeError("Failed to obtain job id")
            job_id = row[0]
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Failed to create job: {str(e)}")
    finally:
        try:
            if conn_db:
                conn_db.close()
        except Exception:
            pass

    # Publish job id to RabbitMQ jobs queue
    queue_name = os.getenv("BACKFILL_JOBS_QUEUE", "backfill_jobs_queue")
    host = os.getenv("RABBITMQ_HOST", "localhost")
    port = int(os.getenv("RABBITMQ_PORT", "5672"))
    user = os.getenv("RABBITMQ_USER", "guest")
    password = os.getenv("RABBITMQ_PASSWORD", "guest")

    try:
        creds = pika.PlainCredentials(user, password)
        params = pika.ConnectionParameters(
            host=host,
            port=port,
            credentials=creds,
            heartbeat=int(os.getenv("RABBITMQ_HEARTBEAT", "30")),
            blocked_connection_timeout=int(os.getenv("RABBITMQ_BLOCKED_TIMEOUT", "60")),
            connection_attempts=1,
            retry_delay=0,
            client_properties={"connection_name": "api-service-backfill-publisher"},
        )
        conn = pika.BlockingConnection(params)
        ch = conn.channel()
        ch.queue_declare(queue=queue_name, durable=True)
        payload = {"job_id": str(job_id)}
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        props = pika.BasicProperties(content_type="application/json", delivery_mode=2)
        ch.basic_publish(exchange="", routing_key=queue_name, body=body, properties=props, mandatory=False)
        try:
            ch.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Failed to enqueue backfill job: {str(e)}")

    return {"job_id": str(job_id)}


class BackfillJobStatusResponse(BaseModel):
    id: str
    ticker: str
    provider: str
    start_date: str
    end_date: str
    status: str
    submitted_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None


@app.get("/v1/backfill/jobs/{job_id}", response_model=BackfillJobStatusResponse)
async def get_backfill_job_status(job_id: str):
    # Sync query via psycopg2 for simplicity
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = int(os.getenv("DB_PORT", "5432"))
    db_name = os.getenv("DB_NAME", "finbase")
    db_user = os.getenv("DB_USER", "finbase")
    db_password = os.getenv("DB_PASSWORD", "supersecretpassword")

    try:
        # Validate UUID format
        _ = uuid.UUID(job_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid job_id format")

    conn_db = None
    try:
        conn_db = psycopg2.connect(host=db_host, port=db_port, dbname=db_name, user=db_user, password=db_password)
        with conn_db.cursor() as cur:
            cur.execute(
                "SELECT id, ticker, provider, start_date, end_date, status, submitted_at, started_at, completed_at, error_message FROM backfill_jobs WHERE id = %s",
                (job_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Job not found")
            id_v, ticker, provider, sd, ed, status_v, sub_at, st_at, comp_at, err = row
            resp = BackfillJobStatusResponse(
                id=str(id_v),
                ticker=ticker,
                provider=provider,
                start_date=sd.isoformat(),
                end_date=ed.isoformat(),
                status=status_v,
                submitted_at=sub_at.isoformat() if sub_at else None,
                started_at=st_at.isoformat() if st_at else None,
                completed_at=comp_at.isoformat() if comp_at else None,
                error_message=err,
            )
            return resp
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Failed to query job: {str(e)}")
    finally:
        try:
            if conn_db:
                conn_db.close()
        except Exception:
            pass

@app.get("/v1/data/history/{ticker}", response_model=HistoryResponse)
async def get_history(
    ticker: str,
    start_date: Optional[datetime] = Query(default=None, description="ISO date/time (UTC) inclusive lower bound"),
    end_date: Optional[datetime] = Query(default=None, description="ISO date/time (UTC) inclusive upper bound"),
    interval: str = Query(default="1min", description="Aggregation interval ('1min'|'1hour'|'1day' with aliases '1m'|'1h'|'1d')"),
    limit: int = Query(default=1000, ge=1, le=10000, description="Max rows to return"),
):
    """
    Time-based pagination: 'limit' means the most recent N candles within the given range.
    To page older data, set end_date to the earliest candle's timestamp minus a small delta and request again.
    """
    # Normalize interval aliases
    aliases = {"1m": "1min", "1min": "1min", "1h": "1hour", "1hour": "1hour", "1d": "1day", "1day": "1day"}
    norm_interval = aliases.get(interval)
    if not norm_interval:
        raise HTTPException(status_code=422, detail="Invalid interval; use one of 1min,1hour,1day (aliases: 1m,1h,1d)")

    q = HistoryQuery(start_date=start_date, end_date=end_date, interval=Interval(value=norm_interval), limit=limit)
    try:
        q.validate_range()
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    pool: asyncpg.Pool = app.state.pool

    if q.interval.bucket is None:
        # No aggregation: fetch most recent first, then reorder ascending for chart consumption
        sql = (
            "SELECT * FROM (\n"
            "  SELECT \"timestamp\" AS ts, open, high, low, close, volume\n"
            "  FROM financial_data\n"
            "  WHERE ticker = $1\n"
            "    AND ($2::timestamptz IS NULL OR \"timestamp\" >= $2)\n"
            "    AND ($3::timestamptz IS NULL OR \"timestamp\" <= $3)\n"
            "  ORDER BY ts DESC\n"
            "  LIMIT $4\n"
            ") sub ORDER BY ts ASC"
        )
        params = (ticker, q.start_date, q.end_date, q.limit)
    else:
        # Aggregation with time_bucket in DB; select most recent buckets and then reorder ASC
        sql = (
            "WITH filt AS (\n"
            "  SELECT \"timestamp\", open, high, low, close, volume\n"
            "  FROM financial_data\n"
            "  WHERE ticker = $1\n"
            "    AND ($2::timestamptz IS NULL OR \"timestamp\" >= $2)\n"
            "    AND ($3::timestamptz IS NULL OR \"timestamp\" <= $3)\n"
            "), agg AS (\n"
            "  SELECT\n"
            "    time_bucket($4::interval, \"timestamp\") AS ts,\n"
            "    (ARRAY_AGG(open  ORDER BY \"timestamp\" ASC))[1]   AS open,\n"
            "    MAX(high)                                         AS high,\n"
            "    MIN(low)                                          AS low,\n"
            "    (ARRAY_AGG(close ORDER BY \"timestamp\" DESC))[1]  AS close,\n"
            "    SUM(volume)                                       AS volume\n"
            "  FROM filt\n"
            "  GROUP BY ts\n"
            ")\n"
            "SELECT * FROM (SELECT ts, open, high, low, close, volume FROM agg ORDER BY ts DESC LIMIT $5) sub ORDER BY ts ASC"
        )
        params = (ticker, q.start_date, q.end_date, q.interval.bucket, q.limit)

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    if not rows:
        raise HTTPException(status_code=404, detail="Ticker not found or no data in the requested range")

    data = [
        Candle(
            timestamp=row["ts"],
            open=row.get("open"),
            high=row.get("high"),
            low=row.get("low"),
            close=row.get("close"),
            volume=row.get("volume"),
        )
        for row in rows
    ]
    return HistoryResponse(ticker=ticker.upper(), interval=q.interval.value, count=len(data), data=data)


@app.get("/v1/symbols", response_model=SymbolsResponse)
async def get_symbols():
    pool: asyncpg.Pool = app.state.pool
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT DISTINCT ticker FROM financial_data ORDER BY ticker ASC")
    symbols = [r["ticker"] for r in rows]
    return SymbolsResponse(symbols=symbols)


# ----------------------
# WebSocket: /v1/stream
# ----------------------
@app.websocket("/v1/stream")
async def websocket_stream(ws: WebSocket):
    await manager.connect(ws)
    try:
        # Expect initial subscription message
        initial = await ws.receive_json()
        if not isinstance(initial, dict) or initial.get("action") != "subscribe":
            await ws.send_json({"type": "error", "message": "First message must be a subscribe action"})
        else:
            tickers = initial.get("tickers") or []
            if not isinstance(tickers, list) or not tickers:
                await ws.send_json({"type": "error", "message": "tickers must be a non-empty list"})
            else:
                interval = initial.get("interval", "1min")
                if interval not in ("1min", "1hour", "1day"):
                    interval = "1min"
                await manager.subscribe(ws, tickers, interval)
                # Optionally push the latest candle immediately
                try:
                    pool: asyncpg.Pool = app.state.pool
                    async with pool.acquire() as conn:
                        for t in [t.upper() for t in tickers]:
                            candle = await _fetch_latest_candle(conn, t, interval)
                            if candle:
                                await ws.send_json(
                                    {
                                        "type": "candle",
                                        "ticker": t,
                                        "interval": interval,
                                        "data": {
                                            "timestamp": candle.timestamp.isoformat(),
                                            "open": candle.open,
                                            "high": candle.high,
                                            "low": candle.low,
                                            "close": candle.close,
                                            "volume": candle.volume,
                                        },
                                    }
                                )
                except Exception:
                    pass
        # Continue handling messages (subscribe/unsubscribe)
        while True:
            msg = await ws.receive_json()
            if not isinstance(msg, dict):
                continue
            action = msg.get("action")
            if action == "subscribe":
                tickers = msg.get("tickers") or []
                interval = msg.get("interval", "1min")
                await manager.subscribe(ws, tickers, interval)
            elif action == "unsubscribe":
                tickers = msg.get("tickers") or []
                await manager.unsubscribe(ws, tickers)
            elif action == "ping":
                await ws.send_json({"type": "pong"})
            else:
                await ws.send_json({"type": "error", "message": "Unknown action"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("WebSocket error: %s", str(e))
    finally:
        await manager.disconnect(ws)

