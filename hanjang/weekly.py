"""주 1회 한 번에 — 받기 → 노트 만들기 → 안내 메일. `python -m hanjang.weekly` (일요일 밤 예약 실행).
단계가 하나 실패하면 거기서 멈춘다 — 빈 노트로 안내 메일을 보내지 않게."""

import sqlite3
import sys
from datetime import date

from hanjang import collect, db, mail, notes


def notify(con: sqlite3.Connection, week: str) -> int:
    """담은 종목 중 이번 주 노트가 있는 사용자에게만 한 통씩."""
    rows = con.execute(
        "select u.email, s.name from users u join holdings h on h.user_id = u.id join stocks s using(ticker)"
        " join notes n on n.ticker = s.ticker and n.week = ? order by u.id, h.added_at", (week,)).fetchall()  # fmt: skip
    by: dict[str, list[str]] = {}
    for email, name in rows:
        by.setdefault(email, []).append(name)
    for email, names in by.items():
        mail.send(email, *mail.weekly_mail(names))
    return len(by)


def main(today: date) -> None:
    collect.main(today)
    notes.main([], today)
    week = notes.week_of(today)
    print(f"안내 메일 {notify(db.connect(), week)}명")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(date.today())
