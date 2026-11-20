"""일봉 데이터 수집과 캐시."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

FIELDS = ["Open", "High", "Low", "Close", "Volume"]


@dataclass
class Prices:
    """필드별 (날짜 x 종목) 표. 거래정지일의 시가/고가/저가는 NaN."""

    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    close: pd.DataFrame
    volume: pd.DataFrame

    def loc(self, start=None, end=None) -> "Prices":
        return Prices(*(getattr(self, f).loc[start:end] for f in ("open", "high", "low", "close", "volume")))


def fetch_one(ticker: str, start: str, end: str | None, cache_dir: Path, refresh: bool = False,
              max_age_hours: float = 6.0) -> pd.DataFrame:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{ticker}.csv"
    if path.exists() and not refresh and (time.time() - path.stat().st_mtime) < max_age_hours * 3600:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
    else:
        import FinanceDataReader as fdr  # 필요할 때만 불러옴 (테스트는 네트워크 없이 실행)

        df = fdr.DataReader(ticker, start)[FIELDS]
        if df.empty:
            raise ValueError(f"{ticker}: 받은 데이터가 없습니다")
        df.to_csv(path)
    df = df.loc[start:end].astype(float)
    # 거래정지일은 시가/고가/저가가 0으로 내려옴 → 거래 불가로 표시
    halted = (df["Open"] <= 0) | (df["Volume"] <= 0)
    df.loc[halted, ["Open", "High", "Low"]] = float("nan")
    return df


def load_prices(tickers: list[str], start: str, end: str | None = None, cache_dir: str | Path = "data/cache",
                refresh: bool = False) -> Prices:
    cache_dir = Path(cache_dir)
    frames = {t: fetch_one(t, start, end, cache_dir, refresh) for t in tickers}
    panel = {f: pd.DataFrame({t: df[f] for t, df in frames.items()}).sort_index() for f in FIELDS}
    return Prices(panel["Open"], panel["High"], panel["Low"], panel["Close"], panel["Volume"])
