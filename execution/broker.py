"""
Broker Interface

Abstracts broker API interactions (Alpaca via alpaca-py).
"""

import logging
from decimal import Decimal
from typing import Dict, List, Optional
from datetime import datetime

try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import (
        MarketOrderRequest,
        LimitOrderRequest,
        StopOrderRequest,
        StopLimitOrderRequest,
        GetOrdersRequest,
    )
    from alpaca.trading.enums import (
        OrderSide as AlpacaSide,
        TimeInForce,
        QueryOrderStatus,
    )
    ALPACA_AVAILABLE = True
except ImportError:
    ALPACA_AVAILABLE = False

from config.settings import settings
from core.order import Order, OrderType, OrderSide, OrderStatus

logger = logging.getLogger(__name__)

_SIDE_MAP = {
    OrderSide.BUY: AlpacaSide.BUY if ALPACA_AVAILABLE else None,
    OrderSide.SELL: AlpacaSide.SELL if ALPACA_AVAILABLE else None,
}

_STATUS_MAP = {
    "new": OrderStatus.PENDING,
    "accepted": OrderStatus.SUBMITTED,
    "filled": OrderStatus.FILLED,
    "partially_filled": OrderStatus.PARTIALLY_FILLED,
    "canceled": OrderStatus.CANCELLED,
    "expired": OrderStatus.EXPIRED,
    "rejected": OrderStatus.REJECTED,
}


class Broker:
    """Broker interface for executing trades."""

    def __init__(self):
        """Initialize broker."""
        self.config = settings.broker
        self.api: Optional["TradingClient"] = None
        self._is_paper_trading = False

        if ALPACA_AVAILABLE and self.config.api_key:
            try:
                self._is_paper_trading = "paper-api" in self.config.base_url.lower()
                if self._is_paper_trading:
                    logger.info("Initializing Alpaca PAPER TRADING broker")
                else:
                    logger.warning("WARNING: Not using paper trading URL!")
                    logger.warning("  Current URL: %s", self.config.base_url)

                self.api = TradingClient(
                    api_key=self.config.api_key,
                    secret_key=self.config.api_secret,
                    paper=self._is_paper_trading,
                )

                try:
                    account = self.api.get_account()
                    mode = "PAPER TRADING" if self._is_paper_trading else "LIVE TRADING"
                    logger.info("Broker initialized: Alpaca (%s)", mode)
                    logger.info("  Account Status: %s", account.status)
                except Exception as e:
                    logger.error("Failed to verify broker connection: %s", e)

            except Exception as e:
                logger.error("Failed to initialize broker: %s", e)
        else:
            if not ALPACA_AVAILABLE:
                logger.warning("alpaca-py not installed - running in simulation mode")
            else:
                logger.warning("Broker not configured - running in simulation mode")
                logger.warning("Set ALPACA_API_KEY and ALPACA_API_SECRET in .env file")

    @property
    def is_paper_trading(self) -> bool:
        return self._is_paper_trading

    @property
    def is_configured(self) -> bool:
        return self.api is not None

    def get_account(self) -> Optional[Dict]:
        if not self.api:
            return None
        try:
            account = self.api.get_account()
            return {
                "equity": float(account.equity),
                "cash": float(account.cash),
                "buying_power": float(account.buying_power),
                "portfolio_value": float(account.portfolio_value),
                "day_trading_buying_power": float(getattr(account, "daytrading_buying_power", 0) or 0),
            }
        except Exception as e:
            logger.error("Error fetching account: %s", e)
            return None

    def get_positions(self) -> Dict[str, Decimal]:
        if not self.api:
            return {}
        try:
            positions = self.api.get_all_positions()
            return {
                pos.symbol: Decimal(str(float(pos.qty) * float(pos.current_price)))
                for pos in positions
            }
        except Exception as e:
            logger.error("Error fetching positions: %s", e)
            return {}

    def get_position_details(self) -> List[Dict]:
        if not self.api:
            return []
        try:
            positions = self.api.get_all_positions()
            return [
                {
                    "symbol": pos.symbol,
                    "quantity": Decimal(str(pos.qty)),
                    "avg_entry_price": Decimal(str(pos.avg_entry_price)),
                    "current_price": Decimal(str(pos.current_price)),
                    "market_value": Decimal(str(float(pos.qty) * float(pos.current_price))),
                    "unrealized_pl": Decimal(str(pos.unrealized_pl)),
                    "unrealized_plpc": float(pos.unrealized_plpc),
                }
                for pos in positions
            ]
        except Exception as e:
            logger.error("Error fetching position details: %s", e)
            return []

    def submit_order(
        self,
        symbol: str,
        quantity: Decimal,
        side: OrderSide,
        order_type: OrderType = OrderType.MARKET,
        limit_price: Optional[Decimal] = None,
        stop_price: Optional[Decimal] = None,
        time_in_force: str = "day",
        fractional: bool = False,
    ) -> Optional[str]:
        """Submit an order and return order ID."""
        if not self.api:
            logger.warning("Broker not configured - order not submitted")
            return None

        if quantity <= 0:
            logger.error("Invalid quantity: %s", quantity)
            return None

        if order_type == OrderType.LIMIT and not limit_price:
            logger.error("Limit price required for LIMIT orders")
            return None
        if order_type == OrderType.STOP and not stop_price:
            logger.error("Stop price required for STOP orders")
            return None
        if order_type == OrderType.STOP_LIMIT and (not limit_price or not stop_price):
            logger.error("Both limit_price and stop_price required for STOP_LIMIT orders")
            return None

        tif = TimeInForce.DAY if time_in_force == "day" else TimeInForce.GTC
        alpaca_side = _SIDE_MAP[side]

        try:
            qty_val = float(quantity)
            if order_type == OrderType.MARKET:
                req = MarketOrderRequest(
                    symbol=symbol.upper(),
                    qty=qty_val if not fractional else None,
                    notional=qty_val if fractional else None,
                    side=alpaca_side,
                    time_in_force=tif,
                )
            elif order_type == OrderType.LIMIT:
                req = LimitOrderRequest(
                    symbol=symbol.upper(),
                    qty=qty_val,
                    side=alpaca_side,
                    time_in_force=tif,
                    limit_price=float(limit_price),
                )
            elif order_type == OrderType.STOP:
                req = StopOrderRequest(
                    symbol=symbol.upper(),
                    qty=qty_val,
                    side=alpaca_side,
                    time_in_force=tif,
                    stop_price=float(stop_price),
                )
            elif order_type == OrderType.STOP_LIMIT:
                req = StopLimitOrderRequest(
                    symbol=symbol.upper(),
                    qty=qty_val,
                    side=alpaca_side,
                    time_in_force=tif,
                    limit_price=float(limit_price),
                    stop_price=float(stop_price),
                )
            else:
                logger.error("Unsupported order type: %s", order_type)
                return None

            mode = "PAPER" if self._is_paper_trading else "LIVE"
            logger.info(
                "[%s] Submitting order: %s %s %s @ %s",
                mode, symbol, side.value, quantity, order_type.value,
            )

            order = self.api.submit_order(order_data=req)
            logger.info("Order submitted successfully: %s", order.id)
            return str(order.id)

        except Exception as e:
            logger.error("Error submitting order: %s", e)
            logger.error("  Symbol: %s, Side: %s, Type: %s", symbol, side.value, order_type.value)
            return None

    def cancel_order(self, order_id: str) -> bool:
        if not self.api:
            return False
        try:
            self.api.cancel_order_by_id(order_id)
            logger.info("Order cancelled: %s", order_id)
            return True
        except Exception as e:
            logger.error("Error cancelling order: %s", e)
            return False

    def get_order_status(self, order_id: str) -> Optional[OrderStatus]:
        if not self.api:
            return None
        try:
            order = self.api.get_order_by_id(order_id)
            return _STATUS_MAP.get(order.status.value if hasattr(order.status, 'value') else str(order.status).lower(), OrderStatus.PENDING)
        except Exception as e:
            logger.error("Error fetching order status: %s", e)
            return None

    def is_market_open(self) -> bool:
        if not self.api:
            return False
        try:
            clock = self.api.get_clock()
            return clock.is_open
        except Exception as e:
            logger.error("Error checking market status: %s", e)
            return False

    def get_market_clock(self) -> Optional[Dict]:
        if not self.api:
            return None
        try:
            clock = self.api.get_clock()
            return {
                "is_open": clock.is_open,
                "next_open": clock.next_open.isoformat() if clock.next_open else None,
                "next_close": clock.next_close.isoformat() if clock.next_close else None,
            }
        except Exception as e:
            logger.error("Error fetching market clock: %s", e)
            return None

    def _order_to_dict(self, o) -> Dict:
        """Convert broker order object to dict with fill info for metrics."""
        filled_qty = float(o.filled_qty) if o.filled_qty else 0
        fill_price = getattr(o, "filled_avg_price", None)
        if fill_price is not None:
            try:
                fill_price = float(fill_price)
            except (TypeError, ValueError):
                fill_price = None
        return {
            "id": str(o.id),
            "symbol": o.symbol,
            "side": o.side.value if hasattr(o.side, "value") else str(o.side),
            "quantity": float(o.qty) if o.qty else 0,
            "filled_quantity": filled_qty,
            "filled_avg_price": fill_price,
            "order_type": o.order_type.value if hasattr(o.order_type, "value") else str(o.order_type),
            "status": o.status.value if hasattr(o.status, "value") else str(o.status),
            "time_in_force": o.time_in_force.value if hasattr(o.time_in_force, "value") else str(o.time_in_force),
            "limit_price": float(o.limit_price) if o.limit_price else None,
            "stop_price": float(o.stop_price) if o.stop_price else None,
            "created_at": o.created_at.isoformat() if o.created_at else None,
            "filled_at": o.filled_at.isoformat() if o.filled_at else None,
        }

    def get_order_details(self, order_id: str) -> Optional[Dict]:
        """Fetch one order by ID with fill info for metrics."""
        if not self.api:
            return None
        try:
            order = self.api.get_order_by_id(order_id)
            return self._order_to_dict(order)
        except Exception as e:
            logger.error("Error fetching order %s: %s", order_id, e)
            return None

    def get_all_orders(self, status: Optional[str] = None, limit: int = 50) -> List[Dict]:
        if not self.api:
            return []
        try:
            params = GetOrdersRequest(limit=limit)
            if status:
                params.status = QueryOrderStatus(status)
            orders = self.api.get_orders(filter=params)
            return [self._order_to_dict(o) for o in orders]
        except Exception as e:
            logger.error("Error fetching orders: %s", e)
            return []
