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


@dataclass
class BrokerConfig:
    """Broker API configuration."""
    name: str = "alpaca"
    api_key: str = os.getenv("ALPACA_API_KEY", "")
    api_secret: str = os.getenv("ALPACA_API_SECRET", "")
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
