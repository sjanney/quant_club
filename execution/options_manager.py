"""
Options Manager

Translates mean-reversion (and other) strategy signals into option overlays
using Alpaca's options API.

Overlay logic (requires Alpaca options level >= 2):
────────────────────────────────────────────────────────────────
Signal score >= 72  →  Buy OTM call  (directional long)
Signal score <= 28  →  Buy OTM put   (directional short / hedge)
Existing equity long + score in [55, 70]
                    →  Sell covered call (yield enhancement)

Contract selection:
- Expiry: 7–21 DTE (short-duration for Theta capture on covered calls,
  sufficient delta on directional buys)
- Strike for buy calls:  ~5% OTM (delta ≈ 0.30–0.40)
- Strike for buy puts:   ~5% OTM (delta ≈ -0.30 to -0.40)
- Strike for covered calls: ~3% OTM (delta ≈ 0.25–0.35, low assignment risk)
- Max spend per contract: options_max_notional_pct × equity
- Max contracts per symbol: options_max_contracts_per_symbol

Position sizing for option buys:
  max_spend = equity × options_max_notional_pct
  contracts = floor(max_spend / (premium × 100))
  capped at options_max_contracts_per_symbol

All orders use limit orders (mid of bid/ask approx via last close_price × 0.95
as conservative limit to ensure fills).
"""

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from config.settings import settings
from execution.broker import Broker

logger = logging.getLogger(__name__)


class OptionsManager:
    """
    Manages option overlay orders based on strategy signals and current positions.
    """

    def __init__(self, broker: Broker):
        self.broker = broker
        self.cfg = settings.options

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run_overlays(
        self,
        signals: Dict[str, float],
        equity: float,
        position_qtys: Dict[str, float],
    ) -> List[Dict]:
        """
        Evaluate signals and open positions; submit option orders as appropriate.

        Returns list of dicts describing each option order attempted.
        """
        options_level = self.broker.get_account_options_level()
        logger.info("Account options level: %d", options_level)

        if options_level < 2:
            logger.warning(
                "Options level %d < 2 — skipping directional option buys. "
                "Only covered calls (level 1) available.",
                options_level,
            )

        if options_level < 1:
            logger.warning("Options trading not enabled on this account. Skipping all overlays.")
            return []

        results = []

        for symbol, score in signals.items():
            current_qty = position_qtys.get(symbol, 0)

            # Directional buy overlays (require level >= 2)
            if options_level >= 2:
                if score >= self.cfg.strong_long_threshold:
                    result = self._buy_directional_option(
                        symbol=symbol,
                        option_type="call",
                        score=score,
                        equity=equity,
                    )
                    if result:
                        results.append(result)

                elif score <= self.cfg.strong_short_threshold:
                    result = self._buy_directional_option(
                        symbol=symbol,
                        option_type="put",
                        score=score,
                        equity=equity,
                    )
                    if result:
                        results.append(result)

            # Covered call yield overlay (requires level >= 1 and long equity position)
            if (options_level >= 1
                    and current_qty >= 100
                    and self.cfg.covered_call_min_score <= score <= self.cfg.covered_call_max_score):
                max_contracts = int(current_qty // 100)
                result = self._sell_covered_call(
                    symbol=symbol,
                    score=score,
                    equity=equity,
                    max_contracts=min(max_contracts, self.cfg.max_contracts_per_symbol),
                )
                if result:
                    results.append(result)

        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _buy_directional_option(
        self,
        symbol: str,
        option_type: str,
        score: float,
        equity: float,
    ) -> Optional[Dict]:
        """Find and buy a directional OTM call or put."""
        # Estimate current price from last known price (passed in via broker position or score)
        price = self._get_last_price(symbol)
        if not price:
            logger.warning("%s: cannot determine price for option sizing", symbol)
            return None

        # Strike selection: ~5% OTM
        otm_pct = self.cfg.directional_otm_pct
        if option_type == "call":
            target_strike = price * (1.0 + otm_pct)
        else:
            target_strike = price * (1.0 - otm_pct)

        contract = self._find_best_contract(
            symbol=symbol,
            option_type=option_type,
            target_strike=target_strike,
            min_dte=self.cfg.min_dte,
            max_dte=self.cfg.max_dte,
        )
        if not contract:
            logger.info("%s: no suitable %s contract found", symbol, option_type)
            return None

        premium = contract["close_price"]
        if premium <= 0:
            logger.warning("%s: contract %s has zero/missing premium", symbol, contract["symbol"])
            return None

        max_spend = equity * self.cfg.max_notional_pct
        contracts = min(
            int(max_spend / (premium * 100)),
            self.cfg.max_contracts_per_symbol,
        )
        if contracts <= 0:
            logger.info("%s: insufficient budget for %s option (premium $%.2f)",
                        symbol, option_type, premium)
            return None

        limit_price = round(premium * 0.95, 2)  # Conservative limit to get fill
        order_id = self.broker.submit_option_order(
            option_symbol=contract["symbol"],
            qty=contracts,
            side="buy",
            order_type="limit",
            limit_price=limit_price,
        )

        result = {
            "action": f"buy_{option_type}",
            "underlying": symbol,
            "option_symbol": contract["symbol"],
            "contracts": contracts,
            "limit_price": limit_price,
            "expiration": contract["expiration_date"],
            "strike": contract["strike_price"],
            "score": score,
            "order_id": order_id,
        }
        status = "submitted" if order_id else "failed"
        logger.info(
            "Option overlay [%s]: %s x%d @ $%.2f (strike=%.0f exp=%s score=%.1f) → %s",
            symbol, contract["symbol"], contracts, limit_price,
            contract["strike_price"], contract["expiration_date"], score, status,
        )
        return result

    def _sell_covered_call(
        self,
        symbol: str,
        score: float,
        equity: float,
        max_contracts: int,
    ) -> Optional[Dict]:
        """Sell a covered call ~3% OTM for yield enhancement."""
        price = self._get_last_price(symbol)
        if not price:
            return None

        target_strike = price * (1.0 + self.cfg.covered_call_otm_pct)

        contract = self._find_best_contract(
            symbol=symbol,
            option_type="call",
            target_strike=target_strike,
            min_dte=self.cfg.min_dte,
            max_dte=self.cfg.covered_call_max_dte,
        )
        if not contract:
            logger.info("%s: no suitable covered call contract found", symbol)
            return None

        premium = contract["close_price"]
        if premium <= 0:
            return None

        contracts = min(max_contracts, self.cfg.max_contracts_per_symbol)
        limit_price = round(premium * 1.05, 2)  # Slightly above last to improve fill on sell

        order_id = self.broker.submit_option_order(
            option_symbol=contract["symbol"],
            qty=contracts,
            side="sell",
            order_type="limit",
            limit_price=limit_price,
        )

        result = {
            "action": "sell_covered_call",
            "underlying": symbol,
            "option_symbol": contract["symbol"],
            "contracts": contracts,
            "limit_price": limit_price,
            "expiration": contract["expiration_date"],
            "strike": contract["strike_price"],
            "score": score,
            "order_id": order_id,
            "premium_collected": round(premium * 100 * contracts, 2),
        }
        status = "submitted" if order_id else "failed"
        logger.info(
            "Covered call [%s]: %s x%d @ $%.2f (strike=%.0f exp=%s) premium=$%.2f → %s",
            symbol, contract["symbol"], contracts, limit_price,
            contract["strike_price"], contract["expiration_date"],
            result["premium_collected"], status,
        )
        return result

    def _find_best_contract(
        self,
        symbol: str,
        option_type: str,
        target_strike: float,
        min_dte: int,
        max_dte: int,
    ) -> Optional[Dict]:
        """
        Query Alpaca for contracts and return the one with strike closest
        to target_strike, within the DTE window.
        """
        today = date.today()
        exp_gte = (today + timedelta(days=min_dte)).isoformat()
        exp_lte = (today + timedelta(days=max_dte)).isoformat()

        contracts = self.broker.get_option_contracts(
            underlying_symbol=symbol,
            contract_type=option_type,
            expiration_date_gte=exp_gte,
            expiration_date_lte=exp_lte,
            limit=50,
        )

        tradable = [c for c in contracts if c.get("tradable", True) and c.get("close_price", 0) > 0]
        if not tradable:
            return None

        # Pick contract with strike closest to target
        best = min(tradable, key=lambda c: abs(c["strike_price"] - target_strike))
        return best

    def _get_last_price(self, symbol: str) -> Optional[float]:
        """Get current price via broker positions or a lightweight account snapshot."""
        try:
            positions = self.broker.get_position_details()
            for p in positions:
                if p["symbol"] == symbol:
                    return float(p["current_price"])
        except Exception:
            pass
        return None
