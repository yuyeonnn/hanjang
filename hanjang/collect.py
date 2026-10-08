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
        "insert into stocks (ticker, name, corp_code, active) values (?, ?, ?, 1) on conflict(ticker) do update set"
        " name = excluded.name, corp_code = excluded.corp_code, active = 1",
        [(t, n, corps.get(t)) for t, n in picked],
    )


def save_financials(con: sqlite3.Connection, rows: list[sources.Financial]):
    con.executemany(
        "insert or replace into financials (ticker, fiscal_year, revenue, operating_income, net_income, equity,"
        " liabilities, rcept_no, basis) values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(f.ticker, f.fiscal_year, f.revenue, f.operating_income, f.net_income, f.equity,
          f.liabilities, f.rcept_no, f.basis) for f in rows],
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

    fin = [f for y in range(today.year - 1, today.year - 6, -1) for f in dart.financials(tickers, y)]  # 5년 — 노트 위 차트
    save_financials(con, fin)
    print(f"재무 {len(fin)}행 ({today.year - 5}~{today.year - 1})")

    lo = today - timedelta(days=DISCLOSURE_DAYS)
    ds = dart.disclosures(lo, today, set(tickers))
    save_disclosures(con, ds)
    # 받은 기간 안에서 이번 목록에 없는 공시 = 정정되어 최종본이 아닌 옛 판 → 지운다 (같은 공시가 두 번 나오지 않게)
    con.execute("create temp table if not exists got (r text primary key)")
    con.execute("delete from got")
    con.executemany("insert or ignore into got values (?)", [(d.rcept_no,) for d in ds])
    gone = con.execute("delete from disclosures where date between ? and ? and rcept_no not in (select r from got)",
                       (lo.isoformat(), today.isoformat())).rowcount  # fmt: skip
    print(f"  정정되어 옛 판이 된 공시 {gone}건 정리")

    for (t,) in con.execute("select ticker from stocks where active = 1 and (induty_code is null or homepage is null)").fetchall():
        con.execute("update stocks set induty_code = ?, homepage = ? where ticker = ?", (*dart.company(t), t))
    # 자기주식 취득 결정은 금액을 전용 API 로 받는다 (제목만으로는 규모를 모른다)
    want = con.execute("select distinct ticker from disclosures where amount is null and date >= ?"
                       " and replace(title, ' ', '') like '%자기주식취득결정%'", (lo.isoformat(),)).fetchall()  # fmt: skip
    got = 0
    for (t,) in want:
        for rno, v in dart.buybacks(t, lo, today).items():
            got += con.execute("update disclosures set amount = ? where rcept_no = ?", (v, rno)).rowcount
    print(f"  업종 코드 · 자사주 취득 금액 {got}건 · DART {dart.calls}콜")
    divs = [(t, *r) for t in tickers for y in (today.year - 1, today.year - 4) for r in dart.dividends(t, y)]  # 3년씩 두 번 = 6년
    con.executemany("insert or replace into dividends values (?, ?, ?, ?, ?)", divs)
    print(f"  배당 {len(divs)}행")
    ins = [x for t in tickers for x in dart.insiders(t, lo)]  # 종목마다 2콜 — 임원·주요주주 · 5% 대량보유
    con.executemany("insert or replace into insiders values (?, ?, ?, ?, ?, ?, ?, ?)",
                    [(x.rcept_no, x.ticker, x.day.isoformat(), x.kind, x.who, x.change, x.rate, x.rate_chg)
                     for x in ins])  # fmt: skip
    print(f"  지분 보고 {len(ins)}건 (임원·주요주주 · 5% 대량보유)")
    print(f"공시 {len(ds)}건 (최근 {DISCLOSURE_DAYS}일) · DART {dart.calls}콜")

    for sid, name in sources.MACRO.items():
        pts = sources.ecos(sid, today - timedelta(days=MACRO_DAYS), today)
        con.executemany("insert or replace into macro values (?, ?, ?)",
                        [(sid, d.isoformat(), v) for d, v in pts])  # fmt: skip
        print(f"{name} {len(pts)}일")

    for sid, name in sources.INDEX.items():
        pts = sources.ecos(sid, date(1957, 1, 1), today, "M")
        con.executemany("insert or replace into macro values (?, ?, ?)", [(sid, d.isoformat(), v) for d, v in pts])
        print(f"{name} 주가지수 {len(pts)}달 (OECD)")

    if sources.price_dev():  # ⚠️ 개발 중 개인용만 — 서버에선 꺼짐 (data-rights §4)
        n = 0
        for t in tickers:
            pts = sources.prices(t, today - timedelta(days=370))
            con.executemany("insert or replace into prices values (?, ?, ?)", [(t, d.isoformat(), v) for d, v in pts])
            n += len(pts)
        print(f"주가 {n}행 (개발용 · 개인용만)")

    hs = [h for y in (today.year, today.year + 1) for h in sources.holidays(y)]
    con.executemany("insert or replace into holidays values (?, ?)", [(d.isoformat(), n) for d, n in hs])
    print(f"공휴일 {len(hs)}일 ({today.year}~{today.year + 1})")

    n = 0
    for t, name in picked if sources.news_dev() else []:  # 서버에선 꺼짐 — NEWS_DEV=1 인 내 컴퓨터에서만
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
    print(f"뉴스 {n}건 (개발용 · 개인용만)" if sources.news_dev() else "뉴스 꺼짐 (NEWS_DEV 없음)")
    con.commit()


if __name__ == "__main__":
    main(date.today())
