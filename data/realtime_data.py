"""
Real-time Data Provider (Alpaca)

Fetches minute bars and quotes from Alpaca Market Data API for HFT strategies.
Uses REST API (suitable for GitHub Actions periodic checks).
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional
import pandas as pd

try:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    ALPACA_DATA_AVAILABLE = True
except ImportError:
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        TimeFrameUnit = None
        ALPACA_DATA_AVAILABLE = True
    except ImportError:
        ALPACA_DATA_AVAILABLE = False

from config.settings import settings

logger = logging.getLogger(__name__)


class RealtimeDataProvider:
    """Provides real-time market data from Alpaca for HFT strategies."""

    def __init__(self):
        self.client = None
        if ALPACA_DATA_AVAILABLE and settings.broker.api_key:
            try:
                self.client = StockHistoricalDataClient(
                    api_key=settings.broker.api_key,
                    secret_key=settings.broker.api_secret,
                )
            except Exception as e:
                logger.warning("Failed to initialize Alpaca data client: %s", e)

    def get_minute_bars(
        self,
        symbols: List[str],
        limit: int = 100,
        timeframe: str = "1Min",
    ) -> Dict[str, pd.DataFrame]:
        """
        Fetch recent minute bars for symbols.

        Returns:
            Dictionary mapping symbols to DataFrames with OHLCV columns.
        """
        if not self.client:
            logger.warning("Alpaca data client not available; returning empty data")
            return {}

        end_time = datetime.now()
        start_time = end_time - timedelta(days=2)

        if TimeFrameUnit is not None:
            tf_map = {
                "1Min": TimeFrame.Minute,
                "5Min": TimeFrame(5, TimeFrameUnit.Minute),
            }
        else:
            tf_map = {"1Min": TimeFrame.Minute, "5Min": TimeFrame.Minute}
        tf = tf_map.get(timeframe, TimeFrame.Minute)

        data: Dict[str, pd.DataFrame] = {}

        # Fetch each symbol individually (batch requests may only return one
        # symbol on Alpaca's free data plan)
        for symbol in symbols:
            sym = symbol.upper()
            try:
                request = StockBarsRequest(
                    symbol_or_symbols=sym,
                    timeframe=tf,
                    start=start_time,
                    end=end_time,
                    limit=limit,
                )
                barset = self.client.get_stock_bars(request)

                if barset is None:
                    logger.info("%s: API returned None", sym)
                    continue

                bar_list = barset.data.get(sym, [])
                if not bar_list:
                    logger.info("%s: no bars returned", sym)
                    continue

                rows = [{
                    "timestamp": b.timestamp,
                    "open": float(b.open),
                    "high": float(b.high),
                    "low": float(b.low),
                    "close": float(b.close),
                    "volume": int(b.volume),
                } for b in bar_list]

                df = pd.DataFrame(rows)
                df.set_index("timestamp", inplace=True)
                df.sort_index(inplace=True)
                data[sym] = df

            except Exception as e:
                logger.error("Error fetching bars for %s: %s", sym, e)

        logger.info("Fetched bars: %s",
                     {s: len(df) for s, df in data.items()} if data else "none for any symbol")
        return data

    def get_latest_quotes(self, symbols: List[str]) -> Dict[str, Dict]:
        """Get latest quotes (uses last bar close as price)."""
        if not self.client:
            return {}

        quotes: Dict[str, Dict] = {}
        bars = self.get_minute_bars(symbols, limit=1)
        for symbol, df in bars.items():
            if len(df) > 0:
                latest_close = df["close"].iloc[-1]
                quotes[symbol] = {
                    "price": Decimal(str(latest_close)),
                    "bid": Decimal(str(latest_close * 0.9999)),
                    "ask": Decimal(str(latest_close * 1.0001)),
                }
        return quotes

    def get_volume_profile(self, symbols: List[str], window: int = 20) -> Dict[str, float]:
        """Get average volume over window for volume spike detection."""
        bars = self.get_minute_bars(symbols, limit=window)
        profiles: Dict[str, float] = {}
        for symbol, df in bars.items():
            if "volume" in df.columns and len(df) > 0:
                profiles[symbol] = float(df["volume"].mean())
        return profiles
