"""오늘의 한 면 — 새 공시가 없는 날에도 날마다 다른 글이 나오게, 내 종목 하나의 한 면(사업·실적·남기는 힘·빚·같은 업종·배당·큰손·위험)을 꺼내 보여 준다.

왜: 담긴 종목의 절반은 14일 동안 중요한 공시가 한 건도 없었다(2026-10-13 실측 — SK하이닉스의 마지막 중요 공시는 8월 21일). 공시만 기다리면 화면이 몇 주씩 그대로다.
새 자료는 없다 — 노트가 쓰는 사실(notes.facts)과 사업보고서 요약·배당·대량보유 표를 **코드가** 문장으로 옮긴다. AI 를 부르지 않고, 숫자는 그 표의 값 그대로이며, 면마다 원문 주소가 붙는다.
오늘 어느 종목의 어느 면인지는 날짜로 정한다: 종목은 하루에 하나씩 돌고, 한 바퀴 돌 때마다 다음 면으로 넘어간다 — 같은 날엔 몇 번을 열어도 같다."""

import json
import sqlite3
from datetime import date

from . import holders, notes


def _src(con, rno: str) -> str:
    from .daily import src  # daily 가 morning 을, morning 이 이 모듈을 부른다 — 위에서 부르면 서로 물린다

    return src(con, rno)


def _ro(v: str) -> str:
    return v + notes.josa(v, "로")


def _was(v: str) -> str:
    return v + ("이었어요" if notes.josa(v, "은") == "은" else "였어요")


def _is(v: str) -> str:
    return v + ("이에요" if notes.josa(v, "은") == "은" else "예요")


def _moved(what: str, s: dict, value: str = "값", way: str = "방향", size: str = "폭", than: str = "1년 전보다") -> str:
    """「매출은 97.1조원으로 1년 전보다 46.8% 늘었어요.」 — 견줄 값이 없으면 「97.1조원이었어요.」"""
    v = s[value] + (f"({s['원화']})" if s.get("원화") and value == "값" else "")
    if s.get(way) and s.get(size):
        return f"{what} {_ro(v)} {than} {s[size]} {s[way]}어요."
    return f"{what} {_was(v)}."


def _business(con, t, by, name):
    row = con.execute("select body, rcept_no from business where ticker = ?", (t,)).fetchone()
    what = json.loads(row[0]).get("what") if row else None
    return what and ("무엇으로 돈을 버나요?", what[:3], _src(con, row[1]))


def _risks(con, t, by, name):
    row = con.execute("select body, rcept_no from business where ticker = ?", (t,)).fetchone()
    risks = json.loads(row[0]).get("risks") if row else None
    return risks and ("회사가 스스로 꼽은 위험은요?", risks[:2], _src(con, row[1]))


def _year(con, t, by, name):
    out = []
    if f := by.get("F1"):
        out.append(_moved(f"{f['slots']['연도']} 매출은", f["slots"]))
    if f := by.get("F2"):
        out.append(_moved(("본업으로 남긴 돈(영업이익)은" if out else f"{f['slots']['연도']} 본업으로 남긴 돈(영업이익)은"), f["slots"]))
    return out and ("지난 한 해 장사는 어땠나요?", out, (by.get("F1") or by["F2"])["url"])


def _margin(con, t, by, name):
    f = by.get("F5")
    if not f:
        return None
    s = f["slots"]
    unit = "달러" if s["백원당"].endswith("달러") else "원"
    out = [f"{s['연도']}에는 100{unit}어치를 팔아 본업으로 {s['백원당']}{notes.josa(s['백원당'], '을')} 남겼어요(영업이익률 {s['비율']})."]
    if s.get("전년비율") and s.get("힘"):
        out.append(f"{s['전년연도']}에는 {s['전년비율']}였으니, 남기는 힘이 {s['힘']}어요.")
    return (f"100{unit}어치 팔면 얼마를 남기나요?", out, f["url"])


def _history(con, t, by, name):
    f = by.get("F6")
    if not f:
        return None
    s, out = f["slots"], []
    year = ((by.get("F1") or by.get("F2") or {}).get("slots") or {}).get("연도", "가장 최근 해")
    span = f"최근 {s['햇수']}({s['기간']}) 가운데"
    if s.get("매출자리"):
        out.append(f"{year} 매출은 {span} {s['매출자리']}어요." + (f" 가장 적었던 해는 {s['매출바닥해']}({s['매출바닥값']})이에요." if s.get("매출바닥해") else ""))
    if s.get("이익자리"):
        head = "영업이익은" if out else f"{year} 영업이익은 {span}"
        out.append(f"{head} {s['이익자리']}어요." + (f" 가장 적었던 해는 {s['이익바닥해']}({s['이익바닥값']})이에요." if s.get("이익바닥해") else ""))
    return out and ("최근 몇 해 가운데 어디쯤인가요?", out, f["url"])


def _quarter(con, t, by, name):
    f = by.get("F8")
    if not f:
        return None
    s, out = f["slots"], []
    when = f"{s['분기']}({s['달']})"
    if s.get("매출"):
        out.append(_moved(f"{when} 매출은", s, "매출", "매출방향", "매출폭", "1년 전 같은 분기보다"))
    if s.get("이익"):
        out.append(_moved("영업이익은" if out else f"{when} 영업이익은", s, "이익", "이익방향", "이익폭", "1년 전 같은 분기보다"))
    return out and ("가장 최근 분기는 어땠나요?", out, f["url"])


def _health(con, t, by, name):
    out = []
    if f := by.get("F3"):
        s = f["slots"]
        out.append(f"{s['연도']} 말 부채비율은 {s['비율']}예요. 빚이 {s['빚']}, 자기 돈이 {_is(s['자기돈'])}.")
    if f := by.get("F4"):
        s = f["slots"]
        out.append(f"자기 돈으로 얼마나 벌었는지 보는 ROE는 {s['비율']}예요(순이익 {s['순이익']}).")
    return out and ("빚과 살림은 어떤가요?", out, (by.get("F3") or by["F4"])["url"])


def _peers(con, t, by, name):
    f = by.get("F10")
    if not f:
        return None
    s = f["slots"]
    return ("같은 업종에서 어디쯤인가요?",
            [f"같은 업종({s['업종']}) {s['곳수']} 가운데 {s['지표']}{notes.josa(s['지표'], '가')} {s['자리']}어요({name} {s['비율']} · {s['곳수']} 중간값 {s['중간값']})."], f["url"])


def _dividend(con, t, by, name):
    if not t.isdigit():  # 미국 종목은 배당 표가 아직 없다
        return None
    rows = con.execute("select d.fiscal_year, d.dps, d.payout, f.rcept_no from dividends d join financials f on f.ticker = d.ticker and f.fiscal_year = d.fiscal_year"
                       " where d.ticker = ? and d.dps > 0 order by d.fiscal_year desc limit 3", (t,)).fetchall()  # fmt: skip
    if not rows:
        return None
    y, dps, payout, rno = rows[0]
    out = [f"{y}년에는 한 주에 {dps:,}원을 배당했어요." + (f" 그해 번 돈(순이익)의 {payout:.1f}%를 배당으로 나눈 거예요." if payout else "")]
    if len(rows) > 1:
        out.append("그 앞 해에는 " + ", ".join(f"{yy}년 {d:,}원" for yy, d, _, _ in rows[1:]) + "이었어요.")
    return ("배당은 어땠나요?", out, _src(con, rno))


def _holders(con, t, by, name):
    rows = [(holders.BIG[i][0], rate, d, rno) for i, rate, d, rno in con.execute(
        "select inst, rate, date, rcept_no from big_holdings where stock_code = ? order by rate desc limit 3", (t,)) if i in holders.BIG]
    if not rows:
        return None
    out = [f"{who}{notes.josa(who, '이')} {rate:.2f}%를 갖고 있다고 보고했어요({date.fromisoformat(d).year}년 {date.fromisoformat(d).month}월 보고)." for who, rate, d, _ in rows]
    return ("큰손은 누가 있나요?", out, _src(con, rows[0][3]))


FACETS = (_business, _year, _margin, _peers, _quarter, _health, _dividend, _history, _holders, _risks)  # 이 순서로 돈다 — 앞이 처음 보는 사람에게 먼저 필요한 것


def of(con: sqlite3.Connection, ticker: str, today: date) -> list[dict]:
    """이 종목에서 꺼낼 수 있는 면 전부 — [{"title", "sentences", "url"}]. 자료가 없는 면은 빠진다."""
    row = con.execute("select name from stocks where ticker = ?", (ticker,)).fetchone()
    if not row:
        return []
    by = {f["id"]: f for f in notes.facts(con, ticker, today) if f.get("slots")}
    out = []
    for fn in FACETS:
        try:
            got = fn(con, ticker, by, row[0])
        except KeyError:  # 그 종목엔 없는 빈칸(금융사는 매출이 없다) — 그 면만 건너뛴다
            got = None
        if got:
            out.append({"title": got[0], "sentences": got[1], "url": got[2]})
    return out


def today_pick(con: sqlite3.Connection, tickers: list[str], today: date, skip: set[str] = frozenset()) -> dict | None:
    """오늘의 한 면 — {"ticker", "name", "title", "sentences", "url"}. 종목은 하루에 하나씩 돌고, 한 바퀴마다 다음 면.
    skip: 오늘 이미 소식이 있는 종목(그 종목은 소식이 대신한다). 다 빠지면 skip 을 무시한다."""
    pool = sorted(t for t in tickers if t not in skip) or sorted(tickers)
    if not pool:
        return None
    k = today.toordinal()
    for step in range(len(pool)):  # 자료가 하나도 없는 종목(막 담은 종목)이면 다음 종목으로
        t = pool[(k + step) % len(pool)]
        fs = of(con, t, today)
        if fs:
            f = fs[(k // len(pool)) % len(fs)]
            (name,) = con.execute("select name from stocks where ticker = ?", (t,)).fetchone()
            return {"ticker": t, "name": name} | f
    return None
