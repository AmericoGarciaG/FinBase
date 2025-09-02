# tests/test_e2e_backfill.py
import os
import time
import requests
from requests.exceptions import RequestException

API_BASE_URL = os.getenv("API_BASE_URL")
API_KEY = os.getenv("BACKFILL_API_KEY")

HEADERS = {"X-API-Key": API_KEY}
JOB_POLL_INTERVAL_SECONDS = 5
JOB_TIMEOUT_SECONDS = 180

def test_full_backfill_flow(clean_test_ticker_data):
    """
    End-to-end backfill flow:
    1. Submit a backfill for a test ticker.
    2. Poll the job status until completion.
    3. Verify data was inserted correctly via the history API.
    """
    TEST_TICKER = clean_test_ticker_data
    
    # --- 1. Act: Submit the backfill ---
    job_payload = {
        "ticker": TEST_TICKER,
        "provider": "yfinance",
        "start_date": "2023-01-03", # Lunes, día de trading
        "end_date": "2023-01-05",   # Miércoles, día de trading
    }
    
    print(f"Submitting backfill job for {TEST_TICKER}...")
    try:
        response = requests.post(
            f"{API_BASE_URL}/v1/backfill/jobs",
            json=job_payload,
            headers=HEADERS
        )
        response.raise_for_status() # Lanza excepción para códigos 4xx/5xx
    except RequestException as e:
        assert False, f"Failed to submit backfill job: {e}"

    assert response.status_code == 202
    job_id = response.json().get("job_id")
    assert job_id is not None
    print(f"Job submitted successfully. Job ID: {job_id}")

    # --- 2. Act: Monitor the job ---
    start_time = time.time()
    while time.time() - start_time < JOB_TIMEOUT_SECONDS:
        print(f"Polling job status for {job_id}...")
        try:
            status_response = requests.get(f"{API_BASE_URL}/v1/backfill/jobs/{job_id}", headers=HEADERS)
            status_response.raise_for_status()
        except RequestException as e:
            assert False, f"Failed to poll job status: {e}"
            
        job_status = status_response.json().get("status")
        print(f"Current job status: {job_status}")
        
        if job_status == "COMPLETED":
            break
        if job_status == "FAILED":
            error_msg = status_response.json().get("error_message")
            assert False, f"Backfill job failed with error: {error_msg}"
            
        time.sleep(JOB_POLL_INTERVAL_SECONDS)
    else:  # Executes if the while loop times out
        assert False, f"Job {job_id} did not complete within {JOB_TIMEOUT_SECONDS} seconds."

    print("Job completed successfully.")

    # --- 3. Verify: Query data ---
    print(f"Verifying data for {TEST_TICKER} via history API...")
    try:
        history_response = requests.get(
            f"{API_BASE_URL}/v1/data/history/{TEST_TICKER}",
            params={"interval": "1d"}
        )
        history_response.raise_for_status()
    except RequestException as e:
        assert False, f"Failed to fetch history for {TEST_TICKER}: {e}"
        
    data = history_response.json()
    
    # For the range 2023-01-03 to 2023-01-05, we expect 3 daily candles.
    assert data.get("count") == 3
    assert len(data.get("data", [])) == 3
    print(f"Verification successful: Found {data.get('count')} candles as expected.")