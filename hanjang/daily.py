"""매일 아침 한 번에 — 받기 → 노트 → (월요일만) 안내 메일. `python -m hanjang.daily` (매일 07:00 예약 실행).
월요일은 그 주 노트를 전부 새로 쓰고, 화~일은 사실이 바뀐 종목만 다시 쓴다(밤비처럼 「자주 받고, 바뀐 것만 쓴다」).
단계가 하나 실패하면 거기서 멈춘다 — 빈 노트로 안내 메일을 보내지 않게."""

import json
import sqlite3
import sys
import traceback
from datetime import date, timedelta

from hanjang import articles, backup, collect, db, holders, mail, notes, sources


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
        evs = [(d, n, t, "", notes.DART.format(r) if r else "", 0) for d, n, _, t, r in evs]  # 칩에는 쉬운 말(「실적 발표」)
        mail.send(email, *mail.weekly_mail(week, stocks, evs, hol))
    return len(by)


def main(today: date) -> None:
    monday = today.weekday() == 0
    print(f"백업 {backup.backup(today)}")  # 받기 전에 — 오늘 실행이 DB 를 망가뜨려도 어제 것으로 돌아갈 수 있게
    collect.main(today)
    notes.main([], today, only_changed=not monday)
    articles.main(today)  # 피드 「최근 소식」 — 새 사건마다 기사 한 편
    holders.main(today)  # 큰손 포트폴리오 — 최근 일주일 대량보유 보고만 더한다
    if monday:
        print(f"안내 메일 {notify(db.connect(), notes.week_of(today))}명")


def alert(err: BaseException) -> None:
    """실패하면 운영자(보내는 Gmail 계정)에게 바로 알린다 — 서버 로그를 매일 들여다보지 않아도 되게. 메일이 안 오면 잘 돈 것."""
    to = sources.env().get("SMTP_USER")
    if to:
        mail.send(to, f"[한장] 매일 실행 실패 — {type(err).__name__}", "".join(traceback.format_exception(err)))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        main(date.today())
    except Exception as err:
        alert(err)
        raise
