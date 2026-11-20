"""성과 지표."""
from __future__ import annotations

import numpy as np
import pandas as pd


def stats(equity: pd.Series) -> dict:
    ret = equity.pct_change(fill_method=None).dropna()
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    total = equity.iloc[-1] / equity.iloc[0] - 1
    dd = equity / equity.cummax() - 1
    monthly = equity.resample("ME").last().pct_change(fill_method=None).dropna()
    vol = ret.std() * np.sqrt(252)
    return {
        "총수익률": total,
        "연환산수익률(CAGR)": (1 + total) ** (1 / years) - 1 if years > 0 else float("nan"),
        "연변동성": vol,
        "샤프지수": ret.mean() * 252 / vol if vol > 0 else float("nan"),
        "최대낙폭(MDD)": dd.min(),
        "월간 승률": (monthly > 0).mean() if len(monthly) else float("nan"),
    }


def yearly_returns(equity: pd.Series) -> pd.Series:
    y = equity.resample("YE").last()
    first = pd.Series([equity.iloc[0]], index=[equity.index[0]])
    out = pd.concat([first, y]).pct_change(fill_method=None).dropna()
    out.index = out.index.year
    return out


def format_table(columns: dict[str, dict]) -> str:
    keys = list(next(iter(columns.values())))
    width = max(len(c) for c in columns) + 2
    lines = [f"{'':<20}" + "".join(f"{c:>{max(width, 12)}}" for c in columns)]
    for k in keys:
        cells = []
        for c in columns.values():
            v = c[k]
            cells.append(f"{v:>{max(width, 12)}.2f}" if k == "샤프지수" else f"{v:>{max(width, 12)}.1%}")
        lines.append(f"{k:<20}" + "".join(cells))
    return "\n".join(lines)
