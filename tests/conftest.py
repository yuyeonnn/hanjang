import pytest

from hanjang import mail, sources


@pytest.fixture(autouse=True)
def no_real_mail(monkeypatch):
    """테스트는 진짜 메일을 보내지 않는다 — .env 에 SMTP 가 있어도 콘솔에만 찍는다."""
    monkeypatch.setattr(mail, "env", lambda: {**sources.env(), "SMTP_HOST": ""})
