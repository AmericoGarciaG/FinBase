
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

## ✨ Core Features & Principles

| Feature | Description |
|-----------|-------------|
| **🧠 Intelligent Backfilling**| Automatically detects existing data gaps and only fetches what's missing. |
| **⚡ Real-Time Streaming**| WebSocket API provides live market data as it arrives. |
| **🛡️ Robust & Scalable** | A decoupled microservices architecture built for reliability and growth. |
| **✅ Data Quality Pipeline**| All incoming data is automatically validated against a set of business rules. |
| **🌐 Open & Free Access**| Financial data available to everyone, without paywalls. |
| **🤝 Community Driven** | A project built by the community, for the community. |


## ⚡ Quick Start: See it in Action!

### 1. Prerequisites
- Docker & Docker Compose

### 2. Launch the Entire System
From the root of the project, run one command:
```bash
docker compose up --build -d
```
This will build and start all microservices in the correct order.

### 3. Explore the FinBase Ecosystem
Once everything is running, you can access the full platform:

-   **📈 Live Charting UI:** Open your browser to **[http://localhost:8080](http://localhost:8080)**
-   **🎛️ Admin Panel:** Manage backfill jobs with our intelligent orchestrator at **[http://localhost:8081](http://localhost:8081)**
-   **📖 API Documentation:** Explore the interactive API docs at **[http://localhost:8000/docs](http://localhost:8000/docs)**
-   **📬 Message Queue Admin:** Monitor the data flow in RabbitMQ at **[http://localhost:15672](http://localhost:15672)** (user: `guest`, pass: `guest`)

## 🧠 System Architecture

FinBase is built on a decoupled microservices architecture featuring an intelligent job orchestrator. Large backfill requests are automatically analyzed and broken down into smaller, manageable tasks.

#### Intelligent Backfill Flow (Master/Sub-Job Architecture)
```
[User Request] -> [api-service: Coverage Planner] -> [Master Job Creation]
                     |
[Gap Detection] -> [Sub-Job Fragmentation] -> [backfill_jobs_queue] -> [backfill-worker]
                     |
[Sub-Job Processing] -> [raw_data_queue] (re-joins main flow) -> [Master Job Completion]
```

#### Live Data & Access Flow
```
[Data Sources] -> [collector-yfinance] -> [raw_data_queue] -> [quality-service] -> [clean-data_queue]
                                                                                          |
                                                                                          v
[finbase-db] <- [storage-service] <-> [api-service] <-> [frontend-service] / [admin-frontend]
```

## 📦 Microservices Ecosystem

This monorepo contains all microservices that power the FinBase ecosystem.

| Service | Status | Description |
|---------|--------|-------------|
| **`api-service`** | ✅ **Active** | The central orchestrator and data gateway (REST & WebSocket). |
| **`frontend-service`** | ✅ **Active** | Interactive charting UI built with React & TradingView Charts. |
| **`admin-frontend`** | ✅ **Active** | Web UI to manage and monitor the intelligent backfilling system. |
| **`backfill-worker-service`**| ✅ **Active** | Executes fragmented backfill sub-jobs from various providers. |
| **`collector-yfinance`** | ✅ **Active** | Continuously fetches the latest live market data. |
| **`quality-service`** | ✅ **Active** | The gatekeeper for data integrity and validation. |
| **`storage-service`** | ✅ **Active** | Efficiently persists clean data into the TimescaleDB. |

## 🧪 End-to-End Testing

The project includes a comprehensive E2E test suite that validates the entire backfilling pipeline, from API request to data verification, including the synthetic data generation for tests.

To run the tests after starting the system:
```bash
# 1. Copy test files into the running api-service container
docker cp ./tests api-service:/tmp/

# 2. Execute pytest inside the container
docker exec api-service python -m pytest -v /tmp/tests/
```

## 🗺️ Project Roadmap

### ✅ Phase 1: Core System & Intelligent Job Management (Completed)
-   Real-time data ingestion pipeline.
-   **Intelligent backfilling system with gap detection and job fragmentation.**
-   High-performance API with REST and WebSocket support.
-   Interactive charting front-end and a separate admin panel.
-   Fully containerized, one-command deployment.
-   End-to-End testing framework with synthetic data generation.

### ➡️ Phase 2: Expansion & Hardening (Next Steps)
-   **Add More Data Providers:** Integrate new collectors and backfill providers (e.g., for cryptocurrency, other stock exchanges).
-   **Implement Caching:** Add a Redis layer to the `api-service` for enhanced performance.
-   **CI/CD Pipeline:** Automate testing and deployment using GitHub Actions.
-   **User Authentication:** Secure the frontend and parts of the API for multi-user environments.

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
