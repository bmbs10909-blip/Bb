"""모의매매 결과를 보기 쉬운 엑셀 파일로 저장."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

SIDE = {"BUY": "매수", "SELL": "매도"}
SLEEVE = {"core": "코어(추세·평균회귀·팩터)", "breakout": "변동성 돌파"}
REGIME = {"bull_calm": "상승·안정", "bull_highvol": "상승·고변동성", "neutral": "중립",
          "bear_calm": "하락·안정", "bear_highvol": "하락·고변동성"}
STRATEGY = {"momentum": "추세추종", "meanrev": "평균회귀", "factor": "팩터", "breakout": "변동성 돌파"}

WON, PCT, INT = "#,##0", "0.00%", "#,##0"
FORMATS = {"날짜": "yyyy-mm-dd", "종가": WON, "평가금액": WON, "체결가": WON, "금액": WON, "비용": WON, "배정 금액": WON,
           "돌파 기준(시가+)": WON, "비중": PCT, "일수익률": PCT, "누적수익률": PCT,
           "수량": INT, "수량(추정)": INT, "코어 수량": INT, "돌파 수량": INT}


def _tables(res, t, cfg: dict, state: dict) -> dict[str, pd.DataFrame]:
    names = {str(k): v for k, v in cfg["universe"].items()}
    today = res.equity.index[-1]
    equity_now = float(res.equity.iloc[-1])
    alloc = t.alloc.iloc[-1]

    summary = [("기준일", str(today.date())), ("모의매매 시작일", state["start"]),
               ("시장 국면", REGIME.get(t.label.iloc[-1], t.label.iloc[-1])),
               ("초기 자본", state["capital"]), ("평가금액", equity_now),
               ("누적수익률", equity_now / state["capital"] - 1), ("현금", res.cash),
               ("현금 비중", res.cash / equity_now), ("보유 종목 수", len(res.positions)),
               ("누적 거래 건수", len(res.trades)), ("누적 거래 비용", float(res.trades["fee"].sum())), ("", "")]
    summary += [(f"전략 배분: {STRATEGY[k]}", float(v)) for k, v in alloc.items()]
    summary += [("전략 배분: 현금", float(1 - alloc.sum()))]

    pos = res.positions.rename(columns={"ticker": "종목코드", "core": "코어 수량", "breakout": "돌파 수량",
                                        "close": "종가", "value": "평가금액"})
    pos.insert(1, "종목명", pos["종목코드"].map(names))
    pos["비중"] = pos["평가금액"] / equity_now

    tr = res.trades.copy()
    tr["금액"] = tr["shares"] * tr["price"]
    tr = pd.DataFrame({"날짜": tr["date"].dt.date, "종목코드": tr["ticker"], "종목명": tr["ticker"].map(names),
                       "구분": tr["side"].map(SIDE), "수량": tr["shares"], "체결가": tr["price"],
                       "금액": tr["금액"], "전략": tr["sleeve"].map(SLEEVE), "비용": tr["fee"]})

    orders = res.next_orders
    orders = pd.DataFrame({"종목코드": orders["ticker"], "종목명": orders["ticker"].map(names),
                           "구분": orders["side"].map(SIDE), "수량(추정)": orders["shares"],
                           "전략": orders["sleeve"].map(SLEEVE)})
    bo = res.next_breakouts
    bo = pd.DataFrame({"종목코드": bo["ticker"], "종목명": bo["ticker"].map(names),
                       "돌파 기준(시가+)": bo["trigger_above_open"], "배정 금액": bo["budget"]})

    eq = pd.DataFrame({"날짜": res.equity.index.date, "평가금액": res.equity.to_numpy(),
                       "일수익률": res.equity.pct_change(fill_method=None).fillna(0).to_numpy(),
                       "누적수익률": (res.equity / state["capital"] - 1).to_numpy()})
    return {"요약": pd.DataFrame(summary, columns=["항목", "값"]), "보유 종목": pos,
            "오늘 체결": tr[tr["날짜"] == today.date()], "다음 거래일 주문": orders, "변동성 돌파 감시": bo,
            "자산 추이": eq, "전체 거래내역": tr}


def write_excel(res, t, cfg: dict, state: dict, out_dir: Path) -> Path:
    from openpyxl.chart import LineChart, Reference
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    tables = _tables(res, t, cfg, state)
    path = out_dir / f"모의매매_리포트_{res.equity.index[-1].date()}.xlsx"
    head_font, head_fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="305496")
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        for name, df in tables.items():
            df.to_excel(xl, sheet_name=name, index=False)
            ws = xl.sheets[name]
            ws.freeze_panes = "A2"
            for col, title in enumerate(df.columns, start=1):
                cell = ws.cell(row=1, column=col)
                cell.font, cell.fill, cell.alignment = head_font, head_fill, Alignment(horizontal="center")
                values = [str(title), *(str(v) for v in df.iloc[:, col - 1])]
                # 한글은 폭이 넓으므로 글자 수보다 넉넉하게
                ws.column_dimensions[get_column_letter(col)].width = min(40, max(len(v) for v in values) * 1.6 + 4)
                if title in FORMATS:
                    for row in range(2, len(df) + 2):
                        ws.cell(row=row, column=col).number_format = FORMATS[title]
            if df.empty:
                ws.cell(row=2, column=1, value="(없음)")
        # 요약 시트: 항목에 따라 원/퍼센트 표시
        ws = xl.sheets["요약"]
        for row in range(2, ws.max_row + 1):
            label, cell = str(ws.cell(row=row, column=1).value), ws.cell(row=row, column=2)
            if isinstance(cell.value, (int, float)):
                is_pct = "수익률" in label or "비중" in label or label.startswith("전략 배분")
                cell.number_format = PCT if is_pct else WON
            cell.alignment = Alignment(horizontal="right")
        # 자산 추이 차트
        ws = xl.sheets["자산 추이"]
        if ws.max_row > 2:
            chart = LineChart()
            chart.title, chart.height, chart.width = "평가금액 추이", 9, 20
            chart.add_data(Reference(ws, min_col=2, min_row=1, max_row=ws.max_row), titles_from_data=True)
            chart.set_categories(Reference(ws, min_col=1, min_row=2, max_row=ws.max_row))
            ws.add_chart(chart, "F2")
    return path


def desktop_dir() -> Path | None:
    """바탕화면 폴더. Windows에서는 OneDrive로 옮겨진 경우도 찾는다."""
    try:
        import os
        import winreg

        key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            path = Path(os.path.expandvars(winreg.QueryValueEx(k, "Desktop")[0]))
        if path.is_dir():
            return path
    except (ImportError, OSError):
        pass
    path = Path.home() / "Desktop"
    return path if path.is_dir() else None
