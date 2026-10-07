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

from hanjang import db, mail, notes
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

# 색·모양은 Stitch 「Warm Editorial Finance」(docs/design.md) — 그림자 없는 얇은 선, 따뜻한 종이색
CSS = """
:root{--bg:#faf9f6;--fg:#1d1d1f;--sub:#6b6b70;--line:#e6e4df;--card:#fff;--accent:#2f5d50;--accent-bg:#eef6f2;
--good:#2f6f4f;--good-bg:#eef6f2;--bad:#a2412f;--bad-bg:#fcf2ef;--red:#d1352b;--soft:#f3f1ec}
@media (prefers-color-scheme:dark){:root{--bg:#141414;--fg:#ececec;--sub:#a0a0a5;--line:#2a2a2a;--card:#1d1d1d;--accent:#8cc7b3;
--accent-bg:#1b2921;--good:#7bc49f;--good-bg:#1b2921;--bad:#e88d7d;--bad-bg:#2d1c1a;--red:#ff6b5e;--soft:#222}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.75 Pretendard,-apple-system,"Apple SD Gothic Neo","Noto Sans KR",sans-serif;
letter-spacing:-.01em;word-break:keep-all}
main{max-width:480px;margin:0 auto;padding:0 16px 104px}
a{color:var(--accent)}h1{font-size:28px;line-height:1.35;margin:12px 0 4px;letter-spacing:-.02em}
h2{font-size:19px;margin:32px 0 10px;display:flex;align-items:center;gap:8px}h2:before{content:"";width:7px;height:7px;border-radius:9px;background:var(--fg)}
.sub{color:var(--sub);font-size:13px;line-height:1.6}.micro{font-size:11px;font-weight:600;letter-spacing:.06em;color:var(--sub)}
.bar{position:sticky;top:0;z-index:2;background:var(--bg);padding:12px 0 10px}
.brand{display:flex;align-items:baseline;gap:8px;margin-bottom:10px}.brand b{font-size:20px;color:var(--accent)}
.card{display:block;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin:14px 0;text-decoration:none;color:inherit}
.row{display:flex;gap:8px;align-items:center}.grow{flex:1}.between{display:flex;justify-content:space-between;align-items:center;gap:8px}
.chip{display:inline-block;font-size:12px;font-weight:600;color:var(--sub);background:var(--soft);border-radius:6px;padding:1px 7px;margin-left:6px;vertical-align:middle}
.tag{display:inline-block;font-size:12px;font-weight:600;border-radius:999px;padding:2px 10px}.tag.good{background:var(--good-bg);color:var(--good)}.tag.bad{background:var(--bad-bg);color:var(--bad)}
input,button{font:inherit;border-radius:12px;border:1px solid var(--line);background:var(--card);color:var(--fg);padding:11px 14px}
input{background:var(--soft);border-color:transparent}button{background:var(--accent);color:#fff;border:0;font-weight:600}
@media (prefers-color-scheme:dark){button{color:#141414}}
button.ghost{background:none;color:var(--sub);padding:2px 6px;font-weight:400}
.search{display:flex;gap:6px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:5px 5px 5px 14px;box-shadow:0 4px 16px rgba(29,29,31,.04)}
.search input{flex:1;background:none;padding:6px 0;border:0;outline:0}.search button{padding:6px 14px;border-radius:9px}
sup a{display:inline-block;font-size:11px;font-weight:600;line-height:14px;text-decoration:none;color:var(--accent);background:var(--accent-bg);border-radius:4px;padding:1px 5px;margin-left:3px}
.lead{font-size:19px;font-weight:700;line-height:1.55;border-left:3px solid var(--accent);background:var(--card);padding:14px 16px;border-radius:0 12px 12px 0;margin:18px 0}
.box{border-radius:12px;padding:14px 16px;margin:12px 0}.box.sum{background:var(--accent-bg)}.box.tip{background:var(--soft)}
.box.good{background:var(--good-bg)}.box.bad{background:var(--bad-bg)}.box b.lbl{display:block;font-size:13px;margin-bottom:4px}
.box.good b.lbl{color:var(--good)}.box.bad b.lbl{color:var(--bad)}.box.sum b.lbl{color:var(--accent)}
.metrics{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:14px 0}.metrics div{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.metrics strong{display:block;font-size:22px;letter-spacing:-.02em}.up{color:var(--good)}.down{color:var(--bad)}
.foot{margin-top:36px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;font-size:14px;color:var(--sub)}
.foot b{color:var(--fg)}.warn{display:block;margin-top:10px;background:var(--bad-bg);color:var(--bad);border-radius:8px;padding:10px 12px;font-weight:600}
.cardfoot a{white-space:nowrap}.cardfoot{display:flex;justify-content:space-between;align-items:center;margin-top:12px;padding-top:10px;border-top:1px solid var(--line);font-size:13px}
.empty{border:1.5px dashed var(--line);border-radius:14px;padding:24px 20px;text-align:center;color:var(--sub);margin:14px 0}
.feat{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:18px 0}.feat div{background:var(--soft);border-radius:12px;padding:14px;font-size:13px;color:var(--sub);line-height:1.6}
.feat b{display:block;color:var(--accent);font-size:15px;margin-bottom:6px}
nav{position:fixed;bottom:0;left:0;right:0;display:flex;background:rgba(250,249,246,.92);backdrop-filter:blur(12px);border-top:1px solid var(--line);padding-bottom:env(safe-area-inset-bottom)}
@media (prefers-color-scheme:dark){nav{background:rgba(20,20,20,.92)}}
nav a{flex:1;display:flex;flex-direction:column;align-items:center;gap:2px;padding:8px 0 10px;text-decoration:none;color:var(--sub);font-size:12px}
nav a.on{color:var(--accent);font-weight:600}nav svg{width:22px;height:22px}
.cal{width:100%;border-collapse:separate;border-spacing:3px;table-layout:fixed;font-size:12px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:6px}
.cal th{font-weight:600;padding:4px 0;color:var(--sub)}.cal th.red{color:var(--red)}
.cal td{vertical-align:top;height:58px;padding:3px;background:var(--soft);border-radius:8px;overflow:hidden}
.cal .n{display:block;font-weight:600}.cal .red .n{color:var(--red)}.cal .dim{opacity:.35}
.cal td.red:has(.hol){background:var(--bad-bg)}.cal .today{outline:2px solid var(--accent);outline-offset:-2px}
.cal .hol{display:block;color:var(--red);font-size:10px;line-height:1.3}
.cal .ev{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;font-size:10px;line-height:1.25;word-break:break-all;
text-decoration:none;color:var(--accent);background:var(--accent-bg);border-radius:4px;padding:1px 3px;margin-top:2px}
.cal .ev.bad{color:var(--bad);background:var(--bad-bg)}
.good{color:var(--good)}.bad{color:var(--bad)}
"""
ICON = {  # 아래 탭 아이콘 — 선 두 개짜리 SVG
    "cards": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M9 9v11"/></svg>',
    "calendar": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>',
}
FONT = "https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css"
# 쉽게 풀어보기 — 우리가 쓴 고정 풀이. 노트 글에 그 낱말이 나올 때만 보인다
GLOSSARY = {
    "영업이익": "물건을 팔아 들어온 돈에서 만드는 비용·월급 같은 본업 비용을 빼고 남은 돈이에요.",
    "부채비율": "회사 빚을 회사 자기 돈으로 나눈 값이에요. 낮을수록 빚 부담이 적어요.",
    "ROE": "주주 돈 100원으로 1년에 몇 원을 벌었는지예요.",
    "자사주": "회사가 자기 회사 주식을 사들이는 거예요. 시중에 도는 주식 수가 줄어요.",
    "유상증자": "회사가 새 주식을 팔아 돈을 모으는 거예요. 주식 수가 늘어 기존 주주의 몫이 묽어질 수 있어요.",
    "전환사채": "나중에 주식으로 바꿀 수 있는 빚이에요. 주식으로 바뀌면 주식 수가 늘어요.",
}


def page(title: str, body: str, tab: str | None = None) -> str:
    nav = "" if tab is None else "<nav>" + "".join(
        f'<a href="{href}" class="{"on" if tab == key else ""}">{ICON[key]}{label}</a>'
        for key, href, label in (("cards", "/", "내 종목"), ("calendar", "/calendar", "캘린더"))) + "</nav>"  # fmt: skip
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<link rel="stylesheet" href="{FONT}">'
            f"<title>{e(title)} · 한장</title><style>{CSS}</style></head>"
            f"<body><main>{body}</main>{nav}</body></html>")  # fmt: skip


def brand(right: str = "") -> str:
    return f"<div class='brand between'><span><b>한장</b> <span class='micro'>WEEKLY NOTE</span></span>{right}</div>"


def safe_url(u: str) -> str:
    return u if u.startswith(("https://", "http://")) else "#"


def sentence(s: dict, links: dict) -> str:
    """문장 + 근거 링크 번호. 모든 문장에 원문 링크 (불변식 2)."""
    refs = "".join(f'<a href="{e(safe_url(links.get(r, "#")))}" target="_blank" rel="noopener">{e(r)}</a>'
                   for r in s["refs"] if r in links)  # fmt: skip
    return f"{e(s['text'])}<sup>{refs}</sup>"


def metrics(facts: list[dict]) -> str:
    """주요 실적 한눈에 보기 — 사실 F1(매출)·F2(영업이익)의 코드 문장에서 그대로 뽑는다(새 계산 없음)."""
    cells = []
    for f in facts:
        m = re.match(r"(\d{4})년 (매출|영업이익) (\S+?원)(?:\(전년보다 ([+-][\d.]+%)\))?", f["text"])
        if m and f["id"] in ("F1", "F2"):
            y, what, val, chg = m.groups()
            cls = "" if not chg else "up" if chg.startswith("+") else "down"
            cells.append(f"<div><span class='sub'>{e(what)}</span><strong>{e(val)}</strong>"
                         f"<span class='{cls}' style='font-size:13px'>{e(chg or '')}</span></div>")  # fmt: skip
    if not cells:
        return ""
    return (f"<div class='between' style='margin-top:18px'><b style='font-size:15px'>주요 실적 한눈에 보기</b>"
            f"<span class='sub'>{e(y)}년 · 전년 대비</span></div><div class='metrics'>{''.join(cells)}</div>")


def glossary(text: str) -> str:
    hits = [(k, v) for k, v in GLOSSARY.items() if k in text][:2]
    return "".join(f"<div class='box tip'><b class='lbl'>💡 쉽게 풀어보기 · {e(k)}</b>{e(v)}</div>" for k, v in hits)


def render_note(name: str, ticker: str, week: str, body: dict, writer: str, facts: list[dict] | None = None) -> str:
    links = body.get("links", {})
    every = body["summary"] + [x for sec in body["sections"] for x in sec["sentences"]] + body.get("good", []) + body.get("concern", [])
    minutes = max(1, round(sum(len(x["text"]) for x in every) / 500))  # 한글 분당 500자쯤
    parts = [f"<div class='bar between'><a href='/' class='sub'>← 내 종목 · {e(week)} 주 노트</a>"
             f"<span class='tag good'>{minutes}분이면 다 읽어요</span></div>",
             f"<h1>{e(name)}<span class='chip'>{e(ticker)}</span></h1>",
             f'<p class="lead">{e(body["headline"])}</p>']  # fmt: skip
    if body.get("summary"):
        parts.append("<div class='box sum'><b class='lbl'>📖 한 장 요약</b>"
                     + " ".join(sentence(s, links) for s in body["summary"]) + "</div>")  # fmt: skip
    used = " ".join(x["text"] for x in every)
    for k, sec in enumerate(body["sections"]):
        parts.append(f"<h2>{e(sec['title'])}</h2><p>" + " ".join(sentence(s, links) for s in sec["sentences"]) + "</p>")
        if k == 0:
            parts.append(metrics(facts or []) + glossary(used))
        if sec["title"].startswith("요즘 기사"):
            parts.append('<p class="sub">⚠️ 개발용 — 기사 제목은 개인용으로만 모은 것이라 남에게 보여주면 안 돼요.</p>')
    if "good" in body:
        parts.append("<h2>좋게 본 것과 걱정되는 것</h2>"
                     "<div class='box good'><b class='lbl'>👍 좋게 본 것</b>" + " ".join(sentence(s, links) for s in body["good"]) + "</div>"
                     "<div class='box bad'><b class='lbl'>⚠ 걱정되는 것</b>" + " ".join(sentence(s, links) for s in body["concern"]) + "</div>"
                     f"<p class='sub'>{e(body.get('tone_rule', ''))}</p>")  # fmt: skip
    how = ("기사·공시·재무에서 코드가 뽑은 사실을 바탕으로 AI가 문장을 다듬었어요. 숫자는 코드가 원문과 대조했어요."
           if writer.startswith("llm") else "코드가 뽑은 사실을 그대로 옮겼어요.")  # fmt: skip
    parts.append(f"<div class='foot'><b>✓ 작성 기준 및 검증 안내</b><br>{how} 초록 번호를 누르면 원문(금융감독원 전자공시 DART·기사)이 열려요."
                 "<span class='warn'>사라·팔아라는 의견도, 목표주가도, 앞으로의 예측도 없어요. 투자 판단은 본인이 해요.</span></div>")
    return page(name, "".join(parts), "cards")


# 캘린더 일정 카드의 한 줄 풀이 — 공시 종류의 뜻(우리가 쓴 고정 문장). 공시 내용을 지어내지 않는다
EVENT_EXPLAIN = {
    "BUYBACK": "회사가 자기 주식을 사들이거나 없애기로 했어요. 시중에 도는 주식 수가 줄어요.",
    "DIVIDEND": "번 돈의 일부를 주주에게 나눠 주기로 했어요.",
    "EARNINGS": "회사가 매출·이익 같은 실적을 알렸어요.",
    "MAJOR_CONTRACT": "큰 판매·공급 계약을 맺었어요.",
    "RIGHTS_ISSUE": "새 주식을 팔아 돈을 모으기로 했어요. 주식 수가 늘어요.",
    "BONUS_ISSUE": "주주에게 주식을 무상으로 더 나눠 주기로 했어요.",
    "CB_BW": "나중에 주식으로 바꿀 수 있는 채권을 냈어요. 바뀌면 주식 수가 늘어요.",
    "LAWSUIT": "소송이 걸렸거나 판결이 났어요.",
    "MA": "다른 회사와 합치거나 사업·회사를 사고팔기로 했어요.",
    "HOLDER_CHANGE": "큰 주주의 지분이 바뀌었어요.",
    "CLINICAL": "신약 임상 시험 소식이에요.",
    "TRADING_HALT": "거래가 멈추거나 관리 대상이 됐어요.",
    "SPLIT": "주식 한 주를 여러 주로 쪼개기로 했어요.",
    "REVERSE_SPLIT": "여러 주를 한 주로 합치거나 자본을 줄이기로 했어요.",
}
TONE_TAG = {1: "<span class='tag good'>반가운 쪽</span>", -1: "<span class='tag bad'>걸리는 쪽</span>"}


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
            return self.note(uid, ticker, query.get("thanks") == "1")
        if path == "/feedback" and method == "POST":
            return self.feedback(uid, form)
        if path == "/calendar":
            self.log(uid, "calendar")
            return "200 OK", [], self.calendar(uid, query.get("m"))
        return "404 Not Found", [], page("없음", "<p>없는 화면이에요. <a href='/'>처음으로</a></p>")

    def login_page(self, sent: str | None = None) -> str:
        msg = (f"<div class='box sum'>{e(sent)} 로 로그인 링크를 보냈어요. 15분 안에 눌러 주세요.</div>" if sent else "")
        return page("로그인", "<div style='text-align:center;margin-top:48px'><h1 style='font-size:40px;color:var(--accent)'>한장</h1>"
                    "<p class='micro'>HANJANG · WEEKLY NOTE</p><p style='font-size:19px;font-weight:700;margin:20px 0 6px'>"
                    "내 주식이 지금 어떤 상황인지,<br>쉬운 글 한 장으로.</p>"
                    "<p class='sub'>숫자 뒤에 숨은 회사 이야기를 공시와 재무로 담백하게 정리해 드려요.</p></div>"
                    + msg + "<form method='post' action='/login' class='card'>"
                    "<div class='between'><b style='font-size:14px'>✉ 이메일 주소</b><span class='sub'>비밀번호 없는 간편 시작</span></div>"
                    "<input type='email' name='email' required placeholder='name@example.com' style='width:100%;margin:10px 0'>"
                    "<button style='width:100%;height:48px'>로그인 링크 받기 →</button>"
                    "<p class='sub' style='text-align:center;margin:10px 0 0'>메일로 온 링크를 누르면 들어와요. 받는 정보는 이메일뿐이에요.</p></form>"
                    "<div class='feat'><div><b>공시 기반 해설</b>어려운 DART 공시와 재무를 일상 언어로 풀어요.</div>"
                    "<div><b>소음 없는 담백함</b>빨강·파랑 시세창 대신, 회사 사정을 천천히 읽어요.</div></div>"
                    "<p class='sub' style='text-align:center'>— 한장의 약속 —<br>이해를 위한 서비스예요. 수익률을 장담하거나 종목을 추천하지 않아요.</p>")  # fmt: skip

    def login(self, email: str):
        if "@" not in email or len(email) > 200:
            return "200 OK", [], self.login_page()
        link = f"{mail.base_url()}/auth?t={quote(login_token(email, self.secret, self.clock()))}"
        mail.send(email, *mail.login_mail(link))  # SMTP 설정이 없으면 서버 콘솔에 찍힌다
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
            "select s.ticker, s.name, n.week, n.body, n.facts from holdings h join stocks s using(ticker)"
            " left join notes n on n.ticker = s.ticker and n.week ="
            " (select max(week) from notes where ticker = s.ticker)"
            " where h.user_id = ? order by h.added_at", (uid,)).fetchall()  # fmt: skip
        names = self.con.execute("select name from stocks where active = 1 order by name").fetchall()
        search = ("<div class='bar'>" + brand() + "<form method='post' action='/add' class='search'>"
                  "<input name='q' list='names' required placeholder='🔍 종목 이름 또는 코드로 담기'>"
                  "<button>담기</button></form><datalist id='names'>"
                  + "".join(f"<option value='{e(n)}'>" for (n,) in names) + "</datalist></div>")  # fmt: skip
        out = [search, "<h1 style='font-size:22px'>내 종목</h1>", f"<div class='box sum'>{e(msg)}</div>" if msg else ""]
        for t, name, week, body, facts in rows:
            head = json.loads(body)["headline"] if body else "이번 주 노트를 준비 중이에요."
            fs = json.loads(facts) if facts else []
            nd, nn = sum(f["id"][0] == "D" for f in fs), sum(f["id"][0] == "N" for f in fs)
            bad, good = sum(f.get("tone") == -1 for f in fs), sum(f.get("tone") == 1 for f in fs)
            mood = (f"<span class='bad'>! 걱정되는 점 {bad}가지</span>" if bad
                    else f"<span class='good'>✓ 좋게 본 점 {good}가지</span>" if good else "")  # fmt: skip
            out.append(f"<div class='card'><div class='between'><a href='/n/{e(t)}' style='color:inherit;text-decoration:none'>"
                       f"<b style='font-size:19px'>{e(name)}</b><span class='chip'>{e(t)}</span>"
                       f" <span class='sub'>{e(week or '')}</span></a>"
                       f"<form method='post' action='/remove'><input type='hidden' name='t' value='{e(t)}'>"
                       f"<button class='ghost' title='빼기'>✕</button></form></div>"
                       f"<a href='/n/{e(t)}' style='color:inherit;text-decoration:none;display:block;margin-top:8px'>{e(head)}</a>"
                       f"<div class='cardfoot'><span class='sub'>최근 공시 {nd}건 · 기사 {nn}건<br>{mood}</span>"
                       f"<a href='/n/{e(t)}' style='font-weight:600;text-decoration:none'>노트 읽기 →</a></div></div>")  # fmt: skip
        if not rows:
            out.append("<div class='empty'>📖<br>가진 종목이나 궁금한 종목을 담아 보세요.<br>매주 한 장씩 차분한 노트가 와요. (최대 20개)</div>")
        out.append("<p class='sub' style='text-align:center;margin-top:24px'>업데이트: 매주 월요일 · 공시 데이터: DART 전자공시<br>"
                   "<a href='/logout'>로그아웃</a></p>")
        return page("내 종목", "".join(out), "cards")

    def trial_week(self, uid: int) -> int:
        """시험 몇 주째인가 — 가입한 날이 1주째 (ERD views 의 주차 계산과 같은 기준)."""
        (created,) = self.con.execute("select created_at from users where id = ?", (uid,)).fetchone()
        return (date.today() - date.fromisoformat(created[:10])).days // 7 + 1

    def survey(self, uid: int, ticker: str, week: str, thanks: bool) -> str:
        """주간 설문 (PRD F7) — 1~5 + 한 줄. 6주째부터 「돈 내고도 보겠다」."""
        done = self.con.execute("select 1 from feedback where user_id = ? and ticker = ? and week = ?",
                                (uid, ticker, week)).fetchone()  # fmt: skip
        if thanks or done:
            return "<div class='box sum' style='margin-top:28px'>이번 주 노트에 대한 의견 고마워요. 다음 주 노트에 참고할게요.</div>"
        pay = ("<p style='margin:14px 0 4px;font-weight:600'>이 노트를 돈을 내고도 보시겠어요? 낸다면 한 달에 얼마까지?</p>"
               "<div class='row' style='flex-wrap:wrap'>" + "".join(
                   f"<label class='chip' style='margin:0;padding:6px 10px'><input type='radio' name='pay' value='{v}' required"
                   f" style='width:auto;padding:0;margin-right:4px'>{t}</label>"
                   for v, t in ((0, "안 내요"), (1000, "1천 원"), (3000, "3천 원"), (5000, "5천 원"), (10000, "1만 원 이상")))
               + "</div>") if self.trial_week(uid) >= 6 else ""  # fmt: skip
        return (f"<form method='post' action='/feedback' class='card' style='margin-top:28px'>"
                f"<input type='hidden' name='t' value='{e(ticker)}'><input type='hidden' name='w' value='{e(week)}'>"
                "<b>이 노트가 도움이 됐나요?</b><div class='between' style='margin:10px 0'>"
                + "".join(f"<label style='text-align:center;flex:1'><input type='radio' name='h' value='{i}' required"
                          f" style='width:auto;padding:0'><br><span class='sub'>{i}</span></label>" for i in range(1, 6))
                + "</div><div class='between sub'><span>별로예요</span><span>아주 좋아요</span></div>" + pay
                + "<input name='c' maxlength='300' placeholder='한 줄 의견 (선택)' style='width:100%;margin:12px 0'>"
                "<button style='width:100%'>보내기</button></form>")  # fmt: skip

    def feedback(self, uid: int, form: dict):
        ticker, week, h = form.get("t", ""), form.get("w", ""), form.get("h", "")
        if not (h.isdigit() and 1 <= int(h) <= 5 and re.fullmatch(r"\d{6}", ticker)
                and re.fullmatch(r"\d{4}-\d{2}-\d{2}", week)):
            return self.see("/")
        pay = form.get("pay")
        self.con.execute("insert into feedback (user_id, ticker, week, helpful, would_pay, comment, at)"
                         " values (?, ?, ?, ?, ?, ?, ?)",
                         (uid, ticker, week, int(h), int(pay) if pay and pay.isdigit() else None,
                          form.get("c", "")[:300], datetime.now().isoformat()))  # fmt: skip
        self.con.commit()
        return self.see(f"/n/{ticker}?thanks=1")

    def note(self, uid: int, ticker: str, thanks: bool = False):
        row = self.con.execute(
            "select s.name, n.week, n.body, n.writer, n.facts from stocks s join notes n using(ticker)"
            " where s.ticker = ? order by n.week desc limit 1", (ticker,)).fetchone()  # fmt: skip
        if not row:
            return "404 Not Found", [], page("없음", "<p>이 종목은 아직 노트가 없어요. <a href='/'>내 종목</a></p>")
        name, week, body, writer, facts = row
        html_ = render_note(name, ticker, week, json.loads(body), writer, json.loads(facts))
        return "200 OK", [], html_.replace("<div class='foot'>", self.survey(uid, ticker, week, thanks) + "<div class='foot'>", 1)

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
        mine = [r for r in rows if r[0][:7] == f"{y}-{m:02d}"]
        kinds: dict[str, int] = {}
        for r in mine:
            kinds[notes.EVENT_KO[r[2]]] = kinds.get(notes.EVENT_KO[r[2]], 0) + 1
        out = ["<div class='bar'>" + brand() + f"<div class='between'><h1 style='font-size:24px;margin:0'>{y}년 {m}월</h1>"
               f"<span><a href='/calendar?m={prev}'>‹ 이전</a> · <a href='/calendar?m={nxt}'>다음 ›</a></span></div></div>",
               f"<div class='box sum'><b class='lbl'>📅 이번 달 내 종목 공시 {len(mine)}건</b>"
               + (" · ".join(f"{e(k)} {v}건" for k, v in kinds.items()) or "큰 공시가 없었어요.") + "</div>",
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
                    tone = {-1: " bad"}.get(dr, "")
                    cell += (f"<a class='ev{tone}' href='{e(notes.DART.format(rno))}' target='_blank' rel='noopener'>"
                             f"{e(name)} {e(notes.EVENT_KO[code])}</a>")  # fmt: skip
                out.append(f"<td class='{cls}'>{cell}</td>")
            out.append("</tr>")
        out.append("</table><h2>이 달의 일정</h2>")
        for d, name, code, title, rno, dr in mine:
            dd = date.fromisoformat(d)
            out.append(f"<a class='card' href='{e(notes.DART.format(rno))}' target='_blank' rel='noopener'>"
                       f"<div class='between'><span class='sub'>{dd.month}월 {dd.day}일 ({'월화수목금토일'[dd.weekday()]}) · {e(name)}</span>"
                       f"{TONE_TAG.get(dr, '')}</div><b style='font-size:18px'>{e(notes.EVENT_KO[code])}</b>"
                       f"<p style='margin:4px 0 8px'>{e(EVENT_EXPLAIN.get(code, ''))}</p>"
                       f"<div class='box tip' style='margin:0;font-size:13px'>✓ DART 공시: {e(title)}</div></a>")  # fmt: skip
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
