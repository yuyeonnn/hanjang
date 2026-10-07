"""모바일 웹 (PRD §3·§6) — 표준 라이브러리 WSGI 하나. 사용자 20명이라 프레임워크가 필요 없다.
`uv run python -m hanjang.web` → http://localhost:8000
화면: 로그인 → ② 내 종목 카드 → ③ 기업 노트 · ④ 캘린더. 열 때마다 `views` 한 행 (시험 판정의 원천)."""

import calendar
import hashlib
import hmac
import html
import json
import re
import sqlite3
import sys
import time
from datetime import date, datetime
from urllib.parse import parse_qs, quote

from hanjang import db, notes
from hanjang.sources import env

MAX_STOCKS = 20  # PRD F2
LINK_TTL = 15 * 60  # 로그인 링크 15분
e = html.escape


# --- 서명: 로그인 링크와 쿠키 (세션 표 없이 — ERD 「안 만든 것」) ---


def sign(value: str, secret: str) -> str:
    return value + "." + hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()[:32]


def unsign(token: str, secret: str) -> str | None:
    value, _, _ = token.rpartition(".")
    return value if value and hmac.compare_digest(sign(value, secret), token) else None


def login_token(email: str, secret: str, now: float) -> str:
    return sign(f"{email}|{int(now) + LINK_TTL}", secret)


def check_login(token: str, secret: str, now: float) -> str | None:
    """링크 → 이메일. 서명이 틀리거나 15분이 지났으면 None."""
    v = unsign(token, secret)
    if not v or "|" not in v:
        return None
    email, _, exp = v.rpartition("|")
    return email if exp.isdigit() and now <= int(exp) else None


# --- 화면 조각 ---

CSS = """
:root{--bg:#faf9f6;--fg:#1d1d1f;--sub:#6b6b70;--line:#e6e4df;--card:#fff;--accent:#2f5d50;--good:#2f6f4f;--bad:#a2412f;--red:#d1352b}
@media (prefers-color-scheme:dark){:root{--bg:#141414;--fg:#ececec;--sub:#a0a0a5;--line:#2c2c2c;--card:#1d1d1d;--accent:#8cc7b3;--good:#8fd0ad;--bad:#e59a87;--red:#ff6b5e}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.7 -apple-system,"Apple SD Gothic Neo","Pretendard","Noto Sans KR",sans-serif;word-break:keep-all}
main{max-width:640px;margin:0 auto;padding:16px 16px 96px}
a{color:var(--accent)}h1{font-size:22px;margin:8px 0}h2{font-size:17px;margin:28px 0 8px}
.sub{color:var(--sub);font-size:13px}.card{display:block;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin:10px 0;text-decoration:none;color:inherit}
.card b{font-size:17px}.row{display:flex;gap:8px;align-items:center}.grow{flex:1}
input,button{font:inherit;padding:10px 12px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--fg)}
button{background:var(--accent);color:var(--bg);border:0}button.ghost{background:none;color:var(--sub);padding:4px 8px}
sup a{font-size:11px;text-decoration:none;margin-left:2px}.lead{font-size:19px;font-weight:700;line-height:1.5}
.box{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
nav{position:fixed;bottom:0;left:0;right:0;display:flex;background:var(--card);border-top:1px solid var(--line)}
nav a{flex:1;text-align:center;padding:14px 0;text-decoration:none;color:var(--sub)}nav a.on{color:var(--accent);font-weight:700}
.top{position:sticky;top:0;z-index:1;background:var(--bg);padding:12px 0;margin:-16px 0 4px}
.cal{width:100%;border-collapse:collapse;table-layout:fixed;font-size:12px}.cal th{font-weight:600;padding:4px 0;color:var(--sub)}
.cal td{vertical-align:top;border:1px solid var(--line);height:64px;padding:2px 3px;background:var(--card);overflow:hidden}
.cal .n{display:block;font-weight:600}.cal .red .n,.cal th.red{color:var(--red)}.cal .dim{opacity:.4}
.cal .today{outline:2px solid var(--accent);outline-offset:-2px}.cal .hol{display:block;color:var(--red);font-size:10px;line-height:1.3}
.cal .ev{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;font-size:10px;line-height:1.25;word-break:break-all;text-decoration:none;color:var(--fg);margin-top:2px;padding-top:2px;border-top:1px dotted var(--line)}
.cal .ev.good{color:var(--good)}.cal .ev.bad{color:var(--bad)}
.good{color:var(--good)}.bad{color:var(--bad)}.foot{margin-top:32px;font-size:13px;color:var(--sub);border-top:1px solid var(--line);padding-top:12px}
"""


def page(title: str, body: str, tab: str | None = None) -> str:
    nav = "" if tab is None else (
        '<nav><a href="/" class="' + ("on" if tab == "cards" else "") + '">내 종목</a>'
        '<a href="/calendar" class="' + ("on" if tab == "calendar" else "") + '">캘린더</a></nav>')  # fmt: skip
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{e(title)} · 한장</title><style>{CSS}</style></head>"
            f"<body><main>{body}</main>{nav}</body></html>")  # fmt: skip


def safe_url(u: str) -> str:
    return u if u.startswith(("https://", "http://")) else "#"


def sentence(s: dict, links: dict) -> str:
    """문장 + 근거 링크 번호. 모든 문장에 원문 링크 (불변식 2)."""
    refs = "".join(f'<a href="{e(safe_url(links.get(r, "#")))}" target="_blank" rel="noopener">[{e(r)}]</a>'
                   for r in s["refs"] if r in links)  # fmt: skip
    return f"{e(s['text'])}<sup>{refs}</sup>"


def render_note(name: str, ticker: str, week: str, body: dict, writer: str) -> str:
    links = body.get("links", {})
    parts = [f'<p class="sub"><a href="/">← 내 종목</a> · {e(week)} 주 노트</p>',
             f"<h1>{e(name)} <span class='sub'>{e(ticker)}</span></h1>",
             f'<p class="lead">{e(body["headline"])}</p>']  # fmt: skip
    if body.get("summary"):
        parts.append('<div class="box"><b>한 장 요약.</b> '
                     + " ".join(sentence(s, links) for s in body["summary"]) + "</div>")  # fmt: skip
    for sec in body["sections"]:
        parts.append(f"<h2>{e(sec['title'])}</h2><p>"
                     + " ".join(sentence(s, links) for s in sec["sentences"]) + "</p>")  # fmt: skip
        if sec["title"].startswith("요즘 기사"):
            parts.append('<p class="sub">⚠️ 개발용 — 기사 제목은 개인용으로만 모은 것이라 남에게 보여주면 안 돼요.</p>')
    how = ("기사·공시·재무에서 코드가 뽑은 사실을 바탕으로 AI가 문장을 다듬었어요. 숫자는 코드가 원문과 대조했어요."
           if writer.startswith("llm") else "코드가 뽑은 사실을 그대로 옮겼어요.")  # fmt: skip
    parts.append(f'<p class="foot">{how} [번호]를 누르면 원문이 열려요.<br>'
                 "<b>사라·팔아라는 의견도, 목표주가도, 앞으로의 예측도 없어요.</b> 투자 판단은 본인이 해요.</p>")
    return page(name, "".join(parts), "cards")


# --- 앱 ---


class App:
    def __init__(self, con: sqlite3.Connection, secret: str, clock=time.time) -> None:
        self.con, self.secret, self.clock = con, secret, clock

    def __call__(self, environ, start_response):
        method, path = environ["REQUEST_METHOD"], environ.get("PATH_INFO", "/")
        form = {}
        if method == "POST":
            n = int(environ.get("CONTENT_LENGTH") or 0)
            form = {k: v[0] for k, v in parse_qs(environ["wsgi.input"].read(n).decode()).items()}
        query = {k: v[0] for k, v in parse_qs(environ.get("QUERY_STRING", "")).items()}
        cookie = dict(c.strip().split("=", 1) for c in environ.get("HTTP_COOKIE", "").split(";") if "=" in c)
        uid = unsign(cookie.get("s", ""), self.secret)
        status, headers, body = self.route(method, path, form, query, int(uid) if uid else None)
        start_response(status, [("Content-Type", "text/html; charset=utf-8"), *headers])
        return [body.encode()]

    def see(self, to: str, *headers) -> tuple:
        return "303 See Other", [("Location", to), *headers], ""

    def log(self, uid: int, page_: str, ticker: str | None = None) -> None:
        self.con.execute("insert into views (user_id, page, ticker, at) values (?, ?, ?, ?)",
                         (uid, page_, ticker, datetime.now().isoformat()))  # fmt: skip
        self.con.commit()

    def route(self, method, path, form, query, uid):
        if path == "/login" and method == "POST":
            return self.login(form.get("email", "").strip().lower())
        if path == "/auth":
            email = check_login(query.get("t", ""), self.secret, self.clock())
            if not email:
                return "200 OK", [], page("로그인", "<p>링크가 만료됐거나 잘못됐어요. <a href='/'>다시 받기</a></p>")
            self.con.execute("insert or ignore into users (email, created_at) values (?, ?)",
                             (email, datetime.now().isoformat()))  # fmt: skip
            self.con.commit()
            (u,) = self.con.execute("select id from users where email = ?", (email,)).fetchone()
            ck = f"s={sign(str(u), self.secret)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=7776000"
            return self.see("/", ("Set-Cookie", ck))
        if uid is None:
            return "200 OK", [], self.login_page()
        if path == "/logout":
            return self.see("/", ("Set-Cookie", "s=; Path=/; Max-Age=0"))
        if path == "/add" and method == "POST":
            return self.add(uid, form.get("q", "").strip())
        if path == "/remove" and method == "POST":
            self.con.execute("delete from holdings where user_id = ? and ticker = ?", (uid, form.get("t")))
            self.con.commit()
            return self.see("/")
        if path == "/":
            self.log(uid, "cards")
            return "200 OK", [], self.cards(uid, query.get("msg"))
        if path.startswith("/n/"):
            ticker = path[3:]
            self.log(uid, "note", ticker)
            return self.note(ticker)
        if path == "/calendar":
            self.log(uid, "calendar")
            return "200 OK", [], self.calendar(uid, query.get("m"))
        return "404 Not Found", [], page("없음", "<p>없는 화면이에요. <a href='/'>처음으로</a></p>")

    def login_page(self, sent: str | None = None) -> str:
        msg = (f"<p class='box'>{e(sent)} 로 로그인 링크를 보냈어요. 15분 안에 눌러 주세요.</p>" if sent else "")
        return page("로그인", "<h1>한장</h1><p class='sub'>내 주식이 지금 어떤 상황인지, 쉬운 글 한 장으로.</p>"
                    + msg + "<form method='post' action='/login' class='row'>"
                    "<input class='grow' type='email' name='email' required placeholder='이메일'>"
                    "<button>링크 받기</button></form>"
                    "<p class='sub'>비밀번호 없이, 메일로 온 링크를 누르면 들어와요. 받는 정보는 이메일뿐이에요.</p>")  # fmt: skip

    def login(self, email: str):
        if "@" not in email or len(email) > 200:
            return "200 OK", [], self.login_page()
        link = f"/auth?t={quote(login_token(email, self.secret, self.clock()))}"
        # ponytail: 메일 발송은 4주차 — 지금은 서버 콘솔에 찍는다 (개발용)
        print(f"[로그인 링크] {email}: http://localhost:8000{link}", file=sys.stderr, flush=True)
        return "200 OK", [], self.login_page(email)

    def add(self, uid: int, q: str):
        row = self.con.execute("select ticker from stocks where active = 1 and (ticker = ? or name = ?)",
                               (q, q)).fetchone()  # fmt: skip
        if not row:
            return self.see("/?msg=" + quote(f"「{q}」은(는) 아직 노트가 없어요. 코스피 큰 회사 100곳부터 시작했어요."))
        (n,) = self.con.execute("select count(*) from holdings where user_id = ?", (uid,)).fetchone()
        if n >= MAX_STOCKS:
            return self.see("/?msg=" + quote(f"종목은 {MAX_STOCKS}개까지 담을 수 있어요."))
        self.con.execute("insert or ignore into holdings values (?, ?, ?)",
                         (uid, row[0], datetime.now().isoformat()))  # fmt: skip
        self.con.commit()
        return self.see("/")

    def cards(self, uid: int, msg: str | None) -> str:
        rows = self.con.execute(
            "select s.ticker, s.name, n.week, n.body from holdings h join stocks s using(ticker)"
            " left join notes n on n.ticker = s.ticker and n.week ="
            " (select max(week) from notes where ticker = s.ticker)"
            " where h.user_id = ? order by h.added_at", (uid,)).fetchall()  # fmt: skip
        names = self.con.execute("select name from stocks where active = 1 order by name").fetchall()
        search = ("<form method='post' action='/add' class='row top'>"
                  "<input class='grow' name='q' list='names' required placeholder='종목 이름 또는 코드로 담기'>"
                  "<button>담기</button></form><datalist id='names'>"
                  + "".join(f"<option value='{e(n)}'>" for (n,) in names) + "</datalist>")  # fmt: skip
        out = [search, "<h1>내 종목</h1>", f"<p class='box'>{e(msg)}</p>" if msg else ""]
        for t, name, week, body in rows:
            head = json.loads(body)["headline"] if body else "이번 주 노트를 준비 중이에요."
            out.append(f"<div class='row'><a class='card grow' href='/n/{e(t)}'><b>{e(name)}</b>"
                       f" <span class='sub'>{e(week or '')}</span><br>{e(head)}</a>"
                       f"<form method='post' action='/remove'><input type='hidden' name='t' value='{e(t)}'>"
                       f"<button class='ghost' title='빼기'>✕</button></form></div>")  # fmt: skip
        if not rows:
            out.append("<p class='sub'>가진 종목이나 궁금한 종목을 담아 보세요. 매주 한 장씩 노트가 와요.</p>")
        out.append("<p class='sub' style='margin-top:24px'><a href='/logout'>로그아웃</a></p>")
        return page("내 종목", "".join(out), "cards")

    def note(self, ticker: str):
        row = self.con.execute(
            "select s.name, n.week, n.body, n.writer from stocks s join notes n using(ticker)"
            " where s.ticker = ? order by n.week desc limit 1", (ticker,)).fetchone()  # fmt: skip
        if not row:
            return "404 Not Found", [], page("없음", "<p>이 종목은 아직 노트가 없어요. <a href='/'>내 종목</a></p>")
        name, week, body, writer = row
        return "200 OK", [], render_note(name, ticker, week, json.loads(body), writer)

    def calendar(self, uid: int, month: str | None, today: date | None = None) -> str:
        """④ 캘린더 — 한 달 달력. 주말·공휴일은 빨간 숫자, 칸 안에 내 종목의 공시.
        ponytail: 앞으로의 일정(실적 발표일·배당 기준일)은 공시 본문을 읽어야 나온다 — 지금은 지난 공시만."""
        today = today or date.today()
        y, m = (int(x) for x in month.split("-")) if month and re.fullmatch(r"\d{4}-\d{2}", month) else (today.year, today.month)
        y, m = (y, m) if 1 <= m <= 12 and 2000 <= y <= 2100 else (today.year, today.month)
        weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(y, m)  # 일요일부터
        lo, hi = weeks[0][0].isoformat(), weeks[-1][-1].isoformat()
        hol = dict(self.con.execute("select date, name from holidays where date between ? and ?", (lo, hi)))
        if (end := date(y, 12, 31)).weekday() < 5 and m == 12:
            hol.setdefault(end.isoformat(), "증시 휴장")  # 연말 휴장 — 공휴일 자료엔 없다
        rows = self.con.execute(
            "select d.date, s.name, d.code, d.title, d.rcept_no, d.direction from disclosures d"
            " join holdings h on h.ticker = d.ticker and h.user_id = ? join stocks s on s.ticker = d.ticker"
            " where d.date between ? and ? and d.importance >= 2 and d.code != 'OTHER' order by d.date",
            (uid, lo, hi)).fetchall()  # fmt: skip
        by: dict[str, list] = {}
        for r in rows:
            by.setdefault(r[0], []).append(r)
        prev = f"{y - (m == 1)}-{(m - 2) % 12 + 1:02d}"
        nxt = f"{y + (m == 12)}-{m % 12 + 1:02d}"
        out = [f"<div class='row'><h1 class='grow'>{y}년 {m}월</h1>"
               f"<a href='/calendar?m={prev}'>‹ 이전</a> <a href='/calendar?m={nxt}'>다음 ›</a></div>",
               "<table class='cal'><tr>" + "".join(f"<th{' class=red' if i in (0, 6) else ''}>{d}</th>"
                                                  for i, d in enumerate("일월화수목금토")) + "</tr>"]  # fmt: skip
        for wk in weeks:
            out.append("<tr>")
            for i, d in enumerate(wk):
                iso = d.isoformat()
                cls = " ".join(c for c, on in (("red", i in (0, 6) or iso in hol), ("dim", d.month != m),
                                               ("today", d == today)) if on)  # fmt: skip
                cell = f"<span class='n'>{d.day}</span>"
                if iso in hol:
                    cell += f"<span class='hol'>{e(hol[iso])}</span>"
                for _, name, code, _, rno, dr in by.get(iso, []):
                    tone = {1: " good", -1: " bad"}.get(dr, "")
                    cell += (f"<a class='ev{tone}' href='{e(notes.DART.format(rno))}' target='_blank' rel='noopener'>"
                             f"{e(name)} {e(notes.EVENT_KO[code])}</a>")  # fmt: skip
                out.append(f"<td class='{cls}'>{cell}</td>")
            out.append("</tr>")
        out.append("</table><h2>이 달의 일정</h2>")
        mine = [r for r in rows if r[0][:7] == f"{y}-{m:02d}"]
        for d, name, code, title, rno, dr in mine:
            tone = {1: " <span class='good'>반가운 쪽</span>", -1: " <span class='bad'>걸리는 쪽</span>"}.get(dr, "")
            out.append(f"<a class='card' href='{e(notes.DART.format(rno))}' target='_blank' rel='noopener'>"
                       f"<span class='sub'>{e(d)} · {e(name)}</span><br><b>{e(notes.EVENT_KO[code])}</b>{tone}"
                       f"<br><span class='sub'>{e(title)}</span></a>")  # fmt: skip
        if not mine:
            out.append("<p class='sub'>이 달엔 내 종목의 큰 공시가 없어요.</p>")
        out.append("<p class='sub'>지난 공시만 보여요. 앞으로의 일정(실적 발표일·배당일)은 준비 중이에요. 공휴일: 한국천문연구원.</p>")
        return page("캘린더", "".join(out), "calendar")


if __name__ == "__main__":
    import threading
    from socketserver import ThreadingMixIn
    from wsgiref.simple_server import WSGIServer, make_server

    class Server(ThreadingMixIn, WSGIServer):
        """연결마다 스레드 — 브라우저가 미리 열어 둔 빈 연결 하나에 서버 전체가 멈추지 않게.
        ponytail: DB 는 연결 하나를 잠금으로 돌려 쓴다. 사용자가 늘면 요청마다 연결로"""

        daemon_threads = True

    sys.stderr.reconfigure(encoding="utf-8")  # 윈도우 콘솔(cp949)에서 한글 로그가 깨지지 않게
    db.connect().close()
    app = App(sqlite3.connect(db.PATH, check_same_thread=False), env()["SECRET"])
    lock = threading.Lock()

    def serial(environ, start_response):
        with lock:
            return app(environ, start_response)

    print("한장 — http://localhost:8000", file=sys.stderr)
    make_server("127.0.0.1", 8000, serial, server_class=Server).serve_forever()
