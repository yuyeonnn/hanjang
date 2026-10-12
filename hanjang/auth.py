"""로그인 — 서명·쿠키·메일 링크 토큰과 요청 한도. 비밀번호는 없다."""

import hashlib
import hmac
from datetime import datetime

from hanjang import mail


CODE_TRIES = 5  # 로그인 코드를 틀릴 수 있는 횟수 — 넘으면 그 코드는 버린다
LINK_TTL = 15 * 60  # 로그인 링크 15분
LOGIN_GAP, LOGIN_HOURLY = 60, 5  # 같은 주소로 링크는 1분에 한 번, 한 시간에 다섯 번까지 (메일 폭탄·발송 계정 정지 막기)
# 주소를 바꿔 가며 요청하면 위 제한을 피해 남의 메일함에 뿌리고 Gmail 하루 한도(약 500통)를 다 쓸 수 있다 — 한 곳(IP)·전체에도 한도 (보안 점검 10/11)
LOGIN_IP_HOURLY, LOGIN_ALL_HOURLY = 10, 60


# --- 서명: 로그인 링크와 쿠키 (세션 표 없이 — ERD 「안 만든 것」) ---


def sign(value: str, secret: str) -> str:
    return value + "." + hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()[:32]


def unsign(token: str, secret: str) -> str | None:
    value, _, _ = token.rpartition(".")
    return value if value and hmac.compare_digest(sign(value, secret), token) else None


SESSION_TTL = 365 * 86400  # 로그인 쿠키는 발급 뒤 1년(앱으로 내면 한 번 로그인하고 계속 쓴다 — 사용자 10/12, 그 전엔 90일) — 서버가 센다(브라우저의 Max-Age 는 정직한 브라우저만 지킨다)
# 날짜 없는 옛 쿠키(「사용자 번호」만 서명)는 이날까지만 받고, 그 사이 들어오면 날짜가 든 새 쿠키로 바꿔 준다 — 아무도 갑자기 로그아웃되지 않게.
# 이날이 지나면 옛 쿠키는 통하지 않는다(새 나간 쿠키가 영영 쓰이던 구멍, 보안 점검 10/11). ponytail: 2026-11-15 뒤엔 이 줄과 legacy 갈래를 지운다
LEGACY_UNTIL = datetime(2026, 11, 15).timestamp()


def session_cookie(uid: int, secret: str, now: float, age: int = SESSION_TTL) -> str:
    ck = f"s={sign(f'{uid}|{int(now)}', secret)}; Path=/; HttpOnly; SameSite=Lax; Max-Age={age}"
    return ck + ("; Secure" if mail.base_url().startswith("https://") else "")


def read_session(token: str, secret: str, now: float) -> tuple[int | None, bool]:
    """쿠키 → (사용자 번호, 옛 쿠키라 새로 구워 줘야 하나). 서명이 틀리거나 SESSION_TTL 이 지났으면 (None, False)."""
    v = unsign(token, secret)
    if not v:
        return None, False
    uid, _, at = v.partition("|")
    if not uid.isdigit():
        return None, False
    if at:
        return (int(uid), False) if at.isdigit() and now - int(at) <= SESSION_TTL else (None, False)
    return (int(uid), True) if now < LEGACY_UNTIL else (None, False)


def login_token(email: str, secret: str, now: float) -> str:
    return sign(f"{email}|{int(now) + LINK_TTL}", secret)


def check_login(token: str, secret: str, now: float) -> str | None:
    """링크 → 이메일. 서명이 틀리거나 15분이 지났으면 None."""
    v = unsign(token, secret)
    if not v or "|" not in v:
        return None
    email, _, exp = v.rpartition("|")
    return email if exp.isdigit() and now <= int(exp) else None
