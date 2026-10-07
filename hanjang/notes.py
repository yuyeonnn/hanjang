"""주간 노트 만들기 ②~⑥ (PRD §5.2): 공시 읽기(규칙→AI) → 사실 묶음(코드) → 쓰기(AI) → 검사 → 저장.
`python -m hanjang.notes [종목코드 …]` — 비우면 전 종목. 같은 주에 다시 돌리면 덮어쓴다.
**숫자와 늘었다/줄었다는 AI 가 쓰지 않는다.** AI 는 `{F1.값}` 같은 빈칸만 쓰고 코드가 채운다 —
AI 글에 숫자가 하나라도 있거나, 사실과 반대 방향 낱말을 쓰면 글째 버린다."""

import json
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta

from hanjang import db, llm

DART = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"
TAXONOMY = ("RIGHTS_ISSUE", "BONUS_ISSUE", "SPLIT", "REVERSE_SPLIT", "BUYBACK", "CB_BW",
            "MAJOR_CONTRACT", "EARNINGS", "DIVIDEND", "LAWSUIT", "MA", "HOLDER_CHANGE",
            "CLINICAL", "TRADING_HALT", "OTHER")  # fmt: skip
EVENT_KO = {
    "RIGHTS_ISSUE": "유상증자", "BONUS_ISSUE": "무상증자", "SPLIT": "액면분할",
    "REVERSE_SPLIT": "감자·병합", "BUYBACK": "자사주 매입", "CB_BW": "전환사채·신주인수권",
    "MAJOR_CONTRACT": "대형 계약", "EARNINGS": "실적", "DIVIDEND": "배당", "LAWSUIT": "소송",
    "MA": "합병·인수", "HOLDER_CHANGE": "대주주 지분 변동", "CLINICAL": "임상",
    "TRADING_HALT": "거래정지", "OTHER": "기타",
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
    (r"매매거래정지|관리종목지정|상장폐지|감사의견(거절|부적정|한정)", "TRADING_HALT", 3),
    (r"사업보고서|반기보고서|분기보고서|기업설명회", "OTHER", 1),
)
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
TITLES = ("회사 사정은 어떤가요?", "요즘 무슨 일이 있었나요?", "요즘 기사는요")
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
    return f"{x * 100:+.1f}%"


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


def facts(con: sqlite3.Connection, ticker: str, today: date) -> list[dict]:
    """종목 하나의 사실 목록 — [{id, text, url, tone, slots}]. 문장도 숫자도, 좋은지 걱정인지(tone)도,
    AI 가 쓸 빈칸 값(slots)도 코드가 만든다. text 는 코드 대체 글·AI 이해용, slots 는 AI 글에 끼울 값."""
    out = []
    fin = con.execute("select fiscal_year, revenue, operating_income, net_income, equity, liabilities, rcept_no,"
                      " basis from financials where ticker = ? order by fiscal_year desc limit 2", (ticker,)).fetchall()  # fmt: skip
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
            slots = {"연도": yy, "값": won(cur)} | ({"변화": chg} if chg else {}) | ({"방향": way} if way else {})
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
    evs = con.execute("select rcept_no, date, title, code, direction from disclosures"
                      " where ticker = ? and date >= ? and importance >= 2 and code != 'OTHER'"
                      " order by importance desc, date desc limit 5",
                      (ticker, (today - timedelta(days=EVENT_DAYS)).isoformat())).fetchall()  # fmt: skip
    for k, (rno, d, title, code, dr) in enumerate(sorted(evs, key=lambda r: r[1], reverse=True), 1):
        d = date.fromisoformat(d)
        tone = {1: " — 주주에게 반가운 쪽으로 분류", -1: " — 주주에게 걸리는 쪽으로 분류"}.get(dr, "")
        day = f"{d.month}월 {d.day}일"
        out.append({"id": f"D{k}", "text": f"{day} {EVENT_KO[code]} 공시 「{title}」{tone}", "url": DART.format(rno),
                    "tone": dr or 0, "slots": {"날짜": day, "종류": EVENT_KO[code], "제목": f"「{title}」"}})  # fmt: skip
    news = con.execute("select url, date, press, title from news where ticker = ? and date >= ?"
                       " order by date desc limit 5",
                       (ticker, (today - timedelta(days=NEWS_DAYS)).isoformat())).fetchall()  # fmt: skip
    # 목표주가·매수 같은 말이 든 기사는 싣지 않는다 — 옮기기만 해도 권유가 된다 (불변식 1)
    news = [n for n in news if not FORBIDDEN.search(n[3])]
    for k, (url, d, press, title) in enumerate(news, 1):
        d = date.fromisoformat(d)
        day = f"{d.month}월 {d.day}일"
        out.append({"id": f"N{k}", "text": f"{day} {press or ''} 기사 제목 「{title}」", "url": url, "tone": 0,
                    "slots": {"날짜": day, "매체": press or "기사", "제목": f"「{title}」"}})  # fmt: skip
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


def fill(sent: dict, by: dict[str, dict]) -> dict:
    """AI 문장의 빈칸을 코드 값으로 채운다. 쓴 빈칸의 사실은 근거(refs)에 저절로 들어간다.
    검사: ① 빈칸 밖에 숫자 금지 ② 없는 빈칸 금지 ③ 빈칸 없이 쓴 방향 낱말이 사실과 반대면 탈락."""
    raw, refs = sent["text"], list(dict.fromkeys(sent["refs"]))
    # 연도(「2025년」)만은 직접 써도 된다 — 사실의 연도와 글자 그대로 같을 때만. 다른 숫자는 전부 빈칸으로
    years = {f["slots"]["연도"] for f in by.values() if "연도" in f.get("slots", {})}
    bare = SLOT.sub("", raw)
    for y in years:
        bare = bare.replace(y, "")
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
    text = SLOT.sub(lambda m: by[m[1]]["slots"][m[2]], raw).replace("었었", "었")
    return {"text": text, "refs": refs}


def check_note(note: dict, fs: list[dict]) -> dict:
    """빈칸을 채운 글 전체 검사 — 하나라도 어기면 ValueError (글째 버린다).
    ① 문장마다 있는 사실 id ② 사실에 없는 숫자 금지(빈칸을 채운 뒤에도 한 번 더) ③ 금지어 ④ 예측 말투
    ⑤ 좋게 본 것은 +1 사실만, 걱정되는 것은 −1 사실만 근거로 — 그런 사실이 있는데 비워 두면 탈락."""
    ids = {f["id"] for f in fs}
    allowed = set().union(*(numbers(f["text"]) for f in fs)) if fs else set()
    quoted = [f["text"] for f in fs]
    for key, sign in (("good", 1), ("concern", -1)):
        want = {f["id"] for f in fs if f["tone"] == sign}
        got = note.get(key) or []
        if want and not got:
            raise ValueError(f"{key} 비었음 — 해당 사실 {sorted(want)}")
        if any(not set(s["refs"]) <= want for s in got):
            raise ValueError(f"{key} 에 다른 쪽 사실이 섞임")
    sents = (note["summary"] + [s for sec in note["sections"] for s in sec["sentences"]]
             + (note.get("good") or []) + (note.get("concern") or []))  # fmt: skip
    if not isinstance(note["headline"], str) or not sents:
        raise ValueError("빈 노트")
    for s in [{"text": note["headline"], "refs": list(ids)}] + sents:
        text, refs = s["text"], s["refs"]
        if not isinstance(text, str) or not refs or not set(refs) <= ids:
            raise ValueError(f"근거 없는 문장: {text!r}")
        if bad := numbers(text) - allowed:
            raise ValueError(f"사실에 없는 숫자 {bad}: {text!r}")
        bare = re.sub(r"「([^」]*)」", lambda m: "" if any(m[1] in q for q in quoted) else m[0], text)
        if FORBIDDEN.search(bare):
            raise ValueError(f"금지어: {text!r}")
        if PREDICT.search(bare) and not all(r.startswith("N") for r in refs):
            raise ValueError(f"예측 말투: {text!r}")
    return note


def short_title(t: str, what: str) -> str:
    """긍정·부정 칸의 짧은 소제목 — 숫자·금지어·예측 말투 없이 24자 안."""
    t = (t or "").strip()
    if not t or len(t) > 24 or re.search(r"\d", t) or FORBIDDEN.search(t) or PREDICT.search(t):
        raise ValueError(f"{what} 소제목: {t!r}")
    return t


def fill_note(j: dict, fs: list[dict]) -> dict:
    """AI 응답(빈칸 글) → 채운 노트 → 검사. 빈칸은 good/concern 칸 검사보다 먼저 채운다(근거가 늘 수 있다)."""
    by = {f["id"]: f for f in fs}
    head = fill({"text": j["headline"], "refs": []}, by)["text"]
    note = {"headline": head,
            "summary": [fill(s, by) for s in j["summary"]],
            "sections": [{"title": sec["title"], "sentences": [fill(s, by) for s in sec["sentences"]]}
                         for sec in j["sections"] if sec["sentences"]],
            "good": [fill(s, by) for s in j["good"]],
            "concern": [fill(s, by) for s in j["concern"]]}  # fmt: skip
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


def code_note(fs: list[dict]) -> dict:
    """AI 글이 검사에서 떨어졌을 때 — 사실 목록을 그대로 문장으로 (PRD §4.3)."""
    groups = zip(TITLES, "FDN")
    secs = [{"title": t, "sentences": [{"text": f["text"] + ".", "refs": [f["id"]]}
                                       for f in fs if f["id"].startswith(p)]} for t, p in groups]  # fmt: skip
    side = {k: [{"text": f["text"] + ".", "refs": [f["id"]]} for f in fs if f["tone"] == sign]
            for k, sign in (("good", 1), ("concern", -1))}  # fmt: skip
    return {"headline": code_headline(fs), "summary": [],
            "sections": [s for s in secs if s["sentences"]], **side}


def finish(note: dict, fs: list[dict], name: str = "") -> dict:
    """좋게 본 것·걱정되는 것은 **늘 두 칸 다** 보인다 — 해당 사실이 없으면 코드가 「없었어요」를 채운다.
    소제목이 없으면(코드 대체 글) 코드가 짓는다. 언론 키워드도 여기서 코드가 센다."""
    seen = [f["id"] for f in fs if f["id"][0] in "FD"] or [fs[0]["id"]]
    for key, what, title in (("good", "좋게 볼", "재무·공시에서 좋게 본 점"), ("concern", "걱정되는", "재무·공시에서 걱정되는 점")):
        if not note.get(key):
            note[key] = [{"text": f"재무와 공시에서 {what} 쪽으로 분류된 건 없었어요.", "refs": seen}]
            note[f"{key}_title"] = "분류된 것 없음"
        note.setdefault(f"{key}_title", title)
    note["tone_rule"] = TONE_RULE
    note["keywords"] = keywords(fs, name)
    return note


def write(name: str, fs: list[dict], today: date) -> tuple[dict, str]:
    """(노트, writer) — writer 는 'llm:<모델>' 또는 'code'."""
    label = {1: "좋게 본 것", -1: "걱정되는 것", 0: "중립"}
    payload = {"today": today.isoformat(), "name": name,
               "facts": [{"id": f["id"], "text": f["text"], "tone": label[f["tone"]],
                          "slots": [f"{{{f['id']}.{k}}}" for k in f["slots"]]} for f in fs]}  # fmt: skip
    got = llm.ask("writer", "note", payload, lambda j: fill_note(j, fs), schema(fs))
    note, writer = (got, f"llm:{llm.MODELS['writer']}") if got else (code_note(fs), "code")
    return finish(note, fs, name), writer


# --- ⑥ 저장 ---


def week_of(today: date) -> str:
    """그 주 월요일 — 노트·설문의 주 단위."""
    return (today - timedelta(days=today.weekday())).isoformat()


def main(tickers: list[str], today: date) -> None:
    con = db.connect()
    ruled, ai = read_disclosures(con)
    print(f"공시 읽기 — 규칙 {ruled}건 · AI {ai}건")
    rows = con.execute("select ticker, name from stocks where active = 1").fetchall()
    rows = [r for r in rows if not tickers or r[0] in tickers]
    week = week_of(today)
    by = {"code": 0}
    for t, name in rows:
        fs = facts(con, t, today)
        if not fs:
            continue
        note, writer = write(name, fs, today)
        note["links"] = {f["id"]: f["url"] for f in fs}
        con.execute("insert or replace into notes values (?, ?, ?, ?, ?, ?)",
                    (t, week, json.dumps(fs, ensure_ascii=False), json.dumps(note, ensure_ascii=False),
                     writer, datetime.now().isoformat()))  # fmt: skip
        con.commit()
        by[writer] = by.get(writer, 0) + 1
    print(f"노트 {sum(by.values())}장 {by} · AI {llm.spent['calls']}콜 ${llm.spent['usd']:.3f}")


if __name__ == "__main__":
    main(sys.argv[1:], date.today())
