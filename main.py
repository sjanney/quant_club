#!/usr/bin/env python3
"""
Trading Desk - Main Entry Point

Professional trading desk system for quantitative trading.
"""

import argparse
import os
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
from core.order import OrderType
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
from strategies.scalping_strategy import ScalpingStrategy
from strategies.mean_reversion_strategy import MeanReversionStrategy
from execution.options_manager import OptionsManager
from monitoring.performance import PerformanceMonitor
from monitoring.discord_notifier import send_discord_message
from backtest.engine import BacktestEngine
from backtest.results import BacktestResults
from data.realtime_data import RealtimeDataProvider
from execution.hft_executor import HFTExecutor

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
        send_discord_message(
            f"Market closed. Signals computed (no orders sent): {signals}"
        )
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
            send_discord_message(
                f"Paper trade submitted: {symbol} {side.value.upper()} {qty} (strategy={strategy.get_name()})"
            )
        elif order and order.status.value == "rejected":
            logger.warning("Order rejected: %s %s %s — %s", symbol, side.value, qty, order.reason)
            send_discord_message(
                f"Order rejected: {symbol} {side.value.upper()} {qty} — {order.reason}"
            )

    if not orders_to_send:
        send_discord_message("Live cycle completed: no orders generated from current signals.")

    logger.info("Live trading cycle complete")


def run_mean_reversion_trading(options: bool = True):
    """
    Run Mean Reversion + VIX Regime strategy with optional options overlays.

    Equity logic: after-hours style (compute signals → submit at market open).
    Options overlays: buy directional calls/puts on extreme signals; sell
    covered calls on moderate longs with existing equity positions.
    """
    logger.info("=" * 60)
    logger.info("TRADING DESK - MEAN REVERSION MODE")
    logger.info("=" * 60)

    broker = Broker()
    if not broker.is_configured:
        logger.error("Broker not configured. Set ALPACA_API_KEY and ALPACA_API_SECRET in .env")
        return

    account = broker.get_account()
    if not account:
        logger.error("Could not load account")
        return

    equity = float(account["equity"])
    logger.info("Account Equity: $%,.2f  Cash: $%,.2f", equity, account["cash"])

    cfg = settings.mean_reversion
    strategy = MeanReversionStrategy(
        rsi_period=cfg.rsi_period,
        bb_period=cfg.bb_period,
        roc_period=cfg.roc_period,
        roc_z_window=cfg.roc_z_window,
        ema_fast=cfg.ema_fast,
        ema_slow=cfg.ema_slow,
        vix_high_threshold=cfg.vix_high_threshold,
        vix_extreme_threshold=cfg.vix_extreme_threshold,
    )

    data_provider = MarketDataProvider()
    universe = list(cfg.universe)
    # Include VIX proxy for regime filter
    if cfg.vix_symbol and cfg.vix_symbol not in universe:
        universe.append(cfg.vix_symbol)

    logger.info("Fetching data for mean-reversion universe: %s", universe)
    data = data_provider.get_universe_data(universe)
    if not data:
        logger.error("No market data available")
        return

    signals = strategy.generate_signals(data)
    logger.info("Mean reversion signals: %s", signals)

    prices = data_provider.get_current_prices(list(signals.keys()))
    position_qtys = current_position_qtys(broker)

    # --- Liquidate positions no longer in signals (clean exit) ---
    _close_stale_positions(broker, position_qtys, signals, cfg)

    # --- Equity orders ---
    allow_orders = broker.is_market_open()
    if not allow_orders:
        logger.warning("Market is closed — signals computed, no equity orders sent")
        send_discord_message(
            f"[MeanReversion] Market closed. Signals: {signals}"
        )
    else:
        from decimal import Decimal
        shortable = set(cfg.shortable) if cfg.shortable else set()
        orders_to_send = signals_to_orders(
            signals,
            {k: v for k, v in prices.items() if v},
            position_qtys,
            equity,
            notional_pct=Decimal(str(cfg.notional_pct)),
            max_names=cfg.max_names,
            long_thresh=cfg.long_threshold,
            short_thresh=cfg.short_threshold,
            shortable=shortable,
        )

        order_manager = OrderManager(broker)
        for symbol, side, qty in orders_to_send:
            order = order_manager.submit_order(
                symbol=symbol,
                quantity=qty,
                side=side,
                order_type=OrderType.MARKET,
                strategy=strategy.get_name(),
                reason="mean-reversion signal",
            )
            if order and order.broker_order_id:
                logger.info("Equity order submitted: %s %s %s", symbol, side.value, qty)
                send_discord_message(
                    f"[MeanReversion] {symbol} {side.value.upper()} {qty} (score={signals.get(symbol, 'N/A'):.1f})"
                )

        if not orders_to_send:
            logger.info("No equity orders generated from current signals")

    # --- Options overlays ---
    if options and settings.options.enabled:
        logger.info("Running options overlays (options_enabled=%s)", settings.options.enabled)
        # Refresh positions after equity orders
        position_qtys = current_position_qtys(broker)
        options_manager = OptionsManager(broker)
        option_results = options_manager.run_overlays(signals, equity, position_qtys)

        if option_results:
            for r in option_results:
                status = "submitted" if r.get("order_id") else "failed"
                send_discord_message(
                    f"[Options] {r['action'].upper()} {r['option_symbol']} x{r['contracts']} "
                    f"@ ${r['limit_price']:.2f} (exp={r['expiration']} strike={r['strike']:.0f}) → {status}"
                )
            logger.info("Options overlays complete: %d orders", len(option_results))
        else:
            logger.info("No options overlays triggered")
    else:
        logger.info("Options overlays skipped (enabled=%s, --options=%s)",
                    settings.options.enabled, options)

    logger.info("Mean reversion cycle complete")


def _close_stale_positions(broker: "Broker", position_qtys: dict, signals: dict, cfg) -> None:
    """
    Sell any equity positions that are no longer in the strategy universe
    or whose signal has flipped to neutral (between short and long thresholds).
    Only closes positions not covered by active signals.
    """
    universe_set = set(cfg.universe)
    for symbol, qty in list(position_qtys.items()):
        if symbol not in universe_set:
            continue
        score = signals.get(symbol)
        if score is None:
            continue
        # If we're long and signal is no longer bullish (< long threshold), close
        if qty > 0 and score < cfg.long_threshold:
            logger.info(
                "Closing stale long %s (qty=%s, score=%.1f < threshold=%.1f)",
                symbol, qty, score, cfg.long_threshold,
            )
            from core.order import OrderSide, OrderType
            from decimal import Decimal
            om = OrderManager(broker)
            om.submit_order(
                symbol=symbol,
                quantity=Decimal(str(abs(qty))),
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                strategy="MeanReversion",
                reason="signal no longer bullish — exit",
            )
            send_discord_message(
                f"[MeanReversion] EXIT {symbol} SELL {abs(qty)} (score={score:.1f}, threshold={cfg.long_threshold})"
            )


def run_hft_trading(interval_seconds: int = 60, universe_override: str = ""):
    """Run HFT intraday scalping strategy."""
    logger.info("=" * 60)
    logger.info("TRADING DESK - HFT MODE (Intraday Scalping)")
    logger.info("=" * 60)

    broker = Broker()
    if not broker.is_configured:
        logger.error("Broker not configured. Set ALPACA_API_KEY and ALPACA_API_SECRET in .env")
        return

    if not broker.is_market_open():
        logger.warning("Market is closed — HFT only runs during market hours")
        return

    cfg = settings.hft
    strategy = ScalpingStrategy(
        bar_interval=cfg.bar_interval,
        stop_loss_atr_mult=cfg.stop_loss_atr_mult,
        take_profit_atr_mult=cfg.take_profit_atr_mult,
        min_confluence=cfg.min_confluence,
    )
    strategy.DEFAULT_UNIVERSE = list(cfg.universe)
    if universe_override:
        universe = [s.strip().upper() for s in universe_override.split(",") if s.strip()]
        strategy.DEFAULT_UNIVERSE = universe
        logger.info("Using custom universe: %s", universe)

    data_provider = RealtimeDataProvider()
    executor = HFTExecutor(strategy, data_provider, broker)

    logger.info("HFT config: size=%.0f%%, signal>=%.0f, SL=%.1fx ATR, TP=%.1fx ATR, "
                "EOD flatten=%d min, cooldown=%d cycles, confluence>=%d",
                cfg.position_size_pct * 100, cfg.min_signal_strength,
                cfg.stop_loss_atr_mult, cfg.take_profit_atr_mult,
                cfg.eod_flatten_minutes_before_close, cfg.cooldown_cycles,
                cfg.min_confluence)

    is_github_actions = os.getenv("GITHUB_ACTIONS") == "true"

    if is_github_actions:
        logger.info("Running in GitHub Actions: single cycle")
        result = executor.run_cycle()
        summary = executor.get_position_summary()
        logger.info("HFT cycle result: %s", result)
        logger.info("Position summary: %s", summary)

        parts = []
        if result.get("orders_submitted"):
            order_list = ", ".join([
                f"{o['symbol']} {o['side']} {o['quantity']:.0f}" for o in result["orders_submitted"][:5]
            ])
            parts.append(f"{len(result['orders_submitted'])} entries: {order_list}")
        if result.get("exits"):
            exit_list = ", ".join([
                f"{e['symbol']} {e['reason']} ${e['pnl']:+.2f}" for e in result["exits"][:5]
            ])
            parts.append(f"{len(result['exits'])} exits: {exit_list}")
        parts.append(f"P&L: ${summary.get('total_pnl', 0):+.2f}")
        send_discord_message(f"HFT cycle: {' | '.join(parts)}")
    else:
        logger.info("Running locally: continuous loop (interval=%ds)", interval_seconds)
        import time
        try:
            while True:
                if not broker.is_market_open():
                    logger.info("Market closed; stopping HFT loop")
                    break

                result = executor.run_cycle()
                
                # Check for early return errors
                if result.get("error"):
                    logger.warning("HFT cycle returned error: %s", result.get("error"))
                    time.sleep(interval_seconds)
                    continue
                
                summary = executor.get_position_summary()
                logger.info(
                    "HFT cycle: %d entries, %d exits, P&L=realized %.2f + unrealized %.2f = %.2f",
                    len(result.get("orders_submitted", [])),
                    len(result.get("exits", [])),
                    summary.get("realized_pnl", 0),
                    summary.get("unrealized_pnl", 0),
                    summary.get("total_pnl", 0),
                )

                time.sleep(interval_seconds)
        except KeyboardInterrupt:
            logger.info("HFT trading stopped by user")
            summary = executor.get_position_summary()
            logger.info("Final position summary: %s", summary)


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
        choices=["live", "backtest", "monitor", "after-hours", "execute-open", "scheduler", "hft", "mean-reversion"],
        default="backtest",
        help="Operation mode (mean-reversion=new VIX-filtered strategy with options)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run in dry-run mode (no real trades)",
    )
    parser.add_argument(
        "--strategy",
        choices=["rammageddon", "momentum", "mean-reversion"],
        default="rammageddon",
        help="Strategy for live and backtest (default: rammageddon)",
    )
    parser.add_argument(
        "--options",
        action="store_true",
        default=True,
        help="Enable options overlays for mean-reversion mode (default: True)",
    )
    parser.add_argument(
        "--no-options",
        action="store_true",
        help="Disable options overlays",
    )
    parser.add_argument(
        "--hft-interval",
        type=int,
        default=60,
        help="Seconds between HFT cycles (local only, default: 60)",
    )
    parser.add_argument(
        "--hft-universe",
        type=str,
        default="",
        help="Comma-separated symbols for HFT (default: SPY,QQQ,AAPL,MSFT,TSLA,NVDA)",
    )

    args = parser.parse_args()

    if args.dry_run:
        settings.dry_run = True
        logger.info("Running in DRY-RUN mode")

    use_options = args.options and not args.no_options

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
        elif args.mode == "hft":
            run_hft_trading(interval_seconds=args.hft_interval, universe_override=args.hft_universe)
        elif args.mode == "mean-reversion":
            run_mean_reversion_trading(options=use_options)
        else:
            logger.error(f"Unknown mode: {args.mode}")
    
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
