## Testing & Development Notes

- Live collector vs backfill worker
  - collector_service continuously fetches recent live market data from yfinance and publishes it into RabbitMQ (raw_data_queue). That stream then flows through quality_service and storage_service into finbase-db.
  - backfill_worker processes historical data sub-jobs created by the api-service’s intelligent planner. It publishes raw historical candles to the same raw_data_queue.

- Isolating backfill testing
  - When developing or testing the backfill pipeline in isolation, it’s often helpful to disable the live collector so your pipeline only handles the sub-jobs you submit.
  - To temporarily disable the collector, comment out the entire collector_service section in docker-compose.yml. This prevents live data from mixing with your backfill and makes it easier to observe the sub-job processing and provider reputation effects.

- Health checks and service readiness
  - The api-service exposes GET /health for lightweight health checks used by docker-compose.
  - The admin_frontend waits for the api-service to be healthy before starting up, reducing race conditions on first load.

- Admin frontend connection retries
  - The Admin Panel now attempts up to 3 times to connect to the API on startup with a short delay between attempts. If it can’t connect, it shows a persistent error message so you can check backend services.

