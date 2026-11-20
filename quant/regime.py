"""시장 국면 판단과 전략 간 동적 배분."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .strategies import ALL


def classify(index_close: pd.Series, trend_fast=50, trend_slow=200, vol_lookback=20, vol_window=252,
             vol_pct=0.8, **_) -> pd.Series:
    """bull/neutral/bear x calm/highvol. 그날 종가까지의 정보만 사용."""
    fast = index_close.rolling(trend_fast).mean()
    slow = index_close.rolling(trend_slow).mean()
    vol = index_close.pct_change(fill_method=None).rolling(vol_lookback).std()
    highvol = vol > vol.rolling(vol_window, min_periods=vol_window // 2).quantile(vol_pct)

    trend = pd.Series("neutral", index=index_close.index)
    trend[(index_close > slow) & (fast > slow)] = "bull"
    trend[index_close < slow] = "bear"
    label = trend.where(trend == "neutral", trend + np.where(highvol, "_highvol", "_calm"))
    label[slow.isna()] = "neutral"
    return label


def allocate(label: pd.Series, allocations: dict, sleeve_returns: pd.DataFrame | None = None,
             adaptive: dict | None = None) -> pd.DataFrame:
    """국면별 기본 배분에 최근 성과 기울기를 더한 전략별 자본 비중 (날짜 x 전략).

    총 노출(합계)은 국면이 정하고, 전략 간 비율만 최근 성과에 따라 움직인다.
    """
    base = pd.DataFrame([{s: allocations[r].get(s, 0.0) for s in ALL} for r in label], index=label.index)
    if not (adaptive and adaptive.get("enabled") and sleeve_returns is not None):
        return base
    lb = adaptive["lookback"]
    roll = sleeve_returns.rolling(lb, min_periods=lb // 2)
    sharpe = (roll.mean() / roll.std().replace(0, np.nan)) * np.sqrt(252)
    mult = (1 + adaptive["strength"] * sharpe).clip(adaptive["min_mult"], adaptive["max_mult"])
    # 변동성 돌파 수익은 다음 날 시가에 확정되므로 2일 늦춰 미래 정보 유입을 막는다
    mult = mult.shift(2).fillna(1.0)
    tilted = base * mult[ALL]
    scale = (base.sum(axis=1) / tilted.sum(axis=1).replace(0, np.nan)).fillna(0.0)
    return tilted.mul(scale, axis=0)
