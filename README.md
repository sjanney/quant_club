# Professional Trading Desk

A professional-grade quantitative trading system designed for institutional-quality trading operations.

## 🏗️ Architecture

```
trading_desk/
├── config/              # Configuration management
│   └── settings.py      # Centralized settings with env var support
├── core/                # Core trading infrastructure
│   ├── portfolio.py     # Portfolio management
│   ├── position.py      # Position tracking
│   └── order.py         # Order management
├── data/                # Data management
│   ├── market_data.py   # Real-time market data
│   └── historical_data.py # Historical data with caching
├── execution/           # Order execution
│   ├── broker.py        # Broker API abstraction
│   └── order_manager.py # Order lifecycle management
├── risk/                # Risk management
│   ├── risk_manager.py  # Risk limit enforcement
│   └── metrics.py       # Risk metrics (VaR, Sharpe, etc.)
├── strategies/          # Trading strategies
│   ├── base_strategy.py # Strategy interface
│   └── momentum_strategy.py # Example strategy
├── backtest/            # Backtesting framework
│   ├── engine.py        # Walk-forward backtest engine
│   └── results.py       # Results analysis
├── monitoring/          # Monitoring & logging
│   ├── logger.py        # Centralized logging
│   └── performance.py   # Performance tracking
└── main.py              # Main entry point
```

## 🚀 Quick Start

### Installation

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration

**📖 For detailed Alpaca paper trading setup, see [ALPACA_SETUP.md](./ALPACA_SETUP.md)**

Create a `.env` file in the project root:

```bash
# Broker Configuration (Alpaca)
ALPACA_API_KEY=your_api_key_here
ALPACA_API_SECRET=your_api_secret_here
ALPACA_BASE_URL=https://paper-api.alpaca.markets
ALPACA_PAPER=true

# Logging
LOG_LEVEL=INFO
```

**Quick Test**: After configuring, test your connection:
```bash
python test_alpaca_connection.py
```

### Running

```bash
# Run backtest (default)
python main.py --mode backtest

# Run live trading (paper trading)
python main.py --mode live --dry-run

# Monitor mode
python main.py --mode monitor
```

### Scheduled trading (after-hours + execute at open)

Run analysis after the market closes and submit orders when the market opens—optionally without leaving your computer on:

```bash
# One-shot: run after market close (saves orders to state/)
python main.py --mode after-hours

# One-shot: at market open, submit saved orders
python main.py --mode execute-open

# Daemon: runs both automatically at configured times (default 4:35 PM & 9:31 AM ET)
python main.py --mode scheduler
```

**📖 Full details (cron, server, timezone): [SCHEDULER.md](./SCHEDULER.md)**

### GitHub Actions automation

You can run checks and scheduled paper trading in GitHub Actions (public repos are free-tier friendly):

- CI checks: `.github/workflows/ci.yml`
- Scheduled trading: `.github/workflows/scheduled_trading.yml`

Set repository secrets:

- `ALPACA_API_KEY`
- `ALPACA_API_SECRET`
- optional: `LOG_LEVEL`

Use **Actions → scheduled-trading → Run workflow** for manual runs/troubleshooting.

## 📊 Features

### Core Infrastructure
- **Portfolio Management**: Track positions, cash, P&L, and portfolio metrics
- **Order Management**: Full order lifecycle with status tracking
- **Position Tracking**: Real-time position monitoring with cost basis and P&L

### Risk Management
- **Position Limits**: Maximum position size per symbol
- **Sector Limits**: Maximum exposure per sector
- **Drawdown Controls**: Circuit breakers for maximum drawdown
- **Leverage Limits**: Hard limits on portfolio leverage
- **Risk Metrics**: VaR, Sharpe ratio, Sortino ratio, max drawdown

### Data Management
- **Multi-Source**: Support for Alpaca, yfinance, and other providers
- **Caching**: Intelligent caching to reduce API calls
- **Historical Data**: Efficient historical data retrieval and storage

### Execution
- **Broker Abstraction**: Unified interface for multiple brokers
- **Order Types**: Market, limit, stop, and stop-limit orders
- **Risk Pre-Trade Checks**: All orders validated before submission

### Backtesting
- **Walk-Forward Analysis**: Robust backtesting with walk-forward validation
- **Multiple Frequencies**: Daily, weekly, monthly rebalancing
- **Transaction Costs**: Realistic slippage and commission modeling
- **Performance Metrics**: Comprehensive performance analysis

### Monitoring
- **Performance Tracking**: Real-time performance monitoring
- **Logging**: Comprehensive logging with rotation
- **Equity Curves**: Track portfolio value over time

## 🔧 Configuration

All configuration is managed through `config/settings.py` with environment variable support:

### Risk Limits
```python
max_position_size_pct: 0.10      # 10% max per position
max_sector_exposure_pct: 0.30     # 30% max per sector
max_leverage: 1.0                 # No leverage
max_drawdown_pct: 0.15            # 15% max drawdown
daily_loss_limit_pct: 0.03       # 3% daily loss limit
```

### Trading Parameters
```python
initial_capital: 100000.0         # Starting capital
min_trade_size: 100.0            # Minimum trade size
max_trade_size: 10000.0          # Maximum trade size
slippage_bps: 5.0                # 5 basis points slippage
```

## 📈 Strategies

### Creating a Strategy

Implement the `BaseStrategy` interface:

```python
from strategies.base_strategy import BaseStrategy
import pandas as pd

class MyStrategy(BaseStrategy):
    def __init__(self):
        super().__init__(
            name="My Strategy",
            description="Strategy description"
        )
    
    def get_required_bars(self) -> int:
        return 50  # Minimum bars needed
    
    def generate_signals(self, data: Dict[str, pd.DataFrame]) -> Dict[str, float]:
        signals = {}
        for symbol, df in data.items():
            # Your signal logic here
            signals[symbol] = 75.0  # Score 0-100
        return signals
```

## 🧪 Backtesting

```python
from backtest.engine import BacktestEngine
from backtest.results import BacktestResults
from strategies.momentum_strategy import MomentumStrategy
from datetime import datetime, timedelta

strategy = MomentumStrategy()
engine = BacktestEngine(strategy)

start_date = datetime(2020, 1, 1)
end_date = datetime(2024, 12, 31)
symbols = ["AAPL", "MSFT", "GOOGL"]

results = engine.run(symbols, start_date, end_date)
backtest_results = BacktestResults(results)

print(backtest_results.generate_report())
backtest_results.plot_equity_curve()
```

## 🛡️ Risk Management

All trades are automatically checked against risk limits:

```python
from risk.risk_manager import RiskManager

risk_manager = RiskManager()
risk_manager.set_portfolio(portfolio)

# Check a trade
check = risk_manager.check_trade("AAPL", Decimal("10000"))
if check.passed:
    # Execute trade
    pass
else:
    print(f"Trade rejected: {check.reason}")
```

## 📝 Logging

Logging is automatically configured:

```python
from monitoring.logger import get_logger

logger = get_logger("my_module")
logger.info("Trading operation started")
logger.error("Error occurred", exc_info=True)
```

## 🔐 Security Best Practices

1. **Never commit API keys**: Use `.env` file (already in `.gitignore`)
2. **Paper trading first**: Always test in paper trading mode
3. **Risk limits**: Never disable risk checks in production
4. **Monitoring**: Monitor all trades and performance metrics
5. **Backtesting**: Always backtest strategies before live trading

## 📚 Dependencies

- **numpy/pandas**: Data manipulation
- **yfinance**: Market data
- **alpaca-trade-api**: Broker integration
- **matplotlib**: Visualization
- **sqlalchemy**: Database (optional)

## 🤝 Contributing

1. Follow PEP 8 style guidelines
2. Add type hints to all functions
3. Write docstrings for all classes and functions
4. Add tests for new features
5. Update documentation

## 📄 License

This project is for educational and research purposes.

## ⚠️ Disclaimer

This software is provided as-is for educational purposes. Trading involves risk of loss. Always test thoroughly in paper trading mode before using real capital. The authors are not responsible for any financial losses.
