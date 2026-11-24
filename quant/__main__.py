"""명령줄 진입점: python -m quant backtest | paper"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import yaml

from . import metrics
from .data import load_prices
from .engine import build_targets, simulate


def load_all(cfg: dict, end: str | None, refresh: bool):
    tickers = [str(t) for t in cfg["universe"]]
    idx = str(cfg["index"])
    p = load_prices([*tickers, idx], cfg["data_start"], end, refresh=refresh)
    index_close = p.close[idx]
    uni = type(p)(*(getattr(p, f)[tickers] for f in ("open", "high", "low", "close", "volume")))
    return uni, index_close


def named(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    names = {str(k): v for k, v in cfg["universe"].items()}
    df = df.copy()
    df.insert(1, "name", df["ticker"].map(names))
    return df


def cmd_backtest(cfg, args):
    p, index_close = load_all(cfg, args.end, args.refresh)
    t = build_targets(p, index_close, cfg)
    start = args.start or cfg["backtest_start"]
    res = simulate(p, t, cfg, start)
    bench = index_close.reindex(res.equity.index).ffill()
    bench = bench / bench.iloc[0] * res.equity.iloc[0]

    print(f"\n백테스트 {res.equity.index[0].date()} ~ {res.equity.index[-1].date()}  "
          f"(초기 {cfg['capital']:,}원 → {res.equity.iloc[-1]:,.0f}원)\n")
    print(metrics.format_table({"전략": metrics.stats(res.equity), "KODEX200": metrics.stats(bench)}))
    yr = pd.DataFrame({"전략": metrics.yearly_returns(res.equity), "KODEX200": metrics.yearly_returns(bench)})
    print("\n연도별 수익률\n" + yr.map(lambda v: f"{v:.1%}").to_string())
    days = len(res.equity)
    turnover = (res.trades["shares"] * res.trades["price"]).sum() / res.equity.mean() / (days / 252)
    print(f"\n거래 {len(res.trades):,}건, 연 회전율 {turnover:.1f}배, 누적 비용 {res.trades['fee'].sum():,.0f}원")
    print("국면 비율: " + ", ".join(f"{k} {v:.0%}" for k, v in
                                 t.label.loc[res.equity.index[0]:].value_counts(normalize=True).items()))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"equity": res.equity, "benchmark": bench, "regime": t.label}).dropna().to_csv(out / "equity.csv")
    res.trades.to_csv(out / "trades.csv", index=False)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(2, 1, figsize=(10, 7), sharex=True, height_ratios=[3, 1])
        ax[0].plot(res.equity / res.equity.iloc[0], label="Strategy")
        ax[0].plot(bench / bench.iloc[0], label="KODEX 200", alpha=0.7)
        ax[0].set_yscale("log"); ax[0].legend(); ax[0].grid(alpha=0.3); ax[0].set_title("Equity (start = 1)")
        ax[1].fill_between(res.equity.index, res.equity / res.equity.cummax() - 1, 0, alpha=0.5)
        ax[1].set_title("Drawdown"); ax[1].grid(alpha=0.3)
        fig.tight_layout(); fig.savefig(out / "equity.png", dpi=120)
        print(f"\n결과 저장: {out}/equity.csv, trades.csv, equity.png")
    except ImportError:
        print(f"\n결과 저장: {out}/equity.csv, trades.csv (matplotlib 설치 시 차트도 저장)")


def cmd_paper(cfg, args):
    """모의매매: 시작일부터 오늘까지 실제 시세로 가상 체결을 재현하고 내일 주문을 보여준다.

    장 마감 후 하루 한 번 실행한다. 상태 파일에는 시작일과 초기 자본만 저장하므로 몇 번 실행해도 결과가 같다.
    """
    state_path = Path(cfg["paper"]["state_file"])
    p, index_close = load_all(cfg, None, refresh=True)
    # 장 마감(15:30) 전에 실행하면 오늘 봉이 미완성이므로 빼고, 전 거래일 종가 기준으로 계산한다
    now = pd.Timestamp.now(tz="Asia/Seoul")
    if p.close.index[-1].date() == now.date() and (now.hour, now.minute) < (15, 40):
        last_done = p.close.index[-2]
        p, index_close = p.loc(end=last_done), index_close.loc[:last_done]
        print(f"장 마감 전이라 오늘 봉은 제외하고 {last_done.date()} 종가 기준으로 계산합니다.")
    if args.reset or not state_path.exists():
        state = {"start": str(p.close.index[-1].date()), "capital": cfg["capital"]}
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state))
        print(f"모의매매 시작: {state['start']} 종가 기준, 자본 {state['capital']:,}원")
    state = json.loads(state_path.read_text())
    cfg = {**cfg, "capital": state["capital"]}
    t = build_targets(p, index_close, cfg)
    # 시작일 종가에 정한 목표가 다음 거래일 시가에 처음 체결되도록 시작일 다음 날부터 시뮬레이션
    first_trade_day = pd.Timestamp(state["start"]) + pd.DateOffset(days=1)
    res = simulate(p, t, cfg, str(first_trade_day.date()))

    today = p.close.index[-1]
    print(f"\n[{today.date()}] 시장 국면: {t.label.iloc[-1]}")
    print("전략 배분: " + ", ".join(f"{k} {v:.0%}" for k, v in t.alloc.iloc[-1].items())
          + f", 현금 {1 - t.alloc.iloc[-1].sum():.0%}")
    print(f"평가금액 {res.equity.iloc[-1]:,.0f}원 (수익률 {res.equity.iloc[-1] / state['capital'] - 1:+.2%}), "
          f"현금 {res.cash:,.0f}원")
    fmt = lambda df: named(df, cfg).to_string(index=False) if len(df) else "  (없음)"
    print("\n보유 종목\n" + fmt(res.positions))
    print(f"\n{today.date()} 체결\n" + fmt(res.trades[res.trades["date"] == today].drop(columns="date")))
    print("\n다음 거래일 시가 주문 예정 (수량은 종가 기준 추정)\n" + fmt(res.next_orders))
    print("\n다음 거래일 변동성 돌파 감시 (시가 + trigger_above_open 돌파 시 budget만큼 매수)\n" + fmt(res.next_breakouts))

    out = state_path.parent
    res.equity.to_csv(out / "equity.csv")
    res.trades.to_csv(out / "trades.csv", index=False)
    res.next_orders.to_csv(out / "next_orders.csv", index=False)
    from .report import publish

    publish(res, t, cfg, state, out, open_file=not args.no_open, prices=p)


def cmd_fills(cfg, args):
    """장중 확인용: 오늘 지금까지 체결된 모의 주문을 보여준다 (시가 체결분 + 이미 돌파한 변동성 돌파 매수).

    시가는 장 시작 직후 확정되므로 시가 체결 내역은 장중에도 정확하다. 기록·리포트는 바꾸지 않는다.
    """
    state_path = Path(cfg["paper"]["state_file"])
    if not state_path.exists():
        print("모의매매를 아직 시작하지 않았습니다. 먼저 python -m quant paper 를 실행하세요.")
        return
    state = json.loads(state_path.read_text())
    p, index_close = load_all(cfg, None, refresh=True)
    cfg = {**cfg, "capital": state["capital"]}
    res = simulate(p, build_targets(p, index_close, cfg), cfg,
                   str((pd.Timestamp(state["start"]) + pd.DateOffset(days=1)).date()))
    last = p.close.index[-1]
    if last.date() != pd.Timestamp.now(tz="Asia/Seoul").date():
        print(f"오늘 시세가 아직 없습니다 (최근 거래일 {last.date()}). 휴장일이거나 장 시작 전입니다.")
        return
    names = {str(k): v for k, v in cfg["universe"].items()}
    tr = res.trades[res.trades["date"] == last]
    print(f"{last.date()} 체결 {len(tr)}건")
    for r in tr.itertuples():
        when = "장중 돌파" if (r.sleeve == "breakout" and r.side == "BUY") else "시가"
        side = "매수" if r.side == "BUY" else "매도"
        print(f"{side} {names.get(r.ticker, r.ticker)} {r.shares:,}주 @ {r.price:,.0f}원 ({when}, {r.shares * r.price:,.0f}원)")


def cmd_schedule(cfg, args):
    from .schedule import install, remove

    remove() if args.remove else install(args.time)


def main():
    ap = argparse.ArgumentParser(prog="quant")
    ap.add_argument("--config", default="config.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backtest", help="과거 데이터로 전략 검증")
    b.add_argument("--start"); b.add_argument("--end"); b.add_argument("--out", default="out/backtest")
    b.add_argument("--refresh", action="store_true", help="캐시를 무시하고 데이터 새로 받기")
    pp = sub.add_parser("paper", help="모의매매 (장 마감 후 하루 한 번)")
    pp.add_argument("--reset", action="store_true", help="오늘부터 새로 시작")
    pp.add_argument("--no-open", action="store_true", help="리포트를 자동으로 열지 않음")
    sc = sub.add_parser("schedule", help="평일 장 마감 후 모의매매 자동 실행 등록 (Windows)")
    sc.add_argument("--time", default="15:50", help="실행 시각 (기본 15:50)")
    sc.add_argument("--remove", action="store_true", help="자동 실행 해제")
    sub.add_parser("fills", help="오늘 지금까지 체결된 모의 주문 보기 (장중 확인용)")
    args = ap.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    {"backtest": cmd_backtest, "paper": cmd_paper, "schedule": cmd_schedule, "fills": cmd_fills}[args.cmd](cfg, args)


if __name__ == "__main__":
    main()
