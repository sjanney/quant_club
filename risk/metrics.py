"""
Risk Metrics

Calculates various risk and performance metrics.
"""

import numpy as np
import pandas as pd
from typing import Optional


def calculate_var(returns: pd.Series, confidence: float = 0.95) -> float:
    """Calculate Value at Risk (VaR)."""
    if returns.empty:
        return 0.0
    return float(returns.quantile(1 - confidence))


def calculate_cvar(returns: pd.Series, confidence: float = 0.95) -> float:
    """Calculate Conditional VaR (Expected Shortfall)."""
    if returns.empty:
        return 0.0
    var = calculate_var(returns, confidence)
    return float(returns[returns <= var].mean())


def calculate_sharpe(returns: pd.Series, risk_free_rate: float = 0.0) -> float:
    """Calculate Sharpe ratio."""
    if returns.empty or returns.std() == 0:
        return 0.0
    excess_returns = returns.mean() - risk_free_rate / 252  # Daily risk-free rate
    return float(excess_returns / returns.std() * np.sqrt(252))


def calculate_sortino(returns: pd.Series, risk_free_rate: float = 0.0) -> float:
    """Calculate Sortino ratio."""
    if returns.empty:
        return 0.0
    excess_returns = returns.mean() - risk_free_rate / 252
    downside_returns = returns[returns < 0]
    if downside_returns.empty or downside_returns.std() == 0:
        return 0.0
    return float(excess_returns / downside_returns.std() * np.sqrt(252))


def calculate_max_drawdown(equity_curve: pd.Series) -> float:
    """Calculate maximum drawdown."""
    if equity_curve.empty:
        return 0.0
    
    running_max = equity_curve.expanding().max()
    drawdown = (equity_curve - running_max) / running_max
    return float(drawdown.min())


def calculate_calmar_ratio(returns: pd.Series) -> float:
    """Calculate Calmar ratio (annual return / max drawdown)."""
    if returns.empty:
        return 0.0
    
    equity_curve = (1 + returns).cumprod()
    max_dd = abs(calculate_max_drawdown(equity_curve))
    
    if max_dd == 0:
        return 0.0
    
    annual_return = (equity_curve.iloc[-1] ** (252 / len(returns))) - 1
    return float(annual_return / max_dd)


def calculate_win_rate(returns: pd.Series) -> float:
    """Calculate win rate (percentage of positive returns)."""
    if returns.empty:
        return 0.0
    return float((returns > 0).sum() / len(returns))


def calculate_profit_factor(returns: pd.Series) -> float:
    """Calculate profit factor (gross profit / gross loss)."""
    if returns.empty:
        return 0.0
    
    gross_profit = returns[returns > 0].sum()
    gross_loss = abs(returns[returns < 0].sum())
    
    if gross_loss == 0:
        return float('inf') if gross_profit > 0 else 0.0
    
    return float(gross_profit / gross_loss)


def calculate_beta(portfolio_returns: pd.Series, benchmark_returns: pd.Series) -> float:
    """Calculate beta relative to benchmark."""
    if portfolio_returns.empty or benchmark_returns.empty:
        return 0.0
    
    # Align indices
    aligned = pd.DataFrame({
        "portfolio": portfolio_returns,
        "benchmark": benchmark_returns,
    }).dropna()
    
    if len(aligned) < 2 or aligned["benchmark"].std() == 0:
        return 0.0
    
    covariance = aligned["portfolio"].cov(aligned["benchmark"])
    variance = aligned["benchmark"].var()
    
    return float(covariance / variance)
