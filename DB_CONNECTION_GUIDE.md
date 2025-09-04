# FinBase Database Connection Guide

This guide provides step-by-step instructions to connect to the FinBase TimescaleDB database using DBeaver or any other PostgreSQL-compatible database client.

## Database Configuration Overview

The FinBase project uses TimescaleDB (PostgreSQL extension) running in a Docker container. The database is configured to accept external connections for development and administration purposes.

## Connection Parameters

Use the following parameters to connect to the FinBase database:

| Parameter | Value |
|-----------|-------|
| **Host** | `localhost` (or `127.0.0.1`) |
| **Port** | `5433` |
| **Database** | `finbase` |
| **Username** | `finbase` |
| **Password** | `supersecretpassword` |
| **Driver** | PostgreSQL |

## DBeaver Connection Setup

### Step 1: Create New Connection

1. Open DBeaver
2. Click on "New Database Connection" (plug icon) or go to `Database → New Database Connection`
3. Select **PostgreSQL** from the list of database types
4. Click **Next**

### Step 2: Configure Connection Settings

Fill in the **Main** tab with the following details:

```
Server Host: localhost
Port: 5433
Database: finbase
Username: finbase
Password: supersecretpassword
```

### Step 3: Authentication Method

- Select **"Database Native"** as the authentication type
- Ensure the username and password are correctly entered as shown above

### Step 4: Test Connection

1. Click **Test Connection** to verify the configuration
2. DBeaver should show "Connected" if everything is configured correctly
3. If the connection fails, ensure that:
   - Docker containers are running (`docker-compose up -d`)
   - The `finbase-db` container is healthy
   - Port 5433 is not blocked by firewall

### Step 5: Save and Connect

1. Click **Finish** to save the connection
2. The connection will appear in the Database Navigator
3. Double-click to connect to the database

## Verifying Database Access

Once connected, you can verify the database setup by running the following test queries:

### Basic Database Information
```sql
-- Check database version and TimescaleDB extension
SELECT version();
SELECT * FROM pg_extension WHERE extname = 'timescaledb';
```

### Check Available Tables
```sql
-- List all tables in the finbase database
SELECT table_name, table_type 
FROM information_schema.tables 
WHERE table_schema = 'public';
```

### Sample Data Query
```sql
-- Check financial data (if any exists)
SELECT ticker, COUNT(*) as record_count, 
       MIN(timestamp) as earliest_record,
       MAX(timestamp) as latest_record
FROM financial_data 
GROUP BY ticker 
ORDER BY ticker;
```

### Monitor Backfill Jobs
```sql
-- Check backfill jobs status
SELECT job_id, ticker, provider, start_date, end_date, status, created_at
FROM backfill_jobs 
ORDER BY created_at DESC 
LIMIT 10;
```

## Docker Container Management

### Starting the Database
```bash
# Start all services
docker-compose up -d

# Start only the database
docker-compose up -d finbase-db
```

### Checking Database Health
```bash
# Check if the database container is running and healthy
docker-compose ps finbase-db

# View database logs
docker-compose logs finbase-db
```

### Stopping the Database
```bash
# Stop all services
docker-compose down

# Stop only the database (keeping data)
docker-compose stop finbase-db
```

## Troubleshooting

### Connection Refused
- **Issue**: "Connection refused" or "Could not connect"
- **Solution**: 
  1. Verify containers are running: `docker-compose ps`
  2. Check if port 5433 is exposed: `docker port finbase-db`
  3. Ensure no other PostgreSQL instance is using port 5433

### Authentication Failed
- **Issue**: "Authentication failed" or "Invalid credentials"
- **Solution**: 
  1. Double-check username: `finbase`
  2. Double-check password: `supersecretpassword`
  3. Verify environment variables in docker-compose.yml

### Database Does Not Exist
- **Issue**: "Database 'finbase' does not exist"
- **Solution**: 
  1. Check container logs: `docker-compose logs finbase-db`
  2. Recreate the database container: `docker-compose down finbase-db && docker-compose up -d finbase-db`

### Port Already in Use
- **Issue**: "Port already in use"
- **Solution**: 
  1. The current configuration uses port 5433 to avoid conflicts with local PostgreSQL installations
  2. If you still have conflicts, stop any competing service or change the port mapping in docker-compose.yml

## Security Considerations

⚠️ **Important**: The current configuration uses default credentials suitable for development environments only.

**For Production Deployment:**
- Change the default password in environment variables
- Use Docker secrets or environment files for sensitive data
- Consider restricting port exposure
- Implement proper firewall rules
- Use SSL/TLS connections

## Database Schema Information

The FinBase database includes the following main tables:

- **`financial_data`**: Time-series financial market data (TimescaleDB hypertable)
- **`backfill_jobs`**: Job tracking for historical data backfilling
- **`data_quality_metrics`**: Quality control metrics and validation results

For detailed schema information, explore the tables using DBeaver's object browser or check the initialization script at `services/storage-service/init.sql`.

---

**Last Updated**: January 2025  
**Compatible with**: TimescaleDB 2.14.2, PostgreSQL 15, DBeaver 23.x+
