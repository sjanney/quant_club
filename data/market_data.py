"""
Market Data Provider

Fetches real-time and delayed market data from various sources.
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional
import pandas as pd
import yfinance as yf

try:
    from cachetools import TTLCache
except ImportError:
    # Fallback if cachetools not available
    class TTLCache(dict):
        def __init__(self, maxsize=100, ttl=3600):
            super().__init__()
            self.maxsize = maxsize
            self.ttl = ttl

from config.settings import settings

logger = logging.getLogger(__name__)


class MarketDataProvider:
    """Provides market data from various sources."""
    
    def __init__(self):
        """Initialize market data provider."""
        self.cache = TTLCache(maxsize=1000, ttl=settings.data.cache_ttl_minutes * 60)
        self.data_source = settings.data.primary_data_source
    
    def get_current_price(self, symbol: str) -> Optional[Decimal]:
        """Get current price for a symbol."""
        symbol = symbol.upper()
        
        # Check cache
        cache_key = f"price_{symbol}"
        if cache_key in self.cache:
            return Decimal(str(self.cache[cache_key]))
        
        try:
            ticker = yf.Ticker(symbol)
            data = ticker.history(period="1d", interval="1m")
            
            if data.empty:
                return None
            
            price = Decimal(str(data["Close"].iloc[-1]))
            self.cache[cache_key] = float(price)
            return price
        
        except Exception as e:
            logger.error(f"Error fetching price for {symbol}: {e}")
            return None
    
    def get_current_prices(self, symbols: List[str]) -> Dict[str, Decimal]:
        """Get current prices for multiple symbols."""
        prices = {}
        for symbol in symbols:
            price = self.get_current_price(symbol)
            if price:
                prices[symbol.upper()] = price
        return prices
    
    def get_quote(self, symbol: str) -> Optional[Dict]:
        """Get full quote (bid, ask, volume, etc.) for a symbol."""
        symbol = symbol.upper()
        
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            quote = {
                "symbol": symbol,
                "price": Decimal(str(info.get("currentPrice", 0))),
                "bid": Decimal(str(info.get("bid", 0))),
                "ask": Decimal(str(info.get("ask", 0))),
                "volume": info.get("volume", 0),
                "market_cap": info.get("marketCap", 0),
                "pe_ratio": info.get("trailingPE", None),
                "dividend_yield": info.get("dividendYield", None),
            }
            
            return quote
        
        except Exception as e:
            logger.error(f"Error fetching quote for {symbol}: {e}")
            return None
    
    def get_bars(
        self,
        symbol: str,
        timeframe: str = "1d",
        limit: int = 100,
        end_time: Optional[datetime] = None,
    ) -> Optional[pd.DataFrame]:
        """Get historical bars for a symbol."""
        symbol = symbol.upper()
        cache_key = f"bars_{symbol}_{timeframe}_{limit}"
        
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        try:
            ticker = yf.Ticker(symbol)
            
            # Map timeframe
            period_map = {
                "1m": ("1d", "1m"),
                "5m": ("5d", "5m"),
                "15m": ("1mo", "15m"),
                "1h": ("3mo", "1h"),
                "1d": ("1y", "1d"),
            }
            
            period, interval = period_map.get(timeframe, ("1y", "1d"))
            data = ticker.history(period=period, interval=interval)
            
            if data.empty:
                return None
            
            # Limit rows
            if len(data) > limit:
                data = data.tail(limit)
            
            # Standardize column names
            data.columns = [col.lower().replace(" ", "_") for col in data.columns]
            
            self.cache[cache_key] = data
            return data
        
        except Exception as e:
            logger.error(f"Error fetching bars for {symbol}: {e}")
            return None
    
    def get_universe_data(self, symbols: List[str]) -> Dict[str, pd.DataFrame]:
        """Get data for multiple symbols."""
        data = {}
        for symbol in symbols:
            df = self.get_bars(symbol, timeframe="1d", limit=252)
            if df is not None:
                data[symbol.upper()] = df
        return data
    
    def is_market_open(self) -> bool:
        """Check if market is currently open."""
        now = datetime.now()
        # Simple check - can be enhanced with actual market calendar
        if now.weekday() >= 5:  # Saturday or Sunday
            return False
        
        # Check time (ET)
        # This is simplified - should use proper timezone handling
        hour = now.hour
        return 9 <= hour < 16
    
    def get_market_status(self) -> Dict:
        """Get current market status."""
        return {
            "is_open": self.is_market_open(),
            "timestamp": datetime.now().isoformat(),
        }
