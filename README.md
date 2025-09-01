
---

```markdown
# FinBase - The Open Ledger


<!-- Replace the URL above with your final logo URL when you have it -->

**Mission: To build the first open, collaborative, and free global database of financial assets, democratizing access to high-quality information.**

[![Estado del Proyecto](https://img.shields.io/badge/estado-en%20desarrollo-green.svg)](https://github.com/AmericoGarciaG/FinBase)
[![Licencia](https://img.shields.io/badge/licencia-MIT-blue.svg)](./LICENSE)
[![GitHub Issues](https://img.shields.io/github/issues/AmericoGarciaG/FinBase.svg)](https://github.com/AmericoGarciaG/FinBase)


---

## Manifesto: The Open Financial Database

We believe that financial knowledge should not be restricted to a select few. Information is power, and access to it defines who can innovate, research, and shape the future of finance.

Today, existing open sources—like Yahoo Finance and other free databases—are limited, incomplete, and unreliable. And premium sources, while powerful, are reserved for those who can afford prohibitive prices. This creates an unfair gap between those who have access to quality data and those who do not.

**We want to change that.**

### Our Vision

To build the first global, open, and collaborative financial asset database, designed to be free, scalable, and universally accessible. A living, transparent space that will, over time, become the trusted reference for financial information, available to researchers, developers, independent traders, students, and curious minds from all over the world.

### Our Commitment

-   **Free and Open Access:** Financial data available to everyone, without paywalls or closed barriers.
-   **Quality and Transparency:** High standards for data validation and traceability.
-   **Community Collaboration:** A project built by the community, for the community.
-   **Organic Scalability:** A solid technological architecture that will grow with demand.
-   **Constant Evolution:** From using third-party data to becoming a primary, direct, and reliable source.

---

## 🏗️ System Architecture

FinBase is built on a decoupled microservices architecture, with components communicating via a message bus (RabbitMQ). This design ensures that each component is independent, replaceable, and scalable.

```
[Data Sources] -> [Collectors] -> [Raw Data Queue] -> [Quality Service] -> [Clean Data Queue] -> [Storage Service] -> [Database] -> [API] -> [Users]
```

The project itself is a laboratory to discover the most efficient, optimal, and cutting-edge way to store, control, access, and extract financial information with minimal resources.

## 📦 Microservices

This repository contains all the microservices that make up the FinBase ecosystem. Each service resides in its own folder within the `/services` directory.

| Service                                                      | Language | Description                                 | Status              |
| :----------------------------------------------------------- | :------- | :------------------------------------------ | :------------------ |
| [`services/collector-yfinance`](./services/collector-yfinance) | Python   | Data collector for Yahoo Finance.           | ✅ **Active**       |
| `services/quality-service`                                   | Python   | Data validator and cleaner.                 | 🚧 In Development |
| `services/storage-service`                                   | Python   | Storage service for TimescaleDB.            | 📝 Planned        |
| `services/api-service`                                       | Python   | REST/WebSocket API for data access.         | 📝 Planned        |

## ⚡ Quick Start Guide

### Prerequisites

-   [Git](https://git-scm.com/)
-   [Docker](https://www.docker.com/) & [Docker Compose](https://docs.docker.com/compose/)

### 1. Clone the Repository

```bash
git clone https://github.com/AmericoGarciaG/FinBase.git
cd finbase
```

### 2. Run an Individual Service

Each microservice can be run independently for development and testing. For example, to launch the Yahoo Finance collector:

```bash
# Navigate to the service's directory
cd services/collector-yfinance

# Create your .env file from the example
cp .env.example .env

# (Optional) Edit the .env file to change tickers or the fetch interval

# Launch the service and its dependency (RabbitMQ)
docker compose up --build
```
For more details, please refer to the `README.md` file inside each service's directory.

*(A root `docker-compose.yml` file will be added later to orchestrate the entire system with a single command.)*

## 🤝 How to Contribute

This project is yours too! We need creative minds, technical contributions, fresh ideas, and allies who believe in our mission.

1.  **Explore the Issues:** The best place to start is our [Issues board](https://github.com/AmericoGarciaG/FinBase/issues). Look for labels like `good first issue` or `help wanted`.
2.  **Start a Discussion:** If you have an idea or a question, open a [Discussion](https://github.com/AmericoGarciaG/FinBase/discussions).
3.  **Submit a Pull Request:**
    -   Fork the repository.
    -   Create a new branch for your feature (`git checkout -b feature/feature-name`).
    -   Make your changes and commit them (`git commit -m 'feat: Add some amazing feature'`).
    -   Push your branch (`git push origin feature/feature-name`).
    -   Open a Pull Request.

We are working on a more detailed contribution guide. In the meantime, don't hesitate to get involved!

## 📜 License

This project is distributed under the **MIT License**. See the [LICENSE](./LICENSE) file for more details.
```