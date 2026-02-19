# Quick Start: Alpaca Paper Trading

## 🚀 3-Step Setup

### 1. Get API Keys
- Sign up at [alpaca.markets](https://alpaca.markets)
- Get paper trading keys from [paper dashboard](https://app.alpaca.markets/paper/dashboard/overview)

### 2. Configure
```bash
cp .env.example .env
# Edit .env and add your API keys
```

### 3. Test
```bash
python test_alpaca_connection.py
```

## 📝 Execute Trades

```python
from execution.broker import Broker
from execution.order_manager import OrderManager
from core.order import OrderType, OrderSide
from decimal import Decimal

broker = Broker()
order_manager = OrderManager(broker)

# Buy 1 share of AAPL
order = order_manager.submit_order(
    symbol="AAPL",
    quantity=Decimal("1"),
    side=OrderSide.BUY,
    order_type=OrderType.MARKET
)
```

## 📚 Full Documentation

See [ALPACA_SETUP.md](./ALPACA_SETUP.md) for complete setup guide.
