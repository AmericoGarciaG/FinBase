
---

# FinBase - The Open Ledger
## The Open-Source Financial Database for Everyone

[![Status](https://img.shields.io/badge/Status-Active-brightgreen)](https://github.com/AmericoGarciaG/FinBase)
[![License](https://img.shields.io/badge/License-MIT-blue)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://python.org)
[![Docker](https://img.shields.io/badge/Docker-Ready-informational)](https://docker.com)
[![Tests](https://img.shields.io/badge/Tests-E2E%20Ready-success)](./tests)

---

## 🚀 Our Mission: Democratizing Financial Data

**FinBase** is an ambitious open-source initiative to build the world's first global, collaborative, and free financial asset database. We are creating a foundational layer of high-quality, accessible data to empower researchers, developers, and independent traders everywhere.

## ✨ Core Principles

| Principle | Description |
|-----------|-------------|
| **Open & Free Access** | Financial data available to everyone, without paywalls or closed barriers. |
| **Community Driven** | A project built by the community, for the community. |
| **Quality & Transparency**| High standards for data validation, cleaning, and traceability. |
| **Scalable Architecture** | A solid technological foundation designed to grow with demand. |
| **Constant Evolution** | From using third-party data to becoming a primary, reliable source. |

## ⚡ Quick Start: See it in Action!

### 1. Prerequisites
- Docker & Docker Compose

### 2. Launch the Entire System
From the root of the project, run one command:
```bash
docker compose up --build -d
```
This will build and start all 7 microservices in the correct order.

### 3. Explore the FinBase Ecosystem
Once everything is running, you can access the full platform:

-   **📈 Live Charting UI:** Open your browser to **[http://localhost:8080](http://localhost:8080)**
-   **📖 API Documentation:** Explore the interactive API docs at **[http://localhost:8000/docs](http://localhost:8000/docs)**
-   **📬 Message Queue Admin:** Monitor the data flow in RabbitMQ at **[http://localhost:15672](http://localhost:15672)** (user: `guest`, pass: `guest`)

## 🧠 System Architecture

FinBase is built on a decoupled microservices architecture. It features two primary data flows: a real-time ingestion pipeline and an on-demand historical backfilling system.

#### Live Data Flow
```
[collector-yfinance] -> [raw_data_queue] -> [quality-service] -> [clean_data_queue] -> [storage-service] -> [finbase-db]
```

#### Backfill Flow
```
[User via API] -> [api-service] -> [backfill_jobs_queue] -> [backfill-worker] -> [raw_data_queue] (re-joins main flow)
```

#### Data Access Flow
```
[finbase-db] <--> [api-service] <--> [frontend-service] / [External Apps]
```

## 📦 Microservices Ecosystem

This monorepo contains all microservices that power the FinBase ecosystem.

| Service | Status | Description |
|---------|--------|-------------|
| **[`collector-yfinance`](services/collector-yfinance)** | ✅ **Active** | Continuously fetches the latest market data. |
| **[`quality-service`](services/quality-service)** | ✅ **Active** | The gatekeeper for data integrity and validation. |
| **[`storage-service`](services/storage-service)** | ✅ **Active** | Efficiently persists clean data into the TimescaleDB. |
| **[`api-service`](services/api-service)** | ✅ **Active** | Exposes data via a high-performance REST & WebSocket API. |
| **[`backfill-worker`](services/backfill-worker-service)**| ✅ **Active** | Executes on-demand historical data backfilling jobs. |
| **[`frontend-service`](services/frontend-service)** | ✅ **Active** | An interactive charting UI built with React & TradingView. |
| **`rabbitmq` / `finbase-db`** | ✅ **Active**| Core infrastructure for messaging and storage. |

## 🔧 Tech Stack

- **Backend**: Python 3.11+, FastAPI, Pydantic
- **Frontend**: React, Vite, TypeScript, Nginx
- **Database**: TimescaleDB (PostgreSQL for time-series)
- **Message Bus**: RabbitMQ
- **Containerization**: Docker & Docker Compose
- **Testing**: Pytest

## 🧪 End-to-End Testing

The project includes a comprehensive End-to-End (E2E) test suite that validates the entire backfilling pipeline, from API request to data verification.

To run the tests after starting the system:
```bash
# 1. Copy test files into the running api-service container
docker cp ./tests api-service:/tmp/

# 2. Execute pytest inside the container
docker exec api-service python -m pytest -v /tmp/tests/
```

## 🗺️ Project Roadmap

### ✅ Phase 1: Core System (Completed)
-   Real-time data ingestion pipeline.
-   Robust, on-demand historical backfilling system.
-   High-performance API with REST and WebSocket support.
-   Interactive charting front-end.
-   Fully containerized, one-command deployment.
-   End-to-End testing framework.

### ➡️ Phase 2: Expansion & Hardening (Next Steps)
-   **Add More Data Providers:** Integrate new collectors and backfill providers (e.g., Binance for crypto, other stock exchanges).
-   **Implement Caching:** Add a Redis layer to the `api-service` for enhanced performance.
-   **CI/CD Pipeline:** Automate testing and deployment using GitHub Actions.
-   **User Authentication:** Secure the frontend and parts of the API.

## 🤝 How to Contribute

We need creative minds, technical contributions, and allies who believe in our mission!

1.  **Fork** the repository.
2.  **Create** a feature branch (`git checkout -b feature/amazing-feature`).
3.  **Implement** your changes and add tests.
4.  **Submit** a Pull Request for review.

Check out our [Issues](https://github.com/AmericoGarciaG/FinBase/issues) tab for tasks labeled `good first issue`!

## 📄 License

This project is licensed under the **MIT License**. See the [LICENSE](LICENSE) file for details.

---

### 🎉 Join Us in Building the Future of Open Financial Data!

**FinBase** is more than a database; it's a movement to create a level playing field for financial innovation.

**Explore the code and become a contributor today!** 🚀