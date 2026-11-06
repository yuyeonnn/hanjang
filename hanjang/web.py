"""모바일 웹 (PRD §3·§6) — 표준 라이브러리 WSGI 하나. 사용자 20명이라 프레임워크가 필요 없다.
`uv run python -m hanjang.web` → http://localhost:8000
화면: 로그인 → ② 내 종목 카드 → ③ 기업 노트 · ④ 캘린더. 열 때마다 `views` 한 행 (시험 판정의 원천).
**화면 모양은 Stitch 시안(2026-10-07 둘째 판, docs/design.md)을 그대로 옮겼다** — 클래스·배치·문구를 바꾸지 않는다.
시안의 예시 내용 자리는 전부 실제 데이터로 채운다(사진·그림은 쓸 권리가 없어 회색 빈 칸)."""

import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from datetime import date, datetime
from hanjang import quiz
from urllib.parse import parse_qs, quote, unquote, urlparse

from hanjang import db, mail, notes, sources, tree
from hanjang.auth import check_login, read_session, session_cookie
from hanjang.pwa import MANIFEST, OFFLINE, SW
from hanjang.ui import BIG_AT_ONCE, BIG_POSTS, BODY_MAX, CSP, FORM_MAX, Me, PEOPLE, STATIC, e, page, photo_url
# 테스트·smoke 가 web.X 로 닿는 이름 — 여기서 다시 내보낸다 (화면 코드는 쓰지 않는다)
from hanjang.pages import login, home, calendar as calendar_pages, profile, social, feed, big, learn as learn_pages, insights as insight_pages  # noqa: F401


# 로그인하지 않은 사람도 둘러보기로 보는 화면 — 첫 화면(/)과 공유된 노트 링크 등
GUEST_PAGES = ("/n/", "/feed", "/calendar", "/learn", "/u/", "/a/", "/big")
# 사람이 아닌 것 — 링크 미리보기·검색 로봇·스크립트. 방문 기록에 넣지 않는다
BOTS = re.compile(r"bot|crawl|spider|slurp|preview|scrap|facebookexternalhit|curl|wget|python|node|headless|lighthouse", re.I)


# 둘러보는 손님이 담기·좋아요·프로필처럼 가입이 필요한 것을 누르면 — 쓰던 화면 위를 흐리게 덮고 「가입하고 이용하세요」. 누르면 가입 화면으로
# 담으려던 종목은 가입 화면 주소(?want=)로 넘겨 기억해 둔다. 서버 쪽 막기(route 의 is_demo)는 스크립트가 없을 때를 위해 그대로 둔다
GUEST_GATE = (
    '<div id="guest-gate" style="display:none;position:fixed;inset:0;z-index:90;align-items:center;justify-content:center;padding:24px;cursor:pointer;'
    'background:rgba(255,255,255,.55);backdrop-filter:blur(7px);-webkit-backdrop-filter:blur(7px)" role="dialog" aria-label="가입 안내">'
    '<div style="max-width:320px;width:100%;background:#fff;border-radius:20px;padding:26px 20px 18px;text-align:center;box-shadow:0 12px 40px rgba(21,69,57,.16)">'
    '<p style="font-weight:700;font-size:19px;color:#154539;margin:0">가입하고 이용하세요</p>'
    '<p id="guest-gate-why" style="margin:8px 0 0;font-size:14px;line-height:22px;color:#434944">내 종목을 담으면 공시·재무·소식을 쉬운 글로 매일 읽어 드려요.</p>'
    '<span style="display:block;margin-top:18px;padding:13px;border-radius:12px;background:#154539;color:#fff;font-weight:700;font-size:15px">가입하기</span>'
    '<button type="button" id="guest-gate-close" style="margin-top:12px;font-size:13px;color:#6f7973;background:none;border:0;cursor:pointer">계속 둘러보기</button></div></div>'
    "<script>(function(){var g=document.getElementById('guest-gate'),to='/login',why='';"
    "function t(k,p,v){try{navigator.sendBeacon('/t?k='+k+'&p='+encodeURIComponent(p||'')+'&v='+encodeURIComponent(v||''))}catch(e){}}"
    "function show(p,want){why=p||'';to='/login?'+(want?'want='+encodeURIComponent(want):'from='+encodeURIComponent(p||''));"
    "if(want)document.getElementById('guest-gate-why').textContent='가입하면 「'+want+'」부터 바로 담아 드려요.';g.style.display='flex';why=want?'담기 '+want:(why||'');t('gate_show',why);}"
    "g.addEventListener('click',function(ev){if(ev.target.id==='guest-gate-close'){g.style.display='none';t('gate_close',why);return;}location.href=to;});"
    "document.addEventListener('submit',function(ev){var f=ev.target;if((f.getAttribute('method')||'').toLowerCase()!=='post')return;"
    "ev.preventDefault();ev.stopPropagation();var q=f.querySelector('[name=q]');show(f.getAttribute('action'),q&&q.value.trim());},true);"
    "document.addEventListener('click',function(ev){var a=ev.target.closest&&ev.target.closest('a[href^=\"/me\"],label');"
    "if(!a||(a.tagName==='LABEL'&&!a.querySelector('input[type=file]')))return;ev.preventDefault();ev.stopPropagation();show(a.getAttribute('href')||'/scan');},true);"
    "var f0=window.fetch;window.fetch=function(u,o){if(o&&String(o.method||'').toUpperCase()==='POST'){show(String(u));return new Promise(function(){});}return f0.apply(this,arguments);};"
    "})();</script>")


class App(login.LoginPages, home.HomePages, calendar_pages.CalendarPages, profile.ProfilePages, social.SocialPages, feed.FeedPages, big.BigPages, learn_pages.LearnPages, insight_pages.InsightPages):
    def __init__(self, con: sqlite3.Connection, secret: str, clock=time.time) -> None:
        self.con, self.secret, self.clock = con, secret, clock
        # 요청은 한 번에 하나씩 — DB 연결 하나를 돌려 쓴다. 화면 하나가 수 ms 라 이 규모에선 이게 가장 빠르고 공평하다
        # (부하 시험 10/10: 실마다 연결을 열면 초당 250건 → 60건, 느린 요청 16초). 대신 메일·AI 처럼 느린 바깥 일 동안엔 잠금을 놓는다(outside)
        self.turn = threading.Lock()
        self.local = threading.local()
        self.making: set[str] = set()  # 지금 첫 노트를 만드는 종목 (담자마자 바로 받기)
        self.making_lock = threading.Lock()  # 화면 서버는 여러 실에서 돈다 — 같은 종목을 두 번 받지 않게
        self.uploads = threading.Semaphore(BIG_AT_ONCE)
        self.memo: dict = {}  # cached() — 매일 실행 뒤에만 바뀌는 큰 조각(종목 목록 186KB · 국민연금·유명 투자자 페이지)
        self.scans: dict[int, list[float]] = {}  # ponytail: 캡처 읽기 시각 — 메모리에. 여러 대면 DB 로

    def cached(self, name: str, build):
        """매일 실행(다른 연결)이 쓰기 전까지는 한 번 만든 것을 돌려준다 — `pragma data_version` 은 다른 연결이 커밋할 때마다 바뀐다.
        이 연결이 직접 쓰는 표(열어본 기록·좋아요·팔로우…)는 여기 넣는 조각과 상관없다. 버전이 바뀌면 통째로 비운다 (DB 점검 10/11)."""
        v = self.con.execute("pragma data_version").fetchone()[0]
        if self.memo.get("v") != v:
            self.memo = {"v": v}
        if name not in self.memo:
            self.memo[name] = build()
        return self.memo[name]

    @contextmanager
    def outside(self):
        """느린 바깥 일(로그인 메일·AI 사진 읽기, 수 초) 동안 잠금을 놓아 다른 사람의 화면이 돌게 한다.
        이 안에서는 DB 를 쓰지 않는다 — 연결을 다른 요청이 쓰고 있다."""
        held = getattr(self.local, "held", False)
        if held:
            self.turn.release()
        try:
            yield
        finally:
            if held:
                self.turn.acquire()

    def __call__(self, environ, start_response):
        method, path = environ["REQUEST_METHOD"], environ.get("PATH_INFO", "/")
        cookie = dict(c.strip().split("=", 1) for c in environ.get("HTTP_COOKIE", "").split(";") if "=" in c)
        uid, renew = read_session(cookie.get("s", ""), self.secret, self.clock())
        n = int(environ.get("CONTENT_LENGTH") or 0) if method == "POST" else 0
        # 본문을 읽기 전에 거른다 — 전에는 로그인하지 않은 누구든 어느 주소로든 6MB 를 보낼 수 있었고, 여럿이 한꺼번에 보내면 메모리가 찼다
        if n > (BODY_MAX if uid and path in BIG_POSTS else FORM_MAX):
            start_response("413 Payload Too Large", [("Content-Type", "text/plain; charset=utf-8")])
            return ["사진이 너무 커요".encode()]
        big = n > FORM_MAX
        if big and not self.uploads.acquire(blocking=False):
            start_response("503 Service Unavailable", [("Content-Type", "application/json; charset=utf-8"), ("Retry-After", "5")])
            return [json.dumps({"msg": "지금 사진을 읽는 사람이 많아요. 잠시 뒤에 다시 해 주세요."}, ensure_ascii=False).encode()]
        try:
            return self.respond(environ, start_response, method, path, n, cookie, uid, renew)
        except Exception:  # 무엇이 잘못됐든 사용자는 「다시 불러오기」를 본다. 까닭은 서버 기록에 (journalctl -u hanjang-web)
            traceback.print_exc()
            try:
                self.con.rollback()
            except sqlite3.Error:
                pass
            body = page("문제가 생겼어요", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen",
                        '<main class="w-full max-w-[480px] mx-auto px-margin pt-14 flex flex-col items-center text-center">'
                        f'<div class="mt-12">{tree.line("oops")}</div><p class="mt-space-md font-body-reading text-body-reading">앗, 뭔가 문제가 있는 것 같아요!</p>'
                        '<button class="mt-space-lg px-5 py-3 rounded-lg bg-primary text-on-primary font-body-reading-strong text-body-compact" onclick="location.reload()" type="button">다시 불러오기</button></main>')  # fmt: skip
            start_response("500 Internal Server Error", [("Content-Type", "text/html; charset=utf-8")])
            return [body.encode()]
        finally:
            if big:
                self.uploads.release()

    def respond(self, environ, start_response, method, path, n, cookie, uid, renew):
        form = {}
        if method == "POST":
            raw = environ["wsgi.input"].read(n).decode()
            if environ.get("CONTENT_TYPE", "").startswith("application/json"):
                form = {"_json": json.loads(raw or "{}")}
            else:
                form = {k: v[0] for k, v in parse_qs(raw).items()}
            del raw
        query = {k: v[0] for k, v in parse_qs(environ.get("QUERY_STRING", "")).items()}
        self.local.ip = (environ.get("HTTP_X_FORWARDED_FOR") or environ.get("REMOTE_ADDR") or "").split(",")[-1].strip()  # 앞의 Caddy 가 붙여 준 마지막 값이 실제 접속 주소
        self.local.cookie = cookie
        old = cookie.get("g", "")
        self.local.gid = old if re.fullmatch(r"[0-9a-f]{16}", old) else secrets.token_hex(8)
        self.local.real = "HTTP_X_FORWARDED_FOR" in environ and not BOTS.search(environ.get("HTTP_USER_AGENT", ""))  # 앞의 Caddy 를 거친 사람의 요청만 센다
        guest = False
        with self.turn:
            self.local.held = True
            try:
                # 처음 온 사람은 로그인 화면 대신 둘러보기로 — 써 보고, 담으려 할 때 가입을 받는다. 초대 링크(?c=)는 로그인 화면 그대로
                if uid is None and method == "GET" and (path == "/" or path.startswith(GUEST_PAGES)) and not query.get("c") and sources.env().get("DEMO") == "1":
                    uid, guest = self.demo_uid(), True
                if method == "GET" and (path in ("/", "/login") or path.startswith(GUEST_PAGES)):
                    self.opened(uid, path, query, environ.get("HTTP_REFERER", ""))
                status, headers, body = self.route(method, path, form, query, uid)
            finally:
                self.local.held = False
        # 덮개는 둘러보는 화면에만 — 가입·운영자 화면에 붙으면 그 화면의 입력까지 막는다
        if method == "GET" and (path == "/" or path.startswith(GUEST_PAGES)) and uid is not None and status.startswith("200") and isinstance(body, str) and "</body>" in body and self.is_demo(uid):
            body = body.replace("</body>", GUEST_GATE + "</body>", 1)
        if guest and not any(k == "Set-Cookie" for k, _ in headers):
            headers = [*headers, ("Set-Cookie", session_cookie(uid, self.secret, self.clock(), 86400))]
        if renew and not any(k == "Set-Cookie" for k, _ in headers):  # 옛 쿠키 → 날짜가 든 새 쿠키로 (로그아웃·탈퇴처럼 쿠키를 지우는 응답은 그대로)
            headers = [*headers, ("Set-Cookie", session_cookie(uid, self.secret, self.clock()))]
        if self.local.real and self.local.gid != old:  # 방문을 세는 무작위 번호 — 처음 한 번
            headers = [*headers, ("Set-Cookie", f"g={self.local.gid}; Path=/; HttpOnly; SameSite=Lax; Max-Age=31536000" + ("; Secure" if mail.base_url().startswith("https://") else ""))]
        kind = [] if any(k == "Content-Type" for k, _ in headers) else [("Content-Type", "text/html; charset=utf-8"), ("Content-Security-Policy", CSP)]
        start_response(status, [*kind, ("X-Content-Type-Options", "nosniff"),
                                ("X-Frame-Options", "DENY"), ("Referrer-Policy", "same-origin"), *headers])  # fmt: skip
        return [body if isinstance(body, bytes) else body.encode()]

    def see(self, to: str, *headers) -> tuple:
        return "303 See Other", [("Location", to), *headers], ""

    def track(self, kind: str, uid: int | None = None, path: str | None = None, ref: str | None = None) -> None:
        """손님·가입 기록 한 줄(인사이트). 바깥에서 온 사람의 요청만 — 올린 뒤 확인·테스트·로봇은 적지 않는다. 둘러보기 계정은 손님(uid 없음)으로."""
        if not getattr(self.local, "real", False):
            return
        if uid is not None and self.is_demo(uid):
            uid = None
        try:
            self.con.execute("insert into visits (at, gid, uid, kind, path, ref) values (?, ?, ?, ?, ?, ?)",
                             (datetime.now().isoformat(timespec="seconds"), self.local.gid, uid, kind, path, ref))  # fmt: skip
            if uid is not None and kind in ("signup", "login"):  # 가입 전 손님 기록을 이 사람에게 붙인다
                self.con.execute("update visits set uid = ? where gid = ? and uid is null", (uid, self.local.gid))
            self.con.commit()
        except sqlite3.OperationalError:
            self.con.rollback()

    def opened(self, uid: int | None, path: str, query: dict, referer: str) -> None:
        """이 브라우저가 오늘 처음 들어왔으면 한 줄 — 어디서 왔는지(링크를 누른 곳의 주소 이름 · utm_source · 초대 묶음)와 함께."""
        if not getattr(self.local, "real", False) or self.con.execute(
                "select 1 from visits where gid = ? and kind = 'open' and at >= ?", (self.local.gid, date.today().isoformat())).fetchone():
            return
        host = (urlparse(referer).hostname or "").removeprefix("www.")
        ref = query.get("utm_source") or (f"초대 {query['c']}" if query.get("c") else "")
        if not ref and host and host != urlparse(mail.base_url()).hostname:
            ref = "앱" if host == "com.hanjangapp" else host
        self.track("open", uid, path, ref[:80] or None)

    def log(self, uid: int, page_: str, ticker: str | None = None) -> None:
        try:
            now = datetime.now().isoformat()
            self.con.execute("insert into views (user_id, page, ticker, at) values (?, ?, ?, ?)", (uid, page_, ticker, now))
            # 들어온 날 수 — 하루에 한 번만 더한다. 처음엔 남아 있는 기록의 날 수에서 시작 (내 나무, 10/11)
            self.con.execute("update users set days = coalesce(days, (select count(distinct substr(at, 1, 10)) from views where user_id = ? and substr(at, 1, 10) < ?)) + 1,"
                             " last_day = ? where id = ? and coalesce(last_day, '') != ?", (uid, now[:10], now[:10], uid, now[:10]))  # fmt: skip
            self.con.commit()
        except sqlite3.OperationalError:  # DB 가 잠깐 잠겨도 화면은 보여 준다 — 기록 한 줄을 잃는 쪽이 낫다
            self.con.rollback()

    def initial(self, uid: int) -> str:
        """위쪽 동그라미에 넣을 것 — 사진 주소, 없으면 닉네임 첫 글자(정하기 전이면 이메일 첫 글자)."""
        row = self.con.execute("select coalesce(nickname, email), photo_at, coalesce(notices_seen, '') from users where id = ?", (uid,)).fetchone()
        me = Me((photo_url(uid, row[1]) or row[0][:1]) if row else "?")
        if row:
            regs, arts = self.fresh(uid, row[2])
            me.unread = self.con.execute("select count(*) from follows where followee_id = ? and at > ?", (uid, row[2])).fetchone()[0] + len(regs) + len(arts)
        return me

    def simple(self, title: str, msg: str) -> str:
        art = tree.line("oops" if title == "없음" else "calm")  # 없는 화면엔 걱정스러운 얼굴, 그 밖의 안내엔 웃는 얼굴
        return page(title, "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen",
                    f'<main class="w-full max-w-[480px] lg:max-w-[760px] mx-auto px-margin pt-14 flex flex-col items-center text-center">'
                    f'<div class="mt-12">{art}</div><p class="mt-space-md font-body-reading text-body-reading">{msg}</p></main>')  # fmt: skip

    def route(self, method, path, form, query, uid):
        if path == "/login" and method == "POST":
            return self.login(form.get("email", "").strip().lower(), form.get("agree") == "1", form.get("c", ""))
        if path.startswith("/static/photos/") and re.fullmatch(r"(pool/)?[a-z]+\d*\.jpg", path[15:]) and (STATIC / "photos" / path[15:]).exists():
            return "200 OK", [("Content-Type", "image/jpeg"), ("Cache-Control", "public, max-age=604800")], (STATIC / "photos" / path[15:]).read_bytes()
        if path == "/stocks.js":  # 검색 자동완성 — 상장사 이름·코드는 공개 정보라 로그인 없이
            return "200 OK", [("Content-Type", "text/javascript; charset=utf-8"), ("Cache-Control", "public, max-age=86400")], self.stocks_js()
        if path.startswith("/static/people/") and path[15:-4] in PEOPLE and path.endswith(".jpg") and (STATIC / "people" / path[15:]).exists():
            return "200 OK", [("Content-Type", "image/jpeg"), ("Cache-Control", "public, max-age=604800")], (STATIC / "people" / path[15:]).read_bytes()
        if path == "/static/og.png":  # 링크 미리보기 그림
            return "200 OK", [("Content-Type", "image/png"), ("Cache-Control", "public, max-age=86400")], (STATIC / "og.png").read_bytes()
        if path in ("/static/icon-192.png", "/static/icon-512.png", "/static/icon-maskable.png", "/static/apple-touch-icon.png"):  # 홈 화면 아이콘
            return "200 OK", [("Content-Type", "image/png"), ("Cache-Control", "public, max-age=604800")], (STATIC / path[8:]).read_bytes()
        if re.fullmatch(r"/static/tree(-[a-z]+)?\.(png|webp)", path) and (STATIC / path[8:]).exists():  # 선 나무 그림과 그 버전들
            return "200 OK", [("Content-Type", "image/" + path.rsplit(".", 1)[1]), ("Cache-Control", "public, max-age=604800")], (STATIC / path[8:]).read_bytes()
        if path == "/static/app.css":  # 주소에 내용 지문(?v=)이 붙어 있어 오래 캐시해도 된다
            return "200 OK", [("Content-Type", "text/css; charset=utf-8"), ("Cache-Control", "public, max-age=31536000, immutable")], (STATIC / "app.css").read_bytes()
        if path == "/manifest.webmanifest":  # 「홈 화면에 추가」 · 플레이스토어 포장(TWA)의 재료
            return "200 OK", [("Content-Type", "application/manifest+json"), ("Cache-Control", "public, max-age=86400")], MANIFEST
        if path == "/sw.js":  # 서비스 워커 — 맨 위 주소에 있어야 사이트 전체를 맡는다
            return "200 OK", [("Content-Type", "text/javascript; charset=utf-8"), ("Cache-Control", "no-cache")], SW
        if path == "/health":  # 바깥 감시(구글 클라우드 모니터링)가 5분마다 연다 — 안 되면 운영자 메일
            return self.health()
        if path == "/robots.txt":  # 공개 페이지(로그인·처리방침·계산 방법)만 검색에 — 나머지는 어차피 로그인 화면
            return "200 OK", [("Content-Type", "text/plain; charset=utf-8")], "User-agent: *\nAllow: /\n"
        if path == "/offline":
            return "200 OK", [], OFFLINE
        if path == "/.well-known/assetlinks.json":  # 안드로이드 앱(TWA)이 이 사이트 것임을 증명 — 서명 키 지문을 .env 에 넣으면 열린다
            return self.assetlinks()
        if path == "/login/code" and method == "POST":
            return self.login_code(form.get("email", "").strip().lower(), form.get("code", ""), form.get("c", ""))
        if path == "/t":  # 화면이 보내는 짧은 기록(인사이트) — 정해 둔 종류만. js: 스크립트가 실제로 돈 브라우저(로봇은 대개 안 돈다)
            k = query.get("k", "")
            if k in ("js", "gate_show", "gate_close"):
                if k != "js" or not self.con.execute("select 1 from visits where gid = ? and kind = 'js' and at >= ?",
                                                     (getattr(self.local, "gid", ""), date.today().isoformat())).fetchone():  # fmt: skip
                    self.track(k, None if self.is_demo(uid) else uid, query.get("p", "")[:60] or None, query.get("v", "")[:20] or None)
            return "204 No Content", [("Content-Type", "text/plain")], ""
        if path == "/login" and method == "GET":  # 둘러보다 흐린 덮개를 누르면 — 무엇을 하려다 왔는지 적고, 담으려던 종목은 기억한다
            want = query.get("want", "").strip()[:100]
            if want or query.get("from"):
                self.track("gate", None, f"담기 {want}" if want else query["from"][:60])
            if want:
                return "200 OK", [("Set-Cookie", f"want={quote(want)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400")], self.login_page(note=f"가입하면 「{want}」부터 바로 담아 드려요.")
            return "200 OK", [], self.login_page(cohort=query.get("c", ""))
        if path == "/admin" or path.startswith("/admin/u/"):  # 운영자 인사이트 — ADMIN_EMAILS 계정으로 로그인해 있으면 바로 열린다 (pages/insights.py)
            if uid is None or not self.is_admin(uid):  # 회원 이메일이 보이는 화면 — 다른 사람에겐 있는지도 알리지 않는다
                return "404 Not Found", [], self.simple("없음", "없는 화면이에요. <a class='text-primary underline' href='/'>처음으로</a>")
            if path == "/admin":
                d = query.get("d", "30")
                return "200 OK", [], self.insights(max(1, min(180, int(d))) if d.isdigit() else 30)
            got = self.insight_user(int(path[9:])) if path[9:].isdigit() else None
            return ("200 OK", [], got) if got else ("404 Not Found", [], self.simple("없음", "없는 회원이에요."))
        if path in ("/privacy", "/method", "/help/login", "/rules"):  # 로그인 없이 열린다
            return "200 OK", [], self.doc(path, uid)
        if path == "/auth":
            email = check_login(query.get("t", ""), self.secret, self.clock())
            if not email:
                return "200 OK", [], self.simple("로그인", "링크가 만료됐거나 잘못됐어요. <a class='text-primary underline' href='/'>다시 받기</a>")
            return self.start(email, query.get("c", ""))
        if path == "/demo":  # 둘러보기 — 이메일 없이 공용 계정으로 (메일 보내기 전, 남에게 보여줄 때)
            return self.demo()
        if uid is None:
            return "200 OK", [], self.login_page(cohort=query.get("c", ""))
        # 둘러보기 = 로그인 없이 구경하는 손님. 프로필·설정·알림을 누르거나 무언가 바꾸려 하면(담기·좋아요·팔로우) 로그인 화면으로
        if self.is_demo(uid) and (method == "POST" or path == "/me" or path.startswith("/me/")):
            want = form.get("q", "").strip()[:100] if path == "/add" else ""
            self.track("gate", None, f"담기 {want}" if want else path)
            if want:  # 담으려던 종목은 가입하고 처음 「내 종목」을 열 때 담아 준다 — 가입하고 다시 찾게 하지 않는다
                return "200 OK", [("Set-Cookie", f"want={quote(want)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400")], \
                    self.login_page(note=f"가입하면 「{want}」부터 바로 담아 드려요.")
            return "200 OK", [], self.login_page(note="둘러보는 중이에요. 가입하면 내 종목을 담고 프로필을 쓸 수 있어요.")
        if path == "/logout":
            return self.see("/", ("Set-Cookie", "s=; Path=/; Max-Age=0"))
        # 닉네임은 가입할 때 받는다 — 정하기 전엔 다른 화면으로 못 간다 (사람 찾기·피드에 쓰이니 겹치면 안 된다)
        # 이용 규칙 동의도 여기서 — 남에게 보이는 프로필을 만들기 전에 (이미 닉네임이 있는 사람도 한 번 동의를 받는다)
        me = self.con.execute("select nickname, rules_at, banned from users where id = ?", (uid,)).fetchone()
        if not me:  # 쿠키는 남았는데 계정이 없다(다른 기기에서 탈퇴) — 오류 화면 대신 쿠키를 지우고 처음으로
            return self.see("/", ("Set-Cookie", "s=; Path=/; Max-Age=0"))
        nick, agreed, banned = me
        if banned:  # 운영자가 막은 계정 — 쿠키를 지우고 알린다
            contact = sources.env().get("PRIVACY_CONTACT", "")
            return "403 Forbidden", [("Set-Cookie", "s=; Path=/; Max-Age=0")], self.simple(
                "이용 제한", "이용 규칙을 어겨 이 계정은 쓸 수 없게 됐어요." + (f" 문의: {e(contact)}" if contact else "") + " <a class='text-primary underline' href='/rules'>이용 규칙</a>")
        if not nick or not agreed:
            if path == "/welcome" and method == "POST":
                return self.welcome(uid, form.get("nickname", "").strip(), form.get("rules") == "1")
            return "200 OK", [], self.welcome_page(nick or "")
        if path == "/welcome":
            return self.see("/")
        if path == "/add" and method == "POST":
            return self.add(uid, form.get("q", "").strip())
        if path.startswith("/p/") and path.endswith(".jpg") and path[3:-4].isdigit():  # 프로필 사진 (로그인한 사람만)
            row = self.con.execute("select photo from users where id = ? and photo is not null", (int(path[3:-4]),)).fetchone()
            if not row:
                return "404 Not Found", [], self.simple("없음", "사진이 없어요.")
            return "200 OK", [("Content-Type", "image/jpeg"), ("Cache-Control", "private, max-age=31536000")], bytes(row[0])
        if path == "/me/photo" and method == "POST":
            return self.save_photo(uid, (form.get("_json") or {}).get("img", ""))
        if path == "/me/photo/delete" and method == "POST":
            self.con.execute("update users set photo = null, photo_at = null where id = ?", (uid,))
            self.con.commit()
            return self.see("/me/settings")
        if path == "/scan" and method == "POST":
            return self.scan(uid, (form.get("_json") or {}).get("img", ""))
        if path == "/remove" and method == "POST":
            self.con.execute("delete from holdings where user_id = ? and ticker = ?", (uid, form.get("t")))
            self.con.commit()
            return self.see("/")
        if path == "/":
            want = "" if self.is_demo(uid) else unquote(getattr(self.local, "cookie", {}).get("want", ""))
            if want:  # 둘러보다 담으려던 종목 — 가입하고 처음 여는 「내 종목」에서 담는다
                status, headers, body = self.add(uid, want)
                return status, [*headers, ("Set-Cookie", "want=; Path=/; Max-Age=0")], body
            self.log(uid, "cards")
            return "200 OK", [], self.cards(uid, query.get("msg"), query.get("sort"))
        if path.startswith("/n/"):
            ticker = path[3:]
            self.log(uid, "note", ticker)
            return self.note(uid, ticker, query.get("thanks") == "1")
        if path.startswith("/a/") and path[3:].isdigit():
            self.log(uid, "article", path[3:])
            return self.article(uid, int(path[3:]))
        if path == "/feed":
            self.log(uid, "feed")
            return "200 OK", [], self.feed(uid, query.get("q", "").strip())
        if path.startswith("/u/") and path[3:].isdigit():
            if int(path[3:]) == uid:
                return self.see("/me")
            self.log(uid, "user")
            return self.user_page(uid, int(path[3:]))
        if path in ("/block", "/report") and method == "POST":
            other = int(form["u"]) if form.get("u", "").isdigit() else 0
            if other == uid or not self.con.execute("select 1 from users where id = ?", (other,)).fetchone():
                return self.see("/feed")
            return self.block(uid, other) if path == "/block" else self.report_user(uid, other, form.get("why", ""))
        if path == "/follow" and method == "POST":  # 한 번 더 누르면 언팔로우
            other = int(form["u"]) if form.get("u", "").isdigit() else 0
            if other != uid and other not in self.blocked(uid) and self.con.execute("select 1 from users where id = ? and nickname is not null", (other,)).fetchone():
                if not self.con.execute("delete from follows where follower_id = ? and followee_id = ?", (uid, other)).rowcount:
                    shut = self.con.execute("select private from users where id = ?", (other,)).fetchone()[0]
                    self.con.execute("insert into follows (follower_id, followee_id, at, ok) values (?, ?, ?, ?)", (uid, other, datetime.now().isoformat(), 0 if shut else 1))
                self.con.commit()
            back = form.get("back", "")
            ok = re.fullmatch(r"/[A-Za-z0-9_/?=&%.\-]*", back) and not back.startswith("//")  # 「/\evil.com」 → 「//evil.com」 막기
            return self.see(back if ok else f"/u/{other}" if other else "/feed")
        if path == "/follow/answer" and method == "POST":  # 팔로우 요청 수락(1)·삭제(0)
            other = int(form["u"]) if form.get("u", "").isdigit() else 0
            if form.get("yes") == "1":
                self.con.execute("update follows set ok = 1 where follower_id = ? and followee_id = ?", (other, uid))
            else:
                self.con.execute("delete from follows where follower_id = ? and followee_id = ? and ok = 0", (other, uid))
            self.con.commit()
            return self.see("/me/notices")
        if path == "/regram" and method == "POST":
            return self.regram(uid, form)
        if path == "/save" and method == "POST":
            return self.regram(uid, form, table="saves")
        if path == "/hl/share" and method == "POST":
            return self.share_quote(uid, form.get("p", ""), form.get("t", ""))
        if path in ("/hl", "/hl/del"):
            return self.highlight(uid, method, path, form, query)
        if path in ("/me/saved", "/me/liked"):
            return "200 OK", [], self.kept(uid, path[4:])
        if path == "/me/profile" and method == "POST":
            return self.save_profile(uid, form.get("nickname", "").strip(), form.get("bio", "").strip())
        if path == "/like" and method == "POST":  # 한 번 더 누르면 취소
            t, w = form.get("t", ""), form.get("w", "")
            if self.con.execute("select 1 from notes where ticker = ? and week = ?", (t, w)).fetchone():
                if not self.con.execute("delete from likes where user_id = ? and ticker = ? and week = ?", (uid, t, w)).rowcount:
                    self.con.execute("insert into likes values (?, ?, ?, ?)", (uid, t, w, datetime.now().isoformat()))
                self.con.commit()
            return self.see(f"/n/{quote(t)}")
        if path == "/feedback" and method == "POST":
            return self.feedback(uid, form)
        if path == "/me/private" and method == "POST":  # 비공개 켜기/끄기 — 끄면 기다리던 요청은 모두 수락
            self.con.execute("update users set private = 1 - private where id = ?", (uid,))
            if not self.con.execute("select private from users where id = ?", (uid,)).fetchone()[0]:
                self.con.execute("update follows set ok = 1 where followee_id = ?", (uid,))
            self.con.commit()
            return self.see("/me/settings")
        if path == "/me/mail" and method == "POST":
            self.con.execute("update users set mail_on = 1 - mail_on where id = ?", (uid,))
            self.con.commit()
            return self.see("/me/settings")
        if path == "/me/delete" and method == "POST":
            # 탈퇴 — 이 사용자의 모든 행을 지운다 (되돌릴 수 없음, 화면에서 한 번 더 확인)
            for table, col in (("holdings", "user_id"), ("views", "user_id"), ("feedback", "user_id"), ("likes", "user_id"),
                               ("regrams", "user_id"), ("quiz_done", "user_id"), ("saves", "user_id"), ("highlights", "user_id"), ("follows", "follower_id"), ("follows", "followee_id"),
                               ("blocks", "user_id"), ("blocks", "blocked_id"), ("reports", "user_id"), ("reports", "target_id"), ("users", "id")):  # fmt: skip
                self.con.execute(f"delete from {table} where {col} = ?", (uid,))
            self.con.commit()
            return self.see("/", ("Set-Cookie", "s=; Path=/; Max-Age=0"))
        if path == "/me/notices":
            return self.notices(uid)
        if path.startswith("/f/") and path[3:].isdigit():
            return self.follow_page(uid, int(path[3:]), query.get("tab", "followers"))
        if path == "/me":
            self.log(uid, "me")
            return "200 OK", [], self.profile(uid)
        if path == "/me/settings":
            return "200 OK", [], self.settings(uid, query.get("msg"))
        if path == "/learn/done" and method == "POST":  # 문제를 다 맞혔다 — 도장 한 줄. 글의 세 문제 또는 오늘의 한 문제만
            slug = form.get("slug", "")
            if slug in quiz.QUIZ or slug == f"daily:{date.today().isoformat()}":
                self.con.execute("insert or ignore into quiz_done values (?, ?, ?)", (uid, slug, datetime.now().isoformat()))
                self.con.commit()
            return "200 OK", [("Content-Type", "application/json; charset=utf-8")], "{}"
        if path == "/learn" or path.startswith("/learn/"):
            slug = path[7:]
            self.log(uid, "learn", slug or None)
            return self.learn(uid, slug)
        if path == "/calendar":
            self.log(uid, "calendar")
            return "200 OK", [], self.calendar(uid, query.get("m"), sort=query.get("s"))
        return "404 Not Found", [], self.simple("없음", "없는 화면이에요. <a class='text-primary underline' href='/'>처음으로</a>")

    def src(self, rno: str | None) -> str:
        """원문 주소(notes.source_url) — 화면의 링크라 모르면 「#」."""
        return notes.source_url(self.con, rno) or "#"

    # ---- 큰손 포트폴리오 (읽기 팁 맨 아래) — 기관이 5% 넘게 가진 종목, 전체 상장사 ----

    # 기관 홈페이지 — 로고(Brandfetch)를 찾는 열쇠. 없으면 색 동그라미 (국민연금은 흰 로고라 뺌, 계열사는 그룹 로고가 또렷함)
    BIG_HOME = {"blackrock": "blackrock.com", "capital": "capitalgroup.com", "samsungam": "samsung.com",
                "miraeam": "miraeasset.com", "shinhanam": "shinhangroup.com", "kbam": "kbfg.com",
                "kitm": "kitmc.com", "align": "alignpartners.co.kr", "silchester": "silchester.com", "pzena": "pzena.com"}  # fmt: skip


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # 윈도우 콘솔(cp949)이 「—」를 못 찍어 뒤에서 도는 첫 노트 쓰기가 멈췄다 (10/10)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    from socketserver import ThreadingMixIn
    import wsgiref.simple_server
    from wsgiref.simple_server import WSGIServer, make_server

    wsgiref.simple_server.ServerHandler.server_software = "hanjang"  # 서버 종류·파이썬 판 번호를 응답 머리에 드러내지 않는다

    class Server(ThreadingMixIn, WSGIServer):
        """연결마다 스레드 — 브라우저가 미리 열어 둔 빈 연결 하나에 서버 전체가 멈추지 않게.
        요청 처리는 App 안의 잠금 하나로 차례대로(App.turn) — 메일·AI 를 기다리는 동안만 놓는다."""

        daemon_threads = True
        request_queue_size = 128  # 한꺼번에 몰린 연결을 받아 둘 줄 (기본 5 — 넘치면 연결을 끊는다)

    sys.stderr.reconfigure(encoding="utf-8")  # 윈도우 콘솔(cp949)에서 한글 로그가 깨지지 않게
    cfg = sources.env()
    if len(cfg.get("SECRET", "")) < 32:  # 짧거나 없는 키로는 로그인 링크·쿠키를 위조당한다 — 켜지 않는다
        sys.exit("SECRET 이 없거나 짧아요(32자 이상). 만들기: python -c \"import secrets; print(secrets.token_hex(32))\"")
    db.connect().close()
    app = App(db.connect(threads=True), cfg["SECRET"])  # 표·색인·구조 변경(migrate)도 여기서 — 올린 직후 매일 실행보다 먼저 켜진다
    host, port = cfg.get("HOST", "127.0.0.1"), int(os.environ.get("PORT") or cfg.get("PORT", "8000"))  # 서버에선 127.0.0.1 그대로 두고 앞의 Caddy 가 https 를 맡는다
    print(f"한장 — http://{host}:{port}", file=sys.stderr)
    make_server(host, port, app, server_class=Server).serve_forever()
