"""메일 보내기 — 표준 라이브러리 SMTP 하나. 어느 메일 서비스든 `.env` 의 SMTP_* 만 바꾸면 된다.
SMTP_HOST 가 비어 있으면 보내지 않고 서버 콘솔에 찍는다 (개발용)."""

import math
import re
import smtplib
import struct
import sys
import zlib
from datetime import date, timedelta
from email.message import EmailMessage
from functools import cache
from html import escape as e

from hanjang import notes
from hanjang.sources import env


def base_url() -> str:
    return env().get("BASE_URL", "http://localhost:8000").rstrip("/")


def send(to: str, subject: str, text: str, html: str = "") -> bool:
    """보냈으면 True, 콘솔에 찍기만 했으면 False."""
    e = env()
    if not e.get("SMTP_HOST"):
        print(f"[메일·개발용] {to} · {subject}\n{text}", file=sys.stderr, flush=True)
        return False
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = e["SMTP_FROM"], to, subject
    msg.set_content(text)
    if html:  # 글자만 보이는 메일 앱은 text 를, 나머지는 html 을 보여준다
        msg.add_alternative(html, subtype="html")
        part = msg.get_payload()[1]
        for color, dots in WAVES:  # 본문이 쓰는 물결 그림만 메일에 붙인다 (cid: 로 본문에서 부른다)
            if f"cid:{_cid(color, dots)}" in html:
                part.add_related(wave_png(color, dots), "image", "png", cid=f"<{_cid(color, dots)}>")
    with smtplib.SMTP(e["SMTP_HOST"], int(e.get("SMTP_PORT", "587")), timeout=30) as s:
        s.starttls()
        s.login(e["SMTP_USER"], e["SMTP_PASSWORD"])
        s.send_message(msg)
    return True


def login_mail(link: str, code: str) -> tuple[str, str]:
    """링크와 6자리 코드 둘 다 — 앱에서는 메일의 링크가 다른 브라우저로 열려 로그인이 안 이어질 수 있어, 그때는 코드를 앱 화면에 넣는다."""
    return (f"[한장] 로그인 코드 {code}",
            f"한장에 들어가는 두 가지 길이에요. 둘 다 15분 동안만 쓸 수 있어요.\n\n"
            f"① 아래 링크 누르기\n{link}\n\n② 한장 화면에 이 코드 넣기\n{code}\n\n"
            "직접 요청하지 않았다면 이 메일은 지우셔도 돼요. 코드를 남에게 알려 주지 마세요.")  # fmt: skip


# 화면과 같은 색 (docs/design.md 「Warm Editorial Finance」) — 메일 앱은 CSS 파일·클래스·웹 글꼴을 못 읽어
# 인라인 스타일과 기기 기본 글꼴 하나로만 쓴다 (글꼴을 섞으면 앱마다 다르게 바뀌어 더 어수선해진다)
INK, SUB, MUTE, LINE, BG, GREEN, MINT, PALE, RED = ("#1b1b1d", "#404945", "#717975", "#c0c8c4", "#f5f5f5",
                                                   "#154539", "#a0d1c0", "#e3f4ec", "#741f11")  # fmt: skip
TINT = {1: ("#aef1c9", "#095134"), -1: ("#ffdad3", "#802919"), 0: ("#f0f0f0", "#404945")}
FONT = "-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Malgun Gothic','맑은 고딕',sans-serif"
ICON = {"회사 사정": "🏢", "요즘 무슨": "📌", "임원·큰손": "👥"}


def _day(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.month}월 {d.day}일 ({'월화수목금토일'[d.weekday()]})"


def _chip(label: str, tone: int, size: int = 12) -> str:
    """흰 바탕 + 옅은 색 테두리 + 진한 글씨 — 쨍한 바탕에 같은 계열 글씨는 읽기 힘들다."""
    return (f'<span style="display:inline-block;padding:1px 7px;border-radius:4px;border:1px solid {TINT[tone][0]};'
            f'color:{TINT[tone][1]};font-size:{size}px;font-weight:700;line-height:1.5">{e(label)}</span>')  # fmt: skip


# 형광펜 칠할 곳 — 「46.8% 늘었을」 「3.1% 줄었어요」 같은 변화 구절. 코드가 고르고, 절마다 처음 하나만 (한곳에 몰지 않게)
KEY = re.compile(r"-?[\d,]+(?:\.\d+)?%\s?(?:늘|줄|올|내|떨어|오르)[가-힣]*")


def _sentence(s: dict, urls: dict[str, str], mark: bool = False) -> str:
    """문장 + 원문 번호 링크 (불변식 2). mark = 문장 안 첫 변화 구절에만 형광펜 (제목·굵은 글씨엔 칠하지 않는다)."""
    t = e(s["text"])
    if mark:
        t = KEY.sub(lambda m: f'<span style="background:{PALE};padding:1px 2px">{m.group()}</span>', t, count=1)
    return t + "".join(f'<a href="{e(urls[r])}" style="color:{MUTE};font-size:11px;text-decoration:none;vertical-align:super">[{e(r)}]</a>'
                       for r in s["refs"] if r in urls)  # fmt: skip


def _paras(items: list[dict], urls: dict[str, str], mark: bool = False) -> str:
    """두 문장씩 문단으로 — 글이 빽빽하게 붙지 않게. mark = 이 절에서 변화 구절이 처음 나오는 문장에만 형광펜."""
    hit = next((i for i, s in enumerate(items) if KEY.search(s["text"])), None) if mark else None
    out = ""
    for i in range(0, len(items), 2):
        body = " ".join(_sentence(s, urls, i + k == hit) for k, s in enumerate(items[i:i + 2]))
        out += f'<p style="margin:0 0 14px;font-size:16px;line-height:1.85;color:{INK}">{body}</p>'
    return out


def _label(kicker: str, title: str, sub: str = "") -> str:
    """구역 머리 — 작은 초록 글씨 + 큰 제목, 왼쪽 정렬."""
    return ((f'<div style="font-size:13px;font-weight:800;letter-spacing:1px;color:{GREEN}">{e(kicker)}</div>' if kicker else "")
            + f'<div style="margin-top:2px;font-size:26px;font-weight:900;letter-spacing:-0.5px;color:{INK}">{title}</div>'
            + (f'<div style="margin-top:4px;font-size:13px;color:{SUB}">{sub}</div>' if sub else ""))  # fmt: skip


WAVES = ((GREEN, False), (GREEN, True), (MINT, False))  # 맨 위 실선·점선 물결 · 구역 사이 물결


def _cid(color: str, dots: bool = False) -> str:
    return f"wave-{color.strip('#')}{'-dots' if dots else ''}@hanjang"


@cache
def wave_png(color: str, dots: bool = False, w: int = 1200, h: int = 24, amp: float = 4.5, period: float = 200, width: float = 5) -> bytes:
    """잔잔한 물결 줄 PNG — 굵기가 일정한 사인 곡선 (메일은 SVG 를 막아서 그림으로). 표준 라이브러리만 쓴다.
    2배 크기로 그려 메일에선 600×12 로 보인다. 점마다 곡선까지의 거리로 투명도를 매겨 가장자리를 부드럽게.
    dots = 곡선을 따라 찍은 둥근 점 (머리의 점선 줄)."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    k, gap = 2 * math.pi / period, 16
    curve = lambda x: h / 2 + amp * math.sin(k * x)  # noqa: E731
    rows = []
    for y in range(h):
        row = bytearray([0])  # 줄마다 필터 0
        for x in range(w):
            if dots:  # 가장 가까운 점의 가운데까지 거리
                cx = (x // gap) * gap + gap / 2
                d = math.hypot(x + 0.5 - cx, y + 0.5 - curve(cx)) - width / 2 * 0.2
            else:
                d = abs(y + 0.5 - curve(x)) / math.hypot(1, amp * k * math.cos(k * x))
            row += bytes((r, g, b, round(255 * min(1, max(0, width / 2 - d + 0.5)))))
        rows.append(bytes(row))

    def chunk(t: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + t + data + struct.pack(">I", zlib.crc32(t + data))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))  # fmt: skip


def _wave(color: str = MINT, dots: bool = False, pad: str = "12px 28px") -> str:
    """구역을 나누는 물결 줄 — 메일에 붙인 그림(cid). 폭은 화면에 맞추고 높이는 고정이라 굵기가 거의 그대로다."""
    return (f'<tr><td style="padding:{pad}"><img src="cid:{_cid(color, dots)}" alt="" width="544" height="11" '
            'style="display:block;width:100%;max-width:544px;height:11px;border:0"></td></tr>')


def _bars(fin: list[tuple]) -> str:
    """최근 몇 해 매출(옅은)·영업이익(진한) 막대 — 노트 화면의 그림과 같은 숫자, 표 칸 높이로 그린다(SVG 는 메일에서 막힌다)."""
    fin = [r for r in fin if r[1] is not None or r[2] is not None]
    if len(fin) < 2:
        return ""
    hi = max(abs(v) for _, a, b in fin for v in (a, b) if v is not None) or 1
    H = 84

    def bar(v, color):
        if v is None:
            return ""
        h = max(round(abs(v) / hi * H), 2)
        return f'<span style="display:inline-block;width:14px;height:{h}px;margin:0 1px;border-radius:2px 2px 0 0;background:{RED if v < 0 else color};vertical-align:bottom"></span>'

    cols = "".join(f'<td align="center" valign="bottom" style="padding:0 2px"><div style="font-size:10px;color:{SUB};padding-bottom:3px">{e(notes.won(a if a is not None else b))}</div>'
                   f'{bar(a, MINT)}{bar(b, GREEN)}<div style="border-top:1px solid {LINE};font-size:11px;color:{MUTE};padding-top:3px">{y}</div></td>'
                   for y, a, b in fin)  # fmt: skip
    rev = any(a is not None for _, a, _ in fin)
    key = ((f'<span style="display:inline-block;width:9px;height:9px;background:{MINT};border-radius:2px"></span> 매출 &nbsp;' if rev else "")
           + f'<span style="display:inline-block;width:9px;height:9px;background:{GREEN};border-radius:2px"></span> 영업이익')  # fmt: skip
    return (f'<div style="margin:22px 0 6px">'
            f'<div style="font-size:13px;font-weight:700;color:{INK};padding-bottom:10px">최근 {len(fin)}년 {"매출·" if rev else ""}영업이익'
            f'<span style="float:right;font-weight:400;font-size:11px;color:{SUB}">{key}</span></div>'
            f'<table width="100%" cellpadding="0" cellspacing="0" style="table-layout:fixed"><tr>{cols}</tr></table>'
            f'<div style="text-align:right;font-size:10px;color:{MUTE};padding-top:6px">자료: DART 사업보고서</div></div>')  # fmt: skip


def _week(start: date, events, holidays) -> str:
    """보내는 날부터 7일 한 줄 — 칸마다 휴장일과 내 종목 일정 칩. 칩을 누르면 DART 원문."""
    hol = dict(holidays)
    days = [start + timedelta(days=i) for i in range(7)]
    head = "".join(f'<td align="center" style="padding:8px 0 4px;font-size:12px;font-weight:700;color:{RED if d.weekday() >= 5 else SUB}">{"월화수목금토일"[d.weekday()]}</td>'
                   for d in days)  # fmt: skip
    cells = []
    for d in days:
        iso = d.isoformat()
        cell = f'<div style="font-size:14px;font-weight:700;color:{RED if d.weekday() >= 5 or iso in hol else INK}">{d.day}</div>'
        if iso in hol:
            cell += f'<div style="font-size:10px;color:{RED};line-height:1.3">{e(hol[iso])}</div>'
        for _, name, kind, _, u, dr in (x for x in events if x[0] == iso):
            line, _ = TINT[dr or 0]
            cell += (f'<a href="{e(u)}" style="display:block;margin-top:4px;padding:3px 0;border-radius:4px;background:#ffffff;border:1px solid {line};color:{INK};'
                     f'font-size:9px;font-weight:700;line-height:1.3;letter-spacing:-0.3px;text-decoration:none;word-break:keep-all;overflow:hidden">{e(name)}<br>{e(kind)}</a>')  # fmt: skip
        cells.append(f'<td valign="top" align="center" width="14%" style="padding:6px 2px 10px;border-top:1px solid {LINE}">{cell}</td>')
    return (f'<tr><td style="padding:0 20px"><table width="100%" cellpadding="0" cellspacing="0" style="table-layout:fixed">'
            f"<tr>{head}</tr><tr>{''.join(cells)}</tr></table></td></tr>")  # fmt: skip


def morning_mail(m: dict, body: str) -> tuple[str, str, str]:
    """아침 소식 메일 — 화면의 「아침 한 장」(morning.build)과 같은 내용을 한 통으로. 화~토 하루 한 통.
    m = morning.build 의 결과, body = morning.text(m). 메일 앱은 CSS 를 못 읽어 인라인 스타일만."""
    url = base_url()
    who = "·".join(x["name"] for x in m["news"][:3]) + (" 등" if len(m["news"]) > 3 or m.get("more") else "")
    soon = next((x["label"] for x in m["week"] if x.get("url")), "")
    moves = m.get("moves", [])
    subject = (f"[한장] 오늘 내 종목 소식 — {who}" if m["news"] else f"[한장] 내 종목 큰손 움직임 — {moves[0].rstrip('.')}" if moves
               else f"[한장] 곧 있는 내 종목 일정 — {soon}" if soon else f"[한장] {m['title']} — 새 공시 없는 조용한 아침이에요")
    foot = "화~토 아침마다 보내요. 그만 받으려면 한장 프로필 → 설정에서 「안내 메일」을 끄면 돼요."
    news = "".join(f'<p style="margin:0 0 14px;font-size:15px;line-height:1.7;color:{INK}">'
                   f'<a href="{e(x["url"])}" style="color:{RED if x.get("warn") else GREEN};font-weight:700;text-decoration:none">{"[꼭 확인] " if x.get("warn") else ""}{e(x["name"])}</a> '
                   f'<span style="color:{SUB}">{e(x["body"])}</span></p>' for x in m["news"])  # fmt: skip
    week = "".join(f'<tr><td style="padding:5px 12px 5px 0;font-size:13px;color:{MUTE};white-space:nowrap">{e(_day(x["date"]))}</td>'
                   f'<td style="padding:5px 0;font-size:14px;color:{INK}">{e(x["label"])}</td></tr>' for x in m["week"][:6])  # fmt: skip
    head, tip, _ = m["tip"]
    html = (f'<div style="font-family:{FONT};max-width:560px;margin:0 auto;padding:28px 22px;background:#fff">'
            f'<p style="margin:0 0 4px;font-size:13px;color:{MUTE}">{e(m["title"])}</p>'
            f'<h1 style="margin:0 0 18px;font-size:21px;line-height:1.4;color:{GREEN}">오늘 내 종목 소식</h1>'
            + (news or f'<p style="margin:0 0 14px;font-size:15px;color:{SUB}">새로 나온 내 종목 공시는 없어요.</p>')
            + "".join(f'<p style="margin:0 0 8px;font-size:14px;line-height:1.7;color:{SUB}">{e(x)}</p>' for x in moves)
            + (f'<h2 style="margin:22px 0 6px;font-size:15px;color:{INK}">시장 · 같은 업종</h2>'
               + "".join(f'<p style="margin:0 0 8px;font-size:14px;line-height:1.7;color:{SUB}">{x}</p>' for x in
                         ([e(m["market"])] if m.get("market") else [])
                         + [f'#{e(p["label"])} <a href="{e(p["url"])}" style="color:{GREEN};font-weight:700;text-decoration:none">{e(p["name"])}</a> {e(p["body"])}' for p in m.get("peers", [])])
               if m.get("market") or m.get("peers") else "")
            + (f'<h2 style="margin:22px 0 6px;font-size:15px;color:{INK}">이번 주</h2><table style="border-collapse:collapse">{week}</table>' if week else "")
            + f'<h2 style="margin:22px 0 6px;font-size:15px;color:{INK}">알아 두면 좋아요 · {e(head)}</h2>'
            f'<p style="margin:0 0 20px;font-size:14px;line-height:1.7;color:{SUB}">{e(tip)}</p>'
            f'<p style="margin:0 0 22px"><a href="{e(url)}" style="display:inline-block;padding:11px 18px;border-radius:999px;background:{GREEN};color:#fff;font-size:14px;font-weight:700;text-decoration:none">한장에서 보기</a></p>'
            f'<p style="margin:0;padding-top:14px;border-top:1px solid {LINE};font-size:12px;line-height:1.6;color:{MUTE}">사실만 모았어요. 사고팔라는 뜻이 아니에요.<br>{foot}</p></div>')  # fmt: skip
    return subject, f"{body}\n\n한장에서 보기: {url}\n\n{foot}", html


def weekly_mail(week: str, stocks: list[dict], events=(), holidays=()) -> tuple[str, str, str]:
    """한 사람에게 한 통 — 앞으로 7일 캘린더 + 담은 종목 노트 전문. (제목, 글자 본문, HTML 본문).
    stocks = [{ticker, name, body, facts, fin?}] · fin = [(연도, 매출, 영업이익)]
    · events = [(날짜, 종목, 종류, 쉬운 말, 원문, 방향)] · holidays = [(날짜, 이름)] — 둘 다 보내는 날부터 7일."""
    names = [s["name"] for s in stocks]
    head = ", ".join(names[:3]) + (f" 외 {len(names) - 3}곳" if len(names) > 3 else "")
    mon, url = date.fromisoformat(week), base_url()
    secs = lambda b: b.get("sections", [])  # noqa: E731
    text = (f"{head}의 이번 주 노트가 올라왔어요.\n"
            + ("\n앞으로 7일\n" + "".join(f"· {_day(d)} {x}\n" for d, x in sorted([(d, f"{n} {k}") for d, n, k, *_ in events]
                                                                                 + [(d, f"{n} — 휴장") for d, n in holidays]))
               if events or holidays else "")
            + "".join(f"\n■ {s['name']}\n{s['body']['headline']}\n" + " ".join(x["text"] for x in s["body"].get("summary", [])) + "\n"
                      + "".join(f"\n[{x['title']}]\n" + " ".join(y["text"] for y in x["sentences"]) + "\n" for x in secs(s["body"]))
                      for s in stocks)
            + f"\n한장에서 보기: {url}/\n\n사라·팔아라는 의견도, 앞으로의 예측도 없어요. 투자 판단은 본인이 해요.\n"
            "안내 메일은 한장의 내 프로필에서 끌 수 있어요.")  # fmt: skip
    rows = [_wave(GREEN, pad="0 28px"), _wave(GREEN, dots=True, pad="2px 28px 0"),  # 머리 — 실선 물결 + 점선 물결
            f'<tr><td align="right" style="padding:14px 28px 0;font-size:13px;font-weight:700;color:{GREEN}">{mon.year}. {mon.month}. {mon.day}.</td></tr>',
            f'<tr><td align="center" style="padding:10px 28px 0"><div style="font-size:13px;font-weight:800;letter-spacing:2px;color:{SUB}">주간 노트</div>'
            f'<div style="margin-top:2px;font-size:56px;font-weight:900;letter-spacing:-2px;line-height:1.1;color:{GREEN}">한장</div></td></tr>',
            f'<tr><td style="padding:28px 28px 0;font-size:16px;line-height:1.85;color:{INK}">'
            f'안녕하세요! 이번 주 <b>{e(head)}</b>의 노트가 올라왔어요. 회사 사정을 쉬운 글로 한 장씩 정리했어요.</td></tr>']  # fmt: skip
    rows += [_wave(), '<tr><td style="padding:8px 28px 16px">'
             + _label("", "📅 CALENDAR")
             + "</td></tr>", _week(mon, events, holidays)]  # fmt: skip
    for k, s in enumerate(stocks, 1):
        b, urls = s["body"], {f["id"]: f["url"] for f in s["facts"] if f.get("url")}
        body = (f'<div style="margin-top:18px;padding:16px 18px;border-left:4px solid {GREEN};background:{BG};font-size:17px;font-weight:700;line-height:1.6;color:{GREEN}">'
                f'{e(b["headline"])}</div>' + _bars(s.get("fin", [])) + '<div style="height:12px"></div>' + _paras(b.get("summary", []), urls))  # fmt: skip
        for x in secs(b):
            icon = next((v for t, v in ICON.items() if x["title"].startswith(t)), "•")
            body += (f'<div style="margin:26px 0 10px;font-size:17px;font-weight:800;color:{INK}">{icon} {e(x["title"])}</div>'
                     + _paras(x["sentences"], urls, mark=True))  # fmt: skip
        sides = [(label, tone, b.get(f"{key}_title", ""), b[key]) for key, label, tone in (("good", "긍정", 1), ("concern", "부정", -1))
                 if b.get(key) and b.get(f"{key}_title") != "분류된 것 없음"]  # fmt: skip
        if sides:
            body += (f'<div style="margin:26px 0 10px;font-size:17px;font-weight:800;color:{INK}">⚖️ 긍정 요인과 부정 요인</div>'
                     + "".join(f'<div style="margin-bottom:16px">{_chip(label, tone)} <b style="font-size:15px;color:{TINT[tone][1]}">{e(title)}</b>'
                               f'<div style="margin-top:6px;font-size:16px;line-height:1.85;color:{INK}">{" ".join(_sentence(x, urls) for x in items)}</div></div>'
                               for label, tone, title, items in sides))  # fmt: skip
        rows += [_wave(), '<tr><td style="padding:8px 28px 8px">'
                 + _label(f"내 종목 {k:02d}", f'{e(s["name"])} <span style="font-size:13px;font-weight:400;color:{MUTE};letter-spacing:1px">{e(s["ticker"])}</span>')
                 + f"{body}</td></tr>"]  # fmt: skip
    rows += [
             f'<tr><td align="center" style="padding:22px 28px 8px"><a href="{url}/" style="display:inline-block;padding:15px 34px;border-radius:30px;background:{GREEN};'
             'color:#ffffff;font-size:16px;font-weight:800;text-decoration:none">한장 앱으로 가기 →</a></td></tr>',
             '<tr><td style="height:30px"></td></tr>']  # fmt: skip
    html = (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>'
            f'<body style="margin:0;padding:24px 8px;background:{BG};font-family:{FONT}">'
            f'<table align="center" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;font-family:{FONT};padding-top:24px">'
            + "".join(rows) + "</table></body></html>")  # fmt: skip
    return "[한장] 이번 주 노트가 올라왔어요", text, html
