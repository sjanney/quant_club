"""
Backtest Engine

Walk-forward backtesting framework.
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional
import pandas as pd

from config.settings import settings
from core.portfolio import Portfolio
from core.order import Order, OrderSide, OrderStatus
from data.historical_data import HistoricalDataProvider
from strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


class BacktestEngine:
    """Backtesting engine with walk-forward analysis."""
    
    def __init__(self, strategy: BaseStrategy):
        """Initialize backtest engine."""
        self.strategy = strategy
        self.config = settings.backtest
        self.data_provider = HistoricalDataProvider()
        self.results: List[Dict] = []
    
    def run(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime,
    ) -> Dict:
        """Run backtest."""
        logger.info(f"Starting backtest: {start_date} to {end_date}")
        
        # Get historical data
        data = self.data_provider.get_universe_historical(
            symbols, start_date, end_date
        )
        
        if not data:
            logger.error("No data available for backtest")
            return {}
        
        # Initialize portfolio
        portfolio = Portfolio(initial_capital=Decimal(str(self.config.initial_capital)))
        
        # Get date range
        all_dates = set()
        for df in data.values():
            all_dates.update(df.index)
        dates = sorted(all_dates)
        dates = [d for d in dates if start_date <= d <= end_date]
        
        # Run simulation
        rebalance_dates = self._get_rebalance_dates(dates)
        
        for i, date in enumerate(dates):
            # Update prices
            prices = {}
            for symbol, df in data.items():
                if date in df.index:
                    close = df.loc[date, "close"] if "close" in df.columns else df.loc[date, "Close"]
                    prices[symbol] = Decimal(str(close))
            
            portfolio.update_prices(prices)
            
            # Rebalance on rebalance dates
            if date in rebalance_dates:
                self._rebalance(portfolio, data, date)
            
            # Record snapshot
            if i % 10 == 0 or date == dates[-1]:  # Record every 10 days
                snapshot = {
                    "date": date,
                    "equity": float(portfolio.total_equity),
                    "cash": float(portfolio.cash),
                    "positions": portfolio.num_positions,
                    "return_pct": portfolio.return_pct,
                    "drawdown_pct": portfolio.drawdown_pct,
                }
                self.results.append(snapshot)
        
        # Calculate final metrics
        equity_curve = pd.Series([r["equity"] for r in self.results], index=[r["date"] for r in self.results])
        returns = equity_curve.pct_change().dropna()
        
        return {
            "equity_curve": equity_curve,
            "returns": returns,
            "final_equity": float(portfolio.total_equity),
            "total_return": portfolio.return_pct,
            "max_drawdown": portfolio.drawdown_pct,
            "num_trades": len(portfolio.orders),
            "portfolio": portfolio.to_dict(),
        }
    
    def _get_rebalance_dates(self, dates: List[datetime]) -> List[datetime]:
        """Get rebalance dates based on frequency."""
        if self.config.rebalance_frequency == "daily":
            return dates
        elif self.config.rebalance_frequency == "weekly":
            # Every Monday
            return [d for d in dates if d.weekday() == self.config.rebalance_day]
        elif self.config.rebalance_frequency == "monthly":
            # First trading day of month
            rebalance_dates = []
            current_month = None
            for d in dates:
                if d.month != current_month:
                    rebalance_dates.append(d)
                    current_month = d.month
            return rebalance_dates
        else:
            return dates
    
    def _rebalance(
        self,
        portfolio: Portfolio,
        data: Dict[str, pd.DataFrame],
        date: datetime,
    ) -> None:
        """Rebalance portfolio."""
        # Get data up to current date
        current_data = {}
        for symbol, df in data.items():
            df_subset = df[df.index <= date].tail(self.strategy.get_required_bars())
            if len(df_subset) >= self.strategy.get_required_bars():
                current_data[symbol] = df_subset
        
        if not current_data:
            return
        
        # Generate signals
        signals = self.strategy.generate_signals(current_data)
        
        if not signals:
            return
        
        # Sort by signal strength
        sorted_signals = sorted(signals.items(), key=lambda x: x[1], reverse=True)
        
        # Select top positions
        target_positions = dict(sorted_signals[:settings.risk.max_positions])
        
        # Calculate target allocation
        total_equity = portfolio.total_equity
        position_size = total_equity / len(target_positions) if target_positions else 0
        
        # Close positions not in target
        current_symbols = set(portfolio.positions.keys())
        target_symbols = set(target_positions.keys())
        
        for symbol in current_symbols - target_symbols:
            pos = portfolio.positions[symbol]
            if not pos.is_empty():
                # Create sell order
                order = Order(
                    symbol=symbol,
                    side=OrderSide.SELL,
                    quantity=pos.quantity,
                    order_type=settings.trading.default_order_type,
                )
                order.status = OrderStatus.FILLED
                order.filled_quantity = pos.quantity
                order.avg_fill_price = pos.current_price
                order.filled_at = date
                
                portfolio.execute_order(order)
        
        # Open new positions
        for symbol in target_symbols - current_symbols:
            if symbol in current_data:
                df = current_data[symbol]
                price = Decimal(str(df["close"].iloc[-1] if "close" in df.columns else df["Close"].iloc[-1]))
                quantity = Decimal(str(int(position_size / price)))
                
                if quantity > 0:
                    order = Order(
                        symbol=symbol,
                        side=OrderSide.BUY,
                        quantity=quantity,
                        order_type=settings.trading.default_order_type,
                    )
                    order.status = OrderStatus.FILLED
                    order.filled_quantity = quantity
                    order.avg_fill_price = price
                    order.filled_at = date
                    
                    portfolio.execute_order(order)
