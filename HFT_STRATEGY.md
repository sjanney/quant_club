# HFT Intraday Scalping Strategy

## Overview

A confluence-based intraday scalping strategy designed for fast execution during market hours. Trades are entered only when multiple independent indicators agree, and every position is managed with ATR-based stop-loss / take-profit levels and automatic end-of-day flattening.

## Strategy Description

### Confluence Scalping

The strategy uses **six independent indicators** and requires a configurable minimum number to agree before generating a trade signal. This eliminates weak, single-indicator entries that lead to whipsaw losses.

### Indicators

1. **RSI (Wilder's Exponential Smoothing)**
   - Uses industry-standard EWM (not SMA) for faster, more responsive readings
   - RSI < 30: Strong buy (+1.0) | RSI < 40: Mild buy (+0.5)
   - RSI > 70: Strong sell (-1.0) | RSI > 60: Mild sell (-0.5)

2. **Bollinger Bands (Mean Reversion)**
   - Price at/below lower band: Strong buy | Price at/above upper band: Strong sell
   - Price below/above middle band: Mild buy/sell bias

3. **VWAP (Volume-Weighted Average Price)**
   - The dominant intraday anchor -- institutional traders key off VWAP
   - Distance from VWAP measured in ATR units for normalization
   - Price well below VWAP (> 1.5 ATR): Buy bias
   - Price well above VWAP (> 1.5 ATR): Sell bias

4. **EMA Trend Filter (9/21 Crossover)**
   - Only take long signals in uptrends (9-EMA > 21-EMA)
   - Only take short signals in downtrends (9-EMA < 21-EMA)
   - Prevents the worst mean-reversion traps (counter-trend entries)

5. **MACD Momentum Confirmation**
   - MACD histogram turning positive and > 0: Confirms long momentum
   - MACD histogram turning negative and < 0: Confirms short momentum
   - Prevents entering against the prevailing momentum

6. **Volume Spike Detection**
   - Volume > 2x 20-bar average: Momentum signal
   - Volume spike + price up: Long bias
   - Volume spike + price down: Short bias

### Volatility Filter

Before scoring, the strategy checks the ATR-to-price ratio:
- **Too quiet** (ATR/price < 0.05%): Skip -- no edge in dead markets
- **Too volatile** (ATR/price > 5%): Skip -- slippage risk too high

### Signal Scoring

Each indicator produces a score from -1.0 (strong short) to +1.0 (strong long). These are combined with configurable weights:

| Indicator   | Weight |
|-------------|--------|
| RSI         | 20%    |
| Bollinger   | 15%    |
| VWAP        | 20%    |
| EMA Trend   | 15%    |
| MACD        | 15%    |
| Volume      | 15%    |

The weighted sum maps to a 0-100 score (50 = neutral). A signal only fires if:
1. The score exceeds the `min_signal_strength` threshold (default: 65)
2. At least `min_confluence` indicators agree (default: 2)
3. The trend filter does not contradict the signal direction

### ATR-Based Exit Levels

Every signal includes suggested stop-loss and take-profit prices:
- **Stop-loss**: Entry price - (ATR x `stop_loss_atr_mult`) for longs
- **Take-profit**: Entry price + (ATR x `take_profit_atr_mult`) for longs
- Reversed for shorts

The asymmetric defaults (SL = 1.5x ATR, TP = 2.0x ATR) create a positive expected value: winners are larger than losers.

## Exit Management

### Per-Position SL/TP Tracking

The executor tracks each open position with entry price, stop-loss, and take-profit levels. Every cycle, current prices are checked against these levels and exits are triggered automatically via market orders.

### End-of-Day Flattening

At 3:45 PM ET (configurable), all open positions are flattened. Scalping positions must not carry overnight -- gap risk destroys edge.

### Per-Symbol Cooldown

After exiting a position, the symbol enters a cooldown period (default: 5 cycles). This prevents whipsaw: rapidly re-entering and exiting the same name on noise.

## Configuration

### Default Settings

Located in `config/settings.py` (`HFTConfig`):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_trades_per_day` | 50 | Daily trade limit |
| `max_positions` | 5 | Max concurrent positions |
| `position_size_pct` | 0.10 | 10% of equity per position |
| `min_signal_strength` | 65.0 | Minimum score to trade (long > 65, short < 35) |
| `max_daily_loss_pct` | 0.02 | 2% daily loss circuit breaker |
| `bar_interval` | "1Min" | Bar interval ("1Min" or "5Min") |
| `stop_loss_atr_mult` | 1.5 | ATR multiplier for stop-loss |
| `take_profit_atr_mult` | 2.0 | ATR multiplier for take-profit |
| `eod_flatten_minutes_before_close` | 15 | Minutes before close to flatten all positions |
| `cooldown_cycles` | 5 | Cycles to wait before re-entering same symbol |
| `min_confluence` | 2 | Minimum confirming indicators required |
| `universe` | SPY, QQQ, AAPL, MSFT, TSLA, NVDA | Symbols to trade |

### Customization

```python
@dataclass
class HFTConfig:
    max_trades_per_day: int = 50
    max_positions: int = 5
    position_size_pct: float = 0.10
    min_signal_strength: float = 65.0
    max_daily_loss_pct: float = 0.02
    bar_interval: str = "1Min"
    universe: List[str] = field(default_factory=lambda: [...])
    stop_loss_atr_mult: float = 1.5
    take_profit_atr_mult: float = 2.0
    eod_flatten_minutes_before_close: int = 15
    cooldown_cycles: int = 5
    min_confluence: int = 2
```

## GitHub Actions Setup

### Workflow Schedule

The HFT workflow runs every 10 minutes during market hours (9:30 AM - 4:00 PM ET):

```yaml
schedule:
  - cron: '*/10 13-20 * * 1-5'  # Every 10 min, 13:00-20:00 UTC, Mon-Fri
```

### Cost Estimate

- **Runs per day**: ~39 (every 10 min x 6.5 hours)
- **Runs per month**: ~858 (39 x 22 trading days)
- **Minutes per run**: ~2 minutes
- **Total minutes/month**: ~1,716 minutes

**Free tier limits:**
- Public repos: Unlimited
- Private repos: 2,000 minutes/month

### Manual Trigger

Go to Actions -> HFT Trading -> Run workflow.

## Local Execution

### Basic Usage

```bash
# Single cycle
python main.py --mode hft

# Continuous loop (default 60-second interval)
python main.py --mode hft --hft-interval 60

# Custom universe
python main.py --mode hft --hft-universe "SPY,QQQ,AAPL"
```

### Environment Variables

Required:
- `ALPACA_API_KEY`: Your Alpaca API key
- `ALPACA_API_SECRET`: Your Alpaca API secret

Optional:
- `LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR)

## Risk Limits

| Control | Description | Default |
|---------|-------------|---------|
| Max trades/day | Prevents overtrading | 50 |
| Max positions | Limits exposure | 5 |
| Position size | Fraction of equity per trade | 10% |
| Signal threshold | Only trade strong confluence signals | 65 |
| Daily loss limit | Circuit breaker | 2% |
| Stop-loss | ATR-based per-position exits | 1.5x ATR |
| Take-profit | ATR-based per-position targets | 2.0x ATR |
| EOD flatten | No overnight risk | 15 min before close |
| Cooldown | Anti-whipsaw per symbol | 5 cycles |
| Trend filter | No counter-trend entries | EMA 9/21 |
| Volatility filter | Skip dead or extreme markets | ATR/price 0.05%-5% |

## Performance Tracking

### Logs

All HFT activity is logged to `logs/trading_desk.log`:
- Signal generation with confluence counts
- Entry orders with SL/TP levels
- Exit orders with realized P&L and reason (stop_loss / take_profit / EOD flatten)
- Per-cycle summary: entries, exits, realized + unrealized P&L

### Position Summary

The executor tracks per cycle:
- Tracked positions with entry price, SL, TP levels
- Active cooldowns per symbol
- Realized P&L (from closed trades)
- Unrealized P&L (from open positions)
- Combined total P&L
- Trade count for the day

## Strategy Files

- **Strategy**: `strategies/scalping_strategy.py`
- **Data Provider**: `data/realtime_data.py`
- **Executor**: `execution/hft_executor.py`
- **Config**: `config/settings.py` (`HFTConfig`)
- **Workflow**: `.github/workflows/hft_trading.yml`

## Troubleshooting

### No Data Fetched

- Check Alpaca API credentials
- Verify market is open
- Check symbol names are correct

### All Signals Neutral (score = 50)

- This means the confluence filter is working -- indicators disagree
- Review logs for per-indicator scores at DEBUG level
- Consider lowering `min_confluence` from 2 to 1 (trades more, but riskier)

### Max Trades Reached

- Review `max_trades_per_day` setting
- Check if cooldown is releasing symbols too quickly

### Market Closed

The strategy automatically skips cycles when the market is closed. This is expected behavior. EOD flattening triggers 15 minutes before close.
