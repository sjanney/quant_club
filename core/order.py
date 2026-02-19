"""
Order Management

Handles order creation, tracking, and execution.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from decimal import Decimal


class OrderType(Enum):
    """Order type enumeration."""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderSide(Enum):
    """Order side enumeration."""
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    """Order status enumeration."""
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class Order:
    """Represents a trading order."""
    
    symbol: str
    side: OrderSide
    quantity: Decimal
    order_type: OrderType = OrderType.MARKET
    status: OrderStatus = OrderStatus.PENDING
    
    # Price fields
    limit_price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    
    # Execution fields
    filled_quantity: Decimal = Decimal("0")
    avg_fill_price: Optional[Decimal] = None
    
    # Timing
    created_at: datetime = field(default_factory=datetime.now)
    submitted_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    
    # Metadata
    strategy: Optional[str] = None
    reason: Optional[str] = None
    order_id: Optional[str] = None
    broker_order_id: Optional[str] = None
    
    def __post_init__(self):
        """Initialize order."""
        if isinstance(self.quantity, (int, float)):
            self.quantity = Decimal(str(self.quantity))
        if isinstance(self.filled_quantity, (int, float)):
            self.filled_quantity = Decimal(str(self.filled_quantity))
        if self.limit_price and isinstance(self.limit_price, (int, float)):
            self.limit_price = Decimal(str(self.limit_price))
        if self.stop_price and isinstance(self.stop_price, (int, float)):
            self.stop_price = Decimal(str(self.stop_price))
        if self.avg_fill_price and isinstance(self.avg_fill_price, (int, float)):
            self.avg_fill_price = Decimal(str(self.avg_fill_price))
    
    @property
    def notional_value(self) -> Decimal:
        """Estimated notional value of the order."""
        if self.avg_fill_price:
            return self.filled_quantity * self.avg_fill_price
        elif self.limit_price:
            return self.quantity * self.limit_price
        else:
            # Use quantity as placeholder (will need current price)
            return self.quantity
    
    @property
    def is_filled(self) -> bool:
        """Check if order is completely filled."""
        return self.status == OrderStatus.FILLED
    
    @property
    def is_partially_filled(self) -> bool:
        """Check if order is partially filled."""
        return self.status == OrderStatus.PARTIALLY_FILLED
    
    @property
    def is_active(self) -> bool:
        """Check if order is still active."""
        return self.status in [
            OrderStatus.PENDING,
            OrderStatus.SUBMITTED,
            OrderStatus.PARTIALLY_FILLED,
        ]
    
    @property
    def remaining_quantity(self) -> Decimal:
        """Remaining quantity to fill."""
        return self.quantity - self.filled_quantity
    
    def fill(self, quantity: Decimal, price: Decimal) -> None:
        """Fill the order (or partially fill)."""
        if isinstance(quantity, (int, float)):
            quantity = Decimal(str(quantity))
        if isinstance(price, (int, float)):
            price = Decimal(str(price))
        
        if quantity > self.remaining_quantity:
            quantity = self.remaining_quantity
        
        # Update filled quantity
        total_filled = self.filled_quantity + quantity
        total_cost = (self.filled_quantity * (self.avg_fill_price or Decimal("0"))) + (quantity * price)
        
        self.filled_quantity = total_filled
        self.avg_fill_price = total_cost / total_filled if total_filled > 0 else price
        
        # Update status
        if self.filled_quantity >= self.quantity:
            self.status = OrderStatus.FILLED
            self.filled_at = datetime.now()
        else:
            self.status = OrderStatus.PARTIALLY_FILLED
        
        if not self.submitted_at:
            self.submitted_at = datetime.now()
    
    def cancel(self) -> None:
        """Cancel the order."""
        self.status = OrderStatus.CANCELLED
    
    def reject(self, reason: Optional[str] = None) -> None:
        """Reject the order."""
        self.status = OrderStatus.REJECTED
        if reason:
            self.reason = reason
    
    def to_dict(self) -> dict:
        """Convert order to dictionary."""
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": float(self.quantity),
            "order_type": self.order_type.value,
            "status": self.status.value,
            "limit_price": float(self.limit_price) if self.limit_price else None,
            "stop_price": float(self.stop_price) if self.stop_price else None,
            "filled_quantity": float(self.filled_quantity),
            "avg_fill_price": float(self.avg_fill_price) if self.avg_fill_price else None,
            "created_at": self.created_at.isoformat(),
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "filled_at": self.filled_at.isoformat() if self.filled_at else None,
            "strategy": self.strategy,
            "reason": self.reason,
            "order_id": self.order_id,
            "broker_order_id": self.broker_order_id,
        }
