"""
Portfolio Management

Tracks positions, cash, and portfolio-level metrics.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from core.position import Position
from core.order import Order


@dataclass
class Portfolio:
    """Manages portfolio positions and cash."""
    
    cash: Decimal = Decimal("0")
    initial_capital: Decimal = Decimal("0")
    positions: Dict[str, Position] = field(default_factory=dict)
    orders: List[Order] = field(default_factory=list)
    
    # Performance tracking
    start_date: datetime = field(default_factory=datetime.now)
    high_water_mark: Decimal = Decimal("0")
    
    def __post_init__(self):
        """Initialize portfolio."""
        if isinstance(self.cash, (int, float)):
            self.cash = Decimal(str(self.cash))
        if isinstance(self.initial_capital, (int, float)):
            self.initial_capital = Decimal(str(self.initial_capital))
        if isinstance(self.high_water_mark, (int, float)):
            self.high_water_mark = Decimal(str(self.high_water_mark))
        
        if self.initial_capital > 0 and self.cash == 0:
            self.cash = self.initial_capital
        if self.high_water_mark == 0:
            self.high_water_mark = self.total_equity
    
    @property
    def total_equity(self) -> Decimal:
        """Total portfolio equity (cash + positions)."""
        return self.cash + self.total_position_value
    
    @property
    def total_position_value(self) -> Decimal:
        """Total market value of all positions."""
        return sum(pos.market_value for pos in self.positions.values())
    
    @property
    def total_cost_basis(self) -> Decimal:
        """Total cost basis of all positions."""
        return sum(pos.cost_basis for pos in self.positions.values())
    
    @property
    def total_unrealized_pnl(self) -> Decimal:
        """Total unrealized P&L."""
        return sum(pos.unrealized_pnl for pos in self.positions.values())
    
    @property
    def total_realized_pnl(self) -> Decimal:
        """Total realized P&L."""
        return sum(pos.realized_pnl for pos in self.positions.values())
    
    @property
    def total_pnl(self) -> Decimal:
        """Total P&L (realized + unrealized)."""
        return self.total_realized_pnl + self.total_unrealized_pnl
    
    @property
    def return_pct(self) -> float:
        """Portfolio return percentage."""
        if self.initial_capital == 0:
            return 0.0
        return float((self.total_equity - self.initial_capital) / self.initial_capital * 100)
    
    @property
    def drawdown_pct(self) -> float:
        """Current drawdown percentage."""
        hwm = float(self.high_water_mark)
        eq = float(self.total_equity)
        if hwm <= 0:
            return 0.0
        return (eq - hwm) / hwm * 100
    
    @property
    def num_positions(self) -> int:
        """Number of active positions."""
        return len([p for p in self.positions.values() if not p.is_empty()])
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """Get position for a symbol."""
        return self.positions.get(symbol.upper())
    
    def add_position(self, position: Position) -> None:
        """Add or update a position."""
        symbol = position.symbol.upper()
        if symbol in self.positions:
            # Update existing position
            existing = self.positions[symbol]
            existing.update_price(position.current_price)
        else:
            self.positions[symbol] = position
    
    def update_position_price(self, symbol: str, price: Decimal) -> None:
        """Update price for a position."""
        symbol = symbol.upper()
        if symbol in self.positions:
            self.positions[symbol].update_price(price)
    
    def update_prices(self, prices: Dict[str, Decimal]) -> None:
        """Update prices for multiple positions."""
        for symbol, price in prices.items():
            self.update_position_price(symbol, price)
    
    def execute_order(self, order: Order) -> bool:
        """Execute an order and update portfolio."""
        if not order.is_filled:
            return False
        
        symbol = order.symbol.upper()
        quantity = order.filled_quantity
        price = order.avg_fill_price or Decimal("0")
        cost = quantity * price
        
        if order.side.value == "buy":
            # Buy order
            if cost > self.cash:
                return False  # Insufficient cash
            
            self.cash -= cost
            
            if symbol in self.positions:
                self.positions[symbol].add_shares(quantity, price)
            else:
                pos = Position(
                    symbol=symbol,
                    quantity=quantity,
                    avg_cost=price,
                    current_price=price,
                    strategy=order.strategy,
                    entry_reason=order.reason,
                )
                self.positions[symbol] = pos
        
        else:  # sell
            if symbol not in self.positions:
                return False  # No position to sell
            
            pos = self.positions[symbol]
            if quantity > pos.quantity:
                quantity = pos.quantity
            
            realized_pnl = pos.remove_shares(quantity, price)
            self.cash += quantity * price
            
            if pos.is_empty():
                del self.positions[symbol]
        
        # Update high water mark
        if self.total_equity > self.high_water_mark:
            self.high_water_mark = self.total_equity
        
        # Track order
        self.orders.append(order)
        
        return True
    
    def get_position_weights(self) -> Dict[str, float]:
        """Get position weights as percentages."""
        if self.total_equity == 0:
            return {}
        
        weights = {}
        for symbol, pos in self.positions.items():
            if not pos.is_empty():
                weights[symbol] = float(pos.market_value / self.total_equity)
        
        return weights
    
    def get_sector_exposure(self, sector_map: Dict[str, str]) -> Dict[str, float]:
        """Get sector exposure percentages."""
        sector_values = defaultdict(Decimal)
        
        for symbol, pos in self.positions.items():
            if not pos.is_empty():
                sector = sector_map.get(symbol, "UNKNOWN")
                sector_values[sector] += pos.market_value
        
        total = self.total_equity
        if total == 0:
            return {}
        
        return {sector: float(value / total) for sector, value in sector_values.items()}
    
    def to_dict(self) -> dict:
        """Convert portfolio to dictionary."""
        return {
            "cash": float(self.cash),
            "initial_capital": float(self.initial_capital),
            "total_equity": float(self.total_equity),
            "total_position_value": float(self.total_position_value),
            "total_unrealized_pnl": float(self.total_unrealized_pnl),
            "total_realized_pnl": float(self.total_realized_pnl),
            "total_pnl": float(self.total_pnl),
            "return_pct": self.return_pct,
            "drawdown_pct": self.drawdown_pct,
            "high_water_mark": float(self.high_water_mark),
            "num_positions": self.num_positions,
            "positions": {sym: pos.to_dict() for sym, pos in self.positions.items()},
            "position_weights": self.get_position_weights(),
        }
