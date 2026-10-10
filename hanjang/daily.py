"""매일 아침 한 번에 — 받기 → 노트 → (월요일만) 안내 메일. `python -m hanjang.daily` (매일 07:00 예약 실행).
월요일은 그 주 노트를 전부 새로 쓰고, 화~일은 사실이 바뀐 종목만 다시 쓴다(밤비처럼 「자주 받고, 바뀐 것만 쓴다」).
단계가 하나 실패하면 거기서 멈춘다 — 빈 노트로 안내 메일을 보내지 않게."""

import json
import sqlite3
import sys
import traceback
from datetime import date, timedelta

from hanjang import articles, backup, collect, db, etf, gurus, holders, morning, nps, llm, mail, notes, personas, sources, us


def src(con: sqlite3.Connection, rno: str | None) -> str:
    """일정의 원문 — 국내 접수번호는 DART, 미국 접수번호(「-」가 있다)는 SEC 공시 목록."""
    if not rno:
        return ""
    if "-" not in rno:
        return notes.DART.format(rno)
    row = con.execute("select s.cik from filings f join stocks s using(ticker) where f.accession = ?", (rno,)).fetchone()
    return f"https://www.sec.gov/Archives/edgar/data/{row[0]}/{rno.replace('-', '')}/{rno}-index.htm" if row else ""


def notify(con: sqlite3.Connection, week: str) -> int:
    """담은 종목 중 이번 주 노트가 있는 사용자에게만 한 통씩 — 프로필에서 메일을 끈 사람은 빼고.
    한 통에 담은 종목 노트 전부 + 보내는 날부터 7일 캘린더 (휴장일 · 내 종목 일정)."""
    rows = con.execute(
        "select u.id, u.email, s.ticker, s.name, n.body, n.facts from users u join holdings h on h.user_id = u.id join stocks s using(ticker)"
        " join notes n on n.ticker = s.ticker and n.week = ? where u.mail_on = 1 order by u.id, h.added_at", (week,)).fetchall()  # fmt: skip
    by: dict[tuple, list[dict]] = {}
    for uid, email, t, name, body, facts in rows:
        fin = con.execute("select fiscal_year, revenue, operating_income from financials where ticker = ?"
                          " order by fiscal_year desc limit 5", (t,)).fetchall()[::-1]  # 노트 화면 그림과 같은 숫자
        by.setdefault((uid, email), []).append({"ticker": t, "name": name, "body": json.loads(body), "facts": json.loads(facts), "fin": fin})
    lo, hi = week, (date.fromisoformat(week) + timedelta(days=6)).isoformat()
    hol = con.execute("select date, name from holidays where date between ? and ? order by date", (lo, hi)).fetchall()
    for (uid, email), stocks in by.items():
        # events = 공시 원문에서 읽은 앞으로의 일정 (collect — 실적 발표·주총·배당 기준일·지급일)
        evs = con.execute(
            "select e.date, s.name, e.kind, e.title, e.rcept_no from events e join holdings h on h.ticker = e.ticker and h.user_id = ?"
            " join stocks s on s.ticker = e.ticker where e.date between ? and ? order by e.date", (uid, lo, hi)).fetchall()  # fmt: skip
        evs = [(d, n, t, "", src(con, r), 0) for d, n, _, t, r in evs]  # 칩에는 쉬운 말(「실적 발표」)
        evs += [(d, {"KR": "한국", "US": "미국"}[nat], {"금리": "금리 결정", "선거": "선거", "휴장": "증시 휴장"}.get(kind, kind + " 발표"), "", sources.MACRO_SOURCE[nat + kind][1], 0)
                for d, kind, nat, _ in sources.macro_events(lo, hi)
                if kind != "휴장" or any(s["ticker"][:1].isalpha() and not s["ticker"].startswith("ETF") for s in stocks)]  # 미국 휴장은 미국 종목이 있을 때만  # 시장 일정 — 금리·물가·고용·선거  # fmt: skip
        mail.send(email, *mail.weekly_mail(week, stocks, evs, hol))
    return len(by)


def main(today: date) -> None:
    monday = today.weekday() == 0
    saved = backup.backup(today)  # 받기 전에 — 오늘 실행이 DB 를 망가뜨려도 어제 것으로 돌아갈 수 있게
    print(f"백업 {saved}")
    try:
        print(f"서버 밖 백업 {backup.offsite(saved)}")
    except Exception as err:  # 서버 밖에 못 올려도 오늘 노트는 쓴다 — 운영자에게만 알린다
        alert(err, "서버 밖 백업 실패")
    try:
        collect.main(today)
    except Exception as err:  # DART 가 쉬어도(점검) 미국·노트·아침 한 장은 어제까지의 자료로 돈다 — 운영자에게만 알린다
        alert(err, "국내 받기(DART) 실패 — 나머지는 계속")
        monday = False  # 새 자료 없이 안내 메일은 보내지 않는다
    us.main(today)  # 미국 주식 받기 (SEC) — 노트·화면은 아직 (docs/stage3-us.md)
    us.read(today)  # 미국 10-K 사업 설명 · 실적 전망 (AI) — 새 보고서만
    notes.main([], today, only_changed=not monday)
    etf.main(today)  # 담은 ETF 한 장 — 투자설명서 표지로, AI 없이
    articles.main(today)  # 피드 「최근 소식」 — 새 사건마다 기사 한 편
    print(f"아침 한 장 문장 {morning.prepare(db.connect(), today)}건")  # 코드 풀이가 없는 공시만 AI 한 문장 — 공시마다 한 번
    holders.main(today)  # 큰손 포트폴리오 — 최근 일주일 대량보유 보고만 더한다
    gurus.main(today)  # 미국 유명 투자자 13F — 새 신고가 나온 사람만 다시 받는다
    nps.main(today)  # 국민연금 한국+미국 — 1년에 한 번 새 공시(공공데이터포털), 같은 날 13F
    if sources.env().get("DEMO") == "1":  # 둘러보기 예시 사람들 — 활동 시각을 다시 「최근」으로
        print(f"예시 사람 {personas.seed(db.connect())}명")
    if monday:
        print(f"안내 메일 {notify(db.connect(), notes.week_of(today))}명")
    if llm.spent.get("no_credit") and (to := sources.env().get("SMTP_USER")):  # 멈추진 않았지만 운영자는 알아야 한다
        mail.send(to, "[한장] OpenAI 크레딧 소진 — 오늘 노트는 코드 문장으로", "platform.openai.com 결제(Billing)에서 크레딧을 채우면 다음 실행부터 AI 글로 돌아와요.")


def alert(err: BaseException, what: str = "매일 실행 실패") -> None:
    """실패하면 운영자(보내는 Gmail 계정)에게 바로 알린다 — 서버 로그를 매일 들여다보지 않아도 되게. 메일이 안 오면 잘 돈 것."""
    to = sources.env().get("SMTP_USER")
    if to:
        mail.send(to, f"[한장] {what} — {type(err).__name__}", "".join(traceback.format_exception(err)))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        main(date.today())
    except Exception as err:
        alert(err)
        raise
