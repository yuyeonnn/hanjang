from datetime import date

from hanjang import db, gurus

XML = """<?xml version="1.0" encoding="UTF-8"?>
<ns1:informationTable xmlns:ns1="http://www.sec.gov/edgar/document/thirteenf/informationtable" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="x y">
{rows}
</ns1:informationTable>"""
ROW = """<ns1:infoTable><ns1:nameOfIssuer>{n}</ns1:nameOfIssuer><ns1:cusip>{c}</ns1:cusip><ns1:value>{v}</ns1:value>
<ns1:shrsOrPrnAmt><ns1:sshPrnamt>{s}</ns1:sshPrnamt><ns1:sshPrnamtType>SH</ns1:sshPrnamtType></ns1:shrsOrPrnAmt>{pc}</ns1:infoTable>"""


def xml(*rows):
    return XML.format(rows="".join(ROW.format(n=n, c=c, v=v, s=s, pc=f"<ns1:putCall>{pc}</ns1:putCall>" if pc else "") for n, c, v, s, pc in rows))


def test_parse_sums_same_cusip_skips_options_and_fixes_thousands():
    rows = gurus.parse(xml(("APPLE INC", "037833100", 600, 2, ""), ("APPLE INC", "037833100", 300, 1, ""), ("TESLA INC", "88160R101", 999, 3, "Put")))
    assert rows == [("037833100", "APPLE INC", 900, 3)]  # 같은 CUSIP 두 줄은 합치고, 풋옵션은 뺀다
    thousand = gurus.parse(xml(("NATERA INC", "632307104", 864923, 3186306, ""), ("TSMC", "874039100", 281613, 589680, "")))  # 듀케인 — 천 달러
    assert thousand[0][2] == 864923 * 1000


class FakeSec:
    calls = 0

    def submissions(self, cik):
        return {"filings": {"recent": {"form": ["4", "13F-HR"], "accessionNumber": ["x", "0001-26-1"], "reportDate": ["", "2026-06-30"], "filingDate": ["", "2026-08-14"]}}}

    def _get(self, url):
        class R:
            text = xml(("ALPHABET INC", "02079K305", 600, 2, ""), ("ALPHABET INC", "02079K107", 400, 2, ""), ("AMERICAN EXPRESS CO", "025816109", 1000, 4, ""))

            @staticmethod
            def json():
                return {"directory": {"item": [{"name": "primary_doc.xml"}, {"name": "56757.xml"}]}}
        return R()


def test_main_merges_share_classes_into_our_ticker_and_skips_same_filing(monkeypatch):
    monkeypatch.setattr(gurus, "GURUS", {"buffett": gurus.GURUS["buffett"]})
    con = db.connect(":memory:")
    gurus.main(date(2026, 10, 10), con, FakeSec())
    got = con.execute("select ticker, issuer, value, weight, period from guru_holdings order by value desc").fetchall()
    assert got == [("GOOGL", "ALPHABET INC", 1000, 50.0, "2026-06-30"), (None, "AMERICAN EXPRESS CO", 1000, 50.0, "2026-06-30")]
    con.execute("update guru_holdings set value = 1")
    gurus.main(date(2026, 10, 11), con, FakeSec())  # 같은 신고면 다시 받지 않는다
    assert con.execute("select sum(value) from guru_holdings").fetchone() == (2,)


def test_cusip_map_covers_every_us_stock():
    uni = [ln.split()[0] for ln in (gurus.CUSIPS.parent / "universe_us.txt").read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    assert set(uni) <= set(gurus.cusip_map().values())


def test_guru_page_and_note_owners_link_each_other():
    from hanjang import web

    con = db.connect(":memory:")
    con.execute("insert into stocks (ticker, name, corp_code, active, market, homepage) values ('AAPL', '애플', '320193', 1, 'US', 'ticker/AAPL')")
    con.executemany("insert into guru_holdings values ('buffett', ?, ?, ?, ?, 1, ?, '0001193125-26-352200', '2026-06-30', '2026-08-14')",
                    [("037833100", "APPLE INC", "AAPL", 66e9, 22.0), ("025816109", "AMERICAN EXPRESS CO", None, 51e9, 17.1)])
    app = web.App(con, "s" * 32)
    title, _, rows = app.owners("AAPL")
    assert title == "이 종목을 가진 유명 투자자" and rows == [("워런 버핏 · 버크셔 해서웨이", "/learn/guru/buffett", "berkshirehathaway.com", "포트폴리오의 22.0% · 2026년 6월 30일 기준")]
    assert 'href="/learn/guru/buffett"' in web.owners_block(app.owners("AAPL")) and web.owners_block(app.owners("005930")) == ""
    _, _, html_ = app.guru(1, "buffett", "", "")
    assert "미국 주식 2종목" in html_ and "비중 22.0% · 660억 달러" in html_ and "AMERICAN EXPRESS CO" in html_
    assert 'href="/n/AAPL"' not in html_  # 노트가 아직 없으면 누르지 않는 줄
    assert "2026년 6월 30일 기준, 2026년 8월 14일에 낸 신고" in html_ and "따라 사고팔라는 뜻이 아니에요" in html_
    assert "/learn/guru/buffett" in app.guru_list() and app.guru(1, "nobody", "", "")[0].startswith("404")
