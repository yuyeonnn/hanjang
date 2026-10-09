"""미국 주식 받기 — SEC 재무(XBRL)·공시 목록·Form 4 를 잘라 둔 실제 응답으로. 외부 호출 없음."""

import json
from datetime import date
from pathlib import Path

from hanjang import db, us

FX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))


def test_fiscal_year_and_quarter_follow_each_companys_calendar():
    assert us.fiscal_year(date(2026, 1, 25), "0131") == 2026 and us.fiscal_year(date(2026, 4, 26), "0131") == 2027  # 엔비디아
    assert us.fiscal_year(date(2025, 9, 27), "0926") == 2025 and us.fiscal_year(date(2025, 12, 27), "0926") == 2026  # 애플
    assert us.fiscal_year(date(2026, 1, 3), "0103") == 2025 and us.fiscal_year(date(2026, 3, 29), "0103") == 2026  # 존슨앤드존슨(12월 결산)
    assert us.fiscal_year(date(2027, 1, 2), "1231") == 2026
    assert [us.quarter_no(d, "0131") for d in (date(2026, 4, 26), date(2026, 7, 26), date(2026, 10, 25), date(2027, 1, 31))] == [1, 2, 3, 4]
    assert us.quarter_no(date(2025, 12, 27), "0926") == 1 and us.quarter_no(date(2026, 3, 29), "0103") == 1


def test_nvidia_quarters_add_up_to_the_year_and_fy_label_is_ignored():
    f = load("facts_NVDA.json")
    fin = {r["fiscal_year"]: r for r in us.financial_rows(f, "0131")}
    assert fin[2026]["end"] == "2026-01-25" and fin[2026]["revenue"] == 215_938_000_000 and fin[2026]["operating_income"] == 130_387_000_000
    assert fin[2026]["liabilities"] == 49_510_000_000 and fin[2026]["eps"] == 4.9 and fin[2026]["currency"] == "USD"
    qs = {(r["fiscal_year"], r["q"]): r for r in us.quarter_rows(f, "0131")}
    q2 = qs[(2027, 2)]
    assert (q2["start"], q2["end"], q2["revenue"], q2["operating_income"], q2["revenue_ytd"], q2["eps"]) == (
        "2026-04-27", "2026-07-26", 96_221_000_000, 63_734_000_000, 177_837_000_000, 2.46)
    q4 = qs[(2026, 4)]
    assert q4["basis"] == "연간−9개월" and q4["end"] == "2026-01-25" and q4["revenue_ytd"] == 215_938_000_000
    assert sum(qs[(2026, q)]["revenue"] for q in (1, 2, 3, 4)) == fin[2026]["revenue"]  # 4분기 = 연간 − 9개월
    assert sum(qs[(2026, q)]["operating_income"] for q in (1, 2, 3, 4)) == fin[2026]["operating_income"]


def test_apple_and_bank_fall_back_to_other_revenue_tags():
    a = load("facts_AAPL.json")
    fin = {r["fiscal_year"]: r for r in us.financial_rows(a, "0926")}
    assert fin[2025]["end"] == "2025-09-27" and fin[2025]["revenue"] > 300_000_000_000  # Revenues 태그는 2018년에 끊겼다 — 둘째 태그
    qs = {(r["fiscal_year"], r["q"]): r for r in us.quarter_rows(a, "0926")}
    assert qs[(2026, 1)]["end"] == "2025-12-27" and qs[(2026, 3)]["revenue"] == 109_417_000_000
    j = load("facts_JPM.json")
    qs = {(r["fiscal_year"], r["q"]): r for r in us.quarter_rows(j, "1231")}
    q = qs[(2026, 2)]
    assert (q["revenue"], q["operating_income"], q["eps"]) == (57_347_000_000, None, 7.7)  # 은행 — 이자 뺀 수익, 영업이익 없음
    fl = {(r["start"], r["end"]): r for r in us.flow_rows(j)}
    assert fl[("2026-01-01", "2026-06-30")]["buyback"] == 15_113_000_000 and fl[("2026-01-01", "2026-06-30")]["months"] == 6


def test_filings_are_dated_in_korean_time_and_form4_keeps_only_market_trades():
    s = load("sub_NVDA.json")
    rows = {r["accession"]: r for r in us.filing_rows(s, date(2026, 8, 1))}
    r = rows["0001045810-26-000073"]  # 8-K 2.02 — 미국 8/26 저녁 접수 = 한국 8/27 새벽
    assert (r["form"], r["items"], r["date"], r["filed_us"]) == ("8-K", "2.02,9.01", "2026-08-27", "2026-08-26")
    assert all(x["form"] in us.FORMS for x in rows.values()) and us.form4_list(s, date(2026, 9, 1))
    xml = ("<ownershipDocument><periodOfReport>2026-09-22</periodOfReport><reportingOwner><reportingOwnerRelationship>"
           "<isDirector>0</isDirector><isOfficer>1</isOfficer><officerTitle>EVP, General Counsel and Sec</officerTitle></reportingOwnerRelationship></reportingOwner>"
           "<aff10b5One>1</aff10b5One><nonDerivativeTable>"
           "<nonDerivativeTransaction><transactionDate><value>2026-09-22</value></transactionDate><transactionCoding><transactionCode>S</transactionCode></transactionCoding>"
           "<transactionAmounts><transactionShares><value>12483</value></transactionShares><transactionPricePerShare><value>222.1932</value></transactionPricePerShare></transactionAmounts></nonDerivativeTransaction>"
           "<nonDerivativeTransaction><transactionCoding><transactionCode>F</transactionCode></transactionCoding><transactionAmounts><transactionShares><value>999</value></transactionShares></transactionAmounts></nonDerivativeTransaction>"
           "</nonDerivativeTable></ownershipDocument>")
    x = us.parse_form4(xml)
    assert x == {"who": "EVP, General Counsel and Sec", "bought": 0.0, "sold": 12483.0, "price": 222.19, "planned": True, "day": "2026-09-22"}
    assert us.parse_form4(xml.replace("<transactionCode>S", "<transactionCode>A")) is None  # 보상만이면 거래가 아니다


class FakeSec:
    calls = 0

    def tickers(self):
        return {"NVDA": (1045810, "NVIDIA CORP"), "AAPL": (320193, "Apple Inc.")}

    def submissions(self, cik):
        return load("sub_NVDA.json") if cik == 1045810 else load("sub_AAPL.json")

    def facts(self, cik):
        return load("facts_NVDA.json") if cik == 1045810 else load("facts_AAPL.json")

    def form4(self, cik, accn, doc):
        return "<ownershipDocument><officerTitle>CEO</officerTitle><nonDerivativeTransaction><transactionCode>P</transactionCode><transactionShares><value>10</value></transactionShares></nonDerivativeTransaction></ownershipDocument>"


def test_main_saves_us_rows_hidden_from_search(monkeypatch):
    monkeypatch.setattr(us, "universe", lambda: [("NVDA", "엔비디아"), ("AAPL", "애플"), ("XXXX", "없는회사")])
    con = db.connect(":memory:")
    us.main(date(2026, 10, 9), con, FakeSec())
    assert dict(con.execute("select ticker, market from stocks")) == {"NVDA": "US", "AAPL": "US"}
    assert con.execute("select active, cik, sic, fye from stocks where ticker = 'NVDA'").fetchone() == (0, 1045810, "3674", "0131")
    assert con.execute("select count(*) from financials where ticker = 'NVDA' and currency = 'USD'").fetchone()[0] >= 3
    (q,) = con.execute("select revenue_prev from quarters where ticker = 'NVDA' and year = 2027 and q = 2").fetchone()
    assert q == con.execute("select revenue from quarters where ticker = 'NVDA' and year = 2026 and q = 2").fetchone()[0]  # 1년 전 같은 분기
    assert con.execute("select count(*) from filings where form = '8-K'").fetchone()[0] > 0
    assert con.execute("select who, change, planned from insiders where ticker = 'NVDA' limit 1").fetchone() == ("CEO", 10.0, 0)
    from hanjang import web
    assert "NVDA" not in web.App(con, "s").stocks_js()  # 화면은 5주차 — 아직 숨긴다
