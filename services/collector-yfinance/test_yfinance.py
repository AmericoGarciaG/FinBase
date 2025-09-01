#!/usr/bin/env python3
"""
Simple test script to verify yfinance connectivity and data availability.
This helps diagnose issues before running the full microservice.
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timezone

def test_ticker(ticker):
    """Test a single ticker for data availability."""
    print(f"\n=== Testing ticker: {ticker} ===")
    
    try:
        # Create ticker object
        stock = yf.Ticker(ticker)
        
        # Test 1: Get basic info
        print("1. Getting basic info...")
        info = stock.info
        if info:
            print(f"   Company: {info.get('longName', 'N/A')}")
            print(f"   Current price: {info.get('regularMarketPrice', 'N/A')}")
            print(f"   Market state: {info.get('marketState', 'N/A')}")
        else:
            print("   No basic info available")
        
        # Test 2: Get recent 1-day, 1-minute data
        print("2. Getting 1-minute data for today...")
        df = stock.history(period="1d", interval="1m", auto_adjust=False, prepost=False, repair=True)
        
        if df is None:
            print("   ERROR: Received None from yfinance")
            return False
        elif df.empty:
            print("   WARNING: Received empty DataFrame")
            return False
        else:
            print(f"   Got {len(df)} data points")
            print(f"   Date range: {df.index[0]} to {df.index[-1]}")
            
            # Show last few entries
            print("   Last 3 entries:")
            last_entries = df.tail(3)
            for idx, row in last_entries.iterrows():
                print(f"     {idx}: O={row['Open']:.2f} H={row['High']:.2f} L={row['Low']:.2f} C={row['Close']:.2f} V={row['Volume']}")
        
        # Test 3: Try to get 5-day data as fallback
        print("3. Getting 5-day data as fallback...")
        df_5d = stock.history(period="5d", interval="1d", auto_adjust=False)
        if not df_5d.empty:
            print(f"   5-day data available: {len(df_5d)} days")
        else:
            print("   No 5-day data available")
        
        return True
        
    except Exception as e:
        print(f"   ERROR: {str(e)}")
        return False

def main():
    """Test multiple tickers to check yfinance connectivity."""
    print("Yahoo Finance Connectivity Test")
    print("=" * 50)
    
    # Test tickers from our configuration
    test_tickers = ["AAPL", "MSFT", "GOOGL"]
    
    # Also test some additional known good tickers
    additional_tickers = ["NVDA", "TSLA", "SPY"]
    
    results = {}
    
    # Test main tickers
    print("\nTesting main tickers:")
    for ticker in test_tickers:
        results[ticker] = test_ticker(ticker)
    
    # Test additional tickers for comparison
    print("\nTesting additional tickers for comparison:")
    for ticker in additional_tickers:
        results[ticker] = test_ticker(ticker)
    
    # Summary
    print("\n" + "=" * 50)
    print("SUMMARY:")
    print("=" * 50)
    
    successful = [ticker for ticker, success in results.items() if success]
    failed = [ticker for ticker, success in results.items() if not success]
    
    print(f"Successful: {len(successful)} - {', '.join(successful) if successful else 'None'}")
    print(f"Failed: {len(failed)} - {', '.join(failed) if failed else 'None'}")
    
    if failed:
        print("\nPossible issues:")
        print("- Yahoo Finance API may be experiencing issues")
        print("- Rate limiting may be in effect")
        print("- Network connectivity issues")
        print("- Some tickers may be delisted or invalid")
        print("- yfinance library may need updating")
    else:
        print("\nAll tests passed! Yahoo Finance connectivity appears to be working.")

if __name__ == "__main__":
    main()
