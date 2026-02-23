"""
Trading Desk Configuration

Centralized configuration management with environment variable support.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _env(key: str, default: str = "") -> str:
    """Get env var and strip whitespace (avoids copy-paste issues in GitHub Secrets)."""
    return (os.getenv(key, default) or "").strip()


@dataclass
class BrokerConfig:
    """Broker API configuration."""
    name: str = "alpaca"
    api_key: str = _env("ALPACA_API_KEY")
    api_secret: str = _env("ALPACA_API_SECRET")
    base_url: str = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    data_url: str = os.getenv("ALPACA_DATA_URL", "https://data.alpaca.markets")
    use_paper: bool = os.getenv("ALPACA_PAPER", "true").lower() == "true"


@dataclass
class RiskConfig:
    """Risk management parameters."""
    # Position limits
    max_position_size_pct: float = 0.10  # 10% max per position
    max_sector_exposure_pct: float = 0.30  # 30% max per sector
    max_leverage: float = 1.0  # No leverage by default
    
    # Portfolio limits
    min_positions: int = 5
    max_positions: int = 30
    
    # Drawdown limits
    max_drawdown_pct: float = 0.15  # 15% max drawdown
    daily_loss_limit_pct: float = 0.03  # 3% daily loss limit
    
    # Risk metrics
    var_confidence: float = 0.95  # 95% VaR
    lookback_days: int = 252  # 1 year for risk calculations


@dataclass
class TradingConfig:
    """Trading execution parameters."""
    initial_capital: float = 100000.0  # $100k default
    min_trade_size: float = 100.0  # Minimum $100 per trade
    max_trade_size: float = 10000.0  # Maximum $10k per trade
    
    # Order types
    default_order_type: str = "market"  # market, limit, stop
    use_limit_orders: bool = False
    limit_order_buffer_pct: float = 0.001  # 0.1% buffer for limit orders
    
    # Execution
    slippage_bps: float = 5.0  # 5 basis points slippage
    commission_per_share: float = 0.0  # $0 commission (Alpaca)
    commission_per_trade: float = 0.0  # $0 commission
    
    # Timing
    market_open_time: str = "09:30"
    market_close_time: str = "16:00"
    timezone: str = "America/New_York"


@dataclass
class DataConfig:
    """Data management configuration."""
    data_dir: Path = PROJECT_ROOT / "data"
    cache_dir: Path = PROJECT_ROOT / "data" / "cache"
    historical_days: int = 252  # 1 year default
    
    # Data sources
    primary_data_source: str = "alpaca"  # alpaca, yfinance, polygon
    fallback_data_source: str = "yfinance"
    
    # Caching
    cache_enabled: bool = True
    cache_ttl_minutes: int = 15
    
    # Universe
    universe_file: Optional[Path] = None  # Custom universe file
    default_universe: List[str] = None  # Will be set to SP500 if None


@dataclass
class BacktestConfig:
    """Backtesting configuration."""
    start_date: str = "2020-01-01"
    end_date: str = "2024-12-31"
    initial_capital: float = 100000.0
    
    # Walk-forward parameters
    train_period_days: int = 252  # 1 year training
    test_period_days: int = 63  # 3 months testing
    step_days: int = 21  # 1 month step
    
    # Transaction costs
    slippage_bps: float = 5.0
    commission_per_trade: float = 1.0
    
    # Rebalancing
    rebalance_frequency: str = "weekly"  # daily, weekly, monthly
    rebalance_day: int = 0  # 0=Monday for weekly


@dataclass
class LoggingConfig:
    """Logging configuration."""
    log_dir: Path = PROJECT_ROOT / "logs"
    log_level: str = os.getenv("LOG_LEVEL", "INFO") or "INFO"
    log_file: str = "trading_desk.log"
    log_rotation: bool = True
    log_max_bytes: int = 10 * 1024 * 1024  # 10MB
    log_backup_count: int = 5


@dataclass
class NotificationConfig:
    """Notification configuration (Discord webhook)."""
    discord_webhook_url: str = os.getenv("DISCORD_WEBHOOK_URL", "")
    discord_enabled: bool = os.getenv("DISCORD_ENABLED", "true").lower() == "true"


@dataclass
class ScheduleConfig:
    """Scheduled trading: after-hours analysis and execute at market open."""
    timezone: str = "America/New_York"
    # After-market: run analysis and save orders (default 4:35 PM ET)
    after_hours_hour: int = 16
    after_hours_minute: int = 35
    # Market open: execute saved orders (default 9:31 AM ET)
    market_open_hour: int = 9
    market_open_minute: int = 31
    # State directory for scheduled_orders.json and scheduler state
    state_dir: Path = PROJECT_ROOT / "state"
    scheduled_orders_file: str = "scheduled_orders.json"
    scheduler_state_file: str = "scheduler_state.json"
    # Archive executed orders for audit
    archive_dir: Path = PROJECT_ROOT / "state" / "archive"


@dataclass
class HFTConfig:
    """High-frequency trading (intraday scalping) configuration — aggressive."""
    max_trades_per_day: int = 100             # Aggressive: high trade count
    max_positions: int = 8                    # More concurrent positions
    position_size_pct: float = 0.08           # 8% base per position (scaled by conviction)
    min_signal_strength: float = 58.0         # Lower threshold = more trades
    max_daily_loss_pct: float = 0.03          # 3% daily loss limit
    bar_interval: str = "1Min"                # 1-minute bars
    universe: List[str] = field(default_factory=lambda: [
        "SPY", "QQQ", "AAPL", "MSFT", "TSLA", "NVDA",
        "AMD", "META", "AMZN", "GOOGL",
    ])
    # Exit management
    stop_loss_atr_mult: float = 1.5           # Initial SL at 1.5x ATR (tightens to 1x when trailing)
    take_profit_atr_mult: float = 2.5         # Wider TP lets winners run with trailing stop
    eod_flatten_minutes_before_close: int = 10  # Flatten 10 min before close
    # Anti-whipsaw
    cooldown_cycles: int = 3                  # Shorter cooldown: re-enter faster
    # Signal quality
    min_confluence: int = 2                   # At least 2 indicators must agree


@dataclass
class MeanReversionConfig:
    """Mean reversion + VIX regime strategy configuration."""
    universe: List[str] = field(default_factory=lambda: [
        "SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN",
        "GOOGL", "META", "TSLA", "AMD", "JPM", "GS",
    ])
    # Include VIX proxy in data fetch for regime filtering
    vix_symbol: str = "VIXY"           # ETF proxy for VIX (easier to fetch via Alpaca)
    rsi_period: int = 2
    bb_period: int = 20
    roc_period: int = 5
    roc_z_window: int = 60
    ema_fast: int = 50
    ema_slow: int = 200
    vix_high_threshold: float = 30.0
    vix_extreme_threshold: float = 40.0
    # Order sizing
    notional_pct: float = 0.10         # 10% equity per name
    max_names: int = 6
    long_threshold: float = 58.0
    short_threshold: float = 42.0
    shortable: List[str] = field(default_factory=lambda: [])  # No shorts by default


@dataclass
class OptionsConfig:
    """Options overlay configuration."""
    enabled: bool = True
    # Score thresholds for directional option buys
    strong_long_threshold: float = 72.0   # Buy call above this
    strong_short_threshold: float = 28.0  # Buy put below this
    # Covered call range (score between these → sell covered call on long)
    covered_call_min_score: float = 55.0
    covered_call_max_score: float = 70.0
    # Contract selection
    min_dte: int = 7
    max_dte: int = 21
    covered_call_max_dte: int = 14       # Shorter DTE for covered calls
    directional_otm_pct: float = 0.05    # 5% OTM for directional buys
    covered_call_otm_pct: float = 0.03   # 3% OTM for covered calls
    # Sizing
    max_notional_pct: float = 0.02       # Max 2% equity per option trade
    max_contracts_per_symbol: int = 2    # Max contracts per symbol


@dataclass
class Settings:
    """Main settings class containing all configuration."""
    broker: BrokerConfig = field(default_factory=BrokerConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    data: DataConfig = field(default_factory=DataConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    hft: HFTConfig = field(default_factory=HFTConfig)
    mean_reversion: MeanReversionConfig = field(default_factory=MeanReversionConfig)
    options: OptionsConfig = field(default_factory=OptionsConfig)

    # Strategy configuration
    active_strategies: List[str] = field(default_factory=list)  # Will be set dynamically
    
    # Feature flags
    dry_run: bool = True  # Default to paper trading
    enable_live_trading: bool = False
    
    def __post_init__(self):
        """Initialize default values."""
        if self.data.default_universe is None:
            # Default SP500 subset
            self.data.default_universe = [
                "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
                "BRK.B", "V", "JNJ", "WMT", "JPM", "MA", "PG", "UNH",
                "HD", "DIS", "BAC", "ADBE", "NFLX", "CRM", "VZ", "CMCSA",
                "KO", "PEP", "TMO", "COST", "AVGO", "ABBV", "NKE"
            ]
        
        if self.active_strategies is None:
            self.active_strategies = []
        
        # Create directories
        self.data.data_dir.mkdir(parents=True, exist_ok=True)
        self.data.cache_dir.mkdir(parents=True, exist_ok=True)
        self.logging.log_dir.mkdir(parents=True, exist_ok=True)
        self.schedule.state_dir.mkdir(parents=True, exist_ok=True)
        self.schedule.archive_dir.mkdir(parents=True, exist_ok=True)


# Global settings instance
settings = Settings()
