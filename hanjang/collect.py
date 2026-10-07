"""주간 노트 만들기 ① 받기 (PRD §5.2). `python -m hanjang.collect` — 다시 돌려도 중복 없음."""

import sqlite3
import sys
import time
from datetime import date, timedelta

from hanjang import db, sources

UNIVERSE = 100
DISCLOSURE_DAYS = 90
MACRO_DAYS = 400  # 민감도(250거래일)에 넉넉히 — 쓰는 건 시세를 산 뒤


def save_universe(con: sqlite3.Connection, picked: list[tuple[str, str]], corps: dict[str, str]):
    """새로 고른 종목만 active. 빠진 종목은 지우지 않고 active=0 (ERD stocks)."""
    con.execute("update stocks set active = 0")
    con.executemany(
        "insert into stocks values (?, ?, ?, 1) on conflict(ticker) do update set"
        " name = excluded.name, corp_code = excluded.corp_code, active = 1",
        [(t, n, corps.get(t)) for t, n in picked],
    )


def save_financials(con: sqlite3.Connection, rows: list[sources.Financial]):
    con.executemany(
        "insert or replace into financials values (?, ?, ?, ?, ?, ?, ?, ?)",
        [(f.ticker, f.fiscal_year, f.revenue, f.operating_income, f.net_income, f.equity,
          f.liabilities, f.rcept_no) for f in rows],
    )  # fmt: skip


def save_disclosures(con: sqlite3.Connection, rows: list[sources.Disclosure]):
    """AI 판독 칸(code·read_at …)은 건드리지 않는다 — 이미 읽은 공시를 다시 읽지 않게."""
    con.executemany(
        "insert into disclosures (rcept_no, ticker, date, title) values (?, ?, ?, ?)"
        " on conflict(rcept_no) do update set title = excluded.title",
        [(d.rcept_no, d.ticker, d.day.isoformat(), d.title) for d in rows],
    )


def main(today: date) -> None:
    con = db.connect()
    dart = sources.Dart()
    picked = sources.kospi_universe(UNIVERSE)
    tickers = [t for t, _ in picked]
    save_universe(con, picked, dart.corps())
    print(f"종목 {len(tickers)}개 (코스피 시총 상위)")

    fin = [f for y in (today.year - 1, today.year - 2) for f in dart.financials(tickers, y)]
    save_financials(con, fin)
    print(f"재무 {len(fin)}행 ({today.year - 2}~{today.year - 1})")

    ds = dart.disclosures(today - timedelta(days=DISCLOSURE_DAYS), today, set(tickers))
    save_disclosures(con, ds)
    print(f"공시 {len(ds)}건 (최근 {DISCLOSURE_DAYS}일) · DART {dart.calls}콜")

    for sid, name in sources.MACRO.items():
        pts = sources.ecos(sid, today - timedelta(days=MACRO_DAYS), today)
        con.executemany("insert or replace into macro values (?, ?, ?)",
                        [(sid, d.isoformat(), v) for d, v in pts])  # fmt: skip
        print(f"{name} {len(pts)}일")

    n = 0
    for t, name in picked:
        try:
            got = sources.news(name)
        except Exception as e:  # noqa: BLE001  뉴스 하나가 막혀도 나머지는 받는다
            print(f"  뉴스 실패 {name}: {type(e).__name__}", file=sys.stderr)
            continue
        con.executemany(
            "insert or ignore into news values (?, ?, ?, ?, ?)",
            [(x.url, t, x.published.date().isoformat(), x.press, x.title) for x in got],
        )
        n += len(got)
        time.sleep(0.5)  # 구글에 몰아치지 않는다
    print(f"뉴스 {n}건 (개발용 · 개인용만)")
    con.commit()


if __name__ == "__main__":
    main(date.today())
