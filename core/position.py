"""
Position Management

Tracks individual positions in the portfolio.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from decimal import Decimal


@dataclass
class Position:
    """Represents a single position in the portfolio."""
    
    symbol: str
    quantity: Decimal = Decimal("0")
    avg_cost: Decimal = Decimal("0")
    current_price: Decimal = Decimal("0")
    entry_date: Optional[datetime] = None
    last_update: datetime = field(default_factory=datetime.now)
    
    # P&L tracking
    unrealized_pnl: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    
    # Metadata
    strategy: Optional[str] = None
    entry_reason: Optional[str] = None
    
    def __post_init__(self):
        """Initialize position."""
        if self.entry_date is None:
            self.entry_date = datetime.now()
        if isinstance(self.quantity, (int, float)):
            self.quantity = Decimal(str(self.quantity))
        if isinstance(self.avg_cost, (int, float)):
            self.avg_cost = Decimal(str(self.avg_cost))
        if isinstance(self.current_price, (int, float)):
            self.current_price = Decimal(str(self.current_price))
    
    @property
    def market_value(self) -> Decimal:
        """Current market value of the position."""
        return self.quantity * self.current_price
    
    @property
    def cost_basis(self) -> Decimal:
        """Total cost basis of the position."""
        return self.quantity * self.avg_cost
    
    @property
    def total_pnl(self) -> Decimal:
        """Total P&L (realized + unrealized)."""
        return self.realized_pnl + self.unrealized_pnl
    
    @property
    def return_pct(self) -> float:
        """Return percentage."""
        if self.cost_basis == 0:
            return 0.0
        return float((self.market_value - self.cost_basis) / self.cost_basis * 100)
    
    def update_price(self, price: Decimal) -> None:
        """Update current price and recalculate unrealized P&L."""
        if isinstance(price, (int, float)):
            price = Decimal(str(price))
        self.current_price = price
        self.unrealized_pnl = (price - self.avg_cost) * self.quantity
        self.last_update = datetime.now()
    
    def add_shares(self, quantity: Decimal, price: Decimal) -> None:
        """Add shares to position (average cost calculation)."""
        if isinstance(quantity, (int, float)):
            quantity = Decimal(str(quantity))
        if isinstance(price, (int, float)):
            price = Decimal(str(price))
        
        total_cost = self.cost_basis + (quantity * price)
        total_shares = self.quantity + quantity
        self.avg_cost = total_cost / total_shares if total_shares > 0 else Decimal("0")
        self.quantity = total_shares
    
    def remove_shares(self, quantity: Decimal, price: Decimal) -> Decimal:
        """Remove shares from position and calculate realized P&L."""
        if isinstance(quantity, (int, float)):
            quantity = Decimal(str(quantity))
        if isinstance(price, (int, float)):
            price = Decimal(str(price))
        
        if quantity > self.quantity:
            quantity = self.quantity
        
        realized = (price - self.avg_cost) * quantity
        self.realized_pnl += realized
        self.quantity -= quantity
        
        return realized
    
    def is_empty(self) -> bool:
        """Check if position is empty."""
        return self.quantity == 0
    
    def to_dict(self) -> dict:
        """Convert position to dictionary."""
        return {
            "symbol": self.symbol,
            "quantity": float(self.quantity),
            "avg_cost": float(self.avg_cost),
            "current_price": float(self.current_price),
            "market_value": float(self.market_value),
            "cost_basis": float(self.cost_basis),
            "unrealized_pnl": float(self.unrealized_pnl),
            "realized_pnl": float(self.realized_pnl),
            "total_pnl": float(self.total_pnl),
            "return_pct": self.return_pct,
            "entry_date": self.entry_date.isoformat() if self.entry_date else None,
            "last_update": self.last_update.isoformat(),
            "strategy": self.strategy,
            "entry_reason": self.entry_reason,
        }
