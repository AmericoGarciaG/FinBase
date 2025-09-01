
---

### 3. `README.md` for `services/quality-service`

```markdown
# FinBase Service: quality-service
## The Guardian of Data Integrity

[![Status](https://img.shields.io/badge/Status-Active-brightgreen)](./)
[![Python](https://img.shields.io/badge/Python-3.11+-blue)](./)
[![Docker](https://img.shields.io/badge/Docker-Ready-informational)](./Dockerfile)

---

## 🚀 Overview

The `quality-service` acts as the critical gatekeeper in the FinBase data pipeline. It consumes raw data, applies a rigorous set of validation rules, and routes messages based on their validity, ensuring that only high-quality, coherent data proceeds to storage.

## ✨ Key Features

| Feature | Description |
|---------|-------------|
| **Rule-Based Validation** | Applies a configurable set of rules to every incoming message. |
| **Message Routing** | Segregates data into `clean` and `invalid` queues for processing. |
| **Lossless Processing** | Uses message acknowledgments (`ack`) to guarantee no data is lost. |
| **High Throughput** | Designed to be a lightweight and fast processing step. |
| **Extensible Design** | New validation rules can be easily added in the `rules.py` module. |

## ⚡ Quick Start

This service is typically run as part of a larger `docker-compose` setup in the project root. To run it standalone for testing:

### 1. Setup Environment

```bash
# From this directory (services/quality-service)
# Create your local environment file
cp .env.example .env

# The default queue names are usually sufficient
# INPUT_QUEUE=raw_data_queue
# VALID_QUEUE=clean_data_queue
```

### 2. Run with Docker Compose

```bash
# This requires a running RabbitMQ instance
# (Best to use the main docker-compose file)
docker compose up --build
```

## 🧠 Architecture & Data Flow

This service consumes from one queue and publishes to two different ones, acting as a smart filter.

```
                         ┌───────────────────┐
┌──────────────────┐     │ quality-service   │
│ raw_data_queue   ├────►│                   │
└──────────────────┘     └───────────────────┘
                                  │
      ┌───────────────────────────┴──────────────────────────┐
      ▼ (If Valid)                                           ▼ (If Invalid)
┌──────────────────┐                                   ┌────────────────────┐
│ clean_data_queue │                                   │ invalid_data_queue │
└──────────────────┘                                   └────────────────────┘
```

## ⚖️ Validation Rules

The service currently implements the following rules:

1.  **Structural Integrity**: Ensures all required fields exist and are not null.
2.  **OHLC Coherence**: Verifies that `High >= {Open, Close}` and `Low <= {Open, Close}`.
3.  **Non-Negative Values**: Checks that all price and volume fields are `> 0`.

## 🔧 Configuration

All settings (RabbitMQ connection, queue names) are managed via environment variables. See `.env.example` for details.

## 🔍 Monitoring & Debugging

-   **View Logs**: `docker compose logs -f quality_service`
-   **RabbitMQ UI**: Access [http://localhost:15672](http://localhost:15672) to watch messages move from `raw_data_queue` to `clean_data_queue` or `invalid_data_queue`.

## 🤝 Contributing

Have ideas for new validation rules or performance improvements? Please follow the contribution guidelines in the main project README.
```