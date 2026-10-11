"""올린 뒤 확인 — 서버가 실제로 만드는 화면을 꺼내 본다. `python -m hanjang.smoke` (서버에서) → JSON {화면 이름: [상태, HTML]}.
받는 쪽(deploy/check.sh)이 상태와 화면 속 스크립트 문법을 본다. 테스트는 글자만 봐서, 스크립트 하나가 통째로 깨진 채 올라간 적이 있다(10/11
— 내 종목 화면의 검색 자동완성·캡처 올리기가 멈춰 있었다). DB 는 읽기 전용으로 연다: 열어본 기록도, 아무것도 쓰지 않는다."""

import io
import json
import sqlite3
import sys
import time
from datetime import datetime, timedelta

from hanjang import db, web

SECRET = "smoke-" + "x" * 40  # 이 프로세스 안에서만 쓰는 열쇠 — 진짜 쿠키와 무관하다


def pages() -> dict[str, tuple[str, str]]:
    # 진짜 DB 는 읽기만 한다 — 메모리에 통째로 베껴(수 MB) 거기서 화면을 그린다. 화면이 쓰는 것(열어본 기록·기사 사진 고르기)은 버려지는 사본에만 남는다
    src = sqlite3.connect(f"file:{db.PATH}?mode=ro", uri=True)
    con = sqlite3.connect(":memory:")
    src.backup(con)
    src.close()
    app = web.App(con, SECRET)
    out = {"로그인": ("200", app.login_page()), "로그인(메일 보냄)": ("200", app.login_page("a@b.c")), "닉네임": ("200", app.welcome_page())}

    def get(path: str, cookie: str = "") -> tuple[str, str]:
        env = {"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": "", "HTTP_COOKIE": cookie, "CONTENT_LENGTH": "0", "wsgi.input": io.BytesIO(b"")}
        got: dict = {}
        try:
            body = b"".join(app(env, lambda s, h: got.update(s=s))).decode()
        except Exception as err:  # noqa: BLE001  화면 하나가 터져도 나머지는 본다
            return "500", f"{type(err).__name__}: {err}"
        return got.get("s", "?")[:3], body

    for p in ("/privacy", "/method", "/rules", "/help/login", "/health", "/manifest.webmanifest", "/sw.js", "/offline", "/static/app.css", "/stocks.js"):
        out[p] = get(p)
    # 종목을 가장 많이 담은 사람의 눈으로 — 내 종목·노트·피드·기사·캘린더·읽기 팁·프로필·설정·알림
    row = con.execute("select h.user_id from holdings h join users u on u.id = h.user_id where u.nickname is not null and u.rules_at is not null"
                      " and u.banned = 0 group by 1 order by count(*) desc limit 1").fetchone()  # fmt: skip
    if row:
        ck = web.session_cookie(row[0], SECRET, time.time()).split(";")[0]
        if "articles" in sys.argv:  # 최근 이틀 기사 화면만 — 글을 읽어 보려고 (deploy/check.sh 와 무관)
            since = (datetime.now() - timedelta(days=2)).isoformat()
            return {f"/a/{i}": get(f"/a/{i}", ck) for (i,) in con.execute("select id from articles where made_at >= ? order by id", (since,))}
        (t,) = con.execute("select ticker from holdings where user_id = ? limit 1", (row[0],)).fetchone()
        art = con.execute("select id from articles order by id desc limit 1").fetchone()
        other = con.execute("select id from users where nickname is not null and id != ? limit 1", (row[0],)).fetchone()
        for p in ["/", f"/n/{t}", "/feed", "/calendar", "/learn", "/learn/dividend", "/me", "/me/settings", "/me/notices"] + (
                [f"/a/{art[0]}"] if art else []) + ([f"/u/{other[0]}"] if other else []):  # fmt: skip
            out[p] = get(p, ck)
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(pages(), ensure_ascii=False))
