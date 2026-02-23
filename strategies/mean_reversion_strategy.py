"""
Mean Reversion + Volatility Regime Strategy

Research basis:
- Jegadeesh (1990), Lo & MacKinlay (1990): short-horizon mean reversion in large-caps
- Ang et al. (2006): high-VIX environments favor short-vol/mean-reversion; low-VIX favors momentum
- RSI(2) extreme reversals: Connors & Alvarez "Short Term Trading Strategies That Work"

Core logic:
1. Compute RSI(2) for short-horizon oversold/overbought signal
2. Bollinger %B for distance from statistical mean
3. Rate-of-change (ROC) z-score for short-term momentum exhaustion
4. VIX regime filter: only trade mean reversion when VIX is in a "calm-to-moderate" range
   (VIX < 30 = green; 30-40 = yellow, reduce size; >40 = red, no longs)
5. Combine into 0-100 conviction score (> threshold → buy; < threshold → sell)

Options overlays (handled by OptionsManager, not here):
- Score > 72: buy OTM call (1-2 weeks out)
- Score < 28: buy OTM put (1-2 weeks out)
- Existing equity long + score 55-70: sell covered call for yield

Returns signal scores 0–100 per symbol. Higher = more bullish.
"""

import logging
from typing import Dict, Optional
import pandas as pd
import numpy as np

from strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Indicator helpers
# ---------------------------------------------------------------------------

def _rsi(series: pd.Series, period: int = 2) -> pd.Series:
    """Wilder's smoothed RSI."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def _bollinger_pct_b(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> pd.Series:
    """Bollinger %B: 0 = at lower band, 1 = at upper band, <0 or >1 = outside."""
    ma = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = ma + std * std_dev
    lower = ma - std * std_dev
    band_width = upper - lower
    return (series - lower) / band_width.replace(0, np.nan)


def _roc_zscore(series: pd.Series, roc_period: int = 5, z_window: int = 60) -> pd.Series:
    """Z-score of N-day rate of change — measures how extreme recent move is."""
    roc = series.pct_change(roc_period)
    z = (roc - roc.rolling(z_window).mean()) / roc.rolling(z_window).std().replace(0, np.nan)
    return z


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, min_periods=period).mean()


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------

class MeanReversionStrategy(BaseStrategy):
    """
    Volatility-filtered mean reversion on large-cap equities.

    Signal logic:
    - RSI(2): strong oversold (<10) → bullish; strong overbought (>90) → bearish
    - Bollinger %B: <0 (below lower band) → bullish; >1 (above upper) → bearish
    - ROC z-score: extreme negative z (<-2) after a down move → mean reversion buy
    - 50/200 EMA trend regime: trade with trend for entries, against for exits
    - VIX proxy: if "^VIX" or "VIXY" data available, scale conviction down in high-vol
    """

    DEFAULT_UNIVERSE = [
        "SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN",
        "GOOGL", "META", "TSLA", "AMD", "JPM", "GS",
    ]

    # Indicator weights (must sum to 1.0)
    W_RSI = 0.35
    W_BB = 0.30
    W_ROC_Z = 0.20
    W_TREND = 0.15

    def __init__(
        self,
        rsi_period: int = 2,
        bb_period: int = 20,
        bb_std: float = 2.0,
        roc_period: int = 5,
        roc_z_window: int = 60,
        ema_fast: int = 50,
        ema_slow: int = 200,
        atr_period: int = 14,
        vix_high_threshold: float = 30.0,   # VIX > this → reduce longs
        vix_extreme_threshold: float = 40.0, # VIX > this → no new longs
    ):
        super().__init__(
            name="MeanReversion",
            description=(
                "Volatility-filtered mean reversion: RSI(2) + Bollinger %B + "
                "ROC z-score + trend filter. Options overlays on extremes."
            ),
        )
        self.rsi_period = rsi_period
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.roc_period = roc_period
        self.roc_z_window = roc_z_window
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.atr_period = atr_period
        self.vix_high_threshold = vix_high_threshold
        self.vix_extreme_threshold = vix_extreme_threshold

        # Populated after generate_signals — used by options manager
        self.last_atrs: Dict[str, float] = {}
        self.last_prices: Dict[str, float] = {}
        self.last_vix: Optional[float] = None

    def get_required_bars(self) -> int:
        return max(self.ema_slow, self.bb_period + self.roc_z_window) + 10

    def get_universe(self) -> list:
        return list(self.DEFAULT_UNIVERSE)

    def generate_signals(self, data: Dict[str, pd.DataFrame]) -> Dict[str, float]:
        """
        Returns symbol → score 0–100.
        > 58 = long bias, < 42 = short bias, 42–58 = neutral.
        Extreme scores (>72 or <28) are candidates for options overlays.
        """
        signals: Dict[str, float] = {}
        self.last_atrs = {}
        self.last_prices = {}

        # Extract VIX level if available
        vix_level = self._extract_vix(data)
        self.last_vix = vix_level

        for symbol, df in data.items():
            if symbol in ("^VIX", "VIXY", "VIX"):
                continue
            if df is None or len(df) < self.get_required_bars():
                logger.debug("%s: skipped — %d bars < %d required",
                             symbol, 0 if df is None else len(df), self.get_required_bars())
                continue

            try:
                cols = {c.lower(): c for c in df.columns}
                if "close" not in cols:
                    continue
                close = df[cols["close"]].astype(float)
                high = df[cols.get("high", cols["close"])].astype(float)
                low = df[cols.get("low", cols["close"])].astype(float)

                price = close.iloc[-1]
                if price <= 0:
                    continue

                # --- Indicators ---
                rsi2 = _rsi(close, self.rsi_period)
                pct_b = _bollinger_pct_b(close, self.bb_period, self.bb_std)
                roc_z = _roc_zscore(close, self.roc_period, self.roc_z_window)
                ema_f = _ema(close, self.ema_fast)
                ema_s = _ema(close, self.ema_slow)
                atr_series = _atr(high, low, close, self.atr_period)

                v_rsi = self._safe_last(rsi2, 50.0)
                v_pct_b = self._safe_last(pct_b, 0.5)
                v_roc_z = self._safe_last(roc_z, 0.0)
                v_ema_f = self._safe_last(ema_f, price)
                v_ema_s = self._safe_last(ema_s, price)
                v_atr = self._safe_last(atr_series, price * 0.01)

                self.last_atrs[symbol] = v_atr
                self.last_prices[symbol] = price

                # --- Component scores [-1, +1] ---
                # RSI(2): oversold = bullish (score +1), overbought = bearish (score -1)
                # Smooth: RSI 5 → +1, RSI 50 → 0, RSI 95 → -1
                rsi_score = np.clip((50.0 - v_rsi) / 45.0, -1.0, 1.0)

                # Bollinger %B: <0 = below lower band (+1), >1 = above upper band (-1)
                # Smooth: pct_b 0 → +1, 0.5 → 0, 1 → -1
                bb_score = np.clip(1.0 - 2.0 * v_pct_b, -1.5, 1.5)
                bb_score = np.clip(bb_score, -1.0, 1.0)

                # ROC z-score: extreme negative (heavy down move) → mean reversion buy
                # z < -2 → +1, z > +2 → -1 (linear)
                roc_score = np.clip(-v_roc_z / 2.0, -1.0, 1.0)

                # Trend: fast > slow = uptrend (slight bullish bias for longs)
                # Normalize gap by ATR to make it price-agnostic
                trend_gap = (v_ema_f - v_ema_s) / max(v_atr, price * 0.001)
                trend_score = np.clip(trend_gap / 10.0, -1.0, 1.0)

                # --- Weighted composite ---
                composite = (
                    self.W_RSI * rsi_score
                    + self.W_BB * bb_score
                    + self.W_ROC_Z * roc_score
                    + self.W_TREND * trend_score
                )
                score = 50.0 + composite * 50.0
                score = float(np.clip(score, 0.0, 100.0))

                # --- VIX regime scaling ---
                if vix_level is not None:
                    if vix_level > self.vix_extreme_threshold:
                        # Extreme fear: suppress long signals, allow shorts
                        if score > 50:
                            score = 50.0 + (score - 50.0) * 0.25
                    elif vix_level > self.vix_high_threshold:
                        # Elevated VIX: reduce long conviction proportionally
                        scale = 1.0 - (vix_level - self.vix_high_threshold) / (self.vix_extreme_threshold - self.vix_high_threshold) * 0.6
                        if score > 50:
                            score = 50.0 + (score - 50.0) * max(scale, 0.4)

                score = float(np.clip(score, 0.0, 100.0))
                signals[symbol] = round(score, 2)

                logger.info(
                    "%s: $%.2f RSI2=%.1f %%B=%.2f ROCz=%.2f trend_gap=%.2f "
                    "| rsi=%.2f bb=%.2f roc=%.2f trend=%.2f → score=%.1f%s",
                    symbol, price, v_rsi, v_pct_b, v_roc_z, trend_gap,
                    rsi_score, bb_score, roc_score, trend_score, score,
                    f" [VIX={vix_level:.1f}]" if vix_level else "",
                )

            except Exception as e:
                logger.warning("%s: signal error — %s", symbol, e, exc_info=True)

        return signals

    def _extract_vix(self, data: Dict[str, pd.DataFrame]) -> Optional[float]:
        """Try to read VIX level from data dict (^VIX, VIXY, or VIX key)."""
        for key in ("^VIX", "VIXY", "VIX"):
            df = data.get(key)
            if df is not None and len(df) > 0:
                cols = {c.lower(): c for c in df.columns}
                if "close" in cols:
                    val = df[cols["close"]].iloc[-1]
                    if pd.notna(val) and float(val) > 0:
                        return float(val)
        return None

    @staticmethod
    def _safe_last(series: pd.Series, default: float) -> float:
        if len(series) == 0:
            return default
        val = series.iloc[-1]
        return default if pd.isna(val) else float(val)
