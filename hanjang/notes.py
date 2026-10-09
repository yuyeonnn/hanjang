"""주간 노트 만들기 ②~⑥ (PRD §5.2): 공시 읽기(규칙→AI) → 사실 묶음(코드) → 쓰기(AI) → 검사 → 저장.
`python -m hanjang.notes [종목코드 …]` — 비우면 전 종목. 같은 주에 다시 돌리면 덮어쓴다.
**숫자와 늘었다/줄었다는 AI 가 쓰지 않는다.** AI 는 `{F1.값}` 같은 빈칸만 쓰고 코드가 채운다 —
AI 글에 숫자가 하나라도 있거나, 사실과 반대 방향 낱말을 쓰면 글째 버린다."""

import json
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta

from hanjang import db, llm, sources

DART = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"
TAXONOMY = ("RIGHTS_ISSUE", "BONUS_ISSUE", "SPLIT", "REVERSE_SPLIT", "BUYBACK", "CB_BW",
            "MAJOR_CONTRACT", "EARNINGS", "DIVIDEND", "LAWSUIT", "MA", "HOLDER_CHANGE",
            "CLINICAL", "TRADING_HALT", "OTHER")  # fmt: skip
EVENT_KO = {
    "RIGHTS_ISSUE": "유상증자", "BONUS_ISSUE": "무상증자", "SPLIT": "액면분할",
    "REVERSE_SPLIT": "감자·병합", "BUYBACK": "자사주 매입", "CB_BW": "전환사채·신주인수권",
    "MAJOR_CONTRACT": "대형 계약", "EARNINGS": "실적", "DIVIDEND": "배당", "LAWSUIT": "소송",
    "MA": "합병·인수", "HOLDER_CHANGE": "대주주 지분 변동", "CLINICAL": "임상",
    "TRADING_HALT": "거래정지·관리", "OTHER": "기타",
}  # fmt: skip
# 주주에게 반가운(+1)/걸리는(−1) 쪽 — 퀀트점프 S7 제목판 부호 그대로. 없으면 0
DIRECTION = {"RIGHTS_ISSUE": -1, "CB_BW": -1, "LAWSUIT": -1, "TRADING_HALT": -1,
             "BUYBACK": 1, "BONUS_ISSUE": 1, "MAJOR_CONTRACT": 1}  # fmt: skip
# 제목만 보고 확정되는 공시 — 거래소·금감원 서식 이름 그대로라 AI 에게 묻지 않는다 (공백·가운뎃점 제거 뒤 대조).
# 순서대로 첫 번째가 이긴다. 여기 없는 제목만 AI 가 분류한다
TITLE_RULES = (
    (r"최대주주등소유주식변동", "OTHER", 1),
    (r"자기주식(취득|소각)|주식소각결정|자기주식취득신탁계약체결", "BUYBACK", 3),
    (r"(?<!무)유상증자결정", "RIGHTS_ISSUE", 3),
    (r"무상증자결정", "BONUS_ISSUE", 3),
    (r"(전환사채권|신주인수권부사채권|교환사채권)발행결정", "CB_BW", 3),
    (r"(현금현물|현금|주식)배당결정", "DIVIDEND", 2),
    (r"단일판매공급계약체결", "MAJOR_CONTRACT", 2),
    (r"영업\(잠정\)실적|매출액또는손익구조", "EARNINGS", 2),
    (r"소송등의(제기|판결)", "LAWSUIT", 3),
    (r"회사(분할)?합병결정|회사분할결정|영업(양수|양도)결정|주식(의포괄적)?교환|타법인주식및출자증권(취득|양수)결정", "MA", 2),
    (r"주식분할결정", "SPLIT", 2),
    (r"주식병합결정|감자결정", "REVERSE_SPLIT", 3),
    (r"최대주주변경", "HOLDER_CHANGE", 2),
    # 코스닥에 잦은 거래소 경고 — 불성실공시·투자주의환기·상장 유지 심사
    (r"매매거래정지(?!해제)|관리종목지정|상장폐지|감사의견(거절|부적정|한정)|불성실공시법인|투자주의환기종목|상장적격성실질심사", "TRADING_HALT", 3),
    (r"사업보고서|반기보고서|분기보고서|기업설명회", "OTHER", 1),
)
# 공시 제목 → 「무슨 일인지」 쉬운 말 (우리가 쓴 고정 문장, 숫자 없음). 첫 번째로 맞는 것을 쓴다.
# AI 가 「자사주 매입 공시」라는 이름만 반복하지 않고 뜻을 풀어 쓰게 하려고 사실에 붙인다
TITLE_PLAIN = (
    # 거래소 경고가 먼저 — 「매매거래정지(합병…)」처럼 다른 말이 섞여도 경고를 알린다
    (r"매매거래정지해제", "멈췄던 사고팔기가 다시 열렸어요"),
    (r"매매거래정지", "거래소가 이 회사 주식의 사고팔기를 잠시 멈췄어요"),
    (r"관리종목지정", "거래소가 관리종목으로 정했어요 — 상장을 이어 갈 요건을 채우지 못했다는 경고예요"),
    (r"불성실공시법인", "알려야 할 일을 늦게 알리거나 뒤집어서, 거래소가 불성실공시법인으로 정했어요"),
    (r"투자주의환기종목", "거래소가 투자에 주의하라고 따로 표시한 종목이 됐어요"),
    (r"상장적격성실질심사", "거래소가 이 회사가 계속 상장해 있어도 되는지 따져 보기로 했어요"),
    (r"상장폐지", "상장 폐지와 관련된 공시예요 — 주식이 시장에서 빠질 수 있어요"),
    (r"자기주식취득신탁계약", "증권사에 돈을 맡겨 자기 회사 주식을 조금씩 사들이기로 했어요"),
    (r"자기주식취득결정", "회사가 시장에서 자기 회사 주식을 사들이기로 했어요 — 시중에 도는 주식이 줄어요"),
    (r"자기주식처분", "회사가 갖고 있던 자기 회사 주식을 팔거나 나눠 주기로 했어요"),
    (r"주식소각|자기주식소각", "회사가 갖고 있던 자기 주식을 아예 없애기로(소각) 했어요 — 전체 주식 수가 줄어요"),
    (r"(?<!무)유상증자결정", "새 주식을 찍어 팔아 돈을 모으기로 했어요 — 주식 수가 늘어 기존 주주 몫이 묽어질 수 있어요"),
    (r"발행가액|발행가격", "새로 찍는 주식을 한 주에 얼마에 팔지 값이 정해졌어요"),
    (r"증권신고서", "주식·채권을 팔기 전에 금융감독원에 내는 신고서예요 — 얼마를 왜 모으는지 적혀 있어요"),
    (r"결산실적공시예고", "1년 실적을 언제 발표할지 미리 알렸어요"),
    (r"기업설명회", "투자자에게 회사를 설명하는 자리(IR)를 연다고 알렸어요"),
    (r"발행결과", "앞서 정한 증자·채권 발행을 실제로 마쳤다는 결과 보고예요"),
    (r"무상증자결정", "주주에게 새 주식을 공짜로 나눠 주기로 했어요"),
    (r"전환사채권발행결정", "나중에 주식으로 바꿀 수 있는 채권(전환사채)을 팔아 돈을 빌리기로 했어요"),
    (r"신주인수권부사채권발행결정", "새 주식을 살 권리가 붙은 채권을 팔아 돈을 빌리기로 했어요"),
    (r"교환사채권발행결정", "회사가 가진 다른 주식으로 바꿔 줄 수 있는 채권을 팔아 돈을 빌리기로 했어요"),
    (r"배당결정", "번 돈의 일부를 주주에게 배당으로 나눠 주기로 했어요"),
    (r"주주명부폐쇄|기준일설정", "배당 등을 받을 주주를 정하는 기준일을 알렸어요"),
    (r"영업\(잠정\)실적|매출액또는손익구조", "최근 실적(매출·이익)을 미리 알렸어요"),
    (r"단일판매공급계약", "큰 판매·공급 계약을 맺었어요"),
    (r"소송등의제기", "회사가 소송을 걸었거나 소송을 당했어요"),
    (r"소송등의판결", "진행 중이던 소송에 판결이 나왔어요"),
    (r"합병", "다른 회사와 합치기로 했어요"),
    (r"분할", "회사의 일부 사업을 떼어 내기로 했어요"),
    (r"타법인주식및출자증권(취득|양수)", "다른 회사의 주식을 사서 지분을 갖기로 했어요"),
    (r"최대주주변경", "가장 큰 주주가 바뀌었어요"),
)


def korean_num(n: int) -> str:
    """사람이 읽는 숫자 — 968091 → 「96만 8,091」 · 12345678 → 「1,234만 5,678」 · 1234 → 「1,234」. 정확한 값 그대로(반올림 없음)."""
    sign, n = ("-" if n < 0 else ""), abs(n)
    if n < 10_000:
        return f"{sign}{n:,}"
    man, rest = divmod(n, 10_000)
    eok, man = divmod(man, 10_000)
    parts = ([f"{eok:,}억"] if eok else []) + ([f"{man:,}만"] if man else []) + ([f"{rest:,}"] if rest else [])
    return sign + " ".join(parts)


# AI 가 몰래 한 셈 — 「두 배 넘게」「절반」「3분의 1」. 숫자 검사를 피해 가는 말이라 따로 막는다 (계산은 코드만, 불변식 2)
CALC = re.compile(r"(?<![가-힣])(한|두|세|네|다섯|여섯|일곱|여덟|아홉|열|몇|수십|\d+)\s?배|절반|(\d+|[이삼사오육칠팔구십])\s?분의\s?(\d+|[일이삼사오육칠팔구])")

# 자릿수가 긴 날숫자(「164,500,200,000」) — 사람이 읽기 힘들다. 글에 나오면 탈락 (사용자 10/8)
LONGNUM = re.compile(r"(?<![\d,.])\d{1,3}(?:,\d{3}){2,}(?![\d,])")


def tidy(title: str) -> str:
    """공시 제목 → 사람이 읽을 이름 — 「[기재정정]」 같은 머리표, 「(공정공시)」 같은 서식 꼬리표, 띄어쓰기 없는 붙은 말을 정리."""
    t = re.sub(r"^\s*\[[^\]]*\]\s*", "", title)
    t = re.sub(r"\((공정공시|안내공시|자율공시|[^()]*주요경영사항|\d{4}년\s*\d분기)\)", "", t)
    return re.sub(r"\s+", " ", t).strip()


def plain(title: str) -> str:
    t = re.sub(r"[\s·ㆍ・]", "", title)
    return next((s for pat, s in TITLE_PLAIN if re.search(pat, t)), "")


# 제목이 코드 정의와 반대인 것 — 규칙·AI 분류 뒤에 덧씌운다 (퀀트점프 RECODE 중 자주 걸리는 것)
RECODE = (
    (("BUYBACK",), "처분|해지|매도", "OTHER"),
    (("MAJOR_CONTRACT",), "해지", "OTHER"),
    (("CB_BW",), r"취득|청구권.{0,20}행사|자기\S*사채매도", "OTHER"),
    (("CB_BW",), "자본으로인정되는채무증권|조건부자본증권", "OTHER"),  # 은행 신종자본·코코본드
    (("DIVIDEND",), "주주명부폐쇄|기준일설정", "OTHER"),
    (("HOLDER_CHANGE",), "최대주주등소유주식변동", "OTHER"),
)
# 「사라」는 앞에 한글이 붙으면 낱말 일부다(인사라고·회사라서) — 따로 선 「사라」만.
# 「목표가」는 「수주·매출·판매 목표가」(회사 사업 목표)면 주가 목표가 아니다.
FORBIDDEN = re.compile(r"매수|매도|(?<![가-힣])(사라|사세요|팔아라|파세요)|비중|목표\s*주가"
                       r"|(?<!수주 )(?<!수주)(?<!매출 )(?<!판매 )목표가|예측|오를\s*것|내릴\s*것|유망|추천")
# 좋게 본 것(+1)·걱정되는 것(−1)은 코드가 정한다 — AI 가 고르지 않는다. 화면에 이 기준을 그대로 밝힌다
DEBT_GOOD, DEBT_BAD = 100, 200  # 부채비율 %
ROE_GOOD = 10  # %. 0 미만(적자)은 걱정
TONE_RULE = ("좋게 본 것·걱정되는 것은 코드가 정한 기준으로 나눴어요 — 매출·영업이익이 늘었나 줄었나, 흑자·적자 전환, "
             f"부채비율 {DEBT_GOOD}% 미만·{DEBT_BAD}% 초과, ROE {ROE_GOOD}% 이상·0% 미만, "
             "공시 종류(자사주 매입·대형 계약 / 증자·전환사채·소송·거래정지).")
# 예측 말투 — 지난 사실을 「~할 전망」으로 쓰면 틀린 말이고 예측이 된다 (불변식 1). 기사(N)만 근거인 문장은
# 「기사는 ~라고 써요」로 남의 전망을 옮기는 자리라 예외
PREDICT = re.compile(r"전망이|전망돼|것으로 보여|것으로 보입|것 같아|예상돼|예상됩|할 거예요|될 거예요|일 거예요|가능성이 (높|커|있)")
# AI 가 직접 쓴 방향 낱말 — 빈칸 {F.방향} 을 안 쓰고 스스로 「늘었어요」라 쓴 경우 사실과 맞는지 본다
UP = re.compile(r"늘|증가|커졌|많아졌|올랐|개선|흑자로")
DOWN = re.compile(r"줄|감소|작아졌|적어졌|내렸|악화|떨어|적자로")
SLOT = re.compile(r"\{([A-Z]\d+)\.([가-힣]+)\}")
# 읽기 검사 (사용자 10/9: 깨진 이음·되풀이·어려운 말이 하나라도 있으면 안 된다) — 걸리면 다시 쓰게 한다
HARD = re.compile(r"유상증자|신주|발행가액|공정공시|기재정정|단일판매|전환사채|자기주식|잠정실적|결산실적")  # 괄호 밖에서 — 쉬운 말로 바꿔 쓴다
STEM = re.compile(r"(늘었|줄었|많았|적었|높았|낮았|돌아섰|이어졌|늘렸|줄였)(?![어고는지으다던기을거네죠습음])")  # 줄기 뒤에 끝이 없음
REPEAT = re.compile(r"([가-힣][가-힣 ]{6,}[가-힣])[^.]*?\1")  # 한 문장 안에서 같은 말(8자 넘게)이 두 번
TITLES = ("회사 사정은 어떤가요?", "올해 장사는 어떤가요?", "이번 주 소식", "임원·큰손은 어떻게 움직였나요?")  # 소식 = 공시(D) + 뉴스룸·언론 RSS(N)
NEWS_DAYS = 7
EVENT_DAYS = 90


# --- ② 공시 읽기: 서식 이름 규칙 → 나머지만 AI ---


def by_rule(title: str) -> tuple[str, int] | None:
    t = re.sub(r"[\s·ㆍ・]", "", title)
    for pat, code, imp in TITLE_RULES:
        if re.search(pat, t):
            return code, imp
    return None


def recode(code: str, title: str) -> str:
    t = title.replace(" ", "")
    for codes, pat, new in RECODE:
        if (codes is None or code in codes) and re.search(pat, t):
            return new
    return code


def _save_code(con, rno: str, title: str, code: str, imp: int, how: str) -> None:
    code = recode(code, title)
    con.execute("update disclosures set code = ?, importance = ?, direction = ?, read_model = ?, read_at = ?"
                " where rcept_no = ?", (code, imp, DIRECTION.get(code, 0), how, datetime.now().isoformat(), rno))  # fmt: skip


BUSINESS_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["what", "segments", "risks"],
                   "properties": {"what": {"type": "array", "items": {"type": "string"}},
                                  "risks": {"type": "array", "items": {"type": "string"}},
                                  "segments": {"type": "array", "items": {
                                      "type": "object", "additionalProperties": False, "required": ["name", "share"],
                                      "properties": {"name": {"type": "string"}, "share": {"type": "string"}}}}}}  # fmt: skip


def check_business(j: dict, source: str) -> dict:
    """사업보고서 요약 검사 — 숫자는 원문에 글자 그대로 있어야 하고, 금지어·예측 말투 없이. 어기면 ValueError(다시 묻는다)."""
    have = numbers(source)
    out = {"what": j["what"][:3], "segments": [], "risks": j["risks"][:4]}
    for s in out["what"] + out["risks"]:
        if bad := numbers(s) - have:
            raise ValueError(f"원문에 없는 숫자 {bad}: {s!r}")
        if FORBIDDEN.search(s) or PREDICT.search(s):
            raise ValueError(f"금지어·예측: {s!r}")
    for seg in j["segments"][:5]:
        if not re.fullmatch(r"\d+(\.\d+)?%", seg["share"].strip()) or numbers(seg["share"]) - have or numbers(seg["name"]) - have:
            continue  # % 가 아니거나 원문에 없는 비중 줄은 버린다 (금융사는 자산 규모를 쓰는 일이 있다)
        out["segments"].append({"name": seg["name"].strip(), "share": seg["share"].strip()})
    if not out["what"]:
        raise ValueError("빈 요약")
    return out


def read_business(con: sqlite3.Connection, today: date, tickers: list[str] | None = None) -> int:
    """종목마다 지난해 사업보고서 「사업의 내용」을 한 번 읽어 둔다(같은 보고서는 다시 읽지 않는다). 읽은 수를 돌려준다."""
    year, n = today.year - 1, 0
    dart = sources.Dart()
    rows = con.execute("select s.ticker, b.body from stocks s left join business b using(ticker) where s.active = 1").fetchall()
    for t, body in rows:
        if (tickers and t not in tickers) or (body and json.loads(body).get("year") == year):
            continue
        rno, text = dart.business_text(t, year)
        if not rno:
            continue
        src = text["overview"] + "\n" + text["etc"]
        got = llm.ask("reader", "business", {"원문": src}, lambda j: check_business(j, src), BUSINESS_SCHEMA, prompt_file="business")
        if got:
            con.execute("insert or replace into business values (?, ?, ?, ?, ?)",
                        (t, rno, json.dumps(got | {"year": year}, ensure_ascii=False), llm.MODELS["reader"], datetime.now().isoformat()))  # fmt: skip
            con.commit()
            n += 1
    return n


SEGMENT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["unit", "rows"],
                  "properties": {"unit": {"type": "string"}, "rows": {"type": "array", "items": {
                      "type": "object", "additionalProperties": False, "required": ["name", "revenue", "op", "revenue_prev", "op_prev"],
                      "properties": {k: {"type": "string"} for k in ("name", "revenue", "op", "revenue_prev", "op_prev")}}}}}  # fmt: skip


def check_segments(j: dict, source: str, year: int) -> dict:
    """옮겨 적은 부문 숫자 검사 — 원문에 글자 그대로 있어야 한다. 코드가 원 단위로 바꾼다(괄호는 음수)."""
    if j["unit"] not in UNITS:
        raise ValueError(f"단위 {j['unit']!r}")
    have = numbers(source)

    def num(s):
        s = s.strip()
        if not s or s in ("-", "—"):
            return None
        if not re.fullmatch(r"\(?-?[\d,]+\)?", s) or numbers(s) - have:
            raise ValueError(f"원문에 없는 값 {s!r}")
        v = int(re.sub(r"[^\d]", "", s)) * UNITS[j["unit"]]
        return -v if s.startswith(("(", "-")) else v

    rows = [{"name": r["name"].strip(), "revenue": num(r["revenue"]), "op": num(r["op"]),
             "revenue_prev": num(r["revenue_prev"]), "op_prev": num(r["op_prev"])}
            for r in j["rows"][:6] if not re.search(r"합계|소계|조정|내부거래|기타", r["name"])]  # fmt: skip
    return {"year": year, "rows": rows}


def read_segments(con: sqlite3.Connection, today: date) -> int:
    """사업보고서의 「영업부문 정보」 표를 한 번 읽어 business.body["seg"] 에 둔다 — 같은 해는 다시 안 읽는다."""
    year, n, dart = today.year - 1, 0, sources.Dart()
    for t, body in con.execute("select ticker, body from business").fetchall():
        b = json.loads(body)
        if (b.get("seg") or {}).get("year") == year or b.get("year") != year:
            continue
        rno, text = dart.business_text(t, year)
        src = (text or {}).get("segment", "")
        got = llm.ask("reader", "segments", {"원문": src}, lambda j: check_segments(j, src, year), SEGMENT_SCHEMA, prompt_file="segments") if src else None
        b["seg"] = got or {"year": year, "rows": []}  # 못 읽어도 표시 — 매일 다시 내려받지 않게
        con.execute("update business set body = ? where ticker = ?", (json.dumps(b, ensure_ascii=False), t))
        con.commit()
        n += bool(got and got["rows"])
    return n


def read_disclosures(con: sqlite3.Connection, batch: int = 100) -> tuple[int, int]:
    """(규칙으로 확정, AI 로 분류). 규칙은 이미 AI 가 읽은 공시에도 다시 덮어쓴다 — 규칙이 늘면 과거 공시도 고쳐진다.
    AI 가 빠뜨린 공시는 비워 두고 다음 실행에서 다시 묻는다."""
    ruled = 0
    for rno, title in con.execute("select rcept_no, title from disclosures where read_model is not 'rule'").fetchall():
        if got := by_rule(title):
            _save_code(con, rno, title, *got, "rule")
            ruled += 1
    con.commit()
    rows = con.execute("select rcept_no, title, date from disclosures where read_at is null").fetchall()
    done = 0
    schema = {"type": "object", "additionalProperties": False, "required": ["items"], "properties": {"items": {
        "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["i", "code", "importance"],
                                   "properties": {"i": {"type": "integer"}, "code": {"type": "string", "enum": list(TAXONOMY)},
                                                  "importance": {"type": "integer", "enum": [1, 2, 3]}}}}}}  # fmt: skip
    for k in range(0, len(rows), batch):
        part = rows[k : k + batch]
        got = llm.ask("reader", "title", [{"i": i, "title": t, "date": d} for i, (_, t, d) in enumerate(part)],
                      _check_titles(len(part)), schema)  # fmt: skip
        for i, code, imp in got or []:
            _save_code(con, part[i][0], part[i][1], code, imp, llm.MODELS["reader"])
            done += 1
        con.commit()
    return ruled, done


def _check_titles(n: int):
    def check(j):
        seen, out = set(), []
        for x in j["items"]:
            i = x.get("i")
            if (type(i) is int and 0 <= i < n and i not in seen and x.get("code") in TAXONOMY
                    and type(x.get("importance")) is int and x["importance"] in (1, 2, 3)):  # fmt: skip
                seen.add(i)
                out.append((i, x["code"], x["importance"]))
        if not out:
            raise ValueError("빈 분류")
        return out

    return check


# --- ④ 사실 묶음 (코드) — 문장(text)과 빈칸(slots)을 같이 만든다 ---


def won(x: int) -> str:
    """원 → 「333.6조원」 「5,583억원」. 노트의 모든 금액은 이 한 함수로."""
    if abs(x) >= 10**12:
        return f"{x / 10**12:,.1f}조원"
    if abs(x) >= 10**8:
        return f"{x / 10**8:,.0f}억원"
    return f"{x:,}원"


def pct(x: float) -> str:
    return f"{x * 100:+,.1f}%"  # 「+1,813.8%」 — 큰 변화도 읽히게


def trend(cur: int, prev: int | None) -> tuple[int, str, str]:
    """(좋고 나쁨, 방향 낱말 줄기, 변화 표시). 전년이 0 이하면 %가 뜻이 없다 → 흑자·적자 전환을 말로.
    방향 낱말은 뒤에 「어요」「고」「는데」를 붙여 쓰는 줄기 — 「늘었」+「어요」."""
    if prev is None or cur == prev:
        return 0, "", ""
    if prev > 0 and cur > 0:
        up = cur > prev
        return (1 if up else -1), ("늘었" if up else "줄었"), pct((cur - prev) / prev)
    if prev <= 0 < cur:
        return 1, "흑자로 돌아섰", "흑자 전환"
    if cur < 0 < prev:
        return -1, "적자로 돌아섰", "적자 전환"
    return -1, "적자가 이어졌", "적자 지속"


def story_facts(fin: list[tuple], url: str, yy: str) -> list[dict]:
    """「회사 사정」을 이야기로 쓰게 하는 재료 — 지표를 늘어놓지 않고 「지금 어떤 상황인지」 말하려면 필요하다 (사용자 10/8).
    F5 = 남기는 정도(100원 팔아 본업으로 몇 원) · F6 = 몇 년 흐름 속 올해의 자리. 계산은 코드가, 말은 AI 가. tone 은 중립(좋다·나쁘다는 F1~F4 가 정한다)."""
    out = []
    y, rev, oi = fin[0][0], fin[0][1], fin[0][2]
    if rev and oi is not None and rev > 0:
        m = oi / rev * 100
        slots = {"연도": yy, "비율": f"{m:.1f}%", "백원당": f"{round(m)}원"}
        prev = fin[1] if len(fin) > 1 else None
        if prev and prev[1] and prev[2] is not None and prev[1] > 0:
            slots |= {"전년비율": f"{prev[2] / prev[1] * 100:.1f}%", "전년연도": f"{prev[0]}년"}
        out.append({"id": "F5", "text": f"{yy} 영업이익률 {slots['비율']} — 100원어치 팔아 본업으로 {slots['백원당']}을 남김"
                    + (f" ({slots['전년연도']} {slots['전년비율']})" if "전년비율" in slots else ""), "url": url, "tone": 0, "slots": slots})  # fmt: skip
    rows = [r for r in fin if r[1] is not None or r[2] is not None]
    if len(rows) >= 3:
        span = f"{rows[-1][0]}~{rows[0][0]}년"
        slots = {"기간": span, "햇수": f"{len(rows)}년"}
        for key, idx, name in (("매출", 1, "매출"), ("이익", 2, "영업이익")):
            vals = [(r[0], r[idx]) for r in rows if r[idx] is not None]
            if len(vals) < 3:
                continue
            rank = sorted((v for _, v in vals), reverse=True).index(vals[0][1]) + 1
            low_y, low_v = min(vals, key=lambda t: t[1])
            slots[f"{key}자리"] = "가장 많았" if rank == 1 else "가장 적었" if rank == len(vals) else f"{rank}번째로 많았"
            if low_y != y:
                slots |= {f"{key}바닥해": f"{low_y}년", f"{key}바닥값": won(low_v)}
        text = f"최근 {slots['햇수']}({span}) 가운데 {yy}" + "".join(
            f" {name}은 {slots[k + '자리']}음" + (f"(가장 적었던 해 {slots[k + '바닥해']} {slots[k + '바닥값']})" if k + "바닥해" in slots else "")
            for k, name in (("매출", "매출"), ("이익", "영업이익")) if k + "자리" in slots)  # fmt: skip
        out.append({"id": "F6", "text": text, "url": url, "tone": 0, "slots": slots})
    return out


QLABEL = {1: ("1분기", "1~3월"), 2: ("2분기", "4~6월"), 3: ("3분기", "7~9월")}
UNITS = {"원": 1, "천원": 1_000, "백만원": 1_000_000, "억원": 100_000_000}


def _change(what: str, cur: int | None, prev: int | None, than: str) -> str | None:
    if cur is None:
        return None
    _, _, chg = trend(cur, prev)
    return f"{what} {won(cur)}" + (f"({than}보다 {chg})" if chg.startswith(("+", "-")) else f"({chg})" if chg else "")


def _slots(key: str, cur: int | None, prev: int | None) -> dict:
    """「{F8.매출}」「{F8.매출폭}」「{F8.매출방향}어요」 — 노트의 F1·F2 와 같은 빈칸 모양."""
    if cur is None:
        return {}
    _, way, chg = trend(cur, prev)
    return ({key: won(cur)} | ({f"{key}방향": way} if way else {})
            | ({f"{key}폭": chg.lstrip("+-")} if chg.startswith(("+", "-")) else {}))  # fmt: skip


def relation(rev: int | None, rp: int | None, op: int | None, opp: int | None) -> dict:
    """판 돈(매출)과 남긴 돈(영업이익)이 1년 전보다 어떻게 움직였나 — 말 줄기와 100원당 남긴 돈. 계산은 코드가, 말은 AI 가 옮긴다."""
    out = {}
    if rev and rev > 0 and op is not None:
        out["백원당"] = f"{round(op / rev * 100)}원"
        if rp and rp > 0 and opp is not None:
            out["전년백원당"] = f"{round(opp / rp * 100)}원"
    if rev and rp and rp > 0 and op is not None and opp and opp > 0:
        r, o = rev / rp - 1, op / opp - 1
        out["관계"] = (RELATIONS[0] if r > 0 and o > r else RELATIONS[1] if r > 0 and 0 <= o <= r else
                      RELATIONS[2] if r > 0 and o < 0 else RELATIONS[3] if r <= 0 and o > 0 else RELATIONS[4])  # fmt: skip
    return out


RELATIONS = ("판 돈보다 남긴 돈이 더 빨리 늘었", "판 돈이 늘어난 만큼은 남긴 돈이 늘지 않았",
             "더 많이 팔았지만 남긴 돈은 줄었", "덜 팔았지만 남긴 돈은 늘었", "판 돈도 남긴 돈도 줄었")  # fmt: skip
REL_WORDS = re.compile(r"판 돈보다 남긴 돈이 더|늘어난 만큼은? 남긴 돈|팔았지만 남긴 돈|판 돈도 남긴 돈도")


def quarter_facts(con: sqlite3.Connection, ticker: str) -> list[dict]:
    """F8 = 가장 최근 분기 3개월 · F9 = 올해 누적 — 둘 다 1년 전 같은 때와 견준다(분기 보고서가 같이 준다). 계산은 코드가."""
    row = con.execute("select year, q, revenue, operating_income, revenue_prev, op_prev, revenue_ytd, op_ytd, revenue_ytd_prev, op_ytd_prev,"
                      " rcept_no from quarters where ticker = ? order by year desc, q desc limit 1", (ticker,)).fetchone()  # fmt: skip
    if not row:
        return []
    y, q, rev, op, rp, opp, ry, oy, ryp, oyp, rno = row
    (name, months), url, out = QLABEL[q], DART.format(rno), []
    if parts := [x for x in (_change("매출", rev, rp, "1년 전 같은 분기"), _change("영업이익", op, opp, "1년 전 같은 분기")) if x]:
        out.append({"id": "F8", "text": f"{y}년 {name}({months}) " + " · ".join(parts), "url": url, "tone": 0,
                    "slots": {"분기": f"{y}년 {name}", "달": months} | _slots("매출", rev, rp) | _slots("이익", op, opp) | relation(rev, rp, op, opp)})  # fmt: skip
    if q >= 2 and (parts := [x for x in (_change("매출", ry, ryp, "작년 같은 기간"), _change("영업이익", oy, oyp, "작년 같은 기간")) if x]):
        out.append({"id": "F9", "text": f"{y}년 1~{q * 3}월 누적 " + " · ".join(parts), "url": url, "tone": 0,
                    "slots": {"기간": f"{y}년 1~{q * 3}월"} | _slots("매출", ry, ryp) | _slots("이익", oy, oyp) | relation(ry, ryp, oy, oyp)})  # fmt: skip
    return out


def industry_fact(con: sqlite3.Connection, ticker: str) -> list[dict]:
    """F10 = 같은 업종 회사들 가운데 자리 — 영업이익률(금융사는 ROE). 셋 이상 모일 때만. 순위·평균은 코드가 센다."""
    rows = con.execute(
        "select s.ticker, s.name, s.induty_code, f.fiscal_year, f.revenue, f.operating_income, f.net_income, f.equity, f.rcept_no"
        " from stocks s join financials f on f.ticker = s.ticker and f.fiscal_year = (select max(fiscal_year) from financials g where g.ticker = s.ticker)"
        " where s.active = 1").fetchall()  # fmt: skip
    me = next((r for r in rows if r[0] == ticker), None)
    label = me and sources.industry_label(me[2])
    if not label:
        return []
    # 매출이 없는 금융사는 금융사끼리만 — 「지주회사」로 묶인 KB금융과 SK 는 견줄 수 없다
    peers = [r for r in rows if sources.industry_label(r[2]) == label and r[3] == me[3] and (r[4] is None) == (me[4] is None)]
    label = "금융지주" if label == "지주회사" and me[4] is None else label
    margin = all(r[4] for r in peers)  # 매출이 다 있으면 영업이익률, 아니면(금융) ROE
    ok = (lambda r: r[4] and r[5] is not None) if margin else (lambda r: r[6] is not None and r[7] and r[7] > 0)
    val = {r[0]: (r[5] / r[4] * 100 if margin else r[6] / r[7] * 100) for r in peers if ok(r)}
    if len(val) < 3 or ticker not in val:
        return []
    order = sorted(val, key=lambda t: -val[t])
    k, n, what = order.index(ticker) + 1, len(val), "영업이익률" if margin else "ROE"
    place = "가장 높았" if k == 1 else "가장 낮았" if k == n else f"{k}번째로 높았"
    avg = sum(val.values()) / n
    others = "·".join(r[1] for r in peers if r[0] != ticker and r[0] in val)
    return [{"id": "F10", "text": f"같은 업종({label}) {n}곳 가운데 {me[3]}년 {what}{josa(what, '이')} {place}음 — {me[1]} {val[ticker]:.1f}% · {n}곳 평균 {avg:.1f}% (함께 본 회사: {others})",
             "url": DART.format(me[8]), "tone": 0,
             "slots": {"업종": label, "곳수": f"{n}곳", "지표": what, "자리": place, "비율": f"{val[ticker]:.1f}%", "평균": f"{avg:.1f}%"}}]  # fmt: skip


# 자금 쓰임 이름 → 쉬운 말 (이름도 함께 둔다 — 쓰기 규칙 「용어 이름과 풀이 함께」)
USE_PLAIN = {"채무상환자금": "빚 갚기", "운영자금": "회사 운영", "시설자금": "공장·설비", "타법인증권취득자금": "다른 회사 지분 사기",
             "운전자금": "회사 운영", "차환자금": "빚 갚기"}  # fmt: skip


def span(a: date, b: date | None) -> str:
    """납입일~만기 → 「3년」 「18개월」."""
    if not b:
        return ""
    m = round((b - a).days / 30.44)
    return f"{m // 12}년" if m % 12 == 0 else f"{m}개월"


def bond_fact(con: sqlite3.Connection, ticker: str, today: date) -> list[dict]:
    """F12 = 최근 90일·앞으로의 회사채 발행 — 신고서 한 장(회차 여럿)을 한 줄로. 금액·만기·쓰임은 신고서 그대로, 합계·기간은 코드가 셈."""
    rows = con.execute("select rcept_no, pay_date, amount, maturity, rate, uses from bonds where ticker = ? and pay_date >= ? order by pay_date desc",
                       (ticker, (today - timedelta(days=EVENT_DAYS)).isoformat())).fetchall()  # fmt: skip
    if not rows:
        return []
    rno = rows[0][0]
    mine = [r for r in rows if r[0] == rno]
    pay = date.fromisoformat(mine[0][1])
    total = sum(r[2] for r in mine)
    spans = "·".join(dict.fromkeys(x for r in mine if (x := span(pay, r[3] and date.fromisoformat(r[3])))))
    uses: dict[str, int] = {}
    for r in mine:
        for k, v in json.loads(r[5] or "{}").items():
            uses[k] = uses.get(k, 0) + v
    use_txt = " · ".join(f"{USE_PLAIN.get(k.replace(' ', ''), k)}({k}) {won(v)}" for k, v in sorted(uses.items(), key=lambda x: -x[1]))
    rates = "·".join(dict.fromkeys(r[4] for r in mine if r[4]))
    when = "납입 예정" if pay > today else "납입"
    day = f"{pay.month}월 {pay.day}일"
    text = (f"{day} 회사채 {won(total)} {when}" + (f" — 만기 {spans}" if spans else "") + (f" · 이자 연 {rates}%" if rates else "")
            + (f" · 쓰임: {use_txt}" if use_txt else ""))  # fmt: skip
    return [{"id": "F12", "text": text, "url": DART.format(rno), "tone": 0,
             "slots": {"날짜": day, "금액": won(total)} | ({"만기": spans} if spans else {})
             | ({"쓰임": use_txt if len(uses) > 1 else f"{USE_PLAIN.get(k.replace(' ', ''), k)}({k})"} if (k := next(iter(uses), "")) else {})}]  # 쓰임이 하나면 금액을 되풀이하지 않게


def segment_fact(con: sqlite3.Connection, ticker: str) -> list[dict]:
    """F11 = 사업부별 영업이익 — 사업보고서 「영업부문 정보」에서 옮겨 적은 값(원 단위로 코드가 바꿔 둔 것). 큰 것 셋."""
    biz = con.execute("select body, rcept_no from business where ticker = ?", (ticker,)).fetchone()
    seg = biz and json.loads(biz[0]).get("seg")
    rows = [r for r in (seg or {}).get("rows", []) if r.get("op") is not None]
    if len(rows) < 2:
        return []
    rows = sorted(rows, key=lambda r: -abs(r["op"]))[:3]
    parts = [f"{r['name']} {won(r['op'])}" + (f"(전년보다 {c})" if (c := trend(r["op"], r.get("op_prev"))[2]).startswith(("+", "-")) else f"({c})" if c else "")
             for r in rows]  # fmt: skip
    return [{"id": "F11", "text": f"{seg['year']}년 사업부별 영업이익 — " + " · ".join(parts), "url": DART.format(biz[1]), "tone": 0,
             "slots": {"연도": f"{seg['year']}년", "첫부문": rows[0]["name"]}}]  # fmt: skip


def facts(con: sqlite3.Connection, ticker: str, today: date) -> list[dict]:
    """종목 하나의 사실 목록 — [{id, text, url, tone, slots}]. 문장도 숫자도, 좋은지 걱정인지(tone)도,
    AI 가 쓸 빈칸 값(slots)도 코드가 만든다. text 는 코드 대체 글·AI 이해용, slots 는 AI 글에 끼울 값."""
    out = []
    fin = con.execute("select fiscal_year, revenue, operating_income, net_income, equity, liabilities, rcept_no,"
                      " basis from financials where ticker = ? order by fiscal_year desc limit 5", (ticker,)).fetchall()  # fmt: skip
    if fin:
        y, rev, oi, ni, eq, li, rno, basis = fin[0]
        p = fin[1] if len(fin) > 1 else (None,) * 8
        url, yy = DART.format(rno), f"{y}년"
        base = {"OFS": " · 별도 재무 기준"}.get(basis, "")  # 연결이 기본. 연결이 없는 회사만 밝힌다
        for fid, what, cur, prev in (("F1", "매출", rev, p[1]), ("F2", "영업이익", oi, p[2])):
            if cur is None:
                continue
            tone, way, chg = trend(cur, prev)
            if fid == "F2" and cur < 0 and not way:
                tone, way, chg = -1, "적자였", "영업 적자"
            tail = f"(전년보다 {chg})" if chg.startswith(("+", "-")) else f"({chg} · 전년 {won(prev)})" if chg else ""
            # 폭 = 부호 없는 변화율 — 「매출이 {F1.폭} {F1.방향}어요」→「매출이 10.9% 늘었어요」(방향 낱말과 +가 겹치지 않게)
            slots = ({"연도": yy, "값": won(cur)} | ({"변화": chg} if chg else {}) | ({"방향": way} if way else {})
                     | ({"폭": chg.lstrip("+-")} if chg.startswith(("+", "-")) else {}))  # fmt: skip
            out.append({"id": fid, "text": f"{yy} {what} {won(cur)}{tail}{base}", "url": url, "tone": tone,
                        "slots": slots})  # fmt: skip
        # 은행·보험은 예금·보험금이 빚으로 잡혀 부채비율이 수백~천 % — 초보자에게 오해만 준다.
        # 금융회사는 DART 에 「매출액」이 없다 → 그걸로 가린다
        if li is not None and eq and eq > 0 and rev is not None:
            r = f"{li / eq * 100:.1f}%"
            out.append({"id": "F3", "text": f"{yy} 말 부채비율 {r} (빚 {won(li)} · 자기 돈 {won(eq)})", "url": url,
                        "tone": 1 if li / eq * 100 < DEBT_GOOD else -1 if li / eq * 100 > DEBT_BAD else 0,
                        "slots": {"연도": yy, "비율": r, "빚": won(li), "자기돈": won(eq)}})  # fmt: skip
        if ni is not None and eq and eq > 0:
            r = f"{ni / eq * 100:.1f}%"
            out.append({"id": "F4", "text": f"{yy} ROE {r} (순이익 {won(ni)} · 자기 돈 {won(eq)})", "url": url,
                        "tone": 1 if ni / eq * 100 >= ROE_GOOD else -1 if ni < 0 else 0,
                        "slots": {"연도": yy, "비율": r, "순이익": won(ni), "자기돈": won(eq)}})  # fmt: skip
        out += story_facts(fin, url, yy)
    biz = con.execute("select body, rcept_no from business where ticker = ?", (ticker,)).fetchone()
    if biz and (segs := json.loads(biz[0]).get("segments")):  # 무엇으로 버나 — 사업보고서의 부문별 매출 비중 (큰 것 둘)
        top = sorted(segs, key=lambda x: -float(x["share"].rstrip("%") or 0))[:2]
        slots = {f"{o}부문": x["name"].split(" · ")[-1] for o, x in zip(("첫", "둘째"), top)} | {f"{o}비중": x["share"] for o, x in zip(("첫", "둘째"), top)}
        out.append({"id": "F7", "text": "매출 비중 — " + ", ".join(f"{x['name']} {x['share']}" for x in top), "url": DART.format(biz[1]),
                    "tone": 0, "slots": slots})  # fmt: skip
    out += quarter_facts(con, ticker) + industry_fact(con, ticker) + segment_fact(con, ticker) + bond_fact(con, ticker, today)
    evs = con.execute("select rcept_no, date, title, code, direction from disclosures"
                      " where ticker = ? and date >= ? and importance >= 2 and code != 'OTHER'"
                      " order by importance desc, date desc limit 5",
                      (ticker, (today - timedelta(days=EVENT_DAYS)).isoformat())).fetchall()  # fmt: skip
    for k, (rno, d, title, code, dr) in enumerate(evs, 1):  # 중요한 것부터(D1 이 가장 중요), 같으면 최근 것부터
        d = date.fromisoformat(d)
        tone = {1: " — 주주에게 반가운 쪽으로 분류", -1: " — 주주에게 걸리는 쪽으로 분류"}.get(dr, "")
        day = f"{d.month}월 {d.day}일"
        what = f" — 무슨 일: {plain(title)}" if plain(title) else ""
        out.append({"id": f"D{k}", "text": f"{day} {EVENT_KO[code]} 공시 「{tidy(title)}」{what}{tone}", "url": DART.format(rno),
                    "tone": dr or 0, "slots": {"날짜": day, "종류": EVENT_KO[code], "제목": f"「{tidy(title)}」"} | ({"무슨일": plain(title)} if plain(title) else {})})  # fmt: skip
    out += insider_facts(con, ticker, today)
    news = con.execute("select url, date, press, title, summary from news where ticker = ? and date >= ?"
                       " order by (summary is not null and summary != '') desc, date desc limit 10",  # 요약문 있는 것부터
                       (ticker, (today - timedelta(days=NEWS_DAYS)).isoformat())).fetchall()  # fmt: skip
    # 목표주가·매수 같은 말이 든 소식은 싣지 않는다 — 옮기기만 해도 권유가 된다 (불변식 1)
    news = [n for n in news if not FORBIDDEN.search(n[3] + " " + (n[4] or ""))]
    for k, (url, d, press, title, summary) in enumerate(news, 1):
        d = date.fromisoformat(d)
        day = f"{d.month}월 {d.day}일"
        # text 에 요약문까지 — AI 는 여기 적힌 숫자만 그대로 옮길 수 있다(fill 의 토큰 대조). 기사 본문은 없다
        out.append({"id": f"N{k}", "text": f"{day} {press} 소식 「{title}」" + (f" — {summary}" if summary else ""), "url": url, "tone": 0,
                    "slots": {"날짜": day, "매체": press, "제목": f"「{title}」"}})  # fmt: skip
    return out


def insider_facts(con: sqlite3.Connection, ticker: str, today: date) -> list[dict]:
    """지분 보고 — I1: 최근 90일 임원·주요주주 보고 집계 · I2~I3: 5% 대량보유 보고 최근 두 건.
    「샀다·팔았다」가 아니라 「보유 주식을 늘렸다·줄였다」 — 회사에서 받은 주식(보상)도 들어가기 때문. tone 은 늘 중립(0)."""
    rows = con.execute("select rcept_no, date, kind, who, change, rate from insiders where ticker = ? and date >= ?"
                       " order by date desc, rcept_no desc",
                       (ticker, (today - timedelta(days=EVENT_DAYS)).isoformat())).fetchall()  # fmt: skip
    out = []
    ex = [r for r in rows if r[2] == "임원" and r[4]]
    if ex:
        span = f"최근 {EVENT_DAYS}일"
        slots, parts = {"기간": span, "건수": f"{len(ex)}건"}, []
        for key, word, side in (("늘린", "늘린", [r for r in ex if r[4] > 0]), ("줄인", "줄인", [r for r in ex if r[4] < 0])):
            if side:
                n, total = f"{len(side)}건", f"{korean_num(abs(sum(r[4] for r in side)))}주"
                slots |= {f"{key}보고": n, f"{key}주식": total}
                parts.append(f"{word} 보고 {n}(합계 {total})")
        out.append({"id": "I1", "text": f"{span} 임원·주요주주 지분 보고 {len(ex)}건 — 보유 주식을 " + " · ".join(parts),
                    "url": DART.format(ex[0][0]), "tone": 0, "slots": slots})  # fmt: skip
    for k, (rno, d, _, who, chg, rate) in enumerate([r for r in rows if r[2] == "5%"][:2], len(out) + 1):
        d = date.fromisoformat(d)
        day = f"{d.month}월 {d.day}일"
        way = f", 직전 보고보다 보유 주식 {korean_num(abs(chg))}주 {'늘림' if chg > 0 else '줄임'}" if chg else ""
        slots = {"날짜": day, "누가": who} | ({"비율": f"{rate:.2f}%"} if rate is not None else {})
        if chg:
            slots |= {"주식": f"{korean_num(abs(chg))}주", "방향": "늘렸" if chg > 0 else "줄였"}
        out.append({"id": f"I{k}", "text": f"{day} {who}의 5% 이상 대량보유 보고 — 보유 비율 {rate:.2f}%{way}" if rate is not None
                    else f"{day} {who}의 5% 이상 대량보유 보고{way}", "url": DART.format(rno), "tone": 0, "slots": slots})  # fmt: skip
    return out


STOP = {"주가", "기사", "오늘", "올해", "내년", "작년", "우리", "관련", "이유", "속보", "단독", "종합", "포토", "영상",
        "그래픽", "시장", "투자", "주식", "증시", "코스피", "코스닥", "상승", "하락", "만에", "이후", "통해", "위해"}  # fmt: skip


def keywords(fs: list[dict], name: str, n: int = 3) -> list[str]:
    """언론 키워드 흐름 — 이번 주 기사 제목에 두 번 이상 나온 낱말(회사 이름·흔한 낱말 빼고). AI 가 아니라 코드가 센다.
    두 번 이상 나온 게 없으면 비운다(지어내지 않는다)."""
    seen: dict[str, int] = {}
    for f in fs:
        if f["id"].startswith("N"):
            for w in set(re.findall(r"[A-Za-z0-9가-힣]{2,}", f["slots"]["제목"])):
                w = re.sub(r"(은|는|이|가|을|를|의|에|에서|와|과|도|로|으로)$", "", w)
                if len(w) >= 2 and w not in STOP and w not in name and name not in w and not w.isdigit():
                    seen[w] = seen.get(w, 0) + 1
    top = sorted((w for w, c in seen.items() if c >= 2), key=lambda w: -seen[w])
    return [f"#{w}" for w in top[:n]]


# --- ⑤ 쓰기 (AI) — 빈칸 채우기 + 검사 ---


def numbers(s: str) -> set[str]:
    """숫자 토큰 — 「333.6조원」 → '333.6', 「1,512건」 → '1512'."""
    return {t.replace(",", "") for t in re.findall(r"\d[\d,]*(?:\.\d+)?", s)}


# 조사 짝 — (받침 없을 때, 받침 있을 때). 빈칸 값 뒤의 조사를 값의 끝소리에 맞춘다(「7월 23일와」→「7월 23일과」)
JOSA = {"와": ("와", "과"), "과": ("와", "과"), "는": ("는", "은"), "은": ("는", "은"),
        "가": ("가", "이"), "이": ("가", "이"), "를": ("를", "을"), "을": ("를", "을"),
        "로": ("로", "으로"), "으로": ("로", "으로")}  # fmt: skip
SLOT_JOSA = re.compile(r"\{([A-Z]\d+)\.([가-힣]+)\}(?:(으로|와|과|는|은|가|이|를|을|로)(?![가-힣]))?")


def josa(value: str, p: str) -> str:
    """값의 마지막 글자에 받침이 있으면 「과·은·이·을」. 한글이 아닌 끝(%, 숫자)은 읽는 소리로 — %·퍼센트는 받침 없음."""
    last = value[-1]
    if "가" <= last <= "힣":
        jong = (ord(last) - 0xAC00) % 28
        has = jong != 0 and not (p in ("로", "으로") and jong == 8)  # ㄹ 받침 + 로 → 「로」
    else:
        has = last in "013678"  # 영·일·삼·육·칠·팔 — 받침 있는 숫자 소리
    return JOSA[p][1 if has else 0]


LIST_SEP = re.compile(r"( ?· ?|, )(?![^「」]*」)")  # 괄호 속 나열의 구분자 — 「제목」 안의 것은 빼고


def dedupe(text: str) -> str:
    """괄호 속 나열에서 같은 항목을 한 번만 — 「(7월 23일·7월 23일·7월 20일)」 → 「(7월 23일·7월 20일)」."""
    def one(m):
        parts = LIST_SEP.split(m[1])
        items, seps = [x.strip() for x in parts[::2]], parts[1::2]
        if len(items) > 1 and all(x in m.string[: m.start()] for x in items):  # 앞에서 이미 다 말한 것을 괄호로 또
            return ""
        return "(" + (seps[0] if seps else "").join(dict.fromkeys(items)) + ")"

    text = re.sub(r"(\d+월) (?=\1 \d)", "", text)  # 「8월 {D3.날짜}」→「8월 8월 3일」 → 「8월 3일」
    text = re.sub(r"\(([^()]*)\)", one, text)
    # 괄호에 기사 제목만 넣은 것은(하나든 여럿이든) 통째로 뺀다 — 출처 번호로 기사가 열린다 (사용자 10/8)
    return re.sub(r" ?\(「[^」]*」(?:(?:, ?| ?· ?)「[^」]*」)*\)", "", text)


def mend(text: str) -> str:
    """빈칸 값(낱말 줄기 「4번째로 많았」「줄였」, 「2021년」)에 AI 가 토씨·글자를 또 붙여 깨진 이음을 고친다.
    fill 에서도, 화면에 그릴 때도(이미 쓴 노트) 쓴다 — 「많았으로」「높았였어요」「3년년」「줄였 보고」「(9.4% -9.4%)」 (사용자 10/9 검토)."""
    text = re.sub(r"(았|었)(?:으로|로)(?=[,\s])", r"\1고", text)
    text = re.sub(r"(았|었)(?:였|이었)", r"\1", text)
    text = re.sub(r"(\d년)년", r"\1", text)
    text = re.sub(r"(렸|였|았|었) 보고를", r"\1다는 보고를", text)
    text = re.sub(r"(렸|였|았|었) (보고|공시)", r"\1다고 \2", text)
    text = re.sub(r"(\d[\d,]*(?:건|주|명|곳))([^()]{0,20})\(\1\)", r"\1\2", text)  # 「1건 있었어요(1건)」
    # 날짜로 시작하는 문장 — 날짜는 문장 끝 괄호로 (사용자 10/9: 날짜가 앞에서 오가면 요점이 안 보인다)
    text = re.sub(r"(?:^|(?<=[.!?] ))(\d+월 \d+일(?:(?:과|와|,| ·) \d+월 \d+일)*)(?:에는|에도|에|엔|,)?\s+([^.!?]+?)([.!?])",
                  lambda m: f"{m[2][:1].upper()}{m[2][1:]}({m[1]}){m[3]}", text)
    text = re.sub(r"(았|었)에(?=\s)", r"\1던 해에", text)  # 「4번째로 많았에 머물렀어요」
    text = re.sub(r"(늘었|줄었)(?=\s*[·)])", lambda m: "증가" if m[1] == "늘었" else "감소", text)  # 괄호 속 「10.9% 늘었 ·」
    return re.sub(r"(\d[\d.,]*%) ([+-])\1", r"\2\1", text)


def fill(sent: dict, by: dict[str, dict]) -> dict:
    """AI 문장의 빈칸을 코드 값으로 채운다. 쓴 빈칸의 사실은 근거(refs)에 저절로 들어간다.
    검사: ① 빈칸 밖 숫자는 근거 사실에 글자 그대로 있을 때만 ② 없는 빈칸 금지 ③ 빈칸 없이 쓴 방향 낱말이 사실과 반대면 탈락."""
    raw, refs = sent["text"], list(dict.fromkeys(sent["refs"]))
    # 연도(「2025년」)만은 직접 써도 된다 — 사실의 연도와 글자 그대로 같을 때만. 다른 숫자는 전부 빈칸으로
    years = {f["slots"]["연도"] for f in by.values() if "연도" in f.get("slots", {})}
    # 날짜(「10월 1일」)와 그 달(「7월」)도 사실에 있는 것과 글자 그대로 같으면 직접 써도 된다
    days = {f["slots"]["날짜"] for f in by.values() if "날짜" in f.get("slots", {})}
    months = {d.split()[0] for d in days}
    # 기간(「최근 90일」)도 사실에 있는 글자 그대로면 직접 써도 된다
    days |= {f["slots"]["기간"] for f in by.values() if "기간" in f.get("slots", {})}
    # 지분 보고(I)를 근거로 든 문장은 그 사실의 빈칸 값(「8건」「1,500주」)을 글자 그대로 써도 된다 — 코드 값과 똑같을 때만
    days |= {v for r in refs if r.startswith("I") and r in by for v in by[r]["slots"].values()}
    bare = SLOT.sub("", raw)
    for y in sorted(years | days, key=len, reverse=True):
        bare = bare.replace(y, "")
    if any("대량보유" in f["text"] for f in by.values()):  # 「5% 이상 대량보유」는 보고 이름이지 숫자가 아니다
        bare = re.sub(r"5\s*%", "", bare)
    for mth in months:
        bare = re.sub(rf"(?<!\d){mth}", "", bare)
    bare = re.sub(r"100원(어치|당)?", "", bare)  # 「100원어치 팔아 13원 남겨요」 — 셈의 단위지 사실 숫자가 아니다
    # 근거로 든 사실(refs·쓴 빈칸)에 글자 그대로 적힌 숫자는 빈칸 없이 옮겨도 된다 (토큰 대조) — 빈칸만 고집하면
    # 맞는 숫자도 버려져 AI 글 대신 사실 목록이 나간다 (사용자 10/8: 「무슨 일: …」은 글이 아니다)
    cited = set(refs) | {fid for fid, _ in SLOT.findall(raw)}
    src = set().union(*(numbers(by[r]["text"]) for r in cited if r in by)) if cited else set()
    # 기간·횟수 같은 작은 정수(「최근 5년」「3건」)는 어느 사실에 있든 된다 — 큰 금액·비율은 근거 사실에 있어야만
    small = {t for f in by.values() for t in numbers(f["text"]) if t.isdigit() and int(t) < 100}
    if numbers(bare) <= src | small:
        bare = re.sub(r"\d", "", bare)
    if re.search(r"\d", bare):
        raise ValueError(f"숫자는 빈칸으로만: {raw!r}")
    used = SLOT.findall(raw)
    for fid, key in used:
        if key not in by.get(fid, {}).get("slots", {}):
            raise ValueError(f"없는 빈칸 {{{fid}.{key}}}: {raw!r}")
        if fid not in refs:
            refs.append(fid)
    if not any(k == "방향" for _, k in used):  # 방향을 빈칸 대신 직접 썼다면 사실과 맞는지
        dirs = {by[r]["tone"] for r in refs if r in ("F1", "F2") and r in by and "방향" in by[r]["slots"]}
        if (dirs == {-1} and UP.search(bare)) or (dirs == {1} and DOWN.search(bare)):
            raise ValueError(f"사실과 반대 방향: {raw!r}")
    # 방향 줄기(「줄었」) 뒤에 AI 가 「었」을 한 번 더 붙이는 일이 잦다 — 「줄었었지만」 → 「줄었지만」
    def put(m):
        v = by[m[1]]["slots"][m[2]]
        return v + (josa(v, m[3]) if m[3] else "")

    # 「관계」 빈칸은 그 자체가 판 돈·남긴 돈 이야기 — 앞에 AI 가 같은 말을 또 쓰면(「판 돈보다 남긴 돈이 더 빨리 {F8.관계}」) 그 말을 뺀다
    raw = re.sub(r"(?:판 돈|남긴 돈|매출|영업이익)[^.{}]*?(\{F\d+\.관계\})", r"\1", raw)
    if REL_WORDS.search(SLOT.sub("", raw)):
        raise ValueError(f"관계는 빈칸으로만: {raw!r}")
    text = mend(dedupe(SLOT_JOSA.sub(put, raw).replace("었었", "었")))
    text = re.sub(r"(\d)(건|주|명|개|원|%|곳)\2", r"\1\2", text)
    text = re.sub(r"(\d{4}년) \1", r"\1", text)  # 「2026년 {F8.분기}」 → 「2026년 2026년 2분기」
    # 빈칸을 끼우며 생기는 어색한 이음 — 「가장 많았인」「최근 최근 90일」「10.9%이었으니」
    text = re.sub(r"(았|었)인(?=\s)", r"\1던", text)
    text = re.sub(r"(최근|약|총) \1(?=\s)", r"\1", text)
    text = re.sub(r"%이(었|에요)", lambda m: "%" + {"었": "였", "에요": "예요"}[m[1]], text)  # 빈칸 값에 단위가 있는데 AI 가 또 붙인 것 — 「765건건」 → 「765건」
    if re.search(r"(늘었|줄었|돌아섰|이어졌)(?![어고는지으다던기을거네죠습])", text) or re.search(r"(늘었|줄었)\S*\s*(늘었|줄었|증가|감소|성장)", text):
        raise ValueError(f"방향 낱말이 어색하게 이어짐: {text!r}")  # 「늘었을 때」「늘었거든요」는 괜찮다
    text = text.replace("「「", "「").replace("」」", "」")
    if "{" in text or "}" in text:  # 영어 이름 같은, 정해 두지 않은 빈칸을 지어낸 경우 (「{N1.body}」)
        raise ValueError(f"없는 빈칸이 남음: {raw!r}")
    kinds = [by[fid]["slots"]["종류"] for fid, key in used if key == "종류"]
    if len(kinds) != len(set(kinds)):  # 「(자사주 매입, 자사주 매입, …)」 같은 이름 반복
        raise ValueError(f"같은 공시 이름 반복: {raw!r}")
    return {"text": text, "refs": refs}


def check_note(note: dict, fs: list[dict]) -> dict:
    """빈칸을 채운 글 전체 검사 — 하나라도 어기면 ValueError (글째 버린다).
    ① 문장마다 있는 사실 id ② 사실에 없는 숫자 금지(빈칸을 채운 뒤에도 한 번 더) ③ 금지어 ④ 예측 말투
    ⑤ 좋게 본 것은 +1 사실만, 걱정되는 것은 −1 사실만 근거로 — 그런 사실이 있는데 비워 두면 탈락."""
    for key, sign in (("good", 1), ("concern", -1)):
        want = {f["id"] for f in fs if f["tone"] == sign}
        # 다른 쪽(중립 등) 사실을 끌어온 문장만 뺀다 — 한 문장 때문에 노트 전체를 버리지 않게 (SK 10/9: 세 번 다 떨어져 코드 글)
        got = note[key] = [s for s in note.get(key) or [] if set(s["refs"]) <= want]
        if want and not got:
            raise ValueError(f"{key} 비었음 — 해당 사실 {sorted(want)}")
    sents = (note["summary"] + [s for sec in note["sections"] for s in sec["sentences"]]
             + (note.get("good") or []) + (note.get("concern") or []))  # fmt: skip
    if not isinstance(note["headline"], str) or not sents:
        raise ValueError("빈 노트")
    for s in [{"text": note["headline"], "refs": [f["id"] for f in fs]}] + sents:
        check_sentence(s, fs)
    return note


def check_sentence(s: dict, fs: list[dict]) -> None:
    """문장 하나 — ① 사실 id 근거 ② 사실에 없는 숫자 금지 ③ 읽기 힘든 긴 숫자 금지 ④ 소식 제목 인용 ⑤ 금지어 ⑥ 예측 말투. 어기면 ValueError."""
    ids = {f["id"] for f in fs}
    text, refs = s["text"], s["refs"]
    if not isinstance(text, str) or not refs or not set(refs) <= ids:
        raise ValueError(f"근거 없는 문장: {text!r}")
    allowed = set().union(*(numbers(f["text"] + " " + f.get("body", "")) for f in fs))
    if bad := numbers(text) - allowed:
        raise ValueError(f"사실에 없는 숫자 {bad}: {text!r}")
    if LONGNUM.search(text):
        raise ValueError(f"읽기 힘든 숫자: {text!r}")
    if CALC.search(text):
        raise ValueError(f"AI 가 한 셈: {text!r}")
    n_titles = [t.strip("「」") for f in fs if f["id"].startswith("N") and (t := f.get("slots", {}).get("제목"))]
    if any(f"「{t}」" in text for t in n_titles):  # 소식 제목을 따옴표로 베껴 넣은 문장 — 제목 대신 그 일을 말해야 한다
        raise ValueError(f"소식 제목 인용: {text!r}")
    quoted = [f["text"] for f in fs]
    bare = re.sub(r"「([^」]*)」", lambda m: "" if any(m[1] in q for q in quoted) else m[0], text)
    if FORBIDDEN.search(bare):
        raise ValueError(f"금지어: {text!r}")
    if PREDICT.search(bare) and not all(r.startswith("N") for r in refs):
        raise ValueError(f"예측 말투: {text!r}")
    outside = re.sub(r"\([^()]*\)|「[^」]*」", "", text)
    if not all(r.startswith("N") for r in refs) and HARD.search(outside):
        raise ValueError(f"어려운 말: {text!r}")
    if STEM.search(outside):
        raise ValueError(f"끝이 잘린 말: {text!r}")
    if any(REPEAT.search(x) for x in re.split(r"(?<=[.?!])\s", outside)):
        raise ValueError(f"같은 말 되풀이: {text!r}")


def short_title(t: str, what: str) -> str:
    """긍정·부정 칸의 짧은 소제목 — 숫자·금지어·예측 말투 없이 24자 안."""
    t = (t or "").strip()
    if not t or len(t) > 24 or re.search(r"\d", t) or FORBIDDEN.search(t) or PREDICT.search(t):
        raise ValueError(f"{what} 소제목: {t!r}")
    return t


def fill_note(j: dict, fs: list[dict]) -> dict:
    """AI 응답(빈칸 글) → 채운 노트 → 검사. 빈칸은 good/concern 칸 검사보다 먼저 채운다(근거가 늘 수 있다)."""
    by = {f["id"]: f for f in fs}
    total, dropped = 0, []

    def days(refs):
        return {by[r]["slots"]["날짜"] for r in refs if r in by and "날짜" in by[r].get("slots", {})}

    def keep(xs):
        """틀린 문장만 빼고 나머지는 살린다 — 한 문장 때문에 글 전체가 사실 목록으로 바뀌지 않게 (사용자 10/8)."""
        nonlocal total
        out = []
        for x in xs:
            total += 1
            try:
                y = fill(x, by)
                check_sentence(y, fs)
                if "같은 날" in y["text"] and (not out or not days(y["refs"]) or not days(y["refs"]) <= days(out[-1]["refs"])):
                    raise ValueError(f"「같은 날」인데 날짜가 다름: {y['text']!r}")
                out.append(y)
            except ValueError as err:
                dropped.append(str(err))
        return out

    try:
        head = fill({"text": j["headline"], "refs": []}, by)["text"]
        check_sentence({"text": head, "refs": list(by)}, fs)
    except ValueError:
        head = code_headline(fs)
    note = {"headline": head, "summary": keep(j["summary"]),
            "sections": [{"title": sec["title"], "sentences": got} for sec in j["sections"] if (got := keep(sec["sentences"]))],
            "good": keep(j["good"]), "concern": keep(j["concern"])}  # fmt: skip
    # 회사채(F12)는 한 번만 — 「회사 사정」과 「이번 주 소식」에 같은 문장이 두 번 나오지 않게 (SK 10/9)
    seen_bond = False
    for sec in note["sections"]:
        keep_ = []
        for x in sec["sentences"]:
            if "F12" in x["refs"]:
                if seen_bond:
                    continue
                seen_bond = True
            keep_.append(x)
        sec["sentences"] = keep_
    note["sections"] = [sec for sec in note["sections"] if sec["sentences"]]
    if total and len(dropped) > total * 0.3:  # 너무 많이 빠지면 이어지지 않는다 — 다시 쓰게
        raise ValueError(f"문장 {len(dropped)}/{total}개 탈락: {dropped[0]}")
    if note["good"]:
        note["good_title"] = short_title(j["good_title"], "긍정")
    if note["concern"]:
        note["concern_title"] = short_title(j["concern_title"], "부정")
    return check_note(note, fs)


def schema(fs: list[dict]) -> dict:
    """OpenAI 구조화 출력 — 근거 id 는 이 노트의 사실 id 중에서만 고를 수 있다 (없는 id 는 API 가 막는다)."""
    sent = {"type": "object", "additionalProperties": False, "required": ["text", "refs"],
            "properties": {"text": {"type": "string"},
                           "refs": {"type": "array", "items": {"type": "string", "enum": [f["id"] for f in fs]}}}}
    arr = {"type": "array", "items": sent}
    return {"type": "object", "additionalProperties": False,
            "required": ["headline", "summary", "sections", "good", "concern", "good_title", "concern_title"],
            "properties": {"headline": {"type": "string"}, "summary": arr, "good": arr, "concern": arr,
                           "good_title": {"type": "string"}, "concern_title": {"type": "string"},
                           "sections": {"type": "array", "items": {
                               "type": "object", "additionalProperties": False, "required": ["title", "sentences"],
                               "properties": {"title": {"type": "string", "enum": list(TITLES)}, "sentences": arr}}}}}  # fmt: skip


def code_headline(fs: list[dict]) -> str:
    """대체 글의 첫 줄 — 그 회사의 가장 큰 이슈 한 줄을 사실에서 고른다(코드가 쓴 문장, 숫자는 사실 그대로).
    차례: 걸리는 공시 → 영업이익의 변화 → 반가운 공시 → 매출 → 첫 사실."""
    by = {f["id"]: f for f in fs}
    ds = [f for f in fs if f["id"][0] == "D"]
    pick = (next((f for f in ds if f["tone"] == -1), None) or (by.get("F2") if "방향" in by.get("F2", {}).get("slots", {}) else None)
            or next((f for f in ds if f["tone"] == 1), None) or (by.get("F1") if "방향" in by.get("F1", {}).get("slots", {}) else None))  # fmt: skip
    if pick and pick["id"][0] == "D":
        s = pick["slots"]
        return f"{s['날짜']}에 {s['종류']} 공시가 있었어요."
    if pick:
        s, what = pick["slots"], "영업이익" if pick["id"] == "F2" else "매출"
        chg = f", {s['변화']}" if s.get("변화", "").startswith(("+", "-")) else ""
        return f"{s['연도']} {what}이 {s['방향']}어요({s['값']}{chg})."
    return fs[0]["text"] + "."


def say(f: dict) -> str:
    """사실 하나 → 사람이 읽을 해요체 한 문장 (코드 대체 글용). 숫자는 사실의 빈칸 값 그대로."""
    s, i = f.get("slots", {}), f["id"]
    if i in ("F1", "F2") and "값" in s:
        what = "매출" if i == "F1" else "영업이익"
        if "방향" in s and "폭" in s:
            return f"{s['연도']} {what}은 {s['값']}으로, 전년보다 {s['폭']} {s['방향']}어요."
        return f"{s['연도']} {what}은 {s['값']}이었어요."
    if i == "F3" and "비율" in s:
        return f"{s['연도']} 말 빚은 {s['빚']}, 자기 돈은 {s['자기돈']}이에요(부채비율 {s['비율']})."
    if i == "F4" and "비율" in s:
        return f"자기 돈으로 얼마나 벌었는지 보는 ROE는 {s['비율']}였어요({s['연도']} 순이익 {s['순이익']})."
    if i == "F5":
        return f"100원어치 팔면 본업으로 {s['백원당']}을 남긴 셈이에요(영업이익률 {s['비율']})."
    if i == "F7" and "첫부문" in s:
        return f"돈은 주로 {s['첫부문']}에서 벌어요(매출의 {s['첫비중']})."
    if i[0] == "D" and "날짜" in s:
        what = re.search(r"무슨 일: ([^—]+?)(?: — |$)", f["text"])
        return f"{s['날짜']}에는 {what[1].rstrip('.')}." if what else f"{s['날짜']}에 {s['종류']} 공시가 나왔어요."
    if i[0] == "N" and "매체" in s:
        return f"{s['날짜']}에는 {s['매체']}가 {s['제목']} 소식을 전했어요."
    return f["text"].rstrip(".") + "."


def code_note(fs: list[dict]) -> dict:
    """AI 글이 검사에서 떨어졌을 때 — 사실마다 해요체 한 문장으로 (PRD §4.3). 같은 날 같은 뜻의 공시는 한 번만."""
    seen: set[str] = set()

    def keep(f):
        t = say(f)
        return not (t in seen or seen.add(t))

    groups = zip(TITLES, (("F1", "F2", "F3", "F4", "F5", "F7", "F10", "F12"), ("F8", "F9", "F11"), ("D", "N"), "I"))
    secs = [{"title": t, "sentences": [{"text": say(f), "refs": [f["id"]]}
                                       for f in fs if f["id"].startswith(p) and keep(f)]} for t, p in groups]  # fmt: skip
    side = {k: [{"text": say(f), "refs": [f["id"]]} for f in fs if f["tone"] == sign]
            for k, sign in (("good", 1), ("concern", -1))}  # fmt: skip
    return {"headline": code_headline(fs), "summary": [],
            "sections": [s for s in secs if s["sentences"]], **side}


def finish(note: dict, fs: list[dict], name: str = "") -> dict:
    """좋게 본 것·걱정되는 것 — 해당 사실이 없는 칸은 비워 두고 화면에서 띄우지 않는다 (사용자 10/7).
    소제목이 없으면(코드 대체 글) 코드가 짓는다. 언론 키워드도 여기서 코드가 센다."""
    for key, title in (("good", "재무·공시에서 좋게 본 점"), ("concern", "재무·공시에서 걱정되는 점")):
        note[key] = note.get(key) or []
        if note[key]:
            note.setdefault(f"{key}_title", title)
    note["tone_rule"] = TONE_RULE
    note["keywords"] = keywords(fs, name)
    return note


def write(name: str, fs: list[dict], today: date) -> tuple[dict, str]:
    """(노트, writer) — writer 는 'llm:<모델>' 또는 'code'."""
    label = {1: "좋게 본 것", -1: "걱정되는 것", 0: "중립"}
    payload = {"today": today.isoformat(), "name": name,
               "facts": [{"id": f["id"], "text": f["text"], "tone": label[f["tone"]],
                          "slots": [f"{{{f['id']}.{k}}}" for k in f["slots"]]} | ({"body": f["body"]} if f.get("body") else {})
                         for f in fs]}  # fmt: skip
    got = llm.ask("writer", "note", payload, lambda j: fill_note(j, fs), schema(fs))
    note, writer = (got, f"llm:{llm.MODELS['writer']}") if got else (code_note(fs), "code")
    return finish(note, fs, name), writer


# --- ⑥ 저장 ---


def week_of(today: date) -> str:
    """그 주 월요일 — 노트·설문의 주 단위."""
    return (today - timedelta(days=today.weekday())).isoformat()


def changed(fs: list[dict], old: list[dict] | None, held: bool) -> bool:
    """이번 주 노트의 사실과 달라졌나 — 재무·공시·지분 보고는 누구 종목이든, 소식(N)은 누군가 담은 종목만 본다.
    (담지 않은 종목은 소식 하나 바뀐 것으로 다시 쓰지 않는다 — 비용)
    I1(최근 90일 임원 보고 집계)은 보지 않는다 — 날마다 창이 밀려 숫자가 조금씩 바뀐다(삼성전자는 90일에 800건). 월요일에 새로 센다."""
    if old is None:
        return True

    def sig(xs):
        return [(f["id"], f["text"]) for f in xs if (held or not f["id"].startswith("N")) and f["id"] != "I1"]

    return sig(fs) != sig(old)


def main(tickers: list[str], today: date, only_changed: bool = False, read: bool = True) -> None:
    """only_changed: 이번 주 노트가 이미 있고 사실이 그대로인 종목은 건너뛴다 (화~일 매일 실행). 월요일은 전부 새로.
    read=False: 사업보고서 읽기(DART)를 건너뛴다 — DART 점검 중에 노트만 다시 쓸 때 (python -m hanjang.notes --rewrite)."""
    con = db.connect()
    ruled, ai = read_disclosures(con)
    if read:
        print(f"사업보고서 읽기 {read_business(con, today, tickers or None)}건 · 사업부별 실적 {read_segments(con, today)}곳")
    print(f"공시 읽기 — 규칙 {ruled}건 · AI {ai}건")
    rows = con.execute("select ticker, name from stocks where active = 1").fetchall()
    rows = [r for r in rows if not tickers or r[0] in tickers]
    week = week_of(today)
    by = {"code": 0}  # 「same」= 바뀐 게 없어 건너뛴 종목
    held = {t for (t,) in con.execute("select distinct ticker from holdings")}
    for t, name in rows:
        fs = facts(con, t, today)
        if not fs:
            continue
        if only_changed:
            old = con.execute("select facts from notes where ticker = ? and week = ?", (t, week)).fetchone()
            if not changed(fs, old and json.loads(old[0]), t in held):
                by["same"] = by.get("same", 0) + 1
                continue
        note, writer = write(name, fs, today)
        note["links"] = {f["id"]: f["url"] for f in fs}
        con.execute("insert or replace into notes values (?, ?, ?, ?, ?, ?)",
                    (t, week, json.dumps(fs, ensure_ascii=False), json.dumps(note, ensure_ascii=False),
                     writer, datetime.now().isoformat()))  # fmt: skip
        con.commit()
        by[writer] = by.get(writer, 0) + 1
    print(f"노트 {sum(v for k, v in by.items() if k != 'same')}장 {by} · AI {llm.spent['calls']}콜 ${llm.spent['usd']:.3f}")


if __name__ == "__main__":
    main([a for a in sys.argv[1:] if a != "--rewrite"], date.today(), read="--rewrite" not in sys.argv)
