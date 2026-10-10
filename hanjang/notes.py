"""주간 노트 만들기 ②~⑥ (PRD §5.2): 공시 읽기(규칙→AI) → 사실 묶음(코드) → 쓰기(AI) → 검사 → 저장.
`python -m hanjang.notes [종목코드 …]` — 비우면 전 종목. 같은 주에 다시 돌리면 덮어쓴다.
**숫자와 늘었다/줄었다는 AI 가 쓰지 않는다.** AI 는 `{F1.값}` 같은 빈칸만 쓰고 코드가 채운다 —
AI 글에 숫자가 하나라도 있거나, 사실과 반대 방향 낱말을 쓰면 글째 버린다."""

import json
import re
import sqlite3
import statistics
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
    # 미국 8-K 에만 있는 종류 (us.ITEMS)
    "DEBT": "빚(차입·채권 발행)", "WRITE_DOWN": "구조조정·손상", "RESTATEMENT": "재무제표 정정", "AUDITOR": "회계법인 교체", "EXEC": "최고경영진 교체",
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
    # 미국 8-K (us.classify_8k 의 제목)
    (r"예전재무제표를믿지말라", "예전에 낸 재무제표에 잘못이 있어 믿지 말라고 회사가 알렸어요 — 숫자를 다시 고쳐 낼 예정이에요"),
    (r"파산절차", "법원에 파산 보호 절차를 신청했어요"),
    (r"상장유지경고", "거래소가 상장을 이어 갈 기준을 채우지 못했다고 알렸어요"),
    (r"큰손상차손", "갖고 있던 자산의 값이 크게 떨어졌다고 보고 장부에서 깎았어요"),
    (r"사업정리비용", "사업을 줄이거나 정리하면서 큰 비용이 생긴다고 알렸어요"),
    (r"경영권변동", "회사를 지배하는 주체가 바뀌었어요"),
    (r"새주식발행\(8-K", "새 주식을 발행했어요 — 주식 수가 늘어 기존 주주 몫이 묽어질 수 있어요"),
    (r"인수합병완료", "다른 회사를 사들이거나 합치는 일을 마쳤어요"),
    (r"실적발표\(8-K", "지난 분기 실적을 발표했어요"),
    (r"판매·?인도대수알림", "지난 분기에 판 물량(인도 대수)을 먼저 알렸어요 — 이익 숫자는 실적 발표 때 나와요"),
    (r"예비실적알림", "지난 분기 실적을 확정 전에 어림값으로 먼저 알렸어요 — 확정 숫자는 실적 발표 때 나와요"),
    (r"큰계약체결", "회사에 중요한 계약을 맺었어요"),
    (r"큰계약해지", "회사에 중요한 계약이 끝났어요"),
    (r"큰빚\(차입", "돈을 크게 빌리거나 채권을 냈어요"),
    (r"회계법인교체", "회사 장부를 검사하는 회계법인이 바뀌었어요"),
    (r"최고경영진교체", "최고경영자(CEO)나 재무책임자(CFO)가 바뀌었어요"),
    (r"자사주매입알림\(8-K", "회사가 자기 회사 주식을 사들이는 계획을 알렸어요"),
    (r"새주식판매알림\(8-K", "새 주식을 시장에서 팔아 돈을 모았다고 알렸어요 — 주식 수가 늘어 기존 주주 몫이 묽어질 수 있어요"),
    (r"배당알림\(8-K", "주주에게 배당을 주기로 했어요"),
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
    (r"결산실적공시예고", "실적을 발표할 날짜를 미리 알렸어요"),
    (r"기업설명회", "투자자에게 회사를 설명하는 자리(IR)를 연다고 알렸어요"),
    (r"발행결과", "앞서 정한 증자·채권 발행을 실제로 마쳤다는 결과 보고예요"),
    (r"무상증자결정", "주주에게 새 주식을 공짜로 나눠 주기로 했어요"),
    (r"전환사채권발행결정", "나중에 주식으로 바꿀 수 있는 채권(전환사채)을 팔아 돈을 빌리기로 했어요"),
    (r"신주인수권부사채권발행결정", "새 주식을 살 권리가 붙은 채권을 팔아 돈을 빌리기로 했어요"),
    (r"교환사채권발행결정", "회사가 가진 다른 주식으로 바꿔 줄 수 있는 채권을 팔아 돈을 빌리기로 했어요"),
    (r"배당결정", "번 돈의 일부를 주주에게 배당으로 나눠 주기로 했어요"),
    (r"주주명부폐쇄|기준일설정", "배당 등을 받을 주주를 정하는 기준일을 알렸어요"),
    (r"영업\(잠정\)실적", "회계 감사 전의 실적 숫자(잠정 실적: 매출·영업이익)를 먼저 공개했어요"),
    (r"매출액또는손익구조", "매출이나 이익이 전년보다 크게(30% 넘게) 달라졌다고 알렸어요"),
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
    return undash(next((s for pat, s in TITLE_PLAIN if re.search(pat, t)), ""))


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
             f"부채비율 {DEBT_GOOD}% 미만·{DEBT_BAD}% 초과(같은 업종 중간값의 1.5배도 넘을 때만 · 금융회사와 원래 빚이 많은 업종 — 조선·방산·항공·전력·건설 — 은 걱정으로 보지 않음), ROE {ROE_GOOD}% 이상·0% 미만, "
             "공시 종류(자사주 매입·대형 계약 / 증자·전환사채·소송·거래정지).")
# 예측 말투 — 지난 사실을 「~할 전망」으로 쓰면 틀린 말이고 예측이 된다 (불변식 1). 기사(N)만 근거인 문장은
# 「기사는 ~라고 써요」로 남의 전망을 옮기는 자리라 예외
PREDICT = re.compile(r"전망이|전망돼|것으로 보여|것으로 보입|것 같아|예상돼|예상됩|할 거예요|될 거예요|일 거예요|가능성이 (높|커|있)|지켜볼 만|주목할 만|기대해 볼|눈여겨볼 만|앞으로[^.]{0,20}영향을 줄 수")
# AI 가 직접 쓴 방향 낱말 — 빈칸 {F.방향} 을 안 쓰고 스스로 「늘었어요」라 쓴 경우 사실과 맞는지 본다
UP = re.compile(r"늘|증가|커졌|많아졌|올랐|개선|흑자로")
DOWN = re.compile(r"줄|감소|작아졌|적어졌|내렸|악화|떨어|적자로")
SLOT = re.compile(r"\{([A-Z]\d+)\.([가-힣]+)\}")
# 읽기 검사 (사용자 10/9: 깨진 이음·되풀이·어려운 말이 하나라도 있으면 안 된다) — 걸리면 다시 쓰게 한다
HARD = re.compile(r"유상증자|신주|발행가액|공정공시|기재정정|단일판매|전환사채|자기주식|잠정실적|결산실적")  # 괄호 밖에서 — 쉬운 말로 바꿔 쓴다
STEM = re.compile(r"(늘었|줄었|많았|적었|높았|낮았|돌아섰|이어졌|늘렸|줄였)(?![어고는지으다던기을거네죠습음])")  # 줄기 뒤에 끝이 없음
JUDGE = re.compile(r"반가운|반갑|호재|악재|좋은 소식|나쁜 소식|긍정적인 신호|부정적인 신호")
REPEAT = re.compile(r"([가-힣][가-힣 ]{6,}[가-힣])[^.]*?\1")  # 한 문장 안에서 같은 말(8자 넘게)이 두 번
TITLES = ("회사 사정은 어떤가요?", "올해 장사는 어떤가요?", "최근 소식", "임원·큰손은 어떻게 움직였나요?")  # 「이번 주」라 하면서 석 달 전 공시가 섞였다 (사용자 10/9)  # 소식 = 공시(D) + 뉴스룸·언론 RSS(N)
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
    # 위험 문장은 하나가 걸리면 그 문장만 뺀다 — 「비용을 예측하기 어렵다」처럼 회사의 위험 설명에 금지어가 섞일 수 있다 (팔란티어·유나이티드헬스 10/9)
    out = {"what": j["what"][:3], "segments": [], "risks": [s for s in j["risks"][:4] if not (numbers(s) - have or FORBIDDEN.search(s) or PREDICT.search(s))]}
    for s in out["what"]:
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
    rows = con.execute("select s.ticker, b.body from stocks s left join business b using(ticker) where s.active = 1 and s.market = 'KR'").fetchall()
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
        if b.get("market") == "US" or (b.get("seg") or {}).get("year") == year or b.get("year") != year:  # 미국은 us.read_10k 가 읽는다
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
    for rno, title in con.execute("select rcept_no, title from disclosures where read_model is not 'rule' and read_model is not '8-K'").fetchall():  # 미국 8-K 는 번호로 이미 정했다
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


def krw(x: int) -> str:
    """원 → 「333.6조원」 「5,583억원」."""
    if abs(x) >= 10**12:
        return f"{x / 10**12:,.1f}조원"
    if abs(x) >= 10**8:
        return f"{x / 10**8:,.0f}억원"
    return f"{x:,.0f}원"


def usd(x: float) -> str:
    """달러 → 「2,159억 달러」 「1.2조 달러」 「35만 달러」."""
    if abs(x) >= 10**12:
        return f"{x / 10**12:,.1f}조 달러"
    if abs(x) >= 10**8:
        v = x / 10**8  # 1,000억 달러 밑에서 소수가 있으면 한 자리 — 23.1억 달러가 「23억」으로 바뀌지 않게
        return f"{v:,.1f}억 달러" if abs(x) < 10**10 and abs(v - round(v)) >= 0.05 else f"{v:,.0f}억 달러"
    if abs(x) >= 10**4:
        return f"{x / 10**4:,.0f}만 달러"
    return f"{x:,.0f}달러"


# 사실을 만드는 동안의 시장 — facts() 가 종목에 맞춰 바꾼다. 금액 함수 하나(won)와 링크 함수 하나(link)를 모두가 쓰니 여기만 바뀌면 된다
_MARKET = {"money": krw, "link": lambda rno: DART.format(rno), "per": "원"}  # per = 「100원어치 팔아 몇 원」의 단위


def won(x: float) -> str:
    """노트의 모든 금액은 이 한 함수로 — 국내는 원, 미국 종목을 만드는 동안은 달러."""
    return _MARKET["money"](x)


def link(rno: str) -> str:
    return _MARKET["link"](rno)


def per(x: float) -> str:
    """100원(달러)어치 팔아 남긴 돈 — 「60원」「32.5달러」."""
    return f"{x}{_MARKET['per']}"


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
        slots = {"연도": yy, "비율": f"{m:.1f}%", "백원당": per(round(m))} | ({"손해": per(round(-m))} if m < 0 else {})
        prev = fin[1] if len(fin) > 1 else None
        if prev and prev[1] and prev[2] is not None and prev[1] > 0:
            was = prev[2] / prev[1] * 100
            slots |= {"전년비율": f"{was:.1f}%", "전년연도": f"{prev[0]}년", "힘": power(m, was)}
        out.append({"id": "F5", "text": f"{yy} 영업이익률 {slots['비율']} — 100{_MARKET['per']}어치 "
                    + (f"팔 때마다 본업에서 {slots['손해']}씩 잃음" if "손해" in slots else f"팔아 본업으로 {slots['백원당']}{josa(slots['백원당'], '을')} 남김")
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
    if what == "매출" and prev is not None and prev <= 0:  # 「매출 흑자 전환」은 말이 안 된다
        return f"{what} {won(cur)}(1년 전엔 매출 없음)"
    _, _, chg = trend(cur, prev)
    return f"{what} {won(cur)}" + (f"({than}보다 {chg})" if chg.startswith(("+", "-")) else f"({chg})" if chg else "")


def _slots(key: str, cur: int | None, prev: int | None) -> dict:
    """「{F8.매출}」「{F8.매출폭}」「{F8.매출방향}어요」 — 노트의 F1·F2 와 같은 빈칸 모양."""
    if cur is None:
        return {}
    if key == "매출" and prev is not None and prev <= 0:
        return {key: won(cur)}
    _, way, chg = trend(cur, prev)
    return ({key: won(cur)} | ({f"{key}방향": way} if way else {})
            | ({f"{key}폭": chg.lstrip("+-")} if chg.startswith(("+", "-")) else {}))  # fmt: skip


def relation(rev: int | None, rp: int | None, op: int | None, opp: int | None) -> dict:
    """판 돈(매출)과 남긴 돈(영업이익)이 1년 전보다 어떻게 움직였나 — 말 줄기와 100원당 남긴 돈. 계산은 코드가, 말은 AI 가 옮긴다."""
    out = {}
    if rev and rev > 0 and op is not None:
        m = op / rev * 100
        out["백원당"] = per(round(m))
        if m < 0:
            out["손해"] = per(round(-m))
        if rp and rp > 0 and opp is not None:
            pm = opp / rp * 100
            out["힘"] = power(m, pm)
            if round(m) == round(pm) and out["힘"] != "비슷했":  # 「4원(1년 전엔 4원) … 세졌어요」로 읽히지 않게 소수 한 자리
                out["백원당"] = per(f"{m:.1f}")
            out["전년백원당"] = per(f"{pm:.1f}") if "." in out["백원당"] else per(round(pm))
    if rev and rp and rp > 0 and op is not None and opp and opp > 0:
        r, o = rev / rp - 1, op / opp - 1
        out["관계"] = (RELATIONS[0] if r > 0 and o > r else RELATIONS[1] if r > 0 and 0 <= o <= r else
                      RELATIONS[2] if r > 0 and o < 0 else RELATIONS[3] if r <= 0 and o > 0 else RELATIONS[4])  # fmt: skip
    return out


def power(now: float, was: float) -> str:
    """100원당 남긴 돈(영업이익률 %)이 1년 전보다 — 「남기는 힘이 {힘}어요」의 줄기. 0.2%p 안쪽만 비슷."""
    return "더 세졌" if now - was >= 0.2 else "약해졌" if was - now >= 0.2 else "비슷했"


STRONGER, WEAKER = re.compile(r"세졌|커졌|좋아졌|나아졌|높아졌"), re.compile(r"약해졌|작아졌|나빠졌|낮아졌")


RELATIONS = ("판 돈보다 남긴 돈이 더 빨리 늘었", "판 돈이 늘어난 만큼은 남긴 돈이 늘지 않았",
             "더 많이 팔았지만 남긴 돈은 줄었", "덜 팔았지만 남긴 돈은 늘었", "판 돈도 남긴 돈도 줄었")  # fmt: skip
REL_WORDS = re.compile(r"판 돈보다 남긴 돈이 더|늘어난 만큼은? 남긴 돈|팔았지만 남긴 돈|판 돈도 남긴 돈도")


def quarter_facts(con: sqlite3.Connection, ticker: str, us: dict | None = None, mid: dict | None = None) -> list[dict]:
    """F8 = 가장 최근 분기 3개월 · F9 = 올해 누적 — 둘 다 1년 전 같은 때와 견준다(분기 보고서가 같이 준다). 계산은 코드가.
    미국은 4분기도 있고(연간−9개월) 분기 이름은 회사 회계연도라 실제 달로 부른다 — 「2026년 5~7월(회사 기준 2분기)」."""
    row = con.execute("select year, q, revenue, operating_income, revenue_prev, op_prev, revenue_ytd, op_ytd, revenue_ytd_prev, op_ytd_prev,"
                      " rcept_no, period_start, period_end, basis from quarters where ticker = ? order by year desc, q desc limit 1", (ticker,)).fetchone()  # fmt: skip
    if not row:
        return []
    y, q, rev, op, rp, opp, ry, oy, ryp, oyp, rno, ps, pe, basis = row
    if us and ps:
        qname, months = span_label(ps, pe), f"회사 기준 {q}분기"
        ytd = span_label(con.execute("select min(period_start) from quarters where ticker = ? and year = ?", (ticker, y)).fetchone()[0], pe)
    else:
        (name, months), qname, ytd = QLABEL[q], f"{y}년 {QLABEL[q][0]}", f"{y}년 1~{q * 3}월"
    url, out = link(rno), []
    if parts := [x for x in (_change("매출", rev, rp, "1년 전 같은 분기"), _change("영업이익", op, opp, "1년 전 같은 분기")) if x]:
        slots = {"분기": qname, "달": months} | _slots("매출", rev, rp) | _slots("이익", op, opp) | relation(rev, rp, op, opp)
        if us and us.get("rate") and rev:
            slots["매출원화"] = f"약 {krw(rev * us['rate'])}"
        if basis == "보도자료":  # 미국 — 분기보고서 전, 실적 발표 보도자료 숫자 (10-Q 가 오면 그 숫자로 바뀐다)
            slots["기준"] = "실적 발표 보도자료 기준"
        out.append({"id": "F8", "text": f"{qname}({months}) " + " · ".join(parts) + (" · 실적 발표 보도자료 기준(분기보고서 전)" if basis == "보도자료" else ""),
                    "url": url, "tone": 0, "slots": slots})  # fmt: skip
    if q >= 2 and (parts := [x for x in (_change("매출", ry, ryp, "작년 같은 기간"), _change("영업이익", oy, oyp, "작년 같은 기간")) if x]):
        out.append({"id": "F9", "text": f"{ytd} 누적 " + " · ".join(parts), "url": url, "tone": 0,
                    "slots": {"기간": ytd} | _slots("매출", ry, ryp) | _slots("이익", oy, oyp) | relation(ry, ryp, oy, oyp)})  # fmt: skip
    unit = "100달러어치" if us else "100원어치"
    if (mid if mid is not None else industry_mid(con, ticker)).get("금융"):  # 금융회사는 「100원당」이 다른 업종과 같은 잣대가 아니다
        for f in out:
            for k in ("백원당", "전년백원당", "힘"):
                f["slots"].pop(k, None)
    for f in out:  # 100원당 남긴 돈도 사실 문장에 — 출처 창에 보이고, 숫자 대조(빈칸 값)도 통과하게
        if "전년백원당" in f["slots"]:
            pv = f["slots"]["전년백원당"]
            was = f"1년 전엔 {pv[1:]}씩 잃음" if pv.startswith("-") else f"1년 전엔 {pv} 남김"
            f["text"] += (f" · {unit} 팔 때마다 본업에서 {f['slots']['손해']}씩 잃음({was})" if "손해" in f["slots"]
                          else f" · {unit} 팔아 본업으로 {f['slots']['백원당']} 남김({was if pv.startswith('-') else '1년 전 ' + pv})")
    return out


def us_facts(con: sqlite3.Connection, ticker: str) -> list[dict]:
    """미국만 — F13 주당순이익(EPS, 미국 투자자가 가장 먼저 보는 숫자) · F14 지난 1년 주주에게 돌려준 돈과 주식 보상 (현금흐름표)."""
    out = []
    row = con.execute("select year, q, eps, rcept_no, period_start, period_end from quarters where ticker = ? and eps is not null"
                      " order by year desc, q desc limit 1", (ticker,)).fetchone()  # fmt: skip
    if row:
        y, q, eps, rno, ps, pe = row
        prev = con.execute("select eps from quarters where ticker = ? and year = ? and q = ?", (ticker, y - 1, q)).fetchone()
        prev = prev and prev[0]
        qname = span_label(ps, pe)
        tone, way, chg = trend(eps, prev) if prev is not None else (0, "", "")
        slots = {"분기": qname, "값": f"{eps:,.2f}달러"} | ({"전년값": f"{prev:,.2f}달러"} if prev is not None else {}) | ({"방향": way} if way else {}) | (
            {"폭": chg.lstrip("+-")} if chg.startswith(("+", "-")) else {})
        out.append({"id": "F13", "text": f"{qname} 주당순이익(EPS) {slots['값']}" + (f"(1년 전 {slots['전년값']})" if prev is not None else ""),
                    "url": link(rno), "tone": 0, "slots": slots})  # fmt: skip
    last = con.execute("select period_end from financials where ticker = ? order by fiscal_year desc limit 1", (ticker,)).fetchone()
    row = last and con.execute("select period_start, period_end, buyback, dividends, sbc, accn from flows where ticker = ? and months = 12 and period_end = ?",
                               (ticker, last[0])).fetchone()  # 가장 최근 1년만 — 그해에 없었으면 앞선 해 것을 끌어오지 않는다(버크셔 2024년 자사주)  # fmt: skip
    if row:
        ps, pe, bb, dv, sbc, accn = row
        span = span_label(ps, pe)
        given = [(k, usd(v)) for k, v in (("자사주 매입", bb), ("배당", dv)) if v]
        if given:
            out.append({"id": "F14", "text": f"{span} 주주에게 돌려준 돈 — " + " · ".join(f"{k} {v}" for k, v in given), "url": link(accn), "tone": 0,
                        "slots": {"기간": span} | {k.replace(" ", ""): v for k, v in given}})  # fmt: skip
        if sbc:  # 주식 보상은 주주에게 돌려준 돈이 아니다 — 따로 (사실이 한 줄이면 AI 가 섞어 쓴다, 알파벳·코인베이스 10/10)
            out.append({"id": "F18", "text": f"{span} 임직원에게 주식으로 준 보상 {usd(sbc)} — 주주에게 돌려준 돈이 아니라 월급처럼 준 것이라 주식 수가 늘어나는 쪽",
                        "url": link(accn), "tone": 0, "slots": {"기간": span, "주식보상": usd(sbc)}})  # fmt: skip
    biz = con.execute("select body, rcept_no from business where ticker = ?", (ticker,)).fetchone()
    geo = biz and json.loads(biz[0]).get("geo")
    if geo and len(geo) >= 2:  # 어디서 파나 — 코드가 나눈 비중
        out.append({"id": "F15", "text": "지역별 매출 비중 — " + " · ".join(f"{g['name']} {g['share']}" for g in geo), "url": link(biz[1]), "tone": 0,
                    "slots": {"첫지역": geo[0]["name"], "첫지역몫": geo[0]["share"], "둘째지역": geo[1]["name"], "둘째지역몫": geo[1]["share"]}})  # fmt: skip
    ol = con.execute("select accession, date, body from outlooks where ticker = ?", (ticker,)).fetchone()
    items = ol and json.loads(ol[2])["items"]
    if items:  # 회사가 실적 발표에서 밝힌 다음 기간 전망 — 회사의 말 그대로, 숫자는 원문 대조를 통과한 것만 (사용자 10/9: 싣는다)
        from hanjang.us import METRIC_KO, say_outlook
        d = date.fromisoformat(ol[1])
        period = json.loads(ol[2]).get("period", "")
        if any("span" in x for x in items):  # 항목마다 기간 — 한 문장에 분기와 1년을 섞지 않는다(오라클). 매출이 있는 쪽, 같으면 다음 분기
            pick = "year" if not any(x["span"] == "quarter" and x["metric"] == "revenue" for x in items) and any(x["span"] == "year" and x["metric"] == "revenue" for x in items) else "quarter"
            items = [x for x in items if x["span"] == pick] or [x for x in items]
            span = "다음 분기" if items[0]["span"] == "quarter" else "올해 1년(회계연도 전체)"
        else:
            span = "다음 분기" if re.search(r"quarter|\bQ[1-4]\b", period, re.I) else "올해 1년(회계연도 전체)" if re.search(r"year|annual|full", period, re.I) else "다음 기간"
        slots = {"날짜": f"{d.month}월 {d.day}일", "기간": span} | {METRIC_KO[x["metric"]]: say_outlook(x) for x in items}
        out.append({"id": "F16", "text": f"{d.month}월 {d.day}일 실적 발표에서 회사가 밝힌 {span} 전망 — "
                    + " · ".join(f"{METRIC_KO[x['metric']]} {say_outlook(x)}" for x in items), "url": link(ol[0]), "tone": 0, "slots": slots})  # fmt: skip
    for f in out:
        f["slots"] = {k: v for k, v in f["slots"].items() if v}
    return out


def industry_fact(con: sqlite3.Connection, ticker: str) -> list[dict]:
    """F10 = 같은 업종 회사들 가운데 자리 — 영업이익률(금융사는 ROE). 셋 이상 모일 때만. 순위·평균은 코드가 센다."""
    label, rows = peers_of(con, ticker)
    rows = [r[:8] + (r[9],) for r in rows]  # (ticker, name, 업종, year, revenue, op, net_income, equity, rcept_no)
    me = next((r for r in rows if r[0] == ticker), None)
    if not label or not me:
        return []
    # 매출이 없는 금융사는 금융사끼리만 — 「지주회사」로 묶인 KB금융과 SK 는 견줄 수 없다
    market = con.execute("select market from stocks where ticker = ?", (ticker,)).fetchone()
    same_year = not (market and market[0] == "US")  # 미국은 회계연도가 회사마다 달라 같은 해로 거르면 몇 곳만 남는다 — 각자 가장 최근 1년끼리
    peers = [r for r in rows if r[2] == label and (r[3] == me[3] or not same_year) and (r[4] is None) == (me[4] is None)]
    label = "금융지주" if label == "지주회사" and me[4] is None else label
    margin = all(r[4] for r in peers)  # 매출이 다 있으면 영업이익률, 아니면(금융) ROE
    ok = (lambda r: r[4] and r[5] is not None) if margin else (lambda r: r[6] is not None and r[7] and r[7] > 0)
    val = {r[0]: (r[5] / r[4] * 100 if margin else r[6] / r[7] * 100) for r in peers if ok(r)}
    # 비율이 ±100% 를 넘는 회사는 빼고 견준다 — 지분 이익이 영업이익으로 잡히는 지주회사(SK스퀘어 623%)는 같은 잣대가 아니다 (SK 10/9)
    val = {t: v for t, v in val.items() if abs(v) <= 100}
    if len(val) < 3 or ticker not in val:
        return []
    order = sorted(val, key=lambda t: -val[t])
    k, n, what = order.index(ticker) + 1, len(val), "영업이익률" if margin else "ROE"
    place = ("가장 높았" if k == 1 else "가장 낮았" if k == n else "한가운데였" if n % 2 and k == (n + 1) // 2  # 5곳 중 3번째 = 한가운데
             else f"{k}번째로 높았" if k <= n / 2 else f"{n - k + 1}번째로 낮았")  # 7곳 중 6번째 → 2번째로 낮았
    mid = statistics.median(val.values())  # 평균은 한두 곳에 끌려간다 — 가운데 회사의 값
    others = "·".join(r[1] for r in peers if r[0] != ticker and r[0] in val)
    return [{"id": "F10", "text": f"같은 업종({label}) {n}곳 가운데 {'가장 최근 회계연도' if not same_year else str(me[3]) + '년'} {what}{josa(what, '이')} {place}음 — {me[1]} {val[ticker]:.1f}% · {n}곳 중간값 {mid:.1f}% (함께 본 회사: {others})",
             "url": link(me[8]), "tone": 0,
             "slots": {"업종": label, "곳수": f"{n}곳", "지표": what, "자리": place, "비율": f"{val[ticker]:.1f}%", "중간값": f"{mid:.1f}%"}}]  # fmt: skip


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
    return [{"id": "F12", "text": text, "url": link(rno), "tone": 0,
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
    yy = seg["year"] if isinstance(seg["year"], str) else f"{seg['year']}년"
    return [{"id": "F11", "text": f"{yy} 사업부별 영업이익 — " + " · ".join(parts), "url": link(biz[1]), "tone": 0,
             "slots": {"연도": yy, "첫부문": rows[0]["name"]}}]  # fmt: skip


AD = re.compile(r"이벤트|캠페인|경품|사은|프로모션|청약 (접수|개시|진행|실시)|청약을 (받|연)|출시 기념|가입 고객|고객 대상|특판")
FINANCE_CODES = ("641", "642", "649", "65", "66")  # 은행·신탁·여신·보험·증권 — 고객 돈이 빚으로 잡혀 부채비율이 원래 높다. 지주회사(64992)는 아니다


# 원래 빚이 많은 업종 — 「빚이 많다」로 몰지 않고 이유를 함께 보인다 (우리 종목 안엔 같은 업종이 1~2곳뿐이라 중간값만으론 못 거른다, 10/9 점검)
HIGH_DEBT = {
    **dict.fromkeys(("조선", "방위산업", "항공우주", "철도차량"),
                    "배·무기·비행기·열차처럼 몇 년 걸려 만드는 것을 수주하면 대금 일부를 미리 받는데, 이 돈(선수금)이 빚으로 잡혀요"),
    "항공": "비행기를 빌려 쓰는 값(리스)이 빚으로 잡혀요",
    "전력·가스": "발전소·송전망 같은 큰 설비를 빚을 내 지어요",
    "건설": "분양 대금을 미리 받거나 공사 자금을 빌려 빚이 큰 편이에요",
}  # fmt: skip


def is_finance(code: str | None) -> bool:
    return bool(code) and code.startswith(FINANCE_CODES) and not code.startswith("64992")


def us_finance(sic: str | None) -> bool:
    """미국 금융회사 — SIC 60~63(은행·여신·증권·보험)과 6199(금융 서비스: 코인베이스·소파이). 고객 돈이 빚으로 잡혀 부채비율이 뜻이 없다."""
    return bool(sic) and (sic[:2] in ("60", "61", "62", "63") or sic == "6199")


SIC_LABEL = {"7372": "소프트웨어", "3674": "반도체", "6199": "금융 서비스", "7389": "사업 서비스", "7370": "인터넷 서비스", "3711": "자동차",
             "2834": "제약", "5331": "종합 소매", "4911": "전력", "3572": "저장장치", "3571": "컴퓨터", "2080": "음료", "3760": "우주항공",
             "6021": "은행", "7841": "영상 서비스", "6331": "보험", "5961": "온라인 소매", "3663": "통신장비", "6211": "증권", "2911": "정유",
             "7990": "엔터테인먼트", "3721": "항공기", "5812": "외식", "6324": "건강보험", "5211": "건자재 소매", "3531": "건설기계",
             "3600": "전기장비", "3576": "네트워크 장비", "3679": "전자부품", "3021": "신발", "5810": "외식", "7373": "컴퓨터 시스템"}  # fmt: skip


def peers_of(con: sqlite3.Connection, ticker: str) -> tuple[str | None, list[tuple]]:
    """(업종 이름, 같은 시장의 종목 재무) — 국내는 DART 업종 코드·노트 쓰는 종목(active), 미국은 SIC·미국 종목 전부.
    줄: (ticker, name, 업종 이름, fiscal_year, revenue, operating_income, net_income, equity, liabilities, rcept_no)."""
    me = con.execute("select market, induty_code, sic from stocks where ticker = ?", (ticker,)).fetchone()
    if not me:
        return None, []
    us = me[0] == "US"
    rows = con.execute(
        f"select s.ticker, s.name, {'s.sic' if us else 's.induty_code'}, f.fiscal_year, f.revenue, f.operating_income, f.net_income, f.equity, f.liabilities, f.rcept_no"
        " from stocks s join financials f on f.ticker = s.ticker and f.fiscal_year = (select max(fiscal_year) from financials g where g.ticker = s.ticker)"
        f" where {'s.market = ' + chr(39) + 'US' + chr(39) if us else 's.active = 1'}").fetchall()  # fmt: skip
    name = (lambda c: SIC_LABEL.get(c)) if us else sources.industry_label
    return name(me[2] if us else me[1]), [(r[0], r[1], name(r[2]), *r[3:]) for r in rows]


def industry_mid(con: sqlite3.Connection, ticker: str) -> dict:
    """같은 업종(우리 종목 안) 중간값 — 100원당 남긴 돈 · 부채비율. 셋 이상일 때만. 금융회사면 {"금융": True}.
    업종마다 원래 빚이 많거나(조선 선수금·항공 리스) 조금 남기는(유통·상사) 구조가 있어, 절대 기준만으로 판단하지 않게 (사용자 10/9)."""
    me = con.execute("select market, induty_code, sic from stocks where ticker = ?", (ticker,)).fetchone()
    code = me and (me[2] if me[0] == "US" else me[1])
    label, all_rows = peers_of(con, ticker)
    rows = [(r[0], r[2], r[4], r[5], r[7], r[8]) for r in all_rows]  # (ticker, 업종 이름, revenue, op, equity, liabilities)
    mine = next((r for r in rows if r[0] == ticker), None)
    fin = us_finance if me and me[0] == "US" else is_finance
    if fin(code) or (mine and mine[2] is None):
        return {"금융": True}
    codes = dict(con.execute(f"select ticker, {'sic' if me and me[0] == 'US' else 'induty_code'} from stocks"))
    peers = [r for r in rows if label and r[1] == label and not fin(codes.get(r[0])) and r[2]]
    out = {}
    margins = [r[3] / r[2] * 100 for r in peers if r[2] > 0 and r[3] is not None and abs(r[3] / r[2]) <= 1]
    debts = [r[5] / r[4] * 100 for r in peers if r[4] and r[4] > 0 and r[5] is not None]
    if len(margins) >= 3:
        out["백원당"] = statistics.median(margins)
    if len(debts) >= 3:
        out["부채비율"] = statistics.median(debts)
    if out:
        out |= {"업종": label, "곳수": len(peers)}
    if label in HIGH_DEBT:
        out |= {"업종": label, "곳수": len(peers), "빚이유": HIGH_DEBT[label]}
    return out


def when(d: date, today: date) -> str:
    """공시가 얼마나 지난 일인지 — 「최근 소식」에서 이번 주 일과 지난 일을 나눠 말하게 (사용자 10/9: 「이번 주」라며 7월 공시)."""
    days = (today - d).days
    return "이번 주" if days <= 7 else "지난주" if days <= 14 else f"{d.month}월"


def span_label(start: str, end: str) -> str:
    """기간 → 「2025년 2월~2026년 1월」 · 한 해 안이면 「2026년 5~7월」 · 달력 연도 그대로면 「2025년」. 52·53주 결산은 일주일을 빼고 본다."""
    a, b = date.fromisoformat(start) + timedelta(days=7), date.fromisoformat(end) - timedelta(days=7)
    if a.month == 1 and b.month == 12 and a.year == b.year:
        return f"{a.year}년"
    return f"{a.year}년 {a.month}~{b.month}월" if a.year == b.year else f"{a.year}년 {a.month}월~{b.year}년 {b.month}월"


def us_market(con: sqlite3.Connection, ticker: str) -> dict | None:
    """미국 종목이면 {cik, rate, rate_day} — 사실을 만드는 동안 금액은 달러, 링크는 SEC. 환율은 한국은행(731Y003) 가장 최근 날."""
    row = con.execute("select cik from stocks where ticker = ? and market = 'US'", (ticker,)).fetchone()
    if not row:
        return None
    fx = con.execute("select date, value from macro where series_id = 'ECOS:731Y003:0000003' order by date desc limit 1").fetchone()
    return {"cik": row[0], "rate": fx[1] if fx else None, "rate_day": fx[0] if fx else None}


def facts(con: sqlite3.Connection, ticker: str, today: date) -> list[dict]:
    """종목 하나의 사실 목록 — [{id, text, url, tone, slots}]. 문장도 숫자도, 좋은지 걱정인지(tone)도,
    AI 가 쓸 빈칸 값(slots)도 코드가 만든다. text 는 코드 대체 글·AI 이해용, slots 는 AI 글에 끼울 값."""
    us = us_market(con, ticker)
    if not us:
        return _facts(con, ticker, today, None)
    _MARKET.update(money=usd, per="달러", link=lambda accn: f"https://www.sec.gov/Archives/edgar/data/{us['cik']}/{accn.replace('-', '')}/{accn}-index.htm")
    try:
        return _facts(con, ticker, today, us)
    finally:
        _MARKET.update(money=krw, per="원", link=lambda rno: DART.format(rno))


def _facts(con: sqlite3.Connection, ticker: str, today: date, us: dict | None) -> list[dict]:
    out = []
    fin = con.execute("select fiscal_year, revenue, operating_income, net_income, equity, liabilities, rcept_no,"
                      " basis, period_start, period_end from financials where ticker = ? order by fiscal_year desc limit 5", (ticker,)).fetchall()  # fmt: skip
    if fin:
        y, rev, oi, ni, eq, li, rno, basis, ps, pe = fin[0]
        p = fin[1] if len(fin) > 1 else (None,) * 10
        url, yy = link(rno), (span_label(ps, pe) if us and ps else f"{y}년")  # 미국은 회계연도 이름 대신 실제 달 (엔비디아 「2026 회계연도」= 2025년 2월~2026년 1월)
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
            if us and us.get("rate"):  # 달러 먼저, 원화는 괄호 — 코드가 곱하고 언제 환율인지 같이 적는다
                d = date.fromisoformat(us["rate_day"])
                slots["원화"] = f"약 {krw(cur * us['rate'])}"
                tail += f" (약 {krw(cur * us['rate'])} · {d.month}월 {d.day}일 환율 {us['rate']:,.1f}원 기준)"
            out.append({"id": fid, "text": f"{yy} {what} {won(cur)}{tail}{base}", "url": url, "tone": tone,
                        "slots": slots})  # fmt: skip
        # 은행·보험은 예금·보험금이 빚으로 잡혀 부채비율이 수백~천 % — 초보자에게 오해만 준다.
        # 금융회사는 DART 에 「매출액」이 없다 → 그걸로 가린다
        mid = industry_mid(con, ticker)
        if li is not None and eq and eq > 0 and rev is not None and not mid.get("금융"):
            d = li / eq * 100
            r = f"{d:.1f}%"
            usual = mid.get("부채비율")  # 같은 업종 중간값 — 조선(선수금)·항공(리스)·전력처럼 원래 높은 업종이 있다
            if us:  # 미국 회사는 자사주 매입으로 자기 돈이 작게 잡히는 일이 흔하다 — 비율로 좋다·나쁘다를 가르지 않는다
                bb = con.execute("select buyback from flows where ticker = ? and months = 12 order by period_end desc limit 1", (ticker,)).fetchone()
                if bb and bb[0] and bb[0] >= eq * 0.1 and d > DEBT_BAD:  # 빚이 많아 보일 때만 이유를 붙인다(엔비디아 31% 에 붙으면 이상하다)
                    mid = mid | {"빚이유": f"자기 회사 주식을 많이 사들여(지난 1년 {usd(bb[0])}) 자기 돈이 작게 잡혀요 — 미국 큰 회사에 흔한 모양이에요"}
            bad = not us and d > DEBT_BAD and (usual is None or d > usual * 1.5) and "빚이유" not in mid
            out.append({"id": "F3", "text": f"{yy.split('~')[-1]} 말 부채비율 {r} (빚 {won(li)} · 자기 돈 {won(eq)})"
                        + (f" · 같은 업종({mid['업종']}) {mid['곳수']}곳 중간값 {usual:.0f}%" if usual is not None else ""), "url": url,
                        "tone": 0 if us else 1 if d < DEBT_GOOD else -1 if bad else 0,
                        "slots": {"연도": yy.split("~")[-1], "비율": r, "빚": won(li), "자기돈": won(eq)}
                        | ({"업종보통": f"{usual:.0f}%", "업종": mid["업종"]} if usual is not None else {})})  # fmt: skip
            if "빚이유" in mid:  # 「모든 문장에 원문 링크」 — 업종 설명은 사업보고서(F3)가 아니라 한장의 업종 풀이 글이 근거다
                out.append({"id": "F17", "text": f"빚이 많은 까닭 — {mid['빚이유']}", "url": url if us else "/learn/sector-debt",
                            "tone": 0, "slots": {"빚이유": mid["빚이유"]}})  # fmt: skip
        if ni is not None and eq and eq > 0:
            r = f"{ni / eq * 100:.1f}%"
            out.append({"id": "F4", "text": f"{yy} ROE {r} (순이익 {won(ni)} · 자기 돈 {won(eq)})", "url": url,
                        "tone": 1 if ni / eq * 100 >= ROE_GOOD else -1 if ni < 0 else 0,
                        "slots": {"연도": yy, "비율": r, "순이익": won(ni), "자기돈": won(eq)}})  # fmt: skip
        story = [f for f in story_facts(fin, url, yy) if not (f["id"] == "F5" and mid.get("금융"))]
        if us:
            for f in story:
                if f["id"] == "F5" and "전년연도" in f["slots"] and p[8]:
                    was = span_label(p[8], p[9])
                    f["text"] = f["text"].replace(f"({f['slots']['전년연도']} ", f"(1년 전 {was} ")
                    f["slots"]["전년연도"] = was  # 「1년 전(1년 전(…))」 — 빈칸엔 기간만
                if f["id"] == "F6":  # 숫자 해는 회사 회계연도 — 그렇게 밝힌다
                    f["text"] = f["text"].replace(f"({f['slots']['기간']})", f"(회사 회계연도 {f['slots']['기간']})", 1)
                    f["slots"]["기간"] = f"회사 회계연도 {f['slots']['기간']}"
        for f in story:  # 100원당 남긴 돈 — 같은 업종 중간값도 (유통·상사·정유는 원래 몇 원, 소프트웨어는 수십 원)
            if f["id"] == "F5" and mid.get("백원당") is not None:
                f["slots"] |= {"업종보통": per(f"{mid['백원당']:.0f}"), "업종": mid["업종"]}
                f["text"] += f" · 같은 업종({mid['업종']}) {mid['곳수']}곳 중간값 {per(f'{mid["백원당"]:.0f}')}"
        out += story
    biz = con.execute("select body, rcept_no from business where ticker = ?", (ticker,)).fetchone()
    if biz and (segs := json.loads(biz[0]).get("segments")):  # 무엇으로 버나 — 사업보고서의 부문별 매출 비중 (큰 것 둘)
        top = sorted(segs, key=lambda x: -float(x["share"].rstrip("%") or 0))[:2]
        slots = {f"{o}부문": x["name"].split(" · ")[-1] for o, x in zip(("첫", "둘째"), top)} | {f"{o}비중": x["share"] for o, x in zip(("첫", "둘째"), top)}
        out.append({"id": "F7", "text": "매출 비중 — " + ", ".join(f"{x['name']} {x['share']}" for x in top), "url": link(biz[1]),
                    "tone": 0, "slots": slots})  # fmt: skip
    out += quarter_facts(con, ticker, us, locals().get("mid")) + industry_fact(con, ticker) + segment_fact(con, ticker) + bond_fact(con, ticker, today)
    if us:
        out += us_facts(con, ticker)
    evs = con.execute("select rcept_no, date, title, code, direction from disclosures"
                      " where ticker = ? and date >= ? and importance >= 2 and code != 'OTHER'"
                      " order by importance desc, date desc limit 5",
                      (ticker, (today - timedelta(days=EVENT_DAYS)).isoformat())).fetchall()  # fmt: skip
    for k, (rno, d, title, code, dr) in enumerate(evs, 1):  # 중요한 것부터(D1 이 가장 중요), 같으면 최근 것부터
        d = date.fromisoformat(d)
        tone = ""
        day = f"{d.month}월 {d.day}일"
        easy = plain(title)
        if "결산실적공시예고" in re.sub(r"\s", "", title):  # 공시에서 읽어 둔 실제 발표일이 있으면 함께 — 「7월 30일에 실적을 발표하겠다고 미리 알렸어요」
            on = con.execute("select date from events where rcept_no = ? order by date limit 1", (rno,)).fetchone()
            if on:
                o = date.fromisoformat(on[0])
                easy = f"실적을 {o.month}월 {o.day}일에 발표하겠다고 미리 알렸어요"
        what = f" — 무슨 일: {easy}" if easy else ""
        out.append({"id": f"D{k}", "text": f"{day} {EVENT_KO[code]} 공시 「{tidy(title)}」{what}{tone}", "url": link(rno),
                    "tone": dr or 0, "slots": {"날짜": day, "종류": EVENT_KO[code], "제목": f"「{tidy(title)}」", "시기": when(d, today)}
                    | ({"무슨일": easy} if easy else {})})  # fmt: skip
    out += insider_facts(con, ticker, today)
    news = con.execute("select url, date, press, title, summary from news where ticker = ? and date >= ?"
                       " order by (summary is not null and summary != '') desc, date desc limit 10",  # 요약문 있는 것부터
                       (ticker, (today - timedelta(days=NEWS_DAYS)).isoformat())).fetchall()  # fmt: skip
    # 목표주가·매수 같은 말이 든 소식은 싣지 않는다 — 옮기기만 해도 권유가 된다 (불변식 1)
    news = [n for n in news if not FORBIDDEN.search(n[3] + " " + (n[4] or "")) and not AD.search(n[3])]
    for k, (url, d, press, title, summary) in enumerate(news, 1):
        d = date.fromisoformat(d)
        day = f"{d.month}월 {d.day}일"
        # text 에 요약문까지 — AI 는 여기 적힌 숫자만 그대로 옮길 수 있다(fill 의 토큰 대조). 기사 본문은 없다
        out.append({"id": f"N{k}", "text": f"{day} {press} 소식 「{title}」" + (f" — {summary}" if summary else ""), "url": url, "tone": 0,
                    "slots": {"날짜": day, "매체": press, "제목": f"「{title}」", "시기": when(d, today)}})  # fmt: skip
    return out


def insider_facts(con: sqlite3.Connection, ticker: str, today: date) -> list[dict]:
    """지분 보고 — I1: 최근 90일 임원·주요주주 보고 집계 · I2~I3: 5% 대량보유 보고 최근 두 건.
    「샀다·팔았다」가 아니라 「보유 주식을 늘렸다·줄였다」 — 회사에서 받은 주식(보상)도 들어가기 때문. tone 은 늘 중립(0)."""
    rows = con.execute("select rcept_no, date, kind, who, change, rate from insiders where ticker = ? and date >= ?"
                       " order by date desc, rcept_no desc",
                       (ticker, (today - timedelta(days=EVENT_DAYS)).isoformat())).fetchall()  # fmt: skip
    out = []
    ex = [r for r in rows if r[2] == "임원" and r[4]]
    planned = dict(con.execute("select rcept_no, planned from insiders where ticker = ? and planned is not null", (ticker,)))
    if ex and planned:  # 미국 — Form 4 에서 장내 매수(P)·매도(S)만 남겼다(보상·옵션 행사·세금 납부는 뺐다). 그래서 「샀·팔았」이 사실이다
        span = f"최근 {EVENT_DAYS}일"
        sold, bought = [r for r in ex if r[4] < 0], [r for r in ex if r[4] > 0]
        plan = [r for r in sold if planned.get(r[0])]
        slots, parts = {"기간": span}, []
        if sold:
            slots |= {"판보고": f"{len(sold)}건", "판주식": f"{korean_num(round(abs(sum(r[4] for r in sold))))}주"}
            if plan:  # 0건이면 말하지 않는다
                slots["계획"] = "전부" if len(plan) == len(sold) else f"{len(plan)}건"
            parts.append(f"시장에서 판 보고 {slots['판보고']}(합계 {slots['판주식']}"
                         + (f", {'모두' if slots['계획'] == '전부' else '그중 ' + slots['계획'] + '은'} 미리 정해 둔 계획에 따라" if plan else "") + ")")
        if bought:
            slots |= {"산보고": f"{len(bought)}건", "산주식": f"{korean_num(round(sum(r[4] for r in bought)))}주"}
            parts.append(f"시장에서 산 보고 {slots['산보고']}(합계 {slots['산주식']})")
        out.append({"id": "I1", "text": f"{span} 임원 장내 거래 보고 — " + " · ".join(parts), "url": link(ex[0][0]), "tone": 0, "slots": slots})
    elif ex:
        span = f"최근 {EVENT_DAYS}일"
        slots, parts = {"기간": span, "건수": f"{len(ex)}건"}, []
        for key, word, side in (("늘린", "늘린", [r for r in ex if r[4] > 0]), ("줄인", "줄인", [r for r in ex if r[4] < 0])):
            if side:
                n, total = f"{len(side)}건", f"{korean_num(abs(sum(r[4] for r in side)))}주"
                slots |= {f"{key}보고": n, f"{key}주식": total}
                parts.append(f"{word} 보고 {n}(합계 {total})")
        out.append({"id": "I1", "text": f"{span} 임원·주요주주 지분 보고 {len(ex)}건 — 보유 주식을 " + " · ".join(parts),
                    "url": link(ex[0][0]), "tone": 0, "slots": slots})  # fmt: skip
    for k, (rno, d, _, who, chg, rate) in enumerate([r for r in rows if r[2] == "5%"][:2], len(out) + 1):
        d = date.fromisoformat(d)
        day = f"{d.month}월 {d.day}일"
        way = f", 직전 보고보다 보유 주식 {korean_num(abs(chg))}주 {'늘림' if chg > 0 else '줄임'}" if chg else ""
        rc = con.execute("select rate_chg from insiders where rcept_no = ?", (rno,)).fetchone()[0] if planned and not chg else None
        if rc:  # 미국 — 직전 같은 보고자보다 비율이 몇 %p
            way = f", 직전 보고보다 {abs(rc):.1f}%p {'늘림' if rc > 0 else '줄임'}"
        slots = {"날짜": day, "누가": who} | ({"비율": f"{rate:.2f}%"} if rate is not None else {})
        if rate is not None and rate < 5:  # 5% 밑으로 내려가며 내는 마지막 보고 (뱅가드 0.0%)
            out.append({"id": f"I{k}", "text": f"{day} {who}의 대량보유 보고 — 보유 비율이 5% 밑으로 내려갔다고 알림({rate:.2f}%)", "url": link(rno), "tone": 0,
                        "slots": slots | {"방향": "5% 밑으로 줄였"}})  # fmt: skip
            continue
        if chg:
            slots |= {"주식": f"{korean_num(abs(chg))}주", "방향": "늘렸" if chg > 0 else "줄였"}
        out.append({"id": f"I{k}", "text": f"{day} {who}의 5% 이상 대량보유 보고 — 보유 비율 {rate:.2f}%{way}" if rate is not None
                    else f"{day} {who}의 5% 이상 대량보유 보고{way}", "url": link(rno), "tone": 0, "slots": slots})  # fmt: skip
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


def undash(text: str) -> str:
    """줄표(—) 대신 매끄러운 문장으로 — 「알렸어요 — 아직 숫자는 없어요」 → 「알렸어요. 아직 숫자는 없어요」 (사용자 10/9)."""
    text = re.sub(r"(요|다)\s*—\s*", r"\1. ", text)
    return re.sub(r"\s*—\s*", ", ", text)


def reword(text: str) -> str:
    """예전에 틀리게 풀었던 말 — 「결산실적공시 예고」는 1년치가 아니라 실적 발표 날짜 알림이다 (사용자 10/9). 노트 글·출처 창 모두."""
    text = re.sub(r"1년치 결산 실적을 발표할 날짜를", "실적을 발표할 날짜를", text)
    text = re.sub(r"1년(?:치)? (?:결산 )?실적을 언제 발표할지", "실적을 언제 발표할지", text)
    text = re.sub(r"(날짜를 미리 알렸어요|발표할지 미리 알렸어요)(\([^()]*\))?(?:\.|,)?\s*(?:—\s*)?아직 숫자는 없어요", r"\1\2", text)
    return re.sub(r"(미리 알렸[^.]*\.)\s*아직 숫자는 없어요\.?", r"\1", text)  # 「…알렸다고도 했어요. 아직 숫자는 없어요.」


def mend(text: str) -> str:
    """빈칸 값(낱말 줄기 「4번째로 많았」「줄였」, 「2021년」)에 AI 가 토씨·글자를 또 붙여 깨진 이음을 고친다.
    fill 에서도, 화면에 그릴 때도(이미 쓴 노트) 쓴다 — 「많았으로」「높았였어요」「3년년」「줄였 보고」「(9.4% -9.4%)」 (사용자 10/9 검토)."""
    text = re.sub(r"(았|었)(?:으로|로)(?=[,\s])", r"\1고", text)
    text = re.sub(r"(았|었)(?:였|이었)", r"\1", text)
    text = re.sub(r"(\d년)년", r"\1", text)
    text = re.sub(r"(\d주)이에요", lambda m: m[1] + "예요", text)
    text = re.sub(r"([았었였했])어요고(?=[,\s])", lambda m: m[1] + "고", text)  # 「발표했어요고,」 — 끝맺은 말 뒤에 「고」를 또 붙였다  # 「433만 2,118주이에요」
    text = re.sub(r"달러이(에요|라서|라(?=\s)|었)", lambda m: "달러" + {"에요": "예요", "라서": "라서", "라": "라", "었": "였"}[m[1]], text)  # 「26달러이라서」 — 미국 노트
    text = re.sub(r"(렸|였|았|었) 보고를", r"\1다는 보고를", text)
    text = re.sub(r"(렸|였|았|었) (보고|공시)", r"\1다고 \2", text)
    text = re.sub(r"(\d[\d,]*(?:건|주|명|곳))([^()]{0,20})\(\1\)", r"\1\2", text)  # 「1건 있었어요(1건)」
    # 날짜로 시작하는 문장 — 날짜는 문장 끝 괄호로 (사용자 10/9: 날짜가 앞에서 오가면 요점이 안 보인다)
    text = re.sub(r"(?:^|(?<=[.!?] ))(\d+월 \d+일(?:(?:과|와|,| ·) (?:\d+월 )?\d+일)*)(?:에는|에도|에|엔|,)?\s+(.+?)([.!?])(?=\s|$)",
                  lambda m: f"{m[2][:1].upper()}{m[2][1:]}({m[1]}){m[3]}", text)
    text = re.sub(r"(았|었)에(?=\s)", r"\1던 해에", text)  # 「4번째로 많았에 머물렀어요」
    text = re.sub(r"(늘었|줄었)(?=\s*[·)])", lambda m: "증가" if m[1] == "늘었" else "감소", text)  # 괄호 속 「10.9% 늘었 ·」
    text = undash(text)
    text = reword(text)
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
    for fid in {f for f, _ in SLOT.findall(raw)} | set(refs):  # 남기는 힘을 직접 썼다면 코드가 정한 쪽과 맞는지
        way = by.get(fid, {}).get("slots", {}).get("힘")
        bare_ = SLOT.sub("", raw)
        if way and ((STRONGER.search(bare_) and way != "더 세졌") or (WEAKER.search(bare_) and way != "약해졌")):
            raise ValueError(f"남기는 힘이 사실과 반대: {raw!r}")
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
        if want and not got:  # AI 가 이 칸을 비우거나 다른 쪽 사실과 섞어 다 빠졌으면 — 노트를 버리지 않고 그 사실을 코드 문장 하나로 (스타벅스 10/10)
            f = next(f for f in fs if f["id"] in want)
            got = note[key] = [{"text": say(f), "refs": [f["id"]]}]
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
    if text.count("(") != text.count(")") or text.count("「") != text.count("」"):
        raise ValueError(f"괄호 짝이 안 맞음: {text!r}")
    outside = re.sub(r"\([^()]*\)|「[^」]*」", "", text)
    if not all(r.startswith("N") for r in refs) and HARD.search(outside):
        raise ValueError(f"어려운 말: {text!r}")
    if JUDGE.search(outside):
        raise ValueError(f"좋다·나쁘다를 단정: {text!r}")
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
                if "이번 주" in y["text"] and not any(by.get(r, {}).get("slots", {}).get("시기") == "이번 주" for r in y["refs"]):
                    y["text"] = re.sub(r"이번 주(?:에는|엔|에|의)?\s*", "최근 ", y["text"])
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
    why = by.get("F17", {}).get("slots", {}).get("빚이유")
    if why and not any("F17" in x["refs"] for sec in note["sections"] for x in sec["sentences"]):
        for sec in note["sections"]:
            at = next((i for i, x in enumerate(sec["sentences"]) if "F3" in x["refs"]), None)
            if at is not None:
                sec["sentences"].insert(at + 1, {"text": undash(f"이 업종은 {why}."), "refs": ["F17"]})
                break
    for key, sign in (("good", 1), ("concern", -1)):
        if not note[key]:
            note[key] = [{"text": mend(say(f)), "refs": [f["id"]]} for f in fs if f["tone"] == sign][:3]
    for key, what in (("good", "긍정"), ("concern", "부정")):
        if note[key]:
            try:
                note[f"{key}_title"] = short_title(j.get(f"{key}_title"), what)
            except ValueError:  # 소제목이 틀리면 비워 둔다 — finish 가 코드로 짓는다
                pass
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
        return mend(say(pick))
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
            return f"{s['연도']} {what}은 {s['값']}{josa(s['값'], '으로')}, 전년보다 {s['폭']} {s['방향']}어요."
        return f"{s['연도']} {what}은 {s['값']}{'였' if not josa(s['값'], '이') == '이' else '이었'}어요."
    if i == "F3" and "비율" in s:
        return f"{s['연도']} 말 빚은 {s['빚']}, 자기 돈은 {s['자기돈']}이에요(부채비율 {s['비율']})."
    if i == "F4" and "비율" in s:
        return f"자기 돈으로 얼마나 벌었는지 보는 ROE는 {s['비율']}였어요({s['연도']} 순이익 {s['순이익']})."
    if i == "F5":
        unit = "달러" if s["백원당"].endswith("달러") else "원"
        return f"100{unit}어치 팔면 본업으로 {s['백원당']}{josa(s['백원당'], '을')} 남긴 셈이에요(영업이익률 {s['비율']})."
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

    groups = zip(TITLES, (("F1", "F2", "F3", "F17", "F4", "F5", "F7", "F10", "F12", "F14", "F18", "F15"), ("F8", "F9", "F11", "F13", "F16"), ("D", "N"), "I"))
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


def main(tickers: list[str], today: date, only_changed: bool = False, read: bool = True, carry: bool = False) -> None:
    """only_changed: 이번 주 노트가 이미 있고 사실이 그대로인 종목은 건너뛴다 (화~일 매일 실행).
    carry: 월요일 — 사실이 지난 노트와 한 글자도 다르지 않으면 그 글을 이번 주로 옮겨 적는다(AI 를 부르지 않는다).
    서버 실측(2026-10-11) 103곳 중 95곳이 그대로였다 — 월요일마다 전부 다시 쓰던 비용의 대부분. 손으로 다시 쓸 땐(--rewrite) 끈다.
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
    # 예시 사람(personas.py)이 담은 종목은 「누가 담은 종목」으로 치지 않는다 — 소식 하나 바뀐 것으로 다시 쓰지 않게 (비용, 2026-10-11)
    held = {t for (t,) in con.execute("select distinct h.ticker from holdings h join users u on u.id = h.user_id where u.email not like '%@persona.hanjang.local'")}
    for t, name in rows:
        fs = facts(con, t, today)
        if not fs:
            continue
        if only_changed:
            old = con.execute("select facts from notes where ticker = ? and week = ?", (t, week)).fetchone()
            if not changed(fs, old and json.loads(old[0]), t in held):
                by["same"] = by.get("same", 0) + 1
                continue
        if carry and not con.execute("select 1 from notes where ticker = ? and week = ?", (t, week)).fetchone():
            last = con.execute("select facts, body, writer from notes where ticker = ? and week < ? order by week desc limit 1", (t, week)).fetchone()
            if last and last[2] != "code" and json.loads(last[0]) == json.loads(json.dumps(fs, ensure_ascii=False)):  # 코드 대체 글은 옮기지 않고 다시 써 본다
                con.execute("insert into notes values (?, ?, ?, ?, ?, ?)", (t, week, last[0], last[1], last[2], datetime.now().isoformat()))
                con.commit()
                by["carried"] = by.get("carried", 0) + 1
                continue
        note, writer = write(name, fs, today)
        note["links"] = {f["id"]: f["url"] for f in fs}
        con.execute("insert or replace into notes values (?, ?, ?, ?, ?, ?)",
                    (t, week, json.dumps(fs, ensure_ascii=False), json.dumps(note, ensure_ascii=False),
                     writer, datetime.now().isoformat()))  # fmt: skip
        con.commit()
        by[writer] = by.get(writer, 0) + 1
    print(f"노트 {sum(v for k, v in by.items() if k not in ('same', 'carried'))}장 {by} · AI {llm.spent['calls']}콜 ${llm.spent['usd']:.3f}")


if __name__ == "__main__":
    main([a for a in sys.argv[1:] if a != "--rewrite"], date.today(), read="--rewrite" not in sys.argv)
