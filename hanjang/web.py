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
from datetime import date, datetime
from urllib.parse import parse_qs, quote

from hanjang import db, learn, mail, notes
from hanjang.sources import env, industry_label

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


# --- 시안 공통 머리 (Stitch 시안의 <head> 그대로) ---

HEAD = """<meta charset="utf-8"><meta content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover" name="viewport"><link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200" rel="stylesheet"><link href="https://fonts.googleapis.com" rel="preconnect"><link crossorigin="" href="https://fonts.gstatic.com" rel="preconnect"><link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&amp;family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,600;1,6..72,400&amp;display=swap" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&amp;display=swap" rel="stylesheet"><style>@layer base{html,body{width:100vw;margin:0;padding:0;}body{overscroll-behavior:none;}.pb-safe{padding-bottom:env(safe-area-inset-bottom,0px);}.pt-safe{padding-top:env(safe-area-inset-top,0px);}main>:first-child{margin-top:0!important;}main>:last-child{margin-bottom:0!important;}}::-webkit-scrollbar{display:none;}</style><script src="https://cdn.tailwindcss.com"></script><script id="tailwind-config">tailwind.config = { darkMode: "class", theme: { extend: { "colors": { "on-secondary-container": "#2e6e4e", "secondary-fixed": "#aef1c9", "outline-variant": "#c0c8c4", "tertiary": "#741f11", "on-background": "#1b1b1d", "surface-container-low": "#f6f3f5", "on-tertiary-fixed-variant": "#802919", "surface-container-lowest": "#ffffff", "surface-container": "#f0edef", "surface-dim": "#dcd9dc", "outline": "#717975", "primary-fixed": "#bceddc", "primary-container": "#2f5d50", "error": "#ba1a1a", "error-container": "#ffdad6", "on-error": "#ffffff", "tertiary-fixed": "#ffdad3", "surface-bright": "#fcf8fb", "surface": "#fcf8fb", "on-primary-fixed-variant": "#204f42", "background": "#fcf8fb", "primary-fixed-dim": "#a0d1c0", "primary": "#154539", "surface-variant": "#e4e2e4", "on-secondary": "#ffffff", "on-primary-fixed": "#002019", "secondary-container": "#abeec6", "surface-tint": "#396759", "on-primary": "#ffffff", "surface-container-highest": "#e4e2e4", "tertiary-fixed-dim": "#ffb4a5", "on-tertiary": "#ffffff", "on-secondary-fixed-variant": "#095134", "on-tertiary-fixed": "#3f0400", "on-surface": "#1b1b1d", "inverse-primary": "#a0d1c0", "secondary": "#296a4a", "tertiary-container": "#933625", "inverse-on-surface": "#f3f0f2", "on-error-container": "#93000a", "on-secondary-fixed": "#002112", "on-surface-variant": "#404945", "inverse-surface": "#303032", "on-tertiary-container": "#ffb8aa", "on-primary-container": "#a3d4c3", "surface-container-high": "#eae7ea", "secondary-fixed-dim": "#93d5ae" }, "borderRadius": { "DEFAULT": "0.25rem", "lg": "0.5rem", "xl": "0.75rem", "full": "9999px" }, "spacing": { "space-md": "0.875rem", "margin": "1rem", "space-xs": "0.25rem", "space-xl": "2rem", "space-lg": "1.25rem", "gutter": "0.75rem", "space-sm": "0.5rem" }, "fontFamily": { "headline-lg": ["Newsreader"], "label-regular": ["Be Vietnam Pro"], "body-reading-strong": ["Be Vietnam Pro"], "label-micro": ["Be Vietnam Pro"], "headline-sm": ["Be Vietnam Pro"], "citation-ref": ["Be Vietnam Pro"], "body-reading": ["Be Vietnam Pro"], "display-editorial": ["Newsreader"], "headline-md": ["Be Vietnam Pro"], "body-compact": ["Be Vietnam Pro"] }, "fontSize": { "headline-lg": ["24px", {"lineHeight": "34px", "letterSpacing": "-0.015em", "fontWeight": "600"}], "label-regular": ["13px", {"lineHeight": "18px", "letterSpacing": "0em", "fontWeight": "500"}], "body-reading-strong": ["16px", {"lineHeight": "28px", "letterSpacing": "-0.01em", "fontWeight": "600"}], "label-micro": ["11px", {"lineHeight": "14px", "letterSpacing": "0.02em", "fontWeight": "600"}], "headline-sm": ["17px", {"lineHeight": "24px", "letterSpacing": "-0.01em", "fontWeight": "600"}], "citation-ref": ["11px", {"lineHeight": "14px", "letterSpacing": "0.04em", "fontWeight": "600"}], "body-reading": ["16px", {"lineHeight": "28px", "letterSpacing": "-0.01em", "fontWeight": "400"}], "display-editorial": ["30px", {"lineHeight": "40px", "letterSpacing": "-0.02em", "fontWeight": "600"}], "headline-md": ["20px", {"lineHeight": "28px", "letterSpacing": "-0.01em", "fontWeight": "600"}], "body-compact": ["14px", {"lineHeight": "22px", "letterSpacing": "-0.005em", "fontWeight": "400"}] } } } };</script>"""


def page(title: str, body_attr: str, inner: str) -> str:
    return (f'<!DOCTYPE html><html lang="ko"><head>{HEAD}<title>{e(title)} · 한장</title></head>'
            f'<body class="{body_attr}">{inner}</body></html>')  # fmt: skip


def avatar(initial: str) -> str:
    """시안의 프로필 사진 자리 — 사진이 없으니 이메일 첫 글자 동그라미."""
    return (f'<span class="w-8 h-8 rounded-full bg-surface-container-high flex items-center justify-center '
            f'text-on-surface-variant font-label-regular text-label-regular">{e(initial.upper())}</span>')  # fmt: skip


def top_bar(initial: str) -> str:
    return ('<header class="fixed top-0 w-full z-50 bg-surface/90 backdrop-blur-xl pt-safe"><div class="h-14 max-w-[480px] mx-auto px-margin flex items-center justify-between"><div class="flex items-center gap-space-sm"><span class="font-display-editorial text-headline-md text-primary tracking-tight">한장</span><span class="text-on-surface-variant font-label-micro text-label-micro uppercase tracking-wider pl-space-xs">Editorial Digest</span></div><div class="flex items-center gap-space-sm">'
            + avatar(initial) + "</div></div></header>")  # fmt: skip


def bottom_nav(tab: str) -> str:
    on = "transition-colors text-primary-container font-semibold"
    off = "text-on-surface-variant hover:text-on-surface transition-colors"
    return ('<nav class="fixed bottom-0 w-full z-50 pb-safe bg-surface/90 backdrop-blur-xl"><div class="max-w-[480px] mx-auto h-14 flex items-center justify-around px-margin">'
            f'<a {"aria-current=page " if tab == "cards" else ""}class="flex flex-col items-center justify-center min-w-[44px] min-h-[44px] px-space-md {on if tab == "cards" else off}" href="/"><span class="material-symbols-outlined text-[22px]">newspaper</span><span class="font-label-micro text-label-micro mt-0.5">내 종목</span></a>'
            f'<a {"aria-current=page " if tab == "calendar" else ""}class="flex flex-col items-center justify-center min-w-[44px] min-h-[44px] px-space-md {on if tab == "calendar" else off}" href="/calendar"><span class="material-symbols-outlined text-[22px]">calendar_today</span><span class="font-label-micro text-label-micro mt-0.5">캘린더</span></a>'
            f'<a {"aria-current=page " if tab == "learn" else ""}class="flex flex-col items-center justify-center min-w-[44px] min-h-[44px] px-space-md {on if tab == "learn" else off}" href="/learn"><span class="material-symbols-outlined text-[22px]">menu_book</span><span class="font-label-micro text-label-micro mt-0.5">읽기 팁</span></a>'
            "</div></nav>")  # fmt: skip


def safe_url(u: str) -> str:
    return u if u.startswith(("https://", "http://")) else "#"


# --- 우리가 쓴 고정 풀이 (공시 내용을 지어내지 않는다 — 낱말·공시 종류의 뜻만) ---

GLOSSARY = {
    "영업이익": "영업이익이란 물건을 팔아 들어온 돈에서 만드는 비용·월급 같은 본업 비용을 빼고 남은 돈을 말해요.",
    "부채비율": "부채비율이란 회사 빚을 회사 자기 돈으로 나눈 값이에요. 낮을수록 빚 부담이 적어요.",
    "ROE": "ROE란 주주 돈 100원으로 1년에 몇 원을 벌었는지예요.",
    "자사주": "자사주 매입이란 회사가 자기 회사 주식을 사들이는 거예요. 시중에 도는 주식 수가 줄어요.",
    "유상증자": "유상증자란 회사가 새 주식을 팔아 돈을 모으는 거예요. 주식 수가 늘어 기존 주주의 몫이 묽어질 수 있어요.",
    "전환사채": "전환사채란 나중에 주식으로 바꿀 수 있는 빚이에요. 주식으로 바뀌면 주식 수가 늘어요.",
}
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
CITE = ("inline-flex items-center align-middle mx-0.5 px-1.5 py-0.5 rounded text-citation-ref font-citation-ref "
        "bg-primary-fixed text-on-primary-fixed hover:bg-primary-fixed-dim transition-colors")  # fmt: skip


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
                      "D": "금융감독원 전자공시시스템 (DART) · 공시"}.get(k, f"{f.get('slots', {}).get('매체', '')} 기사"),
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


def glossary(text: str) -> str:
    hit = next((v for k, v in GLOSSARY.items() if k in text), None)
    if not hit:
        return ""
    return ('<div class="py-1 text-on-surface flex items-start gap-space-xs text-on-surface-variant"><span class="text-[14px] select-none text-outline">💡</span>'
            f'<div class="flex-1 font-body-compact text-body-compact leading-relaxed"><span class="font-medium text-on-surface">쉽게 풀어보기:</span> {e(hit)}</div></div>')  # fmt: skip


def chapter(title: str, body: str, extra: str = "") -> str:
    return ('<article class="mb-space-xl flex flex-col gap-space-sm"><div class="flex items-center gap-2"><span class="w-2 h-2 rounded-full bg-primary"></span>'
            f'<h3 class="font-headline-md text-headline-md text-on-surface">{e(title)}</h3></div>'
            f'<div class="font-body-reading text-body-reading text-on-surface leading-loose">{body}</div>{extra}</article>')  # fmt: skip


def render_note(name: str, ticker: str, week: str, body: dict, writer: str, facts: list[dict] | None = None,
                industry: str | None = None, initial: str = "", survey: str = "") -> str:
    facts = facts or []
    every = body["summary"] + [x for sec in body["sections"] for x in sec["sentences"]] + body.get("good", []) + body.get("concern", [])
    minutes = max(1, round(sum(len(x["text"]) for x in every) / 500))  # 한글 분당 500자쯤
    used = " ".join(x["text"] for x in every)
    tags = [t for t in (industry_label(industry), "코스피 대형주") if t]  # 유니버스 = 코스피 시총 상위 100
    tag_html = '<span class="w-1 h-1 rounded-full bg-outline-variant"></span>'.join(f'<span class="">{e(t)}</span>' for t in tags)
    head = ('<header class="fixed top-0 w-full z-50 bg-surface/90 backdrop-blur-xl pt-safe"><div class="h-14 max-w-[480px] mx-auto px-margin flex items-center justify-between"><div class="flex items-center gap-space-sm"><button class="w-11 h-11 flex items-center justify-center text-on-surface hover:text-primary transition-colors -ml-space-xs" onclick="location.href=\'/\'"><span class="material-symbols-outlined text-[22px]">arrow_back</span></button><h1 class="font-headline-sm text-headline-sm text-on-surface tracking-tight truncate max-w-[200px]">Note</h1></div><div class="flex items-center gap-space-sm">'
            + avatar(initial) + '</div></div></header>')  # fmt: skip
    parts = [
        '<div class="flex items-center justify-between py-space-sm mb-space-xs"><button class="flex items-center gap-space-xs text-on-surface-variant hover:text-primary transition-colors py-1 group" onclick="location.href=\'/\'" type="button"><span class="material-symbols-outlined text-[18px] transition-transform group-hover:-translate-x-0.5">arrow_back</span>'
        f'<span class="font-label-regular text-label-regular text-on-surface-variant font-medium">내 종목 · {e(week)} 주 노트</span></button>'
        '<div class="flex items-center gap-1.5 px-space-sm py-0.5 rounded-full bg-surface-container-high text-on-surface-variant"><span class="material-symbols-outlined text-[14px]">schedule</span>'
        f'<span class="font-label-micro text-label-micro">{minutes}분이면 다 읽어요</span></div></div>',
        '<header class="mb-space-lg"><div class="flex items-baseline gap-2 mb-1">'
        f'<h2 class="font-display-editorial text-display-editorial text-on-surface font-semibold tracking-tight">{e(name)}</h2>'
        f'<span class="font-label-micro text-label-micro text-outline tracking-wider uppercase font-mono">{e(ticker)}</span></div>'
        f'<div class="flex items-center gap-space-sm text-on-surface-variant font-label-regular text-label-regular">{tag_html}'
        '<span class="w-1 h-1 rounded-full bg-outline-variant"></span><span class="text-secondary font-medium">연간 결산 분석</span></div></header>',
        # 시안의 사진 자리 — 쓸 권리가 있는 사진이 없어 회색 빈 칸
        '<div class="relative w-full h-44 rounded-xl overflow-hidden mb-space-lg shadow-sm bg-surface-container">'
        '<div class="absolute inset-0 bg-gradient-to-t from-on-background/80 via-on-background/25 to-transparent flex items-end p-space-md">'
        f'<p class="font-citation-ref text-citation-ref text-surface-container-lowest/90 font-normal">{e(name)} · 이미지 준비 중</p></div></div>',
        f'<aside class="mb-space-lg py-space-md px-space-lg bg-surface-container-low rounded-xl border-l-2 border-primary relative"><p class="font-body-reading-strong text-body-reading-strong text-primary leading-relaxed">"{e(body["headline"])}"</p></aside>',
    ]  # fmt: skip
    if body.get("summary"):
        parts.append('<section class="mb-space-xl pl-space-md py-1 border-l-2 border-primary/60"><div class="flex items-center gap-1.5 mb-1"><span class="material-symbols-outlined text-primary text-[18px]">auto_stories</span><span class="font-label-micro text-label-micro uppercase tracking-wider text-primary font-bold">한 장 요약</span></div>'
                     f'<p class="font-body-reading text-body-reading text-on-surface leading-relaxed">{" ".join(sentence(s) for s in body["summary"])}</p></section>')  # fmt: skip
    nd = sum(f["id"][0] == "D" for f in facts)
    good_d, bad_d = sum(f["id"][0] == "D" and f["tone"] == 1 for f in facts), sum(f["id"][0] == "D" and f["tone"] == -1 for f in facts)
    for sec in body["sections"]:
        text = " ".join(sentence(s) for s in sec["sentences"])
        extra = ""
        if sec["title"].startswith("회사 사정"):
            extra = metrics(facts) + glossary(used)
        elif sec["title"].startswith("요즘 무슨"):
            right = (f"반가운 쪽 {good_d}" + (f" · 걸리는 쪽 {bad_d}" if bad_d else "")) if good_d or bad_d else "분류 완료"
            extra = ('<div class="py-space-sm flex items-center justify-between border-t border-outline-variant/30 mt-space-xs"><div class="flex items-center gap-space-sm"><span class="material-symbols-outlined text-secondary text-[18px]">assignment_turned_in</span><div class="flex items-center gap-2">'
                     f'<span class="font-label-regular text-label-regular text-on-surface font-medium">최근 주요 공시 {nd}건 집계</span><span class="font-label-micro text-label-micro text-on-surface-variant">· DART 기준 자동 분류</span></div></div>'
                     f'<span class="font-label-micro text-label-micro text-secondary font-semibold">{e(right)}</span></div>')  # fmt: skip
        elif sec["title"].startswith("요즘 기사") and body.get("keywords"):
            extra = ('<div class="pt-space-sm pb-1 flex flex-col gap-1.5 border-t border-outline-variant/30 mt-space-xs"><div class="font-label-micro text-label-micro text-outline font-semibold uppercase">언론 키워드 흐름</div><div class="flex flex-wrap gap-2">'
                     + "".join(f'<span class="py-0.5 text-on-surface-variant text-label-micro font-label-micro">{e(k)}</span>' for k in body["keywords"])
                     + "</div></div>")  # fmt: skip
        if sec["title"].startswith("요즘 기사"):
            extra += '<p class="font-label-micro text-label-micro text-tertiary">⚠️ 개발용 — 기사 제목은 개인용으로만 모은 것이라 남에게 보여주면 안 돼요.</p>'
        parts.append(chapter(sec["title"], text, extra))
    if "good" in body:
        def side(label, title, items, bar, chip, ink):
            return (f'<div class="pl-space-md py-1 border-l-2 {bar} flex flex-col gap-1"><div class="flex items-center gap-1.5">'
                    f'<span class="px-2 py-0.5 rounded text-label-micro font-label-micro font-semibold {chip}">{label}</span>'
                    f'<span class="font-label-regular text-label-regular {ink} font-semibold">{e(title)}</span></div>'
                    f'<p class="font-body-reading text-body-reading text-on-surface leading-relaxed">{" ".join(sentence(s) for s in items)}</p></div>')  # fmt: skip
        parts.append('<section class="mb-space-xl flex flex-col gap-space-md"><div class="flex items-center gap-2"><span class="w-2 h-2 rounded-full bg-primary"></span><h3 class="font-headline-md text-headline-md text-on-surface">긍정 요인과 부정 요인</h3></div>'
                     + side("긍정", body.get("good_title", ""), body["good"], "border-secondary/60", "bg-secondary-container text-on-secondary-container", "text-secondary")
                     + side("부정", body.get("concern_title", ""), body["concern"], "border-tertiary/60", "bg-tertiary-fixed text-on-tertiary-fixed-variant", "text-tertiary")
                     + '<span class="font-label-micro text-label-micro text-outline leading-normal pt-1">긍정·부정 요인은 코드가 정한 기준으로 분류했어요 — 매출·영업이익 증감, 부채비율, ROE, 공시 종류.</span></section>')  # fmt: skip
    how = ("기사·공시·재무에서 코드가 뽑은 사실을 바탕으로 AI가 문장을 다듬었어요. 숫자는 코드가 원문과 대조했어요."
           if writer.startswith("llm") else "기사·공시·재무에서 코드가 뽑은 사실을 그대로 옮겼어요.")  # fmt: skip
    parts.append(survey)
    parts.append('<footer class="pt-space-lg pb-space-lg mt-space-sm border-t border-outline-variant/40 flex flex-col gap-space-sm"><div class="flex items-center gap-1.5 text-on-surface font-headline-sm text-headline-sm font-semibold"><span class="material-symbols-outlined text-primary text-[20px]">verified</span><span class="">작성 기준 및 검증 안내</span></div>'
                 f'<p class="font-body-compact text-body-compact text-on-surface-variant leading-relaxed">{how} <span class="font-semibold text-primary">[F1]</span>, <span class="font-semibold text-primary">[D1]</span> 등 번호를 누르면 금융감독원 전자공시(DART)나 기사 원문이 열려요.</p>'
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

    def initial(self, uid: int) -> str:
        row = self.con.execute("select email from users where id = ?", (uid,)).fetchone()
        return (row[0][:1] if row else "") or "?"

    def simple(self, title: str, msg: str) -> str:
        return page(title, "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen",
                    f'<main class="w-full max-w-[480px] mx-auto px-margin pt-14"><p class="font-body-reading text-body-reading">{msg}</p></main>')  # fmt: skip

    def route(self, method, path, form, query, uid):
        if path == "/login" and method == "POST":
            return self.login(form.get("email", "").strip().lower())
        if path == "/auth":
            email = check_login(query.get("t", ""), self.secret, self.clock())
            if not email:
                return "200 OK", [], self.simple("로그인", "링크가 만료됐거나 잘못됐어요. <a class='text-primary underline' href='/'>다시 받기</a>")
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
            return "200 OK", [], self.cards(uid, query.get("msg"), query.get("sort"))
        if path.startswith("/n/"):
            ticker = path[3:]
            self.log(uid, "note", ticker)
            return self.note(uid, ticker, query.get("thanks") == "1")
        if path == "/feedback" and method == "POST":
            return self.feedback(uid, form)
        if path == "/learn" or path.startswith("/learn/"):
            slug = path[7:]
            self.log(uid, "learn", slug or None)
            return self.learn(uid, slug)
        if path == "/calendar":
            self.log(uid, "calendar")
            return "200 OK", [], self.calendar(uid, query.get("m"))
        return "404 Not Found", [], self.simple("없음", "없는 화면이에요. <a class='text-primary underline' href='/'>처음으로</a>")

    # ---- 로그인 (시안 _2) ----

    def login_page(self, sent: str | None = None) -> str:
        box = "" if not sent else (
            '<div class="flex flex-col bg-secondary-container/40 rounded-lg p-4 mt-4 transition-all" id="success-box"><div class="flex items-start gap-3"><div class="flex-shrink-0 w-8 h-8 rounded-full bg-secondary-container flex items-center justify-center mt-0.5"><span class="material-symbols-outlined text-on-secondary-container text-lg" style="font-variation-settings: \'FILL\' 1;">mark_email_read</span></div><div class="flex flex-col flex-1 min-w-0"><div class="flex items-center gap-1.5 mb-1"><span class="font-label-micro text-label-micro bg-primary text-on-primary px-1.5 py-0.5 rounded">발송 완료</span>'
            f'<span class="font-body-reading-strong text-body-compact text-on-surface truncate" id="target-email-preview">{e(sent)}</span></div>'
            '<p class="font-body-compact text-body-compact text-on-secondary-container">위 주소로 안전한 접속 링크를 전송했습니다. 15분 이내에 메일함 속 링크를 눌러 주세요.</p><div class="flex flex-col gap-1 mt-2.5 pt-2.5 border-t border-outline-variant/30"><p class="font-label-micro text-label-micro text-outline">메일이 도착하지 않았나요? 스팸함을 확인하시거나 잠시 후 재전송해 보세요.</p>'
            f'<form method="post" action="/login"><input type="hidden" name="email" value="{e(sent)}"><button class="self-start font-label-regular text-label-regular text-primary font-semibold underline underline-offset-2 hover:opacity-80 transition-opacity mt-1" id="resend-btn" type="submit">링크 다시 보내기</button></form></div></div></div></div>')  # fmt: skip
        inner = ('<main class="flex flex-col relative w-full max-w-[480px] mx-auto bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-12">'
                 '<div class="flex flex-col items-center text-center mt-6 mb-8"><div class="relative flex items-center justify-center w-20 h-20 rounded-full bg-surface-container-low shadow-sm mb-5"><svg class="w-9 h-9 text-primary" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.75" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" x2="8" y1="13" y2="13"></line><line x1="16" x2="8" y1="17" y2="17"></line><line x1="10" x2="8" y1="9" y2="9"></line></svg><div class="absolute -bottom-1 -right-1 flex items-center justify-center w-6 h-6 rounded-full bg-secondary-container shadow-xs"><span class="material-symbols-outlined text-on-secondary-container text-xs" style="font-variation-settings: \'FILL\' 1;">auto_stories</span></div></div>'
                 '<span class="font-display-editorial text-display-editorial text-primary tracking-tight">한장</span><span class="font-label-micro text-label-micro text-outline uppercase tracking-widest mt-1">Hanjang · Daily Financial Letter</span>'
                 '<h1 class="font-headline-sm text-headline-sm text-on-surface mt-4 max-w-[280px] leading-relaxed">내 주식이 지금 어떤 상황인지,<br>쉬운 글 한 장으로.</h1>'
                 '<p class="font-body-compact text-body-compact text-on-surface-variant mt-2 max-w-[300px]">숫자 뒤에 숨겨진 회사의 진짜 이야기와 사업 흐름을 담백하게 정리해 드립니다.</p></div>'
                 '<div class="w-full rounded-xl flex flex-col relative overflow-hidden px-1.5"><form class="flex flex-col w-full relative z-10" id="magic-link-form" method="post" action="/login">'
                 '<div class="flex items-center justify-between mb-2"><label class="font-label-regular text-label-regular text-on-surface flex items-center gap-1.5" for="email-input"><span class="material-symbols-outlined text-primary text-base">mail</span>이메일 주소</label><span class="font-label-micro text-label-micro text-outline">비밀번호 없는 간편 시작</span></div>'
                 '<div class="relative flex items-center w-full"><input class="w-full font-body-reading text-body-reading bg-surface-container-low text-on-surface placeholder:text-outline rounded-lg px-4 py-3.5 focus:outline-none focus:bg-surface-container-lowest transition-all" id="email-input" name="email" placeholder="name@example.com" required="" type="email">'
                 '<button aria-label="이메일 지우기" class="hidden absolute right-3 text-outline hover:text-on-surface p-1 transition-colors" id="clear-btn" onclick="clearInput()" type="button"><span class="material-symbols-outlined text-lg">cancel</span></button></div>'
                 f'<button class="w-full py-3.5 bg-primary text-on-primary font-body-reading-strong text-body-reading-strong rounded-lg shadow-sm hover:opacity-95 active:scale-[0.99] transition-all mt-3 flex items-center justify-center gap-2" id="submit-btn" type="submit"><span class="">{"링크 다시 받기" if sent else "로그인 링크 받기"}</span><span class="material-symbols-outlined text-base">{"refresh" if sent else "arrow_forward"}</span></button>'
                 '<p class="font-label-regular text-label-regular text-outline text-center mt-3 leading-relaxed">복잡한 비밀번호 설정 없이, 메일로 온 링크를 누르면 바로 연결돼요. 개인정보는 오직 이메일만 소중히 보관합니다.</p></form>'
                 + box + '</div>'
                 '<div class="mt-8 flex flex-col gap-4"><div class="grid grid-cols-2 gap-4 pt-2 border-t border-outline-variant/30"><div class="flex flex-col gap-1"><div class="flex items-center gap-1.5 text-primary"><span class="material-symbols-outlined text-base">description</span><span class="font-body-reading-strong text-label-regular">공시 기반 해설</span></div><p class="font-label-micro text-label-micro text-on-surface-variant leading-relaxed">어려운 DART 공시와 분기 보고서를 일상 언어로 풀어냅니다.</p></div><div class="flex flex-col gap-1"><div class="flex items-center gap-1.5 text-secondary"><span class="material-symbols-outlined text-base">spa</span><span class="font-body-reading-strong text-label-regular">소음 없는 담백함</span></div><p class="font-label-micro text-label-micro text-on-surface-variant leading-relaxed">빨강·파랑 시세창 대신 기업 본질을 천천히 읽는 시간.</p></div></div>'
                 '<div class="text-center px-4 mt-4"><div class="inline-flex items-center justify-center gap-2 mb-2"><span class="w-4 h-[1px] bg-outline-variant"></span><span class="font-citation-ref text-citation-ref text-outline">한장의 약속</span><span class="w-4 h-[1px] bg-outline-variant"></span></div><p class="font-label-regular text-label-regular text-outline leading-relaxed">이해를 위한 서비스예요. 수익률을 장담하거나 종목을 추천하지 않아요.</p></div></div></div>'
                 "<script>const emailInput=document.getElementById('email-input');const clearBtn=document.getElementById('clear-btn');"
                 "emailInput.addEventListener('input',(ev)=>{clearBtn.classList.toggle('hidden',ev.target.value.length===0);});"
                 "function clearInput(){emailInput.value='';clearBtn.classList.add('hidden');emailInput.focus();}</script></main>")  # fmt: skip
        return page("로그인", "bg-surface font-body-reading text-on-surface pt-safe pb-safe flex flex-col min-h-screen", inner)

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

    # ---- 내 종목 (시안 _3) ----

    def cards(self, uid: int, msg: str | None, sort: str | None = None) -> str:
        order = "s.name" if sort == "name" else "h.added_at"
        rows = self.con.execute(
            "select s.ticker, s.name, n.week, n.body, n.facts from holdings h join stocks s using(ticker)"
            " left join notes n on n.ticker = s.ticker and n.week ="
            " (select max(week) from notes where ticker = s.ticker)"
            f" where h.user_id = ? order by {order}", (uid,)).fetchall()  # fmt: skip
        stocks = [{"t": t, "n": n, "l": industry_label(c) or ""}
                  for t, n, c in self.con.execute("select ticker, name, induty_code from stocks where active = 1 order by name")]  # fmt: skip
        out = []
        for t, name, week, body, facts in rows:
            head = json.loads(body)["headline"] if body else "이번 주 노트를 준비 중이에요."
            fs = json.loads(facts) if facts else []
            bad = [f for f in fs if f.get("tone") == -1]
            good_d = next((f for f in fs if f["id"][0] == "D" and f.get("tone") == 1), None)
            if bad:  # 걱정되는 사실이 있으면 그걸 먼저 — 시안의 「! … 분석 포함」
                what = FACT_SHORT.get(bad[0]["id"]) or bad[0].get("slots", {}).get("종류", "공시")
                status = ('<div class="flex items-center gap-1.5 text-tertiary font-label-micro text-label-micro font-medium"><span class="material-symbols-outlined text-[15px] text-tertiary">priority_high</span>'
                          f'<span class="">{e(what)} 걱정되는 점 분석 포함</span></div>')  # fmt: skip
            elif good_d:
                status = ('<div class="flex items-center gap-1.5 text-on-secondary-container font-label-micro text-label-micro font-medium"><span class="material-symbols-outlined text-[15px] text-primary">verified</span>'
                          f'<span class="">{e(good_d.get("slots", {}).get("종류", "공시"))} 공시 분석 완료</span></div>')  # fmt: skip
            else:
                nd, nn = sum(f["id"][0] == "D" for f in fs), sum(f["id"][0] == "N" for f in fs)
                status = ('<div class="flex items-center gap-1.5 text-on-secondary-container font-label-micro text-label-micro font-medium"><span class="material-symbols-outlined text-[15px]">summarize</span>'
                          f'<span class="">최근 공시 {nd}건 · 기사 {nn}건 요약됨</span></div>')  # fmt: skip
            out.append(f'<article class="py-4 relative transition-all group" data-stock-id="{e(t)}"><div class="flex items-start justify-between"><div class="flex items-center gap-2">'
                       f'<h2 class="font-headline-sm text-headline-sm text-on-surface font-semibold">{e(name)}</h2><span class="font-citation-ref text-citation-ref text-outline px-1.5 py-0.5 rounded bg-surface-container-low">{e(t)}</span><span class="font-label-micro text-label-micro text-outline-variant">{e(week or "")}</span></div>'
                       f'<form method="post" action="/remove"><input type="hidden" name="t" value="{e(t)}"><button aria-label="{e(name)} 삭제" class="w-6 h-6 rounded-full flex items-center justify-center text-outline hover:text-tertiary hover:bg-surface-container transition-colors" type="submit"><span class="material-symbols-outlined text-[16px]">close</span></button></form></div>'
                       f'<a href="/n/{e(t)}"><p class="font-body-reading text-body-reading text-on-surface mt-2 tracking-tight">{e(head)}</p></a>'
                       f'<div class="mt-3 flex items-center justify-between">{status}<a class="font-label-micro text-label-micro text-primary flex items-center gap-0.5 hover:underline font-semibold" href="/n/{e(t)}">노트 읽기<span class="material-symbols-outlined text-[14px]">arrow_forward</span></a></div></article>')  # fmt: skip
        note = (f'<p class="font-label-micro text-label-micro text-tertiary px-margin pt-2">{e(msg)}</p>' if msg else "")
        inner = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] mx-auto pt-14 pb-24 bg-surface min-h-screen"><div class="flex flex-col w-full">'
                 '<section class="sticky top-0 z-30 bg-surface/95 backdrop-blur-md px-margin py-3 border-b border-surface-container-high transition-all duration-200"><div class="relative w-full">'
                 '<form method="post" action="/add" class="h-11 w-full bg-surface-container-low/60 rounded-xl flex items-center px-3 border border-surface-container-high/60 focus-within:border-primary-container focus-within:bg-surface-container-lowest transition-all"><span class="material-symbols-outlined text-outline text-[20px] mr-2">search</span>'
                 '<input autocomplete="off" class="w-full bg-transparent text-on-surface font-body-compact text-body-compact placeholder:text-outline focus:outline-none" id="stock-search-input" name="q" placeholder="종목 이름 또는 코드로 담기" type="text">'
                 '<button class="shrink-0 ml-1.5 px-3 py-1 bg-primary text-on-primary rounded-lg font-label-micro text-label-micro font-semibold shadow-sm active:scale-95 transition-transform" id="btn-quick-add" type="submit">담기</button></form>'
                 '<div class="hidden absolute left-0 right-0 top-12 mt-1 bg-surface-container-lowest rounded-xl shadow-sm border border-surface-container-high/70 overflow-hidden z-40" id="search-flyout"><div class="p-1.5 flex flex-col gap-0.5" id="search-results"></div></div>'
                 "</div></section>" + note
                 + '<header class="px-margin pt-5 pb-2"><div class="flex items-baseline justify-between mb-1"><div class="flex items-center gap-2"><h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight">내 종목</h1>'
                 f'<span class="px-2 py-0.5 rounded-full bg-secondary-container text-on-secondary-container font-label-micro text-label-micro font-semibold" id="stock-count-badge">{len(rows)} / {MAX_STOCKS}개</span></div>'
                 f'<a class="font-label-micro text-label-micro text-outline hover:text-on-surface transition-colors flex items-center gap-0.5" href="/?sort={"added" if sort == "name" else "name"}"><span class="material-symbols-outlined text-[15px]">tune</span>정렬</a></div>'
                 '<p class="font-body-compact text-body-compact text-on-surface-variant flex items-center gap-1.5"><span class="material-symbols-outlined text-[15px] text-primary">mark_email_unread</span>매주 월요일 아침, 이번 주의 한 장 노트가 도착해요.</p></header>'
                 f'<section class="px-margin flex flex-col divide-y divide-surface-container-high/80" id="stock-list">{"".join(out)}</section>'
                 '<section class="px-margin py-8 text-center flex flex-col items-center justify-center gap-2 border-t border-surface-container-high/60"><p class="font-body-compact text-body-compact text-outline max-w-[280px]">가진 종목이나 궁금한 종목을 담아 보세요.<br>매주 한 장씩 차분한 노트가 와요. (최대 20개)</p><button class="mt-1 px-3.5 py-1.5 text-primary rounded-full font-label-micro text-label-micro font-semibold border border-primary-container/40 hover:bg-surface-container-low active:scale-95 transition-all flex items-center gap-1" onclick="document.getElementById(\'stock-search-input\').focus()" type="button"><span class="material-symbols-outlined text-[15px]">add</span><span class="">새 종목 찾아보기</span></button></section>'
                 '<footer class="px-margin pt-4 pb-8 flex flex-col items-center justify-center gap-2"><div class="flex items-center gap-3 text-outline font-label-micro text-label-micro"><span class="">업데이트 주기: 매주 월 07:00</span><span class="">·</span><span class="">공시 데이터: DART 전자공시</span></div>'
                 '<button class="font-label-micro text-label-micro text-outline hover:text-on-surface transition-colors underline underline-offset-4 py-2" onclick="if(confirm(\'현재 계정에서 로그아웃할까요?\'))location.href=\'/logout\'" type="button">로그아웃</button></footer></div>'
                 # 자동완성 — 노트가 있는 종목(코스피 시총 상위)만. 업종은 DART 업종 코드에서
                 "<script>const STOCKS=" + json.dumps(stocks, ensure_ascii=False).replace("<", "\\u003c") + ";"
                 "const inp=document.getElementById('stock-search-input'),fly=document.getElementById('search-flyout'),res=document.getElementById('search-results');"
                 "function esc(s){return s.replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}"
                 "function draw(){const q=inp.value.trim();if(!q){fly.classList.add('hidden');return;}const hit=STOCKS.filter(s=>s.n.includes(q)||s.t.startsWith(q)).slice(0,6);"
                 "res.innerHTML='<div class=\"px-3 py-1.5 text-outline text-[11px] font-label-micro flex items-center justify-between\"><span class=\"\">검색 결과</span><span class=\"text-primary-container font-semibold\">'+hit.length+'건 일치</span></div>'+hit.map((s,i)=>"
                 "'<form method=\"post\" action=\"/add\" class=\"group flex items-center justify-between p-2.5 rounded-lg '+(i===0?'bg-surface-container-low ':'')+'cursor-pointer hover:bg-surface-container transition-colors\"><input type=\"hidden\" name=\"q\" value=\"'+s.t+'\"><div class=\"flex items-center gap-2 min-w-0\"><span class=\"w-7 h-7 rounded-full '+(i===0?'bg-primary-fixed text-primary':'bg-surface-container-high text-on-surface-variant')+' flex items-center justify-center font-body-reading-strong text-[12px]\">'+esc(s.n[0])+'</span><div class=\"flex flex-col min-w-0\"><div class=\"flex items-center gap-1.5\"><span class=\"font-headline-sm text-headline-sm text-on-surface\">'+esc(s.n)+'</span><span class=\"font-citation-ref text-citation-ref text-outline\">'+s.t+'</span></div><span class=\"font-label-micro text-label-micro text-on-surface-variant truncate\">'+esc(s.l)+'</span></div></div>'"
                 "+(i===0?'<button class=\"px-2.5 py-1 bg-primary-container text-on-primary font-label-micro text-label-micro rounded-lg shadow-sm hover:opacity-90 active:scale-95 transition-all\" type=\"submit\">+ 담기</button>':'<button class=\"px-2.5 py-1 bg-surface-container text-on-surface font-label-micro text-label-micro rounded-lg hover:bg-surface-container-high transition-colors\" type=\"submit\">담기</button>')+'</form>').join('');"
                 "fly.classList.toggle('hidden',hit.length===0);}"
                 "inp.addEventListener('input',draw);inp.addEventListener('focus',draw);"
                 "document.addEventListener('click',ev=>{if(!inp.contains(ev.target)&&!fly.contains(ev.target))fly.classList.add('hidden');});</script></main>"
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
                '<div class="flex justify-between">' + "".join(
                    f'<label class="flex flex-col items-center gap-1 font-label-micro text-label-micro text-on-surface-variant"><input type="radio" name="h" value="{i}" required>{i}</label>'
                    for i in range(1, 6)) + '</div><div class="flex justify-between font-label-micro text-label-micro text-outline"><span>별로예요</span><span>아주 좋아요</span></div>'
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
            "select s.name, n.week, n.body, n.writer, n.facts, s.induty_code from stocks s join notes n using(ticker)"
            " where s.ticker = ? order by n.week desc limit 1", (ticker,)).fetchone()  # fmt: skip
        if not row:
            return "404 Not Found", [], self.simple("없음", "이 종목은 아직 노트가 없어요. <a class='text-primary underline' href='/'>내 종목</a>")
        name, week, body, writer, facts, ind = row
        return "200 OK", [], render_note(name, ticker, week, json.loads(body), writer, json.loads(facts), ind,
                                         self.initial(uid), self.survey(uid, ticker, week, thanks))  # fmt: skip

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
        nav_btn = "flex items-center px-space-sm py-1 rounded-lg bg-surface-container hover:bg-surface-container-high transition-colors text-primary font-label-regular text-label-regular"
        cells = []
        for wk in weeks:
            for i, d in enumerate(wk):
                iso = d.isoformat()
                if d.month != m:
                    num = f'<span class="font-label-micro text-label-micro text-outline-variant">{d.day}</span>'
                elif d == today:
                    num = (f'<div class="flex items-center justify-between"><span class="w-5 h-5 flex items-center justify-center rounded-full bg-primary-container text-on-primary font-label-micro text-label-micro font-bold">{d.day}</span>'
                           '<span class="text-[8px] text-primary-container font-semibold">오늘</span></div>')  # fmt: skip
                elif i in (0, 6) or iso in hol:  # 주말·공휴일은 빨간 숫자 (사용자 요청 10/7)
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
        top_kind = max(kinds, key=kinds.get) if kinds else None
        tip_h, tip_b = TIPS.get(top_kind, TIP_DEFAULT)
        mix = " · ".join(f"{EVENT_SHORT.get(k, k)} {v}" for k, v in kinds.items()) or "큰 공시 없음"
        inner = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] mx-auto pt-14 pb-24 bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-6 gap-space-lg">'
                 '<header class="flex flex-col pt-space-xs gap-space-xs"><div class="flex items-center justify-between"><div class="flex items-baseline gap-space-xs">'
                 f'<h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight">{y}년 {m}월</h1><span class="font-label-micro text-label-micro text-on-surface-variant">공시 타임라인</span></div>'
                 f'<div class="flex items-center gap-space-xs"><a class="{nav_btn}" href="/calendar?m={prev}"><span class="material-symbols-outlined text-[16px] mr-0.5">chevron_left</span>이전</a>'
                 f'<a class="{nav_btn}" href="/calendar?m={nxt}">다음<span class="material-symbols-outlined text-[16px] ml-0.5">chevron_right</span></a></div></div>'
                 '<p class="font-body-compact text-body-compact text-on-surface-variant">관심 기업의 주요 의사결정과 공시 기록을 날짜별로 천천히 짚어드려요.</p></header>'
                 '<section class="py-space-sm px-1 flex items-center justify-between border-b border-surface-container-high"><div class="flex items-center gap-space-sm"><span class="material-symbols-outlined text-primary text-[20px]">calendar_clock</span><div class="flex items-baseline gap-space-xs">'
                 f'<span class="font-label-regular text-label-regular text-on-surface font-semibold">이번 달 주목할 공시 {len(mine)}건</span><span class="font-label-micro text-label-micro text-on-surface-variant">{e(mix)}</span></div></div>'
                 '</section>'
                 '<section class="flex flex-col gap-1 py-1"><div class="grid grid-cols-7 text-center font-label-micro text-label-micro font-semibold pb-1.5 border-b border-surface-container-high/60"><span class="text-tertiary">일</span><span class="text-on-surface-variant">월</span><span class="text-on-surface-variant">화</span><span class="text-on-surface-variant">수</span><span class="text-on-surface-variant">목</span><span class="text-on-surface-variant">금</span><span class="text-tertiary">토</span></div>'
                 f'<div class="grid grid-cols-7 gap-1 pt-1">{"".join(cells)}</div></section>'
                 '<section class="flex flex-col mt-2"><div class="flex items-center justify-between pb-2 border-b border-surface-container-highest"><div class="flex items-center gap-space-xs"><h2 class="font-headline-md text-headline-md text-on-surface">이 달의 일정</h2><span class="font-label-micro text-label-micro text-on-surface-variant bg-surface-container px-2 py-0.5 rounded-full">최신순</span></div>'
                 '<a class="font-label-regular text-label-regular text-primary flex items-center hover:opacity-80 transition-opacity" href="https://dart.fss.or.kr" target="_blank" rel="noopener">전체 공시 원문<span class="material-symbols-outlined text-[15px] ml-0.5">arrow_forward</span></a></div>'
                 f'<div class="flex flex-col">{"".join(items)}</div></section>'
                 # 시안의 사진 자리 — 쓸 권리가 있는 그림이 없어 회색 빈 칸. 팁 문장은 우리가 쓴 고정 문장
                 f'<a href="/learn/{learn.FOR_EVENT.get(top_kind, "disclosure")}" class="pt-4 pb-2 border-t border-surface-container-high flex items-center gap-space-md"><div class="w-16 h-16 rounded-lg flex-shrink-0 bg-surface-container flex items-center justify-center"><span class="material-symbols-outlined text-primary text-[28px]">menu_book</span></div><div class="flex flex-col gap-0.5 min-w-0"><span class="font-label-micro text-label-micro text-primary font-bold">주주를 위한 읽기 팁</span>'
                 f'<p class="font-body-compact text-body-compact text-on-surface truncate font-semibold">{e(tip_h)}</p><span class="font-label-micro text-label-micro text-on-surface-variant">{e(tip_b)}</span></div></a>'
                 '<footer class="mt-2 text-center flex flex-col items-center gap-1"><div class="w-8 h-0.5 bg-surface-container-high rounded-full mb-1"></div><p class="font-citation-ref text-citation-ref text-on-surface-variant leading-relaxed max-w-[340px]">지난 공시만 보여요. 앞으로의 일정(실적 발표일·배당일)은 준비 중이에요. 공휴일: 한국천문연구원.</p></footer>'
                 "</div></main>" + bottom_nav("calendar"))  # fmt: skip
        return page("캘린더", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)


    # ---- 읽기 팁 (시안에 없는 화면 — 같은 디자인 말투로) ----

    def learn(self, uid: int, slug: str):
        wrap = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] mx-auto pt-14 pb-24 bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-6">')
        end = ('<p class="font-label-micro text-label-micro text-outline text-center py-space-lg">설명을 위한 글이에요. 특정 종목이나 상품을 추천하지 않아요.</p></div></main>'
               + bottom_nav("learn"))
        a = learn.BY_SLUG.get(slug)
        if slug and not a:
            return "404 Not Found", [], self.simple("없음", "없는 글이에요. <a class='text-primary underline' href='/learn'>읽기 팁</a>")
        if a:
            more_label, more_url = a["more"]
            inner = (wrap + '<div class="flex items-center py-space-sm"><a class="flex items-center gap-space-xs text-on-surface-variant hover:text-primary transition-colors" href="/learn"><span class="material-symbols-outlined text-[18px]">arrow_back</span>'
                     f'<span class="font-label-regular text-label-regular font-medium">읽기 팁 · {e(a["cat"])}</span></a></div>'
                     f'<h1 class="font-display-editorial text-display-editorial text-on-surface font-semibold tracking-tight mb-space-sm">{e(a["title"])}</h1>'
                     f'<aside class="mb-space-lg py-space-md px-space-lg bg-surface-container-low rounded-xl border-l-2 border-primary"><p class="font-body-reading-strong text-body-reading-strong text-primary leading-relaxed">{e(a["lead"])}</p></aside>'
                     + "".join(f'<p class="font-body-reading text-body-reading text-on-surface leading-loose mb-space-md">{e(x)}</p>' for x in a["body"])
                     + '<section class="mt-space-sm mb-space-lg pl-space-md py-1 border-l-2 border-secondary/60 flex flex-col gap-1"><span class="font-label-micro text-label-micro uppercase tracking-wider text-secondary font-bold">기억할 것</span>'
                     + "".join(f'<p class="font-body-compact text-body-compact text-on-surface">· {e(x)}</p>' for x in a["points"])
                     + f'</section><a class="inline-flex items-center gap-1 font-label-regular text-label-regular text-primary font-semibold hover:underline" href="{e(more_url)}" target="_blank" rel="noopener">더 알아보기: {e(more_label)}<span class="material-symbols-outlined text-[14px]">open_in_new</span></a>'
                     + end)  # fmt: skip
            return "200 OK", [], page(a["title"], "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)
        groups = "".join(
            f'<section class="mt-space-lg"><h2 class="font-headline-sm text-headline-sm text-on-surface mb-1">{e(c)}</h2><div class="flex flex-col divide-y divide-surface-container-high/80">'
            + "".join(f'<a href="/learn/{e(x["slug"])}" class="py-3.5 flex items-start justify-between gap-space-sm"><div class="flex flex-col gap-0.5"><span class="font-body-reading-strong text-body-reading-strong text-on-surface">{e(x["title"])}</span>'
                      f'<span class="font-body-compact text-body-compact text-on-surface-variant">{e(x["lead"])}</span></div><span class="material-symbols-outlined text-outline text-[18px] mt-1">chevron_right</span></a>'
                      for x in learn.ARTICLES if x["cat"] == c) + "</div></section>" for c in learn.CATS)  # fmt: skip
        inner = (wrap + '<header class="pt-5"><h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight">읽기 팁</h1>'
                 '<p class="font-body-compact text-body-compact text-on-surface-variant mt-1">주식을 처음 시작할 때 알아 두면 좋은 기초를 쉬운 말로 풀었어요.</p></header>' + groups + end)  # fmt: skip
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
    db.connect().close()
    app = App(sqlite3.connect(db.PATH, check_same_thread=False), env()["SECRET"])
    lock = threading.Lock()

    def serial(environ, start_response):
        with lock:
            return app(environ, start_response)

    print("한장 — http://localhost:8000", file=sys.stderr)
    make_server("127.0.0.1", 8000, serial, server_class=Server).serve_forever()
