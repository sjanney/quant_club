"""
Momentum Strategy

Simple momentum-based strategy using moving averages.
"""

from typing import Dict
import pandas as pd
import numpy as np

from strategies.base_strategy import BaseStrategy


class MomentumStrategy(BaseStrategy):
    """Momentum strategy using moving average crossovers."""
    
    def __init__(self, fast_period: int = 20, slow_period: int = 50):
        """Initialize momentum strategy."""
        super().__init__(
            name="Momentum",
            description=f"Moving average crossover ({fast_period}/{slow_period})"
        )
        self.fast_period = fast_period
        self.slow_period = slow_period
    
    def get_required_bars(self) -> int:
        """Get minimum bars required."""
        return self.slow_period + 10
    
    def generate_signals(self, data: Dict[str, pd.DataFrame]) -> Dict[str, float]:
        """Generate momentum signals."""
        signals = {}
        
        for symbol, df in data.items():
            if df is None or len(df) < self.get_required_bars():
                continue
            
            try:
                close = df["close"] if "close" in df.columns else df["Close"]
                
                # Calculate moving averages
                fast_ma = close.rolling(window=self.fast_period).mean()
                slow_ma = close.rolling(window=self.slow_period).mean()
                
                # Current values
                current_fast = fast_ma.iloc[-1]
                current_slow = slow_ma.iloc[-1]
                prev_fast = fast_ma.iloc[-2]
                prev_slow = slow_ma.iloc[-2]
                
                # Signal: bullish if fast MA crosses above slow MA
                if current_fast > current_slow and prev_fast <= prev_slow:
                    # Golden cross
                    signal = 1.0
                elif current_fast > current_slow:
                    # Already bullish
                    signal = 0.5
                elif current_fast < current_slow and prev_fast >= prev_slow:
                    # Death cross
                    signal = -1.0
                else:
                    # Already bearish
                    signal = -0.5
                
                # Normalize to 0-100 scale
                signals[symbol] = (signal + 1.0) * 50.0
            
            except Exception as e:
                continue
        
        return signals
