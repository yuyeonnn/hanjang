"""1단계 1주차 — 받기의 순수 부분과 저장의 멱등을 고정한다. 외부 API 는 부르지 않는다."""

from datetime import date

from hanjang import collect, db, sources


def test_universe_keeps_kospi_common_by_mktcap():
    rows = [
        {"srtnCd": "005930", "itmsNm": "삼성전자", "mrktCtg": "KOSPI", "mrktTotAmt": "900"},
        {"srtnCd": "005935", "itmsNm": "삼성전자우", "mrktCtg": "KOSPI", "mrktTotAmt": "999"},
        {"srtnCd": "247540", "itmsNm": "에코프로비엠", "mrktCtg": "KOSDAQ", "mrktTotAmt": "998"},
        {"srtnCd": "000660", "itmsNm": "SK하이닉스", "mrktCtg": "KOSPI", "mrktTotAmt": "1000"},
    ]
    assert sources.top_kospi(rows, 5) == [("000660", "SK하이닉스"), ("005930", "삼성전자")]


def test_corps_does_not_steal_next_code():
    xml = ("<result><list><corp_code>001</corp_code><stock_code> </stock_code></list>"
           "<list><corp_code>002</corp_code><stock_code>005930</stock_code></list></result>")
    assert sources.parse_corps(xml) == {"005930": "002"}


def test_financials_prefer_consolidated():
    def row(fs, acc, amt):
        return {"stock_code": "005930", "fs_div": fs, "account_nm": acc,
                "thstrm_amount": amt, "rcept_no": "20260310002820"}
    rows = [row("CFS", "매출액", "333,600"), row("OFS", "매출액", "200,000"),
            row("CFS", "부채 총계", "10"), row("CFS", "자본총계", "-"),
            row("CFS", "영업이익(손실)", "7")]  # 금융회사 계정 이름
    [f] = sources.parse_financials(rows, 2025)
    assert (f.revenue, f.liabilities, f.equity, f.operating_income) == (333600, 10, None, 7)


def test_news_strips_press_tail():
    xml = ("<rss><channel><item><title>삼전 최대 실적 - 마켓인 - 마켓인</title><link>https://n/1</link>"
           "<pubDate>Sun, 05 Oct 2026 01:00:00 GMT</pubDate><source>마켓인</source></item>"
           "</channel></rss>")
    [n] = sources.parse_news(xml)
    assert (n.title, n.press, n.published.date()) == ("삼전 최대 실적", "마켓인", date(2026, 10, 5))


def test_ecos_empty_and_values():
    assert sources.parse_ecos({"RESULT": {"CODE": "INFO-200"}}, "x") == []
    body = {"StatisticSearch": {"row": [{"TIME": "20261002", "DATA_VALUE": "1390.5"},
                                        {"TIME": "20261003", "DATA_VALUE": ""}]}}
    assert sources.parse_ecos(body, "x") == [(date(2026, 10, 2), 1390.5)]


def test_saving_twice_keeps_one_row_and_ai_fields():
    con = db.connect(":memory:")
    collect.save_universe(con, [("005930", "삼성전자")], {"005930": "00126380"})
    d = sources.Disclosure("20260821000616", "005930", date(2026, 8, 21), "자기주식취득결정")
    collect.save_disclosures(con, [d])
    con.execute("update disclosures set code = 'BUYBACK'")
    collect.save_disclosures(con, [d])  # 다시 받아도
    assert con.execute("select count(*), max(code) from disclosures").fetchone() == (1, "BUYBACK")
    collect.save_universe(con, [("000660", "SK하이닉스")], {})  # 빠진 종목은 지우지 않고 끈다
    assert dict(con.execute("select ticker, active from stocks")) == {"005930": 0, "000660": 1}
