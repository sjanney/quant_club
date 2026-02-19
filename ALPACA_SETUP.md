# Alpaca Paper Trading Setup Guide

This guide will help you connect your Alpaca paper trading account to execute trades in this quant trading system.

## 📋 Prerequisites

1. **Alpaca Account**: Sign up for a free Alpaca account at [https://alpaca.markets](https://alpaca.markets)
2. **Paper Trading Account**: Access your paper trading dashboard at [https://app.alpaca.markets/paper/dashboard/overview](https://app.alpaca.markets/paper/dashboard/overview)
3. **Python Environment**: Python 3.8+ with virtual environment activated

## 🔑 Step 1: Get Your Alpaca API Keys

1. Log into your Alpaca account
2. Navigate to **Paper Trading** dashboard
3. Go to **Your API Keys** section (or visit [https://app.alpaca.markets/paper/dashboard/overview](https://app.alpaca.markets/paper/dashboard/overview))
4. Generate or view your API keys:
   - **API Key ID** (starts with `PK...` for paper trading)
   - **Secret Key** (keep this secure!)

⚠️ **Important**: Make sure you're using **Paper Trading** API keys, not Live Trading keys!

## ⚙️ Step 2: Configure Environment Variables

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

2. Edit the `.env` file and add your credentials:
   ```bash
   # Broker Configuration (Alpaca)
   ALPACA_API_KEY=PKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ALPACA_API_SECRET=your_secret_key_here
   ALPACA_BASE_URL=https://paper-api.alpaca.markets
   ALPACA_DATA_URL=https://data.alpaca.markets
   ALPACA_PAPER=true

   # Logging
   LOG_LEVEL=INFO
   ```

3. **Never commit your `.env` file** - it's already in `.gitignore`

## ✅ Step 3: Test Your Connection

Run the connection test script:

```bash
python test_alpaca_connection.py
```

This will verify:
- ✓ Your API credentials are configured
- ✓ Connection to Alpaca paper trading API
- ✓ Account information retrieval
- ✓ Positions retrieval
- ✓ Market status check
- ✓ Paper trading URL verification

Expected output:
```
============================================================
ALPACA PAPER TRADING CONNECTION TEST
============================================================

📋 Configuration Check:
  API Key: ✓ Set
  API Secret: ✓ Set
  Base URL: https://paper-api.alpaca.markets
  Paper Trading: True

🔌 Initializing Broker...
✓ Broker initialized successfully

📊 Testing Account Connection...
✓ Account connection successful!

Account Information:
  Equity: $100,000.00
  Cash: $100,000.00
  Buying Power: $200,000.00
  Portfolio Value: $100,000.00

📈 Testing Positions Retrieval...
✓ Positions retrieved: 0 positions

🕐 Testing Market Status...
✓ Market is currently: OPEN

🔍 Verifying Paper Trading Configuration...
✓ Paper trading URL confirmed

============================================================
✅ ALL TESTS PASSED!
============================================================
```

## 🚀 Step 4: Execute Your First Trade

Once the connection test passes, you can execute trades using the example script:

```bash
python examples/execute_trade.py
```

This script demonstrates:
- Account balance checking
- Market status verification
- Order submission (market and limit orders)
- Order status tracking

**Note**: The script will prompt for confirmation before executing trades.

## 📚 Usage Examples

### Basic Trade Execution

```python
from execution.broker import Broker
from execution.order_manager import OrderManager
from core.order import OrderType, OrderSide
from decimal import Decimal

# Initialize broker
broker = Broker()

# Initialize order manager
order_manager = OrderManager(broker)

# Submit a market buy order
order = order_manager.submit_order(
    symbol="AAPL",
    quantity=Decimal("1"),
    side=OrderSide.BUY,
    order_type=OrderType.MARKET,
    strategy="my_strategy",
    reason="Testing paper trading"
)

if order.broker_order_id:
    print(f"Order submitted: {order.broker_order_id}")
```

### Limit Order

```python
# Submit a limit buy order
order = order_manager.submit_order(
    symbol="AAPL",
    quantity=Decimal("1"),
    side=OrderSide.BUY,
    order_type=OrderType.LIMIT,
    limit_price=Decimal("150.00"),
    strategy="my_strategy"
)
```

### Check Account Status

```python
from execution.broker import Broker

broker = Broker()
account = broker.get_account()

if account:
    print(f"Equity: ${account['equity']:,.2f}")
    print(f"Cash: ${account['cash']:,.2f}")
    print(f"Buying Power: ${account['buying_power']:,.2f}")
```

### Get Current Positions

```python
positions = broker.get_positions()
for symbol, value in positions.items():
    print(f"{symbol}: ${float(value):,.2f}")

# Or get detailed position info
position_details = broker.get_position_details()
for pos in position_details:
    print(f"{pos['symbol']}: {pos['quantity']} shares @ ${pos['avg_entry_price']}")
    print(f"  Current Value: ${pos['market_value']}")
    print(f"  Unrealized P&L: ${pos['unrealized_pl']} ({pos['unrealized_plpc']*100:.2f}%)")
```

### Check Market Status

```python
if broker.is_market_open():
    print("Market is open - orders will execute immediately")
else:
    print("Market is closed - orders will be queued")
    
# Get detailed market clock info
clock = broker.get_market_clock()
if clock:
    print(f"Next open: {clock['next_open']}")
    print(f"Next close: {clock['next_close']}")
```

## 🛡️ Safety Features

### Paper Trading Only

The system is configured to use **paper trading by default**:
- Default URL: `https://paper-api.alpaca.markets`
- All trades use virtual money
- No real capital at risk

### Risk Management

All orders are automatically checked by the `RiskManager`:
- Position size limits
- Sector exposure limits
- Drawdown controls
- Daily loss limits

### Order Validation

The broker validates all orders before submission:
- Quantity validation
- Price validation for limit/stop orders
- Account balance checks

## 🔧 Troubleshooting

### "Broker not configured" Error

**Problem**: API keys not found in environment variables

**Solution**:
1. Check that `.env` file exists in project root
2. Verify environment variables are set correctly
3. Restart your Python session/terminal after creating `.env`

### "Failed to initialize broker" Error

**Problem**: Invalid API credentials or network issue

**Solution**:
1. Verify your API keys are correct
2. Check that you're using **Paper Trading** keys (start with `PK...`)
3. Ensure you have internet connectivity
4. Check Alpaca status page: [https://status.alpaca.markets](https://status.alpaca.markets)

### "Market is closed" Warning

**Problem**: Trying to trade outside market hours

**Solution**:
- Market hours: 9:30 AM - 4:00 PM ET (Monday-Friday)
- Orders submitted outside market hours will be queued
- Use `broker.is_market_open()` to check before submitting orders

### Order Rejected

**Problem**: Order fails risk checks or has invalid parameters

**Solution**:
1. Check order logs for rejection reason
2. Verify you have sufficient buying power
3. Check risk limits in `config/settings.py`
4. Ensure order parameters are valid (e.g., limit price for limit orders)

## 📖 Additional Resources

- **Alpaca Documentation**: [https://alpaca.markets/docs](https://alpaca.markets/docs)
- **Paper Trading Dashboard**: [https://app.alpaca.markets/paper/dashboard](https://app.alpaca.markets/paper/dashboard)
- **API Reference**: [https://alpaca.markets/docs/api-documentation](https://alpaca.markets/docs/api-documentation)
- **Alpaca Python SDK**: [https://github.com/alpacahq/alpaca-trade-api-python](https://github.com/alpacahq/alpaca-trade-api-python)

## ⚠️ Important Notes

1. **Paper Trading Only**: This setup is configured for paper trading. Never use live trading keys unless you fully understand the risks.

2. **Rate Limits**: Alpaca has rate limits. The system includes caching to minimize API calls.

3. **Market Hours**: Orders submitted outside market hours will be queued for the next market open.

4. **Fractional Shares**: Alpaca supports fractional shares. Use `fractional=True` in `submit_order()`.

5. **Order Types**: Supported order types:
   - `MARKET`: Execute immediately at market price
   - `LIMIT`: Execute only at limit price or better
   - `STOP`: Triggered when price reaches stop price
   - `STOP_LIMIT`: Combination of stop and limit

6. **Time in Force**: Default is `day` (order expires at market close). Other options:
   - `gtc`: Good-till-canceled
   - `ioc`: Immediate-or-cancel
   - `fok`: Fill-or-kill

## 🎯 Next Steps

1. ✅ Test your connection: `python test_alpaca_connection.py`
2. ✅ Try example trade: `python examples/execute_trade.py`
3. ✅ Integrate with your strategies in `main.py`
4. ✅ Monitor performance using the built-in monitoring tools
5. ✅ Backtest strategies before live trading

Happy trading! 🚀
