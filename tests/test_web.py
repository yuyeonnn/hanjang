"""3주차 화면 — 로그인 링크 서명, 종목 담기, 노트 열기와 기록, 글자 탈출. 서버를 띄우지 않고 WSGI 를 직접 부른다."""

import io
from datetime import date
import json
from urllib.parse import quote, unquote

from hanjang import collect, db, notes, web

SECRET = "test-secret"


def _app(now=1_000_000.0):
    con = db.connect(":memory:")
    collect.save_universe(con, [("005930", "삼성전자")], {})
    body = {"headline": "<script>x</script> 매출이 늘었어요.", "summary": [],
            "sections": [{"title": "회사 사정은 어떤가요?",
                          "sentences": [{"text": "많이 팔았어요.", "refs": ["F1"]}]}],
            "links": {"F1": "https://dart.fss.or.kr/x", "F2": "javascript:alert(1)"}}
    facts = [{"id": "F1", "text": "2025년 매출 1조원", "url": "https://dart.fss.or.kr/x", "tone": 1, "slots": {}},
             {"id": "F2", "text": "가짜", "url": "javascript:alert(1)", "tone": 0, "slots": {}}]
    con.execute("insert into notes values ('005930', '2026-10-05', ?, ?, 'llm:x', 'now')",
                (json.dumps(facts), json.dumps(body)))
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
    assert st.startswith("200") and '"url": "https://dart.fss.or.kr/x"' in note  # 출처 창 → 원문
    assert "javascript:alert" not in note and "toggleCitation('F1')" in note
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
    red = '<span class="font-label-micro text-label-micro text-tertiary font-semibold">'
    assert '<span class="font-label-micro text-label-micro text-on-surface font-medium">9</span><span class="text-[8px] text-on-surface-variant leading-tight line-clamp-1 mt-0.5">한글날' in html_  # 공휴일은 시안대로 검정
    assert red + "4</span>" in html_  # 일요일
    assert "삼성 자사주</a>" in html_ and "오늘</span>" in html_
    assert "자기주식취득결정 (자사주 매입)" in html_ and "이번 달 주목할 공시 1건" in html_
    assert "2026년 10월" in app.calendar(uid, "nonsense", today=date(2026, 10, 7))  # 이상한 값은 이번 달


def test_survey_saves_once_and_asks_pay_from_week_six():
    app, con = _app()
    ck = _login(app)
    call(app, "/add", "POST", "q=" + quote("삼성전자"), ck)
    note = call(app, "/n/005930", cookie=ck)[2]
    assert "이 노트가 도움이 됐나요?" in note and "돈을 내고도" not in note  # 1주째엔 안 묻는다
    st, h, _ = call(app, "/feedback", "POST", "t=005930&w=2026-10-05&h=4&c=" + quote("좋아요"), ck)
    assert h["Location"] == "/n/005930?thanks=1"
    assert con.execute("select helpful, comment from feedback").fetchone() == (4, "좋아요")
    assert "의견 고마워요" in call(app, "/n/005930", cookie=ck)[2]
    call(app, "/feedback", "POST", "t=005930&w=2026-10-05&h=9", ck)  # 범위 밖은 버린다
    assert con.execute("select count(*) from feedback").fetchone() == (1,)
    con.execute("update users set created_at = '2026-08-01'")  # 6주가 지난 사용자
    con.execute("delete from feedback")
    assert "돈을 내고도" in call(app, "/n/005930", cookie=ck)[2]


def test_monday_notice_only_to_users_with_new_notes(capsys):
    from hanjang import daily

    app, con = _app()
    ck = _login(app)
    call(app, "/add", "POST", "q=" + quote("삼성전자"), ck)
    con.execute("insert into users (email, created_at) values ('other@x.kr', '2026-10-01')")  # 종목 없음
    assert daily.notify(con, "2026-10-05") == 1
    assert daily.notify(con, "2026-10-12") == 0  # 그 주 노트가 없으면 안 보낸다
    assert "me@x.kr · [한장] 이번 주 노트가 올라왔어요" in capsys.readouterr().err


def test_learn_tab_lists_and_opens_articles():
    from hanjang import learn

    app, con = _app()
    ck = _login(app)
    st, _, body = call(app, "/learn", cookie=ck)
    assert st.startswith("200") and all(web.e(a["title"]) in body for a in learn.ARTICLES)
    st, _, body = call(app, "/learn/inverse-leverage", cookie=ck)
    assert st.startswith("200") and "하루" in body and "추천하지 않아요" in body
    assert '<strong class="font-semibold text-primary' in body and "**" not in body
    assert call(app, "/learn/nope", cookie=ck)[0].startswith("404")
    for a in learn.ARTICLES:  # 읽기 팁에도 권유·예측 말은 없다
        text = " ".join([a["title"], a["lead"], *a["body"], *a["points"]]).replace("**", "")
        assert not notes.FORBIDDEN.search(text), a["slug"]


def test_empty_good_or_concern_side_is_hidden():
    base = {"headline": "h", "summary": [], "sections": []}
    only_good = web.render_note("가", "000000", "2026-10-05", {**base, "good": [{"text": "좋아요.", "refs": ["F1"]}],
                                "concern": [], "good_title": "성장"}, "llm:x")
    assert "긍정</span>" in only_good and "부정</span>" not in only_good
    old = web.render_note("가", "000000", "2026-10-05", {**base, "good": [{"text": "없었어요.", "refs": ["F1"]}],
                          "concern": [{"text": "없었어요.", "refs": ["F1"]}], "good_title": "분류된 것 없음",
                          "concern_title": "분류된 것 없음"}, "llm:x")
    assert "긍정 요인과 부정 요인" not in old  # 둘 다 비면 절째 숨긴다


def test_avatar_opens_profile_with_real_counts():
    app, con = _app()
    ck = _login(app)
    call(app, "/add", "POST", "q=" + quote("삼성전자"), ck)
    assert 'href="/me"' in call(app, "/", cookie=ck)[2]
    call(app, "/n/005930", cookie=ck)
    st, _, body = call(app, "/me", cookie=ck)
    assert st.startswith("200") and "me@x.kr" in body and "1 / 20개" in body and "탈퇴하기" in body
    assert "함께한 지" not in body and "읽은 노트" not in body and "답장" not in body
    assert "로그인 링크 받기" in call(app, "/me")[2]  # 로그인 안 하면 로그인 화면


def test_mail_switch_and_delete_account():
    from hanjang import daily

    app, con = _app()
    ck = _login(app)
    call(app, "/add", "POST", "q=" + quote("삼성전자"), ck)
    assert "ON</span>" in call(app, "/me", cookie=ck)[2]
    call(app, "/me/mail", "POST", "", ck)  # 끄기
    assert "OFF</span>" in call(app, "/me", cookie=ck)[2]
    assert daily.notify(con, "2026-10-05") == 0  # 끈 사람에겐 안내 메일이 가지 않는다
    call(app, "/me/mail", "POST", "", ck)
    assert daily.notify(con, "2026-10-05") == 1
    st, h, _ = call(app, "/me/delete", "POST", "", ck)
    assert st.startswith("303") and "Max-Age=0" in h["Set-Cookie"]
    assert con.execute("select (select count(*) from users) + (select count(*) from holdings)"
                       " + (select count(*) from views)").fetchone() == (0,)


def test_bottom_nav_has_profile_tab():
    app, con = _app()
    ck = _login(app)
    body = call(app, "/me", cookie=ck)[2]
    assert 'href="/me"><span class="material-symbols-outlined text-[22px]">person</span>' in body
    assert 'aria-current=page class="flex flex-col items-center justify-center min-w-[44px] min-h-[44px] px-space-md transition-colors text-primary-container font-semibold" href="/me"' in body


def test_long_short_numbers_from_index():
    """보유 기간별 손해였던 비율 — 코드가 지수로 잰다. 글에 「보장 없음」이 늘 붙는다(불변식 5)."""
    from hanjang import learn

    pts = [(f"{2000 + i // 12}-{i % 12 + 1:02d}-01", v) for i, v in enumerate([100 + (i % 7) - 3 + i * 0.5 for i in range(300)])]
    h = learn.horizon(pts)
    one = next(r for r in h["rows"] if r["label"] == "1달")
    assert 0 < one["loss"] < 1 and h["fall"] < 0
    assert next(r for r in h["rows"] if r["label"] == "10년")["loss"] == 0  # 꾸준히 오른 가짜 자료
    con = db.connect(":memory:")
    con.executemany("insert into macro values (?, ?, ?)", [("ECOS:902Y002:KOR", d, v) for d, v in pts])
    a = learn.long_short(con)
    assert "보장은 없어요" in " ".join(a["body"]) and a["charts"]["한국"]["rows"]


def test_redone_label():
    assert web.redone("2026-10-05", "2026-10-08T07:00:00") == " · 10월 8일 고침"
    assert web.redone("2026-10-05", "2026-10-05T07:00:00") == "" and web.redone("2026-10-05", "now") == ""


def test_login_needs_consent_and_is_rate_limited(capsys):
    app, _ = _app()
    s, _, body = call(app, "/login", "POST", "email=a%40b.c")
    assert "동의해야" in body and "[메일" not in capsys.readouterr().err  # 동의 없이는 메일을 보내지 않는다
    s, _, body = call(app, "/login", "POST", "email=a%40b.c&agree=1")
    assert s.startswith("200") and "[메일" in capsys.readouterr().err
    s, _, body = call(app, "/login", "POST", "email=a%40b.c&agree=1")  # 1분 안에 또
    assert s.startswith("429") and "[메일" not in capsys.readouterr().err


def test_public_pages_and_security_headers():
    app, _ = _app()
    s, h, body = call(app, "/privacy")  # 로그인 없이
    assert s.startswith("200") and "탈퇴하면 그 자리에서 바로 지워요" in body and h["X-Frame-Options"] == "DENY"
    s, _, body = call(app, "/method")
    assert f"부채비율 {notes.DEBT_GOOD}% 미만" in body and "임원 이름은 받지도" in body
    _, _, body = call(app, "/")
    assert 'href="/privacy"' in body and 'name="agree"' in body


def test_news_off_drops_article_facts():
    con = db.connect(":memory:")
    collect.save_universe(con, [("005930", "삼성전자")], {})
    con.execute("insert into news values ('u', '005930', '2026-10-06', '연합', '삼성전자 기사')")
    assert any(f["id"] == "N1" for f in notes.facts(con, "005930", date(2026, 10, 7)))
    assert not any(f["id"].startswith("N") for f in notes.facts(con, "005930", date(2026, 10, 7), news=False))


def test_backup_keeps_last_14(tmp_path):
    from hanjang import backup

    src = tmp_path / "h.db"
    db.connect(src).close()
    for d in range(1, 18):
        backup.backup(date(2026, 10, d), src, tmp_path / "b")
    kept = sorted(p.name for p in (tmp_path / "b").iterdir())
    assert len(kept) == 14 and kept[0] == "hanjang-20261004.db" and kept[-1] == "hanjang-20261017.db"
