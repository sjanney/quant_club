#!/usr/bin/env python3
"""
Trading Desk - Main Entry Point

Professional trading desk system for quantitative trading.
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from decimal import Decimal

from config.settings import settings
from monitoring.logger import setup_logger
from core.portfolio import Portfolio
from core.order import OrderSide, OrderType
from risk.risk_manager import RiskManager
from execution.broker import Broker
from execution.order_manager import OrderManager
from execution.order_sizing import current_position_qtys, signals_to_orders
from execution.scheduled_trades import (
    run_after_hours,
    run_execute_at_open,
    run_scheduler_loop,
)
from data.market_data import MarketDataProvider
from strategies.momentum_strategy import MomentumStrategy
from strategies.rammageddon_strategy import RAMmageddonStrategy
from monitoring.performance import PerformanceMonitor
from backtest.engine import BacktestEngine
from backtest.results import BacktestResults

logger = setup_logger("trading_desk")

# Default strategy for live/backtest (RAMmageddon from research notebook)
LIVE_STRATEGY = RAMmageddonStrategy()
# Paper trading: max notional per name as fraction of equity, max names to trade
LIVE_NOTIONAL_PCT = Decimal("0.12")
LIVE_MAX_NAMES = 5
LIVE_LONG_THRESHOLD = 58
LIVE_SHORT_THRESHOLD = 42
# Symbols we allow shorting (OEM thesis)
LIVE_SHORTABLE = {"DELL", "HPQ"}


def run_live_trading():
    """Run live trading with RAMmageddon strategy (paper trading)."""
    logger.info("=" * 60)
    logger.info("TRADING DESK - LIVE MODE (RAMmageddon)")
    logger.info("=" * 60)

    broker = Broker()
    if not broker.is_configured:
        logger.error("Broker not configured. Set ALPACA_API_KEY and ALPACA_API_SECRET in .env")
        return

    portfolio = Portfolio(initial_capital=settings.trading.initial_capital)
    risk_manager = RiskManager()
    risk_manager.set_portfolio(portfolio)
    order_manager = OrderManager(broker, risk_manager)
    data_provider = MarketDataProvider()
    performance_monitor = PerformanceMonitor()

    account = broker.get_account()
    if not account:
        logger.error("Could not load account")
        return

    portfolio.cash = account["cash"]
    portfolio.initial_capital = account["equity"]
    equity = float(account["equity"])
    logger.info(f"Account Equity: ${equity:,.2f}")
    logger.info(f"Cash: ${account['cash']:,.2f}")

    position_details = broker.get_position_details()
    logger.info(f"Current Positions: {len(position_details)}")

    if not broker.is_market_open():
        logger.warning("Market is closed — no orders sent (signals still run for logging)")
        # Still run strategy and log signals; just don't submit orders
        allow_orders = False
    else:
        allow_orders = True

    # RAMmageddon universe
    strategy = LIVE_STRATEGY
    symbols = strategy.get_universe()
    logger.info("Fetching market data for RAMmageddon universe: %s", symbols)

    data = data_provider.get_universe_data(symbols)
    if not data:
        logger.error("No data available")
        return

    signals = strategy.generate_signals(data)
    logger.info("RAMmageddon signals: %s", signals)

    prices = data_provider.get_current_prices(list(signals.keys()))
    portfolio.update_prices(prices)
    performance_monitor.record_snapshot(portfolio)
    summary = performance_monitor.get_performance_summary()
    logger.info("Performance Summary: %s", summary)

    if not allow_orders:
        logger.info("Live trading cycle complete (no orders; market closed)")
        return

    position_qtys = current_position_qtys(broker)
    orders_to_send = signals_to_orders(
        signals,
        {k: v for k, v in prices.items() if v},
        position_qtys,
        equity,
        notional_pct=LIVE_NOTIONAL_PCT,
        max_names=LIVE_MAX_NAMES,
        long_thresh=LIVE_LONG_THRESHOLD,
        short_thresh=LIVE_SHORT_THRESHOLD,
        shortable=LIVE_SHORTABLE,
    )

    for symbol, side, qty in orders_to_send:
        order = order_manager.submit_order(
            symbol=symbol,
            quantity=qty,
            side=side,
            order_type=OrderType.MARKET,
            strategy=strategy.get_name(),
            reason="RAMmageddon signal",
        )
        if order and order.broker_order_id:
            logger.info("Submitted: %s %s %s", symbol, side.value, qty)
        elif order and order.status.value == "rejected":
            logger.warning("Order rejected: %s %s %s — %s", symbol, side.value, qty, order.reason)

    logger.info("Live trading cycle complete")


def run_backtest(strategy_name: str = "rammageddon"):
    """Run backtest (strategy: rammageddon | momentum)."""
    logger.info("=" * 60)
    logger.info("TRADING DESK - BACKTEST MODE")
    logger.info("=" * 60)

    if strategy_name == "rammageddon":
        strategy = RAMmageddonStrategy()
        symbols = strategy.get_universe()
    else:
        strategy = MomentumStrategy()
        symbols = settings.data.default_universe[:30]

    engine = BacktestEngine(strategy)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365 * 3)

    results = engine.run(symbols, start_date, end_date)
    backtest_results = BacktestResults(results)
    report = backtest_results.generate_report()
    logger.info("\n" + report)

    try:
        backtest_results.plot_equity_curve()
    except Exception as e:
        logger.warning(f"Could not plot results: {e}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Professional Trading Desk System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        choices=["live", "backtest", "monitor", "after-hours", "execute-open", "scheduler"],
        default="backtest",
        help="Operation mode (scheduler=daemon for after-hours + execute-open)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run in dry-run mode (no real trades)",
    )
    parser.add_argument(
        "--strategy",
        choices=["rammageddon", "momentum"],
        default="rammageddon",
        help="Strategy for live and backtest (default: rammageddon)",
    )

    args = parser.parse_args()

    if args.dry_run:
        settings.dry_run = True
        logger.info("Running in DRY-RUN mode")

    try:
        if args.mode == "live":
            run_live_trading()
        elif args.mode == "backtest":
            run_backtest(strategy_name=args.strategy)
        elif args.mode == "monitor":
            logger.info("Monitor mode - coming soon")
        elif args.mode == "after-hours":
            run_after_hours()
        elif args.mode == "execute-open":
            run_execute_at_open()
        elif args.mode == "scheduler":
            run_scheduler_loop(sleep_seconds=60)
        else:
            logger.error(f"Unknown mode: {args.mode}")
    
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
