"""
Backtest Results

Analyzes and visualizes backtest results.
"""

import pandas as pd
import matplotlib.pyplot as plt
from typing import Dict, Optional


class BacktestResults:
    """Manages backtest results and visualization."""
    
    def __init__(self, results: Dict):
        """Initialize with backtest results."""
        self.results = results
        self.equity_curve = results.get("equity_curve", pd.Series())
        self.returns = results.get("returns", pd.Series())
    
    def generate_report(self) -> str:
        """Generate text report."""
        if self.equity_curve.empty:
            return "No results to report"
        
        report = []
        report.append("=" * 60)
        report.append("BACKTEST RESULTS")
        report.append("=" * 60)
        report.append("")
        report.append(f"Final Equity: ${self.results.get('final_equity', 0):,.2f}")
        report.append(f"Total Return: {self.results.get('total_return', 0):.2f}%")
        report.append(f"Max Drawdown: {self.results.get('max_drawdown', 0):.2f}%")
        report.append(f"Number of Trades: {self.results.get('num_trades', 0)}")
        report.append("")
        
        if not self.returns.empty:
            report.append(f"Sharpe Ratio: {self.returns.mean() / self.returns.std() * (252 ** 0.5):.2f}")
            report.append(f"Win Rate: {(self.returns > 0).sum() / len(self.returns) * 100:.1f}%")
        
        report.append("=" * 60)
        
        return "\n".join(report)
    
    def plot_equity_curve(self, save_path: Optional[str] = None) -> None:
        """Plot equity curve."""
        if self.equity_curve.empty:
            return
        
        plt.figure(figsize=(12, 6))
        plt.plot(self.equity_curve.index, self.equity_curve.values)
        plt.title("Equity Curve")
        plt.xlabel("Date")
        plt.ylabel("Portfolio Value ($)")
        plt.grid(True)
        
        if save_path:
            plt.savefig(save_path)
        else:
            plt.show()
    
    def plot_returns(self, save_path: Optional[str] = None) -> None:
        """Plot returns distribution."""
        if self.returns.empty:
            return
        
        plt.figure(figsize=(10, 6))
        plt.hist(self.returns.values, bins=50, edgecolor="black")
        plt.title("Returns Distribution")
        plt.xlabel("Daily Return")
        plt.ylabel("Frequency")
        plt.grid(True)
        
        if save_path:
            plt.savefig(save_path)
        else:
            plt.show()
