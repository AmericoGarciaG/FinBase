# FinBase Collector - Yahoo Finance

A production-ready microservice that collects financial data from Yahoo Finance and publishes it to RabbitMQ in the FinBase canonical format.

## 🚀 Overview

This microservice is part of the **FinBase - The Open Ledger** project, a mission to create the first open, collaborative, and free global database of financial assets. The `collector-yfinance` service:

- Fetches real-time and historical financial data from Yahoo Finance using the `yfinance` Python library
- Transforms data into the FinBase canonical JSON format
- Publishes data to RabbitMQ with reliability guarantees (persistent messages, publisher confirms)
- Runs continuously with configurable intervals
- Provides robust error handling and automatic reconnection

## 🏗️ Architecture

```
┌─────────────────┐    ┌──────────────┐    ┌─────────────────┐
│  Yahoo Finance  │ -> │ collector-   │ -> │   RabbitMQ      │
│     (yfinance)  │    │ yfinance     │    │ raw_data_queue  │
└─────────────────┘    └──────────────┘    └─────────────────┘
```

## 📊 Canonical Data Format

All data is published in the following JSON format:

```json
{
  "ticker_symbol": "AAPL",
  "timestamp_utc": "2023-10-27T14:30:00Z",
  "open": 170.3,
  "high": 170.5,
  "low": 170.1,
  "close": 170.2,
  "volume": 500000,
  "metadata": {
    "source": "yfinance",
    "fetch_timestamp_utc": "2023-10-27T14:31:05.123Z"
  }
}
```

### Field Specifications

- **`ticker_symbol`**: Stock symbol (e.g., "AAPL", "MSFT")
- **`timestamp_utc`**: Bar/candle timestamp in UTC with seconds precision
- **`open/high/low/close`**: OHLC prices as floating-point numbers
- **`volume`**: Trading volume as integer
- **`metadata.source`**: Always "yfinance" for this collector
- **`metadata.fetch_timestamp_utc`**: Data fetch time in UTC with millisecond precision

## ⚡ Quick Start

### Prerequisites

- Docker and Docker Compose
- Git

### 1. Clone and Setup

```bash
git clone <repository-url>
cd collector-yfinance

# Copy environment template and customize
cp .env.example .env
# Edit .env with your preferred settings
```

### 2. Configure Environment

Edit `.env` file:

```bash
# RabbitMQ connection
RABBITMQ_HOST=rabbitmq

# Tickers to collect (comma-separated)
TICKERS=AAPL,MSFT,GOOGL,TSLA,NVDA

# Fetch interval in seconds
FETCH_INTERVAL_SECONDS=60
```

### 3. Start Services

```bash
# Start both RabbitMQ and collector
docker compose up --build

# Or run in background
docker compose up --build -d
```

### 4. Verify Operation

- **Logs**: Watch the collector logs for successful data publishing
- **RabbitMQ UI**: Visit http://localhost:15672 (guest/guest) to see message flow
- **Queue**: Check that `raw_data_queue` exists and receives messages

### 5. Stop Services

```bash
# Graceful shutdown
docker compose down
```

## 📁 Project Structure

```
collector-yfinance/
├── main.py              # Main application logic
├── requirements.txt     # Python dependencies
├── .env.example        # Environment variables template
├── .env               # Your local environment (not in git)
├── Dockerfile         # Multi-stage production container
├── docker-compose.yml # Local development orchestration
└── README.md         # This file
```

## 🔧 Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RABBITMQ_HOST` | `localhost` | RabbitMQ server hostname |
| `RABBITMQ_PORT` | `5672` | RabbitMQ AMQP port |
| `RABBITMQ_USER` | `guest` | RabbitMQ username |
| `RABBITMQ_PASSWORD` | `guest` | RabbitMQ password |
| `RAW_QUEUE_NAME` | `raw_data_queue` | Target queue name |
| `TICKERS` | `AAPL,MSFT` | Comma-separated ticker symbols |
| `FETCH_INTERVAL_SECONDS` | `60` | Data collection interval |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |

### Advanced Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `RABBITMQ_HEARTBEAT` | `30` | Connection heartbeat interval |
| `RABBITMQ_BLOCKED_TIMEOUT` | `60` | Blocked connection timeout |

## 🛡️ Production Features

### Reliability
- **Exponential backoff** on connection failures
- **Automatic reconnection** on network issues
- **Publisher confirms** ensure message delivery
- **Persistent messages** survive broker restarts
- **Graceful shutdown** on SIGTERM/SIGINT

### Observability
- **Structured logging** with UTC timestamps
- **Connection status** monitoring
- **Error rate tracking** in logs
- **Performance metrics** (cycle timing)

### Security
- **Non-root container** execution
- **Multi-stage Docker build** for minimal attack surface
- **No hardcoded credentials** (environment-based config)

## 🔍 Monitoring & Debugging

### View Logs

```bash
# Real-time logs
docker compose logs -f collector

# All logs
docker compose logs
```

### RabbitMQ Management UI

1. Navigate to http://localhost:15672
2. Login: `guest` / `guest`
3. Check `raw_data_queue` for message flow
4. Use "Get Messages" to inspect payloads

### Common Issues

**Connection Failed**: Ensure RabbitMQ is running and healthy
```bash
docker compose ps
docker compose logs rabbitmq
```

**No Data for Ticker**: Check if ticker symbol is valid and markets are open
```bash
# Test ticker manually
python -c "import yfinance as yf; print(yf.Ticker('AAPL').history(period='1d', interval='1m').tail())"
```

**High Memory Usage**: Reduce `TICKERS` count or increase `FETCH_INTERVAL_SECONDS`

## 🧪 Development

### Local Python Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally (ensure RabbitMQ is available)
python main.py
```

### Testing

```bash
# Build container
docker build -t collector-yfinance .

# Test run
docker run --env-file .env collector-yfinance
```

### Code Quality

The codebase follows production best practices:
- **Type hints** for better IDE support
- **Comprehensive error handling**
- **Modular function design**
- **Clear documentation strings**
- **Configuration separation**

## 📈 Performance Considerations

- **Data Fetching**: Yahoo Finance has rate limits; default 60-second interval is conservative
- **Memory Usage**: Each ticker adds ~10MB memory footprint due to pandas/numpy dependencies
- **Network**: Outbound HTTPS to Yahoo Finance, AMQP to RabbitMQ
- **CPU**: Minimal, mostly I/O bound

### Scaling Recommendations

- **Horizontal**: Deploy multiple instances with different ticker sets
- **Vertical**: Increase memory for more tickers per instance
- **Caching**: Consider Redis for ticker metadata caching
- **Load Balancing**: Use RabbitMQ clustering for high availability

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Make your changes following the existing code style
4. Test thoroughly with Docker Compose
5. Submit a pull request

### Code Guidelines

- Follow PEP 8 Python style
- Add type hints to new functions
- Include docstrings for public methods
- Update README for configuration changes
- Test with multiple ticker symbols

## 📜 License

This project is part of the FinBase - The Open Ledger initiative, dedicated to democratizing access to financial data.

## 📞 Support

- **Issues**: Use GitHub Issues for bugs and feature requests
- **Discussions**: Join project discussions for questions and ideas
- **Documentation**: This README and inline code comments

---

**Happy Trading! 📈**

*Built with ❤️ for the open financial data community*

