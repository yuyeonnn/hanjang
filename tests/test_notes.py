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


def test_finish_always_shows_both_sides():
    fs = notes.facts(_con(), "005930", date(2026, 10, 7))  # 걱정 사실 없음
    note = notes.finish({"headline": "x", "summary": [], "sections": [], "good": [], "concern": []}, fs)
    assert "걱정되는 쪽으로 분류된 건 없었어요" in note["concern"][0]["text"] and note["tone_rule"]
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
