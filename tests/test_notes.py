"""2주차 — 사실 묶음 계산과 숫자 대조 검사. AI 는 부르지 않는다."""

from datetime import date

import pytest

from hanjang import collect, db, notes, sources


def _con():
    con = db.connect(":memory:")
    collect.save_universe(con, [("005930", "삼성전자")], {})
    collect.save_financials(con, [
        sources.Financial("005930", 2025, 333605938000000, 43601051000000, 45206805000000,
                          436320337000000, 130621773000000, "20260310002820"),
        sources.Financial("005930", 2024, 300870903000000, 32725961000000, 34451351000000,
                          402192070000000, 112339878000000, "20250311001085"),
    ])  # fmt: skip
    collect.save_disclosures(con, [sources.Disclosure("20260821000616", "005930", date(2026, 8, 21),
                                                      "주요사항보고서(자기주식취득결정)")])  # fmt: skip
    con.execute("update disclosures set code='BUYBACK', importance=3, direction=1, read_at='x'")
    return con


def test_facts_match_sample_note():
    """샘플 노트(퀀트점프 계산)와 같은 숫자가 나와야 한다."""
    fs = {f["id"]: f["text"] for f in notes.facts(_con(), "005930", date(2026, 10, 7))}
    assert fs["F1"] == "2025년 매출 333.6조원(전년보다 +10.9%)"
    assert fs["F2"] == "2025년 영업이익 43.6조원(전년보다 +33.2%)"
    assert "부채비율 29.9%" in fs["F3"] and "ROE 10.4%" in fs["F4"]
    assert fs["D1"].startswith("8월 21일 자사주 매입 공시") and "반가운" in fs["D1"]


def test_won_units():
    assert (notes.won(333605938000000), notes.won(558300000000), notes.won(-120000000)) == (
        "333.6조원", "5,583억원", "-1억원")


def _note(text, refs=("F1",)):
    return {"headline": "작년에 많이 팔았어요.", "summary": [{"text": text, "refs": list(refs)}],
            "sections": [], "good": [{"text": "많이 팔았어요.", "refs": ["F1"]}], "concern": []}


def test_check_rejects_rounded_or_made_up_numbers():
    fs = notes.facts(_con(), "005930", date(2026, 10, 7))
    notes.check_note(_note("매출이 333.6조원으로 10.9% 늘었어요."), fs)  # 그대로 옮기면 통과
    for bad in ("매출이 11% 늘었어요.", "매출이 330조 원쯤이에요.", "3분기에도 그럴 거예요."):
        with pytest.raises(ValueError, match="숫자"):
            notes.check_note(_note(bad), fs)


def test_check_rejects_forbidden_and_unsourced():
    fs = notes.facts(_con(), "005930", date(2026, 10, 7))
    with pytest.raises(ValueError, match="금지어"):
        notes.check_note(_note("지금은 매수할 때예요."), fs)
    with pytest.raises(ValueError, match="근거"):
        notes.check_note(_note("좋은 회사예요.", refs=("X9",)), fs)


def test_recode_and_code_fallback():
    assert notes.recode("BUYBACK", "자기주식 처분 결정") == "OTHER"
    assert notes.recode("CB_BW", "조건부자본증권 발행결정") == "OTHER"
    fs = notes.facts(_con(), "005930", date(2026, 10, 7))
    note = notes.code_note(fs)
    notes.check_note({**note, "headline": "사실만 옮겼어요."}, fs)  # 대체 글도 검사를 통과한다


def test_tone_is_decided_by_code_and_enforced():
    con = _con()
    collect.save_financials(con, [sources.Financial("005930", 2025, 333605938000000, -100, 1, 10, 30,
                                                    "20260310002820")])  # 영업 적자 · 부채비율 300%
    fs = {f["id"]: f for f in notes.facts(con, "005930", date(2026, 10, 7))}
    assert (fs["F1"]["tone"], fs["F2"]["tone"], fs["F3"]["tone"], fs["D1"]["tone"]) == (1, -1, -1, 1)
    note = _note("매출이 늘었어요.")
    with pytest.raises(ValueError, match="concern"):  # 걱정 사실이 있는데 비워 두면 탈락
        notes.check_note(note, list(fs.values()))
    with pytest.raises(ValueError, match="섞임"):  # 좋은 사실을 걱정 칸에
        notes.check_note({**note, "concern": [{"text": "많이 팔았어요.", "refs": ["F1"]}]}, list(fs.values()))
    notes.check_note({**note, "concern": [{"text": "영업 적자예요.", "refs": ["F2"]}]}, list(fs.values()))


def test_finish_leaves_empty_side_empty():
    fs = notes.facts(_con(), "005930", date(2026, 10, 7))  # 걱정 사실 없음
    note = notes.finish({"headline": "x", "summary": [], "sections": [], "good": [], "concern": []}, fs)
    assert note["concern"] == [] and "concern_title" not in note and note["tone_rule"]
    assert notes.code_note(fs)["good"]  # 코드 대체 노트에도 좋게 본 것이 들어간다


def test_prediction_wording_only_allowed_for_news():
    fs = notes.facts(_con(), "005930", date(2026, 10, 7))
    with pytest.raises(ValueError, match="예측"):
        notes.check_note(_note("매출이 늘어날 전망이에요."), fs)
    fs.append({"id": "N1", "text": "10월 5일 기사 제목 「실적 개선 전망」", "url": "https://n", "tone": 0})
    notes.check_note(_note("기사는 실적이 좋아질 것으로 보인다고 써요.", refs=("N1",)), fs)


def test_forbidden_words_do_not_catch_ordinary_words():
    f = notes.FORBIDDEN.search
    assert not f("신규 임원 인사라고 써요") and not f("회사라서") and not f("수주 목표가 올라갔다고 써요")
    assert f("지금 사라") and f("목표가를 올렸어요") and f("목표주가") and f("매수")


def test_slots_fill_numbers_and_direction_from_code():
    fs = notes.facts(_con(), "005930", date(2026, 10, 7))
    by = {f["id"]: f for f in fs}
    got = notes.fill({"text": "{F1.연도} 매출이 {F1.변화} {F1.방향}어요({F1.값}).", "refs": []}, by)
    assert got == {"text": "2025년 매출이 +10.9% 늘었어요(333.6조원).", "refs": ["F1"]}  # 근거도 저절로
    assert notes.fill({"text": "매출이 10.9% 늘었어요.", "refs": ["F1"]}, by)  # 근거 사실에 그대로 있는 숫자는 직접 써도 된다
    with pytest.raises(ValueError, match="빈칸으로만"):  # 다른 사실의 숫자를 끌어오면 탈락
        notes.fill({"text": "매출이 33.2% 늘었어요.", "refs": ["F1"]}, by)
    with pytest.raises(ValueError, match="없는 빈칸"):
        notes.fill({"text": "{F1.주가}예요.", "refs": ["F1"]}, by)


def test_direction_word_against_fact_is_rejected():
    con = _con()
    collect.save_financials(con, [sources.Financial("005930", 2025, 200000000000000, 43601051000000, 1, 10, 3,
                                                    "20260310002820")])  # 매출 감소
    by = {f["id"]: f for f in notes.facts(con, "005930", date(2026, 10, 7))}
    assert by["F1"]["slots"]["방향"] == "줄었" and by["F1"]["tone"] == -1
    with pytest.raises(ValueError, match="반대 방향"):
        notes.fill({"text": "매출이 크게 늘었어요.", "refs": ["F1"]}, by)
    assert notes.fill({"text": "매출이 {F1.방향}어요.", "refs": ["F1"]}, by)["text"] == "매출이 줄었어요."


def test_turnaround_is_said_in_words_not_percent():
    assert notes.trend(5, -3)[:2] == (1, "흑자로 돌아섰")
    assert notes.trend(-5, 3)[:2] == (-1, "적자로 돌아섰")
    assert notes.trend(-5, -3)[2] == "적자 지속"
    assert notes.trend(110, 100) == (1, "늘었", "+10.0%")


def test_title_rules_decide_without_ai():
    assert notes.by_rule("주요사항보고서(자기주식취득결정)") == ("BUYBACK", 3)
    assert notes.by_rule("[기재정정]단일판매ㆍ공급계약체결") == ("MAJOR_CONTRACT", 2)
    assert notes.by_rule("현금ㆍ현물배당결정") == ("DIVIDEND", 2)
    assert notes.by_rule("연결재무제표기준영업(잠정)실적(공정공시)") == ("EARNINGS", 2)
    assert notes.by_rule("최대주주등소유주식변동신고서") == ("OTHER", 1)
    assert notes.by_rule("투자설명서") is None  # 규칙에 없으면 AI 에게
    assert notes.by_rule("불성실공시법인지정") == ("TRADING_HALT", 3)  # 코스닥에 잦은 거래소 경고
    assert notes.by_rule("주권매매거래정지해제") is None and "다시 열렸어요" in notes.plain("주권매매거래정지해제")
    assert "사고팔기를 잠시 멈췄어요" in notes.plain("주권매매거래정지(합병 관련)")


def test_schema_limits_refs_to_this_notes_facts():
    fs = notes.facts(_con(), "005930", date(2026, 10, 7))
    s = notes.schema(fs)
    refs = s["properties"]["summary"]["items"]["properties"]["refs"]["items"]["enum"]
    assert refs == [f["id"] for f in fs] and s["additionalProperties"] is False


def test_fallback_headline_is_the_companys_biggest_issue():
    fs = notes.facts(_con(), "005930", date(2026, 10, 7))
    assert notes.code_headline(fs) == "2025년 영업이익이 늘었어요(43.6조원, +33.2%)."
    con = _con()
    collect.save_disclosures(con, [sources.Disclosure("20261001000001", "005930", date(2026, 10, 1), "유상증자결정")])
    con.execute("update disclosures set code='RIGHTS_ISSUE', importance=3, direction=-1 where rcept_no='20261001000001'")
    assert notes.code_headline(notes.facts(con, "005930", date(2026, 10, 7))) == "10월 1일에 유상증자 공시가 있었어요."


def test_year_may_be_written_but_nothing_else():
    by = {f["id"]: f for f in notes.facts(_con(), "005930", date(2026, 10, 7))}
    assert notes.fill({"text": "2025년 매출이 {F1.방향}었지만 괜찮아요.", "refs": ["F1"]}, by)["text"] == "2025년 매출이 늘었지만 괜찮아요."
    with pytest.raises(ValueError, match="빈칸으로만"):
        notes.fill({"text": "2024년 매출이 늘었어요.", "refs": ["F1"]}, by)  # 사실에 없는 연도


def test_unsigned_width_slot_reads_naturally():
    by = {f["id"]: f for f in notes.facts(_con(), "005930", date(2026, 10, 7))}
    assert notes.fill({"text": "매출이 {F1.폭} {F1.방향}어요.", "refs": ["F1"]}, by)["text"] == "매출이 10.9% 늘었어요."


def test_particle_follows_slot_value():
    by = {f["id"]: f for f in notes.facts(_con(), "005930", date(2026, 10, 7))}
    assert notes.fill({"text": "{D1.날짜}와 {F1.값}가 있어요.", "refs": ["D1", "F1"]}, by)["text"] == "8월 21일과 333.6조원이 있어요."
    assert notes.fill({"text": "{F1.폭}은 컸어요.", "refs": ["F1"]}, by)["text"] == "10.9%는 컸어요."


def test_disclosure_fact_carries_plain_meaning():
    fs = {f["id"]: f for f in notes.facts(_con(), "005930", date(2026, 10, 7))}
    assert "무슨 일: 회사가 시장에서 자기 회사 주식을 사들이기로 했어요" in fs["D1"]["text"]
    assert notes.plain("주식소각결정").startswith("회사가 갖고 있던 자기 주식을 아예 없애기로")
    assert notes.plain("[기재정정]주요사항보고서(유상증자결정)").startswith("새 주식을 찍어 팔아")


def test_news_sentence_may_copy_numbers_from_its_rss_summary():
    by = {f["id"]: f for f in notes.facts(_con(), "005930", date(2026, 10, 7))}
    by["N1"] = {"id": "N1", "text": "10월 5일 연합뉴스 소식 「삼성 실적」 — HBM4 공급이 3분기에 12% 늘었다", "tone": 0, "url": "https://n",
                "slots": {"날짜": "10월 5일", "매체": "연합뉴스", "제목": "「삼성 실적」"}}
    assert notes.fill({"text": "기사는 HBM4 공급이 12% 늘었다고 해요.", "refs": ["N1"]}, by)["text"].startswith("기사는 HBM4")
    with pytest.raises(ValueError, match="빈칸으로만"):  # 소식에 없는 숫자
        notes.fill({"text": "기사는 공급이 30% 늘었다고 해요.", "refs": ["N1"]}, by)
    assert notes.fill({"text": "공급이 12% 늘었다는 보도와 함께 공시도 있었어요.", "refs": ["N1", "D1"]}, by)  # 공시와 묶어도 소식 숫자는 된다
    assert notes.fill({"text": "매출이 {F1.폭} {F1.방향}을 때 영업이익은 {F2.폭} {F2.방향}거든요.", "refs": []}, by)  # 「늘었을 때」


def test_dates_of_facts_may_be_written_directly():
    by = {f["id"]: f for f in notes.facts(_con(), "005930", date(2026, 10, 7))}
    assert notes.fill({"text": "8월 21일에 자사주 매입 공시가 있었어요.", "refs": ["D1"]}, by)["text"].startswith("8월 21일")
    assert notes.fill({"text": "8월에는 자사주를 사들였어요.", "refs": ["D1"]}, by)
    with pytest.raises(ValueError, match="빈칸으로만"):
        notes.fill({"text": "9월 3일에 공시가 있었어요.", "refs": ["D1"]}, by)  # 사실에 없는 날짜


def test_made_up_slot_and_repeated_kind_are_rejected():
    con = _con()
    collect.save_disclosures(con, [sources.Disclosure("20260821000999", "005930", date(2026, 8, 21), "주식소각결정")])
    con.execute("update disclosures set code='BUYBACK', importance=3, direction=1 where rcept_no='20260821000999'")
    by = {f["id"]: f for f in notes.facts(con, "005930", date(2026, 10, 7))}
    with pytest.raises(ValueError, match="빈칸"):
        notes.fill({"text": "규모가 {N1.body}예요.", "refs": ["F1"]}, by)
    with pytest.raises(ValueError, match="반복"):
        notes.fill({"text": "주식을 사고 없앴어요({D1.종류}, {D2.종류}).", "refs": ["D1", "D2"]}, by)


def test_dedupe_paren_list():
    assert notes.dedupe("공시가 나왔어요(7월 23일·7월 23일·7월 20일).") == "공시가 나왔어요(7월 23일·7월 20일)."
    assert notes.dedupe("(10월 1일, 「A, B」, 「A, B」)") == "(10월 1일, 「A, B」)"
    assert notes.dedupe("(매출 97.1조원 · 영업이익 47.2조원)") == "(매출 97.1조원 · 영업이익 47.2조원)"
    assert notes.dedupe("소식이 나왔어요(「A」, 「B」). 끝") == "소식이 나왔어요. 끝"
    assert notes.dedupe("수주했어요(「삼성중공업, LNG선 2척 수주」).") == "수주했어요."
    assert notes.dedupe("나왔어요(「[특징주] 한전기술 강세(종합)」).") == "나왔어요."  # 제목 속 괄호도
    assert notes.dedupe("8월 8월 3일에 공시가 나왔어요.") == "8월 3일에 공시가 나왔어요."


def _insiders(con):
    con.executemany("insert into insiders values (?, ?, ?, ?, ?, ?, ?, ?)", [
        ("r1", "005930", "2026-09-01", "임원", "상무", 500, None, None),
        ("r2", "005930", "2026-09-10", "임원", "부사장", -300, None, None),
        ("r3", "005930", "2026-09-20", "임원", "전무", 1000, None, None),
        ("r4", "005930", "2026-06-01", "임원", "상무", 9999, None, None),  # 90일 밖
        ("r5", "005930", "2026-09-15", "5%", "국민연금공단", -240772, 7.1, 0.39),
    ])  # fmt: skip


def test_insider_facts_count_and_never_say_buy():
    """임원 보고는 늘린·줄인 건수와 합계로 묶고, 「샀다·매수」라고 쓰지 않는다. tone 은 중립."""
    con = _con()
    _insiders(con)
    fs = {f["id"]: f for f in notes.insider_facts(con, "005930", date(2026, 10, 7))}
    assert fs["I1"]["text"] == "최근 90일 임원·주요주주 지분 보고 3건 — 보유 주식을 늘린 보고 2건(합계 1,500주) · 줄인 보고 1건(합계 300주)"
    assert fs["I1"]["url"].endswith("r3")  # 가장 최근 보고로 잇는다
    assert fs["I2"]["text"] == "9월 15일 국민연금공단의 5% 이상 대량보유 보고 — 보유 비율 7.10%, 직전 보고보다 보유 주식 24만 772주 줄임"
    assert fs["I2"]["slots"]["방향"] == "줄였"
    assert all(f["tone"] == 0 and not notes.FORBIDDEN.search(f["text"]) for f in fs.values())
    assert any(f["id"] == "I1" for f in notes.facts(con, "005930", date(2026, 10, 7)))


def test_parse_insider_keeps_position_not_name():
    r = {"rcept_no": "1", "rcept_dt": "2026-06-10", "repror": "홍길동", "isu_exctv_ofcps": "IT본부장",
         "isu_main_shrholdr": "-", "sp_stock_lmp_irds_cnt": "-316"}
    x = sources.parse_insider("임원", r, "105560")
    assert (x.who, x.change, x.day) == ("IT본부장", -316, date(2026, 6, 10))
    m = sources.parse_insider("5%", {"rcept_no": "2", "rcept_dt": "2026-03-11", "repror": "BlackRock",
                                     "stkqy_irds": "1,237,684", "stkrt": "7.05", "stkrt_irds": "1.03"}, "105560")  # fmt: skip
    assert (m.who, m.change, m.rate) == ("BlackRock", 1237684, 7.05)


def test_changed_only_rewrites_when_facts_move():
    fs = [{"id": "F1", "text": "a"}, {"id": "N1", "text": "기사1"}]
    assert notes.changed(fs, None, held=False)  # 이번 주 노트가 없으면 쓴다
    assert not notes.changed(fs, fs, held=False)
    news = [{"id": "F1", "text": "a"}, {"id": "N1", "text": "기사2"}]
    assert not notes.changed(news, fs, held=False)  # 아무도 안 담은 종목은 기사만 바뀐 것으로 다시 쓰지 않는다
    assert notes.changed(news, fs, held=True)
    assert notes.changed([{"id": "F1", "text": "a"}, {"id": "D1", "text": "새 공시"}], fs, held=False)


def test_fill_allows_period_written_out():
    by = {"I1": {"id": "I1", "text": "x", "tone": 0, "slots": {"기간": "최근 90일", "늘린보고": "2건"}}}
    got = notes.fill({"text": "최근 90일 동안 늘린 보고가 {I1.늘린보고} 있었어요.", "refs": ["I1"]}, by)
    assert got["text"] == "최근 90일 동안 늘린 보고가 2건 있었어요."
    with pytest.raises(ValueError):
        notes.fill({"text": "최근 30일 동안 늘린 보고가 {I1.늘린보고} 있었어요.", "refs": ["I1"]}, by)
    by["I2"] = {"id": "I2", "text": "9월 15일 국민연금공단의 5% 이상 대량보유 보고", "tone": 0, "slots": {"날짜": "9월 15일", "누가": "국민연금공단"}}
    assert "5% 이상" in notes.fill({"text": "{I2.누가}가 5% 이상 대량보유 보고를 했어요.", "refs": ["I2"]}, by)["text"]
    assert notes.dedupe("8월 28일과 7월 31일에 줄였어요(8월 28일 · 7월 31일).") == "8월 28일과 7월 31일에 줄였어요."


def test_changed_ignores_rolling_insider_count():
    old = [{"id": "F1", "text": "a"}, {"id": "I1", "text": "최근 90일 … 806건"}]
    assert not notes.changed([{"id": "F1", "text": "a"}, {"id": "I1", "text": "최근 90일 … 807건"}], old, held=True)
    assert notes.changed([{"id": "F1", "text": "a"}, {"id": "I1", "text": "x"}, {"id": "I2", "text": "새 5% 보고"}], old, held=True)


def test_fill_allows_insider_values_verbatim():
    by = {"I1": {"id": "I1", "text": "x", "tone": 0, "slots": {"기간": "최근 90일", "늘린보고": "8건", "줄인보고": "1건"}}}
    ok = "최근 90일 동안 보유 주식을 늘린 보고가 8건, 줄인 보고가 1건 있었어요."
    assert notes.fill({"text": ok, "refs": ["I1"]}, by)["text"] == ok
    with pytest.raises(ValueError):  # 사실에 없는 값은 여전히 안 된다
        notes.fill({"text": "늘린 보고가 9건 있었어요.", "refs": ["I1"]}, by)
    with pytest.raises(ValueError):  # I 를 근거로 들지 않은 문장에선 안 된다
        notes.fill({"text": "늘린 보고가 8건 있었어요.", "refs": []}, by)
    assert notes.dedupe("소식이에요(「A」 · 「B」). 끝") == "소식이에요. 끝"


def test_business_summary_numbers_must_be_in_source():
    src = "2025년 매출은 DX 부문이 56.3%, DS 부문이 39.0%입니다. 반도체 가격 변동이 위험합니다."
    ok = notes.check_business({"what": ["TV와 반도체를 팔아요."], "risks": ["회사는 반도체 가격 변동을 위험으로 꼽아요."],
                               "segments": [{"name": "DX 부문", "share": "56.3%"}, {"name": "은행", "share": "약 585조원"}]}, src)  # fmt: skip
    assert ok["segments"] == [{"name": "DX 부문", "share": "56.3%"}]  # % 가 아닌 줄은 버린다
    with pytest.raises(ValueError):  # 원문에 없는 숫자
        notes.check_business({"what": ["매출이 70% 늘었어요."], "risks": [], "segments": []}, src)
    with pytest.raises(ValueError):  # 예측 말투
        notes.check_business({"what": ["앞으로 오를 것 같아요."], "risks": [], "segments": []}, src)


def test_parse_report_skips_table_of_contents_and_dividends():
    xml = ('<TD>1. 사업의 개요</TD><TD>목차</TD>'
           '<TITLE ATOC="Y">1. 사업의 개요</TITLE><P>반도체를 만들어요.</P><TITLE ATOC="Y">3. 원재료</TITLE>'
           '<TITLE ATOC="Y">7. 기타 참고사항</TITLE><P>경쟁이 심해요.</P><TITLE ATOC="Y">III. 재무에 관한 사항</TITLE>')  # fmt: skip
    r = sources.parse_report(xml)
    assert "반도체를 만들어요" in r["overview"] and "목차" not in r["overview"] and "경쟁이 심해요" in r["etc"]
    rows = [{"se": "주당 현금배당금(원)", "stock_knd": "보통주", "thstrm": "1,668", "frmtrm": "1,446", "lwfr": "-"},
            {"se": "현금배당금총액(백만원)", "thstrm": "11,107,906", "frmtrm": "9,810,767", "lwfr": "-"},
            {"se": "(연결)현금배당성향(%)", "thstrm": "25.10", "frmtrm": "29.20", "lwfr": "-"}]  # fmt: skip
    assert sources.parse_dividends(rows, 2025) == [(2025, 1668, 11107906000000, 25.1), (2024, 1446, 9810767000000, 29.2)]


def test_josa_ro_and_broken_direction_rejected():
    assert notes.josa("1.5조원", "로") == "으로" and notes.josa("서울", "로") == "로" and notes.josa("3.5%", "로") == "로"
    by = {"F1": {"id": "F1", "text": "x", "tone": 1, "slots": {"값": "1.5조원", "폭": "3.5%", "방향": "늘었"}}}
    assert notes.fill({"text": "매출은 {F1.값}로 {F1.폭} {F1.방향}어요.", "refs": ["F1"]}, by)["text"] == "매출은 1.5조원으로 3.5% 늘었어요."
    with pytest.raises(ValueError):
        notes.fill({"text": "매출이 {F1.폭}{F1.방향} 늘었고", "refs": ["F1"]}, by)


def test_article_check_rules():
    from hanjang import articles

    fs = [{"id": "E1", "text": "9월 15일 국민연금공단의 5% 이상 대량보유 보고 — 보유 비율 7.10%", "url": "u", "tone": 0,
           "doc": "보유주식 등의 수 | 12,345,678 | 보고사유 | 단순 변동 || 큰 숫자 읽기: 12,345,678 → 1,234만 5,678"},
          {"id": "F1", "text": "2025년 매출 10조원", "url": "u", "tone": 1}]  # fmt: skip
    s = lambda t, r=("E1",): {"text": t, "refs": list(r)}  # noqa: E731
    long = "국민연금공단이 이 회사 주식을 5% 넘게 가지고 있다고 다시 알렸어요. " * 26
    ok = {"title": "국민연금, 보유 주식을 늘렸어요", "paragraphs": [
        s("9월 15일에 국민연금공단이 보고했어요."), s(long), s("보유 주식은 1,234만 5,678주예요."), s("2025년 매출은 10조원이에요.", ("F1",))]}
    assert articles.check(ok | {"title": "국민연금, 7.10% 보유"}, fs)  # 원문에 있는 숫자는 제목에도
    assert articles.check(ok, fs)["paragraphs"][0]["text"] == "9월 15일에 국민연금공단이 보고했어요."  # 원문(doc) 숫자는 그대로 옮겨도 된다
    for bad in ({"title": "국민연금, 주식 더 샀다"}, {"title": "실적에 긍정적일까"}, {"title": "3배 늘었다"}, {"title": "국민연금, 99% 늘렸다"},
                {"paragraphs": ok["paragraphs"] + [s("보유 주식이 20,000,000주예요.")]},  # 재료에 없는 숫자
                {"paragraphs": [ok["paragraphs"][0], ok["paragraphs"][2], ok["paragraphs"][3]]}):  # 너무 짧음
        with pytest.raises(ValueError):
            articles.check(ok | bad, fs)
    assert "1,645억" in articles.clean_doc(".x{a:b} 한화/공시 | 금액 | 164,500,200,000 ※ 관련공시 | 뒤")  # 큰 숫자 읽기
def test_quoting_a_news_title_is_rejected():
    fs = [{"id": "N1", "text": "10월 8일 연합뉴스 소식 「삼성 실적 신기록」 — 영업이익 107조", "tone": 0, "url": "https://n",
           "slots": {"날짜": "10월 8일", "매체": "연합뉴스", "제목": "「삼성 실적 신기록」"}}]
    note = lambda t: {"headline": "h", "summary": [{"text": t, "refs": ["N1"]}], "sections": [], "good": [], "concern": []}  # noqa: E731
    with pytest.raises(ValueError, match="제목 인용"):
        notes.check_note(note("「삼성 실적 신기록」이라는 보도가 있었어요."), fs)
    notes.check_note(note("영업이익이 107조라는 보도가 있었어요."), fs)


def test_unit_after_slot_is_not_doubled():
    by = {"I1": {"id": "I1", "text": "x", "tone": 0, "url": "u", "slots": {"늘린보고": "765건", "줄인보고": "41건"}}}
    assert notes.fill({"text": "늘린 보고가 {I1.늘린보고}건, 줄인 보고가 {I1.줄인보고} 있었어요.", "refs": ["I1"]}, by)["text"] == "늘린 보고가 765건, 줄인 보고가 41건 있었어요."


def test_story_facts_say_where_this_year_stands():
    fin = [(2025, 300, 30, 0, 0, 0, "r", "CFS"), (2024, 250, 10, 0, 0, 0, "r", "CFS"), (2023, 200, -5, 0, 0, 0, "r", "CFS")]
    f5, f6 = notes.story_facts(fin, "u", "2025년")
    assert f5["slots"] == {"연도": "2025년", "비율": "10.0%", "백원당": "10원", "전년비율": "4.0%", "전년연도": "2024년"}
    assert f6["slots"]["매출자리"] == "가장 많았" and f6["slots"]["이익바닥해"] == "2023년" and f6["slots"]["기간"] == "2023~2025년"


def test_numbers_copied_from_cited_fact_are_ok_but_made_up_ones_are_not():
    by = {f["id"]: f for f in notes.facts(_con(), "005930", date(2026, 10, 7))}
    f1 = by["F1"]["slots"]["값"]
    assert notes.fill({"text": f"매출은 {f1}이었어요.", "refs": ["F1"]}, by)  # 근거 사실에 그대로 있는 숫자
    assert notes.fill({"text": "100원어치 팔면 남는 돈이 늘었어요.", "refs": ["F1"]}, by)  # 셈의 단위
    with pytest.raises(ValueError, match="빈칸으로만"):
        notes.fill({"text": "매출은 999조원이었어요.", "refs": ["F1"]}, by)  # 지어낸 숫자


def test_code_note_reads_like_sentences_and_titles_are_tidy():
    assert notes.tidy("[기재정정]연결재무제표기준영업(잠정)실적(공정공시)") == "연결재무제표기준영업(잠정)실적"
    fs = notes.facts(_con(), "005930", date(2026, 10, 7))
    text = " ".join(x["text"] for sec in notes.code_note(fs)["sections"] for x in sec["sentences"])
    assert "무슨 일:" not in text and "[기재정정]" not in text and text.count("요.") >= 2


def test_numbers_read_like_people_read_them():
    assert notes.korean_num(968091) == "96만 8,091" and notes.korean_num(12345678) == "1,234만 5,678"
    assert notes.korean_num(164500200000) == "1,645억 20만" and notes.korean_num(1234) == "1,234" and notes.korean_num(100000) == "10만"
    assert notes.LONGNUM.search("발행가 164,500,200,000원") and not notes.LONGNUM.search("1,645억 원 · 96만 8,091주 · 8,622억원")


def test_one_bad_sentence_is_dropped_not_the_whole_note():
    fs = notes.facts(_con(), "005930", date(2026, 10, 7))
    ok = [{"text": "{F1.연도} 매출이 {F1.방향}어요.", "refs": ["F1"]}] * 4
    j = {"headline": "많이 팔았어요.", "summary": ok, "sections": [{"title": "회사 사정은 어떤가요?", "sentences": ok + [{"text": "매출이 999조원이에요.", "refs": ["F1"]}]}],
         "good": [{"text": f["text"], "refs": [f["id"]]} for f in fs if f["tone"] == 1][:1],
         "concern": [{"text": f["text"], "refs": [f["id"]]} for f in fs if f["tone"] == -1][:1], "good_title": "좋은 점", "concern_title": "걱정되는 점"}
    note = notes.fill_note(j, fs)
    assert len(note["sections"][0]["sentences"]) == 4  # 지어낸 숫자 문장만 빠졌다


def test_joins_read_naturally():
    by = {"F6": {"id": "F6", "text": "최근 5년 가운데", "tone": 0, "url": "u", "slots": {"매출자리": "가장 많았", "기간": "최근 5년"}},
          "F5": {"id": "F5", "text": "2024년 10.9%", "tone": 0, "url": "u", "slots": {"전년비율": "10.9%"}},
          "F1": {"id": "F1", "text": "2025년 매출 10조원", "tone": 1, "url": "u", "slots": {"연도": "2025년"}}}
    assert notes.fill({"text": "매출이 {F6.매출자리}인 해예요.", "refs": ["F6"]}, by)["text"] == "매출이 가장 많았던 해예요."
    assert notes.fill({"text": "최근 {F6.기간} 동안이에요.", "refs": ["F6"]}, by)["text"] == "최근 5년 동안이에요."
    assert notes.fill({"text": "전년엔 {F5.전년비율}이었으니 세졌어요.", "refs": ["F5"]}, by)["text"] == "전년엔 10.9%였으니 세졌어요."
    assert notes.fill({"text": "매출은 최근 5년 중 가장 많았어요.", "refs": ["F1"]}, by)  # 작은 정수는 다른 사실에서 와도 된다


def test_hidden_arithmetic_words_are_caught():
    for t in ("빚이 자기 돈보다 두 배 넘게 많아요", "절반이 반도체예요", "3분의 1 수준이에요", "2배 늘었어요", "삼분의 일이에요"):
        assert notes.CALC.search(t), t
    for t in ("배당을 했어요", "배를 만드는 회사예요", "선박 2척을 수주했어요"):
        assert not notes.CALC.search(t), t


def test_cost_report_sums_by_day_and_job():
    from hanjang import cost

    lines = ["2026-10-08T07:01:00,writer:note,gpt-4.1,1000,500,0.020000",
             "2026-10-08T07:02:00,article:article,gpt-4.1,1000,500,0.015000",
             "2026-10-07T07:01:00,writer:note,gpt-4.1,1000,500,0.700000"]
    out = cost.report(lines, date(2026, 10, 8))
    assert "오늘 $0.04" in out and "이번 달 $0.73" in out and "노트 쓰기" in out and "피드 기사" in out


def test_quarter_industry_segment_facts():
    con = _con()
    con.execute("insert into quarters values ('005930', 2026, 2, 200, 50, 100, 10, 380, 90, 190, 20, 'r1', 'CFS')")
    f8, f9 = notes.quarter_facts(con, "005930")
    assert f8["slots"]["분기"] == "2026년 2분기" and f8["slots"]["매출방향"] == "늘었" and f8["slots"]["매출폭"] == "100.0%"
    assert "+100.0%" in f8["text"] and "1년 전 같은 분기보다" in f8["text"]
    assert f9["slots"]["기간"] == "2026년 1~6월" and "작년 같은 기간보다" in f9["text"]
    seg = notes.check_segments({"unit": "백만원", "rows": [
        {"name": "DS 부문", "revenue": "130,128,162", "op": "24,858,075", "revenue_prev": "", "op_prev": "15,094,486"},
        {"name": "내부거래 조정", "revenue": "(30,114,556)", "op": "0", "revenue_prev": "", "op_prev": ""}]},
        "DS 부문 | 130,128,162 | 24,858,075 | 15,094,486 | (30,114,556)", 2025)
    assert seg["rows"] == [{"name": "DS 부문", "revenue": 130_128_162_000_000, "op": 24_858_075_000_000, "revenue_prev": None, "op_prev": 15_094_486_000_000}]
    with pytest.raises(ValueError):  # 원문에 없는 값
        notes.check_segments({"unit": "백만원", "rows": [{"name": "A", "revenue": "1,111", "op": "", "revenue_prev": "", "op_prev": ""}]}, "2,222", 2025)


def test_tidy_broken_joins():
    assert notes.mend("매출은 4번째로 많았으로, 바닥이던 2021년년보다") == "매출은 4번째로 많았고, 바닥이던 2021년보다"
    assert notes.mend("영업이익률이 2번째로 높았였어요.") == "영업이익률이 2번째로 높았어요."
    assert notes.mend("국민연금이 주식을 줄였 보고를 했어요. 늘렸 보고했어요") == "국민연금이 주식을 줄였다는 보고를 했어요. 늘렸다고 보고했어요"
    assert notes.mend("매출이 줄었어요(9.4% -9.4%).") == "매출이 줄었어요(-9.4%)."
    assert notes.mend("매출이 늘었고 2025년에는") == "매출이 늘었고 2025년에는"
    assert notes.mend("(매출 10.9% 늘었 · 영업이익 33.2% 줄었)") == "(매출 10.9% 증가 · 영업이익 33.2% 감소)"


def test_relation_says_what_numbers_mean():
    r = notes.relation(130, 100, 123, 100)
    assert r == {"백원당": "95원", "전년백원당": "100원", "관계": "판 돈이 늘어난 만큼은 남긴 돈이 늘지 않았"}
    assert notes.relation(110, 100, 150, 100)["관계"] == "판 돈보다 남긴 돈이 더 빨리 늘었"
    assert notes.relation(90, 100, 80, 100)["관계"] == "판 돈도 남긴 돈도 줄었"
    assert "관계" not in notes.relation(100, None, 10, None)


def test_relation_slot_is_not_wrapped_twice():
    by = {"F8": {"id": "F8", "text": "2026년 2분기(4~6월) 매출 1.3조원(1년 전 같은 분기보다 +30.2%)", "tone": 0,
                 "slots": {"분기": "2026년 2분기", "관계": "판 돈이 늘어난 만큼은 남긴 돈이 늘지 않았"}}}
    got = notes.fill({"text": "{F8.분기}엔 판 돈보다 남긴 돈이 더 빨리 {F8.관계}어요.", "refs": ["F8"]}, by)
    assert got["text"] == "2026년 2분기엔 판 돈이 늘어난 만큼은 남긴 돈이 늘지 않았어요."
    assert notes.mend("줄인 보고가 1건 있었어요(1건).") == "줄인 보고가 1건 있었어요."


def test_reading_checks_hard_words_cut_stems_and_repeats():
    fs = [{"id": "F1", "text": "2025년 매출 9.0조원", "tone": 0, "slots": {}}, {"id": "N1", "text": "유상증자 기사", "tone": 0, "slots": {}}]
    ok = {"text": "새 주식을 찍어 팔아 돈을 모으기로 했어요(유상증자).", "refs": ["F1"]}
    notes.check_sentence(ok, fs)
    notes.check_sentence({"text": "기사는 유상증자 이야기를 해요.", "refs": ["N1"]}, fs)  # 소식만 근거면 그 말을 옮겨도 된다
    for bad in ("유상증자 신주 발행가액 공시도 있었어요.", "매출은 4번째로 많았 바닥보다는 올라왔어요.",
                "DS 부문 영업이익이 많았는데 DS 부문 영업이익이 가장 컸어요."):
        with pytest.raises(ValueError):
            notes.check_sentence({"text": bad, "refs": ["F1"]}, fs)


def test_relation_only_from_slot_and_same_day_must_match():
    by = {"F8": {"id": "F8", "text": "2026년 2분기 매출 1.3조원", "tone": 0, "slots": {"관계": notes.RELATIONS[1]}}}
    with pytest.raises(ValueError):
        notes.fill({"text": "판 돈보다 남긴 돈이 더 빨리 늘었어요.", "refs": ["F8"]}, by)
    fs = [{"id": "D1", "text": "10월 8일 실적 공시", "tone": 0, "url": "u", "slots": {"날짜": "10월 8일"}},
          {"id": "D2", "text": "7월 30일 배당 공시", "tone": 0, "url": "u", "slots": {"날짜": "7월 30일"}}]
    j = {"headline": "소식", "summary": [], "good": [], "concern": [], "good_title": "", "concern_title": "",
         "sections": [{"title": "이번 주 소식", "sentences": [{"text": "실적을 미리 알렸어요.", "refs": ["D1"]},
                                                          {"text": "같은 날 배당도 정했어요.", "refs": ["D2"]},
                                                          {"text": "그 전에 배당을 정했어요.", "refs": ["D2"]}]}]}
    with pytest.raises(ValueError):  # 셋 중 하나 탈락 = 30% 넘음 → 다시 쓰게
        notes.fill_note(j, fs)


def test_bond_fact_sums_one_filing_and_names_its_use():
    con = _con()
    con.executemany("insert into bonds values (?, ?, '005930', '2026-10-21', ?, ?, ?, '신한투자증권', ?)",
                    [("r1", "1", 50_000_000_000, "2028-10-20", None, '{"채무상환자금": 50000000000}'),
                     ("r1", "2", 100_000_000_000, "2029-10-19", "3.52", '{"채무상환자금": 80000000000, "운영자금": 20000000000}')])
    [f] = notes.bond_fact(con, "005930", date(2026, 10, 9))
    assert f["text"] == "10월 21일 회사채 1,500억원 납입 예정 — 만기 2년·3년 · 이자 연 3.52% · 쓰임: 빚 갚기(채무상환자금) 1,300억원 · 회사 운영(운영자금) 200억원"
    assert f["id"] == "F12" and f["tone"] == 0 and f["slots"]["금액"] == "1,500억원"
    assert any(x["id"] == "F12" for x in notes.facts(con, "005930", date(2026, 10, 9)))
    assert notes.bond_fact(con, "005930", date(2027, 3, 1)) == []  # 90일 지나면 빠진다


def test_no_credit_falls_back_to_code_without_more_calls(monkeypatch):
    from hanjang import llm
    calls = []

    def broke(*a, **k):
        calls.append(1)
        raise RuntimeError("OpenAI 크레딧 소진")
    monkeypatch.setattr(llm, "_openai", broke)
    monkeypatch.setitem(llm.spent, "no_credit", False)
    fs = notes.facts(_con(), "005930", date(2026, 10, 7))
    assert notes.write("삼성전자", fs, date(2026, 10, 7))[1] == "code" and notes.write("삼성전자", fs, date(2026, 10, 7))[1] == "code"
    assert len(calls) == 1  # 한 번 막히면 그 뒤로는 묻지 않는다
