"""
Scalping Strategy (HFT Intraday) — Aggressive

Confluence scalping with continuous-gradient scoring:
- Wilder's RSI with smooth gradient (not binary thresholds)
- Bollinger Bands %B position
- VWAP distance normalized by ATR
- EMA trend filter (9/21) with slope strength
- MACD histogram momentum with acceleration
- Volume spike detection
- Open Range Breakout (ORB) for first 15 minutes
- ATR-based stop-loss / take-profit levels

Returns signal dicts per symbol with score 0-100 and suggested SL/TP levels.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List
import pandas as pd
import numpy as np

from strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

def _rsi_wilder(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def _bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2.0):
    ma = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = ma + std * std_dev
    lower = ma - std * std_dev
    return upper, ma, lower


def _percent_b(close: float, upper: float, lower: float) -> float:
    """Bollinger %B: 0 = at lower band, 1 = at upper band."""
    band_width = upper - lower
    if band_width <= 0:
        return 0.5
    return (close - lower) / band_width


def _vwap(close: pd.Series, high: pd.Series, low: pd.Series, volume: pd.Series) -> pd.Series:
    typical_price = (high + low + close) / 3.0
    cum_tp_vol = (typical_price * volume).cumsum()
    cum_vol = volume.cumsum().replace(0, np.nan)
    return cum_tp_vol / cum_vol


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = _ema(series, fast)
    ema_slow = _ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, min_periods=period).mean()


# ---------------------------------------------------------------------------
# Signal detail
# ---------------------------------------------------------------------------

@dataclass
class ScalpSignal:
    score: float
    confluence: int
    stop_loss: float
    take_profit: float
    atr: float


class ScalpingStrategy(BaseStrategy):
    """
    Aggressive confluence scalping with continuous gradient scoring.
    """

    DEFAULT_UNIVERSE = ["SPY", "QQQ", "AAPL", "MSFT", "TSLA", "NVDA",
                        "AMD", "META", "AMZN", "GOOGL"]

    # Weights — VWAP and ORB get heaviest weight for intraday
    WEIGHT_RSI = 0.15
    WEIGHT_BB = 0.10
    WEIGHT_VWAP = 0.20
    WEIGHT_EMA_TREND = 0.10
    WEIGHT_MACD = 0.15
    WEIGHT_VOLUME = 0.10
    WEIGHT_ORB = 0.20

    def __init__(
        self,
        rsi_period: int = 10,        # Faster RSI for scalping
        bb_period: int = 20,
        bb_std: float = 2.0,
        volume_multiplier: float = 1.5,  # Lower threshold = more signals
        bar_interval: str = "1Min",
        ema_fast: int = 9,
        ema_slow: int = 21,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        atr_period: int = 14,
        stop_loss_atr_mult: float = 1.5,
        take_profit_atr_mult: float = 2.0,
        min_confluence: int = 2,
        orb_bars: int = 15,           # First N bars define the opening range
    ):
        super().__init__(
            name="Scalping",
            description="Aggressive confluence scalping with ORB + trailing stops",
        )
        self.rsi_period = rsi_period
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.volume_multiplier = volume_multiplier
        self.bar_interval = bar_interval
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.atr_period = atr_period
        self.stop_loss_atr_mult = stop_loss_atr_mult
        self.take_profit_atr_mult = take_profit_atr_mult
        self.min_confluence = min_confluence
        self.orb_bars = orb_bars

        self.signal_details: Dict[str, ScalpSignal] = {}

    def get_required_bars(self) -> int:
        return max(self.bb_period, self.macd_slow, self.ema_slow, self.atr_period) + 15

    def get_universe(self) -> List[str]:
        return list(self.DEFAULT_UNIVERSE)

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------

    def generate_signals(self, data: Dict[str, pd.DataFrame]) -> Dict[str, float]:
        signals: Dict[str, float] = {}
        self.signal_details = {}

        logger.info("Generating signals for %d symbols (need >= %d bars)",
                     len(data), self.get_required_bars())

        for symbol, df in data.items():
            if df is None or len(df) < self.get_required_bars():
                logger.debug("%s: skipped — only %d bars (need %d)",
                             symbol, 0 if df is None else len(df),
                             self.get_required_bars())
                continue

            close, high, low, volume = self._extract_ohlcv(df)
            if close is None:
                continue

            price = close.iloc[-1]

            # --- Compute indicators ---
            rsi = _rsi_wilder(close, self.rsi_period)
            bb_upper, bb_mid, bb_lower = _bollinger_bands(close, self.bb_period, self.bb_std)
            vwap_series = _vwap(close, high, low, volume)
            ema_f = _ema(close, self.ema_fast)
            ema_s = _ema(close, self.ema_slow)
            _, _, macd_hist = _macd(close, self.macd_fast, self.macd_slow, self.macd_signal)
            atr_series = _atr(high, low, close, self.atr_period)

            v_rsi = self._safe_last(rsi, 50.0)
            v_bb_upper = self._safe_last(bb_upper, price)
            v_bb_mid = self._safe_last(bb_mid, price)
            v_bb_lower = self._safe_last(bb_lower, price)
            v_vwap = self._safe_last(vwap_series, price)
            v_ema_f = self._safe_last(ema_f, price)
            v_ema_s = self._safe_last(ema_s, price)
            v_macd = self._safe_last(macd_hist, 0.0)
            v_macd_prev = self._safe_at(macd_hist, -2, 0.0)
            v_atr = self._safe_last(atr_series, 0.0)

            avg_vol = volume.rolling(self.bb_period).mean()
            v_vol = volume.iloc[-1] if len(volume) > 0 else 0
            v_avg_vol = self._safe_last(avg_vol, max(v_vol, 1))
            if v_avg_vol <= 0:
                v_avg_vol = max(v_vol, 1)

            if v_atr <= 0 or price <= 0:
                continue
            atr_pct = v_atr / price
            if atr_pct < 0.0003:
                logger.debug("%s: skipped — too quiet (ATR/price=%.4f%%)", symbol, atr_pct * 100)
                continue

            # --- Continuous gradient scoring [-1, +1] ---
            ind: Dict[str, float] = {}

            # RSI: smooth gradient.  50 = neutral, 30 = +1, 70 = -1
            ind["rsi"] = np.clip((50.0 - v_rsi) / 20.0, -1.0, 1.0)

            # Bollinger %B: 0.5 = neutral, 0 = +1 (buy at lower), 1 = -1 (sell at upper)
            pct_b = _percent_b(price, v_bb_upper, v_bb_lower)
            ind["bb"] = np.clip(1.0 - 2.0 * pct_b, -1.0, 1.0)

            # VWAP distance in ATR units: below VWAP = long bias
            vwap_dist = (price - v_vwap) / v_atr
            ind["vwap"] = np.clip(-vwap_dist / 2.0, -1.0, 1.0)

            # EMA trend: proportional to gap between fast and slow, normalized by ATR
            ema_gap = (v_ema_f - v_ema_s) / v_atr
            ind["ema_trend"] = np.clip(ema_gap / 1.5, -1.0, 1.0)

            # MACD: histogram value normalized by ATR + acceleration bonus
            macd_norm = v_macd / v_atr if v_atr > 0 else 0
            macd_accel = 0.0
            if v_macd > 0 and v_macd > v_macd_prev:
                macd_accel = 0.3  # Accelerating bullish
            elif v_macd < 0 and v_macd < v_macd_prev:
                macd_accel = -0.3  # Accelerating bearish
            ind["macd"] = np.clip(macd_norm / 1.5 + macd_accel, -1.0, 1.0)

            # Volume: ratio vs average, directional
            vol_ratio = (v_vol / v_avg_vol) if v_avg_vol > 0 else 1.0
            price_change = close.iloc[-1] - close.iloc[-2] if len(close) >= 2 else 0.0
            if vol_ratio > self.volume_multiplier:
                vol_strength = min((vol_ratio - 1.0) / 2.0, 1.0)
                ind["volume"] = vol_strength if price_change > 0 else -vol_strength
            else:
                ind["volume"] = 0.0

            # Open Range Breakout: compare price to first N bars' high/low
            orb_score = self._calc_orb(close, high, low, v_atr)
            ind["orb"] = orb_score

            # --- Confluence ---
            long_count = sum(1 for v in ind.values() if v > 0.2)
            short_count = sum(1 for v in ind.values() if v < -0.2)

            # Trend agreement
            trend_ok_long = ind["ema_trend"] >= -0.1
            trend_ok_short = ind["ema_trend"] <= 0.1

            # Weighted composite
            weights = {
                "rsi": self.WEIGHT_RSI,
                "bb": self.WEIGHT_BB,
                "vwap": self.WEIGHT_VWAP,
                "ema_trend": self.WEIGHT_EMA_TREND,
                "macd": self.WEIGHT_MACD,
                "volume": self.WEIGHT_VOLUME,
                "orb": self.WEIGHT_ORB,
            }
            raw = sum(ind[k] * weights[k] for k in weights)
            score = 50.0 + raw * 50.0
            score = max(0.0, min(100.0, score))

            # Confluence gate
            raw_score = score
            if score > 50 and (long_count < self.min_confluence or not trend_ok_long):
                score = 50.0
            if score < 50 and (short_count < self.min_confluence or not trend_ok_short):
                score = 50.0

            logger.info(
                "%s: $%.2f RSI=%.0f ATR=%.3f | %s | "
                "raw=%.1f conf=L%d/S%d -> %.1f",
                symbol, price, v_rsi, v_atr,
                " ".join(f"{k}={v:+.2f}" for k, v in ind.items()),
                raw_score, long_count, short_count, score,
            )

            # SL / TP
            if score > 50:
                sl = price - v_atr * self.stop_loss_atr_mult
                tp = price + v_atr * self.take_profit_atr_mult
            elif score < 50:
                sl = price + v_atr * self.stop_loss_atr_mult
                tp = price - v_atr * self.take_profit_atr_mult
            else:
                sl = price
                tp = price

            sym = symbol.upper()
            signals[sym] = score
            self.signal_details[sym] = ScalpSignal(
                score=score,
                confluence=max(long_count, short_count),
                stop_loss=round(sl, 4),
                take_profit=round(tp, 4),
                atr=round(v_atr, 4),
            )

        return signals

    # ------------------------------------------------------------------
    # Open Range Breakout
    # ------------------------------------------------------------------

    def _calc_orb(self, close: pd.Series, high: pd.Series,
                  low: pd.Series, atr: float) -> float:
        """
        Score based on breakout from the opening range (first N bars).
        Returns -1 to +1.  Breakout above ORB high = bullish, below = bearish.
        """
        if len(close) <= self.orb_bars or atr <= 0:
            return 0.0

        orb_high = high.iloc[:self.orb_bars].max()
        orb_low = low.iloc[:self.orb_bars].min()
        price = close.iloc[-1]

        if price > orb_high:
            # Breakout distance in ATR units
            return float(np.clip((price - orb_high) / atr, 0, 1.0))
        elif price < orb_low:
            return float(np.clip((orb_low - price) / atr, 0, 1.0)) * -1.0
        else:
            # Inside the range: slight bias toward direction from midpoint
            orb_mid = (orb_high + orb_low) / 2.0
            return float(np.clip((price - orb_mid) / (atr * 2), -0.3, 0.3))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_ohlcv(df: pd.DataFrame):
        cols = {c.lower(): c for c in df.columns}
        if "close" not in cols:
            return None, None, None, None
        close = df[cols["close"]]
        high = df[cols.get("high", cols["close"])]
        low = df[cols.get("low", cols["close"])]
        vol_col = cols.get("volume")
        volume = df[vol_col] if vol_col else pd.Series(0, index=df.index)
        return close, high, low, volume

    @staticmethod
    def _safe_last(series: pd.Series, default: float) -> float:
        if len(series) == 0:
            return default
        val = series.iloc[-1]
        return default if pd.isna(val) else float(val)

    @staticmethod
    def _safe_at(series: pd.Series, idx: int, default: float) -> float:
        try:
            val = series.iloc[idx]
            return default if pd.isna(val) else float(val)
        except (IndexError, KeyError):
            return default
