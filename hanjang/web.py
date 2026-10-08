"""모바일 웹 (PRD §3·§6) — 표준 라이브러리 WSGI 하나. 사용자 20명이라 프레임워크가 필요 없다.
`uv run python -m hanjang.web` → http://localhost:8000
화면: 로그인 → ② 내 종목 카드 → ③ 기업 노트 · ④ 캘린더. 열 때마다 `views` 한 행 (시험 판정의 원천).
**화면 모양은 Stitch 시안(2026-10-07 둘째 판, docs/design.md)을 그대로 옮겼다** — 클래스·배치·문구를 바꾸지 않는다.
시안의 예시 내용 자리는 전부 실제 데이터로 채운다(사진·그림은 쓸 권리가 없어 회색 빈 칸)."""

import calendar
import hashlib
import hmac
import html
import json
import re
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, quote

from hanjang import db, holders, learn, llm, mail, notes, policy, sources
from hanjang.sources import env, industry_label

MAX_STOCKS = 20  # PRD F2
NICK = re.compile(r"[가-힣A-Za-z0-9_]{2,20}")  # 남에게 보이는 이름 — 이메일은 절대 보이지 않는다
BIO_MAX = 150
BODY_MAX = 6_000_000  # 요청 본문 상한 — 캡처 사진(브라우저에서 줄여 보낸다)도 이 안에
PHOTO_MAX = 300_000  # 프로필 사진 — 브라우저가 256px JPEG 로 줄여 보낸다. 이보다 크면 받지 않는다
SCAN_HOURLY = 10
DEMO_EMAIL = "demo@hanjang.local"  # 둘러보기 계정 — .env DEMO=1 일 때만. 보기만 된다
DEMO_STOCKS = ("005930", "000660", "105560", "010140")  # 한 사람이 한 시간에 캡처를 읽힐 수 있는 횟수 (AI 비용)
LINK_TTL = 15 * 60  # 로그인 링크 15분
LOGIN_GAP, LOGIN_HOURLY = 60, 5  # 같은 주소로 링크는 1분에 한 번, 한 시간에 다섯 번까지 (메일 폭탄·발송 계정 정지 막기)
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


# --- 시안 공통 머리 (Stitch 시안의 <head> 그대로) ---

HEAD = """<meta charset="utf-8"><meta content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover" name="viewport"><link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200" rel="stylesheet"><link href="https://fonts.googleapis.com" rel="preconnect"><link crossorigin="" href="https://fonts.gstatic.com" rel="preconnect"><link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&amp;family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,600;1,6..72,400&amp;display=swap" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&amp;display=swap" rel="stylesheet"><style>@layer base{html,body{width:100vw;margin:0;padding:0;}body{overscroll-behavior:none;}.pb-safe{padding-bottom:env(safe-area-inset-bottom,0px);}.pt-safe{padding-top:env(safe-area-inset-top,0px);}main>:first-child{margin-top:0!important;}main>:last-child{margin-bottom:0!important;}}::-webkit-scrollbar{display:none;}</style><script src="https://cdn.tailwindcss.com"></script><script id="tailwind-config">tailwind.config = { darkMode: "class", theme: { extend: { "colors": { "on-secondary-container": "#2e6e4e", "secondary-fixed": "#aef1c9", "outline-variant": "#c0c8c4", "tertiary": "#741f11", "on-background": "#1b1b1d", "surface-container-low": "#f6f3f5", "on-tertiary-fixed-variant": "#802919", "surface-container-lowest": "#ffffff", "surface-container": "#f0edef", "surface-dim": "#dcd9dc", "outline": "#717975", "primary-fixed": "#bceddc", "primary-container": "#2f5d50", "error": "#ba1a1a", "error-container": "#ffdad6", "on-error": "#ffffff", "tertiary-fixed": "#ffdad3", "surface-bright": "#fcf8fb", "surface": "#fcf8fb", "on-primary-fixed-variant": "#204f42", "background": "#fcf8fb", "primary-fixed-dim": "#a0d1c0", "primary": "#154539", "surface-variant": "#e4e2e4", "on-secondary": "#ffffff", "on-primary-fixed": "#002019", "secondary-container": "#abeec6", "surface-tint": "#396759", "on-primary": "#ffffff", "surface-container-highest": "#e4e2e4", "tertiary-fixed-dim": "#ffb4a5", "on-tertiary": "#ffffff", "on-secondary-fixed-variant": "#095134", "on-tertiary-fixed": "#3f0400", "on-surface": "#1b1b1d", "inverse-primary": "#a0d1c0", "secondary": "#296a4a", "tertiary-container": "#933625", "inverse-on-surface": "#f3f0f2", "on-error-container": "#93000a", "on-secondary-fixed": "#002112", "on-surface-variant": "#404945", "inverse-surface": "#303032", "on-tertiary-container": "#ffb8aa", "on-primary-container": "#a3d4c3", "surface-container-high": "#eae7ea", "secondary-fixed-dim": "#93d5ae" }, "borderRadius": { "DEFAULT": "0.25rem", "lg": "0.5rem", "xl": "0.75rem", "full": "9999px" }, "spacing": { "space-md": "0.875rem", "margin": "1rem", "space-xs": "0.25rem", "space-xl": "2rem", "space-lg": "1.25rem", "gutter": "0.75rem", "space-sm": "0.5rem" }, "fontFamily": { "headline-lg": ["Newsreader"], "label-regular": ["Be Vietnam Pro"], "body-reading-strong": ["Be Vietnam Pro"], "label-micro": ["Be Vietnam Pro"], "headline-sm": ["Be Vietnam Pro"], "citation-ref": ["Be Vietnam Pro"], "body-reading": ["Be Vietnam Pro"], "display-editorial": ["Newsreader"], "headline-md": ["Be Vietnam Pro"], "body-compact": ["Be Vietnam Pro"] }, "fontSize": { "headline-lg": ["24px", {"lineHeight": "34px", "letterSpacing": "-0.015em", "fontWeight": "600"}], "label-regular": ["13px", {"lineHeight": "18px", "letterSpacing": "0em", "fontWeight": "500"}], "body-reading-strong": ["16px", {"lineHeight": "28px", "letterSpacing": "-0.01em", "fontWeight": "600"}], "label-micro": ["11px", {"lineHeight": "14px", "letterSpacing": "0.02em", "fontWeight": "600"}], "headline-sm": ["17px", {"lineHeight": "24px", "letterSpacing": "-0.01em", "fontWeight": "600"}], "citation-ref": ["11px", {"lineHeight": "14px", "letterSpacing": "0.04em", "fontWeight": "600"}], "body-reading": ["16px", {"lineHeight": "28px", "letterSpacing": "-0.01em", "fontWeight": "400"}], "display-editorial": ["30px", {"lineHeight": "40px", "letterSpacing": "-0.02em", "fontWeight": "600"}], "headline-md": ["20px", {"lineHeight": "28px", "letterSpacing": "-0.01em", "fontWeight": "600"}], "body-compact": ["14px", {"lineHeight": "22px", "letterSpacing": "-0.005em", "fontWeight": "400"}] } } } };</script>"""


def page(title: str, body_attr: str, inner: str) -> str:
    return (f'<!DOCTYPE html><html lang="ko"><head>{HEAD}<title>{e(title)} · 한장</title></head>'
            f'<body class="{body_attr}">{inner}</body></html>')  # fmt: skip


def avatar(initial: str) -> str:
    """시안의 프로필 사진 자리 — 사진(「/p/…」 주소)이 있으면 사진, 없으면 첫 글자 동그라미. 누르면 내 프로필."""
    inside = (f'<img alt="" class="w-full h-full object-cover" src="{e(initial)}">' if initial.startswith("/p/") else e(initial.upper()))
    return (f'<a href="/me" aria-label="내 프로필" class="w-8 h-8 rounded-full overflow-hidden bg-surface-container-high flex items-center justify-center '
            f'text-on-surface-variant font-label-regular text-label-regular hover:bg-surface-container-highest transition-colors">{inside}</a>')  # fmt: skip


# 업종 → 분위기 사진 (Unsplash 무료 라이선스, hanjang/static/photos/SOURCES.md). 회사 사진이 아니라 주제 사진이다
STATIC = Path(__file__).parent / "static"
PHOTO = {"반도체": "semiconductor", "전자부품": "electronics", "전자·통신장비": "electronics", "통신": "telecom",
         "은행": "bank", "금융서비스": "bank", "증권": "securities", "보험": "insurance", "지주회사": "holding",
         "제약·바이오": "bio", "연구개발": "bio", "화학": "chemical", "석유정제": "chemical",
         "2차전지": "battery", "전지": "battery", "자동차": "auto", "타이어·고무": "auto",
         "조선": "shipbuilding", "해운": "shipping", "무역·도매": "shipping", "물류": "logistics",
         "건설": "construction", "엔지니어링": "construction", "기계": "construction",
         "전기장비": "power", "전선·케이블": "power", "전력·가스": "power",
         "항공우주": "aero", "방위산업": "aero", "항공": "aero", "철강·금속": "steel",
         "인터넷 플랫폼": "internet", "소프트웨어": "internet", "IT 서비스": "internet", "게임": "game",
         "화장품": "cosmetics", "식료품": "food", "엔터테인먼트": "entertainment", "철도차량": "rail"}  # fmt: skip


KIND_PHOTO = {"LAWSUIT": "lawsuit", "DIVIDEND": "dividend", "BUYBACK": "dividend", "MAJOR_CONTRACT": "contract"}


# 피드 사진 묶음 — 사건 종류·업종마다 고를 주제 (static/photos/pool/<주제><번호>.jpg). 한 화면에 같은 사진은 두 번 안 쓴다
KIND_TOPICS = {"MAJOR_CONTRACT": ("contract", "docs", "meeting"), "DIVIDEND": ("money",), "BUYBACK": ("money", "chart"),
               "LAWSUIT": ("docs",), "EARNINGS": ("chart", "docs"), "RIGHTS_ISSUE": ("money", "chart"), "CB_BW": ("money", "chart"),
               "MA": ("meeting", "contract", "building"), "HOLDER_CHANGE": ("building", "chart", "meeting"), "CLINICAL": ("lab", "pills")}
INDUSTRY_TOPICS = {"semiconductor": ("chip", "server"), "electronics": ("chip",), "telecom": ("server",), "internet": ("server",),
                   "game": ("server",), "bio": ("lab", "pills"), "shipbuilding": ("ship",), "shipping": ("ship",),
                   "logistics": ("ship",), "construction": ("site",), "power": ("powerplant",), "chemical": ("factory", "powerplant"),
                   "steel": ("factory",), "auto": ("robot", "factory"), "battery": ("robot", "factory"), "aero": ("factory",),
                   "bank": ("building", "money"), "securities": ("chart", "building"), "insurance": ("building",),
                   "holding": ("building", "meeting"), "seoul": ("city",)}  # fmt: skip


class Photos:
    """한 화면 안에서 사진을 겹치지 않게 고른다 — 사건 종류 주제 → 업종 사진 → 업종 주제 → 남은 아무 사진 순서."""

    def __init__(self):
        self.used: set[str] = set()
        self.pool = sorted(f"/static/photos/pool/{p.name}" for p in (STATIC / "photos" / "pool").glob("*.jpg"))

    def topic(self, t: str) -> list[str]:
        return [p for p in self.pool if re.sub(r"\d+\.jpg$", "", p.rsplit("/", 1)[1]) == t]

    def pick(self, kind: str | None, induty_code: str | None, name: str = "") -> str:
        main = photo_for(induty_code, name)
        key = main.rsplit("/", 1)[1][:-4]
        cands = ([f"/static/photos/{KIND_PHOTO[kind]}.jpg"] if kind in KIND_PHOTO else [])
        cands += [p for t in KIND_TOPICS.get(kind or "", ()) for p in self.topic(t)]
        cands += [main] + [p for t in INDUSTRY_TOPICS.get(key, ()) for p in self.topic(t)] + self.pool
        got = next((p for p in cands if p not in self.used), cands[0])  # 다 썼으면(사진보다 글이 많으면) 그때만 겹친다
        self.used.add(got)
        return got


def photo_for(induty_code: str | None, name: str = "") -> str:
    label = industry_label(induty_code) or ""
    key = "bank" if label == "지주회사" and "금융" in name else PHOTO.get(label, "seoul")  # 금융지주는 은행 사진
    return f"/static/photos/{key}.jpg"


def story(href: str, img: str, title: str, excerpt: str, source: str, day: str, top: str = "") -> str:
    """뉴닉식 한 줄 — 왼쪽 사진, 오른쪽 제목 · 두 줄 요약 · 출처와 날짜. 글씨는 작게, 줄 사이는 넉넉히 (사용자 10/8)."""
    return (f'<article class="py-4 flex flex-col gap-2">{top}<a href="{e(href)}" class="flex gap-3.5 items-start">'
            f'<img alt="" loading="lazy" class="w-[36%] max-w-[148px] aspect-[4/3] object-cover rounded-lg shrink-0 bg-surface-container" src="{e(img)}">'
            '<span class="min-w-0 flex flex-col gap-1 pt-0.5">'
            f'<span class="text-[15px] leading-[21px] font-semibold tracking-tight text-on-surface line-clamp-2">{e(title)}</span>'
            f'<span class="text-[13px] leading-[19px] text-on-surface-variant line-clamp-2">{e(excerpt)}</span>'
            f'<span class="mt-0.5 text-[11px] leading-4 text-outline"><b class="text-on-surface-variant font-medium">{e(source)}</b>  {e(day)}</span>'
            "</span></a></article>")  # fmt: skip


def gist(body: dict) -> str:
    """요약 한 줄 — 한 장 요약의 첫 문장, 없으면 첫 절의 첫 문장."""
    first = body.get("summary") or next((s["sentences"] for s in body.get("sections", []) if s["sentences"]), [])
    return first[0]["text"] if first else ""


# 로고를 못 쓸 때의 표시 — 그룹 대표색 동그라미 + 짧은 이름. 로고 모양은 따라 그리지 않는다(색·글자만).
# (이름 앞부분, 보일 글자, 바탕색, 글자색) — 앞에서부터 처음 맞는 것
GROUP = (("삼성", "삼성", "#1428A0", "#fff"), ("SK", "SK", "#EA002C", "#fff"), ("LG", "LG", "#A50034", "#fff"),
         ("LIG", "LIG", "#00205B", "#fff"), ("LS", "LS", "#0A3D91", "#fff"), ("KB", "KB", "#FFBC00", "#3d2f00"),
         ("KT&G", "KT&G", "#C8102E", "#fff"), ("KT", "KT", "#ED1C24", "#fff"), ("HD", "HD", "#0A2F6B", "#fff"),
         ("현대", "현대", "#002C5F", "#fff"), ("기아", "KIA", "#05141F", "#fff"), ("한화", "한화", "#F37321", "#fff"),
         ("포스코", "POSCO", "#05507D", "#fff"), ("POSCO", "POSCO", "#05507D", "#fff"), ("두산", "두산", "#005EB8", "#fff"),
         ("카카오", "kakao", "#FFE812", "#3a1d1d"), ("NAVER", "N", "#03C75A", "#fff"), ("신한", "신한", "#0046FF", "#fff"),
         ("하나", "하나", "#008485", "#fff"), ("우리", "우리", "#0067AC", "#fff"), ("DB", "DB", "#00854A", "#fff"),
         ("GS", "GS", "#005A9C", "#fff"), ("CJ", "CJ", "#EF3E33", "#fff"), ("한국전력", "KEPCO", "#00A0E2", "#fff"),
         ("한전", "KEPCO", "#00A0E2", "#fff"), ("셀트리온", "셀트", "#4A2A8C", "#fff"), ("NH", "NH", "#0B7A3E", "#fff"),
         ("BNK", "BNK", "#D6001C", "#fff"), ("JB", "JB", "#00479D", "#fff"), ("HMM", "HMM", "#003A70", "#fff"),
         ("S-Oil", "S-OIL", "#FFD100", "#1d2a57"), ("한진", "한진", "#004C97", "#fff"), ("대한항공", "KAL", "#0064DE", "#fff"),
         ("메리츠", "메리츠", "#E4002B", "#fff"), ("미래에셋", "미래", "#F58220", "#fff"), ("키움", "키움", "#E5006E", "#fff"),
         ("하이브", "HYBE", "#111111", "#fff"), ("크래프톤", "KRAF", "#111111", "#fff"))  # fmt: skip
OTHER = ("#154539", "#2f5d50", "#5a3e8c", "#0e6e8c", "#8c5a0e", "#8c2f2f", "#3e5a8c", "#4a6b2f")  # 그 밖의 회사 — 이름마다 정해진 색


def mark(name: str, size: str = "w-9 h-9") -> str:
    hit = next((g for g in GROUP if name.startswith(g[0])), None)
    if hit:
        text, bg, fg = hit[1], hit[2], hit[3]
    else:
        text, bg, fg = name[:1], OTHER[sum(map(ord, name)) % len(OTHER)], "#fff"
    fs = {1: "13px", 2: "11px" if text.isascii() else "10px"}.get(len(text), "8px" if len(text) <= 4 else "7px")
    return (f'<span class="{size} shrink-0 rounded-full flex items-center justify-center font-bold tracking-tight leading-none" '
            f'style="background:{bg};color:{fg};font-size:{fs}">{e(text)}</span>')  # fmt: skip


def logo(name: str, homepage: str | None, size: str = "w-9 h-9") -> str:
    """회사 로고 동그라미 — Brandfetch Logo API(무료·출처 표시 의무 없음, .env BRANDFETCH_CLIENT_ID).
    키나 도메인이 없거나 로고를 못 찾으면 첫 글자 동그라미. 로고는 「이 회사」를 알려주는 데만 쓴다(상표적 사용 아님)."""
    letter = mark(name, size)
    key = env().get("BRANDFETCH_CLIENT_ID", "")
    if not (key and homepage):
        return letter
    src = f"https://cdn.brandfetch.io/{quote(homepage)}/w/96/h/96/fallback/404?c={quote(key)}"
    return (f'<span class="{size} shrink-0 rounded-full overflow-hidden bg-surface-container-lowest border border-outline-variant/40 flex items-center justify-center">'
            f'<img alt="{e(name)} 로고" class="w-full h-full object-contain" loading="lazy" src="{e(src)}" '
            f'onerror="this.parentNode.outerHTML={e(json.dumps(letter))}"></span>')  # fmt: skip


DART_VIEW = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"


def business_block(biz: dict | None, rno: str | None) -> str:
    """무엇으로 돈을 버나요? — 회사 사업보고서 「사업의 내용」을 AI 가 요약(숫자는 원문 그대로인지 코드가 대조) + 부문별 매출 비중 막대."""
    if not biz:
        return ""
    segs = "".join(
        f'<div class="flex items-center gap-2 py-1"><span class="w-[44%] text-[12px] leading-4 text-on-surface-variant">{e(s["name"])}</span>'
        f'<span class="flex-1 h-2 rounded-full bg-surface-container overflow-hidden"><span class="block h-full bg-primary rounded-full" style="width:{min(float(s["share"][:-1]), 100):.1f}%"></span></span>'
        f'<span class="w-12 text-right text-[12px] font-semibold text-on-surface tabular-nums">{e(s["share"])}</span></div>' for s in biz.get("segments", []))  # fmt: skip
    link = f'<a class="text-outline underline" href="{DART_VIEW.format(rno)}" target="_blank" rel="noopener">사업보고서 원문</a>' if rno else ""
    return chapter("무엇으로 돈을 버나요?", " ".join(e(x) for x in biz["what"]),
                   (f'<div class="mt-space-xs"><div class="font-label-micro text-label-micro text-outline mb-1">부문별 매출 비중</div>{segs}</div>' if segs else "")
                   + f'<p class="font-label-micro text-label-micro text-outline">회사가 낸 {biz.get("year", "")}년 사업보고서를 요약했어요 · {link}</p>')  # fmt: skip


def dividend_block(divs: list[tuple]) -> str:
    """주주에게 돌려준 것 — 해마다 주당 현금배당금(보통주) 막대 + 최근 배당성향."""
    divs = [r for r in divs if r[1]]
    if not divs:
        return ""
    top = max(r[1] for r in divs)
    bars = "".join(f'<div class="flex-1 flex flex-col items-center gap-1"><span class="text-[10px] text-on-surface-variant tabular-nums">{r[1]:,}</span>'
                   f'<span class="w-full max-w-[28px] rounded-t bg-secondary/80" style="height:{max(r[1] / top * 72, 2):.0f}px"></span>'
                   f'<span class="text-[10px] text-outline">{r[0]}</span></div>' for r in divs)  # fmt: skip
    y, dps, total, payout = divs[-1]
    text = (f"{y}년에는 한 주에 {dps:,}원을 현금으로 나눠 줬어요" + (f"(배당 총액 {notes.won(total)})" if total else "") + "."
            + (f" 번 돈(순이익)의 {payout:.1f}%를 배당으로 쓴 셈이에요(배당성향)." if payout else ""))  # fmt: skip
    return chapter("주주에게 돌려준 것", e(text),
                   f'<div class="flex items-end gap-1 h-[110px] pt-2">{bars}</div>'
                   '<p class="font-label-micro text-label-micro text-outline">주당 현금배당금(보통주, 원) · 자료: DART 「배당에 관한 사항」</p>')  # fmt: skip


def risk_block(biz: dict | None) -> str:
    if not biz or not biz.get("risks"):
        return ""
    items = "".join(f'<li class="flex gap-2"><span class="material-symbols-outlined text-tertiary text-[16px] mt-1">error</span><span>{e(r)}</span></li>' for r in biz["risks"])
    return chapter("회사가 꼽은 위험", f'<ul class="flex flex-col gap-1.5">{items}</ul>',
                   '<p class="font-label-micro text-label-micro text-outline">회사가 사업보고서에 스스로 적은 위험이에요. 한장의 판단이 아니에요.</p>')  # fmt: skip


# 큰 업종 — 통계청 산업분류 코드 앞 두 자리로 묶는다 (도넛 조각을 열 개 안쪽으로)
SECTOR = [((10, 12), "식품·생활"), ((13, 19), "식품·생활"), ((20, 20), "화학·소재"), ((21, 21), "제약·바이오"),
          ((22, 23), "화학·소재"), ((24, 25), "철강·금속"), ((26, 27), "전자·반도체"), ((28, 29), "기계·전기"),
          ((30, 31), "자동차·운송장비"), ((32, 34), "식품·생활"), ((35, 36), "에너지"), ((41, 42), "건설"),
          ((45, 47), "유통"), ((49, 52), "운송·물류"), ((55, 56), "식품·생활"), ((58, 63), "IT·통신"),
          ((64, 66), "금융"), ((70, 70), "제약·바이오"), ((71, 71), "지주회사"), ((72, 73), "IT·통신")]  # fmt: skip


def sector(code: str | None) -> str | None:
    d = int(code[:2]) if code and code[:2].isdigit() else None
    return next((name for (lo, hi), name in SECTOR if d is not None and lo <= d <= hi), None)


DONUT = ("#154539", "#2a5649", "#40695c", "#5b8172", "#7b9a8d", "#9db5aa", "#c0d1c9", "#e1e9e5")  # 진한 초록부터 — 한장 색


def donut(labels: list[str | None]) -> str:
    """큰손 한눈에 — 5% 넘게 가진 회사들이 어떤 업종에 몰려 있나(곳 수 기준). 많은 7개 큰 업종 + 기타.
    지분율로 그리지 않는다 — 「그 회사 주식 중 몇 %」라서 도넛 조각으로 더하면 뜻이 없다."""
    if not labels:
        return ""
    from collections import Counter

    cnt = Counter(x or "기타" for x in labels)
    top = [(k, v) for k, v in cnt.most_common() if k != "기타"][:7]
    rest = len(labels) - sum(v for _, v in top)
    parts = top + ([("기타", rest)] if rest else [])
    total, r, c = len(labels), 15.915, 2 * 3.14159 * 15.915  # 둘레 100 짜리 원 — dasharray 가 곧 %
    acc, rings, keys = 0.0, [], []
    for (k, v), col in zip(parts, DONUT):
        pct = v / total * 100
        rings.append(f'<circle cx="21" cy="21" r="{r}" fill="none" stroke="{col}" stroke-width="7" '
                     f'stroke-dasharray="{pct:.2f} {100 - pct:.2f}" stroke-dashoffset="{25 - acc:.2f}"/>')  # fmt: skip
        keys.append(f'<li class="flex items-center gap-2 py-1"><span class="w-2.5 h-2.5 rounded-sm shrink-0" style="background:{col}"></span>'
                    f'<span class="flex-1 text-[13px] text-on-surface truncate">{e(k)}</span>'
                    f'<span class="text-[13px] font-semibold text-on-surface tabular-nums">{pct:.0f}%</span>'
                    f'<span class="w-10 text-right text-[11px] text-outline tabular-nums">{v}곳</span></li>')  # fmt: skip
        acc += pct
    return ('<section class="mt-space-lg"><h2 class="font-headline-sm text-headline-sm text-on-surface">어떤 업종에 많이 가졌나</h2>'
            '<div class="mt-2 flex items-center gap-4"><div class="relative w-36 h-36 shrink-0">'
            f'<svg viewBox="0 0 42 42" class="w-full h-full -rotate-0">{"".join(rings)}</svg>'
            f'<div class="absolute inset-0 flex flex-col items-center justify-center"><span class="text-[20px] font-bold text-on-surface leading-none">{total}</span>'
            '<span class="text-[11px] text-outline mt-0.5">곳</span></div></div>'
            f'<ul class="flex-1 min-w-0">{"".join(keys)}</ul></div>'
            '<p class="mt-1 text-[11px] text-outline">5% 넘게 가진 회사들을 큰 업종(통계청 산업분류)으로 나눠 센 비율이에요.</p></section>')  # fmt: skip


def price_chart(points: list[tuple[str, int]]) -> str:
    """토스처럼 — 종가 선 · 기간 안 최고·최저 · 1주/3달/1년. 올랐으면 빨강, 내렸으면 파랑(국내 관례).
    ⚠️ 개발 중 개인용만(PRICE_DEV) — 남에게 보이는 서버엔 그리지 않는다."""
    if len(points) < 5:
        return ""
    data = json.dumps([[d, v] for d, v in points])
    last, prev = points[-1][1], points[-2][1]
    diff = last - prev
    tone = "text-[#e0464c]" if diff > 0 else "text-[#3182f6]" if diff < 0 else "text-on-surface-variant"
    btn = "px-3 py-1 rounded-lg font-label-regular text-label-regular text-on-surface-variant"
    return ('<figure class="mb-space-lg">'
            f'<div class="flex items-baseline gap-2"><span class="font-headline-lg text-headline-lg text-on-surface">{last:,}원</span>'
            f'<span class="font-label-regular text-label-regular {tone}">어제보다 {diff:+,}원 ({diff / prev * 100:+.1f}%)</span></div>'
            '<svg id="pc" viewBox="0 0 340 170" class="w-full h-auto mt-2" role="img" aria-label="주가 흐름"></svg>'
            '<div class="flex justify-around mt-1">' + "".join(f'<button type="button" class="{btn}" data-d="{d}">{t}</button>' for d, t in ((7, "1주"), (91, "3달"), (365, "1년")))
            + '</div><p class="mt-1 font-label-micro text-label-micro text-tertiary">⚠️ 개발용 — 주가는 개인용으로만 받은 것이라 남에게 보여주면 안 돼요. 하루 늦은 종가예요.</p></figure>'
            "<script>(()=>{const P=" + data + ";const svg=document.getElementById('pc');"
            "function draw(days){const end=new Date(P[P.length-1][0]);const from=new Date(end-days*864e5);const p=P.filter(x=>new Date(x[0])>=from);"
            "const v=p.map(x=>x[1]);const hi=Math.max(...v),lo=Math.min(...v);const W=340,H=170,T=22,B=22,span=(hi-lo)||1;"
            "const X=i=>8+i*(W-16)/Math.max(p.length-1,1),Y=y=>T+(hi-y)/span*(H-T-B);"
            "const up=v[v.length-1]>=v[0],c=up?'#e0464c':'#3182f6';const hiI=v.indexOf(hi),loI=v.indexOf(lo);"
            "const lbl=(i,y,t,dy)=>{const x=Math.min(Math.max(X(i),48),W-48);return `<text x='${x}' y='${Y(y)+dy}' text-anchor='middle' font-size='11' fill='${c}'>${t} ${y.toLocaleString()}원</text>`};"
            "svg.innerHTML=`<polyline fill='none' stroke='${c}' stroke-width='2' stroke-linejoin='round' points='${p.map((x,i)=>X(i)+','+Y(x[1])).join(' ')}'/>`"
            "+`<circle cx='${X(hiI)}' cy='${Y(hi)}' r='2.5' fill='${c}'/>`+`<circle cx='${X(loI)}' cy='${Y(lo)}' r='2.5' fill='${c}'/>`"
            "+lbl(hiI,hi,'최고',-8)+lbl(loI,lo,'최저',16);"
            "document.querySelectorAll('[data-d]').forEach(b=>b.classList.toggle('bg-surface-container-high',+b.dataset.d===days));}"
            "document.querySelectorAll('[data-d]').forEach(b=>b.onclick=()=>draw(+b.dataset.d));draw(91);})();</script>")  # fmt: skip


def photo_url(uid: int, at: str | None) -> str | None:
    return f"/p/{uid}.jpg?v={quote(at)}" if at else None


def top_bar(initial: str) -> str:
    return ('<header class="fixed top-0 w-full z-50 bg-surface/90 backdrop-blur-xl pt-safe"><div class="h-14 max-w-[480px] mx-auto px-margin flex items-center justify-between"><div class="flex items-center gap-space-sm"><span class="font-display-editorial text-headline-md text-primary tracking-tight">한장</span><span class="text-on-surface-variant font-label-micro text-label-micro uppercase tracking-wider pl-space-xs">Editorial Digest</span></div><div class="flex items-center gap-space-sm">'
            + avatar(initial) + "</div></div></header>")  # fmt: skip


TABS = (("cards", "/", "newspaper", "내 종목"), ("feed", "/feed", "dynamic_feed", "피드"), ("calendar", "/calendar", "calendar_today", "캘린더"),
        ("learn", "/learn", "menu_book", "읽기 팁"), ("me", "/me", "person", "프로필"))  # fmt: skip


def bottom_nav(tab: str) -> str:
    on = "transition-colors text-primary-container font-semibold"
    off = "text-on-surface-variant hover:text-on-surface transition-colors"
    return ('<nav class="fixed bottom-0 w-full z-50 pb-safe bg-surface/90 backdrop-blur-xl"><div class="max-w-[480px] mx-auto h-14 flex items-center justify-around px-1">'
            + "".join(f'<a {"aria-current=page " if tab == k else ""}class="flex flex-col items-center justify-center min-w-[44px] min-h-[44px] px-1 {on if tab == k else off}" href="{href}">'
                      f'<span class="material-symbols-outlined text-[22px]">{icon}</span><span class="font-label-micro text-label-micro mt-0.5">{label}</span></a>'
                      for k, href, icon, label in TABS)
            + "</div></nav>")  # fmt: skip


def safe_url(u: str) -> str:
    return u if u.startswith(("https://", "http://")) else "#"


# --- 우리가 쓴 고정 풀이 (공시 내용을 지어내지 않는다 — 낱말·공시 종류의 뜻만) ---


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
EVENT_SHORT = {"BUYBACK": "자사주", "DIVIDEND": "배당", "EARNINGS": "실적", "MAJOR_CONTRACT": "계약",
               "RIGHTS_ISSUE": "증자", "BONUS_ISSUE": "무상증자", "CB_BW": "전환사채", "LAWSUIT": "소송",
               "MA": "합병·인수", "HOLDER_CHANGE": "대주주", "CLINICAL": "임상", "TRADING_HALT": "거래정지",
               "SPLIT": "분할", "REVERSE_SPLIT": "병합", "OTHER": "기타"}  # fmt: skip
TIPS = {  # 주주를 위한 읽기 팁 — 이 달에 가장 많은 공시 종류에 맞춰
    "BUYBACK": ("자사주 취득 공시는 소각 여부까지 함께 확인해요", "사둔 주식을 없애야(소각) 시중에 도는 주식 수가 실제로 줄어요."),
    "DIVIDEND": ("배당 공시는 기준일을 함께 확인해요", "기준일에 주식을 갖고 있어야 배당을 받아요."),
    "EARNINGS": ("실적 공시는 '잠정'인지 확인해요", "잠정 실적은 나중에 확정치와 조금 달라질 수 있어요."),
    "MAJOR_CONTRACT": ("계약 공시는 회사 매출에 비한 크기를 봐요", "같은 금액이라도 회사 크기에 따라 무게가 달라요."),
    "RIGHTS_ISSUE": ("유상증자는 모은 돈을 어디에 쓰는지 봐요", "시설 투자인지 빚 갚기인지에 따라 뜻이 달라요."),
    "CB_BW": ("전환사채는 전환 가격을 함께 봐요", "주식으로 바뀌면 주식 수가 늘어 기존 주주 몫이 묽어질 수 있어요."),
}
TIP_DEFAULT = ("공시 원문은 DART에서 누구나 볼 수 있어요", "번호를 누르면 금융감독원 전자공시 원문이 열려요.")
FACT_SHORT = {"F1": "매출", "F2": "영업이익", "F3": "부채비율", "F4": "ROE"}
# 출처 번호는 읽기를 방해하지 않게 — 본문보다 작은 회색 위첨자 (사용자 10/7). 누르면 출처 창
CITE = "align-super ml-0.5 text-[9px] leading-none font-normal text-outline/70 hover:text-on-surface-variant transition-colors"


def short_name(name: str) -> str:
    """달력 칩용 — 「SK하이닉스」→「SK」, 「삼성전자」→「삼성」."""
    m = re.match(r"[A-Za-z&]+", name)
    return m[0] if m else name[:2]


def clean_title(title: str, code: str) -> str:
    """「[기재정정]주요사항보고서(자기주식취득결정)」 → 「자기주식취득결정 (자사주 매입)」."""
    t = re.sub(r"^\[[^\]]*\]", "", title).strip()
    t = re.sub(r"^주요사항보고서\((.+)\)$", r"\1", t)
    ko = notes.EVENT_KO.get(code, "")
    return f"{t} ({ko})" if ko and ko not in t and code != "OTHER" else t


def sentence(s: dict) -> str:
    """문장 + 시안의 출처 단추 [F1] — 누르면 출처 창이 열린다 (모든 문장에 원문 링크, 불변식 2)."""
    btns = "".join(f'<button aria-label="출처 {e(r)} 보기" class="{CITE}" onclick="toggleCitation(\'{e(r)}\')" type="button">[{e(r)}]</button>'
                   for r in s["refs"])  # fmt: skip
    return f"{e(s['text'])}{btns}"


def cite_data(facts: list[dict]) -> dict:
    """출처 창에 넣을 실제 값 — 시안의 가짜 설명 대신 코드가 만든 사실 문장과 원문 링크."""
    out = {}
    for f in facts:
        k = f["id"][0]
        rno = re.search(r"rcpNo=(\d+)", f["url"])
        out[f["id"]] = {
            "badge": f"[{f['id']}]",
            "title": {"F": "금융감독원 전자공시시스템 (DART) · 사업보고서",
                      "D": "금융감독원 전자공시시스템 (DART) · 공시",
                      "I": "금융감독원 전자공시시스템 (DART) · 지분 보고"}.get(k, f"{f.get('slots', {}).get('매체', '')} 기사"),
            "body": f["text"],
            "meta": f"공시접수번호: {rno[1]}" if rno else f"기사 날짜: {f.get('slots', {}).get('날짜', '')}",
            "url": safe_url(f["url"]),
        }  # fmt: skip
    return out


def metrics(facts: list[dict]) -> str:
    """주요 실적 한눈에 보기 — F1(매출)·F2(영업이익)의 코드 값. 막대 길이는 두 변화율 중 큰 쪽을 꽉 찬 것으로 본 상대 길이."""
    rows = [(FACT_SHORT[f["id"]] + ("액" if f["id"] == "F1" else ""), f["slots"])
            for f in facts if f["id"] in ("F1", "F2") and "값" in f.get("slots", {})]  # 빈칸 값이 없는 옛 노트는 건너뛴다
    if not rows:
        return ""
    unit = "조원" if all(s["값"].endswith("조원") for _, s in rows) else ""
    nums = {i: abs(float(s["변화"][:-1])) for i, (_, s) in enumerate(rows) if re.fullmatch(r"[+-][\d.]+%", s.get("변화", ""))}
    top = max(nums.values(), default=0) or 1
    cells = []
    for i, (label, s) in enumerate(rows):
        chg = s.get("변화", "")
        tone = "text-secondary" if chg.startswith("+") or chg == "흑자 전환" else "text-tertiary"
        width = round(nums.get(i, 0) / top * 100)
        cells.append(f'<div class="py-1"><div class="font-label-micro text-label-micro text-on-surface-variant">{e(label)}</div>'
                     f'<div class="flex items-baseline gap-1.5 mt-0.5"><span class="font-headline-sm text-headline-sm text-on-surface">{e(s["값"].removesuffix(unit) if unit else s["값"])}</span>'
                     f'<span class="font-label-micro text-label-micro {tone} font-semibold">{e(chg)}</span></div>'
                     f'<div class="w-full bg-surface-container h-1 rounded-full mt-2 overflow-hidden"><div class="{"bg-primary" if i == 0 else "bg-secondary"} h-full rounded-full" style="width: {width}%;"></div></div></div>')  # fmt: skip
    return ('<div class="py-space-md my-space-xs border-y border-outline-variant/30"><div class="flex justify-between items-center mb-space-sm">'
            '<span class="font-label-regular text-label-regular text-on-surface font-semibold">주요 실적 한눈에 보기</span>'
            f'<span class="font-label-micro text-label-micro text-on-surface-variant">{"단위: 조원 " if unit else ""}(전년대비)</span></div>'
            f'<div class="grid grid-cols-2 gap-space-md">{"".join(cells)}</div></div>')  # fmt: skip


def chapter(title: str, body: str, extra: str = "") -> str:
    return ('<article class="mb-space-xl flex flex-col gap-space-sm"><div class="flex items-center gap-2"><span class="w-2 h-2 rounded-full bg-primary"></span>'
            f'<h3 class="font-headline-md text-headline-md text-on-surface">{e(title)}</h3></div>'
            f'<div class="font-body-reading text-body-reading text-on-surface leading-loose">{body}</div>{extra}</article>')  # fmt: skip


def index_chart(got: dict) -> str:
    """한국·미국 주가지수 선 그림 — 세로는 로그 눈금(같은 % 변화가 같은 높이). 한국 자료가 시작된 달부터."""
    import math

    start = got["한국"]["from"]
    lines = {n: [(d, v) for d, v in g["series"] if d >= start] for n, g in got.items()}
    ds = sorted({d for pts in lines.values() for d, _ in pts})
    lo, hi = (f(math.log(v) for pts in lines.values() for _, v in pts) for f in (min, max))
    W, H, P = 340, 180, 24

    def xy(d, v):
        return f"{P + (ds.index(d) / (len(ds) - 1)) * (W - P - 4):.1f},{H - 18 - (math.log(v) - lo) / (hi - lo) * (H - 30):.1f}"

    color = {"한국": "text-primary", "미국": "text-secondary"}
    polys = "".join(f'<polyline class="{color.get(n, "text-outline")}" fill="none" stroke="currentColor" stroke-width="1.6"{' stroke-dasharray="3 2"' if n != "한국" else ""} points="{" ".join(xy(d, v) for d, v in pts)}"/>'
                    for n, pts in lines.items())  # fmt: skip
    years = sorted({d[:4] for d in ds if d[:4].endswith(("0", "5")) and d[5:7] == "01"})
    ticks = "".join(f'<text x="{xy(f"{y}-01-01", math.exp(lo)).split(",")[0]}" y="{H - 4}" font-size="9" text-anchor="middle" fill="currentColor" class="text-outline">{y}</text>'
                    for y in years if f"{y}-01-01" in ds and int(y) % 10 == 0)  # fmt: skip
    legend = " ".join(f'<span class="inline-flex items-center gap-1"><span class="w-4 {color.get(n, "")} border-t-2 {"border-dashed" if n != "한국" else ""} border-current"></span>{e(n)}</span>' for n in lines)
    return ('<figure class="my-space-md"><figcaption class="font-label-regular text-label-regular text-on-surface font-semibold mb-1">주가지수 흐름 (로그 눈금)</figcaption>'
            f'<svg viewBox="0 0 {W} {H}" class="w-full h-auto" role="img" aria-label="한국과 미국 주가지수 흐름">{polys}{ticks}</svg>'
            f'<div class="flex gap-3 font-label-micro text-label-micro text-on-surface-variant">{legend}</div></figure>')  # fmt: skip


def loss_bars(got: dict) -> str:
    """보유 기간별 「손해였던 비율」 막대 — 한국·미국 나란히."""
    labels = [r["label"] for r in got["한국"]["rows"]]
    color = {"한국": "bg-primary", "미국": "bg-secondary"}
    rows = []
    for lab in labels:
        cells = []
        for n, g in got.items():
            r = next((x for x in g["rows"] if x["label"] == lab), None)
            if r:
                w = round(r["loss"] * 100)
                cells.append(f'<div class="flex items-center gap-2"><span class="w-7 font-label-micro text-label-micro text-outline">{e(n)}</span>'
                             f'<div class="flex-1 h-2 rounded-full bg-surface-container overflow-hidden"><div class="{color.get(n, "bg-outline")} h-full rounded-full" style="width:{w}%"></div></div>'
                             f'<span class="w-9 text-right font-label-micro text-label-micro text-on-surface">{w}%</span></div>')  # fmt: skip
        rows.append(f'<div class="flex items-start gap-3 py-1.5"><span class="w-10 pt-0.5 font-label-regular text-label-regular text-on-surface font-semibold">{e(lab)}</span><div class="flex-1 flex flex-col gap-1">{"".join(cells)}</div></div>')
    return ('<figure class="my-space-md"><figcaption class="font-label-regular text-label-regular text-on-surface font-semibold">이만큼 들고 있었다면 — 손해였던 비율</figcaption>'
            '<p class="font-label-micro text-label-micro text-on-surface-variant mb-1">아무 달에나 사서 그 기간 뒤에 팔았다고 치고, 손해였던 경우를 셌어요.</p>'
            + "".join(rows)
            + '<p class="font-label-micro text-label-micro text-outline mt-1">자료: OECD 주가지수(월평균, 2015=100) · 한국은행 ECOS에서 받음. 배당은 빠져 있고, 하루하루 출렁임은 이보다 커요.</p></figure>')  # fmt: skip


def md(made: str) -> str:
    """「2026-10-08T07:00」 → 「10월 8일」 — 노트를 쓴(고친) 날."""
    return f"{int(made[5:7])}월 {int(made[8:10])}일" if re.match(r"\d{4}-\d{2}-\d{2}", made or "") else ""


def no_news(body: dict) -> dict:
    """노트에서 기사(N) 흔적을 뺀다 — 「요즘 기사」 절, 근거가 기사뿐인 문장, 언론 키워드."""
    def keep(xs):
        return [x for x in xs if not x["refs"] or not all(r.startswith("N") for r in x["refs"])]

    return body | {"summary": keep(body.get("summary", [])), "good": keep(body.get("good", [])), "concern": keep(body.get("concern", [])),
                   "sections": [sec | {"sentences": keep(sec["sentences"])} for sec in body["sections"] if not sec["title"].startswith("요즘 기사")],
                   "keywords": []}  # fmt: skip


def redone(week: str, made: str) -> str:
    """주 중간에 다시 쓴 노트면 「 · 10월 8일 고침」 — 월요일에 쓴 그대로면 빈 글."""
    d = date.fromisoformat(made[:10]) if re.match(r"\d{4}-\d{2}-\d{2}", made or "") else None
    return f" · {d.month}월 {d.day}일 고침" if d and d.isoformat() > week else ""


def render_note(name: str, ticker: str, week: str, body: dict, writer: str, facts: list[dict] | None = None,
                industry: str | None = None, initial: str = "", survey: str = "", made: str = "", homepage: str | None = None,
                stats: tuple[int, int, bool] = (0, 0, False), regram: str = "",
                prices: list | None = None, report: dict | None = None) -> str:
    """report = {"divs": [(연도, 주당배당, 총액, 배당성향)], "biz": 요약, "rno": 사업보고서}."""
    report = report or {}
    if not sources.news_dev():  # 기사를 꺼 둔 곳(서버·남에게 보여줄 때)에선 예전 노트의 기사 칸·기사만 근거인 문장도 그리지 않는다
        body = no_news(body)
    """stats = (이 주 노트를 연 횟수, 좋아요 수, 내가 눌렀나)."""
    facts = facts or []
    head = ('<header class="fixed top-0 w-full z-50 bg-surface/90 backdrop-blur-xl pt-safe"><div class="h-14 max-w-[480px] mx-auto px-margin flex items-center justify-between"><div class="flex items-center gap-space-sm"><button class="w-11 h-11 flex items-center justify-center text-on-surface hover:text-primary transition-colors -ml-space-xs" onclick="location.href=\'/\'"><span class="material-symbols-outlined text-[22px]">arrow_back</span></button><h1 class="font-headline-sm text-headline-sm text-on-surface tracking-tight truncate max-w-[200px]">Note</h1></div><div class="flex items-center gap-space-sm">'
            + avatar(initial) + '</div></div></header>')  # fmt: skip
    parts = [
        # 머리 — 로고·이름 한 줄, 업종 · 날짜 · 읽음 한 줄 (글자를 줄였다, 사용자 10/8)
        f'<header class="mt-space-sm mb-space-lg"><div class="flex items-center gap-2.5">{logo(name, homepage, "w-10 h-10")}'
        f'<h2 class="font-display-editorial text-display-editorial text-on-surface font-semibold tracking-tight">{e(name)}</h2></div>'
        f'<p class="mt-1.5 text-[12px] text-outline">{e(" · ".join(x for x in (industry_label(industry), md(made), f"읽음 {stats[0]:,}") if x))}</p></header>',
        price_chart(prices) if prices else "",
        f'<aside class="mb-space-lg py-space-md px-space-lg bg-surface-container-low rounded-xl border-l-2 border-primary relative"><p class="font-body-reading-strong text-body-reading-strong text-primary leading-relaxed">"{e(body["headline"])}"</p></aside>',
    ]  # fmt: skip
    if body.get("summary"):
        parts.append('<section class="mb-space-xl pl-space-md py-1 border-l-2 border-primary/60"><div class="flex items-center gap-1.5 mb-1"><span class="material-symbols-outlined text-primary text-[18px]">auto_stories</span><span class="font-label-micro text-label-micro uppercase tracking-wider text-primary font-bold">한 장 요약</span></div>'
                     f'<p class="font-body-reading text-body-reading text-on-surface leading-relaxed">{" ".join(sentence(s) for s in body["summary"])}</p></section>')  # fmt: skip
    parts.append(business_block(report.get("biz"), report.get("rno")))
    nd = sum(f["id"][0] == "D" for f in facts)
    good_d, bad_d = sum(f["id"][0] == "D" and f["tone"] == 1 for f in facts), sum(f["id"][0] == "D" and f["tone"] == -1 for f in facts)
    for sec in body["sections"]:
        text = " ".join(sentence(s) for s in sec["sentences"])
        extra = ""
        if sec["title"].startswith("회사 사정"):
            extra = metrics(facts)
        elif sec["title"].startswith("요즘 무슨"):
            right = (f"반가운 쪽 {good_d}" + (f" · 걸리는 쪽 {bad_d}" if bad_d else "")) if good_d or bad_d else "분류 완료"
            extra = ('<div class="py-space-sm flex items-center justify-between border-t border-outline-variant/30 mt-space-xs"><div class="flex items-center gap-space-sm"><span class="material-symbols-outlined text-secondary text-[18px]">assignment_turned_in</span><div class="flex items-center gap-2">'
                     f'<span class="font-label-regular text-label-regular text-on-surface font-medium">최근 주요 공시 {nd}건 집계</span><span class="font-label-micro text-label-micro text-on-surface-variant">· DART 기준 자동 분류</span></div></div>'
                     f'<span class="font-label-micro text-label-micro text-secondary font-semibold">{e(right)}</span></div>')  # fmt: skip
        elif sec["title"].startswith("임원·큰손"):
            extra = ('<p class="font-label-micro text-label-micro text-outline leading-normal">임원 보고에는 회사에서 받은 주식(보상)도 들어가요. '
                     "누가 늘리고 줄였는지는 사실일 뿐, 따라 사고팔라는 뜻이 아니에요.</p>")  # fmt: skip
        elif sec["title"].startswith("요즘 기사") and body.get("keywords"):
            extra = ('<div class="pt-space-sm pb-1 flex flex-col gap-1.5 border-t border-outline-variant/30 mt-space-xs"><div class="font-label-micro text-label-micro text-outline font-semibold uppercase">언론 키워드 흐름</div><div class="flex flex-wrap gap-2">'
                     + "".join(f'<span class="py-0.5 text-on-surface-variant text-label-micro font-label-micro">{e(k)}</span>' for k in body["keywords"])
                     + "</div></div>")  # fmt: skip
        if sec["title"].startswith("요즘 기사"):
            extra += '<p class="font-label-micro text-label-micro text-tertiary">⚠️ 개발용 — 기사 제목은 개인용으로만 모은 것이라 남에게 보여주면 안 돼요.</p>'
        parts.append(chapter(sec["title"], text, extra))
        if sec["title"].startswith("요즘 무슨"):
            parts.append(dividend_block(report.get("divs", [])))
    if not any(s["title"].startswith("요즘 무슨") for s in body["sections"]):
        parts.append(dividend_block(report.get("divs", [])))
    parts.append(risk_block(report.get("biz")))

    def filled(key):  # 옛 노트의 「분류된 것 없음」 자리 채움 문장도 빈 칸으로 본다
        return [] if body.get(f"{key}_title") == "분류된 것 없음" else body.get(key) or []

    if filled("good") or filled("concern"):
        def side(label, title, items, bar, chip, ink):
            if not items:
                return ""
            return (f'<div class="pl-space-md py-1 border-l-2 {bar} flex flex-col gap-1"><div class="flex items-center gap-1.5">'
                    f'<span class="px-2 py-0.5 rounded text-label-micro font-label-micro font-semibold {chip}">{label}</span>'
                    f'<span class="font-label-regular text-label-regular {ink} font-semibold">{e(title)}</span></div>'
                    f'<p class="font-body-reading text-body-reading text-on-surface leading-relaxed">{" ".join(sentence(s) for s in items)}</p></div>')  # fmt: skip
        parts.append('<section class="mb-space-xl flex flex-col gap-space-md"><div class="flex items-center gap-2"><span class="w-2 h-2 rounded-full bg-primary"></span><h3 class="font-headline-md text-headline-md text-on-surface">긍정 요인과 부정 요인</h3></div>'
                     + side("긍정", body.get("good_title", ""), filled("good"), "border-secondary/60", "bg-secondary-container text-on-secondary-container", "text-secondary")
                     + side("부정", body.get("concern_title", ""), filled("concern"), "border-tertiary/60", "bg-tertiary-fixed text-on-tertiary-fixed-variant", "text-tertiary")
                     + '<span class="font-label-micro text-label-micro text-outline leading-normal pt-1">긍정·부정 요인은 코드가 정한 기준으로 분류했어요 — 매출·영업이익 증감, 부채비율, ROE, 공시 종류. <a class="underline" href="/method">기준 보기</a></span></section>')  # fmt: skip
    how = ("기사·공시·재무에서 코드가 뽑은 사실을 바탕으로 AI가 문장을 다듬었어요. 숫자는 코드가 원문과 대조했어요."
           if writer.startswith("llm") else "기사·공시·재무에서 코드가 뽑은 사실을 그대로 옮겼어요.")  # fmt: skip
    views, likes, liked = stats
    faces = "".join('<span class="w-7 h-7 rounded-full bg-surface-container-high border-2 border-surface flex items-end justify-center overflow-hidden -ml-2 first:ml-0">'
                    '<span class="material-symbols-outlined text-outline text-[22px] translate-y-1" style="font-variation-settings: \'FILL\' 1;">person</span></span>'
                    for _ in range(min(likes, 3)))  # fmt: skip  누가 눌렀는지는 보여주지 않는다 — 모양만
    parts.append(f'<div class="mb-space-lg flex items-center justify-end gap-space-md"><form method="post" action="/like" class="flex items-center gap-space-sm"><input type="hidden" name="t" value="{e(ticker)}"><input type="hidden" name="w" value="{e(week)}">'
                 f'<button type="submit" aria-pressed="{"true" if liked else "false"}" aria-label="좋아요{" 취소" if liked else ""}" class="w-10 h-10 rounded-full flex items-center justify-center border {"border-tertiary/40 bg-tertiary-fixed/50" if liked else "border-outline-variant/60"} transition-colors">'
                 f'<span class="material-symbols-outlined text-[20px] {"text-tertiary" if liked else "text-outline"}" style="font-variation-settings: \'FILL\' {1 if liked else 0};">favorite</span></button>'
                 f'<span class="flex items-center">{faces}</span><span class="font-label-regular text-label-regular text-on-surface-variant font-semibold">좋아요 {likes:,}개</span></form>{regram}</div>')  # fmt: skip
    parts.append(survey)
    parts.append('<footer class="pt-space-lg pb-space-lg mt-space-sm border-t border-outline-variant/40 flex flex-col gap-space-sm"><div class="flex items-center gap-1.5 text-on-surface font-headline-sm text-headline-sm font-semibold"><span class="material-symbols-outlined text-primary text-[20px]">verified</span><span class="">작성 기준 및 검증 안내</span></div>'
                 f'<p class="font-body-compact text-body-compact text-on-surface-variant leading-relaxed">{how} <span class="text-outline">[F1]</span>, <span class="text-outline">[D1]</span> 같은 작은 번호를 누르면 금융감독원 전자공시(DART)나 기사 원문이 열려요. <a class="text-primary underline" href="/method">계산 방법</a></p>'
                 '<div class="pt-1"><p class="font-label-regular text-label-regular text-on-surface leading-relaxed font-medium">사라·팔아라는 의견도, 목표주가도, 앞으로의 예측도 없어요. 투자 판단은 본인이 해요.</p></div></footer>')  # fmt: skip
    dialog = ('<div class="fixed inset-0 z-50 bg-on-surface/40 backdrop-blur-sm hidden items-end justify-center px-margin pb-6" id="citation-dialog" onclick="closeCitation(event)"><div class="bg-surface-container-lowest w-full max-w-[440px] rounded-2xl p-space-lg shadow-xl flex flex-col gap-space-sm" onclick="event.stopPropagation()"><div class="flex items-center justify-between"><div class="flex items-center gap-2"><span class="px-2 py-0.5 rounded font-citation-ref text-citation-ref bg-primary-fixed text-on-primary-fixed font-bold" id="citation-badge"></span><span class="font-label-regular text-label-regular font-bold text-on-surface" id="citation-title"></span></div><button class="w-8 h-8 rounded-full flex items-center justify-center text-on-surface-variant hover:bg-surface-container" onclick="hideCitation()" type="button"><span class="material-symbols-outlined text-[20px]">close</span></button></div><div class="font-body-compact text-body-compact text-on-surface-variant leading-relaxed" id="citation-body"></div><div class="flex items-center justify-between pt-2"><span class="font-label-micro text-label-micro text-outline font-mono" id="citation-meta"></span><a class="inline-flex items-center gap-1 font-label-regular text-label-regular text-primary font-semibold hover:underline" href="#" id="citation-link" rel="noopener noreferrer" target="_blank">원문 확인<span class="material-symbols-outlined text-[14px]">open_in_new</span></a></div></div></div>'
              # JSON 안의 </script> 를 막으려고 < 를 < 로
              "<script>const citations = " + json.dumps(cite_data(facts), ensure_ascii=False).replace("<", "\\u003c") + ";"
              "function toggleCitation(id){const d=citations[id];if(!d)return;document.getElementById('citation-badge').innerText=d.badge;document.getElementById('citation-title').innerText=d.title;document.getElementById('citation-body').innerText=d.body;document.getElementById('citation-meta').innerText=d.meta;document.getElementById('citation-link').href=d.url;const g=document.getElementById('citation-dialog');g.classList.remove('hidden');g.classList.add('flex');}"
              "function hideCitation(){const g=document.getElementById('citation-dialog');g.classList.add('hidden');g.classList.remove('flex');}"
              "function closeCitation(ev){if(ev.target.id==='citation-dialog')hideCitation();}</script>")  # fmt: skip
    inner = (head + '<main class="flex flex-col relative w-full max-w-[480px] mx-auto pt-14 pb-safe bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-space-xl">'
             + "".join(parts) + dialog + "</div></main>")  # fmt: skip
    return page(name, "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)


TONE_TAG = {1: ("긍정", "bg-secondary-fixed/70 text-on-secondary-fixed-variant"),
            -1: ("부정", "bg-tertiary-fixed text-on-tertiary-fixed-variant"),
            0: ("중립", "bg-surface-container text-on-surface-variant")}  # fmt: skip


# --- 앱 ---


class App:
    def __init__(self, con: sqlite3.Connection, secret: str, clock=time.time) -> None:
        self.con, self.secret, self.clock = con, secret, clock
        self.sent: dict[str, list[float]] = {}
        self.scans: dict[int, list[float]] = {}  # ponytail: 캡처 읽기 시각 — 메모리에. 여러 대면 DB 로  # ponytail: 링크 요청 시각을 메모리에 — 서버를 다시 켜면 비워진다. 여러 대면 DB 로

    def __call__(self, environ, start_response):
        method, path = environ["REQUEST_METHOD"], environ.get("PATH_INFO", "/")
        form = {}
        if method == "POST":
            n = int(environ.get("CONTENT_LENGTH") or 0)
            if n > BODY_MAX:
                start_response("413 Payload Too Large", [("Content-Type", "text/plain; charset=utf-8")])
                return ["사진이 너무 커요".encode()]
            raw = environ["wsgi.input"].read(n).decode()
            if environ.get("CONTENT_TYPE", "").startswith("application/json"):
                form = {"_json": json.loads(raw or "{}")}
            else:
                form = {k: v[0] for k, v in parse_qs(raw).items()}
        query = {k: v[0] for k, v in parse_qs(environ.get("QUERY_STRING", "")).items()}
        cookie = dict(c.strip().split("=", 1) for c in environ.get("HTTP_COOKIE", "").split(";") if "=" in c)
        uid = unsign(cookie.get("s", ""), self.secret)
        status, headers, body = self.route(method, path, form, query, int(uid) if uid else None)
        kind = [] if any(k == "Content-Type" for k, _ in headers) else [("Content-Type", "text/html; charset=utf-8")]
        start_response(status, [*kind, ("X-Content-Type-Options", "nosniff"),
                                ("X-Frame-Options", "DENY"), ("Referrer-Policy", "same-origin"), *headers])  # fmt: skip
        return [body if isinstance(body, bytes) else body.encode()]

    def see(self, to: str, *headers) -> tuple:
        return "303 See Other", [("Location", to), *headers], ""

    def log(self, uid: int, page_: str, ticker: str | None = None) -> None:
        self.con.execute("insert into views (user_id, page, ticker, at) values (?, ?, ?, ?)",
                         (uid, page_, ticker, datetime.now().isoformat()))  # fmt: skip
        self.con.commit()

    def initial(self, uid: int) -> str:
        """위쪽 동그라미에 넣을 것 — 사진 주소, 없으면 이메일 첫 글자."""
        row = self.con.execute("select email, photo_at from users where id = ?", (uid,)).fetchone()
        return (photo_url(uid, row[1]) or row[0][:1]) if row else "?"

    def simple(self, title: str, msg: str) -> str:
        return page(title, "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen",
                    f'<main class="w-full max-w-[480px] mx-auto px-margin pt-14"><p class="font-body-reading text-body-reading">{msg}</p></main>')  # fmt: skip

    def route(self, method, path, form, query, uid):
        if path == "/login" and method == "POST":
            return self.login(form.get("email", "").strip().lower(), form.get("agree") == "1")
        if path.startswith("/static/photos/") and re.fullmatch(r"(pool/)?[a-z]+\d*\.jpg", path[15:]) and (STATIC / "photos" / path[15:]).exists():
            return "200 OK", [("Content-Type", "image/jpeg"), ("Cache-Control", "public, max-age=604800")], (STATIC / "photos" / path[15:]).read_bytes()
        if path in ("/privacy", "/method", "/help/login"):  # 로그인 없이 열린다
            return "200 OK", [], self.doc(path, uid)
        if path == "/auth":
            email = check_login(query.get("t", ""), self.secret, self.clock())
            if not email:
                return "200 OK", [], self.simple("로그인", "링크가 만료됐거나 잘못됐어요. <a class='text-primary underline' href='/'>다시 받기</a>")
            self.con.execute("insert or ignore into users (email, created_at) values (?, ?)",
                             (email, datetime.now().isoformat()))  # fmt: skip
            self.con.commit()
            (u,) = self.con.execute("select id from users where email = ?", (email,)).fetchone()
            ck = f"s={sign(str(u), self.secret)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=7776000"
            if mail.base_url().startswith("https://"):
                ck += "; Secure"
            return self.see("/", ("Set-Cookie", ck))
        if path == "/demo":  # 둘러보기 — 이메일 없이 공용 계정으로 (메일 보내기 전, 남에게 보여줄 때)
            return self.demo()
        if uid is None:
            return "200 OK", [], self.login_page()
        if method == "POST" and self.is_demo(uid):  # 둘러보기는 보기만 — 여럿이 같이 쓰는 계정이라 바꾸지 않는다
            return "200 OK", [], self.simple("둘러보기", "둘러보기에서는 보기만 할 수 있어요. 직접 쓰려면 로그인해 주세요. "
                                             "<a class='text-primary underline' href='javascript:history.back()'>돌아가기</a>")
        if path == "/logout":
            return self.see("/", ("Set-Cookie", "s=; Path=/; Max-Age=0"))
        # 닉네임은 가입할 때 받는다 — 정하기 전엔 다른 화면으로 못 간다 (사람 찾기·피드에 쓰이니 겹치면 안 된다)
        if not self.con.execute("select nickname from users where id = ?", (uid,)).fetchone()[0]:
            if path == "/welcome" and method == "POST":
                return self.welcome(uid, form.get("nickname", "").strip())
            return "200 OK", [], self.welcome_page()
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
        if path == "/follow" and method == "POST":  # 한 번 더 누르면 언팔로우
            other = int(form["u"]) if form.get("u", "").isdigit() else 0
            if other != uid and self.con.execute("select 1 from users where id = ? and nickname is not null", (other,)).fetchone():
                if not self.con.execute("delete from follows where follower_id = ? and followee_id = ?", (uid, other)).rowcount:
                    self.con.execute("insert into follows values (?, ?, ?)", (uid, other, datetime.now().isoformat()))
                self.con.commit()
            return self.see(f"/u/{other}" if other else "/feed")
        if path == "/regram" and method == "POST":
            return self.regram(uid, form)
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
        if path == "/me/mail" and method == "POST":
            self.con.execute("update users set mail_on = 1 - mail_on where id = ?", (uid,))
            self.con.commit()
            return self.see("/me/settings")
        if path == "/me/delete" and method == "POST":
            # 탈퇴 — 이 사용자의 모든 행을 지운다 (되돌릴 수 없음, 화면에서 한 번 더 확인)
            for table, col in (("holdings", "user_id"), ("views", "user_id"), ("feedback", "user_id"), ("likes", "user_id"),
                               ("regrams", "user_id"), ("follows", "follower_id"), ("follows", "followee_id"), ("users", "id")):  # fmt: skip
                self.con.execute(f"delete from {table} where {col} = ?", (uid,))
            self.con.commit()
            return self.see("/", ("Set-Cookie", "s=; Path=/; Max-Age=0"))
        if path == "/me":
            self.log(uid, "me")
            return "200 OK", [], self.profile(uid)
        if path == "/me/settings":
            return "200 OK", [], self.settings(uid, query.get("msg"))
        if path == "/learn" or path.startswith("/learn/"):
            slug = path[7:]
            self.log(uid, "learn", slug or None)
            return self.learn(uid, slug)
        if path == "/calendar":
            self.log(uid, "calendar")
            return "200 OK", [], self.calendar(uid, query.get("m"))
        return "404 Not Found", [], self.simple("없음", "없는 화면이에요. <a class='text-primary underline' href='/'>처음으로</a>")

    # ---- 로그인 (시안 _2) ----

    def login_page(self, sent: str | None = None, error: str = "") -> str:
        box = (f'<p class="font-body-compact text-body-compact text-tertiary mt-3" role="alert">{e(error)}</p>' if error else "") + ("" if not sent else (
            '<div class="flex flex-col bg-secondary-container/40 rounded-lg p-4 mt-4 transition-all" id="success-box"><div class="flex items-start gap-3"><div class="flex-shrink-0 w-8 h-8 rounded-full bg-secondary-container flex items-center justify-center mt-0.5"><span class="material-symbols-outlined text-on-secondary-container text-lg" style="font-variation-settings: \'FILL\' 1;">mark_email_read</span></div><div class="flex flex-col flex-1 min-w-0"><div class="flex items-center gap-1.5 mb-1"><span class="font-label-micro text-label-micro bg-primary text-on-primary px-1.5 py-0.5 rounded">발송 완료</span>'
            f'<span class="font-body-reading-strong text-body-compact text-on-surface truncate" id="target-email-preview">{e(sent)}</span></div>'
            '<p class="font-body-compact text-body-compact text-on-secondary-container">위 주소로 안전한 접속 링크를 전송했습니다. 15분 이내에 메일함 속 링크를 눌러 주세요.</p><div class="flex flex-col gap-1 mt-2.5 pt-2.5 border-t border-outline-variant/30"><p class="font-label-micro text-label-micro text-outline">메일이 도착하지 않았나요? 스팸함을 확인하시거나 잠시 후 재전송해 보세요.</p>'
            f'<form method="post" action="/login"><input type="hidden" name="email" value="{e(sent)}"><input type="hidden" name="agree" value="1"><button class="self-start font-label-regular text-label-regular text-primary font-semibold underline underline-offset-2 hover:opacity-80 transition-opacity mt-1" id="resend-btn" type="submit">링크 다시 보내기</button></form></div></div></div></div>'))  # fmt: skip
        inner = ('<main class="flex flex-col relative w-full max-w-[480px] mx-auto bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-12">'
                 '<div class="flex flex-col items-center text-center mt-6 mb-8"><div class="relative flex items-center justify-center w-20 h-20 rounded-full bg-surface-container-low shadow-sm mb-5"><svg class="w-9 h-9 text-primary" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.75" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" x2="8" y1="13" y2="13"></line><line x1="16" x2="8" y1="17" y2="17"></line><line x1="10" x2="8" y1="9" y2="9"></line></svg><div class="absolute -bottom-1 -right-1 flex items-center justify-center w-6 h-6 rounded-full bg-secondary-container shadow-xs"><span class="material-symbols-outlined text-on-secondary-container text-xs" style="font-variation-settings: \'FILL\' 1;">auto_stories</span></div></div>'
                 '<span class="font-display-editorial text-display-editorial text-primary tracking-tight">한장</span><span class="font-label-micro text-label-micro text-outline uppercase tracking-widest mt-1">Hanjang · Weekly Financial Letter</span>'
                 '<h1 class="font-headline-sm text-headline-sm text-on-surface mt-4 max-w-[280px] leading-relaxed">내 주식이 지금 어떤 상황인지,<br>쉬운 글 한 장으로.</h1>'
                 '<p class="font-body-compact text-body-compact text-on-surface-variant mt-2 max-w-[300px]">숫자 뒤에 숨겨진 회사의 진짜 이야기와 사업 흐름을 담백하게 정리해 드립니다.</p></div>'
                 '<div class="w-full rounded-xl flex flex-col relative overflow-hidden px-1.5"><form class="flex flex-col w-full relative z-10" id="magic-link-form" method="post" action="/login">'
                 '<div class="flex items-center justify-between mb-2"><label class="font-label-regular text-label-regular text-on-surface flex items-center gap-1.5" for="email-input"><span class="material-symbols-outlined text-primary text-base">mail</span>이메일 주소</label><span class="font-label-micro text-label-micro text-outline">비밀번호 없는 간편 시작</span></div>'
                 '<div class="relative flex items-center w-full"><input class="w-full font-body-reading text-body-reading bg-surface-container-low text-on-surface placeholder:text-outline rounded-lg px-4 py-3.5 focus:outline-none focus:bg-surface-container-lowest transition-all" id="email-input" name="email" placeholder="name@example.com" required="" type="email">'
                 '<button aria-label="이메일 지우기" class="hidden absolute right-3 text-outline hover:text-on-surface p-1 transition-colors" id="clear-btn" onclick="clearInput()" type="button"><span class="material-symbols-outlined text-lg">cancel</span></button></div>'
                 '<label class="flex items-start gap-2 mt-3 font-label-regular text-label-regular text-on-surface-variant"><input class="mt-0.5 accent-primary" name="agree" required type="checkbox" value="1">'
                 '<span>[필수] 이메일 수집·이용에 동의해요 — <a class="text-primary underline" href="/privacy" target="_blank">개인정보 처리방침</a></span></label>'
                 f'<button class="w-full py-3.5 bg-primary text-on-primary font-body-reading-strong text-body-reading-strong rounded-lg shadow-sm hover:opacity-95 active:scale-[0.99] transition-all mt-3 flex items-center justify-center gap-2" id="submit-btn" type="submit"><span class="">{"링크 다시 받기" if sent else "로그인 링크 받기"}</span><span class="material-symbols-outlined text-base">{"refresh" if sent else "arrow_forward"}</span></button>'
                 '<p class="font-label-regular text-label-regular text-outline text-center mt-3 leading-relaxed">복잡한 비밀번호 설정 없이, 메일로 온 링크를 누르면 바로 연결돼요. 받는 개인정보는 이메일 하나뿐이에요.</p>'
                 '<a class="block text-center mt-2 font-label-regular text-label-regular text-primary underline underline-offset-2" href="/help/login">로그인 링크가 안 와요</a></form>'
                 + ('<a class="mt-3 w-full py-3 rounded-lg border border-outline-variant/70 text-on-surface font-body-reading-strong text-body-compact flex items-center justify-center gap-1" href="/demo">'
                    '<span class="material-symbols-outlined text-[18px]">visibility</span>로그인 없이 둘러보기</a>' if env().get("DEMO") == "1" else "")
                 + box + '</div>'
                 '<div class="mt-8 flex flex-col gap-4"><div class="grid grid-cols-2 gap-4 pt-2 border-t border-outline-variant/30"><div class="flex flex-col gap-1"><div class="flex items-center gap-1.5 text-primary"><span class="material-symbols-outlined text-base">description</span><span class="font-body-reading-strong text-label-regular">공시 기반 해설</span></div><p class="font-label-micro text-label-micro text-on-surface-variant leading-relaxed">어려운 DART 공시와 분기 보고서를 일상 언어로 풀어냅니다.</p></div><div class="flex flex-col gap-1"><div class="flex items-center gap-1.5 text-secondary"><span class="material-symbols-outlined text-base">spa</span><span class="font-body-reading-strong text-label-regular">소음 없는 담백함</span></div><p class="font-label-micro text-label-micro text-on-surface-variant leading-relaxed">빨강·파랑 시세창 대신 기업 본질을 천천히 읽는 시간.</p></div></div>'
                 '<div class="text-center px-4 mt-4"><div class="inline-flex items-center justify-center gap-2 mb-2"><span class="w-4 h-[1px] bg-outline-variant"></span><span class="font-citation-ref text-citation-ref text-outline">한장의 약속</span><span class="w-4 h-[1px] bg-outline-variant"></span></div><p class="font-label-regular text-label-regular text-outline leading-relaxed">이해를 위한 서비스예요. 수익률을 장담하거나 종목을 추천하지 않아요.</p></div></div></div>'
                 "<script>const emailInput=document.getElementById('email-input');const clearBtn=document.getElementById('clear-btn');"
                 "emailInput.addEventListener('input',(ev)=>{clearBtn.classList.toggle('hidden',ev.target.value.length===0);});"
                 "function clearInput(){emailInput.value='';clearBtn.classList.add('hidden');emailInput.focus();}</script></main>")  # fmt: skip
        return page("로그인", "bg-surface font-body-reading text-on-surface pt-safe pb-safe flex flex-col min-h-screen", inner)

    def is_demo(self, uid: int) -> bool:
        row = self.con.execute("select email from users where id = ?", (uid,)).fetchone()
        return bool(row and row[0] == DEMO_EMAIL)

    def demo(self):
        if env().get("DEMO") != "1":
            return "404 Not Found", [], self.simple("없음", "없는 화면이에요. <a class='text-primary underline' href='/'>처음으로</a>")
        self.con.execute("insert or ignore into users (email, created_at, nickname, mail_on) values (?, ?, '둘러보기', 0)",
                         (DEMO_EMAIL, datetime.now().isoformat()))  # fmt: skip
        (u,) = self.con.execute("select id from users where email = ?", (DEMO_EMAIL,)).fetchone()
        for t in DEMO_STOCKS:
            if self.con.execute("select 1 from stocks where ticker = ?", (t,)).fetchone():
                self.con.execute("insert or ignore into holdings values (?, ?, ?)", (u, t, datetime.now().isoformat()))
        self.con.commit()
        ck = f"s={sign(str(u), self.secret)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400"
        if mail.base_url().startswith("https://"):
            ck += "; Secure"
        return self.see("/", ("Set-Cookie", ck))

    def login(self, email: str, agreed: bool = False):
        if "@" not in email or len(email) > 200:
            return "200 OK", [], self.login_page()
        if not agreed:
            return "200 OK", [], self.login_page(error="개인정보 수집·이용에 동의해야 로그인 링크를 보낼 수 있어요.")
        now = self.clock()
        times = [t for t in self.sent.get(email, []) if now - t < 3600]
        if (times and now - times[-1] < LOGIN_GAP) or len(times) >= LOGIN_HOURLY:
            return "429 Too Many Requests", [], self.login_page(error="링크를 방금 보냈어요. 메일함을 먼저 확인하고, 잠시 뒤에 다시 요청해 주세요.")
        self.sent[email] = times + [now]
        link = f"{mail.base_url()}/auth?t={quote(login_token(email, self.secret, self.clock()))}"
        mail.send(email, *mail.login_mail(link))  # SMTP 설정이 없으면 서버 콘솔에 찍힌다
        return "200 OK", [], self.login_page(email)

    def match(self, q: str) -> str | None:
        """이름·코드 → 종목 코드. 띄어쓰기·대소문자는 무시한다(「삼성 SDI」→ 삼성SDI)."""
        key = re.sub(r"\s+", "", q).upper()
        row = self.con.execute("select ticker from stocks where active = 1 and (ticker = ? or upper(replace(name, ' ', '')) = ?)",
                               (key, key)).fetchone()  # fmt: skip
        return row[0] if row else None

    def add_many(self, uid: int, names: list[str]) -> tuple[list[str], list[str], bool]:
        """(담은 것, 못 찾은 것, 20개가 차서 멈췄나). 이미 담은 종목은 담은 것으로 센다."""
        added, unknown = [], []
        for q in dict.fromkeys(x.strip() for x in names if x.strip()):
            t = self.match(q)
            if not t:
                unknown.append(q)
                continue
            (n,) = self.con.execute("select count(*) from holdings where user_id = ?", (uid,)).fetchone()
            have = self.con.execute("select 1 from holdings where user_id = ? and ticker = ?", (uid, t)).fetchone()
            if not have and n >= MAX_STOCKS:
                return added, unknown, True
            self.con.execute("insert or ignore into holdings values (?, ?, ?)", (uid, t, datetime.now().isoformat()))
            added.append(self.con.execute("select name from stocks where ticker = ?", (t,)).fetchone()[0])
        self.con.commit()
        return added, unknown, False

    @staticmethod
    def added_msg(added: list[str], unknown: list[str], full: bool) -> str:
        parts = [f"{len(added)}종목을 담았어요 ({', '.join(added[:5])}{' 외' if len(added) > 5 else ''})."] if added else []
        if unknown:
            parts.append(f"「{', '.join(unknown[:5])}」은(는) 아직 노트가 없어요 — 코스피 큰 회사 100곳부터 시작했어요.")
        if full:
            parts.append(f"종목은 {MAX_STOCKS}개까지 담을 수 있어요.")
        return " ".join(parts) or "담을 종목을 찾지 못했어요."

    def add(self, uid: int, q: str):
        """한 종목, 또는 쉼표·줄바꿈·띄어쓰기로 여러 종목을 한 번에 (「삼성전자, SK하이닉스」)."""
        if not q:
            return self.see("/")
        names = [q] if self.match(q) else [w for part in re.split(r"[,\n;/·]+", q)
                                           for w in ([part] if self.match(part) else part.split())]  # fmt: skip
        added, unknown, full = self.add_many(uid, names)
        if len(names) == 1 and added and not full:
            return self.see("/")
        return self.see("/?msg=" + quote(self.added_msg(added, unknown, full)))

    def scan(self, uid: int, img: str):
        """보유 종목 캡처 → AI 가 종목 이름만 읽는다 → 코드가 우리 종목과 맞춰 담는다. 사진은 저장하지 않는다."""
        def reply(msg, code="200 OK"):
            return code, [("Content-Type", "application/json; charset=utf-8")], json.dumps({"msg": msg}, ensure_ascii=False)

        if not re.match(r"data:image/(jpeg|png|webp);base64,", img):
            return reply("사진을 읽지 못했어요. 캡처 사진(JPG·PNG)을 골라 주세요.", "400 Bad Request")
        now = self.clock()
        times = [t for t in self.scans.get(uid, []) if now - t < 3600]
        if len(times) >= SCAN_HOURLY:
            return reply("사진 읽기는 한 시간에 10번까지예요. 잠시 뒤에 다시 해 주세요.", "429 Too Many Requests")
        self.scans[uid] = times + [now]
        schema = {"type": "object", "additionalProperties": False, "required": ["names"],
                  "properties": {"names": {"type": "array", "items": {"type": "string"}}}}  # fmt: skip
        try:
            got = llm.ask("scan", "holdings", {}, lambda j: [str(x) for x in j["names"]][:40], schema, image=img)
        except RuntimeError:
            got = None
        if not got:
            return reply("사진에서 종목을 찾지 못했어요. 증권사 앱의 「보유 종목」 화면을 캡처해 주세요.")
        return reply(self.added_msg(*self.add_many(uid, got)))

    # ---- 내 종목 (시안 _3) ----

    def cards(self, uid: int, msg: str | None, sort: str | None = None) -> str:
        order = "s.name" if sort == "name" else "h.added_at"
        rows = self.con.execute(
            "select s.ticker, s.name, n.week, n.body, n.facts, s.homepage from holdings h join stocks s using(ticker)"
            " left join notes n on n.ticker = s.ticker and n.week ="
            " (select max(week) from notes where ticker = s.ticker)"
            f" where h.user_id = ? order by {order}", (uid,)).fetchall()  # fmt: skip
        stocks = [{"t": t, "n": n, "l": industry_label(c) or ""}
                  for t, n, c in self.con.execute("select ticker, name, induty_code from stocks where active = 1 order by name")]  # fmt: skip
        out = []
        for t, name, week, body, facts, home in rows:  # facts 는 지금 카드에 안 쓴다 (상태 줄은 사용자 요청 10/7로 뺐다)
            head = json.loads(body)["headline"] if body else "이번 주 노트를 준비 중이에요."
            status = "<span></span>"  # 「노트 읽기 →」를 오른쪽에 두는 빈 자리
            out.append(f'<article class="py-4 relative transition-all group" data-stock-id="{e(t)}"><div class="flex items-start justify-between"><div class="flex items-center gap-2">'
                       f'{logo(name, home, "w-7 h-7")}<a href="/n/{e(t)}"><h2 class="font-headline-sm text-headline-sm text-on-surface font-semibold hover:underline">{e(name)}</h2></a><span class="font-citation-ref text-citation-ref text-outline px-1.5 py-0.5 rounded bg-surface-container-low">{e(t)}</span><span class="font-label-micro text-label-micro text-outline-variant">{e(week or "")}</span></div>'
                       f'<form method="post" action="/remove"><input type="hidden" name="t" value="{e(t)}"><button aria-label="{e(name)} 삭제" class="w-6 h-6 rounded-full flex items-center justify-center text-outline hover:text-tertiary hover:bg-surface-container transition-colors" type="submit"><span class="material-symbols-outlined text-[16px]">close</span></button></form></div>'
                       f'<a href="/n/{e(t)}"><p class="font-body-reading text-body-reading text-on-surface mt-2 tracking-tight">{e(head)}</p></a>'
                       f'<div class="mt-3 flex items-center justify-between">{status}<a class="font-label-micro text-label-micro text-primary flex items-center gap-0.5 hover:underline font-semibold" href="/n/{e(t)}">노트 읽기<span class="material-symbols-outlined text-[14px]">arrow_forward</span></a></div></article>')  # fmt: skip
        note = (f'<p class="font-label-micro text-label-micro text-tertiary px-margin pt-2">{e(msg)}</p>' if msg else "")
        inner = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] mx-auto pt-14 pb-24 bg-surface min-h-screen"><div class="flex flex-col w-full">'
                 '<section class="sticky top-0 z-30 bg-surface/95 backdrop-blur-md px-margin py-3 border-b border-surface-container-high transition-all duration-200"><div class="relative w-full">'
                 '<form method="post" action="/add" class="h-11 w-full bg-surface-container-low/60 rounded-xl flex items-center px-3 border border-surface-container-high/60 focus-within:border-primary-container focus-within:bg-surface-container-lowest transition-all"><span class="material-symbols-outlined text-outline text-[20px] mr-2">search</span>'
                 '<input autocomplete="off" class="w-full bg-transparent text-on-surface font-body-compact text-body-compact placeholder:text-outline focus:outline-none" id="stock-search-input" name="q" placeholder="종목 이름 또는 코드로 담기" type="text">'
                 '<button class="shrink-0 ml-1.5 px-3 py-1 bg-primary text-on-primary rounded-lg font-label-micro text-label-micro font-semibold shadow-sm active:scale-95 transition-transform" id="btn-quick-add" type="submit">담기</button>'
                 '<label class="shrink-0 ml-1 w-8 h-8 flex items-center justify-center rounded-lg text-on-surface-variant hover:bg-surface-container cursor-pointer" aria-label="보유 종목 캡처로 담기" title="보유 종목 캡처로 담기">'
                 '<span class="material-symbols-outlined text-[20px]">photo_camera</span><input accept="image/*" class="hidden" id="scan-input" type="file"></label></form>'
                 '<div class="hidden fixed inset-0 z-[60] bg-surface/90 backdrop-blur-sm flex-col items-center justify-center gap-3 px-margin text-center" id="scan-wait" role="status">'
                 '<span class="material-symbols-outlined text-primary text-[40px] animate-pulse">document_scanner</span>'
                 '<p class="font-headline-sm text-headline-sm text-on-surface">분석 중…</p>'
                 '<p class="font-body-compact text-body-compact text-on-surface-variant">캡처에서 종목 이름만 읽고 있어요. 사진은 저장하지 않아요.</p></div>'
                 '<div class="hidden absolute left-0 right-0 top-12 mt-1 bg-surface-container-lowest rounded-xl shadow-sm border border-surface-container-high/70 overflow-hidden z-40" id="search-flyout"><div class="p-1.5 flex flex-col gap-0.5" id="search-results"></div></div>'
                 "</div></section>" + note
                 + '<header class="px-margin pt-5 pb-2"><div class="flex items-baseline justify-between mb-1"><div class="flex items-center gap-2"><h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight">내 종목</h1>'
                 f'<span class="font-label-regular text-label-regular text-outline" id="stock-count-badge">{len(rows)} / {MAX_STOCKS}개</span></div>'
                 f'<a class="font-label-micro text-label-micro text-outline hover:text-on-surface transition-colors flex items-center gap-0.5" href="/?sort={"added" if sort == "name" else "name"}"><span class="material-symbols-outlined text-[15px]">tune</span>정렬</a></div>'
                 '</header>'
                 f'<section class="px-margin flex flex-col divide-y divide-surface-container-high/80" id="stock-list">{"".join(out)}</section>'
                 '<footer class="px-margin pt-4 pb-8 flex flex-col items-center justify-center gap-2"><p class="font-label-regular text-label-regular text-on-surface-variant text-center flex items-center justify-center gap-1.5"><span class="material-symbols-outlined text-[15px] text-primary">mark_email_unread</span>월요일 아침마다 새 노트가 와요. 새 공시·기사가 나오면 매일 아침 고쳐 써요.</p><div class="flex items-center gap-3 text-outline font-label-micro text-label-micro"><span class="">업데이트: 매일 07:00 (바뀐 종목만)</span><span class="">·</span><span class="">공시 데이터: DART 전자공시</span></div>'
                 '<button class="font-label-micro text-label-micro text-outline hover:text-on-surface transition-colors underline underline-offset-4 py-2" onclick="if(confirm(\'현재 계정에서 로그아웃할까요?\'))location.href=\'/logout\'" type="button">로그아웃</button></footer></div>'
                 # 자동완성 — 노트가 있는 종목(코스피 시총 상위)만. 업종은 DART 업종 코드에서
                 "<script>const STOCKS=" + json.dumps(stocks, ensure_ascii=False).replace("<", "\\u003c") + ";"
                 "const inp=document.getElementById('stock-search-input'),fly=document.getElementById('search-flyout'),res=document.getElementById('search-results');"
                 "function esc(s){return s.replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}"
                 "function draw(){const q=inp.value.trim();if(!q){fly.classList.add('hidden');return;}const hit=STOCKS.filter(s=>s.n.includes(q)||s.t.startsWith(q)).slice(0,6);"
                 "res.innerHTML=hit.map((s,i)=>"
                 "'<form method=\"post\" action=\"/add\" class=\"group flex items-center justify-between p-2.5 rounded-lg cursor-pointer hover:bg-surface-container transition-colors\"><input type=\"hidden\" name=\"q\" value=\"'+s.t+'\"><div class=\"flex items-center gap-2 min-w-0\"><span class=\"w-7 h-7 rounded-full bg-primary-fixed text-primary flex items-center justify-center font-body-reading-strong text-[12px]\">'+esc(s.n[0])+'</span><div class=\"flex flex-col min-w-0\"><div class=\"flex items-center gap-1.5\"><span class=\"font-headline-sm text-headline-sm text-on-surface\">'+esc(s.n)+'</span><span class=\"font-citation-ref text-citation-ref text-outline\">'+s.t+'</span></div><span class=\"font-label-micro text-label-micro text-on-surface-variant truncate\">'+esc(s.l)+'</span></div></div>'"
                 "+'<button class=\"px-2.5 py-1 bg-primary-container text-on-primary font-label-micro text-label-micro rounded-lg shadow-sm hover:opacity-90 active:scale-95 transition-all\" type=\"submit\">+ 담기</button>'+'</form>').join('');"
                 "fly.classList.toggle('hidden',hit.length===0);}"
                 "inp.addEventListener('input',draw);inp.addEventListener('focus',draw);"
                 "document.addEventListener('click',ev=>{if(!inp.contains(ev.target)&&!fly.contains(ev.target))fly.classList.add('hidden');});"
                 # 캡처 → 브라우저에서 1600px 로 줄여 JPEG 로 → /scan. 끝나면 결과 문장과 함께 새로 그린다
                 "const sc=document.getElementById('scan-input'),wait=document.getElementById('scan-wait');"
                 "sc.addEventListener('change',async()=>{const f=sc.files[0];if(!f)return;wait.classList.remove('hidden');wait.classList.add('flex');"
                 "try{const bmp=await createImageBitmap(f);const k=Math.min(1,1600/Math.max(bmp.width,bmp.height));const c=document.createElement('canvas');"
                 "c.width=Math.round(bmp.width*k);c.height=Math.round(bmp.height*k);c.getContext('2d').drawImage(bmp,0,0,c.width,c.height);"
                 "const r=await fetch('/scan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({img:c.toDataURL('image/jpeg',0.85)})});"
                 "const j=await r.json();location.href='/?msg='+encodeURIComponent(j.msg);}"
                 "catch(err){location.href='/?msg='+encodeURIComponent('사진을 읽지 못했어요. 다시 해 주세요.');}});</script></main>"
                 + bottom_nav("cards"))  # fmt: skip
        return page("내 종목", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    # ---- 설문 (시안에 없는 칸 — 시험 판정에 꼭 필요해 노트 끝에, 시안과 같은 모양으로) ----

    def trial_week(self, uid: int) -> int:
        """시험 몇 주째인가 — 가입한 날이 1주째 (ERD views 의 주차 계산과 같은 기준)."""
        (created,) = self.con.execute("select created_at from users where id = ?", (uid,)).fetchone()
        return (date.today() - date.fromisoformat(created[:10])).days // 7 + 1

    def survey(self, uid: int, ticker: str, week: str, thanks: bool) -> str:
        """주간 설문 (PRD F7) — 1~5 + 한 줄. 6주째부터 「돈 내고도 보겠다」."""
        done = self.con.execute("select 1 from feedback where user_id = ? and ticker = ? and week = ?",
                                (uid, ticker, week)).fetchone()  # fmt: skip
        if thanks or done:
            return ('<section class="mb-space-xl pl-space-md py-1 border-l-2 border-primary/60"><p class="font-body-compact text-body-compact text-on-surface">'
                    "이번 주 노트에 대한 의견 고마워요. 다음 주 노트에 참고할게요.</p></section>")  # fmt: skip
        chip = "px-2.5 py-1 rounded-full border border-outline-variant/60 font-label-micro text-label-micro text-on-surface flex items-center gap-1"
        pay = ('<p class="font-label-regular text-label-regular text-on-surface font-semibold mt-space-sm">이 노트를 돈을 내고도 보시겠어요? 낸다면 한 달에 얼마까지?</p><div class="flex flex-wrap gap-2">'
               + "".join(f'<label class="{chip}"><input type="radio" name="pay" value="{v}" required>{t}</label>'
                         for v, t in ((0, "안 내요"), (1000, "1천 원"), (3000, "3천 원"), (5000, "5천 원"), (10000, "1만 원 이상")))
               + "</div>") if self.trial_week(uid) >= 6 else ""  # fmt: skip
        return (f'<form method="post" action="/feedback" class="mb-space-xl flex flex-col gap-space-sm pt-space-lg border-t border-outline-variant/40">'
                f'<input type="hidden" name="t" value="{e(ticker)}"><input type="hidden" name="w" value="{e(week)}">'
                '<div class="flex items-center gap-2"><span class="w-2 h-2 rounded-full bg-primary"></span><h3 class="font-headline-md text-headline-md text-on-surface">이 노트가 도움이 됐나요?</h3></div>'
                '<input type="range" name="h" min="1" max="5" step="1" value="3" aria-label="도움 정도 1~5" class="w-full accent-primary cursor-pointer">'
                '<div class="flex justify-between px-1 -mt-1 font-label-micro text-label-micro text-on-surface-variant">' + "".join(f"<span>{i}</span>" for i in range(1, 6))
                + '</div><div class="flex justify-between font-label-micro text-label-micro text-outline"><span>별로예요</span><span>아주 좋아요</span></div>'
                + pay + '<input class="w-full font-body-compact text-body-compact bg-surface-container-low text-on-surface placeholder:text-outline rounded-lg px-4 py-3 focus:outline-none" maxlength="300" name="c" placeholder="한 줄 의견 (선택)">'
                '<button class="w-full py-3 bg-primary text-on-primary font-body-reading-strong text-body-reading-strong rounded-lg shadow-sm" type="submit">보내기</button></form>')  # fmt: skip

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

    # ---- 기업 노트 (시안 _1) ----

    def note(self, uid: int, ticker: str, thanks: bool = False):
        row = self.con.execute(
            "select s.name, n.week, n.body, n.writer, n.facts, s.induty_code, n.made_at, s.homepage from stocks s join notes n using(ticker)"
            " where s.ticker = ? order by n.week desc limit 1", (ticker,)).fetchone()  # fmt: skip
        if not row:
            return "404 Not Found", [], self.simple("없음", "이 종목은 아직 노트가 없어요. <a class='text-primary underline' href='/'>내 종목</a>")
        name, week, body, writer, facts, ind, made, home = row
        (views,) = self.con.execute("select count(*) from views where page = 'note' and ticker = ? and at >= ?", (ticker, week)).fetchone()
        (likes,) = self.con.execute("select count(*) from likes where ticker = ? and week = ?", (ticker, week)).fetchone()
        liked = bool(self.con.execute("select 1 from likes where user_id = ? and ticker = ? and week = ?", (uid, ticker, week)).fetchone())
        return "200 OK", [], render_note(name, ticker, week, json.loads(body), writer, json.loads(facts), ind,
                                         self.initial(uid), self.survey(uid, ticker, week, thanks), made, home, (views, likes, liked),
                                         self.regram_form(uid, "note", ticker, week),
                                         prices=self.con.execute("select date, close from prices where ticker = ? order by date", (ticker,)).fetchall()
                                         if sources.price_dev() else None, report=self.report(ticker))  # fmt: skip

    def report(self, ticker: str) -> dict:
        divs = self.con.execute("select fiscal_year, dps, total, payout from dividends where ticker = ? order by fiscal_year", (ticker,)).fetchall()
        biz = self.con.execute("select body, rcept_no from business where ticker = ?", (ticker,)).fetchone()
        return {"divs": divs, "biz": json.loads(biz[0]) if biz else None, "rno": biz[1] if biz else None}

    # ---- 캘린더 (시안 _4) ----

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
            "select d.date, s.name, d.code, d.title, d.rcept_no, d.direction, s.ticker, d.amount from disclosures d"
            " join holdings h on h.ticker = d.ticker and h.user_id = ? join stocks s on s.ticker = d.ticker"
            " where d.date between ? and ? and d.importance >= 2 and d.code != 'OTHER' order by d.date",
            (uid, lo, hi)).fetchall()  # fmt: skip
        by: dict[str, list] = {}
        for r in rows:
            by.setdefault(r[0], []).append(r)
        mine = sorted((r for r in rows if r[0][:7] == f"{y}-{m:02d}"), key=lambda r: r[0], reverse=True)  # 최신순
        kinds: dict[str, int] = {}
        for r in mine:
            kinds[r[2]] = kinds.get(r[2], 0) + 1
        prev = f"{y - (m == 1)}-{(m - 2) % 12 + 1:02d}"
        nxt = f"{y + (m == 12)}-{m % 12 + 1:02d}"
        cells = []
        for wk in weeks:
            for i, d in enumerate(wk):
                iso = d.isoformat()
                if d.month != m:
                    num = f'<span class="font-label-micro text-label-micro text-outline-variant">{d.day}</span>'
                elif d == today:
                    num = (f'<div class="flex items-center justify-between"><span class="w-5 h-5 flex items-center justify-center rounded-full bg-primary-container text-on-primary font-label-micro text-label-micro font-bold">{d.day}</span>'
                           '<span class="text-[8px] text-primary-container font-semibold">오늘</span></div>')  # fmt: skip
                elif iso in hol:  # 공휴일은 시안대로 검은 숫자 + 이름 (사용자 10/7: 시안 그대로)
                    num = f'<span class="font-label-micro text-label-micro text-on-surface font-medium">{d.day}</span>'
                elif i in (0, 6):  # 주말은 빨간 숫자
                    num = f'<span class="font-label-micro text-label-micro text-tertiary font-semibold">{d.day}</span>'
                else:
                    num = f'<span class="font-label-micro text-label-micro text-on-surface">{d.day}</span>'
                cell = num
                if iso in hol and d.month == m:
                    cell += f'<span class="text-[8px] text-on-surface-variant leading-tight line-clamp-1 mt-0.5">{e(hol[iso])}</span>'
                for _, name, code, _, rno, dr, _, _ in by.get(iso, []) if d.month == m else []:
                    tint = {1: "bg-secondary-fixed text-on-secondary-fixed-variant", -1: "bg-tertiary-fixed text-on-tertiary-fixed-variant"}.get(dr, "bg-surface-container-high text-on-surface-variant")
                    cell += (f'<a href="{e(notes.DART.format(rno))}" target="_blank" rel="noopener" class="mt-0.5 px-1 py-0.5 rounded {tint} text-[9px] font-semibold leading-tight line-clamp-1">'
                             f"{e(short_name(name))} {e(EVENT_SHORT.get(code, ''))}</a>")  # fmt: skip
                cells.append(f'<div class="min-h-[52px] p-1 flex flex-col justify-start">{cell}</div>')
        items = []
        for d, name, code, title, rno, dr, t, amount in mine:
            dd = date.fromisoformat(d)
            label, chip = TONE_TAG.get(dr or 0, TONE_TAG[0])
            src = "DART 공시: " + re.sub(r"^\[[^\]]*\]", "", title) + (f" {notes.won(amount)} 규모" if amount else "")
            items.append(f'<a href="{e(notes.DART.format(rno))}" target="_blank" rel="noopener"><article class="py-3.5 border-b border-surface-container-high flex flex-col gap-1 transition-colors hover:bg-surface-container-low/40"><div class="flex items-center justify-between">'
                         f'<span class="font-label-micro text-label-micro text-on-surface-variant">{dd.month}월 {dd.day}일 ({"월화수목금토일"[dd.weekday()]}) · {e(name)} ({e(t)})</span>'
                         f'<span class="font-label-micro text-label-micro px-2 py-0.5 rounded-full {chip} font-semibold">{label}</span></div>'
                         f'<h3 class="font-headline-sm text-headline-sm text-on-surface font-semibold">{e(clean_title(title, code))}</h3>'
                         f'<p class="font-body-compact text-body-compact text-on-surface-variant leading-relaxed">{e(EVENT_EXPLAIN.get(code, ""))}</p>'
                         f'<div class="flex items-center gap-1.5 text-on-surface-variant font-citation-ref text-citation-ref pt-0.5"><span class="material-symbols-outlined {"text-tertiary" if dr == -1 else "text-primary"} text-[15px]">{"info" if dr == -1 else "verified"}</span><span class="">{e(src)}</span></div></article></a>')  # fmt: skip
        if not items:
            items.append('<p class="py-3.5 font-body-compact text-body-compact text-on-surface-variant">이 달엔 내 종목의 큰 공시가 없어요.</p>')
        # 이 달 일정에 나온 공시 종류마다 그에 맞는 읽기 팁 글 — 많이 나온 종류부터, 같은 글은 한 번, 최대 3편
        picks = {}
        for kind in sorted(kinds, key=kinds.get, reverse=True):
            picks.setdefault(learn.FOR_EVENT.get(kind, "disclosure"), kind)
        tips = "".join(
            f'<a href="/learn/{slug}" class="py-3 flex items-center gap-space-md"><div class="w-12 h-12 rounded-lg flex-shrink-0 bg-surface-container flex items-center justify-center"><span class="material-symbols-outlined text-primary text-[22px]">menu_book</span></div>'
            f'<div class="flex flex-col gap-0.5 min-w-0"><span class="font-label-micro text-label-micro text-outline">이 달 {e(EVENT_SHORT.get(kind, kind))} 공시와 관련</span>'
            f'<p class="font-body-compact text-body-compact text-on-surface font-semibold truncate">{e(learn.BY_SLUG[slug]["title"])}</p>'
            f'<span class="font-label-micro text-label-micro text-on-surface-variant truncate">{e(TIPS.get(kind, TIP_DEFAULT)[0])}</span></div>'
            '<span class="material-symbols-outlined text-outline text-[18px] ml-auto">chevron_right</span></a>'
            for slug, kind in list(picks.items())[:3]) or (
            '<a href="/learn/disclosure" class="py-3 flex items-center gap-space-md"><div class="w-12 h-12 rounded-lg flex-shrink-0 bg-surface-container flex items-center justify-center"><span class="material-symbols-outlined text-primary text-[22px]">menu_book</span></div>'
            f'<div class="flex flex-col gap-0.5 min-w-0"><p class="font-body-compact text-body-compact text-on-surface font-semibold">{e(learn.BY_SLUG["disclosure"]["title"])}</p>'
            f'<span class="font-label-micro text-label-micro text-on-surface-variant">{e(TIP_DEFAULT[0])}</span></div></a>')  # fmt: skip
        mix = " · ".join(f"{EVENT_SHORT.get(k, k)} {v}" for k, v in kinds.items()) or "큰 공시 없음"
        inner = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] mx-auto pt-14 pb-24 bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-6 gap-space-lg">'
                 '<header class="flex flex-col pt-space-xs gap-space-xs"><div class="flex items-center justify-between"><div class="flex items-baseline gap-space-xs">'
                 f'<h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight">{y}년 {m}월</h1><span class="font-label-micro text-label-micro text-on-surface-variant">공시 타임라인</span></div>'
                 '</div>'
                 '<p class="font-body-compact text-body-compact text-on-surface-variant">관심 기업의 주요 의사결정과 공시 기록을 날짜별로 천천히 짚어드려요.</p></header>'
                 '<section class="py-space-sm px-1 flex items-center justify-between border-b border-surface-container-high"><div class="flex items-center gap-space-sm"><span class="material-symbols-outlined text-primary text-[20px]">calendar_clock</span><div class="flex items-baseline gap-space-xs">'
                 f'<span class="font-label-regular text-label-regular text-on-surface font-semibold">이번 달 주목할 공시 {len(mine)}건</span><span class="font-label-micro text-label-micro text-on-surface-variant">{e(mix)}</span></div></div>'
                 '</section>'
                 '<section class="flex flex-col gap-1 py-1"><div class="grid grid-cols-7 text-center font-label-micro text-label-micro font-semibold pb-1.5 border-b border-surface-container-high/60"><span class="text-tertiary">일</span><span class="text-on-surface-variant">월</span><span class="text-on-surface-variant">화</span><span class="text-on-surface-variant">수</span><span class="text-on-surface-variant">목</span><span class="text-on-surface-variant">금</span><span class="text-tertiary">토</span></div>'
                 f'<div class="grid grid-cols-7 gap-1 pt-1">{"".join(cells)}</div>'
                 '<nav class="flex justify-center items-center gap-5 pt-2 text-[12px] text-outline">'
                 f'<a class="flex items-center hover:text-on-surface-variant" href="/calendar?m={prev}"><span class="material-symbols-outlined text-[14px]">chevron_left</span>이전 달</a>'
                 f'<a class="flex items-center hover:text-on-surface-variant" href="/calendar?m={nxt}">다음 달<span class="material-symbols-outlined text-[14px]">chevron_right</span></a></nav></section>'
                 '<section class="flex flex-col mt-2"><div class="flex items-center justify-between pb-2 border-b border-surface-container-highest"><div class="flex items-center gap-space-xs"><h2 class="font-headline-md text-headline-md text-on-surface">이 달의 일정</h2><span class="font-label-micro text-label-micro text-on-surface-variant bg-surface-container px-2 py-0.5 rounded-full">최신순</span></div>'
                 '<a class="font-label-regular text-label-regular text-primary flex items-center hover:opacity-80 transition-opacity" href="https://dart.fss.or.kr" target="_blank" rel="noopener">전체 공시 원문<span class="material-symbols-outlined text-[15px] ml-0.5">arrow_forward</span></a></div>'
                 f'<div class="flex flex-col">{"".join(items)}</div></section>'
                 '<section class="pt-4 border-t border-surface-container-high flex flex-col"><span class="font-label-regular text-label-regular text-primary font-bold">주주를 위한 읽기 팁</span>'
                 f'<div class="flex flex-col divide-y divide-surface-container-high/70">{tips}</div></section>'
                 '<footer class="mt-2 text-center flex flex-col items-center gap-1"><div class="w-8 h-0.5 bg-surface-container-high rounded-full mb-1"></div><p class="font-citation-ref text-citation-ref text-on-surface-variant leading-relaxed max-w-[340px]">지난 공시만 보여요. 앞으로의 일정(실적 발표일·배당일)은 준비 중이에요. 공휴일: 한국천문연구원.</p></footer>'
                 "</div></main>" + bottom_nav("calendar"))  # fmt: skip
        return page("캘린더", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)


    # ---- 내 프로필 (시안에 없는 화면 — 같은 디자인 말투로. 가진 정보만) ----

    def profile(self, uid: int) -> str:
        """내 프로필 — 남이 보는 모양 그대로(이름·자기소개·팔로워·리그램). 설정은 오른쪽 위 톱니바퀴."""
        email, nick, bio, at = self.con.execute("select email, nickname, bio, photo_at from users where id = ?", (uid,)).fetchone()
        inner = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] mx-auto pt-14 pb-24 bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-6">'
                 f'<header class="pt-5 flex items-center gap-space-md">{self.face(nick or email, "w-14 h-14", photo_url(uid, at))}<div class="flex flex-col min-w-0 flex-1">'
                 f'<h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight truncate">{e(nick or "내 프로필")}</h1>{self.follow_line(uid)}</div>'
                 '<a href="/me/settings" aria-label="설정" class="w-10 h-10 rounded-full flex items-center justify-center text-on-surface-variant hover:bg-surface-container"><span class="material-symbols-outlined text-[22px]">settings</span></a></header>'
                 + (f'<p class="mt-space-md font-body-compact text-body-compact text-on-surface whitespace-pre-line">{e(bio)}</p>' if bio else "")
                 + self.regram_list("where r.user_id = ?", (uid,), "내 리그램", mine=True)
                 + "</div></main>" + bottom_nav("me"))  # fmt: skip
        return page("내 프로필", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    def settings(self, uid: int, msg: str | None = None) -> str:
        email, created, mail_on, nick, bio = self.con.execute(
            "select email, created_at, mail_on, nickname, bio from users where id = ?", (uid,)).fetchone()  # fmt: skip
        (at,) = self.con.execute("select photo_at from users where id = ?", (uid,)).fetchone()
        (held,) = self.con.execute("select count(*) from holdings where user_id = ?", (uid,)).fetchone()
        joined = date.fromisoformat(created[:10])
        # 주간 안내 메일 켜기/끄기 — 누르면 바로 바뀐다 (답장 같은 절차 없이, 사용자 10/7)
        knob = "translate-x-5" if mail_on else "translate-x-0"
        track = "bg-primary" if mail_on else "bg-surface-container-highest"
        switch = (f'<form method="post" action="/me/mail" class="py-3.5 flex items-center justify-between"><span class="flex items-center gap-2 font-body-compact text-body-compact text-on-surface-variant">'
                  '<span class="material-symbols-outlined text-primary text-[18px]">mark_email_unread</span>주간 안내 메일</span>'
                  f'<button aria-label="주간 안내 메일 {"끄기" if mail_on else "켜기"}" aria-pressed="{"true" if mail_on else "false"}" type="submit" class="flex items-center gap-2">'
                  f'<span class="font-label-micro text-label-micro {"text-primary" if mail_on else "text-outline"} font-semibold">{"ON" if mail_on else "OFF"}</span>'
                  f'<span class="w-11 h-6 rounded-full p-0.5 {track} transition-colors"><span class="block w-5 h-5 rounded-full bg-surface-container-lowest shadow-sm transition-transform {knob}"></span></span></button></form>')  # fmt: skip

        def row(icon, label, value):
            return (f'<div class="py-3.5 flex items-center justify-between"><span class="flex items-center gap-2 font-body-compact text-body-compact text-on-surface-variant">'
                    f'<span class="material-symbols-outlined text-primary text-[18px]">{icon}</span>{label}</span>'
                    f'<span class="font-body-reading-strong text-body-compact text-on-surface">{value}</span></div>')  # fmt: skip

        field = "w-full font-body-compact text-body-compact bg-surface-container-low rounded-lg px-4 py-3 focus:outline-none"
        photo = ('<div class="mt-space-lg flex items-center gap-space-md">'
                 '<label class="relative cursor-pointer" aria-label="프로필 사진 바꾸기">' + self.face(nick or email, "w-20 h-20", photo_url(uid, at))
                 + '<span class="absolute -bottom-0.5 -right-0.5 w-7 h-7 rounded-full bg-primary text-on-primary flex items-center justify-center border-2 border-surface">'
                 '<span class="material-symbols-outlined text-[16px]">photo_camera</span></span><input accept="image/*" class="hidden" id="photo-input" type="file"></label>'
                 '<div class="flex flex-col gap-1"><span class="font-label-regular text-label-regular text-on-surface font-semibold">프로필 사진</span>'
                 + ('<form method="post" action="/me/photo/delete"><button class="font-label-micro text-label-micro text-outline underline" type="submit">사진 지우기</button></form>' if at else "")
                 + '</div></div>'
                 # 고른 사진 → 동그라미 안에서 끌어 옮기고 크기를 맞춘 뒤(인스타그램처럼) 보이는 부분만 256px JPEG → /me/photo
                 '<div class="hidden fixed inset-0 z-[70] bg-on-background/80 flex-col items-center justify-center gap-4 px-margin" id="crop">'
                 '<p class="font-label-regular text-label-regular text-surface">끌어서 옮기고, 아래 막대로 크기를 맞춰요</p>'
                 '<div class="relative w-[280px] h-[280px] overflow-hidden rounded-xl bg-black touch-none select-none" id="stage">'
                 '<img alt="" class="absolute top-0 left-0 max-w-none origin-top-left pointer-events-none" id="crop-img">'
                 '<div class="absolute inset-0 rounded-full pointer-events-none" style="box-shadow:0 0 0 999px rgba(0,0,0,.55)"></div></div>'
                 '<input class="w-[280px] accent-primary" id="zoom" max="3" min="1" step="0.01" type="range" value="1" aria-label="사진 크기">'
                 '<div class="flex gap-3"><button class="px-5 py-2 rounded-lg border border-surface/60 text-surface font-label-regular text-label-regular" id="crop-cancel" type="button">취소</button>'
                 '<button class="px-5 py-2 rounded-lg bg-primary text-on-primary font-label-regular text-label-regular font-semibold" id="crop-ok" type="button">이대로 저장</button></div></div>'
                 "<script>(()=>{const S=280,box=document.getElementById('crop'),stage=document.getElementById('stage'),im=document.getElementById('crop-img'),zoom=document.getElementById('zoom');"
                 "let base=1,k=1,x=0,y=0,drag=null;"
                 "const clamp=()=>{const w=im.naturalWidth*base*k,h=im.naturalHeight*base*k;x=Math.min(0,Math.max(S-w,x));y=Math.min(0,Math.max(S-h,y));"
                 "im.style.transform=`translate(${x}px,${y}px) scale(${base*k})`;};"
                 "const open=()=>{box.classList.remove('hidden');box.classList.add('flex');},close=()=>{box.classList.add('hidden');box.classList.remove('flex');};"
                 "document.getElementById('photo-input').addEventListener('change',ev=>{const f=ev.target.files[0];if(!f)return;im.onload=()=>{"
                 "base=S/Math.min(im.naturalWidth,im.naturalHeight);k=1;zoom.value=1;x=(S-im.naturalWidth*base)/2;y=(S-im.naturalHeight*base)/2;clamp();open();};"
                 "im.src=URL.createObjectURL(f);});"
                 "stage.addEventListener('pointerdown',e=>{drag=[e.clientX-x,e.clientY-y];stage.setPointerCapture(e.pointerId);});"
                 "stage.addEventListener('pointermove',e=>{if(!drag)return;x=e.clientX-drag[0];y=e.clientY-drag[1];clamp();});"
                 "stage.addEventListener('pointerup',()=>drag=null);"
                 "zoom.addEventListener('input',()=>{const c=S/2,old=base*k;k=+zoom.value;const now=base*k;x=c-(c-x)*now/old;y=c-(c-y)*now/old;clamp();});"
                 "document.getElementById('crop-cancel').onclick=()=>{close();document.getElementById('photo-input').value='';};"
                 "document.getElementById('crop-ok').onclick=async()=>{const sc=base*k,c=document.createElement('canvas');c.width=c.height=256;"
                 "c.getContext('2d').drawImage(im,-x/sc,-y/sc,S/sc,S/sc,0,0,256,256);"
                 "try{const r=await fetch('/me/photo',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({img:c.toDataURL('image/jpeg',0.85)})});"
                 "const j=await r.json();location.href='/me/settings'+(j.msg?'?msg='+encodeURIComponent(j.msg):'');}"
                 "catch(err){location.href='/me/settings?msg='+encodeURIComponent('사진을 바꾸지 못했어요. 다시 해 주세요.');}};})();</script>")  # fmt: skip
        inner = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] mx-auto pt-14 pb-24 bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-6">'
                 '<a class="pt-5 flex items-center gap-space-xs text-on-surface-variant hover:text-primary" href="/me"><span class="material-symbols-outlined text-[18px]">arrow_back</span>'
                 '<span class="font-label-regular text-label-regular font-medium">내 프로필</span></a>'
                 '<h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight mt-space-sm">설정</h1>'
                 f'<span class="font-body-compact text-body-compact text-on-surface-variant truncate">{e(email)}</span>'
                 + (f'<p class="mt-space-sm font-body-compact text-body-compact text-tertiary" role="alert">{e(msg)}</p>' if msg else "")
                 + photo + '<form method="post" action="/me/profile" class="mt-space-lg flex flex-col gap-space-sm">'
                 '<label class="font-label-regular text-label-regular text-on-surface" for="nick">닉네임</label>'
                 f'<input class="{field}" id="nick" name="nickname" maxlength="20" required value="{e(nick or "")}">'
                 '<label class="font-label-regular text-label-regular text-on-surface" for="bio">자기소개</label>'
                 f'<textarea class="{field}" id="bio" name="bio" maxlength="{BIO_MAX}" rows="2">{e(bio or "")}</textarea>'
                 '<button class="self-end px-4 py-2 rounded-lg bg-primary text-on-primary font-label-regular text-label-regular font-semibold" type="submit">저장</button></form>'
                 '<section class="mt-space-lg flex flex-col divide-y divide-surface-container-high/80 border-y border-surface-container-high">'
                 + row("event", "가입한 날", f"{joined.year}년 {joined.month}월 {joined.day}일")
                 + row("bookmark", "담은 종목", f'<a class="text-primary" href="/">{held} / {MAX_STOCKS}개</a>')
                 + switch + "</section>"
                 '<button class="mt-space-xl w-full py-3 rounded-lg border border-outline-variant/60 text-on-surface-variant font-body-reading-strong text-body-compact hover:bg-surface-container-low transition-colors" '
                 'onclick="if(confirm(\'현재 계정에서 로그아웃할까요?\'))location.href=\'/logout\'" type="button">로그아웃</button>'
                 '<form method="post" action="/me/delete" onsubmit="return confirm(\'탈퇴하면 이메일과 담은 종목, 기록이 모두 지워지고 되돌릴 수 없어요. 탈퇴할까요?\')">'
                 '<button class="mt-space-sm w-full py-3 font-label-regular text-label-regular text-tertiary hover:underline" type="submit">탈퇴하기</button></form>'
                 '<p class="mt-space-lg flex justify-center gap-3 font-label-micro text-label-micro text-outline"><a class="underline" href="/privacy">개인정보 처리방침</a><span>·</span><a class="underline" href="/method">계산 방법</a></p>'
                 '</div></main>' + bottom_nav("me"))  # fmt: skip
        return page("설정", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    # ---- 팔로우 · 리그램 · 피드 (뉴닉 「뉴니커」처럼 — 좋아한 글을 내 팔로워에게) ----

    def counts(self, uid: int) -> tuple[int, int]:
        q = "select count(*) from follows where {} = ?"
        return (self.con.execute(q.format("followee_id"), (uid,)).fetchone()[0],
                self.con.execute(q.format("follower_id"), (uid,)).fetchone()[0])  # fmt: skip

    @staticmethod
    def face(name: str, size: str = "w-9 h-9", photo: str | None = None) -> str:
        inside = f'<img alt="" class="w-full h-full object-cover" src="{e(photo)}">' if photo else e((name or "?")[:1].upper())
        return (f'<span class="{size} shrink-0 overflow-hidden rounded-full bg-primary-fixed text-primary flex items-center justify-center font-label-regular text-label-regular font-semibold">'
                f'{inside}</span>')  # fmt: skip

    def follow_line(self, uid: int) -> str:
        fer, fing = self.counts(uid)
        return (f'<p class="font-label-regular text-label-regular text-on-surface-variant">팔로워 <b class="text-on-surface">{fer:,}</b>'
                f'<span class="mx-2 text-outline-variant">|</span>팔로잉 <b class="text-on-surface">{fing:,}</b></p>')  # fmt: skip

    def save_photo(self, uid: int, img: str):
        """프로필 사진 — JPEG 만, 작게(PHOTO_MAX). 브라우저가 이미 256px 정사각형으로 잘라 보낸다."""
        import base64
        import binascii

        def reply(msg="", code="200 OK"):
            return code, [("Content-Type", "application/json; charset=utf-8")], json.dumps({"msg": msg}, ensure_ascii=False)

        head = "data:image/jpeg;base64,"
        try:
            raw = base64.b64decode(img[len(head):], validate=True) if img.startswith(head) else b""
        except binascii.Error:
            raw = b""
        if not raw.startswith(b"\xff\xd8\xff") or len(raw) > PHOTO_MAX:
            return reply("사진을 바꾸지 못했어요. 다른 사진으로 해 주세요.", "400 Bad Request")
        self.con.execute("update users set photo = ?, photo_at = ? where id = ?", (raw, datetime.now().isoformat(timespec="seconds"), uid))
        self.con.commit()
        return reply()

    def nick_error(self, uid: int, nick: str) -> str:
        """닉네임 검사 — 문제가 없으면 빈 글. 겹침은 대소문자를 무시하고 본다(DB 유일 색인과 같게)."""
        if not NICK.fullmatch(nick):
            return "닉네임은 한글·영문·숫자·_ 2~20자로 정해 주세요."
        if notes.FORBIDDEN.search(nick):
            return "닉네임에 쓸 수 없는 말이 들어 있어요."
        if self.con.execute("select 1 from users where nickname = ? collate nocase and id != ?", (nick, uid)).fetchone():
            return f"「{nick}」은(는) 이미 누가 쓰고 있어요. 다른 닉네임으로 해 주세요."
        return ""

    def welcome_page(self, nick: str = "", error: str = "") -> str:
        inner = ('<main class="flex flex-col relative w-full max-w-[480px] mx-auto bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pt-16 pb-12">'
                 '<span class="font-display-editorial text-display-editorial text-primary tracking-tight">한장</span>'
                 '<h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight mt-space-md">닉네임을 정해 주세요</h1>'
                 '<p class="font-body-compact text-body-compact text-on-surface-variant mt-1">다른 사람에게는 이메일 대신 이 이름이 보여요. 한글·영문·숫자 2~20자, 다른 사람과 겹칠 수 없어요.</p>'
                 '<form method="post" action="/welcome" class="mt-space-lg flex flex-col gap-space-sm">'
                 f'<input autofocus class="w-full font-body-reading text-body-reading bg-surface-container-low rounded-lg px-4 py-3.5 focus:outline-none" maxlength="20" name="nickname" required value="{e(nick)}">'
                 + (f'<p class="font-body-compact text-body-compact text-tertiary" role="alert">{e(error)}</p>' if error else "")
                 + '<button class="w-full py-3.5 bg-primary text-on-primary font-body-reading-strong text-body-reading-strong rounded-lg shadow-sm" type="submit">시작하기</button></form>'
                 '</div></main>')  # fmt: skip
        return page("닉네임", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    def welcome(self, uid: int, nick: str):
        if err := self.nick_error(uid, nick):
            return "200 OK", [], self.welcome_page(nick, err)
        try:
            self.con.execute("update users set nickname = ? where id = ?", (nick, uid))
            self.con.commit()
        except sqlite3.IntegrityError:  # 거의 같은 때 누가 먼저 가져간 경우
            return "200 OK", [], self.welcome_page(nick, f"「{nick}」은(는) 이미 누가 쓰고 있어요. 다른 닉네임으로 해 주세요.")
        return self.see("/")

    def save_profile(self, uid: int, nick: str, bio: str):
        if err := self.nick_error(uid, nick):  # 닉네임은 바꿀 수는 있어도 비울 수는 없다
            return self.see("/me/settings?msg=" + quote(err))
        if len(bio) > BIO_MAX or notes.FORBIDDEN.search(bio):
            return self.see("/me/settings?msg=" + quote("자기소개에 종목을 사라·팔라는 말이나 추천은 쓸 수 없어요."))
        try:
            self.con.execute("update users set nickname = ?, bio = ? where id = ?", (nick, bio or None, uid))
            self.con.commit()
        except sqlite3.IntegrityError:
            return self.see("/me/settings?msg=" + quote(f"「{nick}」은(는) 이미 누가 쓰고 있어요."))
        return self.see("/me/settings")

    def regram_form(self, uid: int, kind: str, ref: str, week: str) -> str:
        """노트·읽기 팁 글 아래 — 리그램(한 줄 코멘트는 선택). 이미 했으면 취소 버튼."""
        done = self.con.execute("select 1 from regrams where user_id = ? and kind = ? and ref = ? and week = ?", (uid, kind, ref, week)).fetchone()
        (n,) = self.con.execute("select count(*) from regrams where kind = ? and ref = ? and week = ?", (kind, ref, week)).fetchone()
        undo = '<input type="hidden" name="undo" value="1">' if done else ""
        return (f'<form method="post" action="/regram" class="flex items-center gap-1.5"><input type="hidden" name="k" value="{e(kind)}"><input type="hidden" name="r" value="{e(ref)}"><input type="hidden" name="w" value="{e(week)}">{undo}'
                f'<button type="submit" aria-pressed="{"true" if done else "false"}" aria-label="리그램{" 취소" if done else ""} — 내 팔로워의 피드에 보여요" title="리그램 — 내 팔로워의 피드에 보여요" '
                f'class="w-10 h-10 rounded-full flex items-center justify-center border {"border-secondary/40 bg-secondary-container/60 text-secondary" if done else "border-outline-variant/60 text-outline"} transition-colors">'
                f'<span class="material-symbols-outlined text-[20px]">repeat</span></button>'
                f'<span class="font-label-regular text-label-regular text-on-surface-variant font-semibold">{n:,}</span></form>')  # fmt: skip

    def regram(self, uid: int, form: dict):
        kind, ref, week = form.get("k", ""), form.get("r", ""), form.get("w", "")
        back = f"/n/{quote(ref)}" if kind == "note" else f"/learn/{quote(ref)}"
        ok = (kind == "note" and self.con.execute("select 1 from notes where ticker = ? and week = ?", (ref, week)).fetchone()) or (
            kind == "learn" and ref in learn.BY_SLUG and week == "")
        if not ok:
            return self.see("/feed")
        if form.get("undo"):
            self.con.execute("delete from regrams where user_id = ? and kind = ? and ref = ? and week = ?", (uid, kind, ref, week))
            self.con.commit()
            return self.see(back)
        if not self.con.execute("select nickname from users where id = ?", (uid,)).fetchone()[0]:
            return self.see("/me/settings?msg=" + quote("리그램하려면 닉네임을 먼저 정해 주세요. 팔로워에게 이 이름으로 보여요."))
        self.con.execute("insert or ignore into regrams (user_id, kind, ref, week, at) values (?, ?, ?, ?, ?)",
                         (uid, kind, ref, week, datetime.now().isoformat()))  # fmt: skip
        self.con.commit()
        return self.see(back)

    def regram_list(self, where: str, args: tuple, title: str, mine: bool = False, photos: "Photos | None" = None) -> str:
        photos = photos or Photos()
        rows = self.con.execute(
            "select r.user_id, u.nickname, r.kind, r.ref, r.week, r.comment, r.at, u.photo_at from regrams r join users u on u.id = r.user_id "
            + where + " order by r.at desc limit 50", args).fetchall()  # fmt: skip
        cards = []
        for who, nick, kind, ref, week, comment, at, pat in rows:
            if kind == "note":
                hit = self.con.execute("select s.name, n.body, s.induty_code from stocks s join notes n on n.ticker = s.ticker and n.week = ?"
                                       " where s.ticker = ?", (week, ref)).fetchone()  # fmt: skip
                if not hit:
                    continue
                b = json.loads(hit[1])
                head, sub, href, src, img = b["headline"], gist(b), f"/n/{ref}", hit[0], photos.pick(None, hit[2], hit[0])
            else:
                a = learn.BY_SLUG.get(ref)
                if not a:
                    continue
                head, sub, href, src, img = a["title"], a["lead"].replace("**", ""), f"/learn/{ref}", "읽기 팁", "/static/photos/securities.jpg"
            d = at[:10].replace("-", ".")
            top = "" if mine else (f'<a href="/u/{who}" class="flex items-center gap-2">{self.face(nick, "w-6 h-6", photo_url(who, pat))}'
                                   f'<span class="font-label-regular text-label-regular text-on-surface-variant"><b class="text-on-surface font-semibold">{e(nick)}</b>님이 리그램</span></a>')  # fmt: skip
            cards.append(story(href, img, head, sub, src, d, top))
        if not cards:
            return ""
        body = "".join(cards)
        return (f'<section class="mt-space-lg"><h2 class="font-headline-sm text-headline-sm text-on-surface">{e(title)}</h2>'
                f'<div class="flex flex-col">{body}</div></section>')  # fmt: skip

    def people(self, uid: int, q: str) -> str:
        if not q:
            return ""
        rows = self.con.execute("select id, nickname, bio, photo_at from users where nickname is not null and id != ? and nickname like ? limit 20",
                                (uid, f"%{q}%")).fetchall()  # fmt: skip
        items = "".join(f'<a href="/u/{i}" class="py-space-sm flex items-center gap-space-sm">{self.face(n, photo=photo_url(i, p))}<span class="flex flex-col min-w-0">'
                        f'<span class="font-label-regular text-label-regular text-on-surface font-semibold">{e(n)}</span>'
                        f'<span class="font-label-micro text-label-micro text-on-surface-variant truncate">{e(b or "")}</span></span></a>' for i, n, b, p in rows)  # fmt: skip
        none = '<p class="py-2 font-body-compact text-body-compact text-outline">그런 닉네임이 없어요.</p>'
        return f'<div class="mt-space-sm flex flex-col divide-y divide-surface-container-high/80">{items or none}</div>'

    def latest(self, uid: int, photos: "Photos") -> str:
        """최근 소식 — 사건마다 쓴 기사. 담은 종목 먼저, 최신 먼저."""
        rows = self.con.execute(
            "select a.id, a.kind, a.date, a.body, s.name, s.induty_code, a.ticker in (select ticker from holdings where user_id = ?) mine"
            " from articles a join stocks s using(ticker) order by mine desc, a.date desc, a.id desc limit 30", (uid,)).fetchall()  # fmt: skip
        if not rows:
            return ""
        items = "".join(
            story(f"/a/{i}", photos.pick(k, ind, name),
                  (b := json.loads(body))["title"], b["paragraphs"][0]["text"], name + (" · 내 종목" if mine else ""), d.replace("-", "."))
            for i, k, d, body, name, ind, mine in rows)  # fmt: skip
        return (f'<section class="mt-space-lg"><h2 class="font-headline-sm text-headline-sm text-on-surface">최근 소식</h2>'
                f'<div class="flex flex-col">{items}</div></section>')  # fmt: skip

    def article(self, uid: int, aid: int):
        row = self.con.execute("select a.ticker, a.kind, a.date, a.body, s.name, s.induty_code from articles a join stocks s using(ticker)"
                               " where a.id = ?", (aid,)).fetchone()  # fmt: skip
        if not row:
            return "404 Not Found", [], self.simple("없음", "없는 기사예요. <a class='text-primary underline' href='/feed'>피드</a>")
        t, kind, d, body, name, ind = row
        b = json.loads(body)
        img = f"/static/photos/{KIND_PHOTO[kind]}.jpg" if kind in KIND_PHOTO else photo_for(ind, name)
        def cite(p):  # 출처 번호 → 원문 바로 열기 (작은 회색 위첨자)
            return e(p["text"]) + "".join(f'<a class="{CITE}" href="{e(safe_url(b["links"].get(r, "#")))}" target="_blank" rel="noopener">[{e(r)}]</a>' for r in p["refs"])

        paras = "".join(f'<p class="text-[15px] leading-[27px] text-on-surface mb-4">{cite(p)}</p>' for p in b["paragraphs"])
        inner = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] mx-auto pt-14 pb-24 bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-6">'
                 '<a class="pt-4 flex items-center gap-space-xs text-on-surface-variant hover:text-primary" href="/feed"><span class="material-symbols-outlined text-[18px]">arrow_back</span><span class="font-label-regular text-label-regular">피드</span></a>'
                 f'<h1 class="mt-space-sm text-[22px] leading-[30px] font-bold tracking-tight text-on-surface">{e(b["title"])}</h1>'
                 f'<p class="mt-1 text-[12px] text-outline">{e(name)} · {e(d.replace("-", "."))}</p>'
                 f'<img alt="" class="mt-space-md w-full aspect-[16/10] object-cover rounded-xl" src="{e(img)}">'
                 '<p class="mt-1 text-right text-[11px] text-outline">주제 사진 · Unsplash</p>'
                 f'<article class="mt-space-md">{paras}</article>'
                 f'<a class="mt-space-sm flex items-center justify-between rounded-xl border border-outline-variant/50 px-space-md py-3" href="/n/{e(t)}">'
                 f'<span class="flex items-center gap-2">{logo(name, self.con.execute("select homepage from stocks where ticker = ?", (t,)).fetchone()[0], "w-8 h-8")}'
                 f'<span class="text-[14px] font-semibold text-on-surface">{e(name)} 분석 보고서 보기</span></span><span class="material-symbols-outlined text-outline">chevron_right</span></a>'
                 '<p class="mt-space-md text-[11px] text-outline leading-relaxed">공시·재무에서 코드가 뽑은 사실을 바탕으로 AI가 쓴 글이에요. 숫자는 코드가 원문과 대조했어요. 작은 번호를 누르면 원문이 열려요. 사라·팔아라는 뜻이 아니에요.</p>'
                 + "</div></main>" + bottom_nav("feed"))  # fmt: skip
        return "200 OK", [], page(b["title"], "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    def popular(self, photos: "Photos") -> str:
        """팔로우한 사람의 리그램이 없을 때 — 이번 주 노트를 많이 읽힌 순서로."""
        rows = self.con.execute(
            "select s.ticker, s.name, n.body, s.induty_code, n.made_at,"
            " (select count(*) from views v where v.page = 'note' and v.ticker = s.ticker and v.at >= n.week) c"
            " from notes n join stocks s using(ticker) where n.week = (select max(week) from notes) order by c desc, s.name limit 20").fetchall()  # fmt: skip
        cards = "".join(story(f"/n/{t}", photos.pick(None, ind, name), json.loads(b)["headline"], gist(json.loads(b)), name, made[:10].replace("-", "."))
                        for t, name, b, ind, made, c in rows)  # fmt: skip
        return (f'<section class="mt-space-lg"><h2 class="font-headline-sm text-headline-sm text-on-surface">많이 읽은 노트</h2>'
                f'<div class="flex flex-col">{cards}</div></section>')  # fmt: skip

    def feed(self, uid: int, q: str) -> str:
        mine = "where r.user_id in (select followee_id from follows where follower_id = ?) or r.user_id = ?"
        (n,) = self.con.execute("select count(*) from regrams r " + mine, (uid, uid)).fetchone()
        photos = Photos()
        news = self.latest(uid, photos)
        body = news + (self.regram_list(mine, (uid, uid), "팔로우한 사람들의 리그램", photos=photos) if n else "") + ("" if news or n else self.popular(photos))
        inner = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] mx-auto pt-14 pb-24 bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-6">'
                 '<header class="pt-5"><h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight">피드</h1></header>'
                 + '<form method="get" action="/feed" class="mt-space-md flex items-center gap-space-sm bg-surface-container-low rounded-xl px-4 py-2.5"><span class="material-symbols-outlined text-outline text-[20px]">person_search</span>'
                 f'<input class="flex-1 bg-transparent font-body-compact text-body-compact focus:outline-none" name="q" value="{e(q)}" placeholder="닉네임으로 사람 찾기"></form>'
                 + self.people(uid, q) + body
                 + "</div></main>" + bottom_nav("feed"))  # fmt: skip
        return page("피드", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    def user_page(self, uid: int, other: int):
        row = self.con.execute("select nickname, bio, photo_at from users where id = ? and nickname is not null", (other,)).fetchone()
        if not row:  # 닉네임이 없는 사람은 남에게 보이지 않는다
            return "404 Not Found", [], self.simple("없음", "없는 사람이에요. <a class='text-primary underline' href='/feed'>피드</a>")
        nick, bio, pat = row
        on = self.con.execute("select 1 from follows where follower_id = ? and followee_id = ?", (uid, other)).fetchone()
        btn = "border border-outline-variant/60 text-on-surface-variant" if on else "bg-primary text-on-primary"
        inner = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] mx-auto pt-14 pb-24 bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-6">'
                 f'<header class="pt-5 flex items-center gap-space-md">{self.face(nick, "w-14 h-14", photo_url(other, pat))}<div class="flex flex-col min-w-0 flex-1">'
                 f'<h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight truncate">{e(nick)}</h1>{self.follow_line(other)}</div>'
                 f'<form method="post" action="/follow"><input type="hidden" name="u" value="{other}"><button class="px-4 py-2 rounded-lg font-label-regular text-label-regular font-semibold {btn}" type="submit">{"팔로잉" if on else "팔로우"}</button></form></header>'
                 + (f'<p class="mt-space-md font-body-compact text-body-compact text-on-surface whitespace-pre-line">{e(bio)}</p>' if bio else "")
                 + self.regram_list("where r.user_id = ?", (other,), f"{nick}의 리그램", mine=True)
                 + "</div></main>" + bottom_nav("feed"))  # fmt: skip
        return "200 OK", [], page(nick, "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    # ---- 큰손 포트폴리오 (읽기 팁 맨 아래) — 기관이 5% 넘게 가진 종목, 전체 상장사 ----

    # 기관 홈페이지 — 로고(Brandfetch)를 찾는 열쇠. 없으면 색 동그라미 (국민연금은 흰 로고라 뺌, 계열사는 그룹 로고가 또렷함)
    BIG_HOME = {"blackrock": "blackrock.com", "capital": "capitalgroup.com", "samsungam": "samsung.com",
                "miraeam": "miraeasset.com", "shinhanam": "shinhangroup.com", "kbam": "kbfg.com",
                "kitm": "kitmc.com", "align": "alignpartners.co.kr", "silchester": "silchester.com", "pzena": "pzena.com"}  # fmt: skip

    def big_list(self) -> str:
        counts = dict(self.con.execute("select inst, count(*) from big_holdings group by inst").fetchall())
        rows = [(k, v) for k, v in holders.BIG.items() if counts.get(k)]
        if not rows:
            return ""
        rows.sort(key=lambda kv: -counts[kv[0]])
        items = "".join(
            f'<a href="/learn/big/{k}" class="py-3.5 flex items-center gap-space-md">{logo(name, self.BIG_HOME.get(k), "w-10 h-10")}'
            f'<span class="flex flex-col min-w-0 flex-1"><span class="font-body-reading-strong text-body-compact text-on-surface">{e(name)}</span>'
            f'<span class="font-label-micro text-label-micro text-on-surface-variant truncate">{e(intro)}</span></span>'
            f'<span class="text-[12px] text-outline shrink-0">{counts[k]:,}종목</span></a>' for k, (name, _, intro) in rows)  # fmt: skip
        return ('<section class="mt-space-xl pt-space-md border-t border-surface-container-high"><h2 class="font-headline-md text-headline-md text-primary border-l-4 border-primary pl-2 leading-none">큰손 포트폴리오</h2>'
                '<p class="mt-2 font-body-compact text-body-compact text-on-surface-variant">국민연금·운용사 같은 기관이 5% 넘게 가진 회사들이에요. 공시로 알려진 것만 보여요.</p>'
                f'<div class="flex flex-col divide-y divide-surface-container-high/80">{items}</div></section>')  # fmt: skip

    def big(self, uid: int, key: str, wrap: str, end: str):
        if key not in holders.BIG:
            return "404 Not Found", [], self.simple("없음", "없는 기관이에요. <a class='text-primary underline' href='/learn'>읽기 팁</a>")
        name, _, intro = holders.BIG[key]
        rows = self.con.execute(
            "select b.stock_code, b.corp_name, b.rate, b.rate_chg, b.date, b.rcept_no, s.ticker is not null, s.homepage"
            " from big_holdings b left join stocks s on s.ticker = b.stock_code where b.inst = ? order by b.rate desc", (key,)).fetchall()  # fmt: skip
        inds = [x for (x,) in self.con.execute("select induty_code from big_holdings where inst = ?", (key,))]
        since = (date.today() - timedelta(days=90)).isoformat()
        recent = sorted((r for r in rows if r[3] and r[4] >= since), key=lambda r: r[4], reverse=True)[:8]

        def row(i, r):
            code, corp, rate, chg, d, rno, ours, home = r
            href = f"/n/{code}" if ours else DART_VIEW.format(rno)
            tag = (f'<span class="text-[11px] {"text-secondary" if chg > 0 else "text-tertiary"}">{"늘림" if chg > 0 else "줄임"} {abs(chg):.2f}%p</span>' if chg else "")
            return (f'<a href="{e(href)}" {"" if ours else "target=_blank rel=noopener"} class="py-3 flex items-center gap-3">'
                    f'<span class="w-5 text-right text-[12px] text-outline tabular-nums">{i}</span>{logo(corp, home, "w-9 h-9")}'
                    f'<span class="flex flex-col min-w-0 flex-1"><span class="text-[15px] font-semibold text-on-surface truncate">{e(corp)}</span>'
                    f'<span class="text-[12px] text-on-surface-variant">지분 {rate:.2f}% {tag}</span></span>'
                    f'<span class="text-[11px] text-outline shrink-0">{e(d[2:].replace("-", "."))}</span></a>')  # fmt: skip

        body = (f'<div class="flex items-center py-space-sm"><a class="flex items-center gap-space-xs text-on-surface-variant hover:text-primary" href="/learn"><span class="material-symbols-outlined text-[18px]">arrow_back</span><span class="font-label-regular text-label-regular font-medium">읽기 팁</span></a></div>'
                f'<header class="flex items-center gap-space-md">{logo(name, self.BIG_HOME.get(key), "w-14 h-14")}<div class="flex flex-col"><h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight">{e(name)}</h1>'
                f'<span class="text-[12px] text-outline">5% 넘게 가진 회사 {len(rows):,}곳</span></div></header>'
                f'<p class="mt-space-md font-body-compact text-body-compact text-on-surface">{e(intro)}</p>'
                + donut([sector(x) for x in inds])
                + (f'<section class="mt-space-lg"><h2 class="font-headline-sm text-headline-sm text-on-surface">최근 늘리고 줄인 회사</h2><div class="flex flex-col divide-y divide-surface-container-high/70">'
                   + "".join(row(i, r) for i, r in enumerate(recent, 1)) + "</div></section>" if recent else "")
                + '<section class="mt-space-lg"><h2 class="font-headline-sm text-headline-sm text-on-surface">지분이 큰 순서</h2><div class="flex flex-col divide-y divide-surface-container-high/70">'
                + "".join(row(i, r) for i, r in enumerate(rows, 1)) + "</div></section>"
                '<p class="mt-space-md text-[11px] text-outline leading-relaxed">한국엔 기관의 보유 종목 전체를 알리는 제도가 없어서, 5% 넘게 가진 회사만 보여요(대량보유 보고). '
                "지분율은 가장 최근 보고 기준이에요. 따라 사고팔라는 뜻이 아니에요. 자료: DART</p>")  # fmt: skip
        return "200 OK", [], page(name, "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", wrap + body + end)

    # ---- 공개 페이지: 개인정보 처리방침 · 계산 방법 (로그인 없이) ----

    def doc(self, path: str, uid: int | None) -> str:
        contact = env().get("PRIVACY_CONTACT", "")
        title, parts = {"/privacy": ("개인정보 처리방침", policy.privacy(contact)), "/method": ("계산 방법", policy.method()),
                        "/help/login": ("로그인 링크가 안 와요", policy.login_help(contact))}[path]  # fmt: skip
        body = "".join(
            f'<section class="mt-space-lg"><h2 class="font-headline-sm text-headline-sm text-primary mb-space-xs">{e(h)}</h2>'
            + "".join(f'<p class="font-body-compact text-body-compact text-on-surface leading-relaxed mb-space-sm">{self.marked(x)}</p>' for x in ps)
            + "</section>" for h, ps in parts)  # fmt: skip
        inner = ('<main class="flex flex-col relative w-full max-w-[480px] mx-auto bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pt-space-lg pb-24">'
                 '<a class="flex items-center gap-space-xs text-on-surface-variant hover:text-primary" href="/"><span class="material-symbols-outlined text-[18px]">arrow_back</span>'
                 '<span class="font-label-regular text-label-regular font-medium">한장</span></a>'
                 f'<h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight mt-space-md">{e(title)}</h1>'
                 f'<p class="font-label-micro text-label-micro text-outline mt-1">마지막 고침 {policy.UPDATED}</p>{body}</div></main>'
                 + (bottom_nav("me") if uid else ""))  # fmt: skip
        return page(title, "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    # ---- 읽기 팁 (시안에 없는 화면 — 같은 디자인 말투로) ----

    @staticmethod
    def marked(text: str) -> str:
        """「**핵심 말**」 → 진한 초록 굵은 글씨. 나머지는 그대로 이스케이프."""
        return re.sub(r"\*\*(.+?)\*\*", r'<strong class="font-semibold text-primary">\1</strong>', e(text))

    def learn(self, uid: int, slug: str):
        wrap = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] mx-auto pt-14 pb-24 bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-6">')
        end = ('<p class="font-label-micro text-label-micro text-outline text-center py-space-lg">설명을 위한 글이에요. 특정 종목이나 상품을 추천하지 않아요.</p></div></main>'
               + bottom_nav("learn"))
        if slug.startswith("big/"):  # 큰손 포트폴리오 한 곳
            return self.big(uid, slug[4:], wrap, end)
        a = learn.BY_SLUG.get(slug)
        if slug == "long-short":  # 숫자를 DB 의 지수로 채운 글
            a = learn.long_short(self.con) or a
        if slug and not a:
            return "404 Not Found", [], self.simple("없음", "없는 글이에요. <a class='text-primary underline' href='/learn'>읽기 팁</a>")
        if a:
            more_label, more_url = a["more"]
            inner = (wrap + '<div class="flex items-center py-space-sm"><a class="flex items-center gap-space-xs text-on-surface-variant hover:text-primary transition-colors" href="/learn"><span class="material-symbols-outlined text-[18px]">arrow_back</span>'
                     f'<span class="font-label-regular text-label-regular font-medium">읽기 팁</span></a><span class="ml-2 px-2 py-0.5 rounded-full bg-primary text-on-primary font-label-micro text-label-micro font-semibold">{e(a["cat"])}</span></div>'
                     f'<h1 class="font-display-editorial text-display-editorial text-on-surface font-semibold tracking-tight mb-space-sm">{e(a["title"])}</h1>'
                     f'<aside class="mb-space-lg py-space-md px-space-lg bg-surface-container-low rounded-xl border-l-2 border-primary"><p class="font-body-reading-strong text-body-reading-strong text-primary leading-relaxed">{self.marked(a["lead"])}</p></aside>'
                     + "".join(f'<p class="font-body-reading text-body-reading text-on-surface leading-loose mb-space-md">{self.marked(x)}</p>' for x in a["body"][:1])
                     + (index_chart(a["charts"]) + loss_bars(a["charts"]) if a.get("charts") else "")
                     + "".join(f'<p class="font-body-reading text-body-reading text-on-surface leading-loose mb-space-md">{self.marked(x)}</p>' for x in a["body"][1:])
                     + '<section class="mt-space-sm mb-space-lg rounded-xl bg-primary-fixed/40 border-l-4 border-primary px-space-md py-space-md flex flex-col gap-1.5"><span class="flex items-center gap-1 font-label-regular text-label-regular text-primary font-bold"><span class="material-symbols-outlined text-[18px]">lightbulb</span>기억할 것</span>'
                     + "".join(f'<p class="flex items-start gap-1.5 font-body-compact text-body-compact text-on-surface"><span class="material-symbols-outlined text-primary text-[16px] mt-0.5">check_circle</span><span>{self.marked(x)}</span></p>' for x in a["points"])
                     + f'</section><a class="inline-flex items-center gap-1 font-label-regular text-label-regular text-primary font-semibold hover:underline" href="{e(more_url)}" target="_blank" rel="noopener">더 알아보기: {e(more_label)}<span class="material-symbols-outlined text-[14px]">open_in_new</span></a>'
                     + '<div class="mt-space-lg flex justify-end">' + self.regram_form(uid, "learn", slug, "") + "</div>" + end)  # fmt: skip
            return "200 OK", [], page(a["title"], "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)
        groups = "".join(
            f'<section class="mt-space-xl pt-space-md border-t border-surface-container-high"><div class="flex items-center justify-between mb-space-sm"><h2 class="font-headline-md text-headline-md text-primary border-l-4 border-primary pl-2 leading-none">{e(c)}</h2></div>'
            f'<div class="flex flex-col divide-y divide-surface-container-high/80">'
            + "".join(f'<a href="/learn/{e(x["slug"])}" class="py-3.5 flex items-start justify-between gap-space-sm"><div class="flex flex-col gap-0.5"><span class="font-body-reading-strong text-body-reading-strong text-on-surface">{e(x["title"])}</span>'
                      f'<span class="font-body-compact text-body-compact text-on-surface-variant">{e(x["lead"].replace("**", ""))}</span></div><span class="material-symbols-outlined text-primary text-[18px] mt-1">chevron_right</span></a>'
                      for x in learn.ARTICLES if x["cat"] == c) + "</div></section>" for c in learn.CATS)  # fmt: skip
        inner = (wrap + '<header class="pt-5"><h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight">읽기 팁</h1>'
                 '<p class="font-body-compact text-body-compact text-on-surface-variant mt-1">주식을 처음 시작할 때 알아 두면 좋은 기초를 쉬운 말로 풀었어요.</p></header>' + groups + self.big_list() + end)  # fmt: skip
        return "200 OK", [], page("읽기 팁", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)


if __name__ == "__main__":
    import threading
    from socketserver import ThreadingMixIn
    from wsgiref.simple_server import WSGIServer, make_server

    class Server(ThreadingMixIn, WSGIServer):
        """연결마다 스레드 — 브라우저가 미리 열어 둔 빈 연결 하나에 서버 전체가 멈추지 않게.
        ponytail: DB 는 연결 하나를 잠금으로 돌려 쓴다. 사용자가 늘면 요청마다 연결로"""

        daemon_threads = True

    sys.stderr.reconfigure(encoding="utf-8")  # 윈도우 콘솔(cp949)에서 한글 로그가 깨지지 않게
    cfg = env()
    if len(cfg.get("SECRET", "")) < 32:  # 짧거나 없는 키로는 로그인 링크·쿠키를 위조당한다 — 켜지 않는다
        sys.exit("SECRET 이 없거나 짧아요(32자 이상). 만들기: python -c \"import secrets; print(secrets.token_hex(32))\"")
    db.connect().close()
    app = App(sqlite3.connect(db.PATH, timeout=30, check_same_thread=False), cfg["SECRET"])
    lock = threading.Lock()

    def serial(environ, start_response):
        with lock:
            return app(environ, start_response)

    host, port = cfg.get("HOST", "127.0.0.1"), int(cfg.get("PORT", "8000"))  # 서버에선 127.0.0.1 그대로 두고 앞의 Caddy 가 https 를 맡는다
    print(f"한장 — http://{host}:{port}", file=sys.stderr)
    make_server(host, port, serial, server_class=Server).serve_forever()
