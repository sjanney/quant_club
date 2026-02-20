"""
Scheduled trading: after-hours analysis and execute at market open.

- After market close: run strategy, compute target orders, save to state/scheduled_orders.json.
- At market open: load scheduled orders and submit to broker, then archive.

Can be run via:
  python main.py --mode after-hours   (one-shot after close)
  python main.py --mode execute-open (one-shot at open)
  python main.py --mode scheduler    (daemon: runs both at configured times)
Or via cron on a server (see SCHEDULER.md).
"""

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytz

from config.settings import settings
from execution.broker import Broker
from execution.order_manager import OrderManager
from execution.order_sizing import (
    current_position_qtys,
    signals_to_orders,
    DEFAULT_LONG_THRESHOLD,
    DEFAULT_MAX_NAMES,
    DEFAULT_NOTIONAL_PCT,
    DEFAULT_SHORT_THRESHOLD,
    DEFAULT_SHORTABLE,
)
from data.market_data import MarketDataProvider
from strategies.rammageddon_strategy import RAMmageddonStrategy
from core.order import OrderSide, OrderType
from decimal import Decimal
from monitoring.discord_notifier import send_discord_message

logger = logging.getLogger(__name__)

TZ = pytz.timezone(settings.schedule.timezone)


def _schedule_path() -> Path:
    return settings.schedule.state_dir / settings.schedule.scheduled_orders_file


def _scheduler_state_path() -> Path:
    return settings.schedule.state_dir / settings.schedule.scheduler_state_file


def save_scheduled_orders(
    orders: List[Dict[str, Any]],
    *,
    strategy_name: str = "RAMmageddon",
    equity_snapshot: float = 0.0,
    signals_snapshot: Dict[str, float] = None,
) -> Path:
    """Write scheduled orders to state/scheduled_orders.json."""
    path = _schedule_path()
    payload = {
        "generated_at_et": datetime.now(TZ).isoformat(),
        "strategy": strategy_name,
        "equity_snapshot": equity_snapshot,
        "signals_snapshot": signals_snapshot or {},
        "orders": orders,
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    logger.info("Saved %d scheduled orders to %s", len(orders), path)
    return path


def load_scheduled_orders() -> Optional[Dict[str, Any]]:
    """Load scheduled orders from state/scheduled_orders.json. Returns None if missing/invalid."""
    path = _schedule_path()
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Failed to load scheduled orders from %s: %s", path, e)
        return None


def archive_executed_orders(payload: Dict[str, Any]) -> Path:
    """Move executed payload to state/archive/ for audit."""
    settings.schedule.archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(TZ).strftime("%Y%m%d_%H%M%S")
    path = settings.schedule.archive_dir / f"executed_{stamp}.json"
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    return path


def _daily_report_path(prefix: str) -> Path:
    """Path for daily report file: state/daily_YYYY-MM-DD_<prefix>.txt."""
    settings.schedule.state_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    return settings.schedule.state_dir / f"daily_{today}_{prefix}.txt"


def _write_daily_after_hours(
    strategy_name: str,
    equity: float,
    signals: Dict[str, float],
    orders_payload: List[Dict[str, Any]],
) -> Path:
    """Write human-readable after-hours summary for the day."""
    path = _daily_report_path("after_hours")
    lines = [
        f"After-Hours Run: {datetime.now(TZ).isoformat()}",
        f"Strategy: {strategy_name}",
        f"Equity snapshot: {equity:,.2f}",
        "",
        "Signals:",
    ]
    for sym, val in sorted(signals.items()):
        lines.append(f"  {sym}: {val}")
    lines.append("")
    lines.append(f"Scheduled orders ({len(orders_payload)}):")
    for o in orders_payload:
        lines.append(f"  {o['symbol']} {o['side']} qty={o['quantity']}")
    path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote daily report: %s", path)
    return path


def _write_daily_execute_open(
    results: List[Tuple[str, str, float, str]],
    submitted_count: int,
    rejected_count: int,
    failed_count: int,
) -> Path:
    """Write human-readable execute-open summary (per-order outcome + counts)."""
    path = _daily_report_path("execute_open")
    lines = [
        f"Execute-Open Run: {datetime.now(TZ).isoformat()}",
        "",
        "Per-order results:",
    ]
    for symbol, side, qty, outcome in results:
        lines.append(f"  {symbol} {side} {qty}: {outcome}")
    lines.append("")
    lines.append(f"Summary: submitted={submitted_count} rejected={rejected_count} failed={failed_count}")
    path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote daily report: %s", path)
    return path


def _write_trade_metrics_report(
    order_ids: List[str],
    broker: Broker,
) -> Path:
    """Fetch fill info for submitted orders and write trade metrics report."""
    path = _daily_report_path("trade_metrics")
    lines = [
        f"Trade Metrics: {datetime.now(TZ).isoformat()}",
        "",
    ]
    total_filled_notional = 0.0
    for order_id in order_ids:
        details = broker.get_order_details(order_id) if order_id else None
        if not details:
            lines.append(f"  Order {order_id}: (could not fetch)")
            continue
        sym = details.get("symbol", "?")
        side = details.get("side", "?")
        qty_req = details.get("quantity", 0)
        qty_filled = details.get("filled_quantity", 0)
        fill_price = details.get("filled_avg_price")
        status = details.get("status", "?")
        filled_at = details.get("filled_at", "")
        notional = qty_filled * fill_price if (fill_price and qty_filled) else 0
        total_filled_notional += notional
        lines.append(f"  {sym} {side} qty_req={qty_req} filled={qty_filled} fill_price={fill_price} status={status} filled_at={filled_at} notional={notional:,.2f}")
    lines.append("")
    lines.append(f"Total filled notional: {total_filled_notional:,.2f}")
    path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote trade metrics report: %s", path)
    return path


def run_after_hours() -> bool:
    """
    Run after-market analysis: fetch data, run strategy, compute orders, save to state.
    Call after market close (e.g. 4:35 PM ET).
    """
    logger.info("Running after-hours analysis")
    broker = Broker()
    if not broker.is_configured:
        logger.error("Broker not configured; cannot fetch positions for after-hours analysis")
        return False

    account = broker.get_account()
    if not account:
        logger.error("Could not load account")
        return False

    equity = float(account["equity"])
    strategy = RAMmageddonStrategy()
    symbols = strategy.get_universe()
    data_provider = MarketDataProvider()
    data = data_provider.get_universe_data(symbols)
    if not data:
        logger.error("No market data for after-hours analysis")
        return False

    signals = strategy.generate_signals(data)
    prices = data_provider.get_current_prices(list(signals.keys()))
    position_qtys = current_position_qtys(broker)

    order_tuples = signals_to_orders(
        signals,
        {k: v for k, v in prices.items() if v},
        position_qtys,
        equity,
        notional_pct=DEFAULT_NOTIONAL_PCT,
        max_names=DEFAULT_MAX_NAMES,
        long_thresh=DEFAULT_LONG_THRESHOLD,
        short_thresh=DEFAULT_SHORT_THRESHOLD,
        shortable=DEFAULT_SHORTABLE,
    )

    orders_payload = [
        {"symbol": sym, "side": side.value, "quantity": float(qty)}
        for sym, side, qty in order_tuples
    ]
    save_scheduled_orders(
        orders_payload,
        strategy_name=strategy.get_name(),
        equity_snapshot=equity,
        signals_snapshot=signals,
    )
    _write_daily_after_hours(
        strategy_name=strategy.get_name(),
        equity=equity,
        signals=signals,
        orders_payload=orders_payload,
    )
    logger.info("After-hours analysis complete: %d orders scheduled", len(orders_payload))
    send_discord_message(
        f"After-hours analysis complete. Scheduled {len(orders_payload)} orders. Signals: {signals}"
    )
    return True


def run_execute_at_open() -> bool:
    """
    Load scheduled orders and submit to broker at market open.
    Archives the file after execution; writes daily report and trade metrics.
    """
    logger.info("Executing scheduled orders at market open")
    payload = load_scheduled_orders()
    if not payload or not payload.get("orders"):
        logger.info("No scheduled orders to execute")
        send_discord_message("Execute-open run: no scheduled orders found.")
        return True

    broker = Broker()
    if not broker.is_configured:
        logger.error("Broker not configured; cannot execute scheduled orders")
        return False

    order_manager = OrderManager(broker)
    results: List[Tuple[str, str, float, str]] = []
    submitted_order_ids: List[str] = []
    submitted_count = 0
    rejected_count = 0
    failed_count = 0

    for item in payload["orders"]:
        symbol = item["symbol"]
        side_str = item["side"]
        quantity = float(item["quantity"])
        side = OrderSide.BUY if side_str == "buy" else OrderSide.SELL
        order = None
        try:
            order = order_manager.submit_order(
                symbol=symbol,
                quantity=Decimal(str(quantity)),
                side=side,
                order_type=OrderType.MARKET,
                strategy=payload.get("strategy", "scheduled"),
                reason="scheduled at market open",
            )
        except Exception as e:
            logger.exception("Scheduled order failed: %s %s %s - %s", symbol, side_str, quantity, e)
            results.append((symbol, side_str, quantity, f"failed: {e}"))
            failed_count += 1
            continue

        if order and order.broker_order_id:
            submitted_count += 1
            submitted_order_ids.append(order.broker_order_id)
            results.append((symbol, side_str, quantity, "submitted"))
            logger.info("Submitted scheduled order: %s %s %s", symbol, side_str, quantity)
        elif order and getattr(order, "status", None) and str(getattr(order.status, "value", "")) == "rejected":
            rejected_count += 1
            reason = getattr(order, "reason", "rejected")
            results.append((symbol, side_str, quantity, f"rejected: {reason}"))
            logger.warning("Scheduled order rejected: %s %s %s - %s", symbol, side_str, quantity, reason)
        else:
            results.append((symbol, side_str, quantity, "failed (no order id)"))
            failed_count += 1
            logger.warning("Scheduled order failed (no order id): %s %s %s", symbol, side_str, quantity)

    _write_daily_execute_open(results, submitted_count, rejected_count, failed_count)

    if submitted_order_ids:
        time.sleep(2)
        _write_trade_metrics_report(submitted_order_ids, broker)

    archive_executed_orders(payload)
    _schedule_path().unlink(missing_ok=True)
    logger.info(
        "Execute-at-open complete: submitted=%d rejected=%d failed=%d",
        submitted_count, rejected_count, failed_count,
    )
    summary_line = f"Submitted {submitted_count}, rejected {rejected_count}, failed {failed_count}"
    discord_parts = [f"Execute-open complete. {summary_line} of {len(payload['orders'])} scheduled."]
    if results:
        short = ", ".join(f"{s} {side} {q}" for s, side, q, _ in results[:10])
        if len(results) > 10:
            short += f" (+{len(results) - 10} more)"
        discord_parts.append(f"Orders: {short}")
    send_discord_message("\n".join(discord_parts)[:1900])
    return True


def read_scheduler_state() -> Dict[str, str]:
    """Read last-run dates for after_hours and execute_open."""
    path = _scheduler_state_path()
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def write_scheduler_state(state: Dict[str, str]) -> None:
    """Write scheduler state (last run dates)."""
    with open(_scheduler_state_path(), "w") as f:
        json.dump(state, f, indent=2)


def should_run_after_hours(now_et: datetime) -> bool:
    """True if we're in the after-hours window and haven't run today."""
    cfg = settings.schedule
    window_start = now_et.replace(hour=cfg.after_hours_hour, minute=cfg.after_hours_minute, second=0, microsecond=0)
    window_end = window_start + timedelta(minutes=30)
    if not (window_start <= now_et <= window_end):
        return False
    today = now_et.date().isoformat()
    state = read_scheduler_state()
    if state.get("last_after_hours_date") == today:
        return False
    return True


def should_run_execute_open(now_et: datetime) -> bool:
    """True if we're in the market-open window and haven't run today."""
    cfg = settings.schedule
    window_start = now_et.replace(hour=cfg.market_open_hour, minute=cfg.market_open_minute, second=0, microsecond=0)
    window_end = window_start + timedelta(minutes=5)
    if not (window_start <= now_et <= window_end):
        return False
    today = now_et.date().isoformat()
    state = read_scheduler_state()
    if state.get("last_execute_open_date") == today:
        return False
    return True


def run_scheduler_loop(sleep_seconds: int = 60) -> None:
    """
    Daemon loop: every sleep_seconds, check if it's time to run after-hours or execute-open.
    Run the job and update scheduler state so we don't double-run the same day.
    """
    logger.info("Scheduler daemon started (timezone=%s, check every %ds)", settings.schedule.timezone, sleep_seconds)
    import time

    while True:
        now_et = datetime.now(TZ)
        state = read_scheduler_state()
        today = now_et.date().isoformat()

        if should_run_after_hours(now_et):
            try:
                run_after_hours()
                state["last_after_hours_date"] = today
                write_scheduler_state(state)
            except Exception as e:
                logger.exception("After-hours job failed: %s", e)

        if should_run_execute_open(now_et):
            try:
                run_execute_at_open()
                state["last_execute_open_date"] = today
                write_scheduler_state(state)
            except Exception as e:
                logger.exception("Execute-at-open job failed: %s", e)

        time.sleep(sleep_seconds)
