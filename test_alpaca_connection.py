#!/usr/bin/env python3
"""
Test Alpaca Paper Trading Connection

This script tests the connection to Alpaca's paper trading API and verifies
that your credentials are configured correctly.
"""

import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from config.settings import settings
from execution.broker import Broker
from monitoring.logger import setup_logger

logger = setup_logger("alpaca_test")


def _print_github_secrets_help():
    """Print help for GitHub Actions credentials issues."""
    print()
    print("If running in GitHub Actions:")
    print("  1. Repo Settings → Secrets and variables → Actions")
    print("  2. Add secrets named exactly: ALPACA_API_KEY and ALPACA_API_SECRET")
    print("  3. Use your Alpaca *paper* trading keys (https://app.alpaca.markets/paper/dashboard)")
    print("  4. Workflows on *forks* do not get access to repo secrets; run from the main repo.")
    print("  5. Remove any leading/trailing spaces when pasting secrets.")
    print()


def test_alpaca_connection():
    """Test Alpaca paper trading connection."""
    print("=" * 60)
    print("ALPACA PAPER TRADING CONNECTION TEST")
    print("=" * 60)
    print()
    
    # Check configuration
    print("📋 Configuration Check:")
    print(f"  API Key: {'✓ Set' if settings.broker.api_key else '✗ Missing'}")
    print(f"  API Secret: {'✓ Set' if settings.broker.api_secret else '✗ Missing'}")
    print(f"  Base URL: {settings.broker.base_url}")
    print(f"  Paper Trading: {settings.broker.use_paper}")
    print()
    
    if not settings.broker.api_key or not settings.broker.api_secret:
        print("❌ ERROR: API credentials not configured!")
        print()
        print("Please create a .env file with your Alpaca credentials:")
        print("  ALPACA_API_KEY=your_api_key_here")
        print("  ALPACA_API_SECRET=your_api_secret_here")
        print("  ALPACA_BASE_URL=https://paper-api.alpaca.markets")
        print()
        print("Get your paper trading API keys from:")
        print("  https://app.alpaca.markets/paper/dashboard/overview")
        return False
    
    # Initialize broker
    print("🔌 Initializing Broker...")
    try:
        broker = Broker()
    except Exception as e:
        print(f"❌ ERROR: Failed to initialize broker: {e}")
        _print_github_secrets_help()
        return False

    if not broker.api:
        print("❌ ERROR: Failed to initialize broker API")
        print("Check your credentials and network connection.")
        _print_github_secrets_help()
        return False

    print("✓ Broker initialized successfully")
    print()

    # Test account connection
    print("📊 Testing Account Connection...")
    try:
        account = broker.get_account()
        if account:
            print("✓ Account connection successful!")
            print()
            print("Account Information:")
            print(f"  Equity: ${account['equity']:,.2f}")
            print(f"  Cash: ${account['cash']:,.2f}")
            print(f"  Buying Power: ${account['buying_power']:,.2f}")
            print(f"  Portfolio Value: ${account['portfolio_value']:,.2f}")
            print()
        else:
            print("❌ ERROR: Could not retrieve account information")
            return False
    except Exception as e:
        err = str(e).lower()
        print(f"❌ ERROR: {e}")
        if "401" in err or "unauthorized" in err or "invalid" in err or "credential" in err:
            _print_github_secrets_help()
        logger.error(f"Account connection error: {e}", exc_info=True)
        return False
    
    # Test positions
    print("📈 Testing Positions Retrieval...")
    try:
        positions = broker.get_positions()
        print(f"✓ Positions retrieved: {len(positions)} positions")
        if positions:
            print("  Current Positions:")
            for symbol, value in positions.items():
                print(f"    {symbol}: ${float(value):,.2f}")
        print()
    except Exception as e:
        print(f"❌ ERROR: {e}")
        logger.error(f"Positions retrieval error: {e}", exc_info=True)
        return False
    
    # Test market status
    print("🕐 Testing Market Status...")
    try:
        is_open = broker.is_market_open()
        status = "OPEN" if is_open else "CLOSED"
        print(f"✓ Market is currently: {status}")
        print()
    except Exception as e:
        print(f"❌ ERROR: {e}")
        logger.error(f"Market status error: {e}", exc_info=True)
        return False
    
    # Verify paper trading URL
    print("🔍 Verifying Paper Trading Configuration...")
    if "paper-api" in settings.broker.base_url.lower():
        print("✓ Paper trading URL confirmed")
    else:
        print("⚠️  WARNING: Not using paper trading URL!")
        print(f"   Current URL: {settings.broker.base_url}")
        print("   Paper trading URL should be: https://paper-api.alpaca.markets")
    print()
    
    print("=" * 60)
    print("✅ ALL TESTS PASSED!")
    print("=" * 60)
    print()
    print("Your Alpaca paper trading account is properly configured.")
    print("You can now execute trades using the OrderManager.")
    print()
    
    return True


if __name__ == "__main__":
    try:
        success = test_alpaca_connection()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        logger.error("Unexpected error", exc_info=True)
        sys.exit(1)
