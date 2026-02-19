"""
Performance Monitor

Tracks portfolio performance metrics.
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional
import pandas as pd

from core.portfolio import Portfolio
from risk.metrics import (
    calculate_sharpe,
    calculate_max_drawdown,
    calculate_win_rate,
    calculate_profit_factor,
)

logger = logging.getLogger(__name__)


class PerformanceMonitor:
    """Monitors portfolio performance."""
    
    def __init__(self):
        """Initialize performance monitor."""
        self.snapshots: List[Dict] = []
        self.start_date = datetime.now()
    
    def record_snapshot(self, portfolio: Portfolio) -> None:
        """Record a portfolio snapshot."""
        snapshot = {
            "timestamp": datetime.now(),
            "equity": float(portfolio.total_equity),
            "cash": float(portfolio.cash),
            "positions": portfolio.num_positions,
            "return_pct": portfolio.return_pct,
            "drawdown_pct": portfolio.drawdown_pct,
            "unrealized_pnl": float(portfolio.total_unrealized_pnl),
            "realized_pnl": float(portfolio.total_realized_pnl),
        }
        self.snapshots.append(snapshot)
    
    def get_performance_summary(self) -> Dict:
        """Get performance summary."""
        if not self.snapshots:
            return {}
        
        df = pd.DataFrame(self.snapshots)
        df.set_index("timestamp", inplace=True)
        
        equity_series = df["equity"]
        returns = equity_series.pct_change().dropna()
        
        summary = {
            "current_equity": float(equity_series.iloc[-1]),
            "total_return": float((equity_series.iloc[-1] / equity_series.iloc[0] - 1) * 100),
            "max_drawdown": calculate_max_drawdown(equity_series),
            "sharpe_ratio": calculate_sharpe(returns) if not returns.empty else 0.0,
            "win_rate": calculate_win_rate(returns) if not returns.empty else 0.0,
            "profit_factor": calculate_profit_factor(returns) if not returns.empty else 0.0,
            "num_snapshots": len(self.snapshots),
        }
        
        return summary
    
    def get_equity_curve(self) -> pd.Series:
        """Get equity curve as pandas Series."""
        if not self.snapshots:
            return pd.Series()
        
        df = pd.DataFrame(self.snapshots)
        df.set_index("timestamp", inplace=True)
        return df["equity"]
