"""미국 주식 받기 — SEC EDGAR 를 DART 처럼 (docs/stage3-us.md 1주차).
세 창구(티커 표 · 회사별 공시 목록 · XBRL 재무)와 Form 4 원문(XML)만. 키 없음, 조건은 User-Agent 와 초당 10번 아래 (data-rights §6).
재무는 기간(start·end)으로만 판단한다 — fy/fp 칸은 「그 숫자가 실린 보고서」의 것이라 믿지 않는다. 4분기 = 연간 − 9개월 누적."""

import json
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import httpx

from hanjang import db
from hanjang.sources import ROOT, CACHE, env

UNIVERSE = ROOT / "hanjang" / "universe_us.txt"
KST = timezone(timedelta(hours=9))  # 한국은 서머타임이 없다 — 시간대 자료 없이
# 같은 뜻의 태그 — 기간마다 앞에 있는 것부터 찾는다 (애플은 최근 분기가 둘째 태그에만, 은행은 넷째에만)
REVENUE = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractWithCustomerIncludingAssessedTax",  # 크라우드스트라이크
           "SalesRevenueNet", "RevenuesNetOfInterestExpense")
TAGS = {"revenue": REVENUE, "operating_income": ("OperatingIncomeLoss",), "net_income": ("NetIncomeLoss",),
        "eps": ("EarningsPerShareDiluted",), "liabilities": ("Liabilities",), "equity": ("StockholdersEquity",),
        "buyback": ("PaymentsForRepurchaseOfCommonStock",), "dividends": ("PaymentsOfDividends", "PaymentsOfDividendsCommonStock"),
        "sbc": ("ShareBasedCompensation",)}  # fmt: skip
FORMS = ("10-K", "10-Q", "8-K", "DEF 14A", "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A", "SCHEDULE 13D", "SCHEDULE 13D/A", "SCHEDULE 13G", "SCHEDULE 13G/A")
DAYS = 400  # 공시 목록은 이만큼 (10-K 한 번은 들어오게) · Form 4 는 90일


def universe() -> list[tuple[str, str]]:
    rows = (ln.split(maxsplit=1) for ln in UNIVERSE.read_text(encoding="utf-8").splitlines() if ln and not ln.startswith("#"))
    return [(t, n.strip()) for t, n in rows]


class Edgar:
    """SEC 호출 — User-Agent 에 운영자 메일(.env SMTP_USER), 초당 8번 아래로 쉰다."""

    def __init__(self):
        self.ua = f"Hanjang {env().get('SMTP_USER', 'psiobinq@gmail.com')}"
        self.calls = 0
        self._tickers = None

    def _get(self, url: str) -> httpx.Response:
        for wait in (2, 10, None):
            r = httpx.get(url, headers={"User-Agent": self.ua, "Accept-Encoding": "gzip"}, timeout=60)
            self.calls += 1
            time.sleep(0.13)
            if r.status_code in (429, 503) and wait:
                time.sleep(wait)
                continue
            return r
        return r

    def tickers(self) -> dict[str, tuple[int, str]]:
        """티커 → (CIK, 영어 이름). 하루 캐시."""
        if self._tickers is None:
            f = CACHE / "sec_tickers.json"
            if not f.exists() or time.time() - f.stat().st_mtime > 86_400:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(self._get("https://www.sec.gov/files/company_tickers.json").content)
            self._tickers = {v["ticker"]: (v["cik_str"], v["title"]) for v in json.loads(f.read_text(encoding="utf-8")).values()}
        return self._tickers

    def submissions(self, cik: int) -> dict:
        return self._get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()

    def facts(self, cik: int) -> dict:
        return self._get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json").json()

    def form4(self, cik: int, accession: str, primary: str) -> str:
        """Form 4 원문 XML — primaryDocument 「xslF345X06/wk-form4_….xml」에서 보기용 xsl 폴더를 뗀 파일."""
        name = primary.split("/")[-1]
        return self._get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{name}").text


# --- 파싱 (순수 함수 — 테스트는 잘라 둔 JSON 으로) ---


@dataclass(frozen=True)
class Period:
    start: date | None  # 잔액(부채·자본)은 start 없음
    end: date
    val: float
    accn: str
    filed: str


def series(facts: dict, tags: tuple[str, ...], unit_prefix: str = "USD") -> dict[tuple, Period]:
    """태그들을 합쳐 (start, end) → 값. 같은 기간은 가장 나중에 낸 보고서 값, 같은 보고서면 앞 태그가 이긴다."""
    out: dict[tuple, Period] = {}
    g = facts.get("facts", {}).get("us-gaap", {})
    for tag in tags:
        for unit, rows in g.get(tag, {}).get("units", {}).items():
            if not unit.startswith(unit_prefix):
                continue
            for r in rows:
                if r.get("form", "").split("/")[0] not in ("10-K", "10-Q") or r.get("val") is None:
                    continue
                key = (r.get("start"), r["end"])
                p = Period(date.fromisoformat(r["start"]) if r.get("start") else None, date.fromisoformat(r["end"]), r["val"], r["accn"], r["filed"])
                if key not in out or p.filed > out[key].filed:
                    out[key] = p
    return out


def months(p: Period) -> int | None:
    """기간 길이 — 3·6·9·12 (분기·반기·9개월·연간). 잔액은 None."""
    if not p.start:
        return None
    d = (p.end - p.start).days
    return next((m for m, (lo, hi) in ((3, (75, 100)), (6, (165, 195)), (9, (255, 285)), (12, (350, 380))) if lo <= d <= hi), None)


def fye_month(fye: str) -> int:
    """회계연도가 끝나는 달 — SEC 의 「MMDD」. 달 초(7일 안)에 끝나면 앞 달로 본다(존슨앤드존슨 0103 = 12월 결산)."""
    if not fye or not fye[:4].isdigit():
        return 12
    m, d = int(fye[:2]), int(fye[2:4])
    return (m - 2) % 12 + 1 if d <= 7 else m


def fiscal_year(end: date, fye: str) -> int:
    """기간 끝 → 회계연도(끝나는 해). 52·53주 결산으로 달 초에 끝나는 건 일주일을 빼고 본다.
    엔비디아(0131): 2026-01-25 → 2026, 2026-04-26 → 2027 · 애플(0926): 2025-12-27 → 2026."""
    m, e = fye_month(fye), end - timedelta(days=7)
    return e.year if m == 12 or e.month <= m else e.year + 1


def quarter_no(end: date, fye: str) -> int:
    """회계연도 안의 분기 번호 — 회계연도 끝까지 남은 달로 (0 → 4분기 · 3 → 3분기 · 6 → 2분기 · 9 → 1분기)."""
    left = (fye_month(fye) - (end - timedelta(days=7)).month) % 12
    return 4 - round(left / 3)


def anchors(s: dict) -> dict[tuple, Period]:
    """기간의 기준 — 매출이 있으면 매출, 없으면 순이익 (매출이 아직 없는 회사도 연간·분기가 잡히게)."""
    return {**s["net_income"], **s["revenue"]}


def financial_rows(facts: dict, fye: str) -> list[dict]:
    """연간 — {fiscal_year, start, end, revenue, operating_income, net_income, eps, liabilities, equity, accn}."""
    s = {k: series(facts, v) for k, v in TAGS.items()}
    out = {}
    for (st, en), p in anchors(s).items():
        if months(p) != 12:
            continue
        fy = fiscal_year(p.end, fye)
        rv = s["revenue"].get((st, en))
        row = {"fiscal_year": fy, "start": p.start.isoformat(), "end": p.end.isoformat(), "revenue": rv.val if rv else None, "accn": p.accn, "currency": "USD"}
        for k in ("operating_income", "net_income", "eps"):
            q = s[k].get((st, en))
            row[k] = q.val if q else None
        for k in ("liabilities", "equity"):
            q = s[k].get((None, en))
            row[k] = q.val if q else None
        if fy not in out or p.filed > out[fy]["_filed"]:
            out[fy] = row | {"_filed": p.filed}
    return [dict((k, v) for k, v in r.items() if k != "_filed") for r in sorted(out.values(), key=lambda r: r["fiscal_year"])]


def quarter_rows(facts: dict, fye: str) -> list[dict]:
    """분기 — 3개월 값은 그대로, 4분기는 연간 − 9개월 누적. {fiscal_year, q, start, end, revenue, operating_income, net_income, eps,
    revenue_ytd, op_ytd, accn}. 1년 전 같은 분기(prev)는 저장할 때 우리 표에서 채운다."""
    s = {k: series(facts, v) for k, v in TAGS.items()}
    by_len: dict[int, dict] = {3: {}, 9: {}, 12: {}}
    for key, p in anchors(s).items():
        if (m := months(p)) in by_len:
            by_len[m][key] = p
    rows = {}

    def grab(k, key):
        q = s[k].get(key)
        return q.val if q else None

    for key, p in by_len[3].items():
        fy, q = fiscal_year(p.end, fye), quarter_no(p.end, fye)
        ytd = next((pp for kk, pp in anchors(s).items() if pp.end == p.end and months(pp) == {1: 3, 2: 6, 3: 9, 4: 12}[q]), None)
        rows[(fy, q)] = {"fiscal_year": fy, "q": q, "start": p.start.isoformat(), "end": p.end.isoformat(), "revenue": grab("revenue", key),
                         "operating_income": grab("operating_income", key), "net_income": grab("net_income", key), "eps": grab("eps", key),
                         "revenue_ytd": grab("revenue", (ytd.start.isoformat(), ytd.end.isoformat())) if ytd else None,
                         "op_ytd": grab("operating_income", (ytd.start.isoformat(), ytd.end.isoformat())) if ytd else None,
                         "accn": p.accn, "currency": "USD", "basis": "3개월"}  # fmt: skip
    for key, p in by_len[12].items():  # 4분기 = 연간 − 9개월 (같은 시작일)
        fy = fiscal_year(p.end, fye)
        nine = next((pp for kk, pp in by_len[9].items() if pp.start == p.start), None)
        if not nine or (fy, 4) in rows:
            continue
        k9 = (nine.start.isoformat(), nine.end.isoformat())

        def diff(k):
            a, b = grab(k, key), grab(k, k9)
            return round(a - b, 2) if a is not None and b is not None else None
        rows[(fy, 4)] = {"fiscal_year": fy, "q": 4, "start": (nine.end + timedelta(days=1)).isoformat(), "end": p.end.isoformat(),
                         "revenue": diff("revenue"), "operating_income": diff("operating_income"), "net_income": diff("net_income"), "eps": diff("eps"),
                         "revenue_ytd": grab("revenue", key), "op_ytd": grab("operating_income", key), "accn": p.accn, "currency": "USD", "basis": "연간−9개월"}  # fmt: skip
    return sorted(rows.values(), key=lambda r: (r["fiscal_year"], r["q"]))


def flow_rows(facts: dict) -> list[dict]:
    """주주에게 돌려준 돈·주식 보상 — 누적(ytd)과 연간 그대로. {start, end, months, buyback, dividends, sbc, accn}."""
    s = {k: series(facts, TAGS[k]) for k in ("buyback", "dividends", "sbc")}
    keys = {k for v in s.values() for k in v}
    out = []
    for st, en in sorted(keys, key=lambda k: (k[1], k[0] or "")):
        if not st:
            continue
        ps = [s[k].get((st, en)) for k in ("buyback", "dividends", "sbc")]
        p0 = next(p for p in ps if p)
        if months(p0) is None:
            continue
        out.append({"start": st, "end": en, "months": months(p0), "buyback": ps[0].val if ps[0] else None,
                    "dividends": ps[1].val if ps[1] else None, "sbc": ps[2].val if ps[2] else None, "accn": p0.accn})  # fmt: skip
    return out


def filing_rows(sub: dict, since: date) -> list[dict]:
    """공시 목록 — 우리가 쓰는 서식만. 날짜는 접수 시각(UTC)을 한국 시간으로."""
    r = sub["filings"]["recent"]
    out = []
    for i in range(len(r["form"])):
        if r["form"][i] not in FORMS or r["filingDate"][i] < since.isoformat():
            continue
        at = datetime.fromisoformat(r["acceptanceDateTime"][i].replace("Z", "+00:00")).astimezone(KST)
        out.append({"accession": r["accessionNumber"][i], "form": r["form"][i], "date": at.date().isoformat(), "at": at.isoformat(timespec="minutes"),
                    "items": r["items"][i], "doc": r["primaryDocument"][i], "filed_us": r["filingDate"][i]})  # fmt: skip
    return out


def form4_list(sub: dict, since: date) -> list[tuple[str, str, str]]:
    r = sub["filings"]["recent"]
    return [(r["accessionNumber"][i], r["primaryDocument"][i], r["filingDate"][i]) for i in range(len(r["form"]))
            if r["form"][i] == "4" and r["filingDate"][i] >= since.isoformat()]  # fmt: skip


def parse_form4(xml: str) -> dict | None:
    """Form 4 한 장 → {who, kind, bought, sold, price, planned, day}. 장내 매수(P)·매도(S)만 센다 — 보상(A)·옵션 행사(M)·세금 납부(F)는 거래가 아니다.
    이름은 옮기지 않는다(직위만). planned = 미리 정해 둔 계획(10b5-1)대로 한 거래."""
    def tag(name, src=xml):
        m = re.search(rf"<{name}>\s*(?:<value>)?\s*([^<]*?)\s*(?:</value>)?\s*</{name}>", src, re.S)
        return m.group(1).strip() if m else ""

    title = tag("officerTitle")
    kind = title or ("이사" if tag("isDirector") in ("1", "true") else "10% 주주" if tag("isTenPercentOwner") in ("1", "true") else "임원")
    bought = sold = 0.0
    prices: list[float] = []
    for blk in re.findall(r"<nonDerivativeTransaction>(.*?)</nonDerivativeTransaction>", xml, re.S):
        code = tag("transactionCode", blk)
        if code not in ("P", "S"):
            continue
        n = float(tag("transactionShares", blk) or 0)
        if code == "P":
            bought += n
        else:
            sold += n
        if (pr := tag("transactionPricePerShare", blk)):
            prices.append(float(pr))
    if not bought and not sold:
        return None
    return {"who": kind, "bought": bought, "sold": sold, "price": round(sum(prices) / len(prices), 2) if prices else None,
            "planned": tag("aff10b5One") in ("1", "true"), "day": tag("transactionDate") or tag("periodOfReport")}  # fmt: skip


# --- 저장 ---


def save_company(con: sqlite3.Connection, ticker: str, name: str, cik: int, sub: dict) -> None:
    con.execute("insert into stocks (ticker, name, corp_code, active, market, cik, sic, fye, homepage) values (?, ?, ?, 0, 'US', ?, ?, ?, ?)"
                " on conflict(ticker) do update set name = excluded.name, cik = excluded.cik, sic = excluded.sic, fye = excluded.fye,"
                " homepage = coalesce(stocks.homepage, excluded.homepage)",
                (ticker, name, str(cik), cik, sub.get("sic"), sub.get("fiscalYearEnd"), (sub.get("website") or "").replace("https://", "").replace("http://", "").strip("/") or None))  # fmt: skip


def save_facts(con: sqlite3.Connection, ticker: str, facts: dict, fye: str) -> tuple[int, int, int]:
    fin = financial_rows(facts, fye)
    con.executemany("insert or replace into financials (ticker, fiscal_year, revenue, operating_income, net_income, equity, liabilities, rcept_no, basis,"
                    " period_start, period_end, currency, eps) values (?, ?, ?, ?, ?, ?, ?, ?, 'US-GAAP', ?, ?, ?, ?)",
                    [(ticker, r["fiscal_year"], r["revenue"], r["operating_income"], r["net_income"], r["equity"], r["liabilities"], r["accn"],
                      r["start"], r["end"], r["currency"], r["eps"]) for r in fin])  # fmt: skip
    qs = quarter_rows(facts, fye)
    by = {(r["fiscal_year"], r["q"]): r for r in qs}
    con.executemany("insert or replace into quarters (ticker, year, q, revenue, operating_income, revenue_prev, op_prev, revenue_ytd, op_ytd, revenue_ytd_prev, op_ytd_prev, rcept_no, basis, period_start, period_end, currency, eps) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [(ticker, r["fiscal_year"], r["q"], r["revenue"], r["operating_income"],
                      (p := by.get((r["fiscal_year"] - 1, r["q"]))) and p["revenue"], p and p["operating_income"],
                      r["revenue_ytd"], r["op_ytd"], p and p["revenue_ytd"], p and p["op_ytd"], r["accn"], r["basis"],
                      r["start"], r["end"], r["currency"], r["eps"]) for r in qs])  # fmt: skip
    fl = flow_rows(facts)
    con.executemany("insert or replace into flows values (?, ?, ?, ?, ?, ?, ?, ?)",
                    [(ticker, r["start"], r["end"], r["months"], r["buyback"], r["dividends"], r["sbc"], r["accn"]) for r in fl])  # fmt: skip
    return len(fin), len(qs), len(fl)


def main(today: date, con: sqlite3.Connection | None = None, sec: Edgar | None = None) -> None:
    con, sec = con or db.connect(), sec or Edgar()
    tk = sec.tickers()
    got = {"회사": 0, "연간": 0, "분기": 0, "흐름": 0, "공시": 0, "임원": 0}
    for ticker, name in universe():
        if ticker not in tk:
            print(f"  {ticker} {name}: SEC 티커 표에 없음 — universe_us.txt 를 고친다", file=sys.stderr)
            continue
        cik, _ = tk[ticker]
        sub = sec.submissions(cik)
        if "10-K" not in sub["filings"]["recent"]["form"] and "10-Q" not in sub["filings"]["recent"]["form"]:
            print(f"  {ticker} {name}: 10-K 를 내지 않는 회사(20-F) — 뺀다", file=sys.stderr)
            continue
        save_company(con, ticker, name, cik, sub)
        f, q, fl = save_facts(con, ticker, sec.facts(cik), sub.get("fiscalYearEnd") or "1231")
        rows = filing_rows(sub, today - timedelta(days=DAYS))
        con.executemany("insert or replace into filings values (?, ?, ?, ?, ?, ?, ?, ?)",
                        [(r["accession"], ticker, r["form"], r["date"], r["at"], r["items"], r["doc"], r["filed_us"]) for r in rows])  # fmt: skip
        have = {a for (a,) in con.execute("select rcept_no from insiders where ticker = ?", (ticker,))}
        ins = 0
        for accn, doc, filed in form4_list(sub, today - timedelta(days=90)):
            if accn in have:
                continue
            x = parse_form4(sec.form4(cik, accn, doc))
            if x:
                con.execute("insert or replace into insiders (rcept_no, ticker, date, kind, who, change, rate, rate_chg, planned, price) values (?, ?, ?, ?, ?, ?, null, null, ?, ?)",
                            (accn, ticker, x["day"] or filed, "임원·주요주주", x["who"], x["bought"] - x["sold"], int(x["planned"]), x["price"]))  # fmt: skip
                ins += 1
        con.commit()
        got["회사"] += 1
        for k, v in zip(("연간", "분기", "흐름", "공시", "임원"), (f, q, fl, len(rows), ins)):
            got[k] += v
    print(f"미국 {got} · SEC {sec.calls}콜")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(date.today())
