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

    def doc(self, cik, accn, doc):
        if "13G" in doc or "13D" in doc:  # 하나는 엔비디아가 대상, 하나는 남의 회사가 대상
            issuer = cik if accn.endswith("1") else 999
            return f"<issuerCik>{issuer:010d}</issuerCik><reportingPersonName>Vanguard Group Inc</reportingPersonName><classPercent>8.9</classPercent><eventDateRequiresFilingThisStatement>09/30/2026</eventDateRequiresFilingThisStatement><typeOfReportingPerson>IA</typeOfReportingPerson>"
        return "<p>Item 8.01 Other Events. The Board approved a new $50 billion share repurchase program.</p>"

    def _get(self, url):  # 8-K 첨부(보도자료)
        class R:
            text = ('<a href="/ex.htm">ex.htm</a></td><td>EX-99.1</td>' if url.endswith("-index.htm")
                    else "<p>Revenue was $46.7 billion. Net income was $26.4 billion.</p>")
        return R()

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


def test_us_facts_use_dollars_with_won_in_brackets_and_company_months(monkeypatch):
    from hanjang import notes
    monkeypatch.setattr(us, "universe", lambda: [("NVDA", "엔비디아"), ("AAPL", "애플")])
    con = db.connect(":memory:")
    us.main(date(2026, 10, 9), con, FakeSec())
    con.execute("insert into macro values ('ECOS:731Y003:0000003', '2026-10-08', 1338.5)")
    fs = {f["id"]: f for f in notes.facts(con, "NVDA", date(2026, 10, 9))}
    assert fs["F1"]["text"].startswith("2025년 2월~2026년 1월 매출 2,159억 달러(전년보다 +65.5%) (약 289.0조원 · 10월 8일 환율 1,338.5원 기준)")
    assert fs["F1"]["slots"]["원화"] == "약 289.0조원" and fs["F1"]["url"].endswith("-index.htm") and "sec.gov" in fs["F1"]["url"]
    assert fs["F5"]["slots"]["백원당"] == "60달러" and "100달러어치" in fs["F5"]["text"]
    assert (fs["F8"]["slots"]["분기"], fs["F8"]["slots"]["달"], fs["F8"]["slots"]["백원당"]) == ("2026년 5~7월", "회사 기준 2분기", "66달러")
    assert fs["F9"]["slots"]["기간"] == "2026년 2~7월" and fs["F13"]["slots"]["값"] == "2.46달러" and fs["F14"]["slots"]["자사주매입"] == "401억 달러"
    assert fs["F3"]["tone"] == 0 and "빚이유" not in fs["F3"]["slots"]  # 미국 부채비율은 판단하지 않는다 · 낮으면 이유도 없다
    assert notes.mend("중간값은 26달러이라서 높아요. 배당 10억 달러이에요.") == "중간값은 26달러라서 높아요. 배당 10억 달러예요."
    a = {f["id"]: f for f in notes.facts(con, "AAPL", date(2026, 10, 9))}
    assert a["F1"]["slots"]["연도"] == "2024년 10월~2025년 9월" and "주식을 많이 사들여" in a["F3"]["slots"]["빚이유"]
    assert notes.won(123_456_789_000) == "1,235억원" and notes._MARKET["per"] == "원"  # 끝나면 국내로 되돌아간다


def test_8k_items_map_to_our_kinds_without_ai():
    assert us.classify_8k("2.02,9.01") == ("EARNINGS", 2, 0, "실적 발표 (8-K 2.02)")
    assert us.classify_8k("4.02,2.02") [0:3] == ("RESTATEMENT", 3, -1)  # 무거운 번호가 이긴다
    assert us.classify_8k("1.01,2.03,9.01")[0] == "MAJOR_CONTRACT" and us.classify_8k("3.01")[2] == -1
    assert us.needs_text("2.02,7.01,9.01") and not us.needs_text("1.01,2.03") and us.needs_text("7.01,8.01,9.01") and us.needs_text("5.02")
    assert us.classify_8k("2.02,9.01", "announced vehicle production and deliveries for the third quarter")[3] == "판매·인도 대수 알림 (8-K 2.02)"  # 테슬라
    assert us.member_name("nvda:ProfessionalVisualizationMember") == "전문가용 그래픽" and us.member_name("x:CloudPlatformSegmentMember") == "Cloud Platform"
    assert us.classify_8k("8.01,9.01", "declared a quarterly dividend of $0.26 per share")[:2] == ("DIVIDEND", 2)
    assert us.classify_8k("7.01", "new share repurchase program")[:3] == ("BUYBACK", 3, 1)
    assert us.classify_8k("5.02", "appointed Chief Financial Officer")[0] == "EXEC" and us.classify_8k("5.02", "director resigned")[1] == 1
    x = us.parse_13dg("<issuerCik>0001045810</issuerCik><reportingPersonName>JPMORGAN CHASE &amp; CO.</reportingPersonName><classPercent>11.0</classPercent>"
                      "<eventDateRequiresFilingThisStatement>09/30/2026</eventDateRequiresFilingThisStatement><typeOfReportingPerson>HC</typeOfReportingPerson>")
    assert x == {"issuer": 1045810, "who": "JPMORGAN CHASE & CO.", "rate": 11.0, "day": "2026-09-30", "person": "HC"}


def test_us_disclosures_and_insiders_become_note_facts(monkeypatch):
    from hanjang import notes
    monkeypatch.setattr(us, "universe", lambda: [("NVDA", "엔비디아")])
    con = db.connect(":memory:")
    s = load("sub_NVDA.json")
    r = s["filings"]["recent"]
    # 13G 두 장을 끼워 넣는다 — 끝자리 1 은 엔비디아가 대상, 2 는 남의 회사
    for accn in ("0000000000-26-000001", "0000000000-26-000002"):
        r["accessionNumber"].insert(0, accn); r["filingDate"].insert(0, "2026-10-01"); r["acceptanceDateTime"].insert(0, "2026-10-01T20:00:00.000Z")
        r["form"].insert(0, "SCHEDULE 13G/A"); r["items"].insert(0, ""); r["primaryDocument"].insert(0, "xslSCHEDULE_13G_X02/primary_doc.xml")
    fake = FakeSec()
    monkeypatch.setattr(fake, "submissions", lambda cik: s)
    us.main(date(2026, 10, 9), con, fake)
    kinds = dict(con.execute("select title, code from disclosures where ticker = 'NVDA' and importance >= 2"))
    assert kinds.get("실적 발표 (8-K 2.02)") == "EARNINGS" and any(c == "BUYBACK" for c in kinds.values())
    assert con.execute("select who, rate from insiders where kind = '5%'").fetchall() == [("Vanguard Group Inc", 8.9)]  # 남의 회사 보고는 뺐다
    assert ("0000000000-26-000002",) in con.execute("select accession from skipped").fetchall()  # 다시 열지 않게 적어 둔다
    fs = {f["id"]: f for f in notes.facts(con, "NVDA", date(2026, 10, 9))}
    d = next(f for f in fs.values() if f["id"].startswith("D") and f["slots"]["종류"] == "실적")
    assert "지난 분기 실적을 발표했어요" in d["slots"]["무슨일"] and "sec.gov" in d["url"]
    assert "시장에서 산 보고" in fs["I1"]["text"] and "Vanguard" in fs["I2"]["text"]


def test_outlook_quotes_must_be_in_the_release_and_are_said_in_korean():
    src = ("NVIDIA's outlook for the third quarter of fiscal 2027 is as follows: Revenue is expected to be $108.0 billion, plus or minus 2%. "
           "GAAP and non-GAAP gross margins are expected to be 74.0%, plus or minus 50 basis points.")
    j = {"period": "third quarter of fiscal 2027", "items": [
        {"metric": "revenue", "low": 108.0, "high": 108.0, "plus_minus": 2, "plus_minus_unit": "percent", "unit": "billion", "quote": "Revenue is expected to be $108.0 billion, plus or minus 2%."},
        {"metric": "gross_margin", "low": 74.0, "high": 74.0, "plus_minus": 50, "plus_minus_unit": "bp", "unit": "percent", "quote": "GAAP and non-GAAP gross margins are expected to be 74.0%, plus or minus 50 basis points."},
        {"metric": "eps", "low": 9.9, "high": 9.9, "plus_minus": 0, "plus_minus_unit": "none", "unit": "dollars", "quote": "EPS is expected to be $9.90."}]}  # 원문에 없는 인용
    got = us.check_outlook(j, src)
    assert [x["metric"] for x in got["items"]] == ["revenue", "gross_margin"]
    assert [us.say_outlook(x) for x in got["items"]] == ["1,080억 달러(±2%)", "74.0%(±0.5%p)"]
    assert us.say_outlook({"low": 61.5, "high": 61.5, "plus_minus": 1.5, "plus_minus_unit": "same", "unit": "billion"}) == "615억 달러(±15억 달러)"
    assert us.say_outlook({"low": 16.0, "high": 18.0, "plus_minus": 0, "plus_minus_unit": "none", "unit": "percent"}) == "16.0~18.0%"
    assert us.say_outlook({"low": 85.95, "high": 85.95, "plus_minus": 0, "plus_minus_unit": "none", "unit": "percent"}) == "85.95%"  # 반올림하지 않는다
    assert us.say_outlook({"low": 2.31, "high": 2.31, "plus_minus": 0, "plus_minus_unit": "none", "unit": "billion"}) == "23.1억 달러"
