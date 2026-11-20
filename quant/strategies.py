"""4개 전략. 각 함수는 '그날 종가에 결정한' 전략 내 목표 비중(날짜 x 종목)을 돌려준다.

모든 신호는 당일 종가까지의 정보만 쓰고, 체결은 엔진이 다음 거래일에 처리한다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import Prices


def rsi(close: pd.DataFrame, period: int) -> pd.DataFrame:
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    return 100 - 100 / (1 + up / down.replace(0, np.nan))


def month_end_mask(index: pd.DatetimeIndex) -> np.ndarray:
    """월의 마지막 거래일 여부. 마지막 행은 다음 영업일의 달이 바뀌는지로 판단."""
    months = index.month.to_numpy()
    mask = np.zeros(len(index), dtype=bool)
    mask[:-1] = months[:-1] != months[1:]
    if len(index):
        mask[-1] = (index[-1] + pd.offsets.BDay(1)).month != index[-1].month
    return mask


def _top_n_monthly(score: pd.DataFrame, top_n: int) -> pd.DataFrame:
    """월말마다 점수 상위 top_n 종목을 1/top_n 씩. 다음 월말까지 유지."""
    rebal = month_end_mask(score.index)
    ranks = score.rank(axis=1, ascending=False, method="first")
    picked = (ranks <= top_n).astype(float) / top_n
    picked[~rebal] = np.nan
    return picked.ffill().fillna(0.0)


def momentum(p: Prices, top_n=5, lookback=252, skip=21, trend_ma=120) -> pd.DataFrame:
    """추세추종: 최근 1개월을 뺀 12개월 수익률 상위 + 장기 이평 위에 있는 종목."""
    mom = p.close.shift(skip) / p.close.shift(lookback) - 1
    ok = (p.close > p.close.rolling(trend_ma).mean()) & (mom > 0)
    return _top_n_monthly(mom.where(ok), top_n)


def factor(p: Prices, top_n=8, mom_lookback=126, vol_lookback=60, w_mom=0.4, w_lowvol=0.4,
           w_reversal=0.2) -> pd.DataFrame:
    """팩터 포트폴리오: 중기 모멘텀 + 저변동성 + 단기 반전의 순위 합성 (가격 기반 팩터)."""
    ret = p.close.pct_change(fill_method=None)
    mom = p.close.shift(21) / p.close.shift(mom_lookback) - 1
    vol = ret.rolling(vol_lookback).std()
    rev = -(p.close / p.close.shift(21) - 1)
    valid = mom.notna() & vol.notna() & rev.notna()
    rk = lambda x: x.where(valid).rank(axis=1, pct=True)
    score = w_mom * rk(mom) + w_lowvol * rk(-vol) + w_reversal * rk(rev)
    return _top_n_monthly(score, top_n)


def meanrev(p: Prices, max_positions=5, rsi_period=2, rsi_entry=10, trend_ma=200, exit_ma=5,
            max_hold=10) -> pd.DataFrame:
    """평균회귀: 상승 추세 종목의 단기 과매도(RSI) 매수, 단기 이평 회복 또는 기간 만료 시 청산."""
    r = rsi(p.close, rsi_period)
    entry = ((r < rsi_entry) & (p.close > p.close.rolling(trend_ma).mean())).to_numpy()
    exit_ = (p.close > p.close.rolling(exit_ma).mean()).to_numpy()
    r_np = r.to_numpy()
    n_days, n_tk = entry.shape
    w = np.zeros((n_days, n_tk))
    held: dict[int, int] = {}  # 종목 위치 -> 보유 일수
    for i in range(n_days):
        for j in list(held):
            held[j] += 1
            if exit_[i, j] or held[j] >= max_hold:
                del held[j]
        cands = [j for j in np.flatnonzero(entry[i]) if j not in held]
        for j in sorted(cands, key=lambda j: r_np[i, j])[: max_positions - len(held)]:
            held[j] = 0
        w[i, list(held)] = 1 / max_positions
    return pd.DataFrame(w, index=p.close.index, columns=p.close.columns)


def breakout(p: Prices, top_n=5, k=0.5, trend_ma=20, noise_lookback=20) -> pd.DataFrame:
    """변동성 돌파 후보: 단기 이평 위 + 노이즈(꼬리 비율)가 낮은 종목 top_n.

    실제 매수는 엔진이 다음 날 '시가 + k x 전일 변동폭' 돌파 시 체결하고 그다음 날 시가에 청산한다.
    """
    rng = (p.high - p.low).replace(0, np.nan)
    noise = (1 - (p.open - p.close).abs() / rng).rolling(noise_lookback).mean()
    ok = p.close > p.close.rolling(trend_ma).mean()
    ranks = noise.where(ok).rank(axis=1, ascending=True, method="first")
    return (ranks <= top_n).astype(float) / top_n


CORE = {"momentum": momentum, "meanrev": meanrev, "factor": factor}
ALL = [*CORE, "breakout"]
