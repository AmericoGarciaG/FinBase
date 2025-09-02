# tests/conftest.py
import os
import psycopg2
import pytest
from dotenv import load_dotenv

load_dotenv()

@pytest.fixture(scope="module")
def db_connection():
    """Create a database connection to be used for test setup/teardown."""
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )
    yield conn
    conn.close()
@pytest.fixture

def clean_test_ticker_data(db_connection):
    """Fixture to ensure the test ticker has no pre-existing data."""
    TEST_TICKER = "TEST.E2E"
    
    # --- Setup ---
    with db_connection.cursor() as cur:
        cur.execute("DELETE FROM financial_data WHERE ticker = %s", (TEST_TICKER,))
        db_connection.commit()
    
    yield TEST_TICKER  # El test se ejecuta aquí
    
    # --- Teardown ---
    with db_connection.cursor() as cur:
        cur.execute("DELETE FROM financial_data WHERE ticker = %s", (TEST_TICKER,))
        db_connection.commit()