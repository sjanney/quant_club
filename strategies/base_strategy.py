"""
Base Strategy

Abstract base class for all trading strategies.
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional
import pandas as pd


class BaseStrategy(ABC):
    """Base class for all trading strategies."""
    
    def __init__(self, name: str, description: str = ""):
        """Initialize strategy."""
        self.name = name
        self.description = description
    
    @abstractmethod
    def generate_signals(self, data: Dict[str, pd.DataFrame]) -> Dict[str, float]:
        """
        Generate trading signals for symbols.
        
        Args:
            data: Dictionary mapping symbols to DataFrames with OHLCV data
        
        Returns:
            Dictionary mapping symbols to signal scores (higher = more bullish)
        """
        pass
    
    @abstractmethod
    def get_required_bars(self) -> int:
        """Get minimum number of bars required for the strategy."""
        pass
    
    def validate_data(self, data: Dict[str, pd.DataFrame]) -> bool:
        """Validate that data meets strategy requirements."""
        required_bars = self.get_required_bars()
        for symbol, df in data.items():
            if df is None or len(df) < required_bars:
                return False
        return True
    
    def get_name(self) -> str:
        """Get strategy name."""
        return self.name
    
    def describe(self) -> str:
        """Get strategy description."""
        return self.description
