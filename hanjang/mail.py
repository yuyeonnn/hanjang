"""메일 보내기 — 표준 라이브러리 SMTP 하나. 어느 메일 서비스든 `.env` 의 SMTP_* 만 바꾸면 된다.
SMTP_HOST 가 비어 있으면 보내지 않고 서버 콘솔에 찍는다 (개발용)."""

import smtplib
import sys
from email.message import EmailMessage

from hanjang.sources import env


def base_url() -> str:
    return env().get("BASE_URL", "http://localhost:8000").rstrip("/")


def send(to: str, subject: str, text: str) -> bool:
    """보냈으면 True, 콘솔에 찍기만 했으면 False."""
    e = env()
    if not e.get("SMTP_HOST"):
        print(f"[메일·개발용] {to} · {subject}\n{text}", file=sys.stderr, flush=True)
        return False
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = e["SMTP_FROM"], to, subject
    msg.set_content(text)
    with smtplib.SMTP(e["SMTP_HOST"], int(e.get("SMTP_PORT", "587")), timeout=30) as s:
        s.starttls()
        s.login(e["SMTP_USER"], e["SMTP_PASSWORD"])
        s.send_message(msg)
    return True


def login_mail(link: str) -> tuple[str, str]:
    return ("[한장] 로그인 링크예요",
            f"아래 링크를 누르면 한장에 들어가요. 15분 동안만 쓸 수 있어요.\n\n{link}\n\n"
            "직접 요청하지 않았다면 이 메일은 지우셔도 돼요.")  # fmt: skip


def weekly_mail(names: list[str]) -> tuple[str, str]:
    head = ", ".join(names[:3]) + (f" 외 {len(names) - 3}곳" if len(names) > 3 else "")
    return ("[한장] 이번 주 노트가 올라왔어요",
            f"{head}의 이번 주 노트가 올라왔어요.\n\n{base_url()}/\n\n"
            "사라·팔아라는 의견도, 앞으로의 예측도 없어요. 회사 사정을 쉬운 글로 정리했어요.\n"
            "안내 메일은 한장의 내 프로필에서 끌 수 있어요.")  # fmt: skip
