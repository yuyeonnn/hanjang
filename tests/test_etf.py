"""국내 ETF 한 장 — 투자설명서 제목·표지 읽기와 노트 모양. 외부 API 는 부르지 않는다."""

import json
from datetime import date

from hanjang import collect, db, etf, notepage

# DART 투자설명서 표지 (2026-10-08 신한SOL국고채3년 · 10-01 삼성KODEX 코스피에서 줄임)
SOL = ("정 정 신 고 (보고) 2026년 10월 08일 1. 정정대상 공시서류 : 간이투자설명서 2. 정정대상 공시서류의 최초제출일 : 2022.08.22 "
       "3. 정정사유 1) 분배금 지급기준일 추가 2) 이익초과분배 관련조항 신설 4. 정정요구ㆍ명령 관련 여부: 아니오 "
       "간이투자설명서 (작성기준일 : 2026.09.30 ) 신한SOL국고채3년증권상장지수투자신탁[채권] 투자위험등급\n5등급[ 낮은 위험 ] "
       "이 투자신탁은\n채권\n을 법 시행령 제94조제2항제4호에서 규정하는 주된 투자대상자산으로 하며,“\nKAP국고채3년지수(총수익지수)\n”를 기초지수로 하여 "
       "따라서\n원본손실위험, 이자율 변동에 따른 위험, 시장위험 및 개별위험, 추적오차(Tracking Error) 발생위험, 상장폐지위험\n등이 있으므로")
KODEX = ("정 정 신 고 (보고) 2026년 10월 1일 1. 정정대상 공시서류 : 투자설명서 2. 정정대상 공시서류의 최초제출일 : 2015. 8.17 "
         "3. 정정 사유: - 운용역 변경(가 운용역 → 나 운용역) 4. 정정요구ㆍ명령 관련 여부 : 아니오 투자위험등급 2등급[ 높은 위험 ] "
         "1. 집합투자기구 명칭 : 삼성KODEX 코스피증권상장지수투자신탁[주식] 2. 집합투자업자 명칭 : 삼성자산운용주식회사 4. 작 성 기 준 일 : 2026.9.18")


def test_names_from_dart_titles():
    assert etf.fund_name("[기재정정]투자설명서(집합투자증권)(삼성KODEX 코스피증권상장지수투자신탁[주식])") == "삼성KODEX 코스피증권상장지수투자신탁[주식]"
    assert etf.fund_name("투자설명서(집합투자증권)(DB마이티26-09특수채(AAA)액티브증권상장지수투자신탁[채권])") == "DB마이티26-09특수채(AAA)액티브증권상장지수투자신탁[채권]"
    assert etf.fund_name("투자설명서(집합투자증권)(신영디딤자산배분증권자투자신탁(채권혼합))") is None  # ETF 가 아닌 펀드
    assert etf.fund_name("증권발행실적보고서(집합투자증권)(삼성KODEX200증권상장지수투자신탁[주식])") is None
    assert etf.short("삼성KODEX 코스피증권상장지수투자신탁[주식]") == "KODEX 코스피"
    assert etf.short("미래에셋TIGER미국S&P500증권상장지수투자신탁(주식)") == "TIGER 미국S&P500"
    assert etf.short("미래에셋TIGER유로스탁스50증권상장지수투자신탁(주식-파생형)(합성H)") == "TIGER 유로스탁스50(합성 H)"
    assert etf.short("삼성KODEX미국달러선물레버리지특별자산상장지수투자신탁[미국달러-파생형]") == "KODEX 미국달러선물레버리지"
    assert etf.short("IBKIBK200증권상장지수투자신탁[주식]") == "IBK 200"
    assert etf.short("타임폴리오TIME코스피액티브증권상장지수투자신탁(주식)") == "TIME 코스피액티브"
    assert etf.ticker_of("a") == etf.ticker_of("a") and etf.ticker_of("a").startswith("ETF")


def test_cover_reads_grade_index_and_why_it_changed():
    a = etf.parse_cover(SOL)
    assert (a["risk"], a["risk_label"], a["index"], a["asset"], a["as_of"], a["first"]) == (
        5, "낮은 위험", "KAP국고채3년지수(총수익지수)", "채권", "2026-09-30", "2022-08")
    assert a["risks"][0] == "원본손실위험" and len(a["risks"]) == 5 and a["change"] == "분배금을 주는 규칙이 바뀌었어요"
    b = etf.parse_cover(KODEX)
    assert (b["risk"], b["manager"], b["change"]) == (2, "삼성자산운용", "운용을 맡은 사람이 바뀌었어요")  # 운용역 이름은 옮기지 않는다
    assert etf.parse_cover("운용전문인력의 운용규모 업데이트")  == {}  # 정정 표지가 없으면 「고친 이유」도 없다


def test_note_is_plain_and_renders_like_a_stock_note():
    name = "신한SOL국고채3년증권상장지수투자신탁[채권]"
    facts, body = etf.note(name, etf.parse_cover(SOL), "20261008000372", "2026-10-08")
    text = " ".join(s["text"] for sec in body["sections"] for s in sec["sentences"])
    assert body["headline"] == "SOL 국고채3년은 만기가 3년쯤 남은 나라 빚(국고채)를 한꺼번에 담는 상자예요."
    assert "「KAP국고채3년지수(총수익지수)」를 따라가도록" in text and "6단계 가운데 5등급(낮은 위험)" in text
    assert "10월 8일에 투자설명서를 고쳤어요 — 분배금을 주는 규칙이 바뀌었어요." in text and "증권사 앱에서" in text
    assert all(s["refs"] == ["F1"] for sec in body["sections"] for s in sec["sentences"])  # 모든 문장에 원문 링크
    _, lev = etf.note("삼성KODEX미국달러선물레버리지특별자산상장지수투자신탁[미국달러-파생형]", {}, "r", "2026-10-01")
    assert "두 배만큼" in json.dumps(lev, ensure_ascii=False)
    html_ = notepage.render_note("SOL 국고채3년", "ETFabcde", "2026-10-05", body, "code:etf", facts)
    assert "무엇을 담는 상자인가요?" in html_ and "dart.fss.or.kr" in html_


def test_held_etf_is_not_sent_to_stock_notes():
    con = db.connect(":memory:")
    con.execute("insert into stocks (ticker, name, active) values ('ETFabcde', 'SOL 국고채3년', 0)")
    con.execute("insert into users (id, email, created_at) values (1, 'a@x.kr', 'now')")
    con.execute("insert into holdings values (1, 'ETFabcde', 'now')")
    collect.save_universe(con, [("005930", "삼성전자")], {})
    assert dict(con.execute("select ticker, active from stocks")) == {"ETFabcde": 0, "005930": 1}


class FakeDart:
    calls = 0

    def _list(self, path, **p):
        return {"total_page": 1, "list": [
            {"report_nm": "[기재정정]투자설명서(집합투자증권)(신한SOL국고채3년증권상장지수투자신탁[채권])", "rcept_no": "20261008000372", "rcept_dt": "20261008"},
            {"report_nm": "투자설명서(집합투자증권)(신한SOL국고채3년증권상장지수투자신탁[채권])", "rcept_no": "20260113000674", "rcept_dt": "20260113"}]}

    def doc_text(self, rno, every=False):
        return SOL


def test_main_lists_etfs_and_writes_a_note_only_for_held_ones():
    con = db.connect(":memory:")
    etf.main(date(2026, 10, 9), con, FakeDart())
    (t, name, rno) = con.execute("select e.ticker, s.name, e.rcept_no from etfs e join stocks s using(ticker)").fetchone()
    assert (name, rno) == ("SOL 국고채3년", "20261008000372")  # 같은 펀드는 가장 새 투자설명서
    assert con.execute("select count(*) from notes").fetchone() == (0,)  # 아무도 안 담았으면 원문을 열지 않는다
    con.execute("insert into users (id, email, created_at) values (1, 'a@x.kr', 'now')")
    con.execute("insert into holdings values (1, ?, 'now')", (t,))
    etf.main(date(2026, 10, 9), con, FakeDart())
    assert con.execute("select writer, week from notes").fetchone() == ("code:etf", "2026-10-05")


def test_monday_mail_carries_the_etf_page():
    from hanjang import mail
    facts, body = etf.note("신한SOL국고채3년증권상장지수투자신탁[채권]", etf.parse_cover(SOL), "20261008000372", "2026-10-08")
    _, text, html_ = mail.weekly_mail("2026-10-05", [{"ticker": "ETFabcde", "name": "SOL 국고채3년", "body": body, "facts": facts, "fin": []}])
    assert "무엇을 담는 상자인가요?" in text and "SOL 국고채3년" in html_
