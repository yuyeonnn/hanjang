"""시험 판정 숫자 (PRD §1) — `python -m hanjang.trial trial-1`. 시험 사용자는 초대 링크 /?c=trial-1 로 가입한 사람.

「다시 열었다」 = 그 주(월~일)에 자기 종목 노트를 1번 이상 연 것. 1주째 = 묶음의 첫 가입이 있는 주.
기준은 시작 전에 정한 그대로 — 3주째 30% 미만이면 접음, 6주째 절반 넘게 열고 5명 이상 「돈 내고도 보겠다」면 계속.
20명보다 적게 모이면 비율로 본다(plan.md 「막히면」). 「돈 내고도 보겠다 5명」은 그대로."""

import sqlite3
import sys
from datetime import date, timedelta

from hanjang import db

FOLD_WEEK, FOLD_RATE = 3, 0.3
KEEP_WEEK, KEEP_RATE, KEEP_PAY = 6, 0.5, 5


def weekly(con: sqlite3.Connection, cohort: str, today: date) -> tuple[int, int, list[tuple[int, date, int]]]:
    """(사람 수, 「돈 내고도 보겠다」 수, [(주차, 그 주 월요일, 자기 종목 노트를 연 사람 수)])."""
    users = con.execute("select id, created_at from users where cohort = ?", (cohort,)).fetchall()
    if not users:
        return 0, 0, []
    first = min(date.fromisoformat(c[:10]) for _, c in users)
    start = first - timedelta(days=first.weekday())
    rows, k = [], 1
    while (mon := start + timedelta(weeks=k - 1)) <= today:
        # ponytail: 「자기 종목」은 지금 담은 종목으로 본다 — 중간에 뺀 종목의 노트는 안 센다
        (n,) = con.execute(
            "select count(distinct v.user_id) from views v join users u on u.id = v.user_id and u.cohort = ?"
            " join holdings h on h.user_id = v.user_id and h.ticker = v.ticker"
            " where v.page = 'note' and v.at >= ? and v.at < ?",
            (cohort, mon.isoformat(), (mon + timedelta(days=7)).isoformat())).fetchone()  # fmt: skip
        rows.append((k, mon, n))
        k += 1
    # 사람마다 가장 마지막 답 — 0 은 「안 내요」, 그 밖은 한 달에 낼 금액
    (pay,) = con.execute(
        "select count(*) from (select f.user_id, f.would_pay from feedback f join users u on u.id = f.user_id and u.cohort = ?"
        " where f.would_pay is not null and f.at = (select max(at) from feedback g where g.user_id = f.user_id and g.would_pay is not null))"
        " where would_pay > 0", (cohort,)).fetchone()  # fmt: skip
    return len(users), pay, rows


def verdict(people: int, pay: int, rows: list[tuple[int, date, int]]) -> str:
    by = {k: n for k, _, n in rows}
    if FOLD_WEEK in by and by[FOLD_WEEK] < people * FOLD_RATE:
        return f"접음 — {FOLD_WEEK}주째 {by[FOLD_WEEK]}명 < {people}명의 {FOLD_RATE:.0%}"
    if KEEP_WEEK in by:
        if by[KEEP_WEEK] > people * KEEP_RATE and pay >= KEEP_PAY:
            return f"계속 — {KEEP_WEEK}주째 {by[KEEP_WEEK]}명 > {people}명의 절반 · 돈 내고도 보겠다 {pay}명"
        return f"그 사이 — 6주 끝에 데이터를 보고 한 번만 정한다 ({KEEP_WEEK}주째 {by[KEEP_WEEK]}명 · 돈 {pay}명)"
    return "아직 — 판정 주차 전"


def main(cohort: str, today: date) -> None:
    people, pay, rows = weekly(db.connect(), cohort, today)
    print(f"{cohort} — {people}명 · 돈 내고도 보겠다 {pay}명 (기준 {KEEP_PAY}명)")
    for k, mon, n in rows:
        mark = " ← 접음 판정" if k == FOLD_WEEK else " ← 계속 판정" if k == KEEP_WEEK else ""
        print(f"  {k}주째 ({mon:%m/%d}~) 자기 종목 노트를 연 사람 {n}명 ({n / people:.0%}){mark}")
    print(verdict(people, pay, rows))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1] if len(sys.argv) > 1 else "trial-1", date.today())
