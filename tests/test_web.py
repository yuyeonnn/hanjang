"""3주차 화면 — 로그인 링크 서명, 종목 담기, 노트 열기와 기록, 글자 탈출. 서버를 띄우지 않고 WSGI 를 직접 부른다."""

import io
import json
from urllib.parse import quote, unquote

from hanjang import collect, db, web

SECRET = "test-secret"


def _app(now=1_000_000.0):
    con = db.connect(":memory:")
    collect.save_universe(con, [("005930", "삼성전자")], {})
    body = {"headline": "<script>x</script> 매출이 늘었어요.", "summary": [],
            "sections": [{"title": "회사 사정은 어떤가요?",
                          "sentences": [{"text": "많이 팔았어요.", "refs": ["F1"]}]}],
            "links": {"F1": "https://dart.fss.or.kr/x", "F2": "javascript:alert(1)"}}
    con.execute("insert into notes values ('005930', '2026-10-05', '[]', ?, 'llm:x', 'now')",
                (json.dumps(body),))
    return web.App(con, SECRET, clock=lambda: now), con


def call(app, path, method="GET", form="", cookie=""):
    p, _, q = path.partition("?")
    env = {"REQUEST_METHOD": method, "PATH_INFO": p, "QUERY_STRING": q, "HTTP_COOKIE": cookie,
           "CONTENT_LENGTH": str(len(form.encode())), "wsgi.input": io.BytesIO(form.encode())}
    got = {}
    body = b"".join(app(env, lambda s, h: got.update(status=s, headers=dict(h))))
    return got["status"], got["headers"], body.decode()


def test_login_link_expires_and_cannot_be_forged():
    t = web.login_token("a@b.c", SECRET, 0)
    assert web.check_login(t, SECRET, 60) == "a@b.c"
    assert web.check_login(t, SECRET, web.LINK_TTL + 1) is None  # 15분 지나면 끝
    assert web.check_login(t.replace("a@b.c", "x@b.c"), SECRET, 60) is None  # 이메일 바꿔치기
    assert web.check_login(t, "other", 60) is None


def _login(app):
    link = "/auth?t=" + quote(web.login_token("me@x.kr", SECRET, 1_000_000.0))
    _, h, _ = call(app, link)
    return h["Set-Cookie"].split(";")[0]


def test_flow_add_open_note_and_log_view():
    app, con = _app()
    assert "링크 받기" in call(app, "/")[2]  # 로그인 전엔 로그인 화면
    ck = _login(app)
    st, h, _ = call(app, "/add", "POST", "q=" + quote("삼성전자"), ck)
    assert st.startswith("303")
    _, _, cards = call(app, "/", cookie=ck)
    assert "삼성전자" in cards and "&lt;script&gt;" in cards and "<script>x" not in cards
    st, _, note = call(app, "/n/005930", cookie=ck)
    assert st.startswith("200") and 'href="https://dart.fss.or.kr/x"' in note
    assert "사라·팔아라는 의견도" in note
    assert [r[0] for r in con.execute("select page from views order by id")] == ["cards", "note"]


def test_unknown_stock_and_forged_cookie():
    app, con = _app()
    ck = _login(app)
    _, h, _ = call(app, "/add", "POST", "q=" + quote("없는회사"), ck)
    assert "아직 노트가 없어요" in unquote(h["Location"])
    assert "링크 받기" in call(app, "/", cookie="s=1.deadbeef")[2]  # 서명 틀린 쿠키는 로그인 화면
    assert web.safe_url("javascript:alert(1)") == "#"


def test_calendar_month_grid_marks_red_days_and_events():
    from datetime import date

    from hanjang import sources

    app, con = _app()
    ck = _login(app)
    call(app, "/add", "POST", "q=" + quote("삼성전자"), ck)
    con.execute("insert into holidays values ('2026-10-09', '한글날')")
    collect.save_disclosures(con, [sources.Disclosure("20261002000001", "005930", date(2026, 10, 2),
                                                      "주요사항보고서(자기주식취득결정)")])  # fmt: skip
    con.execute("update disclosures set code='BUYBACK', importance=3, direction=1")
    (uid,) = con.execute("select id from users").fetchone()
    html_ = app.calendar(uid, "2026-10", today=date(2026, 10, 7))
    assert "2026년 10월" in html_
    assert "<td class='red'><span class='n'>9</span><span class='hol'>한글날</span>" in html_
    assert "<td class='red'><span class='n'>4</span>" in html_  # 일요일
    assert "삼성전자 자사주 매입</a>" in html_ and "class='today'" in html_
    assert "2026년 10월" in app.calendar(uid, "nonsense", today=date(2026, 10, 7))  # 이상한 값은 이번 달
