"""목표 비중 계산과 일봉 체결 시뮬레이션 (백테스트와 모의매매가 같은 엔진을 쓴다).

하루의 순서:
  1) 시가: 전일 변동성 돌파 물량 청산 → 전일 종가에 정한 코어 목표 비중으로 리밸런싱
  2) 장중: 변동성 돌파 후보가 '시가 + k x 전일 변동폭'을 넘으면 그 가격에 매수
  3) 종가: 평가, 다음 날 목표 계산
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import regime, strategies
from .data import Prices


@dataclass
class Targets:
    core: pd.DataFrame        # 종가에 결정한 코어 목표 비중 (자산 대비)
    bo_weight: pd.DataFrame   # 변동성 돌파 후보별 자산 대비 배정 비중
    bo_range: pd.DataFrame    # 당일 고가-저가
    label: pd.Series          # 시장 국면
    alloc: pd.DataFrame       # 전략별 자본 배분
    sleeves: dict = field(default_factory=dict)


@dataclass
class Result:
    equity: pd.Series
    trades: pd.DataFrame
    positions: pd.DataFrame   # 마지막 날 보유 현황
    cash: float
    next_orders: pd.DataFrame # 다음 거래일 시가 주문 예정
    next_breakouts: pd.DataFrame


def build_targets(p: Prices, index_close: pd.Series, cfg: dict) -> Targets:
    sc, costs = cfg["strategies"], cfg["costs"]
    index_close = index_close.reindex(p.close.index).ffill()
    sleeves = {name: fn(p, **sc[name]) for name, fn in strategies.CORE.items()}
    sleeves["breakout"] = strategies.breakout(p, **sc["breakout"])
    rng = p.high - p.low

    # 전략별 근사 일수익률 (배분 기울기 계산 전용)
    ret = p.close.pct_change(fill_method=None)
    sleeve_ret = pd.DataFrame({n: (sleeves[n].shift(1) * ret).sum(axis=1) for n in strategies.CORE})
    k = sc["breakout"]["k"]
    trigger = p.open + k * rng.shift(1)
    hit = p.high >= trigger
    rt_cost = 2 * (costs["commission"] + costs["slippage"]) + costs["sell_tax"]
    bo_ret = (p.open.shift(-1) / trigger - 1 - rt_cost).where(hit, 0.0)
    sleeve_ret["breakout"] = (sleeves["breakout"].shift(1) * bo_ret).sum(axis=1)

    rc = cfg["regime"]
    label = regime.classify(index_close, **rc)
    alloc = regime.allocate(label, rc["allocations"], sleeve_ret, rc.get("adaptive"))

    core = sum(sleeves[n].mul(alloc[n], axis=0) for n in strategies.CORE)
    core = core.clip(upper=cfg["risk"]["max_weight"])
    bo_weight = sleeves["breakout"].mul(alloc["breakout"], axis=0)
    return Targets(core, bo_weight, rng, label, alloc, sleeves)


def simulate(p: Prices, t: Targets, cfg: dict, start: str | None = None) -> Result:
    costs, band = cfg["costs"], cfg["risk"]["rebalance_band"]
    comm, tax, slip = costs["commission"], costs["sell_tax"], costs["slippage"]
    k = cfg["strategies"]["breakout"]["k"]
    dates, tickers = p.close.index, list(p.close.columns)
    O, H = p.open.to_numpy(), p.high.to_numpy()
    C = p.close.ffill().to_numpy()            # 평가용 (거래정지일은 직전 종가)
    W, BW, R = t.core.to_numpy(), t.bo_weight.to_numpy(), t.bo_range.to_numpy()
    n = len(tickers)

    cash = float(cfg["capital"])
    core = np.zeros(n, dtype=np.int64)
    bo = np.zeros(n, dtype=np.int64)
    equity = np.full(len(dates), cash)
    trades: list[tuple] = []
    first = max(1, int(dates.searchsorted(pd.Timestamp(start)))) if start else 1

    def sell(i, j, shares, px, sleeve):
        nonlocal cash
        px *= 1 - slip
        fee = shares * px * (comm + tax)
        cash += shares * px - fee
        trades.append((dates[i], tickers[j], "SELL", int(shares), px, sleeve, fee))

    def buy(i, j, shares, px, sleeve):
        nonlocal cash
        px *= 1 + slip
        shares = min(int(shares), int(cash // (px * (1 + comm))))
        if shares <= 0:
            return 0
        fee = shares * px * comm
        cash -= shares * px + fee
        trades.append((dates[i], tickers[j], "BUY", shares, px, sleeve, fee))
        return shares

    for i in range(first, len(dates)):
        o = O[i]
        can = ~np.isnan(o)
        # 1) 시가: 돌파 물량 청산 (거래정지면 재개될 때까지 보유)
        for j in np.flatnonzero((bo > 0) & can):
            sell(i, j, bo[j], o[j], "breakout")
            bo[j] = 0
        mark = np.where(can, o, C[i - 1])
        mark = np.nan_to_num(mark)
        eq = cash + float((core + bo) @ mark)
        # 코어 리밸런싱: 매도 먼저, 그다음 매수
        tgt = np.where(can, np.floor(np.nan_to_num(W[i - 1]) * eq / np.where(can, o, 1.0)), core).astype(np.int64)
        diff = tgt - core
        small = (np.abs(diff) * mark < band * eq) & (tgt > 0)
        diff[small] = 0
        for j in np.flatnonzero(diff < 0):
            sell(i, j, -diff[j], o[j], "core")
            core[j] += diff[j]
        for j in sorted(np.flatnonzero(diff > 0), key=lambda j: -diff[j] * o[j]):
            core[j] += buy(i, j, diff[j], o[j], "core")
        # 2) 장중: 변동성 돌파
        trig = o + k * R[i - 1]
        fire = can & (BW[i - 1] > 0) & (R[i - 1] > 0) & (H[i] >= trig)
        for j in np.flatnonzero(fire):
            bo[j] += buy(i, j, BW[i - 1, j] * eq // trig[j], trig[j], "breakout")
        # 3) 종가 평가
        equity[i] = cash + float((core + bo) @ np.nan_to_num(C[i]))

    eq_s = pd.Series(equity, index=dates, name="equity")
    if start:
        eq_s = eq_s.iloc[first - 1:]
    tr = pd.DataFrame(trades, columns=["date", "ticker", "side", "shares", "price", "sleeve", "fee"])
    tr["date"] = pd.to_datetime(tr["date"])  # 거래가 한 건도 없을 때도 날짜 형식 유지

    last = np.nan_to_num(C[-1])
    held = np.flatnonzero((core + bo) > 0)
    positions = pd.DataFrame({"ticker": [tickers[j] for j in held], "core": core[held], "breakout": bo[held],
                              "close": last[held], "value": (core + bo)[held] * last[held]})
    # 다음 거래일 주문 예정 (종가 기준 추정 수량; 실제 수량은 시가로 다시 계산됨)
    eq_now = equity[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        tgt = np.where(last > 0, np.floor(np.nan_to_num(W[-1]) * eq_now / last), 0).astype(np.int64)
    diff = tgt - core
    diff[(np.abs(diff) * last < band * eq_now) & (tgt > 0)] = 0
    rows = [(tickers[j], "BUY" if diff[j] > 0 else "SELL", abs(int(diff[j])), "core", last[j])
            for j in np.flatnonzero(diff)]
    rows += [(tickers[j], "SELL", int(bo[j]), "breakout", last[j]) for j in np.flatnonzero(bo)]
    next_orders = pd.DataFrame(rows, columns=["ticker", "side", "shares", "sleeve", "close"])
    cand = np.flatnonzero((BW[-1] > 0) & (R[-1] > 0))
    next_bo = pd.DataFrame({"ticker": [tickers[j] for j in cand], "trigger_above_open": k * R[-1, cand],
                            "budget": BW[-1, cand] * eq_now})
    return Result(eq_s, tr, positions, cash, next_orders, next_bo)
