"""
HFT Executor

High-frequency trading execution loop for intraday scalping strategies.
Features:
- Per-position stop-loss / take-profit tracking
- End-of-day position flattening (no overnight risk)
- Per-symbol cooldown to prevent whipsaw
- Cached account data per cycle
- Realized + unrealized P&L tracking
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional
import os

from config.settings import settings
from execution.broker import Broker
from execution.order_manager import OrderManager
from execution.order_sizing import current_position_qtys
from core.order import OrderSide, OrderType
from monitoring.discord_notifier import send_discord_message

logger = logging.getLogger(__name__)


class _TrackedPosition:
    """Internal per-position state for SL/TP, trailing stop, and P&L."""

    __slots__ = ("symbol", "side", "entry_price", "quantity",
                 "stop_loss", "take_profit", "entry_time",
                 "atr", "highest_price", "lowest_price", "trailing_active")

    def __init__(self, symbol: str, side: str, entry_price: float,
                 quantity: float, stop_loss: float, take_profit: float,
                 atr: float = 0.0):
        self.symbol = symbol
        self.side = side  # "long" or "short"
        self.entry_price = entry_price
        self.quantity = abs(quantity)
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.entry_time = datetime.now()
        self.atr = atr
        # Trailing stop state
        self.highest_price = entry_price  # Best price seen (for longs)
        self.lowest_price = entry_price   # Best price seen (for shorts)
        self.trailing_active = False      # Activated once profit > 1x ATR


class HFTExecutor:
    """Executes HFT scalping strategy with risk management."""

    def __init__(self, strategy, data_provider, broker: Optional[Broker] = None):
        self.strategy = strategy
        self.data_provider = data_provider
        self.broker = broker or Broker()
        self.order_manager = OrderManager(self.broker)

        # Daily counters (reset externally or on new day)
        self.trades_today: int = 0
        self.realized_pnl: float = 0.0
        self.unrealized_pnl: float = 0.0

        # Per-position SL/TP tracking: symbol -> _TrackedPosition
        self._tracked: Dict[str, _TrackedPosition] = {}

        # Cooldown: symbol -> cycles remaining before allowed to re-enter
        self._cooldowns: Dict[str, int] = {}

        # Win/loss tracker: symbol -> {"wins": int, "losses": int}
        self._win_tracker: Dict[str, Dict] = {}

        # Broker positions snapshot (refreshed each cycle)
        self.positions_tracked: Dict[str, Dict] = {}

    # ------------------------------------------------------------------
    # Adopt orphan broker positions
    # ------------------------------------------------------------------

    def _adopt_broker_positions(self, prices: Dict[str, float]):
        """
        Pick up any broker positions that aren't in our tracker (e.g. from
        a previous run). Assign them ATR-based SL/TP so they get managed.
        """
        broker_positions = self.broker.get_position_details()
        for pos in broker_positions:
            sym = pos["symbol"]
            if sym in self._tracked:
                continue
            qty = float(pos["quantity"])
            if qty == 0:
                continue
            entry_px = float(pos["avg_entry_price"])
            current_px = prices.get(sym, entry_px)

            # Estimate ATR as 0.5% of price (conservative fallback)
            est_atr = current_px * 0.005
            cfg = settings.hft

            side = "long" if qty > 0 else "short"
            if side == "long":
                sl = current_px - est_atr * cfg.stop_loss_atr_mult
                tp = current_px + est_atr * cfg.take_profit_atr_mult
            else:
                sl = current_px + est_atr * cfg.stop_loss_atr_mult
                tp = current_px - est_atr * cfg.take_profit_atr_mult

            self._tracked[sym] = _TrackedPosition(
                symbol=sym, side=side,
                entry_price=entry_px, quantity=abs(qty),
                stop_loss=sl, take_profit=tp,
                atr=est_atr,
            )
            logger.info("ADOPTED orphan position: %s %s qty=%.0f entry=%.2f "
                        "SL=%.2f TP=%.2f (est ATR=%.3f)",
                        sym, side, abs(qty), entry_px, sl, tp, est_atr)

    # ------------------------------------------------------------------
    # Risk gate
    # ------------------------------------------------------------------

    def should_trade(self, symbol: str, signal: float,
                     account: Dict, position_count: int) -> bool:
        """Pre-trade risk checks (account data passed in, not re-fetched)."""
        cfg = settings.hft

        # Signal strength
        if signal >= 50 and signal < cfg.min_signal_strength:
            logger.debug("%s: signal %.1f too weak (need >= %.0f for long)",
                         symbol, signal, cfg.min_signal_strength)
            return False
        if signal < 50 and signal > (100 - cfg.min_signal_strength):
            logger.debug("%s: signal %.1f too weak (need <= %.0f for short)",
                         symbol, signal, 100 - cfg.min_signal_strength)
            return False

        # Max trades per day
        if self.trades_today >= cfg.max_trades_per_day:
            logger.debug("%s: max daily trades reached (%d)", symbol, cfg.max_trades_per_day)
            return False

        # Max concurrent positions
        if position_count >= cfg.max_positions:
            logger.debug("%s: max positions reached (%d)", symbol, cfg.max_positions)
            return False

        # Per-symbol cooldown
        if self._cooldowns.get(symbol, 0) > 0:
            logger.debug("%s: cooldown active (%d cycles left)",
                         symbol, self._cooldowns[symbol])
            return False

        # Auto-reduce: block symbols with < 30% win rate after 5+ trades
        tracker = self._win_tracker.get(symbol)
        if tracker:
            total = tracker["wins"] + tracker["losses"]
            if total >= 5:
                win_rate = tracker["wins"] / total
                if win_rate < 0.30:
                    logger.warning("%s: blocked — win rate %.0f%% (%d/%d trades)",
                                   symbol, win_rate * 100, tracker["wins"], total)
                    return False

        # Daily loss limit (use realized + unrealized)
        equity = float(account.get("equity", 0))
        total_pnl = self.realized_pnl + self.unrealized_pnl
        if equity > 0 and total_pnl < 0:
            loss_pct = abs(total_pnl) / equity
            if loss_pct >= cfg.max_daily_loss_pct:
                logger.warning("%s: daily loss limit hit (%.2f%%)", symbol, loss_pct * 100)
                return False

        return True

    # ------------------------------------------------------------------
    # Main cycle
    # ------------------------------------------------------------------

    def run_cycle(self) -> Dict:
        """Execute one full HFT cycle: data -> signals -> exits -> entries."""
        logger.info("=" * 60)
        logger.info("HFT CYCLE STARTED")
        logger.info("=" * 60)
        cfg = settings.hft

        if not self.broker.is_configured:
            logger.error("Broker not configured; skipping cycle")
            return {"error": "Broker not configured"}

        if not self.broker.is_market_open():
            logger.info("Market closed; skipping cycle")
            return {"error": "Market closed"}

        # --- Cache account data once per cycle ---
        account = self.broker.get_account()
        if not account:
            logger.error("Could not get account")
            return {"error": "Account unavailable"}
        equity = float(account["equity"])

        # --- Check EOD flattening ---
        if self._near_close():
            self._flatten_all_positions("EOD flatten")
            return {
                "action": "eod_flatten",
                "realized_pnl": self.realized_pnl,
                "trades_today": self.trades_today,
            }

        # --- Fetch data ---
        universe = self.strategy.get_universe()
        logger.info("Fetching data for %d symbols: %s", len(universe), universe)
        bars = self.data_provider.get_minute_bars(
            universe, limit=100, timeframe=cfg.bar_interval,
        )
        if not bars:
            logger.warning("No data fetched for any symbol; skipping cycle")
            return {"error": "No data"}

        logger.info("Data received: %s",
                     {s: f"{len(df)} bars" for s, df in bars.items()})

        # --- Generate signals ---
        signals = self.strategy.generate_signals(bars)
        logger.info("Signals: %s", {s: f"{v:.1f}" for s, v in signals.items()})

        actionable = {s: v for s, v in signals.items()
                      if v >= cfg.min_signal_strength or v <= (100 - cfg.min_signal_strength)}
        if not actionable:
            logger.info("No actionable signals (all between %.0f-%.0f); nothing to trade",
                        100 - cfg.min_signal_strength, cfg.min_signal_strength)

        # --- Current broker positions ---
        position_qtys = current_position_qtys(self.broker)
        quotes = self.data_provider.get_latest_quotes(list(set(
            list(signals.keys()) + list(self._tracked.keys()) + list(position_qtys.keys())
        )))
        prices = {sym: float(q["price"]) for sym, q in quotes.items()}

        # --- Phase 0: Adopt any orphan broker positions we don't track ---
        self._adopt_broker_positions(prices)

        # --- Phase 1: Check SL/TP exits on tracked positions ---
        exits_done = self._check_sl_tp_exits(prices)

        # --- Phase 2: Decrement cooldowns ---
        expired = [s for s, c in self._cooldowns.items() if c <= 0]
        for s in expired:
            del self._cooldowns[s]
        for s in list(self._cooldowns):
            self._cooldowns[s] -= 1

        # --- Phase 3: Enter new positions ---
        position_count = len([
            p for p in self._tracked.values() if p.quantity > 0
        ])
        # Also count positions we see on broker but aren't tracking locally
        for sym in position_qtys:
            if sym not in self._tracked and abs(position_qtys[sym]) > 0:
                position_count += 1

        orders_submitted = []
        signal_details = getattr(self.strategy, "signal_details", {})

        for symbol, signal in signals.items():
            if symbol not in prices:
                logger.debug("%s: skipped entry — no price quote available", symbol)
                continue
            if not self.should_trade(symbol, signal, account, position_count):
                continue
            if symbol in self._tracked:
                logger.debug("%s: skipped entry — already have tracked position", symbol)
                continue

            price = prices[symbol]

            # Adaptive position sizing: scale by signal conviction
            # Base size * multiplier that ranges from 0.5x (marginal) to 1.5x (max conviction)
            base_size = equity * cfg.position_size_pct
            if signal >= cfg.min_signal_strength:
                side = OrderSide.BUY
                pos_side = "long"
                conviction = (signal - cfg.min_signal_strength) / (100 - cfg.min_signal_strength)
            elif signal <= (100 - cfg.min_signal_strength):
                side = OrderSide.SELL
                pos_side = "short"
                conviction = ((100 - cfg.min_signal_strength) - signal) / (100 - cfg.min_signal_strength)
            else:
                continue

            # Confluence bonus: +25% for each extra confirming indicator
            detail = signal_details.get(symbol)
            conf_bonus = 0.0
            if detail and detail.confluence > cfg.min_confluence:
                conf_bonus = 0.25 * (detail.confluence - cfg.min_confluence)

            size_mult = 0.5 + conviction + conf_bonus
            size_mult = min(size_mult, 1.5)  # Cap at 1.5x base
            position_size = base_size * size_mult

            qty = Decimal(str(position_size / price)).quantize(Decimal("1"))
            if qty <= 0:
                continue

            # Get SL/TP and ATR from strategy signal details (or fallback)
            detail = signal_details.get(symbol)
            if detail:
                sl_price = detail.stop_loss
                tp_price = detail.take_profit
                pos_atr = detail.atr
            else:
                sl_price = price * (0.99 if pos_side == "long" else 1.01)
                tp_price = price * (1.015 if pos_side == "long" else 0.985)
                pos_atr = 0.0

            # Submit — use limit order slightly inside the spread for better fills
            if pos_atr > 0:
                # Place limit 0.25 ATR inside current price for a better fill
                offset = pos_atr * 0.25
                if pos_side == "long":
                    limit_px = Decimal(str(round(price - offset, 2)))
                else:
                    limit_px = Decimal(str(round(price + offset, 2)))
                entry_type = OrderType.LIMIT
            else:
                limit_px = None
                entry_type = OrderType.MARKET

            try:
                order = self.order_manager.submit_order(
                    symbol=symbol,
                    quantity=qty,
                    side=side,
                    order_type=entry_type,
                    limit_price=limit_px,
                    strategy=self.strategy.get_name(),
                    reason=f"HFT signal={signal:.1f} sz={size_mult:.2f}x",
                )
                if order and order.broker_order_id:
                    self._tracked[symbol] = _TrackedPosition(
                        symbol=symbol, side=pos_side,
                        entry_price=price, quantity=float(qty),
                        stop_loss=sl_price, take_profit=tp_price,
                        atr=pos_atr,
                    )
                    orders_submitted.append({
                        "symbol": symbol, "side": side.value,
                        "quantity": float(qty), "signal": signal,
                        "sl": sl_price, "tp": tp_price,
                        "order_id": order.broker_order_id,
                    })
                    self.trades_today += 1
                    position_count += 1
                    logger.info("ENTRY %s %s qty=%s sig=%.1f sz=%.2fx %s@%s SL=%.2f TP=%.2f",
                                symbol, pos_side, qty, signal, size_mult,
                                entry_type.value, limit_px if limit_px else "mkt",
                                sl_price, tp_price)
            except Exception as e:
                logger.error("Error submitting order for %s: %s", symbol, e)

        # --- Refresh broker positions for summary ---
        self._refresh_positions()

        # Diagnostic summary
        actionable_signals = {s: v for s, v in signals.items()
                              if v >= cfg.min_signal_strength or v <= (100 - cfg.min_signal_strength)}
        neutral_signals = {s: v for s, v in signals.items() if s not in actionable_signals}

        if len(orders_submitted) == 0:
            logger.info("=== NO ENTRIES THIS CYCLE ===")
            logger.info("  Signals generated: %d", len(signals))
            logger.info("  Actionable signals (>=%.0f or <=%.0f): %d",
                        cfg.min_signal_strength, 100 - cfg.min_signal_strength, len(actionable_signals))
            if actionable_signals:
                logger.info("  Actionable: %s", actionable_signals)
            if neutral_signals:
                logger.info("  Neutral (filtered): %s", neutral_signals)
            logger.info("  Current positions: %d (max: %d)", position_count, cfg.max_positions)
            logger.info("  Trades today: %d (max: %d)", self.trades_today, cfg.max_trades_per_day)
            logger.info("  Active cooldowns: %s", list(self._cooldowns.keys()) if self._cooldowns else "none")

        result = {
            "signals": signals,
            "orders_submitted": orders_submitted,
            "exits": exits_done,
            "positions": self.positions_tracked,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "total_pnl": self.realized_pnl + self.unrealized_pnl,
            "trades_today": self.trades_today,
        }

        logger.info(
            "HFT cycle done: %d entries, %d exits, %d positions, "
            "realized=%.2f unrealized=%.2f",
            len(orders_submitted), len(exits_done),
            len(self.positions_tracked),
            self.realized_pnl, self.unrealized_pnl,
        )
        return result

    # ------------------------------------------------------------------
    # SL / TP exit logic
    # ------------------------------------------------------------------

    def _check_sl_tp_exits(self, prices: Dict[str, float]) -> List[Dict]:
        """Check all tracked positions against SL/TP with trailing stop."""
        exits: List[Dict] = []
        to_remove = []

        for symbol, pos in self._tracked.items():
            current_price = prices.get(symbol)
            if current_price is None:
                continue

            # --- Update trailing stop ---
            if pos.atr > 0:
                if pos.side == "long":
                    if current_price > pos.highest_price:
                        pos.highest_price = current_price
                    # Activate trailing once profit exceeds 1x ATR
                    if not pos.trailing_active and (current_price - pos.entry_price) >= pos.atr:
                        pos.trailing_active = True
                        logger.info("%s: trailing stop ACTIVATED (price %.2f, entry %.2f, +%.2f ATR)",
                                    symbol, current_price, pos.entry_price, pos.atr)
                    if pos.trailing_active:
                        # Trail SL at highest_price minus 1x ATR (tighter than initial 1.5x)
                        new_sl = pos.highest_price - pos.atr
                        if new_sl > pos.stop_loss:
                            pos.stop_loss = new_sl
                else:  # short
                    if current_price < pos.lowest_price:
                        pos.lowest_price = current_price
                    if not pos.trailing_active and (pos.entry_price - current_price) >= pos.atr:
                        pos.trailing_active = True
                        logger.info("%s: trailing stop ACTIVATED (price %.2f, entry %.2f, +%.2f ATR)",
                                    symbol, current_price, pos.entry_price, pos.atr)
                    if pos.trailing_active:
                        new_sl = pos.lowest_price + pos.atr
                        if new_sl < pos.stop_loss:
                            pos.stop_loss = new_sl

            # --- Check exit conditions ---
            exit_reason = None
            if pos.side == "long":
                if current_price <= pos.stop_loss:
                    exit_reason = "trailing_stop" if pos.trailing_active else "stop_loss"
                elif current_price >= pos.take_profit:
                    exit_reason = "take_profit"
            else:
                if current_price >= pos.stop_loss:
                    exit_reason = "trailing_stop" if pos.trailing_active else "stop_loss"
                elif current_price <= pos.take_profit:
                    exit_reason = "take_profit"

            if exit_reason:
                exit_side = OrderSide.SELL if pos.side == "long" else OrderSide.BUY
                pnl = self._calc_pnl(pos, current_price)

                try:
                    order = self.order_manager.submit_order(
                        symbol=symbol,
                        quantity=Decimal(str(pos.quantity)),
                        side=exit_side,
                        order_type=OrderType.MARKET,
                        strategy=self.strategy.get_name(),
                        reason=f"HFT {exit_reason}",
                    )
                    if order and order.broker_order_id:
                        self.realized_pnl += pnl
                        self.trades_today += 1
                        exits.append({
                            "symbol": symbol, "reason": exit_reason,
                            "pnl": round(pnl, 2), "price": current_price,
                        })
                        to_remove.append(symbol)
                        # Track win/loss per symbol
                        if symbol not in self._win_tracker:
                            self._win_tracker[symbol] = {"wins": 0, "losses": 0}
                        if pnl > 0:
                            self._win_tracker[symbol]["wins"] += 1
                        else:
                            self._win_tracker[symbol]["losses"] += 1

                        logger.info("EXIT %s %s pnl=%.2f (%s) [W/L: %d/%d]",
                                    symbol, exit_reason, pnl,
                                    "profit" if pnl > 0 else "loss",
                                    self._win_tracker[symbol]["wins"],
                                    self._win_tracker[symbol]["losses"])
                except Exception as e:
                    logger.error("Error exiting %s: %s", symbol, e)

        for sym in to_remove:
            del self._tracked[sym]
            self._cooldowns[sym] = settings.hft.cooldown_cycles

        return exits

    @staticmethod
    def _calc_pnl(pos: _TrackedPosition, exit_price: float) -> float:
        if pos.side == "long":
            return (exit_price - pos.entry_price) * pos.quantity
        else:
            return (pos.entry_price - exit_price) * pos.quantity

    # ------------------------------------------------------------------
    # EOD flattening
    # ------------------------------------------------------------------

    def _near_close(self) -> bool:
        """Check if we are within N minutes of market close."""
        clock = self.broker.get_market_clock()
        if not clock or not clock.get("next_close"):
            return False
        try:
            close_time = datetime.fromisoformat(clock["next_close"])
            now = datetime.now(close_time.tzinfo)
            minutes_left = (close_time - now).total_seconds() / 60
            return 0 < minutes_left <= settings.hft.eod_flatten_minutes_before_close
        except Exception:
            return False

    def _flatten_all_positions(self, reason: str = "flatten"):
        """Close every tracked position and any residual broker positions."""
        logger.info("Flattening all positions: %s", reason)

        # Close tracked positions first
        for symbol, pos in list(self._tracked.items()):
            exit_side = OrderSide.SELL if pos.side == "long" else OrderSide.BUY
            try:
                self.order_manager.submit_order(
                    symbol=symbol,
                    quantity=Decimal(str(pos.quantity)),
                    side=exit_side,
                    order_type=OrderType.MARKET,
                    strategy=self.strategy.get_name(),
                    reason=reason,
                )
                self.trades_today += 1
            except Exception as e:
                logger.error("Error flattening %s: %s", symbol, e)

        # Close any broker positions not in our tracker
        position_qtys = current_position_qtys(self.broker)
        for symbol, qty in position_qtys.items():
            if qty == 0:
                continue
            side = OrderSide.SELL if qty > 0 else OrderSide.BUY
            try:
                self.order_manager.submit_order(
                    symbol=symbol,
                    quantity=Decimal(str(abs(qty))),
                    side=side,
                    order_type=OrderType.MARKET,
                    strategy=self.strategy.get_name(),
                    reason=f"{reason} (residual)",
                )
                self.trades_today += 1
            except Exception as e:
                logger.error("Error flattening residual %s: %s", symbol, e)

        self._tracked.clear()
        logger.info("All positions flattened (%s)", reason)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _refresh_positions(self):
        """Sync broker positions and update unrealized P&L."""
        positions = self.broker.get_position_details()
        self.positions_tracked = {
            pos["symbol"]: {
                "quantity": float(pos["quantity"]),
                "market_value": float(pos["market_value"]),
                "unrealized_pl": float(pos["unrealized_pl"]),
            }
            for pos in positions
        }
        self.unrealized_pnl = sum(
            p["unrealized_pl"] for p in self.positions_tracked.values()
        )

    def get_position_summary(self) -> Dict:
        return {
            "tracked_positions": {
                s: {"side": p.side, "entry": p.entry_price,
                    "qty": p.quantity, "sl": p.stop_loss, "tp": p.take_profit,
                    "trailing": p.trailing_active}
                for s, p in self._tracked.items()
            },
            "broker_positions": self.positions_tracked,
            "realized_pnl": round(self.realized_pnl, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "total_pnl": round(self.realized_pnl + self.unrealized_pnl, 2),
            "trades_today": self.trades_today,
            "active_cooldowns": dict(self._cooldowns),
            "win_tracker": dict(self._win_tracker),
        }
