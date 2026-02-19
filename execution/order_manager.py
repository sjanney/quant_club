"""
Order Manager

Manages order lifecycle and execution.
"""

import logging
from decimal import Decimal
from typing import Dict, List, Optional
from datetime import datetime

from core.order import Order, OrderType, OrderSide, OrderStatus
from execution.broker import Broker
from risk.risk_manager import RiskManager

logger = logging.getLogger(__name__)


class OrderManager:
    """Manages order execution and tracking."""
    
    def __init__(self, broker: Optional[Broker] = None, risk_manager: Optional[RiskManager] = None):
        """Initialize order manager."""
        self.broker = broker or Broker()
        self.risk_manager = risk_manager
        self.pending_orders: Dict[str, Order] = {}
        self.filled_orders: List[Order] = []
    
    def submit_order(
        self,
        symbol: str,
        quantity: Decimal,
        side: OrderSide,
        order_type: OrderType = OrderType.MARKET,
        limit_price: Optional[Decimal] = None,
        stop_price: Optional[Decimal] = None,
        strategy: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Optional[Order]:
        """Submit an order."""
        # Create order object
        order = Order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            stop_price=stop_price,
            strategy=strategy,
            reason=reason,
        )
        
        # Risk check if risk manager is available
        if self.risk_manager:
            order_value = quantity * (limit_price or Decimal("100"))  # Estimate
            check = self.risk_manager.check_trade(symbol, order_value)
            if not check.passed:
                order.reject(check.reason)
                logger.warning(f"Order rejected: {check.reason}")
                return order
        
        # Submit to broker
        broker_order_id = self.broker.submit_order(
            symbol=symbol,
            quantity=quantity,
            side=side,
            order_type=order_type,
            limit_price=limit_price,
            stop_price=stop_price,
        )
        
        if broker_order_id:
            order.broker_order_id = broker_order_id
            order.status = OrderStatus.SUBMITTED
            order.submitted_at = datetime.now()
            self.pending_orders[broker_order_id] = order
            logger.info(f"Order submitted: {symbol} {side.value} {quantity}")
        else:
            order.reject("Broker submission failed")
            logger.error(f"Order submission failed: {symbol}")
        
        return order
    
    def update_order_status(self, order_id: str) -> Optional[Order]:
        """Update order status from broker."""
        order = self.pending_orders.get(order_id)
        if not order:
            return None
        
        status = self.broker.get_order_status(order_id)
        if status:
            order.status = status
            
            if status == OrderStatus.FILLED:
                # Move to filled orders
                self.pending_orders.pop(order_id, None)
                self.filled_orders.append(order)
                order.filled_at = datetime.now()
        
        return order
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        order = self.pending_orders.get(order_id)
        if not order:
            return False
        
        success = self.broker.cancel_order(order_id)
        if success:
            order.cancel()
            self.pending_orders.pop(order_id, None)
        
        return success
    
    def get_pending_orders(self) -> List[Order]:
        """Get all pending orders."""
        return list(self.pending_orders.values())
    
    def get_filled_orders(self) -> List[Order]:
        """Get all filled orders."""
        return self.filled_orders.copy()
