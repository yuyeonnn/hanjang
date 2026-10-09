"""테스트는 진짜 메일을 보내지 않는다 — .env 에 SMTP 가 있어도 늘 「서버 콘솔에 찍기」로 (2026-10-08, 실제로 가짜 주소로 나갈 뻔했다)."""

import pytest

from hanjang import mail


@pytest.fixture(autouse=True)
def no_real_mail(monkeypatch):
    monkeypatch.setattr(mail, "env", lambda: {})


@pytest.fixture(autouse=True)
def no_real_first_note(monkeypatch):
    """테스트는 새 종목을 담아도 진짜 DART·AI 를 부르지 않는다 (web.FIRST — 담자마자 바로 받기)."""
    from hanjang import web

    monkeypatch.setattr(web, "FIRST", lambda ticker: False)
