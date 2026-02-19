"""
Risk Manager

Enforces risk limits and validates trades before execution.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional

from config.settings import settings
from core.portfolio import Portfolio
from core.order import Order

logger = logging.getLogger(__name__)


@dataclass
class RiskCheck:
    """Result of a risk check."""
    passed: bool
    reason: Optional[str] = None
    details: Optional[Dict] = None


class RiskManager:
    """Manages risk limits and validates trades."""
    
    def __init__(self):
        """Initialize risk manager."""
        self.config = settings.risk
        self.portfolio: Optional[Portfolio] = None
    
    def set_portfolio(self, portfolio: Portfolio) -> None:
        """Set the portfolio to monitor."""
        self.portfolio = portfolio
    
    def check_trade(
        self,
        symbol: str,
        order_value: Decimal,
        current_positions: Optional[Dict[str, Decimal]] = None,
    ) -> RiskCheck:
        """Check if a trade passes risk limits."""
        if not self.portfolio:
            return RiskCheck(False, "Portfolio not set")
        
        symbol = symbol.upper()
        total_equity = self.portfolio.total_equity
        
        if total_equity == 0:
            return RiskCheck(False, "Zero portfolio equity")
        
        # Check position size limit
        position_pct = float(order_value / total_equity)
        if position_pct > self.config.max_position_size_pct:
            return RiskCheck(
                False,
                f"Position size {position_pct:.1%} exceeds limit {self.config.max_position_size_pct:.1%}",
            )
        
        # Check if adding this position would exceed max positions
        current_count = self.portfolio.num_positions
        if symbol not in self.portfolio.positions or self.portfolio.positions[symbol].is_empty():
            if current_count >= self.config.max_positions:
                return RiskCheck(
                    False,
                    f"Max positions limit reached ({self.config.max_positions})",
                )
        
        # Check leverage
        total_exposure = self.portfolio.total_position_value + order_value
        leverage = float(total_exposure / total_equity) if total_equity > 0 else 0
        if leverage > self.config.max_leverage:
            return RiskCheck(
                False,
                f"Leverage {leverage:.2f}x exceeds limit {self.config.max_leverage:.2f}x",
            )
        
        return RiskCheck(True, "Trade passed risk checks")
    
    def check_portfolio_limits(self) -> List[RiskCheck]:
        """Check all portfolio-level risk limits."""
        if not self.portfolio:
            return [RiskCheck(False, "Portfolio not set")]
        
        checks = []
        total_equity = self.portfolio.total_equity
        
        # Check drawdown
        drawdown = abs(self.portfolio.drawdown_pct) / 100
        if drawdown > self.config.max_drawdown_pct:
            checks.append(
                RiskCheck(
                    False,
                    f"Drawdown {drawdown:.1%} exceeds limit {self.config.max_drawdown_pct:.1%}",
                )
            )
        
        # Check position count
        num_positions = self.portfolio.num_positions
        if num_positions < self.config.min_positions:
            checks.append(
                RiskCheck(
                    False,
                    f"Position count {num_positions} below minimum {self.config.min_positions}",
                )
            )
        elif num_positions > self.config.max_positions:
            checks.append(
                RiskCheck(
                    False,
                    f"Position count {num_positions} exceeds maximum {self.config.max_positions}",
                )
            )
        
        # Check position sizes
        weights = self.portfolio.get_position_weights()
        for symbol, weight in weights.items():
            if weight > self.config.max_position_size_pct:
                checks.append(
                    RiskCheck(
                        False,
                        f"Position {symbol} weight {weight:.1%} exceeds limit {self.config.max_position_size_pct:.1%}",
                    )
                )
        
        return checks
    
    def check_sector_exposure(
        self,
        sector_map: Dict[str, str],
        new_symbol: Optional[str] = None,
        new_value: Optional[Decimal] = None,
    ) -> List[RiskCheck]:
        """Check sector exposure limits."""
        if not self.portfolio:
            return [RiskCheck(False, "Portfolio not set")]
        
        checks = []
        exposures = self.portfolio.get_sector_exposure(sector_map)
        
        # Add new position if provided
        if new_symbol and new_value:
            sector = sector_map.get(new_symbol.upper(), "UNKNOWN")
            total_equity = self.portfolio.total_equity
            if total_equity > 0:
                new_exposure = float(new_value / total_equity)
                exposures[sector] = exposures.get(sector, 0) + new_exposure
        
        # Check limits
        for sector, exposure in exposures.items():
            if exposure > self.config.max_sector_exposure_pct:
                checks.append(
                    RiskCheck(
                        False,
                        f"Sector {sector} exposure {exposure:.1%} exceeds limit {self.config.max_sector_exposure_pct:.1%}",
                    )
                )
        
        return checks
    
    def validate_order(self, order: Order) -> RiskCheck:
        """Validate an order against risk limits."""
        if not self.portfolio:
            return RiskCheck(False, "Portfolio not set")
        
        if not order.is_filled:
            return RiskCheck(False, "Order not filled")
        
        order_value = order.filled_quantity * (order.avg_fill_price or Decimal("0"))
        
        return self.check_trade(order.symbol, order_value)
    
    def can_trade(self) -> bool:
        """Check if trading is allowed (e.g., drawdown limits)."""
        if not self.portfolio:
            return False
        
        checks = self.check_portfolio_limits()
        return all(check.passed for check in checks)
