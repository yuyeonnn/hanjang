"""주간 노트 만들기 ① 받기 (PRD §5.2). `python -m hanjang.collect` — 다시 돌려도 중복 없음."""

import sqlite3
import sys
from datetime import date, timedelta

from hanjang import db, sources

DISCLOSURE_DAYS = 90
MACRO_DAYS = 400  # 민감도(250거래일)에 넉넉히 — 쓰는 건 시세를 산 뒤


def save_universe(con: sqlite3.Connection, picked: list[tuple[str, str]], corps: dict[str, str],
                  listed: list[tuple[str, str]] = ()):
    """새로 고른 종목만 active. 빠진 종목은 지우지 않고 active=0 (ERD stocks).
    listed = 상장 회사 전체 — 검색·담기용으로 active=0 으로 넣어 둔다. 누가 담으면 다음 받기부터 active."""
    con.executemany("insert into stocks (ticker, name, corp_code, active) values (?, ?, ?, 0) on conflict(ticker) do update set"
                    " name = excluded.name, corp_code = excluded.corp_code", [(t, n, corps.get(t)) for t, n in listed])  # fmt: skip
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


def save_ipos(con: sqlite3.Connection, dart: "sources.Dart", today: date) -> int:
    """공모주 청약·상장 일정 — 신고서가 정정되면 새 값으로. 상장 예정일은 투자설명서 원문에서, 아직 모르는 것만 다시 연다."""
    xs = dart.ipos(today - timedelta(days=DISCLOSURE_DAYS), today)
    con.executemany(
        "insert into ipos (corp_code, rcept_no, name, sub_start, sub_end, pay_date, price, total, lead, uses) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " on conflict(corp_code) do update set rcept_no = excluded.rcept_no, name = excluded.name, sub_start = excluded.sub_start,"
        " sub_end = excluded.sub_end, pay_date = excluded.pay_date, price = excluded.price, total = excluded.total,"
        " lead = excluded.lead, uses = excluded.uses",
        [(x.corp_code, x.rcept_no, x.name, x.sub_start.isoformat(), x.sub_end.isoformat(), x.pay and x.pay.isoformat(),
          x.price, x.total, x.lead, x.uses) for x in xs])  # fmt: skip
    # ponytail: 상장일을 못 찾은 공모는 청약 뒤 2주까지 매일 원문을 다시 연다 (하루 열 콜 남짓)
    for cc, rno in con.execute("select corp_code, rcept_no from ipos where list_date is null and sub_end >= ?",
                               ((today - timedelta(days=14)).isoformat(),)).fetchall():  # fmt: skip
        if d := sources.parse_listing_day(dart.doc_text(rno)):
            con.execute("update ipos set list_date = ? where corp_code = ?", (d.isoformat(), cc))
    return len(xs)


def save_news(con: sqlite3.Connection, picked: list[tuple[str, str]], today: date, days: int = 10) -> int:
    """회사 뉴스룸 RSS + 언론사 RSS 에서 우리 종목 이름이 든 것만 — 제목·요약문·링크 (본문 없음). 피드 하나가 막혀도 나머지는 받는다."""
    since = (today - timedelta(days=days)).isoformat()
    rows: list[tuple] = []

    def grab(url, press, keep):
        try:
            items = sources.fetch_rss(url, press)
        except Exception as e:  # noqa: BLE001
            print(f"  소식 실패 {press}: {type(e).__name__}", file=sys.stderr)
            return
        rows.extend((x.url, t, x.published.date().isoformat(), x.press, x.title, x.summary)
                    for x in items for t in keep(x) if x.published.date().isoformat() >= since)

    for url, press in sources.PRESS_FEEDS.items():
        grab(url, press, lambda x: [t for t, name in picked if sources.mentions(name, x.title)])
    rooms = sources.newsrooms()
    for t, name in picked:
        if t in rooms:
            grab(rooms[t], f"{name} 뉴스룸", lambda x, t=t: [t])
    con.executemany("insert or ignore into news (url, ticker, date, press, title, summary) values (?, ?, ?, ?, ?, ?)", rows)
    return len(rows)


def main(today: date) -> None:
    con = db.connect()
    # 문장마다 바로 저장 — 받기는 몇 분 걸려서, 끝에 한 번 저장하면 그동안 화면이 DB 에 못 써서 오류가 난다 (2026-10-08 사이트 500)
    con.isolation_level = None
    dart = sources.Dart()
    # 노트를 쓰는 종목 = universe.txt(코스피 큰 회사 100곳) + 누군가 담은 종목(코스닥 포함). 나머지 상장사는 검색에만
    listed = dart.listed(today)
    picked = sources.kospi_universe()
    held = {t for (t,) in con.execute("select distinct ticker from holdings")} - {t for t, _ in picked}
    names = dict(con.execute("select ticker, name from stocks")) | dict(listed)  # 막 상장해 정기보고서가 아직 없는 회사도 담겼으면 쓴다
    extra = [(t, names[t]) for t in sorted(held) if t in names and not t.startswith("ETF")]  # ETF 는 etf.py 가 따로
    picked += extra
    tickers = [t for t, _ in picked]
    save_universe(con, picked, dart.corps(), listed)
    print(f"종목 {len(tickers)}개 (universe.txt + 담은 종목 {len(extra)}개) · 상장사 {len(listed)}곳")

    fin = [f for y in range(today.year - 1, today.year - 6, -1) for f in dart.financials(tickers, y)]  # 5년 — 노트 위 차트
    save_financials(con, fin)
    print(f"재무 {len(fin)}행 ({today.year - 5}~{today.year - 1})")

    qs = [x for y in (today.year, today.year - 1) for x in dart.quarters(tickers, y)]  # 분기 실적 — 올해 흐름
    con.executemany("insert or replace into quarters values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [(x.ticker, x.year, x.q, x.revenue, x.operating_income, x.revenue_prev, x.op_prev, x.revenue_ytd, x.op_ytd,
                      x.revenue_ytd_prev, x.op_ytd_prev, x.rcept_no, x.basis) for x in qs])  # fmt: skip
    print(f"분기 실적 {len(qs)}줄 ({today.year - 1}~{today.year})")

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
    # 앞으로의 일정 (실적 발표·주총·배당 기준일·지급일) — 공시 원문을 한 번 열어 날짜를 읽는다
    # ponytail: 날짜가 없거나 같은 날 같은 일정이 이미 있는 공시는 매일 다시 연다(하루 수십 콜). 많아지면 「읽음」 칸을 둔다
    todo = [(r, t, title) for r, t, title in con.execute(
        "select rcept_no, ticker, title from disclosures where date >= ? and rcept_no not in"
        " (select rcept_no from events where rcept_no is not null)", (lo.isoformat(),)) if sources.has_schedule(title)]  # fmt: skip
    evs = [(t, d.isoformat(), kind, what, r) for r, t, title in todo for d, kind, what in sources.parse_schedule(title, dart.doc_text(r))]
    con.executemany("insert or replace into events values (?, ?, ?, ?, ?)", evs)
    print(f"  일정 {len(evs)}건 (공시 {len(todo)}건에서)")
    print(f"공시 {len(ds)}건 (최근 {DISCLOSURE_DAYS}일) · DART {dart.calls}콜")
    print(f"공모주 {save_ipos(con, dart, today)}건 (증권신고서 · 지난 {DISCLOSURE_DAYS}일)")

    con.execute("delete from macro where series_id = 'ECOS:731Y001:0000001'")  # 서울외국환중개 작성 — 예전에 받은 것 지움
    for sid, name in sources.MACRO.items():
        pts = sources.ecos(sid, today - timedelta(days=MACRO_DAYS), today)
        con.executemany("insert or replace into macro values (?, ?, ?)",
                        [(sid, d.isoformat(), v) for d, v in pts])  # fmt: skip
        print(f"{name} {len(pts)}일")

    for sid, name in sources.INDEX.items():
        pts = sources.ecos(sid, date(1957, 1, 1), today, "M")
        con.executemany("insert or replace into macro values (?, ?, ?)", [(sid, d.isoformat(), v) for d, v in pts])
        print(f"{name} 주가지수 {len(pts)}달 (OECD)")

    for sid in sources.RATES:
        pts = sources.ecos(sid, date(2000, 1, 1), today, "M")
        con.executemany("insert or replace into macro values (?, ?, ?)", [(sid, d.isoformat(), v) for d, v in pts])
    print(f"금리 {len(sources.RATES)}가지 (월평균 · 한국은행)")

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

    print(f"소식 {save_news(con, picked, today)}건 (회사 뉴스룸 · 언론사 RSS — 제목·요약문만)")
    con.commit()


if __name__ == "__main__":
    main(date.today())
