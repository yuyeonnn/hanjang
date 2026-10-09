import re
"""3주차 화면 — 로그인 링크 서명, 종목 담기, 노트 열기와 기록, 글자 탈출. 서버를 띄우지 않고 WSGI 를 직접 부른다."""

import io
from datetime import date
import json
from urllib.parse import quote, unquote

from hanjang import collect, db, mail, notes, web

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


def call(app, path, method="GET", form="", cookie="", ctype="application/x-www-form-urlencoded"):
    p, _, q = path.partition("?")
    env = {"REQUEST_METHOD": method, "PATH_INFO": p, "QUERY_STRING": q, "HTTP_COOKIE": cookie, "CONTENT_TYPE": ctype,
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


def _login(app, nick="나"):
    link = "/auth?t=" + quote(web.login_token("me@x.kr", SECRET, 1_000_000.0))
    _, h, _ = call(app, link)
    ck = h["Set-Cookie"].split(";")[0]
    call(app, "/welcome", "POST", "nickname=" + quote(nick + "닉"), ck)  # 가입할 때 닉네임
    return ck


def test_flow_add_open_note_and_log_view():
    app, con = _app()
    assert "시작하기" in call(app, "/")[2]  # 로그인 전엔 로그인 화면
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
    assert "찾지 못했어요" in unquote(h["Location"])
    assert "시작하기" in call(app, "/", cookie="s=1.deadbeef")[2]  # 서명 틀린 쿠키는 로그인 화면
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
    red = '<span class="font-label-micro text-label-micro lg:text-[14px] text-tertiary font-semibold">'
    assert '<span class="font-label-micro text-label-micro lg:text-[14px] text-on-surface font-medium">9</span><span class="text-[8px] lg:text-[11px] text-on-surface-variant leading-tight line-clamp-1 mt-0.5">한글날' in html_  # 공휴일은 시안대로 검정
    assert red + "4</span>" in html_  # 일요일
    assert "<span class='lg:hidden'>삼성</span><span class='hidden lg:inline'>삼성전자</span> 자사주</a>" in html_ and "오늘</span>" in html_
    assert "자기주식취득결정 (자사주 매입)" in html_ and "이번 달 주목할 공시 1건" in html_
    assert "2026년 10월" in app.calendar(uid, "nonsense", today=date(2026, 10, 7))  # 이상한 값은 이번 달
    con.execute("insert into events values ('005930', '2026-10-29', 'EARNINGS', '실적 발표', '20261007000002')")
    soon = app.calendar(uid, "2026-10", today=date(2026, 10, 7))
    assert "삼성 실적</span>" in soon and "삼성전자 실적 발표</span>" in soon and "삼성전자 <b>실적 발표</b>" in soon  # 앞으로의 일정 — 테두리 칩 · 이 달의 일정 목록
    # 고른 날 일정 — 처음엔 오늘(10/7, 일정 없음), 10/2 칸을 누르면 그 날 공시가 보이게 미리 묶어 둔다
    assert 'data-day="2026-10-02"' in soon and "pickDay('2026-10-07')" in soon
    assert '<div data-list="2026-10-02" hidden>' in soon and '<div data-list="2026-10-29" hidden>' in soon and '<p data-list="none"' in soon
    assert "pickDay('2026-11-01')" in app.calendar(uid, "2026-11", today=date(2026, 10, 7))  # 다른 달은 1일
    con.execute("insert into ipos values ('c1', 'r9', '엘리스그룹', '2026-10-20', '2026-10-21', null, null, 70400, 1, '', '')")  # 상장일 아직 없음
    assert '<div data-list="2026-10-20" hidden>' in app.calendar(uid, "2026-10", today=date(2026, 10, 7))


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
    body = {"headline": "h<b>", "summary": [{"text": "문장.", "refs": ["F1"]}]}
    _, _, html = mail.weekly_mail("2026-10-05", [{"ticker": "005930", "name": "삼성전자", "body": body, "facts": [{"id": "F1", "url": "https://dart/x"}]}],
                                  [("2026-10-07", "삼성전자", "배당", "", "https://dart/y", 0)], [("2026-10-09", "한글날")])  # fmt: skip
    assert 'href="https://dart/x"' in html and "h&lt;b&gt;" in html and "한글날" in html and "문장." in html and "dart/y" in html


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
    assert "좋게 볼 점</span>" in only_good and "주의해서 볼 점</span>" not in only_good
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
    assert st.startswith("200") and 'href="/me/settings"' in body and "탈퇴하기" not in body  # 프로필엔 설정 버튼만
    st, _, body = call(app, "/me/settings", cookie=ck)
    assert st.startswith("200") and "me@x.kr" in body and "1 / 20개" in body and "탈퇴하기" in body
    assert "함께한 지" not in body and "읽은 노트" not in body and "답장" not in body
    assert "시작하기" in call(app, "/me")[2]  # 로그인 안 하면 로그인 화면


def test_mail_switch_and_delete_account():
    from hanjang import daily

    app, con = _app()
    ck = _login(app)
    call(app, "/add", "POST", "q=" + quote("삼성전자"), ck)
    assert "ON</span>" in call(app, "/me/settings", cookie=ck)[2]
    call(app, "/me/mail", "POST", "", ck)  # 끄기
    assert "OFF</span>" in call(app, "/me/settings", cookie=ck)[2]
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
    assert 'aria-current=page class="flex flex-col items-center justify-center min-w-[44px] min-h-[44px] px-1 transition-colors text-primary-container font-semibold" href="/me"' in body


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


def test_login_needs_consent_then_goes_straight_in(capsys):
    app, _ = _app()
    s, _, body = call(app, "/login", "POST", "email=a%40b.c")
    assert "동의해야" in body  # 동의 없이는 안 된다
    s, h, _ = call(app, "/login", "POST", "email=a%40b.c&agree=1")
    assert s.startswith("303") and "s=" in h["Set-Cookie"] and "[메일" not in capsys.readouterr().err  # 처음 — 메일 없이 바로
    assert "닉네임" in call(app, "/", cookie=h["Set-Cookie"].split(";")[0])[2]
    _login(app)  # 닉네임까지 만든 계정도
    s, h, _ = call(app, "/login", "POST", "email=me%40x.kr&agree=1")
    assert s.startswith("303") and "[메일" not in capsys.readouterr().err  # 바로 내 종목으로
    assert "내 종목" in call(app, "/", cookie=h["Set-Cookie"].split(";")[0])[2]


def test_public_pages_and_security_headers():
    app, _ = _app()
    s, h, body = call(app, "/privacy")  # 로그인 없이
    assert s.startswith("200") and "탈퇴하면 그 자리에서 바로 지워요" in body and h["X-Frame-Options"] == "DENY"
    s, _, body = call(app, "/method")
    assert f"부채비율 {notes.DEBT_GOOD}% 미만" in body and "임원 이름은 받지도" in body
    _, _, body = call(app, "/")
    assert 'href="/privacy"' in body and 'name="agree"' in body
    assert 'property="og:title" content="한장' in body and "/static/og.png" in body  # 링크 미리보기 카드


def test_news_fact_carries_rss_summary_so_its_numbers_may_be_quoted():
    from datetime import date

    app, con = _app()
    con.execute("insert into news (url, ticker, date, press, title, summary) values ('u', '005930', '2026-10-06', '연합뉴스', '삼성전자 소식', '영업이익 107.4조원')")
    con.execute("insert into news (url, ticker, date, press, title, summary) values ('v', '005930', '2026-10-06', '한국경제', '삼성전자 목표주가 상향', '')")
    ns = [f for f in notes.facts(con, "005930", date(2026, 10, 7)) if f["id"].startswith("N")]
    assert len(ns) == 1 and "107.4조원" in ns[0]["text"] and ns[0]["slots"]["매체"] == "연합뉴스"  # 목표주가 소식은 뺀다

def test_backup_keeps_last_14(tmp_path):
    from hanjang import backup

    src = tmp_path / "h.db"
    db.connect(src).close()
    for d in range(1, 18):
        backup.backup(date(2026, 10, d), src, tmp_path / "b")
    kept = sorted(p.name for p in (tmp_path / "b").iterdir())
    assert len(kept) == 14 and kept[0] == "hanjang-20261004.db" and kept[-1] == "hanjang-20261017.db"


def test_like_toggle_views_and_date():
    """좋아요는 한 번 더 누르면 취소 · 읽음은 이 주 노트를 연 횟수 · 날짜는 노트를 만든 날. 누가 눌렀는지는 안 보인다."""
    app, con = _app()
    con.execute("update notes set made_at = '2026-10-06T07:00:00'")
    con.execute("insert into users (id, email, created_at, nickname) values (1, 'a@b.c', '2026-10-01', '가'), (2, 'z@b.c', '2026-10-01', '나')")
    me, other = f"s={web.sign('1', SECRET)}", f"s={web.sign('2', SECRET)}"
    call(app, "/like", "POST", "t=005930&w=2026-10-05", other)
    call(app, "/n/005930", cookie=other)
    _, _, body = call(app, "/n/005930", cookie=me)
    assert "10월 6일 · 읽음 2" in body and "좋아요 1개" in body and "z@b.c" not in body
    call(app, "/like", "POST", "t=005930&w=2026-10-05", me)
    _, _, body = call(app, "/n/005930", cookie=me)
    assert "좋아요 2개" in body and 'aria-pressed="true"' in body
    call(app, "/like", "POST", "t=005930&w=2026-10-05", me)  # 다시 누르면 취소
    assert con.execute("select count(*) from likes").fetchone()[0] == 1
    call(app, "/like", "POST", "t=005930&w=1999-01-04", me)  # 없는 노트엔 안 쌓인다
    assert con.execute("select count(*) from likes").fetchone()[0] == 1


def test_follow_regram_feed_and_privacy():
    """닉네임이 있어야 남에게 보인다 · 팔로우한 사람의 리그램이 피드에 · 이메일은 어디에도 안 보인다 · 코멘트 금지어."""
    app, con = _app()
    con.execute("insert into users (id, email, created_at, nickname) values (1, 'me@b.c', '2026-10-01', '나닉'), (2, 'you@b.c', '2026-10-01', '너닉')")
    me, you = f"s={web.sign('1', SECRET)}", f"s={web.sign('2', SECRET)}"
    assert call(app, "/me/profile", "POST", "nickname=" + quote("반도체공부") + "&bio=" + quote("메모리 회사를 봐요"), you)[1]["Location"] == "/me"  # 저장하면 내 프로필로
    assert call(app, "/me/profile", "POST", "nickname=" + quote("반도체공부"), me)[1]["Location"].startswith("/me/settings?msg=")  # 같은 이름은 안 된다
    assert "msg=" in call(app, "/me/profile", "POST", "nickname=" + quote("가나") + "&bio=" + quote("지금 사세요"), me)[1]["Location"]  # 자기소개 금지어
    call(app, "/regram", "POST", "k=note&r=005930&w=2026-10-05", you)
    _, _, body = call(app, "/feed", cookie=me)
    assert "많이 읽은 노트" in body and "반도체공부" not in body  # 팔로우 전 — 조회수 순 노트
    call(app, "/follow", "POST", "u=2", me)
    _, _, body = call(app, "/feed", cookie=me)
    assert "반도체공부" in body and "삼성전자" in body and "you@b.c" not in body and "많이 읽은 노트" not in body
    _, _, body = call(app, "/u/2", cookie=me)
    assert "팔로워 <b class=\"text-on-surface\">1</b>" in body and "메모리 회사를 봐요" in body and ">팔로잉</button>" in body
    _, _, body = call(app, "/feed?q=" + quote("반도체"), cookie=me)
    assert 'href="/u/2"' in body
    call(app, "/me/delete", "POST", "", you)  # 탈퇴하면 팔로우·리그램도 지운다
    assert con.execute("select (select count(*) from follows) + (select count(*) from regrams)").fetchone()[0] == 0


def test_add_many_by_paste_and_scan(monkeypatch):
    """여러 종목 한 번에(쉼표·줄바꿈·띄어쓰기) · 캡처는 AI 가 이름만 읽고 코드가 우리 종목과 맞춰 담는다."""
    app, con = _app()
    collect.save_universe(con, [("005930", "삼성전자"), ("000660", "SK하이닉스"), ("006400", "삼성SDI")], {})
    ck = _login(app)
    _, h, _ = call(app, "/add", "POST", "q=" + quote("삼성전자, SK하이닉스\n없는회사"), ck)
    assert "2종목을 담았어요" in unquote(h["Location"]) and "없는회사" in unquote(h["Location"])
    from hanjang import llm

    seen = {}
    monkeypatch.setattr(llm, "ask", lambda *a, **k: seen.update(k) or ["삼성 SDI", "SK하이닉스", "123456"])
    s, h, body = call(app, "/scan", "POST", json.dumps({"img": "data:image/jpeg;base64,AAAA"}), ck, ctype="application/json")
    assert h["Content-Type"].startswith("application/json") and "2종목을 담았어요" in json.loads(body)["msg"]
    assert seen["image"].startswith("data:image/jpeg")
    assert con.execute("select count(*) from holdings").fetchone()[0] == 3
    s, _, body = call(app, "/scan", "POST", json.dumps({"img": "javascript:x"}), ck, ctype="application/json")
    assert s.startswith("400")


def test_profile_photo_upload_serve_and_delete():
    import base64

    app, con = _app()
    ck = _login(app)
    jpg = b"\xff\xd8\xff\xe0" + b"0" * 100
    s, _, body = call(app, "/me/photo", "POST", json.dumps({"img": "data:image/jpeg;base64," + base64.b64encode(jpg).decode()}), ck, ctype="application/json")
    assert s.startswith("200")
    s, h, body = call_raw(app, "/p/1.jpg", ck)
    assert h["Content-Type"] == "image/jpeg" and body == jpg
    assert '/p/1.jpg?v=' in call(app, "/me", cookie=ck)[2]  # 위쪽 동그라미·프로필에 사진
    s, _, _ = call(app, "/me/photo", "POST", json.dumps({"img": "data:image/jpeg;base64," + base64.b64encode(b"<svg>").decode()}), ck, ctype="application/json")
    assert s.startswith("400")  # JPEG 가 아니면 받지 않는다
    call(app, "/me/photo/delete", "POST", "", ck)
    assert call_raw(app, "/p/1.jpg", ck)[0].startswith("404")


def call_raw(app, path, cookie=""):
    env = {"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": "", "HTTP_COOKIE": cookie, "CONTENT_LENGTH": "0", "wsgi.input": io.BytesIO()}
    got = {}
    body = b"".join(app(env, lambda s, h: got.update(status=s, headers=dict(h))))
    return got["status"], got["headers"], body


def test_nickname_is_asked_at_signup_and_unique():
    app, con = _app()
    con.execute("insert into users (id, email, created_at, nickname) values (9, 'x@b.c', '2026-10-01', 'Hanjang')")
    _, h, _ = call(app, "/auth?t=" + quote(web.login_token("new@b.c", SECRET, 1_000_000.0)))
    ck = h["Set-Cookie"].split(";")[0]
    assert "닉네임을 정해 주세요" in call(app, "/", cookie=ck)[2]  # 정하기 전엔 다른 화면으로 못 간다
    assert "닉네임을 정해 주세요" in call(app, "/feed", cookie=ck)[2]
    assert "이미 누가 쓰고 있어요" in call(app, "/welcome", "POST", "nickname=hanjang", ck)[2]  # 대소문자만 달라도 겹침
    assert "2~20자" in call(app, "/welcome", "POST", "nickname=a", ck)[2]
    assert call(app, "/welcome", "POST", "nickname=" + quote("새사람"), ck)[1]["Location"] == "/"
    assert "닉네임을 정해 주세요" not in call(app, "/", cookie=ck)[2]
    assert "msg=" in call(app, "/me/profile", "POST", "nickname=", ck)[1]["Location"]  # 비울 수 없다


def test_industry_photos_served_and_used():
    app, con = _app()
    s, h, body = call_raw(app, "/static/photos/semiconductor.jpg")  # 로그인 없이
    assert s.startswith("200") and h["Content-Type"] == "image/jpeg" and body[:3] == b"\xff\xd8\xff"
    assert call_raw(app, "/static/photos/../db.jpg")[1]["Content-Type"].startswith("text/html")  # 다른 파일은 못 꺼낸다(로그인 화면이 나온다)
    assert web.photo_for(None) == "/static/photos/seoul.jpg"
    assert all((web.STATIC / "photos" / f"{k}.jpg").exists() for k in set(web.PHOTO.values()) | {"seoul"})
    ck = _login(app)
    assert "/static/photos/" in call(app, "/feed", cookie=ck)[2]  # 사진은 피드에만 — 노트 위는 실적 차트


def test_note_logo_and_domain():
    assert ">삼성<" in web.logo("삼성전자", None)  # 로고를 못 찾으면 그룹 대표색 표시
    from hanjang import sources
    assert sources.domain("www.samsung.com/sec") == "samsung.com" and sources.domain("http://WWW.SKHYNIX.COM") == "skhynix.com"
    assert sources.domain("-") is None


def test_report_blocks_compute_from_dart_numbers():
    d = web.dividend_block([(2024, 1000, 5_000_000_000_000, 25.0), (2025, 1100, 6_000_000_000_000, 30.0)])
    assert "1,100원" in d and "30.0%" in d and "6.0조원" in d
    b = web.business_block({"what": ["반도체를 만들어요."], "segments": [{"name": "DS", "share": "39.0%"}], "risks": ["경쟁"], "year": 2025}, "123")
    assert "39.0%" in b and "rcpNo=123" in b and "2025년 사업보고서" in b
    assert "회사가 꼽은 위험" in web.risk_block({"risks": ["경쟁이 심해요"]}) and web.risk_block(None) == ""


def test_weekly_mail_carries_wave_images(monkeypatch):
    """본문이 부르는 물결 그림(cid)이 메일에 붙어 간다 — 안 붙으면 메일 앱에 깨진 그림이 보인다."""
    sent = []

    class FakeSMTP:
        def __init__(self, *a, **k): ...
        def __enter__(self): return self
        def __exit__(self, *a): ...
        def starttls(self): ...
        def login(self, *a): ...
        def send_message(self, m): sent.append(m)

    monkeypatch.setattr(mail, "env", lambda: {"SMTP_HOST": "x", "SMTP_FROM": "a@b.c", "SMTP_USER": "u", "SMTP_PASSWORD": "p"})
    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSMTP)
    body = {"headline": "h", "summary": [{"text": "문장.", "refs": []}]}
    assert mail.send("me@x.kr", *mail.weekly_mail("2026-10-05", [{"ticker": "005930", "name": "삼성전자", "body": body, "facts": []}]))
    cids = {p["Content-ID"] for p in sent[0].walk() if p.get_content_type() == "image/png"}
    assert cids == {f"<{mail._cid(c, d)}>" for c, d in mail.WAVES}  # 본문이 부르는 물결 그림 셋
    assert mail.wave_png(mail.GREEN).startswith(b"\x89PNG")


def test_feed_photos_never_repeat_on_one_screen():
    p = web.Photos()
    assert p.topic("chip") and all("chip" in x for x in p.topic("chip"))
    picks = [p.pick("MAJOR_CONTRACT", None) for _ in range(20)] + [p.pick(None, "264") for _ in range(10)]
    assert len(set(picks)) == len(picks)  # 같은 화면에 같은 사진은 두 번 없다
    app, _ = _app()
    assert call_raw(app, "/static/photos/pool/chip1.jpg")[1]["Content-Type"] == "image/jpeg"


def test_big_holders_list_and_page():
    app, con = _app()
    con.execute("insert into big_holdings (inst, stock_code, corp_name, corp_cls, rate, rate_chg, date, rcept_no) values ('nps', '005930', '삼성전자', 'Y', 7.1, 0.3, '2026-10-01', 'r1'),"
                " ('nps', '999990', '작은회사', 'K', 5.2, -1.0, '2026-09-01', 'r2')")
    ck = _login(app)
    _, _, body = call(app, "/learn", cookie=ck)
    assert "큰손 포트폴리오" in body and 'href="/learn/big/nps"' in body and "2종목" in body
    _, _, body = call(app, "/learn/big/nps", cookie=ck)
    assert "국민연금" in body and "지분 7.10%" in body and 'href="/n/005930"' in body and "rcpNo=r2" in body  # 우리 종목이 아니면 DART 원문으로
    assert "따라 사고팔라는 뜻이 아니에요" in body
    from hanjang import holders
    assert holders.who("국민연금공단") == "nps" and holders.who("홍길동") is None


def test_donut_by_industry():
    d = web.donut(["반도체", "반도체", "화학", None])
    assert "4</span>" in d and "반도체" in d and "50%" in d and "기타" in d and "25%" in d
    assert web.donut([]) == ""

    assert web.sector("264") == "전자·반도체" and web.sector("64992") == "금융" and web.sector("7150") == "지주회사" and web.sector(None) is None


def test_demo_browse_without_email_is_read_only(monkeypatch):
    app, con = _app()
    monkeypatch.setattr(web, "env", lambda: {})
    assert call(app, "/demo")[0].startswith("404")  # 꺼져 있으면 없다
    monkeypatch.setattr(web, "env", lambda: {"DEMO": "1"})
    s, h, _ = call(app, "/demo")
    ck = h["Set-Cookie"].split(";")[0]
    assert s.startswith("303") and "삼성전자" in call(app, "/", cookie=ck)[2]  # 닉네임 화면 없이 바로
    assert "보기만" in call(app, "/add", "POST", "q=005930", ck)[2]  # 바꾸는 것은 막는다
    assert "로그인 없이 둘러보기" in call(app, "/")[2]


def test_mark_uses_group_color_not_logo():
    assert "#1428A0" in web.mark("삼성전자") and ">삼성<" in web.mark("삼성전자")
    assert ">SK<" in web.mark("SK하이닉스") and ">KB<" in web.mark("KB금융")
    assert web.mark("유한양행") == web.mark("유한양행") and ">유<" in web.mark("유한양행")  # 그 밖의 회사는 이름마다 같은 색


def test_daily_failure_mails_the_operator(monkeypatch):
    from hanjang import daily, sources

    sent = []
    monkeypatch.setattr(sources, "env", lambda: {"SMTP_USER": "op@x.kr"})
    monkeypatch.setattr(mail, "send", lambda to, subject, text, html="": sent.append((to, subject, text)))
    try:
        raise RuntimeError("database is locked")
    except RuntimeError as err:
        daily.alert(err)
    assert sent[0][0] == "op@x.kr" and "RuntimeError" in sent[0][1] and "database is locked" in sent[0][2]


def test_invite_link_tags_trial_users_and_report_counts_weeks(capsys):
    """초대 링크 /?c=trial-1 → 로그인 링크에 묶음이 따라가 가입 때 cohort 가 된다. 판정은 자기 종목 노트를 연 사람만 센다."""
    from datetime import date

    from hanjang import trial

    app, con = _app()
    assert 'name="c" value="trial-1"' in call(app, "/?c=trial-1")[2]
    assert 'name="c"' not in call(app, "/?c=<x>")[2]  # 이상한 이름은 버린다
    call(app, "/login", "POST", "email=a%40b.c&agree=1&c=trial-1")  # 처음 — 바로 시작하며 묶인다
    call(app, "/auth?t=" + quote(web.login_token("a@b.c", SECRET, 1_000_000.0)) + "&c=trial-2")  # 처음 묶음 그대로
    assert con.execute("select cohort from users where email = 'a@b.c'").fetchone() == ("trial-1",)

    con.execute("update users set created_at = '2026-11-17T09:00' where email = 'a@b.c'")
    (u,) = con.execute("select id from users where email = 'a@b.c'").fetchone()
    con.execute("insert into holdings values (?, '005930', '2026-11-17')", (u,))
    con.executemany("insert into views (user_id, page, ticker, at) values (?, ?, ?, ?)",
                    [(u, "note", "005930", "2026-11-18T10:00"), (u, "note", "005930", "2026-11-19T10:00"),
                     (u, "cards", None, "2026-11-25T10:00")])  # 2주째는 카드만 — 안 센다  # fmt: skip
    con.execute("insert into feedback (user_id, ticker, week, helpful, would_pay, at) values (?, '005930', '2026-12-22', 4, 3000, '2026-12-23')", (u,))
    people, pay, rows = trial.weekly(con, "trial-1", date(2026, 12, 7))
    assert (people, pay) == (1, 1) and [n for _, _, n in rows] == [1, 0, 0, 0]  # 11/16 주부터 4주째(12/7~)까지
    assert trial.verdict(people, pay, rows).startswith("접음")  # 3주째 0명
    assert trial.verdict(20, 5, [(6, date(2026, 12, 22), 11)]).startswith("계속")
    assert trial.verdict(20, 4, [(6, date(2026, 12, 22), 11)]).startswith("그 사이")



def test_calendar_merges_same_day_same_kind_and_shows_market_events():
    from datetime import date

    from hanjang import sources

    app, con = _app()
    _login(app)
    call(app, "/add", "POST", "q=" + quote("삼성전자"), _login(app))
    collect.save_disclosures(con, [sources.Disclosure("20261021000001", "005930", date(2026, 10, 21), "단일판매ㆍ공급계약체결"),
                                   sources.Disclosure("20261021000002", "005930", date(2026, 10, 21), "단일판매ㆍ공급계약체결")])
    con.execute("update disclosures set code='MAJOR_CONTRACT', importance=3, direction=1")
    (uid,) = con.execute("select id from users").fetchone()
    html_ = app.calendar(uid, "2026-10", today=date(2026, 10, 9))
    assert html_.count("외 1건") == 2 and "계약 2건" in html_  # 두 건이 한 줄로 (고른 날 일정 · 이 달의 일정에 한 번씩)
    assert "한국 금리 결정" in html_ and "미국 금리 결정" in html_ and "관련 높은 순" in html_ and "🇰🇷" not in html_
    assert html_.index("외 1건") < html_.index("한국 금리 결정</h3>")  # 내 종목 공시가 시장 일정보다 위
    con.execute("insert into ipos values ('c1', 'r9', '엘리스그룹', '2026-10-07', '2026-10-08', '2026-10-13', '2026-10-16', 70400, 156428800000, '미래에셋증권', '시설자금 1,549억원')")
    html_ = app.calendar(uid, "2026-10", today=date(2026, 10, 9))
    assert html_.count("엘리스그룹 공모주 청약</span>") == 1 and "엘리스그룹 공모주 상장" in html_  # 청약 첫날 · 상장일
    assert "새로 상장하려는 회사가 주식을 팔아 돈을 모아요.</p>" in html_ and "70,400원" not in html_  # 한 줄, 숫자 없이
    assert html_.index("외 1건") < html_.index("한국 금리 결정</h3>") < html_.index("공모주 청약</h3>")
    assert "line-clamp-2" not in html_  # 칸 안 칩은 한 줄
    assert sources.macro_events("2026-11-01", "2026-11-30")[0] == ("2026-11-03", "물가", "KR", "한국 소비자물가 발표")


def test_money_blocks_and_use_ring():
    h = web.money_blocks((2025, 1000, 200, -50, 400, 600))
    assert "100원 팔면" in h and "20원" in h and "적자" in h and "부채비율 150%" in h
    assert web.money_blocks((2025, None, 8, 5, 60, 737)) == ""  # 금융사(매출 없음)는 그리지 않는다
    d = web.dividend_block([(2025, 100, 250, 25.0)], (2025, 1000, 300, 1000, 1, 1))
    assert "배당으로 나눠 줌" in d and "25%" in d and "회사에 남김" in d
    assert "배당으로 나눠 줌" not in web.dividend_block([(2024, 100, 250, 25.0)], (2025, 1000, 300, 1000, 1, 1))  # 해가 다르면 도넛 없음


def test_soften_parentheses():
    h = web.soften("영업이익이 늘었어요(9.0조원 · 7,921억원)(영업이익률 8.8%). 끝")
    assert h.count("<span") == 1 and "(9.0조원 · 7,921억원 · 영업이익률 8.8%)" in h and "text-outline" in h
    assert web.soften("괄호 없음") == "괄호 없음"

def test_any_listed_stock_can_be_added_and_waits_for_tomorrow():
    """코스닥 등 노트가 아직 없는 상장사도 담긴다 — 카드는 「내일 아침」, 검색 목록(/stocks.js)엔 상장사 전체."""
    app, con = _app()
    collect.save_universe(con, [("005930", "삼성전자")], {}, [("247540", "에코프로비엠"), ("005930", "삼성전자")])
    assert dict(con.execute("select ticker, active from stocks")) == {"005930": 1, "247540": 0}
    ck = _login(app)
    call(app, "/add", "POST", "q=" + quote("에코프로 비엠"), ck)
    assert con.execute("select ticker from holdings order by ticker").fetchall()[-1] == ("247540",)
    assert "첫 노트" in call(app, "/", cookie=ck)[2]  # 바로 받기가 끝났거나(실패) 만드는 중
    js = call(app, "/stocks.js")[2]
    assert js.index("삼성전자") < js.index("에코프로비엠") and "/stocks.js?v=2-1" in call(app, "/", cookie=ck)[2]


def test_repeated_numbers_and_paragraphs():
    seen: set = set()
    a = web.sentence({"text": "매출이 줄었어요(9.0조원 · 7,921억원).", "refs": ["F1"]}, seen)
    b = web.sentence({"text": "본업으로 남긴 돈도 줄었어요(9.0조원 · 7,921억원).", "refs": ["F2"]}, seen)
    assert "9.0조원" in a and "9.0조원" not in b and b.startswith("본업으로 남긴 돈도 줄었어요.")
    h = web.paras([{"text": "많이 팔았어요.", "refs": ["F1"]}, {"text": "남겼어요.", "refs": ["F5"]},
                   {"text": "빚이 적어요.", "refs": ["F3"]}], set())
    assert h.count("<p") == 2  # 실적 한 문단 · 살림 한 문단


def test_returns_watch_and_cite_tone():
    d = web.dividend_block([(2025, 100, 10**12, 25.0)], None, [("2026-08-01", 3 * 10**12)])
    assert "자사주 사기로 한 돈 · 1번" in d and "3.0조원" in d and "2025년 배당" in d
    assert "자사주" not in web.dividend_block([(2025, 100, 10**12, 25.0)], None, [])
    fins = [(2025, 1000, 88, 50, 400, 503), (2024, 1000, 97, 50, 400, 400)]
    h = web.risk_block({"risks": ["수급 불균형에 따른 가격 변동 위험", "차입금 금리 위험", "환율 위험"]}, fins)
    assert "영업이익률 8.8% (2025년 · 2024년 9.7%)" in h and "부채비율 125.8%" in h and h.count("살펴볼 숫자:") == 2
    assert web.risk_block({"risks": ["가격 위험", "수요 위험"]}, fins).count("살펴볼 숫자:") == 1  # 같은 숫자는 한 번만
    h = web.risk_block({"risks": ["발주 계획에 따라 달라짐"]}, fins)
    assert "매출 1,000원 (2025년 · 전년보다 +0.0%)" in h and "「살펴볼 숫자」는" in h
    assert "「살펴볼 숫자」는" not in web.risk_block({"risks": ["환율 위험"]}, fins)
    assert "text-outline/70" in web.sentence({"text": "기사", "refs": ["N1"]}) and "text-primary/70" in web.sentence({"text": "재무", "refs": ["F1"]})


def test_rates_article_measures_from_bank_of_korea_series():
    from hanjang import learn, sources
    app, con = _app()
    ck = _login(app)
    assert "자료를 아직 받지 않았어요" in call(app, "/learn/rates", cookie=ck)[2]  # 자료가 없으면 고정 글
    base = {"기준금리": 3.0, "국고채 3년": 4.0, "국고채 10년": 4.5, "회사채 AA-": 4.7, "회사채 BBB-": 10.5}
    for sid, n in sources.RATES.items():
        con.executemany("insert into macro values (?, ?, ?)", [(sid, f"{2001 + i // 12}-{i % 12 + 1:02d}-01", base[n] + (3 if n == "회사채 BBB-" and i == 5 else 0))
                                                              for i in range(150)])
    a = learn.rates(con)
    assert a["month"] == "2013-06-01" and "가장 크게 벌어졌던 때는 2001년 6월로 **9.5%p**" in a["body"][1] and "**0달**" in a["body"][2]
    html_ = call(app, "/learn/rates", cookie=ck)[2]
    assert "금리 흐름" in html_ and "자료: 한국은행 ECOS" in html_ and html_.count("<polyline") == 5

def test_metrics_compares_last_year_and_this_year():
    h = web.metrics([(2025, 4_600, 2_100, 0, 0, 0), (2024, 4_590, 1_339, 0, 0, 0)])
    assert "2024년 → 2025년" in h and "+56.8%" in h and h.count("bg-outline-variant") == 2 and h.count("bg-primary") == 2
    assert web.metrics([(2025, 1, 1, 0, 0, 0)]) == ""  # 전년이 없으면 그리지 않는다


def test_calendar_shows_my_companys_bond_on_pay_day():
    from datetime import date
    app, con = _app()
    ck = _login(app)
    call(app, "/add", "POST", "q=" + quote("삼성전자"), ck)
    con.executemany("insert into bonds values ('r1', ?, '005930', '2026-10-21', ?, ?, null, '신한투자증권', ?)",
                    [("1", 50_000_000_000, "2028-10-20", '{"채무상환자금": 50000000000}'), ("2", 100_000_000_000, "2029-10-19", '{"운영자금": 100000000000}')])
    (uid,) = con.execute("select id from users").fetchone()
    html_ = app.calendar(uid, "2026-10", today=date(2026, 10, 9))
    assert html_.count("삼성전자 회사채 1,500억원</span>") == 1  # 두 회차가 칩 하나로
    assert "<p class=\"font-body-compact text-body-compact text-on-surface-variant leading-relaxed\">회사가 채권을 팔아 돈을 빌려요.</p>" in html_  # 한 줄, 숫자 없이 (사용자 10/9)
    assert '<a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=r1"' in html_ and 'noopener"><article' not in html_  # 카드는 글자 — 출처 줄만 원문 링크


def test_adding_a_stock_without_note_starts_first_note_now(monkeypatch):
    import threading
    app, con = _app()
    con.execute("insert or ignore into stocks (ticker, name, active) values ('036620', '감성코퍼레이션', 0)")
    con.commit()
    started, gate = [], threading.Event()
    monkeypatch.setattr(web, "FIRST", lambda t: (started.append(t), gate.wait(2)))
    ck = _login(app)
    call(app, "/add", "POST", "q=036620", ck)
    assert started == ["036620"] and "036620" in app.making
    assert "첫 노트를 만들고 있어요" in call(app, "/", cookie=ck)[2]
    call(app, "/add", "POST", "q=036620", ck)  # 이미 만드는 중이면 한 번만
    assert started == ["036620"]
    gate.set()


def test_money_blocks_finance_and_industry_usual():
    fin = (2025, 1000, 70, 50, 135, 1368)
    h = web.money_blocks(fin, {"금융": True})
    assert "금융회사는 잣대가 달라요" in h and "부채비율 1" not in h and "ROE 37.0%" in h
    h = web.money_blocks((2025, 1000, 30, 20, 400, 600), {"백원당": 3.2, "부채비율": 180.0, "업종": "무역·도매", "곳수": 4})
    assert "보통(중간값): 영업이익 3원" in h and "원래 조금씩 남겨요" in h and "보통(중간값)은 180%" in h


def test_high_debt_sector_shows_reason():
    h = web.money_blocks((2025, 1000, 70, 50, 100, 446), {"업종": "방위산업", "곳수": 1, "빚이유": "수주 대금을 미리 받아요"})
    assert "부채비율 446%" in h and "방위산업 업종은 수주 대금을 미리 받아요." in h


def test_feed_and_article_show_the_same_photo():
    app, con = _app()
    con.execute("insert into articles (ref, ticker, date, kind, body, made_at) values ('r1', '005930', '2026-10-01', 'RIGHTS_ISSUE', ?, 'x')",
                (json.dumps({"title": "새 주식", "paragraphs": [{"text": "돈을 모아요.", "refs": []}], "links": {}}, ensure_ascii=False),))
    con.commit()
    (aid,) = con.execute("select id from articles").fetchone()
    ck = _login(app)
    call(app, "/feed", cookie=ck)
    (photo,) = con.execute("select photo from articles where id = ?", (aid,)).fetchone()
    assert photo and re.search(r"/(money|chart)\d*\.jpg$", photo)  # 증자 → 돈·차트 주제
    assert photo in call(app, f"/a/{aid}", cookie=ck)[2]
