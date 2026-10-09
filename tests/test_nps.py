from datetime import date

from hanjang import db, gurus, nps, web


def test_parse_kr_reads_cp949_and_drops_zero_rows():
    raw = "번호,종목명,평가액(억 원),자산군 내 비중(퍼센트),지분율(퍼센트)\n1,삼성전자,551095,21.06,7.76\n2,MTRON,0,0,0\n".encode("cp949")
    assert nps.parse_kr(raw) == [("삼성전자", 551095e8, 7.76)]  # 억 원 → 원


def test_nps_page_ranks_korea_and_us_together(monkeypatch):
    con = db.connect(":memory:")
    con.execute("insert into stocks (ticker, name, corp_code, active, market) values ('005930', '삼성전자', '1', 1, 'KR'), ('NVDA', '엔비디아', '2', 1, 'US')")
    con.executemany("insert into nps_port values ('2025-12-31', ?, ?, ?, ?, ?)",
                    [("KR", "삼성전자", "005930", 55e12, 7.8), ("US", "NVIDIA CORPORATION", "NVDA", 13e12, None),
                     ("US", "INVESCO EXCH TRADED FD TR II PURBTA MSCI US", None, 4e12, None), ("KR", "현대차", None, 5e12, 7.7)])
    con.execute("insert into nps_meta values ('2025-12-31', 1439.0, 'x')")
    html_ = web.App(con, "s" * 32).nps_portfolio()
    ranked = html_.split('<div class="mt-space-sm')[1]  # 파이 밑 순위 목록
    order = [ranked.index(x) for x in ('>삼성전자<', '>엔비디아<', '>현대차<', '>Invesco ETF<')]
    assert order == sorted(order)  # 한국·미국 섞어 금액 큰 순
    assert "1달러 1,439.0원" in html_ and "기준 · 한국" not in html_  # 요약 줄(종목 수·합계)은 뺐다 (사용자 10/10)
    assert gurus.sector("", "ISHARES TR") == "ETF(지수 펀드)"
