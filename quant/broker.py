"""실매매 연결 지점. 지금은 구조만 있고 실제 주문은 구현되어 있지 않다.

모의매매(paper.py)가 만든 '다음 거래일 주문 예정'을 실계좌로 보내려면
Broker를 구현해 장 시작 전에 submit()을 호출하면 된다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class Broker(ABC):
    @abstractmethod
    def cash(self) -> float: ...

    @abstractmethod
    def positions(self) -> dict[str, int]: ...

    @abstractmethod
    def submit(self, ticker: str, side: str, shares: int, price: float | None = None) -> str:
        """주문을 내고 주문번호를 돌려준다. price가 None이면 시장가."""


class KISBroker(Broker):
    """한국투자증권 Open API용 자리. 앱키/시크릿은 환경변수로 받고 코드에 넣지 않는다."""

    def __init__(self, *_, **__):
        raise NotImplementedError("실매매는 아직 구현하지 않았습니다. 모의매매 검증 후 추가하세요.")

    def cash(self): ...
    def positions(self): ...
    def submit(self, ticker, side, shares, price=None): ...
