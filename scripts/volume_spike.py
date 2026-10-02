"""2026년 9월 거래량 급증 종목 스크리너 (KOSPI + KOSDAQ).

기준: 9월 일평균 거래량 / 8월 일평균 거래량 >= RATIO (기본 3배)
데이터: pykrx (KRX 정보데이터시스템, data.krx.co.kr)

사용법:
    pip install pykrx pandas
    python scripts/volume_spike.py                 # 기본: 2026-09 vs 2026-08, 3배
    python scripts/volume_spike.py --ratio 5 --min-volume 100000
"""
import argparse
import time

import pandas as pd
from pykrx import stock


def monthly_avg_volume(year: int, month: int) -> pd.Series:
    days = stock.get_previous_business_days(year=year, month=month)
    vols = []
    for d in days:
        df = stock.get_market_ohlcv(d.strftime("%Y%m%d"), market="ALL")
        vols.append(df["거래량"].rename(d.strftime("%Y%m%d")))
        time.sleep(0.3)  # KRX 요청 간격
    # 거래정지 등으로 거래량 0인 날도 평균에 포함 (해당 월 전체 영업일 기준)
    return pd.concat(vols, axis=1).fillna(0).mean(axis=1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--year", type=int, default=2026)
    p.add_argument("--month", type=int, default=9)
    p.add_argument("--ratio", type=float, default=3.0)
    p.add_argument("--min-volume", type=int, default=10_000,
                   help="비교 기준월 일평균 거래량 하한 (저유동성 종목 노이즈 제거)")
    p.add_argument("--out", default="volume_spike_2026_09.csv")
    args = p.parse_args()

    prev_year, prev_month = (args.year, args.month - 1) if args.month > 1 else (args.year - 1, 12)
    cur = monthly_avg_volume(args.year, args.month)
    prev = monthly_avg_volume(prev_year, prev_month)

    df = pd.DataFrame({"prev_avg_vol": prev, "cur_avg_vol": cur}).dropna()
    df = df[df["prev_avg_vol"] >= args.min_volume]
    df["ratio"] = df["cur_avg_vol"] / df["prev_avg_vol"]
    df = df[df["ratio"] >= args.ratio].sort_values("ratio", ascending=False)
    df.insert(0, "name", [stock.get_market_ticker_name(t) for t in df.index])
    df.index.name = "ticker"

    df.round(1).to_csv(args.out, encoding="utf-8-sig")
    print(f"{len(df)}개 종목 (기준 {args.ratio}배 이상) → {args.out}")
    print(df.round(1).head(50).to_string())


if __name__ == "__main__":
    main()
