"""
Broker Interface

Abstracts broker API interactions (Alpaca, etc.).
"""

import logging
from decimal import Decimal
from typing import Dict, List, Optional
from datetime import datetime

try:
    import alpaca_trade_api as tradeapi
    ALPACA_AVAILABLE = True
except ImportError:
    ALPACA_AVAILABLE = False

from config.settings import settings
from core.order import Order, OrderType, OrderSide, OrderStatus

logger = logging.getLogger(__name__)


class Broker:
    """Broker interface for executing trades."""
    
    def __init__(self):
        """Initialize broker."""
        self.config = settings.broker
        self.api = None
        self._is_paper_trading = False
        
        if ALPACA_AVAILABLE and self.config.api_key:
            try:
                # Verify we're using paper trading URL
                if "paper-api" in self.config.base_url.lower():
                    self._is_paper_trading = True
                    logger.info("Initializing Alpaca PAPER TRADING broker")
                else:
                    logger.warning("⚠️  WARNING: Not using paper trading URL!")
                    logger.warning(f"   Current URL: {self.config.base_url}")
                    logger.warning("   Paper trading URL: https://paper-api.alpaca.markets")
                
                self.api = tradeapi.REST(
                    self.config.api_key,
                    self.config.api_secret,
                    self.config.base_url,
                    api_version="v2",
                )
                
                # Verify connection by checking account
                try:
                    account = self.api.get_account()
                    trading_mode = "PAPER TRADING" if self._is_paper_trading else "LIVE TRADING"
                    logger.info(f"✓ Broker initialized: Alpaca ({trading_mode})")
                    logger.info(f"  Account Status: {account.status}")
                except Exception as e:
                    logger.error(f"Failed to verify broker connection: {e}")
                    logger.error("Please check your API credentials")
                    
            except Exception as e:
                logger.error(f"Failed to initialize broker: {e}")
                logger.error("Please check your .env configuration")
        else:
            if not ALPACA_AVAILABLE:
                logger.warning("alpaca-trade-api not installed - running in simulation mode")
            else:
                logger.warning("Broker not configured - running in simulation mode")
                logger.warning("Set ALPACA_API_KEY and ALPACA_API_SECRET in .env file")
    
    @property
    def is_paper_trading(self) -> bool:
        """Check if broker is configured for paper trading."""
        return self._is_paper_trading
    
    @property
    def is_configured(self) -> bool:
        """Check if broker is properly configured."""
        return self.api is not None
    
    def get_account(self) -> Optional[Dict]:
        """Get account information."""
        if not self.api:
            return None
        
        try:
            account = self.api.get_account()
            return {
                "equity": float(account.equity),
                "cash": float(account.cash),
                "buying_power": float(account.buying_power),
                "portfolio_value": float(account.portfolio_value),
                "day_trading_buying_power": float(account.daytrading_buying_power),
            }
        except Exception as e:
            logger.error(f"Error fetching account: {e}")
            return None
    
    def get_positions(self) -> Dict[str, Decimal]:
        """Get current positions (symbol -> market value)."""
        if not self.api:
            return {}
        
        try:
            positions = self.api.list_positions()
            result = {}
            for pos in positions:
                result[pos.symbol] = Decimal(str(float(pos.qty) * float(pos.current_price)))
            return result
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return {}
    
    def get_position_details(self) -> List[Dict]:
        """Get detailed position information."""
        if not self.api:
            return []
        
        try:
            positions = self.api.list_positions()
            result = []
            for pos in positions:
                result.append({
                    "symbol": pos.symbol,
                    "quantity": Decimal(str(pos.qty)),
                    "avg_entry_price": Decimal(str(pos.avg_entry_price)),
                    "current_price": Decimal(str(pos.current_price)),
                    "market_value": Decimal(str(float(pos.qty) * float(pos.current_price))),
                    "unrealized_pl": Decimal(str(pos.unrealized_pl)),
                    "unrealized_plpc": float(pos.unrealized_plpc),
                })
            return result
        except Exception as e:
            logger.error(f"Error fetching position details: {e}")
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
        """
        Submit an order and return order ID.
        
        Args:
            symbol: Stock symbol (e.g., 'AAPL')
            quantity: Number of shares (can be fractional if fractional=True)
            side: OrderSide.BUY or OrderSide.SELL
            order_type: OrderType.MARKET, LIMIT, STOP, or STOP_LIMIT
            limit_price: Required for LIMIT and STOP_LIMIT orders
            stop_price: Required for STOP and STOP_LIMIT orders
            time_in_force: 'day', 'gtc' (good-till-canceled), 'ioc' (immediate-or-cancel), 'fok' (fill-or-kill)
            fractional: Allow fractional shares (Alpaca supports this)
        
        Returns:
            Order ID if successful, None otherwise
        """
        if not self.api:
            logger.warning("Broker not configured - order not submitted")
            return None
        
        # Validate order parameters
        if quantity <= 0:
            logger.error(f"Invalid quantity: {quantity}")
            return None
        
        if order_type == OrderType.LIMIT and not limit_price:
            logger.error("Limit price required for LIMIT orders")
            return None
        
        if order_type == OrderType.STOP and not stop_price:
            logger.error("Stop price required for STOP orders")
            return None
        
        if order_type == OrderType.STOP_LIMIT:
            if not limit_price or not stop_price:
                logger.error("Both limit_price and stop_price required for STOP_LIMIT orders")
                return None
        
        try:
            order_params = {
                "symbol": symbol.upper(),
                "side": side.value,
                "type": order_type.value,
                "time_in_force": time_in_force,
            }
            
            # Alpaca supports fractional shares via notional parameter
            if fractional:
                order_params["notional"] = float(quantity)
            else:
                order_params["qty"] = float(quantity)
            
            if order_type == OrderType.LIMIT and limit_price:
                order_params["limit_price"] = float(limit_price)
            elif order_type == OrderType.STOP and stop_price:
                order_params["stop_price"] = float(stop_price)
            elif order_type == OrderType.STOP_LIMIT:
                if limit_price:
                    order_params["limit_price"] = float(limit_price)
                if stop_price:
                    order_params["stop_price"] = float(stop_price)
            
            trading_mode = "PAPER" if self._is_paper_trading else "LIVE"
            logger.info(f"[{trading_mode}] Submitting order: {symbol} {side.value} {quantity} @ {order_type.value}")
            
            order = self.api.submit_order(**order_params)
            logger.info(f"✓ Order submitted successfully: {order.id}")
            return order.id
        
        except Exception as e:
            logger.error(f"Error submitting order: {e}")
            logger.error(f"  Symbol: {symbol}, Side: {side.value}, Type: {order_type.value}")
            return None
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        if not self.api:
            return False
        
        try:
            self.api.cancel_order(order_id)
            logger.info(f"Order cancelled: {order_id}")
            return True
        except Exception as e:
            logger.error(f"Error cancelling order: {e}")
            return False
    
    def get_order_status(self, order_id: str) -> Optional[OrderStatus]:
        """Get order status."""
        if not self.api:
            return None
        
        try:
            order = self.api.get_order(order_id)
            status_map = {
                "new": OrderStatus.PENDING,
                "accepted": OrderStatus.SUBMITTED,
                "filled": OrderStatus.FILLED,
                "partially_filled": OrderStatus.PARTIALLY_FILLED,
                "canceled": OrderStatus.CANCELLED,
                "expired": OrderStatus.EXPIRED,
                "rejected": OrderStatus.REJECTED,
            }
            return status_map.get(order.status.lower(), OrderStatus.PENDING)
        except Exception as e:
            logger.error(f"Error fetching order status: {e}")
            return None
    
    def is_market_open(self) -> bool:
        """Check if market is open."""
        if not self.api:
            return False
        
        try:
            clock = self.api.get_clock()
            return clock.is_open
        except Exception as e:
            logger.error(f"Error checking market status: {e}")
            return False
    
    def get_market_clock(self) -> Optional[Dict]:
        """Get detailed market clock information."""
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
            logger.error(f"Error fetching market clock: {e}")
            return None
    
    def get_all_orders(self, status: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """Get all orders, optionally filtered by status."""
        if not self.api:
            return []
        
        try:
            orders = self.api.list_orders(status=status, limit=limit)
            result = []
            for order in orders:
                result.append({
                    "id": order.id,
                    "symbol": order.symbol,
                    "side": order.side,
                    "quantity": float(order.qty),
                    "filled_quantity": float(order.filled_qty) if order.filled_qty else 0,
                    "order_type": order.order_type,
                    "status": order.status,
                    "time_in_force": order.time_in_force,
                    "limit_price": float(order.limit_price) if order.limit_price else None,
                    "stop_price": float(order.stop_price) if order.stop_price else None,
                    "created_at": order.created_at.isoformat() if order.created_at else None,
                    "filled_at": order.filled_at.isoformat() if order.filled_at else None,
                })
            return result
        except Exception as e:
            logger.error(f"Error fetching orders: {e}")
            return []
