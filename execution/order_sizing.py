"""
Order sizing and signal-to-order conversion.

Shared by live trading and scheduled (after-hours) flow.
"""

from decimal import Decimal, ROUND_DOWN
from typing import Dict, List, Set, Tuple

from core.order import OrderSide
from execution.broker import Broker

# Defaults (can be overridden by caller)
DEFAULT_NOTIONAL_PCT = Decimal("0.12")
DEFAULT_MAX_NAMES = 5
DEFAULT_LONG_THRESHOLD = 58
DEFAULT_SHORT_THRESHOLD = 42
DEFAULT_SHORTABLE: Set[str] = {"DELL", "HPQ"}


def current_position_qtys(broker: Broker) -> Dict[str, float]:
    """Return symbol -> signed quantity (positive = long, negative = short)."""
    out: Dict[str, float] = {}
    for d in broker.get_position_details():
        sym = d["symbol"]
        qty = d["quantity"]
        out[sym] = int(qty) if qty == int(qty) else float(qty)
    return out


def signals_to_orders(
    signals: Dict[str, float],
    prices: Dict[str, Decimal],
    position_qtys: Dict[str, float],
    equity: float,
    notional_pct: Decimal = DEFAULT_NOTIONAL_PCT,
    max_names: int = DEFAULT_MAX_NAMES,
    long_thresh: int = DEFAULT_LONG_THRESHOLD,
    short_thresh: int = DEFAULT_SHORT_THRESHOLD,
    shortable: Set[str] = DEFAULT_SHORTABLE,
) -> List[Tuple[str, OrderSide, Decimal]]:
    """
    Convert signals (symbol -> score 0-100) and current positions into
    (symbol, side, quantity) to execute.
    """
    orders: List[Tuple[str, OrderSide, Decimal]] = []
    notional_per_name = equity * float(notional_pct)
    scored = [(s, sc) for s, sc in signals.items() if s in prices and prices[s]]
    scored.sort(key=lambda x: -abs(x[1] - 50))
    chosen = scored[:max_names]

    for symbol, score in chosen:
        price = prices.get(symbol)
        if not price or price <= 0:
            continue
        price_dec = Decimal(str(float(price)))
        current_qty = position_qtys.get(symbol, 0)
        target_shares = Decimal(0)

        if score >= long_thresh:
            target_shares = (Decimal(str(notional_per_name)) / price_dec).quantize(Decimal("1"), rounding=ROUND_DOWN)
            if target_shares <= 0:
                continue
        elif score <= short_thresh and symbol in shortable:
            target_shares = -(Decimal(str(notional_per_name)) / price_dec).quantize(Decimal("1"), rounding=ROUND_DOWN)
            if target_shares >= 0:
                continue

        current_dec = Decimal(str(current_qty))
        delta = target_shares - current_dec
        if delta == 0:
            continue

        qty = abs(delta)
        side = OrderSide.BUY if delta > 0 else OrderSide.SELL
        orders.append((symbol, side, qty))
    return orders
