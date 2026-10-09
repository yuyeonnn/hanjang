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

    def tickers(self):
        return {"AXP": (4962, "AMERICAN EXPRESS CO")}

    def submissions(self, cik):
        if cik == 4962:
            return {"sic": "6199"}
        return {"filings": {"recent": {"form": ["4", "13F-HR"], "accessionNumber": ["x", "0001-26-1"], "reportDate": ["", "2026-06-30"], "filingDate": ["", "2026-08-14"]}}}

    def _get(self, url):
        class R:
            content = xml(("ALPHABET INC", "02079K305", 600, 2, ""), ("ALPHABET INC", "02079K107", 400, 2, ""), ("AMERICAN EXPRESS CO", "025816109", 1000, 4, "")).encode()

            @staticmethod
            def json():
                return {"directory": {"item": [{"name": "primary_doc.xml"}, {"name": "56757.xml"}]}}
        return R()


def test_main_merges_share_classes_into_our_ticker_and_skips_same_filing(monkeypatch):
    monkeypatch.setattr(gurus, "GURUS", {"buffett": gurus.GURUS["buffett"]})
    monkeypatch.setattr(gurus, "INSTS", {"capital": [1, 2]})  # 기관은 여러 부문을 합친다 — 같은 표를 두 번 받으니 금액이 두 배
    con = db.connect(":memory:")
    gurus.main(date(2026, 10, 10), con, FakeSec())
    assert con.execute("select accn, value, sic from guru_holdings where guru = 'capital' and ticker = 'GOOGL'").fetchone() == ("0001-26-1+0001-26-1", 2000, "")
    con.execute("delete from guru_holdings where guru = 'capital'")
    got = con.execute("select ticker, issuer, value, weight, period, sic from guru_holdings order by value desc").fetchall()
    assert got == [("GOOGL", "ALPHABET INC", 1000, 50.0, "2026-06-30", ""), (None, "AMERICAN EXPRESS CO", 1000, 50.0, "2026-06-30", "6199")]  # 우리 종목 밖은 이름 → CIK → SIC
    assert gurus.sector("6199") == "금융" and gurus.sector("3674") == "전자·반도체" and gurus.sector("", "SPDR S&P 500 ETF TR") == "ETF(지수 펀드)"
    con.execute("update guru_holdings set value = 1")
    gurus.main(date(2026, 10, 11), con, FakeSec())  # 같은 신고면 다시 받지 않는다
    assert con.execute("select sum(value) from guru_holdings where guru = 'buffett'").fetchone() == (2,)


def test_cusip_map_covers_every_us_stock():
    uni = [ln.split()[0] for ln in (gurus.CUSIPS.parent / "universe_us.txt").read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    assert set(uni) <= set(gurus.cusip_map().values())


def test_guru_page_and_note_owners_link_each_other():
    from hanjang import web

    con = db.connect(":memory:")
    con.execute("insert into stocks (ticker, name, corp_code, active, market, homepage) values ('AAPL', '애플', '320193', 1, 'US', 'ticker/AAPL')")
    con.executemany("insert into guru_holdings values ('buffett', ?, ?, ?, ?, 1, ?, '0001193125-26-352200', '2026-06-30', '2026-08-14', ?)",
                    [("037833100", "APPLE INC", "AAPL", 66e9, 22.0, "3571"), ("025816109", "AMERICAN EXPRESS CO", None, 51e9, 17.1, "6199")])
    app = web.App(con, "s" * 32)
    title, _, rows = app.owners("AAPL")
    assert title == "이 종목을 가진 유명 투자자·기관" and [(n, h, d) for n, h, _, d in rows] == [("워런 버핏 · 버크셔 해서웨이", "/learn/guru/buffett", "포트폴리오의 22.0% · 2026년 6월 30일 기준")]
    assert 'src="/static/people/buffett.jpg"' in rows[0][2] and "Public domain" in rows[0][2]  # 위키미디어 공용 사진 · 출처는 마우스를 올리면
    assert 'href="/learn/guru/buffett"' in web.owners_block(app.owners("AAPL")) and web.owners_block(app.owners("005930")) == ""
    _, _, html_ = app.guru(1, "buffett", "", "")
    assert "어떤 업종에 많이 가졌나" in html_ and ">금융</span>" in html_ and ">44%</span>" in html_  # 금액 비중 — 아멕스 510억/1,170억
    assert "미국 주식 2종목" in html_ and "비중 22.0% · 660억 달러" in html_ and "American Express Co" in html_  # 대문자 줄임말은 보기 좋게
    assert 'href="/n/AAPL"' not in html_  # 노트가 아직 없으면 누르지 않는 줄
    assert "2026년 6월 30일 기준, 2026년 8월 14일에 낸 신고" in html_ and "따라 사고팔라는 뜻이 아니에요" in html_
    assert "사진: <a" in html_ and "위키미디어 공용" in html_  # 페이지 맨 아래 사진 출처
    assert app.route("GET", "/static/people/buffett.jpg", {}, {}, None)[2][:2] == bytes([0xFF, 0xD8])  # JPEG
    assert "/static/people/burry.jpg" not in web.guru_face("burry")  # 자유 이용 사진이 없으면 글자 동그라미
    assert "가장 많이 가진 종목" in html_ and ">56.4%</span>" in html_ and ">애플</span>" in html_ and "금액이 큰 다섯 종목이에요" not in html_  # 애플 660억/1,170억
    left = html_.split('<svg viewBox="0 0 100 100"')[0].rsplit("<ul", 1)[1]  # 원 왼쪽 목록
    assert "flex-row-reverse" in left and "items-end" in left and ">American Express Co</span>" in left  # 왼쪽 반 조각은 왼쪽 목록, 오른쪽 정렬
    # 기관(국민연금)의 미국 주식 — 기관 페이지에 파이·10종목, 노트 맨 밑엔 유명 투자자 다음에
    con.execute("insert into guru_holdings values ('nps', '037833100', 'APPLE INC', 'AAPL', 9e9, 1, 5.9, 'x', '2026-06-30', '2026-08-13', '')")
    assert [r[0] for r in app.owners("AAPL")[2]] == ["워런 버핏 · 버크셔 해서웨이", "국민연금"] and "미국 주식의 5.9%" in app.owners("AAPL")[2][1][3]
    assert "미국 주식 포트폴리오" in app.us_portfolio("nps") and app.us_portfolio("blackrock") == ""
    con.execute("insert into big_holdings (inst, stock_code, corp_name, corp_cls, rate, rate_chg, date, rcept_no, induty_code) values ('nps', '005930', '삼성전자', 'Y', 7.1, 0, '2026-10-01', 'r1', '264')")
    big = app.big(1, "nps", "", "")[2]  # 기관 페이지 — 미국 주식은 국내 목록 위에, 머리에 종목 수
    assert "미국 주식 1종목" in big and big.index("가장 많이 가진 종목") < big.index("어떤 업종에 많이 가졌나") < big.index("비중 5.9%")  # 파이 → 업종 → 많이 가진 순서
    assert "지분이 큰 순서" not in big and "최근 늘리고 줄인" not in big  # 너무 자세한 목록은 뺐다
    con.execute("insert into big_holdings (inst, stock_code, corp_name, corp_cls, rate, rate_chg, date, rcept_no, induty_code) values ('kbam', '005930', '삼성전자', 'Y', 5.2, 0, '2026-10-01', 'r2', '264')")
    assert "5% 넘게 가진 회사</h2>" in app.big(1, "kbam", "", "")[2]  # 미국 신고가 없는 기관은 5% 목록이 전부라 남긴다
    two = web.pie([("가", 50), ("나", 30), ("다", 20)], n=2)  # 기타는 그리지 않는다 — 상위 2종목만, 글자는 전체 중 비중
    assert two.count("<path") == 2 and ">기타<" not in two and ">50.0%</span>" in two and "기타는 빼고 상위 2종목만 그렸어요 (전체의 80%)" in two
    assert "/learn/guru/buffett" in app.guru_list() and app.guru(1, "nobody", "", "")[0].startswith("404")


def test_spread_out_portfolio_is_still_a_pie_without_other():
    from hanjang import web

    many = [(f"종목{i}", 3) for i in range(30)]  # 넓게 나눈 곳도 파이 — 기타 없이 상위 5, 뺐다는 말은 눈에 띄게
    h = web.pie(many)
    assert "data-pie" in h and h.count("<path") == 5 and "기타는 빼고 상위 5종목만 그렸어요 (전체의 17%)" in h and ">기타<" not in h

def test_every_holdings_list_shows_twenty():
    from hanjang import web

    con = db.connect(":memory:")
    rows = [(k, f"{i:09d}", f"CO {i}", None, 1e9 - i, 1, 1.0, "a", "2026-06-30", "2026-08-14", "") for k in ("buffett", "nps") for i in range(25)]
    con.executemany("insert into guru_holdings values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    app = web.App(con, "s" * 32)
    for h in (app.guru(1, "buffett", "", "")[2], app.us_portfolio("nps")):  # 유명 투자자 · 기관 — 같은 20종목
        assert h.count("text-[12px] text-outline tabular-nums") == 20 and "외 5종목" in h


def test_industry_tag_is_plain_gray_text():
    from hanjang import web

    assert ">#반도체</span>" in web.ind_tag(sic="3674") and "bg-" not in web.ind_tag(sic="3674")  # 상자·배경 없이 회색 글씨
    assert ">#ETF</span>" in web.ind_tag(sic="", issuer="ISHARES TR") and web.ind_tag() == ""
