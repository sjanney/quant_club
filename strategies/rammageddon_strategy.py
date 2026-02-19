"""
RAMmageddon Trading Strategy

Implements the DRAM shortage thesis from research/RAMmageddon_Trading_Strategy.ipynb:
- Strategy 1: Long memory manufacturers (MU) — RSI + 200MA
- Strategy 2: Short OEMs (DELL, HPQ)
- Strategy 3: Pairs trade (Long MU / Short DELL) via z-score of MU/DELL ratio
- Strategy 4: Apple as safe haven (long AAPL)

Returns signal scores 0–100 per symbol (higher = more bullish / long bias).
"""

from typing import Dict, Optional, Tuple
import pandas as pd
import numpy as np

from strategies.base_strategy import BaseStrategy


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """RSI(period)."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _zscore(series: pd.Series, window: int) -> pd.Series:
    """Rolling z-score."""
    ma = series.rolling(window).mean()
    std = series.rolling(window).std()
    return (series - ma) / std.replace(0, np.nan)


class RAMmageddonStrategy(BaseStrategy):
    """
    RAMmageddon: Long memory fabs (MU), short OEMs (DELL, HPQ), pairs MU/DELL, long AAPL.
    """

    # Universe from research notebook
    DEFAULT_UNIVERSE = ["MU", "AAPL", "SMH", "DELL", "HPQ"]

    def __init__(
        self,
        rsi_period: int = 14,
        ma_fast: int = 50,
        ma_slow: int = 200,
        pairs_window: int = 60,
        pairs_long_z: float = -1.0,
        pairs_exit_z: float = 2.0,
    ):
        super().__init__(
            name="RAMmageddon",
            description="DRAM shortage: long MU, short OEMs, pairs MU/DELL, long AAPL",
        )
        self.rsi_period = rsi_period
        self.ma_fast = ma_fast
        self.ma_slow = ma_slow
        self.pairs_window = pairs_window
        self.pairs_long_z = pairs_long_z
        self.pairs_exit_z = pairs_exit_z

    def get_required_bars(self) -> int:
        return max(self.ma_slow, self.pairs_window) + 20

    def generate_signals(self, data: Dict[str, pd.DataFrame]) -> Dict[str, float]:
        """
        Returns symbol -> score 0–100 (higher = more long bias).
        Scores < 50 indicate short bias for symbols we can short (DELL, HPQ).
        """
        signals: Dict[str, float] = {}

        # Need at least MU and DELL for pairs; others optional
        if "MU" not in data or "DELL" not in data:
            return signals

        # --- Pairs trade: MU/DELL ratio z-score ---
        mu_df = data["MU"]
        dell_df = data["DELL"]
        # Align by index
        common_idx = mu_df.index.intersection(dell_df.index)
        if len(common_idx) < self.pairs_window:
            return signals

        close_mu = mu_df.loc[common_idx, "close"] if "close" in mu_df.columns else mu_df.loc[common_idx, "Close"]
        close_dell = dell_df.loc[common_idx, "close"] if "close" in dell_df.columns else dell_df.loc[common_idx, "Close"]
        ratio = close_mu / close_dell
        z_score = _zscore(ratio, self.pairs_window)
        latest_z = z_score.iloc[-1] if not pd.isna(z_score.iloc[-1]) else 0.0

        # --- Strategy 1: Long MU (RSI + 200 MA) ---
        mu_price = close_mu.iloc[-1]
        mu_series = close_mu
        rsi = _rsi(mu_series, self.rsi_period)
        ma200 = mu_series.rolling(self.ma_slow).mean()
        ma50 = mu_series.rolling(self.ma_fast).mean()

        latest_rsi = rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50.0
        above_200 = float(mu_price > ma200.iloc[-1]) if not pd.isna(ma200.iloc[-1]) else 0
        ma_bull = float(ma50.iloc[-1] > ma200.iloc[-1]) if not pd.isna(ma50.iloc[-1]) and not pd.isna(ma200.iloc[-1]) else 0

        # Long MU score: higher when RSI oversold (buy dip) + above 200 MA, or when pairs says long MU (z < -1)
        mu_score = 50.0
        if above_200:
            mu_score += 15.0
        if latest_rsi < 35:  # oversold bounce
            mu_score += 15.0
        if ma_bull:
            mu_score += 10.0
        if latest_z < self.pairs_long_z:  # pairs: long MU
            mu_score += 20.0
        if latest_z > self.pairs_exit_z:  # pairs: exit long MU
            mu_score -= 25.0
        signals["MU"] = max(0.0, min(100.0, mu_score))

        # --- Strategy 2 & 3: DELL (short when pairs or OEM thesis) ---
        dell_score = 50.0
        if latest_z < self.pairs_long_z:  # pairs: short DELL
            dell_score -= 25.0
        if latest_z > self.pairs_exit_z:
            dell_score += 15.0
        # OEM short thesis: bias toward short
        dell_score -= 10.0
        signals["DELL"] = max(0.0, min(100.0, dell_score))

        # --- HPQ: short OEM thesis ---
        if "HPQ" in data:
            hpq_df = data["HPQ"]
            if len(hpq_df) >= self.get_required_bars():
                signals["HPQ"] = max(0.0, min(100.0, 50.0 - 15.0))  # bias short

        # --- Strategy 4: AAPL safe haven (moderate long) ---
        if "AAPL" in data:
            aapl_df = data["AAPL"]
            if len(aapl_df) >= self.get_required_bars():
                signals["AAPL"] = 62.0  # moderate long

        # --- SMH: sector long (optional) ---
        if "SMH" in data:
            smh_df = data["SMH"]
            if len(smh_df) >= self.get_required_bars():
                signals["SMH"] = 58.0

        return signals

    def get_universe(self) -> list:
        return list(self.DEFAULT_UNIVERSE)
