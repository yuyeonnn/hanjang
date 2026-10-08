"""1단계 1주차 — 받기의 순수 부분과 저장의 멱등을 고정한다. 외부 API 는 부르지 않는다."""

from datetime import date

from hanjang import collect, db, sources


def test_universe_file_has_100_common_stocks():
    rows = sources.kospi_universe()
    assert len(rows) == 100 and ("005930", "삼성전자") in rows
    assert all(t.isdigit() and len(t) == 6 and t.endswith("0") and n for t, n in rows)  # 보통주만 (우선주는 끝자리 5)


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


def test_schedule_reads_dates_from_exchange_forms():
    """거래소 서식 공시 → 앞으로의 일정. 날짜가 「-」인 칸은 일정이 없다. 자회사 공시는 그 회사 일정이 아니다."""
    ir = "기업설명회(IR) 개최(안내공시)\n1. 일시 및 장소\n일시\n2026-10-28\n16:00\n3. 개최목적\n2026년 3분기 경영실적 발표\n7. 결정일자\n2026-10-07"
    assert sources.parse_schedule("기업설명회(IR)개최(안내공시)", ir) == [(date(2026, 10, 28), "EARNINGS", "실적 발표")]
    agm = "1. 구분\n임시주주총회\n2. 일시\n2026-11-20\n10:00\n4. 의결권행사기준일\n2026-10-19"
    assert sources.parse_schedule("주주총회소집결의", agm) == [(date(2026, 11, 20), "AGM", "임시 주총")]
    div = "6. 배당기준일\n2026-09-11\n7. 배당금지급 예정일자\n-\n8. 주주총회 개최여부\n미개최\n10. 이사회결의일(결정일)\n2026-08-27"
    assert sources.parse_schedule("현금ㆍ현물배당결정", div) == [(date(2026, 9, 11), "DIVIDEND", "배당 기준일")]
    assert sources.parse_schedule("현금ㆍ현물배당결정(자회사의 주요경영사항)", div) == []
    assert sources.parse_schedule("단일판매ㆍ공급계약체결", div) == []
