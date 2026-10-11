import re
"""3주차 화면 — 로그인 링크 서명, 종목 담기, 노트 열기와 기록, 글자 탈출. 서버를 띄우지 않고 WSGI 를 직접 부른다."""

import io
from datetime import date, datetime, timedelta
import json
from urllib.parse import quote, unquote

from hanjang import collect, db, learn, mail, notes, web

SECRET = "test-secret"


def _app(now=1_000_000.0):
    con = db.connect(":memory:")
    # 테스트가 표에 바로 넣는 사람(닉네임 있음)은 이용 규칙에 동의한 것으로 — 동의 관문 자체는 닉네임 테스트가 본다
    con.execute("create trigger agreed after insert on users when new.nickname is not null begin update users set rules_at = 'x' where id = new.id; end")
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
    call(app, "/welcome", "POST", "nickname=" + quote(nick + "닉") + "&rules=1", ck)  # 가입할 때 닉네임 + 이용 규칙 동의
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
    assert "<span class='lg:hidden'>삼성</span><span class='hidden lg:inline'>삼성전자</span> 자사주</span>" in html_ and "오늘</span>" in html_
    assert 'target="_blank" rel="noopener" title=' not in html_  # 칸 안 칩은 원문 링크가 아니다 — 누르면 그날 일정 (사용자 10/10)
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


def test_login_needs_consent_and_a_mailed_link(capsys):
    app, _ = _app()
    s, _, body = call(app, "/login", "POST", "email=a%40b.c")
    assert "동의해야" in body and "[메일" not in capsys.readouterr().err  # 동의 없이는 메일을 보내지 않는다
    s, h, body = call(app, "/login", "POST", "email=a%40b.c&agree=1")
    assert s.startswith("200") and "Set-Cookie" not in h and "[메일" in capsys.readouterr().err  # 처음 온 사람도 링크로만
    _login(app)  # 닉네임까지 만든 계정도
    s, h, _ = call(app, "/login", "POST", "email=me%40x.kr&agree=1")
    assert s.startswith("200") and "Set-Cookie" not in h and "[메일" in capsys.readouterr().err  # 이메일만 알아서는 못 들어간다
    s, _, _ = call(app, "/login", "POST", "email=me%40x.kr&agree=1")  # 1분 안에 또
    assert s.startswith("429") and "[메일" not in capsys.readouterr().err


def test_login_help_page_is_public():
    app, _ = _app()
    assert 'href="/help/login"' in call(app, "/")[2]
    s, _, body = call(app, "/help/login")
    assert s.startswith("200") and "15분" in body and "비밀번호가 없어요" in body


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
    assert "많이 읽은 노트" in body and "님이 리그램" not in body  # 팔로우 전 — 리그램은 안 보이고 조회수 순 노트
    body = call(app, "/me", cookie=me)[2]
    assert "추천 프로필" in body and "반도체공부" in body and "리그램 1개" not in body  # 활발한 사람은 추천 프로필로, 이유 글은 없이 (사용자 10/10)
    call(app, "/follow", "POST", "u=2", me)
    _, _, body = call(app, "/feed", cookie=me)
    assert "반도체공부" in body and "삼성전자" in body and "you@b.c" not in body and "많이 읽은 노트" not in body
    assert "추천 프로필" not in call(app, "/me", cookie=me)[2]  # 이미 팔로우한 사람은 추천하지 않는다
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
    assert "이용 규칙에 동의해야" in call(app, "/welcome", "POST", "nickname=" + quote("새사람"), ck)[2]  # 동의 없이는 안 된다
    assert call(app, "/welcome", "POST", "nickname=" + quote("새사람") + "&rules=1", ck)[1]["Location"] == "/"
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


def test_industry_bars():
    d = web.bars(["반도체", "반도체", "화학", None], [1, 1, 1, 1], "곳")
    assert "width:50.00%" in d and ">반도체</span>" in d and ">50%</span>" in d and ">기타</span>" in d and ">25%</span>" in d and "2곳</span>" in d
    assert web.bars([], []) == ""

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
    call(app, "/auth?t=" + quote(web.login_token("a@b.c", SECRET, 1_000_000.0)) + "&c=trial-1")  # 처음 — 링크로 들어오며 묶인다
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
    assert js.index("삼성전자") < js.index("에코프로비엠") and re.search(r"/stocks\.js\?v=[0-9a-f]{10}\"", call(app, "/", cookie=ck)[2])  # 주소의 v 는 목록 내용의 지문 — 내용이 바뀌면 브라우저가 새로 받는다


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


def test_regram_cards_note_like_my_stock_and_article_like_feed_row():
    app, con = _app()
    con.execute("insert into articles (ref, ticker, date, kind, body, made_at) values ('r9', '005930', '2026-10-01', 'BUYBACK', ?, 'x')",
                (json.dumps({"title": "자사주 산다", "paragraphs": [{"text": "회사가 주식을 사요.", "refs": []}], "links": {}}, ensure_ascii=False),))
    con.commit()
    (aid,) = con.execute("select id from articles where ref = 'r9'").fetchone()
    ck = _login(app)
    call(app, "/me/profile", "POST", "nickname=" + quote("리그램왕"), ck)
    assert "/regram" in call(app, f"/a/{aid}", cookie=ck)[2]
    call(app, "/regram", "POST", f"k=article&r={aid}&w=", ck)
    me = call(app, "/me", cookie=ck)[2]
    assert "자사주 산다" in me and "max-w-[180px]" in me and "lg:w-full" not in me.split("내 리그램")[1]


def test_follow_notice_and_lists():
    app, con = _app()
    con.execute("insert into users (id, email, created_at, nickname) values (1, 'a@b.c', '2026-10-01', '가가'), (2, 'b@b.c', '2026-10-01', '나나')")
    con.commit()
    a, b, aid, bid = f"s={web.sign('1', SECRET)}", f"s={web.sign('2', SECRET)}", 1, 2
    assert "알림 1개" not in call(app, "/", cookie=a)[2]
    call(app, "/follow", "POST", f"u={aid}&back=" + quote(f"/f/{aid}?tab=followers"), b)
    assert "알림 1개" in call(app, "/", cookie=a)[2]  # 위쪽 알림 단추에 빨간 숫자
    n = call(app, "/me/notices", cookie=a)[2]
    assert "나나" in n and "회원님을 팔로우하기 시작했어요" in n and "팔로우</button>" in n  # 맞팔로우 단추
    assert "알림 1개" not in call(app, "/", cookie=a)[2]  # 열어 보면 사라진다
    f = call(app, f"/f/{aid}?tab=followers", cookie=a)[2]
    assert "팔로워 1명" in f and "팔로잉 0명" in f and "나나" in f
    assert "가가" in call(app, f"/f/{bid}?tab=following", cookie=a)[2]


def test_industry_chip_icon():
    assert "settings" in web.industry_chip("29") and ">기계<" in web.industry_chip("29")
    assert web.industry_chip(None) == ""


def test_follow_back_must_be_our_path():
    app, con = _app()
    con.execute("insert into users (id, email, created_at, nickname) values (1, 'a@b.c', '2026-10-01', '가가'), (2, 'b@b.c', '2026-10-01', '나나')")
    con.commit()
    b = f"s={web.sign('2', SECRET)}"
    assert call(app, "/follow", "POST", "u=1&back=" + quote("/\\evil.example"), b)[1]["Location"] == "/u/1"
    assert call(app, "/follow", "POST", "u=1&back=" + quote("/f/1?tab=followers"), b)[1]["Location"] == "/f/1?tab=followers"


def test_installable_app_pieces_are_public(monkeypatch):
    app, _ = _app()
    s, h, body = call(app, "/manifest.webmanifest")  # 로그인 없이
    m = json.loads(body)
    assert s.startswith("200") and m["display"] == "standalone" and {i["sizes"] for i in m["icons"]} >= {"192x192", "512x512"}
    assert all(call_raw(app, i["src"])[0].startswith("200") for i in m["icons"])
    assert "/offline" in call(app, "/sw.js")[2] and "연결이 끊겼어요" in call(app, "/offline")[2]
    assert 'rel="manifest"' in call(app, "/")[2]
    assert call(app, "/.well-known/assetlinks.json")[0].startswith("404")  # 지문을 넣기 전엔 닫혀 있다
    monkeypatch.setattr(web, "env", lambda: {"TWA_PACKAGE": "kr.hanjang.app", "TWA_SHA256": "AA:BB"})
    s, _, body = call(app, "/.well-known/assetlinks.json")
    assert json.loads(body)[0]["target"] == {"namespace": "android_app", "package_name": "kr.hanjang.app", "sha256_cert_fingerprints": ["AA:BB"]}


def test_learn_related_tips():
    from hanjang import learn

    assert all(x in learn.BY_SLUG for v in learn.RELATED.values() for x in v)  # 잇는 글은 모두 있는 글
    app, con = _app()
    ck = _login(app)
    body = call(app, "/learn/dividend", cookie=ck)[2]
    assert "함께 읽으면 좋은 팁" in body and 'href="/learn/disclosure"' in body


def test_prebuilt_css_has_every_class():
    """화면 CSS 는 미리 만든 파일이다 — 클래스를 새로 쓰고 다시 만들지 않으면 그 모양이 사라진다.
    실패하면: npx tailwindcss@3.4.17 -c tailwind.config.js -o hanjang/static/app.css --minify"""
    from pathlib import Path

    css = (web.STATIC / "app.css").read_text(encoding="utf-8")
    not_tailwind = {"material-symbols-outlined", "pb-safe", "pt-safe", "shadow-xs"}  # 구글 글꼴 · 머리의 <style> · 시안에 있지만 Tailwind 3 에 없는 것(CDN 때도 없었다)
    toks = {t for f in Path(web.__file__).parent.glob("*.py")
            for m in re.finditer(r'class="([^"{}\']*)"', f.read_text(encoding="utf-8")) for t in m.group(1).split()}
    sel = lambda t: "." + re.sub(r"[^a-zA-Z0-9_-]", lambda c: "\\2c " if c.group() == "," else "\\" + c.group(), t)  # Tailwind 의 이름 적기
    missing = sorted(t for t in toks - not_tailwind if sel(t) not in css)
    assert len(toks) > 300 and not missing, missing
    assert "cdn.tailwindcss.com" not in call(_app()[0], "/")[2]


def test_learn_story_box():
    from hanjang import learn

    for slug, paras in learn.STORY.items():  # 이야기에도 권유·예측 말은 없다 · 핵심 한 줄 + 사례 1~2개
        assert slug in learn.BY_SLUG and 2 <= len(paras) <= 3, slug
        assert not any(notes.FORBIDDEN.search(x.replace("**", "")) for x in paras), slug
    app, con = _app()
    ck = _login(app)
    body = call(app, "/learn/stock-bond", cookie=ck)[2]
    assert "이야기로 보면" not in body and "실리콘밸리은행" in body  # 소제목 없이 본문으로 이어진다


def test_learn_figures():
    from hanjang import learn

    for slug, f in learn.FIGURE.items():  # 그림도 있는 글에만 · 권유·예측 말 없이
        assert slug in learn.BY_SLUG and f["type"] in ("flow", "compare", "equation", "cards", "ladder", "timeline", "bars", "lines", "stack"), slug
        words = " ".join(str(x) for x in [f["title"], f.get("note", ""), *(f.get(k) or [] for k in ("steps", "rows", "cols", "items", "points", "parts"))])
        assert not notes.FORBIDDEN.search(words), slug
    app, con = _app()
    ck = _login(app)
    body = call(app, "/learn/start", cookie=ck)[2]
    assert "주식을 처음 사기까지" in body and "이틀 뒤 내 것으로 확정" in body
    assert "PER" in web.figure(learn.FIGURE["ratios"]) and "<polyline" in web.figure(learn.FIGURE["inverse-leverage"])
    assert len({f["type"] for f in learn.FIGURE.values()}) >= 8  # 여러 모양 (사용자 10/10: 다 똑같다)
    for f in learn.FIGURE.values():
        assert web.figure(f).startswith("<figure"), f["type"]


def test_book_author_photo(tmp_path):
    from hanjang import web
    face, credit = web.book_face("book-graham")
    assert "/static/people/graham.jpg" in face and "Public domain" in credit
    assert web.book_face("book-lynch") == ("", "")  # 자유 이용 사진이 없으면 그림 없이
    for key in web.BOOK_FACE.values():
        assert (web.STATIC / "people" / f"{key}.jpg").exists() and key in web.PEOPLE
    app, _ = _app()
    assert call_raw(app, "/static/people/graham.jpg")[1]["Content-Type"] == "image/jpeg"  # 투자자 목록에 없는 지은이도 열린다

def test_private_account_needs_approved_follow():
    app, con = _app()
    con.execute("insert into users (id, email, created_at, nickname) values (1, 'a@b.c', '2026-10-01', '가가'), (2, 'b@b.c', '2026-10-01', '나나')")
    con.commit()
    a, b = f"s={web.sign('1', SECRET)}", f"s={web.sign('2', SECRET)}"
    call(app, "/me/private", "POST", "", a)
    assert "비공개 계정 끄기" in call(app, "/me/settings", cookie=a)[2]
    p = call(app, "/u/1", cookie=b)[2]
    assert "비공개 계정이에요" in p and 'href="/f/1' not in p
    assert call(app, "/f/1?tab=followers", cookie=b)[1]["Location"] == "/u/1"  # 목록도 못 본다
    call(app, "/follow", "POST", "u=1", b)
    p = call(app, "/u/1", cookie=b)[2]
    assert "요청됨" in p and "비공개 계정이에요" in p and '팔로워 <b class="text-on-surface">0' in p  # 수락 전엔 세지 않는다
    n = call(app, "/me/notices", cookie=a)[2]
    assert "팔로우를 요청했어요" in n and "수락" in n
    call(app, "/follow/answer", "POST", "u=2&yes=1", a)
    p = call(app, "/u/1", cookie=b)[2]
    assert "비공개 계정이에요" not in p and "팔로잉" in p
    call(app, "/follow", "POST", "u=1", b)  # 언팔로우
    call(app, "/follow", "POST", "u=1", b)  # 다시 요청
    call(app, "/follow/answer", "POST", "u=2&yes=0", a)  # 삭제
    assert con.execute("select count(*) from follows").fetchone()[0] == 0
    call(app, "/follow", "POST", "u=1", b)
    call(app, "/me/private", "POST", "", a)  # 비공개를 끄면 기다리던 요청은 수락
    assert con.execute("select ok from follows").fetchone()[0] == 1


def test_slow_mail_does_not_stop_other_pages(monkeypatch):
    """부하 시험(10/10) — 요청은 잠금 하나로 차례대로 처리하는데, 로그인 메일을 보내는 몇 초 동안 사이트 전체가 멈췄다."""
    import threading
    import time

    app, _ = _app()
    sending, done = threading.Event(), threading.Event()
    monkeypatch.setattr(mail, "send", lambda *a, **k: (sending.set(), done.wait(5)))  # 메일 서버가 느리다
    t = threading.Thread(target=lambda: call(app, "/login", "POST", "email=a%40b.c&agree=1"))
    t.start()
    assert sending.wait(5)
    started = time.perf_counter()
    assert call(app, "/privacy")[0].startswith("200")  # 메일을 기다리는 동안에도 다른 화면은 열린다
    assert time.perf_counter() - started < 1
    done.set()
    t.join(5)
    assert not t.is_alive()


def test_notices_this_week():
    """알림 — 팔로우한 사람의 새 리그램 · 내 종목 새 소식이 빨간 점 숫자와 알림 화면에. 이번 주 한장은 2명 이상일 때만."""
    app, con = _app()
    now = (datetime.now().replace(minute=0, second=0, microsecond=0) - timedelta(minutes=30)).isoformat()  # 순위는 정각까지 센다
    con.execute("insert into users (id, email, created_at, nickname) values (1, 'me@b.c', '2026-10-01', '나닉'), (2, 'you@b.c', '2026-10-01', '너닉')")
    con.execute("insert into holdings values (1, '005930', ?)", (now,))
    con.execute("insert into articles (ref, ticker, date, kind, body, made_at) values ('x', '005930', '2026-10-09', 'contract', ?, ?)",
                (json.dumps({"title": "큰 계약을 맺었어요", "paragraphs": [{"text": "a", "refs": []}], "links": {}}), now))
    me, you = f"s={web.sign('1', SECRET)}", f"s={web.sign('2', SECRET)}"
    call(app, "/follow", "POST", "u=2", me)
    call(app, "/regram", "POST", "k=learn&r=start", you)
    assert app.initial(1).unread == 2  # 리그램 1 + 내 종목 소식 1
    body = call(app, "/me/notices", cookie=me)[2]
    assert "너닉</b>님이 리그램했어요" in body and "내 종목 <b>삼성전자</b> 새 소식" in body and "큰 계약을 맺었어요" in body
    assert app.initial(1).unread == 0  # 열면 사라진다
    assert "나닉" in app.suggest(2)  # 활동이 없어도 추천은 비우지 않는다 — 사람이 적은 처음 (사용자 10/10)
    con.execute("insert into users (id, email, created_at) values (3, 'c@b.c', '2026-10-01')")
    con.execute("insert into holdings values (2, '005930', ?)", (now,))
    assert "많이 담은 종목" not in app.this_week()  # 두 사람뿐이면 서로의 종목이 짐작돼서 드러내지 않는다
    con.execute("insert into holdings values (3, '005930', ?)", (now,))
    week = app.this_week()
    assert "많이 담은 종목" in week and "삼성전자" in week and "명이" not in week  # 몇 명인지는 적지 않는다
    assert "NEW" not in week and "올랐어요" in week and "시 업데이트" in week  # 하루 전보다 담은 사람이 늘었다 — NEW 는 쓰지 않는다


def test_health_says_what_is_wrong(tmp_path, monkeypatch):
    import os
    import time

    app, _ = _app()
    monkeypatch.setattr(web.db, "PATH", tmp_path / "hanjang.db")
    (tmp_path / "backup").mkdir()
    s, h, body = call(app, "/health")  # 로그인 없이 · 백업이 없다 = 매일 실행이 안 돌았다
    assert s.startswith("503") and body == "daily" and h["Cache-Control"] == "no-store"
    b = tmp_path / "backup" / "hanjang-20261010.db"
    b.write_bytes(b"x")
    assert call(app, "/health")[2] == "ok"
    os.utime(b, (time.time() - 31 * 3600,) * 2)  # 31시간 전 — 어제 아침 실행이 멈췄다
    assert call(app, "/health")[0].startswith("503")


def test_offsite_backup_is_create_only_and_skipped_without_bucket(tmp_path, monkeypatch):
    import gzip

    from hanjang import backup

    f = tmp_path / "hanjang-20261010.db"
    f.write_bytes(b"db")
    key = tmp_path / "k.json"
    monkeypatch.setattr(backup, "env", lambda: {})
    assert backup.offsite(f, key) is None  # 내 컴퓨터 — 버킷이 없으면 건너뛴다
    key.write_text("{}")
    monkeypatch.setattr(backup, "env", lambda: {"BACKUP_BUCKET": "b"})
    monkeypatch.setattr(backup.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": "tok\n"})())
    sent = {}

    class R:
        def raise_for_status(self): ...

    monkeypatch.setattr(backup.httpx, "post", lambda url, **k: sent.update(url=url, **k) or R())
    assert backup.offsite(f, key).startswith("gs://b/hanjang-20261010-")
    assert sent["params"]["ifGenerationMatch"] == "0" and sent["headers"]["Authorization"] == "Bearer tok"  # 덮어쓰지 않는다
    assert gzip.decompress(sent["content"]) == b"db"


def test_morning_card_on_home(monkeypatch):
    from datetime import timedelta
    from hanjang import llm, morning

    app, con = _app()
    today = date.today()
    lo = morning.since(today).isoformat()
    con.execute("insert into users (id, email, created_at, nickname) values (1, 'a@b.c', '2026-10-01', '가가')")
    con.execute("insert into stocks (ticker, name, corp_code, active) values ('042660', '한화오션', 'x', 1), ('128940', '한미약품', 'y', 1)")
    con.execute("insert into holdings values (1, '042660', '2026-10-01'), (1, '128940', '2026-10-01')")
    con.execute("insert into disclosures (rcept_no, ticker, date, title, code, importance, direction) values"
                " ('1', '042660', ?, '유상증자결정', 'RIGHTS_ISSUE', 3, -1), ('2', '128940', ?, '투자판단관련주요경영사항 (에페 품목허가 승인)', 'OTHER', 2, 0)", (lo, lo))
    con.execute("insert into events values ('042660', ?, 'EARNINGS', '실적 발표', '3')", ((today + timedelta(days=2)).isoformat(),))
    con.commit()
    asked = []
    monkeypatch.setattr(llm, "ask", lambda *a, **k: asked.append(a[2]) or a[3]({"sentence": "에페 주사제가 팔아도 된다는 품목허가를 받았다고 알렸어요."}))
    assert morning.prepare(con, today) == 1 and len(asked) == 1  # 코드 풀이가 있는 유상증자는 AI 를 부르지 않는다
    assert morning.prepare(con, today) == 0 and len(asked) == 1  # 공시마다 한 번
    body = call(app, "/", cookie=f"s={web.sign('1', SECRET)}")[2]
    assert "아침 한 장" in body and ">한화오션</span>" in body and "새 주식을 찍어 팔아" in body and "공시 원문 보기" in body and "품목허가를 받았다고 알렸어요" in body
    assert "실적 발표" in body and "유상증자 공시는 이렇게 읽어요" in body
    try:
        morning.check({"sentence": "매출이 30% 늘 거예요."}, "단일판매공급계약")
        raise AssertionError
    except ValueError:
        pass


def test_personas_seen_by_everyone_with_label():
    """예시 사람들 — 모두에게 보인다(사용자 10/10). 다시 깔아도 겹치지 않고 실제 사용자를 먼저 팔로우하지 않는다."""
    from hanjang import personas
    app, con = _app()
    con.execute("insert into users (id, email, created_at, nickname) values (1, 'me@b.c', '2026-10-01', '나닉')")
    assert personas.seed(con) == len(personas.PEOPLE)
    assert personas.seed(con) == len(personas.PEOPLE)
    demo = con.execute("select id from users where email = ?", (personas.DEMO_EMAIL,)).fetchone()[0]
    first = con.execute("select id from users where email = ?", ("chip" + personas.DOMAIN,)).fetchone()[0]
    me = f"s={web.sign('1', SECRET)}"
    assert "삼성전자" in app.this_week() and "반도체일기" in app.suggest(1)
    body = call(app, f"/u/{first}", cookie=me)[2]
    assert "반도체일기" in body
    assert "반도체일기" in call(app, "/feed?q=" + quote("반도체"), cookie=me)[2]
    assert "님이 리그램" in call(app, "/feed", cookie=f"s={web.sign(str(demo), SECRET)}")[2]
    assert not con.execute("select 1 from follows where follower_id in (select id from users where email like '%' || ?) and followee_id = 1", (personas.DOMAIN,)).fetchone()


def test_save_lists_and_highlighter():
    """저장 — 나만 보는 목록 · 좋아요 목록 · 형광펜(칠하기·다시 불러오기·지우기·남의 것은 못 지움) (사용자 10/10)."""
    app, con = _app()
    con.execute("insert into users (id, email, created_at) values (1, 'me@b.c', '2026-10-01'), (2, 'you@b.c', '2026-10-01')")
    me, you = f"s={web.sign('1', SECRET)}", f"s={web.sign('2', SECRET)}"
    con.execute("update users set nickname = '나닉', rules_at = 'x' where id = 1")
    con.execute("update users set nickname = '너닉', rules_at = 'x' where id = 2")
    assert 'action="/save"' in call(app, "/n/005930", cookie=me)[2]
    call(app, "/save", "POST", "k=note&r=005930&w=2026-10-05", me)
    call(app, "/save", "POST", "k=learn&r=start&w=", me)
    call(app, "/like", "POST", "t=005930&w=2026-10-05", me)
    saved = call(app, "/me/saved", cookie=me)[2]
    assert "내 저장 목록" in saved and "삼성전자" in saved and learn.BY_SLUG["start"]["title"] in saved
    assert "삼성전자" in call(app, "/me/liked", cookie=me)[2]
    assert "아직 저장한 글이 없어요" in call(app, "/me/saved", cookie=you)[2]  # 남의 저장은 안 보인다
    assert "내 저장 목록" in call(app, "/me/settings", cookie=me)[2] and "내 좋아요 목록" in call(app, "/me/settings", cookie=me)[2]
    call(app, "/save", "POST", "k=note&r=005930&w=2026-10-05&undo=1", me)
    assert "삼성전자" not in call(app, "/me/saved", cookie=me)[2]
    assert con.execute("select count(*) from regrams").fetchone()[0] == 0  # 저장은 리그램이 아니다
    # 형광펜
    got = json.loads(call(app, "/hl", "POST", "p=/n/005930&s=3&e=9&c=y&t=" + quote("많이 팔았어요"), me)[2])
    assert got["id"] and json.loads(call(app, "/hl?p=/n/005930", cookie=me)[2]) == [{"id": got["id"], "s": 3, "e": 9, "t": "많이 팔았어요", "c": "y"}]
    assert json.loads(call(app, "/hl?p=/n/005930", cookie=you)[2]) == []  # 남의 형광펜은 안 보인다
    for bad in ("p=/evil&s=1&e=2&c=y&t=a", "p=/n/005930&s=5&e=2&c=y&t=a", "p=/n/005930&s=1&e=2&c=red&t=a", "p=/n/005930&s=1&e=2&c=y&t=" + "a" * 501):
        assert json.loads(call(app, "/hl", "POST", bad, me)[2]) == {}
    call(app, "/hl/del", "POST", f"id={got['id']}", you)
    assert con.execute("select count(*) from highlights").fetchone()[0] == 1  # 남의 것은 못 지운다
    call(app, "/hl/del", "POST", f"id={got['id']}", me)
    assert con.execute("select count(*) from highlights").fetchone()[0] == 0
    assert "selectionchange" in call(app, "/n/005930", cookie=me)[2]  # 형광펜 스크립트가 실린다


def test_share_quote_to_profile():
    """형광펜 띠의 「공유」 — 글에 실제로 있는 문장만 내 프로필(리그램)에 인용구로 (사용자 10/10)."""
    app, con = _app()
    con.execute("insert into users (id, email, created_at, nickname) values (1, 'me@b.c', '2026-10-01', '나닉')")
    me = f"s={web.sign('1', SECRET)}"
    said = lambda form: json.loads(call(app, "/hl/share", "POST", form, me)[2])["msg"]  # noqa: E731
    assert said("p=/n/005930&t=" + quote("많이 팔았어요.")) == "내 프로필에 올렸어요"
    body = call(app, "/me", cookie=me)[2]
    assert "“많이 팔았어요.”" in body and "삼성전자" in body
    assert said("p=/n/005930&t=" + quote("지금 당장 담으세요 여러분")) == "글에 있는 문장만 공유할 수 있어요"  # 제 말은 못 올린다
    assert said("p=/n/005930&t=" + quote("가")) != "내 프로필에 올렸어요" and said("p=/evil&t=" + quote("많이 팔았어요.")) != "내 프로필에 올렸어요"
    first = learn.BY_SLUG["start"]["body"][0].replace("**", "")[:30]
    assert said("p=/learn/start&t=" + quote(first)) == "내 프로필에 올렸어요"
    assert said("p=/n/005930&t=" + quote("매출이 늘었어요.")) == "내 프로필에 올렸어요"  # 같은 글에서 다시 — 바뀐다
    rows = con.execute("select kind, ref, comment from regrams where user_id = 1 order by kind").fetchall()
    assert rows == [("learn", "start", first), ("note", "005930", "매출이 늘었어요.")]


def test_month_list_sorts_and_drops_minor():
    app, con = _app()
    con.execute("insert into users (id, email, created_at, nickname) values (1, 'a@b.c', '2026-10-01', '가가')")
    con.execute("insert into stocks (ticker, name, corp_code, active) values ('000001', '가회사', 'x', 1)")
    con.execute("insert into holdings values (1, '000001', '2026-10-01')")
    con.execute("insert into disclosures (rcept_no, ticker, date, title, code, importance, direction) values"
                " ('1', '000001', '2026-10-02', '유상증자결정', 'RIGHTS_ISSUE', 3, -1), ('2', '000001', '2026-10-20', '단일판매ㆍ공급계약체결', 'MAJOR_CONTRACT', 2, 1),"
                " ('3', '000001', '2026-10-07', '판매·인도 대수 알림 (8-K 2.02)', 'EARNINGS', 2, 0)")
    con.execute("insert into ipos (corp_code, rcept_no, name, sub_start, sub_end) values ('c', '9', '새회사', '2026-10-12', '2026-10-13')")
    con.commit()
    a = f"s={web.sign('1', SECRET)}"
    page = call(app, "/calendar?m=2026-10", cookie=a)[2]
    month = page[page.index('id="month-list"'):]
    assert "유상증자" in month and "판매·인도" not in month  # 보통 공시는 목록에서 빠지고
    assert "이 달 공모주 청약 1곳" in month and "새회사 공모주 청약" not in month  # 공모주는 한 줄로
    assert "판매·인도" in page  # 달력의 그날 일정에는 그대로
    new = call(app, "/calendar?m=2026-10&s=new", cookie=a)[2]
    new = new[new.index('id="month-list"'):]
    assert new.index("단일판매") < new.index("유상증자")  # 최신순
    old = call(app, "/calendar?m=2026-10&s=old", cookie=a)[2]
    old = old[old.index('id="month-list"'):]
    assert old.index("유상증자") < old.index("단일판매")  # 날짜순


def test_article_key_phrases_are_emphasized_without_touching_the_text(monkeypatch):
    from hanjang import articles, llm

    app, con = _app()
    paras = [{"text": "계약금액은 935억 원이에요. <b>장기 계약</b>입니다.", "refs": []}, {"text": "위탁생산(CMO) 계약이에요.", "refs": []}]
    con.execute("insert into articles (ref, ticker, date, kind, body, made_at) values ('r1', '005930', '2026-10-01', 'CONTRACT', ?, 'x')",
                (json.dumps({"title": "계약", "paragraphs": paras, "links": {}}, ensure_ascii=False),))
    con.commit()
    # AI 답: 본문에 없는 말·너무 짧은 말·셋째 것은 버리고, 그대로 있는 말만 받는다
    monkeypatch.setattr(llm, "ask", lambda *a, **k: a[3]({"marks": [["935억 원", "없는 말이에요", "계약", "계약금액은 935억", "장기 계약"], ["위탁생산(CMO)"]]}))
    assert articles.emphasize(con) == 1 and articles.emphasize(con) == 0  # 한 번 붙이면 다시 묻지 않는다
    (body,) = con.execute("select body from articles").fetchone()
    b = json.loads(body)
    assert [p["text"] for p in b["paragraphs"]] == [p["text"] for p in paras]  # 글은 한 글자도 안 바뀐다
    assert [p["marks"] for p in b["paragraphs"]] == [["935억 원", "계약금액은 935억"], ["위탁생산(CMO)"]]
    ck = _login(app)
    page_ = call(app, "/a/1", cookie=ck)[2]
    assert '<strong class="font-semibold text-primary">935억 원</strong>' in page_ and "계약금액은 <strong" in page_  # 겹치면 먼저 고른 것만
    assert '<strong class="font-semibold text-primary">위탁생산(CMO)</strong>' in page_ and "&lt;b&gt;장기 계약&lt;/b&gt;" in page_  # 나머지는 그대로 탈출
    assert "**" not in call(app, "/feed", cookie=ck)[2]
    # 굵게 해도 알려 주는 게 없는 말은 버린다 — 날짜만 · 값 없는 항목 이름 · 주가 움직임 · 긴 숫자 · 앞 문단에서 고른 말 (22편 읽기 10/10)
    texts = ["2026년 10월 2일 영업이익은 2.1조 원이에요. 7%대 하락했어요. 24,480,000,000원이에요.", "영업이익은 2.1조 원이고 부채비율은 48.4%예요."]
    got = articles.pick_marks({"marks": [["2026년 10월 2일", "영업이익", "7%대 하락", "24,480,000,000원", "영업이익은 2.1조 원"], ["영업이익은 2.1조 원", "부채비율", "부채비율은 48.4%"]]}, texts)
    assert got == [["영업이익은 2.1조 원"], ["부채비율은 48.4%"]]


def test_no_article_without_the_filing_text(monkeypatch):
    """원문을 못 받은 채 제목 한 줄로 쓰게 했더니 「자세한 건 공시에」만 되풀이하고 없는 내용을 지어냈다 (22편 읽기 10/10)."""
    from hanjang import articles, llm

    _, con = _app()

    class Dart:
        def doc_text(self, rno):
            raise RuntimeError("없음")

    monkeypatch.setattr(llm, "ask", lambda *a, **k: (_ for _ in ()).throw(AssertionError("AI 를 부르면 안 된다")))
    ev = {"ref": "r", "ticker": "005930", "date": "2026-10-07", "kind": "MAJOR_CONTRACT", "fact": {"id": "E1", "text": "x", "url": "u", "tone": 0, "slots": {}}}
    assert articles.write(con, ev, date(2026, 10, 10), Dart()) is None


def test_old_articles_are_rewritten_in_place_when_the_filing_text_is_back(monkeypatch):
    """옛 규칙으로 쓴 기사는 매일 실행이 같은 번호로 다시 쓴다 — 원문을 못 받는 날(DART 점검)엔 그대로 두고 다음 날 다시 (10/10)."""
    from hanjang import articles

    _, con = _app()
    con.execute("insert into disclosures (rcept_no, ticker, date, title, code, importance, direction) values ('r1', '005930', '2026-09-01', '단일판매ㆍ공급계약체결', 'MAJOR_CONTRACT', 2, 1)")
    old = {"title": "옛 글", "paragraphs": [{"text": "자세한 건 공시에 적혀 있어요.", "refs": ["E1"], "marks": []}], "links": {}}
    con.execute("insert into articles (id, ref, ticker, date, kind, body, made_at, photo) values (7, 'r1', '005930', '2026-09-01', 'MAJOR_CONTRACT', ?, 'x', 'p.jpg')",
                (json.dumps(old, ensure_ascii=False),))
    con.commit()
    today = date(2026, 10, 12)  # 사건은 14일보다 오래됐어도 다시 쓴다
    body = lambda: json.loads(con.execute("select body from articles where id = 7").fetchone()[0])  # noqa: E731
    monkeypatch.setattr(articles.llm, "ask", lambda *a, **k: None)  # AI 글이 검사를 못 넘는다
    monkeypatch.setattr(articles, "fetch", lambda *a: "")  # 점검 중 — 원문 없음: 세지 않는다
    assert articles.rewrite(con, today, None) == 0 and body()["title"] == "옛 글" and "tries" not in body()
    monkeypatch.setattr(articles, "fetch", lambda *a: "원문 " * 100)
    assert articles.rewrite(con, today, None) == 0 and body()["tries"] == 1 and "v" not in body()  # 원문은 받았는데 검사 탈락 — 하루
    new = {"title": "새 글", "paragraphs": [{"text": "계약금액은 935억 원이에요.", "refs": ["E1"]}], "links": {}, "v": articles.VERSION}
    seen = []
    monkeypatch.setattr(articles, "write", lambda con, ev, *a, **k: seen.append(ev["fact"]["text"]) or new)
    assert articles.rewrite(con, today, None) == 1 and "단일판매" in seen[0]
    assert con.execute("select id, photo, json_extract(body, '$.title') from articles").fetchall() == [(7, "p.jpg", "새 글")]  # 번호·사진 그대로
    assert articles.rewrite(con, today, None) == 0 and len(seen) == 1  # 한 번 다시 쓰면 끝
    # 사흘 내리 검사를 못 넘으면 그만둔다 — 옛 글로 확정하고 더 묻지 않는다(돈이 새지 않게)
    con.execute("update articles set body = ? where id = 7", (json.dumps(old, ensure_ascii=False),))
    monkeypatch.setattr(articles, "write", lambda *a, **k: seen.append("또") and None)
    for day in range(articles.MAX_TRIES + 2):
        articles.rewrite(con, today, None)
    assert seen.count("또") == articles.MAX_TRIES and body()["kept"] and body()["title"] == "옛 글"


def test_judging_sentences_are_cut_and_a_yardstick_makes_it_a_fact():
    """평가는 기준과 함께만 — 「업종 중간값보다 낮은 편」은 사실, 「탄탄한 편」「낮은 편」은 평가 (22편 읽기 10/11)."""
    from hanjang import articles

    assert not articles.judging("부채비율은 28.7%로, 같은 업종 회사들 중간값보다 낮은 편이에요.") and not articles.judging("같은 업종 회사들 중에서도 높은 편이라고.")
    assert articles.judging("부채비율은 17.8%로 낮은 편이고, 자기 돈은 6,903억 원이에요.") and articles.judging("살림살이도 꽤 탄탄한 편이에요.")
    assert articles.judging("이런 수치는 회사의 재무 상태가 견실하다는 걸 보여줍니다.") and not articles.judging("영업이익은 2.1조 원으로 56.8% 증가했어요.")
    _, con = _app()
    paras = [{"text": "살림살이도 꽤 탄탄한 편이에요. 2025년 매출이 12.0조 원이에요.", "refs": ["F1"], "marks": ["꽤 탄탄한 편", "매출이 12.0조 원"]},
             {"text": "이런 수치는 좋은 실적을 보여줍니다.", "refs": ["F1"]}, {"text": "계약 상대는 삼성전기예요.", "refs": ["E1"]}]
    con.execute("insert into articles (id, ref, ticker, date, kind, body, made_at) values (1, 'r', '005930', '2026-10-01', 'MA', ?, 'x')",
                (json.dumps({"title": "t", "paragraphs": paras, "links": {}}, ensure_ascii=False),))
    assert articles.scrub(con) == 2 and articles.scrub(con) == 0  # 여러 번 돌려도 같다
    got = json.loads(con.execute("select body from articles").fetchone()[0])["paragraphs"]
    assert got == [{"text": "2025년 매출이 12.0조 원이에요.", "refs": ["F1"], "marks": ["매출이 12.0조 원"]}, paras[2]]  # 문장만 빠지고, 빈 문단·걸린 강조도


def test_parent_buying_its_subsidiarys_new_shares_is_one_article():
    """자회사 유상증자결정 + 모회사 타법인 주식 취득결정 — 같은 날 같은 일. 기사는 취득 쪽 한 편 (한화오션 3·4번, 10/11)."""
    from hanjang import articles

    _, con = _app()
    con.executemany("insert into disclosures (rcept_no, ticker, date, title, code, importance, direction) values (?, '005930', ?, ?, ?, 2, 0)",
                    [("m", "2026-10-07", "타법인주식및출자증권취득결정", "MA"), ("r", "2026-10-07", "유상증자결정(종속회사의주요경영사항)", "RIGHTS_ISSUE"),
                     ("own", "2026-10-05", "유상증자결정", "RIGHTS_ISSUE")])  # 회사 자신의 증자는 따로 쓴다
    assert sorted(x["ref"] for x in articles.events(con, date(2026, 10, 10))) == ["m", "own"]
    con.execute("insert into articles (ref, ticker, date, kind, body, made_at) values ('m', '005930', '2026-10-07', 'MA', '{}', 'x')")
    assert [x["ref"] for x in articles.events(con, date(2026, 10, 10))] == ["own"]  # 취득 기사를 이미 썼어도 자회사 증자 쪽을 또 쓰지 않는다


def test_daily_keeps_going_when_dart_is_down_and_finishes_later(tmp_path, monkeypatch):
    """DART 주말 점검(10/10·10/11)에 매일 실행이 통째로 멈췄다 — 쉬는 날엔 DART 가 필요한 일만 건너뛰고, 오후에 돌아오면 마저 한다."""
    import pytest

    from hanjang import daily

    ran, up, mails = [], [False], []
    monkeypatch.setattr(daily, "STATE", tmp_path / "daily.json")
    monkeypatch.setattr(daily.sources.Dart, "up", lambda self: up[0])
    monkeypatch.setattr(daily.sources, "env", lambda: {"SMTP_USER": "op@x.kr", "OPEN_DART_API_KEY": "k", "OPEN_DART_BASE_URL": "https://x"})
    monkeypatch.setattr(daily.mail, "send", lambda to, subject, *a, **k: mails.append(subject))
    monkeypatch.setattr(daily.backup, "backup", lambda today: ran.append("백업") or tmp_path)
    monkeypatch.setattr(daily.backup, "offsite", lambda p: None)
    # 국내 받기·미국 받기는 따로 띄운 파이썬에서 돈다(메모리) — 여기선 무엇을 띄우려 했는지만 본다
    monkeypatch.setattr(daily, "apart", lambda code: ran.append(f"받기:{'True' in code}" if "collect.main" in code else "미국"))
    monkeypatch.setattr(daily.notes, "main", lambda t, today, only_changed, read, carry=False, batch=False: ran.append(f"노트:전부={not only_changed}:읽기={read}"))
    monkeypatch.setattr(daily.us, "read", lambda today: (_ for _ in ()).throw(RuntimeError("SEC 오류")))  # 한 단계가 실패해도
    for mod, name in ((daily.etf, "ETF"), (daily.articles, "기사"), (daily.holders, "큰손"), (daily.gurus, "유명"), (daily.nps, "국민연금")):
        monkeypatch.setattr(mod, "main", lambda today, name=name: ran.append(name))
    monkeypatch.setattr(daily.morning, "prepare", lambda con, today: ran.append("아침") or 0)
    monkeypatch.setattr(daily, "notify", lambda con, week: ran.append("안내 메일") or 3)
    monkeypatch.setattr(daily.db, "connect", lambda: None)  # 진짜 DB 를 열지 않는다
    monkeypatch.setattr(daily.db, "tidy", lambda con, today: {})
    monday = date(2026, 10, 12)

    with pytest.raises(SystemExit, match="미국 읽기"):  # 실패한 단계가 있으면 끝에 실패로 — 그래도 뒤 단계는 다 돌았다
        daily.main(monday)
    assert ran == ["백업", "받기:False", "미국", "노트:전부=False:읽기=False", "기사", "아침", "유명", "국민연금"]  # ETF·큰손·안내 메일은 없다
    assert any("DART 점검" in m for m in mails) and any("미국 읽기 실패" in m for m in mails)

    monkeypatch.setattr(daily.us, "read", lambda today: ran.append("미국 읽기"))
    ran.clear(), mails.clear()
    daily.main(monday)  # 13시 — 아침에 실패한 단계가 있었으니 DART 가 아직 쉬어도 다시 돈다
    assert "미국 읽기" in ran and "ETF" not in ran and not any("DART 점검" in m for m in mails)  # 점검 메일은 하루 한 번
    ran.clear()
    daily.main(monday)  # 다시 — 더 할 일이 없다
    assert ran == []

    up[0] = True
    daily.main(monday)  # 19시 — DART 가 돌아왔다: 받기·ETF·큰손까지, 월요일이라 노트 전부와 안내 메일도
    assert ran == ["백업", "받기:True", "미국", "미국 읽기", "노트:전부=True:읽기=True", "ETF", "기사", "아침", "큰손", "유명", "국민연금", "안내 메일"]
    ran.clear()
    daily.main(monday)  # 끝까지 돈 날은 다시 불러도 아무것도 안 한다 (메일도 한 번만)
    assert ran == []


def test_login_mail_is_capped_per_address_and_overall(monkeypatch):
    """이메일을 바꿔 가며 요청하면 주소별 제한을 피해 남의 메일함에 뿌리고 발송 한도를 다 쓸 수 있었다 (보안 점검 10/11)."""
    app, _ = _app()
    sent = []
    monkeypatch.setattr(mail, "send", lambda to, *a, **k: sent.append(to))

    def ask(i, ip):
        env = {"REQUEST_METHOD": "POST", "PATH_INFO": "/login", "QUERY_STRING": "", "HTTP_COOKIE": "", "CONTENT_TYPE": "application/x-www-form-urlencoded",
               "HTTP_X_FORWARDED_FOR": f"9.9.9.9, {ip}"}  # 앞의 것은 보낸 쪽이 지어낼 수 있다 — 마지막 값만 믿는다
        body = f"email=u{i}%40x.kr&agree=1".encode()
        got = {}
        b"".join(app(env | {"CONTENT_LENGTH": str(len(body)), "wsgi.input": io.BytesIO(body)}, lambda s, h: got.update(status=s, headers=dict(h))))
        return got

    assert [ask(i, "1.1.1.1")["status"][:3] for i in range(web.LOGIN_IP_HOURLY + 2)] == ["200"] * web.LOGIN_IP_HOURLY + ["429"] * 2
    assert len(sent) == web.LOGIN_IP_HOURLY and ask(99, "2.2.2.2")["status"].startswith("200")  # 다른 곳에서는 된다
    for i in range(200, 200 + web.LOGIN_ALL_HOURLY):
        ask(i, f"3.3.{i // 250}.{i % 250}")
    assert len(sent) == web.LOGIN_ALL_HOURLY and ask(999, "4.4.4.4")["status"].startswith("429")  # 전체 한도
    h = ask(1000, "5.5.5.5")["headers"]
    assert "form-action 'self'" in h["Content-Security-Policy"] and "frame-ancestors 'none'" in h["Content-Security-Policy"]


def test_login_with_six_digit_code_from_the_mail(monkeypatch):
    """앱(웹뷰)·홈 화면에 추가한 한장에서는 메일의 링크가 다른 브라우저로 열린다 — 메일의 6자리 코드를 화면에 넣어 들어온다 (앱 출시 준비 10/11)."""
    app, _ = _app()
    mails = []
    monkeypatch.setattr(mail, "send", lambda to, subject, text, *a, **k: mails.append((to, subject, text)))
    body = call(app, "/login", "POST", "email=a%40b.c&agree=1")[2]
    assert 'action="/login/code"' in body and 'name="code"' in body
    code = mails[0][1].split()[-1]
    assert re.fullmatch(r"\d{6}", code) and code in mails[0][2] and "/auth?t=" in mails[0][2]  # 링크와 코드 둘 다
    wrong = "000000" if code != "000000" else "111111"
    s, h, body = call(app, "/login/code", "POST", f"email=a%40b.c&code={wrong}")
    assert s.startswith("200") and "Set-Cookie" not in h and "맞지 않아요" in body and "4번 남음" in body
    s, h, _ = call(app, "/login/code", "POST", f"email=a%40b.c&code={code}")
    assert s.startswith("303") and "s=" in h["Set-Cookie"]
    assert "만료" in call(app, "/login/code", "POST", f"email=a%40b.c&code={code}")[2]  # 한 번만 쓴다
    assert "만료" in call(app, "/login/code", "POST", "email=x%40b.c&code=123456")[2]  # 받은 적 없는 주소

    app, _ = _app()  # 다섯 번 틀리면 그 코드는 버린다 — 맞는 코드도 더는 안 된다
    mails.clear()
    call(app, "/login", "POST", "email=a%40b.c&agree=1")
    code = mails[0][1].split()[-1]
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(web.CODE_TRIES):
        last = call(app, "/login/code", "POST", f"email=a%40b.c&code={wrong}")[2]
    assert "여러 번 틀렸어요" in last and "Set-Cookie" not in call(app, "/login/code", "POST", f"email=a%40b.c&code={code}")[1]

    app, _ = _app(now=1_000_000.0)  # 15분이 지나면 만료
    mails.clear()
    call(app, "/login", "POST", "email=a%40b.c&agree=1")
    app.clock = lambda: 1_000_000.0 + web.LINK_TTL + 1
    assert "만료" in call(app, "/login/code", "POST", f"email=a%40b.c&code={mails[0][1].split()[-1]}")[2]


def test_report_block_rules_and_ban(monkeypatch):
    """앱 마켓이 남에게 보이는 프로필(사용자 콘텐츠)이 있는 앱에 요구하는 것 — 이용 규칙 동의 · 금지 말 거르기 · 신고 · 차단 · 계정 막기 (10/11)."""
    from hanjang import moderate

    app, con = _app()
    mails = []
    monkeypatch.setattr(mail, "send", lambda to, subject, text, *a, **k: mails.append((subject, text)))
    monkeypatch.setattr(web, "env", lambda: {"SMTP_USER": "op@x.kr", "PRIVACY_CONTACT": "help@x.kr"})
    con.execute("insert into users (id, email, created_at, nickname, bio) values (1, 'a@b.c', '2026-10-01', '가가', '소개'), (2, 'b@b.c', '2026-10-01', '나나', null), (3, 'c@b.c', '2026-10-01', '다다', null)")
    con.commit()
    a, b, c = (f"s={web.sign(str(i), SECRET)}" for i in (1, 2, 3))
    assert "올리면 안 되는 것" in call(app, "/rules")[2] and "help@x.kr" in call(app, "/rules")[2]  # 로그인 없이 · 연락처
    # 금지 말 — 닉네임·자기소개
    assert "msg=" in call(app, "/me/profile", "POST", "nickname=" + quote("리딩방장") + "&bio=", a)[1]["Location"]
    assert "msg=" in call(app, "/me/profile", "POST", "nickname=" + quote("가가") + "&bio=" + quote("문의 open.kakao.com/o/x"), a)[1]["Location"]
    # 신고 — 한 건으로 적히고 운영자에게 메일
    p = call(app, "/u/1", cookie=b)[2]
    assert 'action="/report"' in p and 'action="/block"' in p and 'action="/report"' not in call(app, "/u/1", cookie=a)[2]  # 내 프로필엔 없다
    assert "24시간" in call(app, "/report", "POST", "u=1&why=" + quote("사칭·남의 사진"), b)[2]
    call(app, "/report", "POST", "u=1&why=x", b)
    assert con.execute("select user_id, target_id, why from reports").fetchall() == [(2, 1, "사칭·남의 사진")] and len(mails) == 1
    assert "사칭" in mails[0][0] and "moderate wipe 1" in mails[0][1] and "가가" in mails[0][1]
    # 차단 — 서로 팔로우가 풀리고, 서로 안 보이고, 다시 팔로우도 안 된다. 풀면 돌아온다
    call(app, "/follow", "POST", "u=1", b), call(app, "/follow", "POST", "u=2", a)
    call(app, "/block", "POST", "u=1", b)
    assert con.execute("select count(*) from follows").fetchone() == (0,)
    assert call(app, "/u/2", cookie=a)[0].startswith("404") and "차단 풀기" in call(app, "/u/1", cookie=b)[2]  # 당한 쪽엔 없는 사람, 한 쪽엔 풀기
    call(app, "/follow", "POST", "u=2", a)
    assert con.execute("select count(*) from follows").fetchone() == (0,)
    assert "가가" not in call(app, "/feed?q=" + quote("가"), cookie=b)[2] and "가가" in call(app, "/feed?q=" + quote("가"), cookie=c)[2]  # 사람 찾기
    assert "차단한 사람" in call(app, "/me/settings", cookie=b)[2] and "차단한 사람" not in call(app, "/me/settings", cookie=a)[2]
    call(app, "/block", "POST", "u=1", b)
    assert call(app, "/u/2", cookie=a)[0].startswith("200")
    # 운영자 처리 — 프로필 지우기: 닉네임부터 다시(규칙 동의도), 신고는 닫힌다. 막기: 쿠키가 있어도 못 쓴다
    assert [r[0] for r in moderate.pending(con)] == [1]
    moderate.act(con, "wipe", 1)
    assert moderate.pending(con) == [] and "닉네임을 정해 주세요" in call(app, "/", cookie=a)[2] and call(app, "/u/1", cookie=c)[0].startswith("404")
    moderate.act(con, "ban", 1)
    s, h, body = call(app, "/", cookie=a)
    assert s.startswith("403") and "Max-Age=0" in h["Set-Cookie"] and "help@x.kr" in body
    # 탈퇴하면 차단·신고 기록도 지운다
    call(app, "/block", "POST", "u=3", b), call(app, "/report", "POST", "u=3&why=" + quote("기타"), b)
    call(app, "/me/delete", "POST", "", b)
    assert con.execute("select (select count(*) from blocks) + (select count(*) from reports)").fetchone() == (0,)


def test_my_tree_grows_with_days_and_shows_this_month():
    from hanjang import tree

    assert tree.stage(0) == ("씨앗", 1) and tree.stage(3) == ("새싹", 1) and tree.stage(50) == ("잎이 풍성한 나무", 40) and tree.stage(200)[1] is None
    assert all(tree.svg(n).startswith("<svg") for n in (0, 2, 8, 60, 120))
    assert tree.svg(40) == tree.svg(40)  # 같은 날수면 같은 나무
    app, con = _app()
    con.execute("insert into users (id, email, created_at, nickname) values (1, 'a@b.c', '2026-10-01', '가가')")
    con.executemany("insert into views (user_id, page, at) values (1, 'cards', ?)", [(f"2026-09-{d:02d}T08:00:00",) for d in range(1, 21)])
    con.commit()
    body = call(app, "/me", cookie=f"s={web.sign('1', SECRET)}")[2]
    assert con.execute("select days from users where id = 1").fetchone()[0] == 21  # 남은 기록 20일 + 오늘
    con.execute("delete from views")  # 열어본 기록이 지워져도(180일) 나무는 줄지 않는다
    con.commit()
    assert "지금까지 21일 들어왔어요" in call(app, "/me", cookie=f"s={web.sign('1', SECRET)}")[2]
    assert "내 나무" in body and "지금까지 21일 들어왔어요" in body and "자라는 나무" in body and "잎이 풍성한 나무까지 19일" in body


def test_login_cookie_expires_on_the_server_and_old_cookies_are_upgraded():
    """쿠키에 날짜가 없어, 한 번 새 나간 쿠키가 영영 통했다 (보안 점검 10/11). 옛 쿠키는 정한 날까지만 받고 그 사이 새 쿠키로 바꿔 준다."""
    now = [1_000_000.0]
    app, con = _app()
    app.clock = lambda: now[0]
    con.execute("insert into users (id, email, created_at, nickname) values (1, 'a@b.c', '2026-10-01', '가가')")
    con.commit()
    new = web.session_cookie(1, SECRET, now[0]).split(";")[0]
    assert "내 종목" in call(app, "/", cookie=new)[2] and "Set-Cookie" not in call(app, "/", cookie=new)[1]
    now[0] += web.SESSION_TTL + 1
    assert "시작하기" in call(app, "/", cookie=new)[2]  # 90일이 지나면 서버가 받지 않는다 — 다시 로그인
    assert "시작하기" in call(app, "/", cookie="s=" + web.sign("1|9999999999999", SECRET).replace("1|", "2|"))[2]  # 번호 바꿔치기

    old = f"s={web.sign('1', SECRET)}"  # 날짜 없는 옛 쿠키
    now[0] = web.LEGACY_UNTIL - 10
    s, h, body = call(app, "/", cookie=old)
    assert "내 종목" in body and web.read_session(h["Set-Cookie"].split(";")[0][2:], SECRET, now[0]) == (1, False)  # 받아 주고, 새 쿠키로 바꿔 준다
    assert "Max-Age=0" in call(app, "/logout", cookie=old)[1]["Set-Cookie"]  # 로그아웃은 그대로 지운다
    now[0] = web.LEGACY_UNTIL + 10
    assert "시작하기" in call(app, "/", cookie=old)[2]  # 정한 날이 지나면 옛 쿠키는 끝


def test_tidy_drops_old_views_and_news_and_hot_queries_use_indexes():
    """DB 점검(10/11) — 지우는 규칙이 백업뿐이었고, 화면이 자주 묻는 조회가 표 전체를 훑었다."""
    _, con = _app()
    con.execute("insert into users (id, email, created_at) values (1, 'a@b.c', '2026-01-01')")
    con.executemany("insert into views (user_id, page, ticker, at) values (1, 'note', '005930', ?)", [("2026-03-01T10:00",), ("2026-10-01T10:00",)])
    con.executemany("insert into news (url, ticker, date, press, title) values (?, '005930', ?, '삼성전자 뉴스룸', 't')", [("u1", "2026-07-01"), ("u2", "2026-10-01")])
    assert db.tidy(con, date(2026, 10, 11)) == {"views": 1, "news": 1}
    assert con.execute("select at from views").fetchall() == [("2026-10-01T10:00",)] and con.execute("select url from news").fetchall() == [("u2",)]
    for q in ("select count(*) from views where page = 'note' and ticker = '005930' and at >= '2026-10-05'", "select count(*) from follows where followee_id = 1 and ok = 1",
              "select * from highlights where user_id = 1 and page = '/n/005930'", "select * from news where ticker = '005930' and date >= '2026-10-01'",
              "select * from disclosures where ticker = '005930' and date >= '2026-07-01'", "select count(*) from regrams where kind = 'note' and ref = '005930' and week = '2026-10-05'",
              "select count(*) from likes where ticker = '005930' and week = '2026-10-05'"):
        plan = " ".join(r[3] for r in con.execute("explain query plan " + q))
        assert "SEARCH" in plan and "SCAN" not in plan, (q, plan)


def test_cached_fragments_refresh_when_another_connection_writes(tmp_path):
    """종목 목록(186KB)·국민연금·유명 투자자 페이지는 매일 실행 뒤에만 바뀐다 — 그때까지 한 번 만든 것을 돌려주고, 다른 연결이 쓰면 새로 만든다 (DB 점검 10/11)."""
    import sqlite3

    path = tmp_path / "h.db"
    con = db.connect(path)
    con.execute("insert into stocks (ticker, name) values ('005930', '삼성전자')")
    con.commit()
    app = web.App(con, SECRET)
    first = app.stocks_js()
    assert "삼성전자" in first and app.stocks_js() is first  # 같은 것을 그대로
    con.execute("insert into views (user_id, page, at) select 1, 'x', 'now' where 0")  # 이 연결의 쓰기(열어본 기록 같은 것)는 캐시와 상관없다
    con.commit()
    assert app.stocks_js() is first
    other = sqlite3.connect(path)  # 매일 실행 — 다른 연결
    other.execute("insert into stocks (ticker, name) values ('000660', 'SK하이닉스')")
    other.commit()
    second = app.stocks_js()
    assert second is not first and "SK하이닉스" in second
    assert db.connect(":memory:").execute("pragma synchronous").fetchone()[0] == 1  # normal — 커밋마다 디스크 확인을 기다리지 않는다


def test_big_bodies_only_for_logged_in_photo_uploads_and_few_at_once():
    """로그인하지 않은 누구든 어느 주소로든 6MB 를 보낼 수 있었다 — 여럿이 한꺼번에 보내면 1GB 서버의 메모리가 찬다 (메모리 점검 10/11)."""
    app, con = _app()
    con.execute("insert into users (id, email, created_at, nickname) values (1, 'a@b.c', '2026-10-01', '가가')")
    con.commit()
    me = web.session_cookie(1, SECRET, 1_000_000.0).split(";")[0]

    def post(path, size, cookie=""):
        read = []

        class Body(io.BytesIO):
            def read(self, n=-1):
                read.append(n)
                return super().read(n)

        env = {"REQUEST_METHOD": "POST", "PATH_INFO": path, "QUERY_STRING": "", "HTTP_COOKIE": cookie, "CONTENT_TYPE": "application/json",
               "CONTENT_LENGTH": str(size), "wsgi.input": Body(b'{"img": "' + b"x" * (size - 11) + b'"}')}
        got = {}
        b"".join(app(env, lambda s, h: got.update(status=s)))
        return got["status"][:3], bool(read)

    assert post("/scan", web.FORM_MAX + 1) == ("413", False)  # 로그인 안 함 — 읽지도 않는다
    assert post("/login", web.FORM_MAX + 1, me) == ("413", False)  # 사진 받는 곳이 아니면 로그인해도
    assert post("/scan", web.BODY_MAX + 1, me) == ("413", False)
    assert post("/scan", web.FORM_MAX + 1, me)[1]  # 로그인한 사람의 캡처는 받는다
    for _ in range(web.BIG_AT_ONCE):  # 큰 본문 자리가 다 찼으면 기다리게 하지 않고 돌려보낸다
        app.uploads.acquire()
    assert post("/scan", web.FORM_MAX + 1, me) == ("503", False)
    for _ in range(web.BIG_AT_ONCE):
        app.uploads.release()
    assert post("/scan", web.FORM_MAX + 1, me)[0] != "503" and app.uploads._value == web.BIG_AT_ONCE  # 끝나면 자리를 돌려준다


def test_inline_scripts_on_main_pages_are_valid_javascript(tmp_path):
    """파이썬 문자열 안의 「\n」 하나가 내 종목 화면 스크립트를 통째로 깨뜨려, 검색 자동완성과 캡처 올리기가 서버에서 멈춰 있었다 (10/11).
    글자만 보는 테스트는 이런 걸 못 잡는다 — 화면의 스크립트를 node 에 넣어 문법을 본다(node 가 없는 곳에선 건너뛴다)."""
    import shutil
    import subprocess

    import pytest

    node = shutil.which("node")
    if not node:
        pytest.skip("node 없음")
    app, con = _app()
    ck = _login(app)
    call(app, "/add", "POST", "q=" + quote("삼성전자"), ck)
    con.execute("insert into users (id, email, created_at, nickname) values (77, 'o@b.c', '2026-10-01', '남남')")
    con.execute("insert into articles (id, ref, ticker, date, kind, body, made_at) values (1, 'r1', '005930', '2026-10-01', 'MAJOR_CONTRACT', ?, 'x')",
                (json.dumps({"title": "계약", "paragraphs": [{"text": "계약금액은 935억 원이에요.", "refs": []}], "links": {}}, ensure_ascii=False),))
    con.commit()
    pages = {"로그인": call(app, "/")[2], "로그인(보냄)": app.login_page("a@b.c"), "닉네임": app.welcome_page()}
    for p in ("/", "/n/005930", "/feed", "/a/1", "/calendar", "/learn", "/learn/dividend", "/me", "/me/settings", "/me/notices", "/u/77", "/privacy", "/rules"):
        s, _, body = call(app, p, cookie=ck)
        assert s.startswith("200"), p
        pages[p] = body
    n = 0
    for name, body in pages.items():
        for k, src in enumerate(re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", body, re.S)):
            f = tmp_path / f"s{n}.js"
            f.write_text(src, encoding="utf-8")
            r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True, encoding="utf-8", errors="replace")
            assert r.returncode == 0, f"{name} 의 {k + 1}번째 스크립트: {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else r.stderr}"
            n += 1
    assert n > 20


def test_others_see_my_tree_unless_private():
    app, con = _app()
    con.execute("insert into users (id, email, created_at, nickname, days) values (1, 'a@b.c', '2026-10-01', '가가', 50), (2, 'b@b.c', '2026-10-01', '나나', 1)")
    con.commit()
    a, b = f"s={web.sign('1', SECRET)}", f"s={web.sign('2', SECRET)}"
    p = call(app, "/u/1", cookie=b)[2]
    assert "가가의 나무" in p and "지금까지 50일 들어왔어요" in p and "최근 석 달" not in p  # 나무와 날 수만 — 잔디는 본인만
    call(app, "/me/private", "POST", "", a)
    assert "가가의 나무" not in call(app, "/u/1", cookie=b)[2]  # 비공개 — 승인 전엔 안 보인다
    call(app, "/follow", "POST", "u=1", b)
    call(app, "/follow/answer", "POST", "u=2&yes=1", a)
    assert "가가의 나무" in call(app, "/u/1", cookie=b)[2]


def test_line_tree_on_notice_error_and_offline_pages():
    from hanjang import tree

    assert "animateTransform" in tree.line("wait") and "animateTransform" not in tree.line("oops")
    app, con = _app()
    con.execute("insert into users (id, email, created_at, nickname) values (1, 'a@b.c', '2026-10-01', '가가')")
    con.commit()
    a = f"s={web.sign('1', SECRET)}"
    s404, _, body = call(app, "/nope", cookie=a)
    assert s404.startswith("404") and 'aria-label="나무"' in body and "없는 화면이에요" in body
    assert 'aria-label="나무"' in call(app, "/offline")[2]
    app.cards = lambda *x, **k: 1 / 0  # 화면을 그리다 터져도
    s500, _, body = call(app, "/", cookie=a)
    assert s500.startswith("500") and "다시 불러오기" in body and "ZeroDivisionError" not in body


def test_my_stock_card_shows_what_happened_to_it():
    """내 종목 카드 — 그 종목의 공시·다가오는 일정·큰손 움직임 가운데 점수가 가장 큰 것을 노트 첫 줄 대신. 남의 종목 일은 안 나온다."""
    from datetime import date, timedelta

    from hanjang import sources

    app, con = _app()
    ck = _login(app)
    call(app, "/add", "POST", "q=" + quote("삼성전자"), ck)
    (uid,) = con.execute("select id from users").fetchone()
    today = date.today()
    assert app.my_events(uid, today) == []
    collect.save_disclosures(con, [sources.Disclosure("20261010000001", "005930", today - timedelta(days=1), "주요사항보고서(자기주식취득결정)"),
                                   sources.Disclosure("20261001000009", "005930", today - timedelta(days=10), "단일판매ㆍ공급계약체결")])  # 열흘 전 — 7일 밖
    con.execute("update disclosures set code='BUYBACK', importance=3, direction=1")
    con.execute("insert into events values ('005930', ?, 'EARNINGS', '실적 발표', 'r1')", ((today + timedelta(days=3)).isoformat(),))
    con.execute("insert into big_holdings (inst, stock_code, corp_name, corp_cls, rate, rate_chg, date, rcept_no) values ('nps', '005930', '삼성전자', 'Y', 7.76, 0.5, ?, 'r2')", ((today - timedelta(days=3)).isoformat(),))
    con.execute("insert into insiders (rcept_no, ticker, date, kind, who, change) values ('r3', '005930', ?, '임원', '상무', -100)", ((today - timedelta(days=2)).isoformat(),))
    con.execute("insert into stocks (ticker, name, corp_code, active) values ('000660', 'SK하이닉스', '9', 1)")
    con.execute("insert into events values ('000660', ?, 'EARNINGS', '남의 종목 실적', 'r4')", ((today + timedelta(days=1)).isoformat(),))
    con.commit()
    heads = [c[5] for c in app.my_events(uid, today)]
    assert [h for h in heads if "공급계약" in h or "남의" in h] == [] and len(heads) == 4
    assert "자기주식취득결정" in heads[0] and heads[1] == "실적 발표" and heads[2] == "국민연금이 지분을 늘렸어요" and heads[3] == "임원 주식 거래 보고 1건"
    home = call(app, "/", cookie=ck)[2]
    assert "자기주식취득결정" in home and "어제 · 소식 3건 더" in home  # 맨 위 것 하나 + 몇 건 더
    assert "오늘의 내 종목" not in call(app, "/feed", cookie=ck)[2]  # 피드에서는 뺐다
    card = home[home.index('data-stock-id="005930"'):]
    assert 'href="/n/005930"><p' in card and 'href="/calendar"' not in card[:card.index("노트 읽기")]  # 글자를 누르면 노트로
    note = call(app, "/n/005930", cookie=ck)[2]
    assert "요즘 생긴 일" in note and "국민연금이 지분을 늘렸어요" in note and "임원 주식 거래 보고 1건" in note and "회사 사정은 어떤가요?" in note  # 맨 위에 그 일들, 아래에 원래 노트


def test_cookie_of_a_deleted_account_goes_to_login_not_error():
    app, con = _app()
    ck = _login(app)
    con.execute("delete from users")
    s, h, _ = call(app, "/feed", cookie=ck)  # 다른 기기에서 탈퇴한 뒤 남은 쿠키
    assert s.startswith("303") and h["Location"] == "/" and "Max-Age=0" in h["Set-Cookie"]


def test_things_found_by_clicking_through_every_screen(monkeypatch):
    """화면을 하나씩 눌러 보며 찾은 것들 (10/11) — 글자만 보는 테스트로는 안 보이던 쓰임새 문제."""
    app, con = _app()
    monkeypatch.setattr(mail, "send", lambda *a, **k: None)
    assert "autofocus" in re.search(r'<input[^>]*name="code"[^>]*>', call(app, "/login", "POST", "email=a%40b.c&agree=1")[2])[0]  # 코드 칸이 화면 아래로 밀려 있었다
    _, h, _ = call(app, "/auth?t=" + quote(web.login_token("new@b.c", SECRET, 1_000_000.0)))
    ck = h["Set-Cookie"].split(";")[0]
    body = call(app, "/welcome", "POST", "nickname=" + quote("리딩방장") + "&rules=1", ck)[2]
    assert "쓸 수 없는 말" in body and re.search(r'name="rules"[^>]* checked', body)  # 오류로 다시 떠도 동의 체크는 그대로
    assert "checked" not in call(app, "/welcome", "POST", "nickname=" + quote("새사람"), ck)[2].split('name="rules"')[1].split(">")[0]
    call(app, "/welcome", "POST", "nickname=" + quote("새사람") + "&rules=1", ck)
    home = call(app, "/", cookie=ck)[2]
    assert "가진 종목을 담아 보세요" in home  # 종목이 없을 때 빈 화면만 보이던 것
    assert re.search(r'<a[^>]*href="/me"[^>]*>.*?새', home, re.S)  # 위쪽 동그라미는 닉네임 첫 글자
    call(app, "/add", "POST", "q=" + quote("삼성전자"), ck)
    assert "가진 종목을 담아 보세요" not in call(app, "/", cookie=ck)[2]
    # 자동완성 — 많이 담긴 종목이 목록 앞에, 그리고 이름이 그 글자로 시작하는 종목 먼저
    con.executemany("insert into stocks (ticker, name) values (?, ?)", [("000001", "가나삼성"), ("000002", "삼성가나")])
    con.commit()
    js = app._stocks_js()
    assert js.index("삼성전자") < js.index("삼성가나") and "all.filter(first)" in home
    # 차단한 사람 화면에 돌아갈 길
    con.execute("insert into users (id, email, created_at, nickname) values (50, 'o@b.c', '2026-10-01', '남남')")
    con.commit()
    call(app, "/block", "POST", "u=50", ck)
    assert "피드로 돌아가기" in call(app, "/u/50", cookie=ck)[2]


def test_morning_brief_mail_only_when_there_is_news(monkeypatch):
    """아침 소식 메일 — 내 종목에 새 공시가 있거나 오늘·내일 일정이 있는 사람에게만 한 통. 끈 사람은 빼고."""
    from datetime import date

    from hanjang import daily, mail, sources

    app, con = _app()
    ck = _login(app)
    call(app, "/add", "POST", "q=" + quote("삼성전자"), ck)
    sent = []
    monkeypatch.setattr(mail, "send", lambda to, subject, text, html="": sent.append((to, subject, text, html)) or True)
    today = date(2026, 10, 14)  # 수요일
    assert daily.brief(con, today) == 0 and not sent  # 새 소식 없음 — 보내지 않는다
    collect.save_disclosures(con, [sources.Disclosure("20261013000001", "005930", date(2026, 10, 13), "주요사항보고서(자기주식취득결정)")])
    con.execute("update disclosures set code='BUYBACK', importance=3, direction=1")
    assert daily.brief(con, today) == 1
    to, subject, text, html = sent[0]
    assert subject == "[한장] 오늘 내 종목 소식 — 삼성전자" and "삼성전자" in text and "안내 메일」을 끄면" in text
    assert "오늘 내 종목 소식" in html and "한장에서 보기" in html and "사고팔라는 뜻이 아니에요" in html
    con.execute("update users set mail_on = 0")
    assert daily.brief(con, today) == 0  # 안내 메일을 끈 사람
    con.execute("update users set mail_on = 1")
    con.execute("delete from disclosures")
    con.execute("insert into events values ('005930', '2026-10-15', 'EARNINGS', '실적 발표', '20261013000001')")
    assert daily.brief(con, today) == 1 and sent[-1][1].startswith("[한장] 곧 있는 내 종목 일정 — 삼성전자 실적 발표")  # 내일 일정
    con.execute("delete from events")
    con.execute("insert into big_holdings (inst, stock_code, corp_name, corp_cls, rate, rate_chg, date, rcept_no) values ('nps', '005930', '삼성전자', 'Y', 7.76, 0.5, '2026-10-13', 'r2')")
    assert daily.brief(con, today) == 1  # 큰손 움직임만 있어도 — 아침 한 장과 메일에 같은 문장
    assert sent[-1][1] == "[한장] 내 종목 큰손 움직임 — 국민연금이 삼성전자 지분을 늘렸어요(지분 7.76%)" and "국민연금이 삼성전자 지분을 늘렸어요" in sent[-1][3]
