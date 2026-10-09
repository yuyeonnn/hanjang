"""아침 한 장 — 매일 아침 내 종목 소식 · 이번 주 일정 · 그 소식에 맞춘 짧은 꿀팁 (docs/growth.md §3-1, 시안 2026-10-10).

코드가 쓴다. 쉬운 풀이가 없는 공시 제목만 AI 가 문장 하나로 — **공시마다 한 번**(매일 실행 prepare), 담은 사람이 있는 회사만.
같은 회사 소식은 누구에게나 같아서 사용자가 늘어도 AI 비용은 늘지 않는다(사용자 10/10 ②안). 화면은 AI 를 부르지 않는다. 이어지는 문장으로(사용자 10/10: 막대기·나열 말고 자연스러운 문장, 간결하게). 회사 이름마다 원문 링크.
주가는 쓸 권리가 없어 싣지 않는다(data-rights §4) — 그 말도 따로 적지 않는다(사용자 10/10).

    uv run python -m hanjang.morning 005930 000660 TSLA --day 2026-10-08   # 시안 보기 (글 + data/morning-sample.html)
"""

import re
import sqlite3
import sys
from datetime import date, timedelta
from html import escape as e

from . import learn, notes, sources

WEEK = "월화수목금토일"

# 그 주에 생긴 일에 맞춘 짧은 꿀팁 — 사실과 읽는 법만(사라·팔아라·예측 없음, 불변식 1). (제목, 글, 더 읽기 slug)
TIPS = {
    "RIGHTS_ISSUE": ("유상증자 공시는 이렇게 읽어요",
                     "새 주식을 몇 주, 한 주에 얼마에 파는지 먼저 봐요. 지금 주식 수에 견줘 새 주식이 많을수록 기존 주주 몫이 더 묽어져요. "
                     "모은 돈을 어디에 쓰는지(빚 갚기·시설 투자·운영 자금)도 공시에 적혀 있어서, 회사가 왜 돈이 필요한지 알 수 있어요.", "disclosure"),
    "CB_BW": ("전환사채는 이런 빚이에요",
              "지금은 빚이지만, 나중에 정해 둔 값(전환가액)에 주식으로 바꿀 수 있는 채권이에요. "
              "주식으로 바뀌면 주식 수가 늘어나서, 공시의 「전환가액」과 「전환 청구 기간」을 보면 언제 얼마나 늘 수 있는지 알 수 있어요.", "disclosure"),
    "BUYBACK": ("자사주 매입은 소각까지 봐요",
                "회사가 시장에서 자기 회사 주식을 사들이는 거예요. 사들인 주식을 없애는 「소각」까지 하면 전체 주식 수가 줄어 한 주의 몫이 커지지만, "
                "들고만 있으면 나중에 다시 팔 수도 있어요. 그래서 공시에 소각 계획이 있는지 함께 보면 좋아요.", "ratios"),
    "DIVIDEND": ("배당은 기준일에 가진 사람이 받아요",
                 "배당을 받으려면 「배당 기준일」에 주주 명부에 올라 있어야 해요. 국내 주식은 산 날로부터 이틀 뒤(영업일)에 내 것이 되기 때문에, "
                 "기준일보다 이틀 앞선 거래일까지 사 두어야 그 배당을 받아요.", "dividend"),
    "EARNINGS": ("잠정 실적은 1년 전 같은 분기와 견줘요",
                 "잠정 실적은 회계 감사를 받기 전에 먼저 알리는 숫자라, 나중에 나오는 확정 숫자와 조금 다를 수 있어요. "
                 "바로 앞 분기보다 1년 전 같은 분기와 견주면 계절 탓을 덜 받아서 흐름이 잘 보여요.", "statements"),
    "EARNINGS_US": ("미국 실적 발표엔 전망이 함께 나와요",
                    "미국 회사는 실적을 발표할 때 다음 분기나 올해 매출 전망을 함께 내는 일이 많아요. "
                    "지난 분기 숫자만큼 이 전망이 이야기되는데, 한장 노트의 「회사는 이렇게 전망했어요」에서 그 숫자를 볼 수 있어요.", "statements"),
    "MAJOR_CONTRACT": ("큰 계약은 매출과 견줘 봐요",
                       "판매·공급 계약 공시에는 계약 금액이 최근 매출의 몇 %인지 함께 적혀 있어요. 이 비율이 클수록 회사에 큰 계약이고, "
                       "계약 기간이 길면 그 매출이 여러 해에 나뉘어 들어와요.", "disclosure"),
    "MA": ("다른 회사 지분을 살 땐 자기 돈과 견줘요",
           "지분을 사는 공시에는 얼마를 주고 몇 %를 사는지, 그 돈이 회사 자기 돈(자기자본)의 몇 %인지가 적혀 있어요. "
           "자기 돈에 견줘 금액이 크면 회사 살림에 그만큼 큰 결정이에요.", "disclosure"),
    "CLINICAL": ("임상과 허가는 다른 단계예요",
                 "「품목허가」는 이제 팔아도 된다는 허가이고, 「임상」은 아직 사람에게 시험하는 중이라는 뜻이에요. "
                 "임상은 1상·2상·3상 순서로 가고, 3상까지 마쳐야 허가를 신청할 수 있어요.", "disclosure"),
    "TRADING_HALT": ("거래 정지는 까닭부터 봐요",
                     "거래소가 중요한 일을 확인하는 동안 사고팔기를 잠시 멈추는 거예요. 정지된 동안엔 팔 수도 살 수도 없어서, "
                     "공시에 적힌 정지 까닭과 풀리는 조건을 먼저 보는 게 좋아요.", "disclosure"),
    "금리": ("금리가 바뀌면 이자가 달라져요",
             "기준금리는 돈을 빌리는 기본값이에요. 금리가 오르면 빚이 많은 회사는 이자를 더 내고, 내리면 덜 내요. "
             "내 종목 노트의 「부채비율」에서 그 회사 빚이 얼마나 되는지 볼 수 있어요.", "sector-debt"),
    "물가": ("물가 발표는 금리 결정의 재료예요",
             "소비자물가는 우리가 사는 물건값이 1년 전보다 얼마나 올랐는지 재는 숫자예요. "
             "중앙은행은 이 숫자를 보고 금리를 정하기 때문에, 물가 발표는 금리 결정 앞에 많이 이야기돼요.", None),
    "고용": ("고용 보고서는 경기의 체온계예요",
             "일자리가 한 달 동안 얼마나 늘었는지 알려 주는 숫자예요. 중앙은행이 금리를 정할 때 물가와 함께 보는 숫자라 발표 날 많이 이야기돼요.", None),
    "공모주": ("공모주 청약은 이렇게 해요",
               "신청한 금액의 절반쯤을 증거금으로 먼저 맡기고, 경쟁률에 따라 주식을 나눠 받아요. 받지 못한 증거금은 며칠 뒤 돌려받아요. "
               "투자설명서에 공모가를 정한 근거와 모은 돈의 쓰임이 적혀 있어요.", "start"),
}
TIP_ORDER = ("TRADING_HALT", "RIGHTS_ISSUE", "CB_BW", "CLINICAL", "EARNINGS", "BUYBACK", "DIVIDEND", "MAJOR_CONTRACT", "MA")


def since(today: date) -> date:
    """「새로 생긴 일」의 시작 — 앞 평일(월요일이면 금요일). 어제 장 마감 뒤·밤사이 미국 공시까지 들어온다."""
    d = today - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def md(d: date) -> str:
    return f"{d.month}월 {d.day}일({WEEK[d.weekday()]})"


def eun(name: str) -> str:
    """「한화오션은」「LG전자는」 — 영어로 끝나면 읽는 소리로(notes.josa)."""
    return notes.josa(name, "은")


def happened(title: str, ai: str | None = None) -> str:
    """공시 하나 → 「…했어요.」로 끝나는 말. 코드 풀이 → AI 가 미리 쓴 문장(prepare) → 괄호 속 설명이나 다듬은 제목을 「…」 소식으로."""
    p = notes.plain(title) or ai
    if p:
        return p.rstrip(".") + "."
    t = notes.tidy(title)
    m = re.search(r"\((.+)\)\s*$", t)
    t = m[1].strip() if m and len(m[1]) > 6 else t
    return f"「{t}」 소식을 알렸어요."


SCHEMA = {"type": "object", "additionalProperties": False, "required": ["sentence"], "properties": {"sentence": {"type": "string"}}}


def check(j: dict, title: str) -> str:
    """AI 문장 검사 — 해요체 한 문장 · 80자 안 · 제목에 없는 숫자 없음 · 금지어·예측 말투 없음. 비면 「알 수 없음」."""
    s = j["sentence"].strip()
    if not s:
        return ""
    if len(s) > 90 or not s.endswith("요.") or s.count(".") > 1 or notes.FORBIDDEN.search(s) or notes.PREDICT.search(s):
        raise ValueError(s)
    if any(n not in title for n in re.findall(r"\d+(?:[.,]\d+)?", s)):
        raise ValueError(s)
    return s


def prepare(con: sqlite3.Connection, today: date) -> int:
    """매일 실행 — 지난 평일부터 나온 중요 공시 가운데 코드 풀이가 없는 것만, 담은 사람이 있는 회사만 AI 로 한 문장(disclosures.plain).
    한 번 쓰면 다시 묻지 않는다(실패해도 빈 칸으로 남겨 두고 화면은 제목을 「」로)."""
    from . import llm

    rows = con.execute("select d.rcept_no, d.title, s.name from disclosures d join stocks s using(ticker) where d.date >= ? and d.importance >= 2"
                       " and d.plain is null and d.ticker in (select ticker from holdings)", (since(today).isoformat(),)).fetchall()  # fmt: skip
    n = 0
    for rno, title, name in rows:
        got = "" if notes.plain(title) else llm.ask("reader", "plain", {"회사": name, "제목": notes.tidy(title)}, lambda j, t=title: check(j, t), SCHEMA, prompt_file="morning")
        con.execute("update disclosures set plain = ? where rcept_no = ?", (got or "", rno))
        n += bool(got)
    con.commit()
    return n


def rate_now(con: sqlite3.Connection) -> str:
    """한국 기준금리 지금 값과 가장 최근에 바뀐 때 — 「지금 3.00% · 8월에 2.75%에서 올렸어요」. 시장의 예상은 쓸 데이터가 없어 적지 않는다."""
    rows = con.execute("select date, value from macro where series_id = 'ECOS:722Y001:0101000' order by date desc limit 24").fetchall()
    if not rows:
        return ""
    now = rows[0][1]
    for (d, v), (_, before) in zip(rows, rows[1:]):
        if v != before:
            return f"지금 {now:.2f}% · {int(d[5:7])}월에 {before:.2f}%에서 {'올렸어요' if v > before else '내렸어요'}"
    return f"지금 {now:.2f}%"


TAG = {"EARNINGS": "실적", "AGM": "주총", "DIVIDEND": "배당", "OTHER": "회사", "금리": "금리", "물가": "물가", "고용": "고용", "휴장": "휴장", "선거": "선거"}


def build(con: sqlite3.Connection, tickers: list[str], today: date, uid: int | None = None) -> dict:
    """{"title", "when", "news": [회사마다 {"name", "url", "text"}], "follows", "week": [{"date", "label", "tag", "url"}], "tip": (제목, 글, 더 읽기)}"""
    from .daily import src  # daily 가 이 모듈을 부른다 — 위에서 부르면 서로 물린다

    q = ",".join("?" * len(tickers)) or "''"
    name = dict(con.execute(f"select ticker, name from stocks where ticker in ({q})", tickers).fetchall())
    lo = since(today)
    when = f"어제({lo.month}월 {lo.day}일)" if lo == today - timedelta(days=1) else f"지난 {WEEK[lo.weekday()]}요일({lo.month}월 {lo.day}일)부터"

    # 1) 내 종목 소식 — 회사마다 한 문단. 한 회사 안에서는 「이와 함께」로 이어지게. 회사 이름에 원문 링크
    rows = con.execute(f"select ticker, title, rcept_no, code, plain from disclosures where ticker in ({q}) and date >= ? and date < ? and importance >= 2"
                       " order by importance desc, date desc limit 8", (*tickers, lo.isoformat(), today.isoformat())).fetchall()  # fmt: skip
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r[0], []).append(r)
    news, codes = [], []
    for t, items in list(by.items())[:4]:
        nm = name.get(t, t)
        body = " ".join(("" if i == 0 else "이와 함께 ") + happened(title, ai) for i, (_, title, _, _, ai) in enumerate(items[:2]))
        news.append({"name": nm, "url": src(con, items[0][2]), "text": f"{nm}{eun(nm)} {body}", "body": body, "tag": KIND.get(items[0][3], "공시")})
        codes += [("EARNINGS_US" if c == "EARNINGS" and not t.isdigit() else c, t) for _, _, _, c, _ in items]
    follows = []
    if uid:
        follows = [f"팔로우한 {n}님은 글 {k}개를 리그램했어요." for n, k in con.execute(
            "select u.nickname, count(*) from regrams r join users u on u.id = r.user_id where r.user_id in "
            "(select followee_id from follows where follower_id = ? and ok = 1) and r.at >= ? group by u.id order by count(*) desc limit 2",
            (uid, lo.isoformat())).fetchall()]  # fmt: skip

    # 2) 이번 주 — 날짜 순서 타임라인. 내 종목 일정 · 시장 일정(금리는 지금 값과 지난번 변화) · 공모주(날마다 한 줄)
    hi = today + timedelta(days=7)
    week, kinds = [], []
    for t, d, kind, title, rno in con.execute(f"select ticker, date, kind, title, rcept_no from events where ticker in ({q}) and date >= ? and date <= ? order by date",
                                              (*tickers, today.isoformat(), hi.isoformat())).fetchall():  # fmt: skip
        week.append({"date": d, "label": f"{name.get(t, t)} {title.replace(' (회사가 알린 날)', '')}", "tag": TAG.get(kind, "회사"), "url": src(con, rno)})
    us = any(not t.isdigit() for t in tickers)
    for d, kind, nation, what in sources.macro_events(today.isoformat(), hi.isoformat()):
        if kind == "휴장" and nation == "US" and not us:
            continue  # 미국 휴장은 미국 주식을 가진 사람만
        note = rate_now(con) if kind == "금리" and nation == "KR" else ""
        week.append({"date": d, "label": what + (" 예정" if kind == "금리" else ""), "tag": TAG.get(kind, kind), "url": "", "note": note})
        kinds.append(kind)
    ipos = con.execute("select name, sub_start, sub_end from ipos where sub_start <= ? and sub_end >= ? order by sub_start",
                       (hi.isoformat(), today.isoformat())).fetchall()  # fmt: skip
    ipo = f"이번 주 청약하는 공모주 {len(ipos)}곳 — {'·'.join(n for n, _, _ in ipos[:3])}" + (" 등" if len(ipos) > 3 else "") if ipos else ""  # 타임라인을 다 차지하지 않게 한 줄로
    week.sort(key=lambda x: x["date"])

    # 3) 알아 두면 좋아요 — 그 주에 생긴 일 하나에 맞춘 짧은 꿀팁. 내 종목 공시 > 시장 일정 > 공모주 > 읽기 팁 돌려 가며
    key = next((c for c in TIP_ORDER + ("EARNINGS_US",) if c in {x for x, _ in codes}), None) or next((k for k in ("금리", "물가", "고용") if k in kinds), None) or ("공모주" if ipos else None)
    if key:
        head, body, slug = TIPS[key]
        a = learn.BY_SLUG.get(slug)
        tip = (head, body, (a["title"], f"/learn/{slug}") if a else None)
    else:
        a = learn.ARTICLES[today.toordinal() % len(learn.ARTICLES)]
        tip = (a["title"], a["lead"].replace("**", ""), ("이어서 읽기", f"/learn/{a['slug']}"))
    return {"title": f"{today.month}월 {today.day}일 {WEEK[today.weekday()]}요일 아침", "when": when, "news": news, "more": max(0, len(by) - 4),
            "follows": follows, "week": week, "ipo": ipo, "tip": tip, "today": today.isoformat()}


def text(m: dict) -> str:
    out = [m["title"], "", f"[내 종목 소식 · {m['when']}]"]
    out += [x["text"] for x in m["news"]] or ["새로 나온 내 종목 공시는 없어요."]
    out += m["follows"]
    out += ["", "[이번 주]"] + [f"{x['date'][5:]}  {x['tag']:<4} {x['label']}" + (f"  ({x['note']})" if x.get("note") else "") for x in m["week"]] + ([m["ipo"]] if m["ipo"] else [])
    head, body, more = m["tip"]
    out += ["", f"[알아 두면 좋아요 · {head}]", body] + ([f"→ {more[0]}"] if more else [])
    return "\n".join(out)


KIND = {"RIGHTS_ISSUE": "유상증자", "CB_BW": "전환사채", "BONUS_ISSUE": "무상증자", "EARNINGS": "실적", "MAJOR_CONTRACT": "큰 계약", "BUYBACK": "자사주",
        "DIVIDEND": "배당", "MA": "지분·합병", "CLINICAL": "신약", "TRADING_HALT": "거래 정지", "EXEC": "경영진", "DEBT": "빚", "LAWSUIT": "소송",
        "WRITE_DOWN": "손상", "HOLDER_CHANGE": "최대주주"}  # fmt: skip


def html(m: dict) -> str:
    """홈 맨 위 접힌 카드 + 누르면 위에 뜨는 카드(<dialog>). 펼친 카드는 Stitch 시안(2026-10-10 「아침 한 장」) 그대로 —
    진한 초록 머리 · 초록 점 소제목 · 점선으로 나눈 회사별 글 · 두 줄(실선+점선) 칸막이. 시안의 「동결 유력 전망」(쓸 데이터 없음)·보관·공유 단추는 뺐다."""
    def h3(title: str, right: str = "") -> str:
        return (f'<div class="flex items-center justify-between mb-3"><div class="flex items-center gap-2"><span class="w-2.5 h-2.5 shrink-0 rounded-full bg-primary"></span>'
                f'<h3 class="text-[17px] font-bold text-primary tracking-tight">{title}</h3></div>'
                + (f'<span class="text-[11px] font-medium text-on-surface-variant">{right}</span>' if right else "") + "</div>")  # fmt: skip

    rule = '<div class="py-2" role="separator"><div class="w-full h-[2px] bg-primary"></div><div class="w-full mt-[3px] border-b-[2.5px] border-dotted border-primary"></div></div>'
    dot = "border-b border-dotted border-primary/20"
    arts = "".join(
        f'<article class="flex flex-col gap-1.5 pb-3 {dot} last:border-b-0"><div class="flex items-center gap-2">'
        f'<span class="text-[16px] font-bold text-on-surface">{e(x["name"])}</span><span class="text-[11px] font-bold text-primary">{e(x["tag"])}</span></div>'
        f'<p class="text-[14px] leading-[23px] text-on-surface">{e(x["body"])}</p>'
        f'<a class="pt-1 text-[11px] font-bold text-primary hover:underline inline-flex items-center gap-0.5" href="{e(x["url"])}">공시 원문 보기'
        '<span class="material-symbols-outlined text-[13px]">arrow_forward</span></a></article>' for x in m["news"])  # fmt: skip
    if not m["news"]:
        arts = '<p class="text-[14px] leading-[23px] text-on-surface-variant">새로 나온 내 종목 공시는 없어요.</p>'
    if m["more"]:
        arts += f'<p class="text-[13px] text-on-surface-variant">그 밖에 {m["more"]}곳 소식은 각 노트에서 볼 수 있어요.</p>'
    arts += "".join(f'<p class="text-[13px] text-on-surface-variant">{e(f)}</p>' for f in m["follows"])
    count = f"{len(m['news']) + m['more']}곳" if m["news"] else ""
    news = f'<section class="flex flex-col">{h3("내 종목 소식 · " + e(m["when"]), count)}<div class="flex flex-col gap-4">{arts}</div></section>'

    rows = []
    for x in m["week"]:
        d = date.fromisoformat(x["date"])
        when = "오늘" if x["date"] == m["today"] else f"{d.month}/{d.day} ({WEEK[d.weekday()]})"
        label = f'<a class="hover:underline" href="{e(x["url"])}">{e(x["label"])}</a>' if x["url"] else e(x["label"])
        rows.append(f'<div class="flex flex-col gap-1 pb-2.5 {dot}"><div class="flex items-baseline justify-between gap-2"><div class="flex items-baseline gap-2.5 min-w-0">'
                    f'<span class="shrink-0 text-[13px] font-bold text-primary">{when}</span><span class="text-[14px] font-semibold text-on-surface">{label}</span></div>'
                    f'<span class="shrink-0 text-[11px] font-bold text-secondary">{e(x["tag"])}</span></div>'
                    + (f'<div class="text-[12px] text-on-surface-variant">{e(x["note"])}</div>' if x.get("note") else "") + "</div>")  # fmt: skip
    if m["ipo"]:
        rows.append('<a class="pt-1 flex items-center justify-between gap-2" href="/calendar"><span class="flex items-center gap-2 min-w-0">'
                    '<span class="material-symbols-outlined text-primary text-[17px]">campaign</span>'
                    f'<span class="text-[13px] font-bold text-primary truncate">{e(m["ipo"])}</span></span>'
                    '<span class="shrink-0 text-[11px] font-bold text-primary inline-flex items-center gap-0.5">캘린더<span class="material-symbols-outlined text-[13px]">arrow_forward</span></span></a>')  # fmt: skip
    week = (rule + f'<section class="flex flex-col">{h3("이번 주 일정")}<div class="flex flex-col gap-3">{"".join(rows)}</div></section>') if rows else ""

    head, body, more = m["tip"]
    tip = (rule + f'<section class="flex flex-col">{h3("알아 두면 좋아요")}<h4 class="text-[15px] font-bold text-primary leading-tight">{e(head)}</h4>'
           f'<p class="mt-2 text-[14px] leading-[23px] text-on-surface">{e(body)}</p>'
           + (f'<a class="mt-3 pt-2.5 border-t border-dotted border-primary/20 text-[12px] font-bold text-primary hover:underline inline-flex items-center gap-1" href="{e(more[1])}">'
              f'<span class="material-symbols-outlined text-[14px]">help_outline</span>{e(more[0])}<span class="material-symbols-outlined text-[13px]">arrow_forward</span></a>' if more else "")
           + "</section>")  # fmt: skip

    lead = m["news"][0]["text"] if m["news"] else "새 공시 없는 조용한 아침이에요."
    # 접힌 카드 한 장(눌러서 펼침). 해 아이콘·날짜 한 줄 + 이야기 한 줄만 (사용자 10/10)
    card = ('<button type="button" onclick="document.getElementById(\'morning\').showModal()" aria-haspopup="dialog" '
            'class="group mt-space-md w-full text-left rounded-2xl border border-surface-container-high bg-surface-container-lowest '
            'shadow-[0_10px_24px_-12px_rgba(21,69,57,0.45)] hover:shadow-[0_14px_30px_-12px_rgba(21,69,57,0.55)] hover:-translate-y-0.5 transition-all px-4 py-3.5 flex items-center gap-3">'
            f'<span class="flex-1 min-w-0 flex flex-col gap-1"><span class="flex items-center gap-1 text-[12px] font-semibold text-primary">'
            f'<span class="material-symbols-outlined text-[16px]">wb_sunny</span>아침 한 장 · {e(m["title"].replace(" 아침", ""))}</span>'
            f'<span class="text-[15px] font-semibold text-on-surface truncate">{e(lead)}</span></span>'
            '<span class="material-symbols-outlined shrink-0 text-primary transition-transform group-hover:translate-x-0.5">chevron_right</span></button>')  # fmt: skip
    # 위에 뜨는 카드 — 뒤 화면은 가리지 않고(사용자 10/10) 그림자 두 겹으로 띄운다. ✕·바깥을 누르면 닫힘
    sheet = ('<dialog id="morning" onclick="if(event.target===this)this.close()" aria-label="아침 한 장" '
             'class="w-[calc(100%-32px)] max-w-[448px] max-h-[82vh] p-0 rounded-3xl bg-surface-container-lowest border border-primary/10 backdrop:bg-transparent overflow-hidden '
             'shadow-[0_24px_50px_-10px_rgba(21,69,57,0.18),0_4px_16px_rgba(0,0,0,0.05)]"><div class="flex flex-col max-h-[82vh]">'
             '<header class="shrink-0 bg-primary text-on-primary px-6 pt-5 pb-5 flex items-start justify-between">'
             '<div class="flex flex-col gap-1"><div class="flex items-center gap-1.5 text-primary-fixed-dim text-[11px] font-semibold tracking-wider">'
             '<span class="material-symbols-outlined text-[15px]">wb_sunny</span>아침 한 장</div>'
             f'<h2 class="font-headline-lg text-[22px] font-bold tracking-tight mt-0.5">{e(m["title"])}</h2></div>'
             '<form method="dialog"><button aria-label="닫기" class="text-on-primary/80 hover:text-on-primary p-1 rounded-full hover:bg-on-primary/10 transition-colors">'
             '<span class="material-symbols-outlined text-[20px]">close</span></button></form></header>'
             f'<div class="overflow-y-auto px-6 pt-5 pb-7 flex flex-col gap-4">{news}{week}{tip}</div></div></dialog>')  # fmt: skip
    return card + sheet


if __name__ == "__main__":
    from pathlib import Path

    from . import db, web

    args = sys.argv[1:]
    day = date.fromisoformat(args[args.index("--day") + 1]) if "--day" in args else date.today()
    tickers = [a for i, a in enumerate(args) if a != "--day" and (i == 0 or args[i - 1] != "--day")]
    con = db.connect()
    m = build(con, tickers, day)
    sys.stdout.reconfigure(encoding="utf-8")
    print(text(m))
    css = (web.STATIC / "app.css").read_text(encoding="utf-8")
    out = Path(db.ROOT) / "data" / "morning-sample.html"
    out.write_text(web.page("아침 한 장 시안", "bg-surface font-body-reading text-on-surface", f'<main class="w-full max-w-[480px] mx-auto px-margin py-6">{html(m)}</main>')
                   .replace(web.CSS_TAG, f"<style>{css}</style>"), encoding="utf-8")  # fmt: skip
    print(f"\n→ {out}")
