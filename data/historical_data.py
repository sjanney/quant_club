"""
Historical Data Provider

Manages historical market data with caching and storage.
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd
import yfinance as yf

from config.settings import settings

logger = logging.getLogger(__name__)


class HistoricalDataProvider:
    """Provides historical market data."""
    
    def __init__(self):
        """Initialize historical data provider."""
        self.data_dir = settings.data.data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
    
    def get_historical_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = "1d",
    ) -> Optional[pd.DataFrame]:
        """Get historical data for a symbol."""
        symbol = symbol.upper()
        
        # Check local cache first
        cache_file = self.data_dir / f"{symbol}_{interval}.csv"
        if cache_file.exists():
            try:
                df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
                df = df[(df.index >= start_date) & (df.index <= end_date)]
                if not df.empty:
                    return df
            except Exception as e:
                logger.warning(f"Error reading cache for {symbol}: {e}")
        
        # Fetch from API
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(start=start_date, end=end_date, interval=interval)
            
            if df.empty:
                return None
            
            # Standardize columns
            df.columns = [col.lower().replace(" ", "_") for col in df.columns]
            
            # Cache the data
            try:
                df.to_csv(cache_file)
            except Exception as e:
                logger.warning(f"Error caching data for {symbol}: {e}")
            
            return df
        
        except Exception as e:
            logger.error(f"Error fetching historical data for {symbol}: {e}")
            return None
    
    def get_universe_historical(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime,
        interval: str = "1d",
    ) -> Dict[str, pd.DataFrame]:
        """Get historical data for multiple symbols."""
        data = {}
        for symbol in symbols:
            df = self.get_historical_data(symbol, start_date, end_date, interval)
            if df is not None:
                data[symbol.upper()] = df
        return data
    
    def update_cache(self, symbol: str, days: int = 30) -> bool:
        """Update cache for a symbol."""
        symbol = symbol.upper()
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        df = self.get_historical_data(symbol, start_date, end_date)
        return df is not None and not df.empty
