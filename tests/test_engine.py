"""네트워크 없이 합성 시세로 엔진의 핵심 성질을 검증한다."""
import copy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from quant import strategies
from quant.data import Prices
from quant.engine import build_targets, simulate

CFG = yaml.safe_load((Path(__file__).parent.parent / "config.yaml").read_text(encoding="utf-8"))


def make_prices(n_days=700, n_tk=12, seed=0) -> tuple[Prices, pd.Series]:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n_days)
    cols = [f"T{i:02d}" for i in range(n_tk)]
    ret = rng.normal(0.0005, 0.02, (n_days, n_tk))
    close = 50000 * np.exp(np.cumsum(ret, axis=0))
    open_ = np.vstack([close[0], close[:-1]]) * (1 + rng.normal(0, 0.005, (n_days, n_tk)))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.01, (n_days, n_tk))))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.01, (n_days, n_tk))))
    df = lambda a: pd.DataFrame(a, index=idx, columns=cols)
    p = Prices(df(open_), df(high), df(low), df(close), df(np.full((n_days, n_tk), 1e6)))
    return p, p.close.mean(axis=1)


@pytest.fixture(scope="module")
def data():
    return make_prices()


def test_no_lookahead(data):
    """미래 데이터를 잘라내도 과거의 목표 비중은 달라지지 않아야 한다."""
    p, index = data
    cut = p.close.index[600]
    full = build_targets(p, index, CFG)
    part = build_targets(p.loc(end=cut), index.loc[:cut], CFG)
    # 마지막 날은 '월말 여부' 추정이 달라질 수 있으므로 그 전날까지 비교
    upto = p.close.index[599]
    pd.testing.assert_frame_equal(full.core.loc[:upto], part.core.loc[:upto])
    pd.testing.assert_frame_equal(full.bo_weight.loc[:upto], part.bo_weight.loc[:upto])


def test_simulation_accounting(data):
    p, index = data
    t = build_targets(p, index, CFG)
    res = simulate(p, t, CFG)
    assert len(res.trades) > 0
    assert res.cash >= 0
    assert (res.equity > 0).all()
    # 마지막 평가금액 = 현금 + 보유 평가액
    assert res.equity.iloc[-1] == pytest.approx(res.cash + res.positions["value"].sum())
    # 현금 흐름 재구성: 초기자본 - 매수 + 매도 - 비용 = 남은 현금
    tr = res.trades
    signed = np.where(tr["side"] == "BUY", -1, 1) * tr["shares"] * tr["price"]
    assert CFG["capital"] + signed.sum() - tr["fee"].sum() == pytest.approx(res.cash)


def test_costs_reduce_returns(data):
    p, index = data
    free = copy.deepcopy(CFG)
    free["costs"] = {"commission": 0.0, "sell_tax": 0.0, "slippage": 0.0}
    with_cost = simulate(p, build_targets(p, index, CFG), CFG).equity.iloc[-1]
    no_cost = simulate(p, build_targets(p, index, free), free).equity.iloc[-1]
    assert no_cost > with_cost


def test_weights_within_limits(data):
    p, index = data
    t = build_targets(p, index, CFG)
    assert (t.core.max(axis=1) <= CFG["risk"]["max_weight"] + 1e-12).all()
    assert ((t.core.sum(axis=1) + t.bo_weight.sum(axis=1)) <= 1 + 1e-9).all()
    assert (t.alloc.sum(axis=1) <= 1 + 1e-9).all()


def test_halted_stock_is_not_traded(data):
    p, index = data
    p = copy.deepcopy(p)
    halt = p.close.index[400:420]
    for f in (p.open, p.high, p.low):
        f.loc[halt, "T00"] = np.nan
    res = simulate(p, build_targets(p, index, CFG), CFG)
    tr = res.trades
    assert tr[(tr["ticker"] == "T00") & tr["date"].isin(halt)].empty


def test_month_end_mask():
    idx = pd.to_datetime(["2024-01-30", "2024-01-31", "2024-02-01", "2024-02-29"])
    assert strategies.month_end_mask(idx).tolist() == [False, True, False, True]


def test_ledger_matches_equity(data, tmp_path):
    """실현손익 + 보유분 평가손익이 자산 증감과 일치하고, Word 리포트가 만들어진다."""
    from quant.report import ledger, write_docx

    p, index = data
    t = build_targets(p, index, CFG)
    res = simulate(p, t, CFG)
    held, closed = ledger(res.trades)
    close = p.close.ffill().iloc[-1]
    unrealized = sum(h["shares"] * close[tk] - h["cost"] for (tk, _), h in held.items())
    assert closed["pnl"].sum() + unrealized == pytest.approx(res.equity.iloc[-1] - CFG["capital"])
    assert sum(h["shares"] for h in held.values()) == res.positions[["core", "breakout"]].to_numpy().sum()

    cfg = {**CFG, "universe": {c: c for c in p.close.columns}}
    path = write_docx(res, t, cfg, {"start": "2020-01-01", "capital": CFG["capital"]}, tmp_path, p)
    assert path.stat().st_size > 5000
