"""매일 아침 한 번에 — 받기 → 노트 → (월요일만) 안내 메일. `python -m hanjang.daily` (매일 07:00 예약 실행).
월요일은 그 주 노트를 전부 새로 쓰고, 화~일은 사실이 바뀐 종목만 다시 쓴다(밤비처럼 「자주 받고, 바뀐 것만 쓴다」).
단계가 하나 실패하면 거기서 멈춘다 — 빈 노트로 안내 메일을 보내지 않게."""

import sqlite3
import sys
from datetime import date

from hanjang import articles, backup, collect, db, holders, mail, notes


def notify(con: sqlite3.Connection, week: str) -> int:
    """담은 종목 중 이번 주 노트가 있는 사용자에게만 한 통씩 — 프로필에서 메일을 끈 사람은 빼고."""
    rows = con.execute(
        "select u.email, s.name from users u join holdings h on h.user_id = u.id join stocks s using(ticker)"
        " join notes n on n.ticker = s.ticker and n.week = ? where u.mail_on = 1 order by u.id, h.added_at", (week,)).fetchall()  # fmt: skip
    by: dict[str, list[str]] = {}
    for email, name in rows:
        by.setdefault(email, []).append(name)
    for email, names in by.items():
        mail.send(email, *mail.weekly_mail(names))
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


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(date.today())
