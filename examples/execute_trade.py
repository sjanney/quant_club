#!/usr/bin/env python3
"""
Example: Execute a Trade with Alpaca Paper Trading

This script demonstrates how to execute trades using the OrderManager
with Alpaca paper trading. It includes:
- Account balance check
- Market status check
- Order submission
- Order status tracking
"""

import sys
from pathlib import Path
from decimal import Decimal

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.settings import settings
from execution.broker import Broker
from execution.order_manager import OrderManager
from core.order import OrderType, OrderSide
from risk.risk_manager import RiskManager
from core.portfolio import Portfolio
from monitoring.logger import setup_logger
import time

logger = setup_logger("trade_example")


def execute_example_trade():
    """Execute an example trade."""
    print("=" * 60)
    print("ALPACA PAPER TRADING - EXAMPLE TRADE EXECUTION")
    print("=" * 60)
    print()
    
    # Initialize components
    broker = Broker()
    
    if not broker.api:
        print("❌ ERROR: Broker not initialized. Please check your .env configuration.")
        print("Run 'python test_alpaca_connection.py' to verify your setup.")
        return False
    
    # Get account info
    print("📊 Account Information:")
    account = broker.get_account()
    if not account:
        print("❌ Could not retrieve account information")
        return False
    
    print(f"  Equity: ${account['equity']:,.2f}")
    print(f"  Cash: ${account['cash']:,.2f}")
    print(f"  Buying Power: ${account['buying_power']:,.2f}")
    print()
    
    # Check market status
    print("🕐 Market Status:")
    is_open = broker.is_market_open()
    print(f"  Market is: {'OPEN ✓' if is_open else 'CLOSED (orders will be queued)'}")
    print()
    
    # Initialize portfolio and risk manager
    portfolio = Portfolio(initial_capital=account['equity'])
    portfolio.cash = account['cash']
    risk_manager = RiskManager()
    risk_manager.set_portfolio(portfolio)
    order_manager = OrderManager(broker, risk_manager)
    
    # Example: Buy 1 share of AAPL (or any symbol you want to test)
    symbol = "AAPL"
    quantity = Decimal("1")
    
    print(f"📝 Example Trade:")
    print(f"  Symbol: {symbol}")
    print(f"  Side: BUY")
    print(f"  Quantity: {quantity}")
    print(f"  Order Type: MARKET")
    print()
    
    # Check if we have enough buying power
    # For simplicity, we'll use a small quantity
    # In production, you'd fetch the current price first
    estimated_cost = Decimal("200")  # Rough estimate for AAPL
    if account['cash'] < float(estimated_cost):
        print(f"⚠️  WARNING: Estimated cost (${estimated_cost}) exceeds available cash")
        print("   Reducing quantity or using a cheaper symbol...")
        # You could adjust quantity here
        return False
    
    # Submit order
    print("🚀 Submitting order...")
    try:
        order = order_manager.submit_order(
            symbol=symbol,
            quantity=quantity,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            strategy="example",
            reason="Testing paper trading connection"
        )
        
        if order.status.value == "rejected":
            print(f"❌ Order rejected: {order.reason}")
            return False
        
        if order.broker_order_id:
            print(f"✓ Order submitted successfully!")
            print(f"  Broker Order ID: {order.broker_order_id}")
            print(f"  Status: {order.status.value}")
            print()
            
            # Wait a moment and check status
            print("⏳ Waiting for order status update...")
            time.sleep(2)
            
            updated_order = order_manager.update_order_status(order.broker_order_id)
            if updated_order:
                print(f"  Updated Status: {updated_order.status.value}")
                if updated_order.is_filled:
                    print(f"  Filled Quantity: {updated_order.filled_quantity}")
                    if updated_order.avg_fill_price:
                        print(f"  Average Fill Price: ${updated_order.avg_fill_price:.2f}")
            
            print()
            print("✅ Trade execution example completed!")
            print()
            print("Note: This was a paper trade - no real money was used.")
            
        else:
            print("❌ Order submission failed")
            return False
            
    except Exception as e:
        print(f"❌ Error submitting order: {e}")
        logger.error("Order submission error", exc_info=True)
        return False
    
    return True


def execute_limit_order_example():
    """Example of submitting a limit order."""
    print("\n" + "=" * 60)
    print("LIMIT ORDER EXAMPLE")
    print("=" * 60)
    print()
    
    broker = Broker()
    if not broker.api:
        return False
    
    portfolio = Portfolio(initial_capital=100000)
    risk_manager = RiskManager()
    risk_manager.set_portfolio(portfolio)
    order_manager = OrderManager(broker, risk_manager)
    
    symbol = "AAPL"
    quantity = Decimal("1")
    limit_price = Decimal("150.00")  # Example limit price
    
    print(f"📝 Limit Order Example:")
    print(f"  Symbol: {symbol}")
    print(f"  Side: BUY")
    print(f"  Quantity: {quantity}")
    print(f"  Limit Price: ${limit_price}")
    print()
    
    try:
        order = order_manager.submit_order(
            symbol=symbol,
            quantity=quantity,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            limit_price=limit_price,
            strategy="example",
            reason="Testing limit order"
        )
        
        if order.broker_order_id:
            print(f"✓ Limit order submitted: {order.broker_order_id}")
            print("  Note: Limit orders may take time to fill or may not fill at all")
            print("        if the market price doesn't reach your limit price.")
        else:
            print("❌ Limit order submission failed")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False
    
    return True


if __name__ == "__main__":
    print()
    print("⚠️  IMPORTANT: This script will execute REAL paper trades!")
    print("   Paper trading uses virtual money, but orders are sent to Alpaca.")
    print()
    response = input("Continue? (yes/no): ").strip().lower()
    
    if response not in ['yes', 'y']:
        print("Cancelled.")
        sys.exit(0)
    
    try:
        # Run market order example
        success = execute_example_trade()
        
        # Optionally run limit order example
        if success:
            print()
            response = input("Would you like to see a limit order example? (yes/no): ").strip().lower()
            if response in ['yes', 'y']:
                execute_limit_order_example()
        
        sys.exit(0 if success else 1)
        
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        logger.error("Unexpected error", exc_info=True)
        sys.exit(1)
