"""주간 노트 만들기 ②~⑥ (PRD §5.2): 공시 읽기(AI) → 사실 묶음(코드) → 쓰기(AI) → 숫자 대조 검사 → 저장.
`python -m hanjang.notes [종목코드 …]` — 비우면 전 종목. 같은 주에 다시 돌리면 덮어쓴다.
숫자는 전부 여기 코드가 만든다. AI 는 사실 목록을 엮기만 하고, 사실에 없는 숫자를 쓰면 글째 버린다."""

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
# 제목이 코드 정의와 반대인 것 — 퀀트점프 RECODE 중 자주 걸리는 것만 복사
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
TONE_RULE = ("좋게 본 것·걱정되는 것은 코드가 정한 기준으로 나눴어요 — 매출·영업이익이 늘었나 줄었나, 영업 적자인가, "
             f"부채비율 {DEBT_GOOD}% 미만·{DEBT_BAD}% 초과, ROE {ROE_GOOD}% 이상·0% 미만, "
             "공시 종류(자사주 매입·대형 계약 / 증자·전환사채·소송·거래정지).")
# 예측 말투 — 지난 사실을 「~할 전망」으로 쓰면 틀린 말이고 예측이 된다 (불변식 1). 기사(N)만 근거인 문장은
# 「기사는 ~라고 써요」로 남의 전망을 옮기는 자리라 예외
PREDICT = re.compile(r"전망이|전망돼|것으로 보여|것으로 보입|것 같아|예상돼|예상됩|할 거예요|될 거예요|일 거예요|가능성이 (높|커|있)")
NEWS_DAYS = 7
EVENT_DAYS = 90


# --- ② 공시 읽기 (AI) ---


def recode(code: str, title: str) -> str:
    t = title.replace(" ", "")
    for codes, pat, new in RECODE:
        if (codes is None or code in codes) and re.search(pat, t):
            return new
    return code


def read_disclosures(con: sqlite3.Connection, batch: int = 100) -> int:
    """아직 안 읽은 공시 제목을 분류한다. 모델이 빠뜨린 건 비워 두고 다음 실행에서 다시 묻는다."""
    rows = con.execute("select rcept_no, title, date from disclosures where read_at is null").fetchall()
    done = 0
    for k in range(0, len(rows), batch):
        part = rows[k : k + batch]
        got = llm.ask("reader", "title", [{"i": i, "title": t, "date": d}
                                          for i, (_, t, d) in enumerate(part)], _check_titles(len(part)))  # fmt: skip
        for i, code, imp in got or []:
            rno, title, _ = part[i]
            code = recode(code, title)
            con.execute("update disclosures set code = ?, importance = ?, direction = ?,"
                        " read_model = ?, read_at = ? where rcept_no = ?",
                        (code, imp, DIRECTION.get(code, 0), llm.MODELS["reader"], datetime.now().isoformat(), rno))  # fmt: skip
            done += 1
        con.commit()
    return done


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


# --- ④ 사실 묶음 (코드) ---


def won(x: int) -> str:
    """원 → 「333.6조원」 「5,583억원」. 노트의 모든 금액은 이 한 함수로."""
    if abs(x) >= 10**12:
        return f"{x / 10**12:,.1f}조원"
    if abs(x) >= 10**8:
        return f"{x / 10**8:,.0f}억원"
    return f"{x:,}원"


def pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def _up(cur: int | None, prev: int | None) -> int:
    """전년보다 늘었나(+1) 줄었나(−1). 전년이 0·음수면 비교하지 않는다(0)."""
    if cur is None or prev is None or prev <= 0 or cur == prev:
        return 0
    return 1 if cur > prev else -1


def _change(cur: int | None, prev: int | None) -> str:
    """전년 대비 — 전년이 0·음수면 비율이 뜻이 없다 → 금액만."""
    if cur is None:
        return ""
    if prev is None:
        return won(cur)
    if prev <= 0:
        return f"{won(cur)}(전년 {won(prev)})"
    return f"{won(cur)}(전년보다 {pct((cur - prev) / prev)})"


def facts(con: sqlite3.Connection, ticker: str, today: date) -> list[dict]:
    """종목 하나의 사실 목록 — [{id, text, url, tone}]. 문장도 숫자도, 좋은지 걱정인지(tone)도 코드가 만든다."""
    out = []
    fin = con.execute("select fiscal_year, revenue, operating_income, net_income, equity, liabilities,"
                      " rcept_no from financials where ticker = ? order by fiscal_year desc limit 2",
                      (ticker,)).fetchall()  # fmt: skip
    if fin:
        y, rev, oi, ni, eq, li, rno = fin[0]
        p = fin[1] if len(fin) > 1 else (None,) * 7
        url = DART.format(rno)
        if rev is not None:
            out.append({"id": "F1", "text": f"{y}년 매출 {_change(rev, p[1])}", "url": url,
                        "tone": _up(rev, p[1])})  # fmt: skip
        if oi is not None:
            out.append({"id": "F2", "text": f"{y}년 영업이익 {_change(oi, p[2])}" + (" — 영업 적자" if oi < 0 else ""),
                        "url": url, "tone": -1 if oi < 0 else _up(oi, p[2])})  # fmt: skip
        # 은행·보험은 예금·보험금이 빚으로 잡혀 부채비율이 수백~천 % — 초보자에게 오해만 준다.
        # 금융회사는 DART 에 「매출액」이 없다 → 그걸로 가린다
        if li is not None and eq and eq > 0 and rev is not None:
            r = li / eq * 100
            out.append({"id": "F3", "text": f"{y}년 말 부채비율 {r:.1f}% (빚 {won(li)} · 자기 돈 {won(eq)})",
                        "url": url, "tone": 1 if r < DEBT_GOOD else -1 if r > DEBT_BAD else 0})  # fmt: skip
        if ni is not None and eq and eq > 0:
            r = ni / eq * 100
            out.append({"id": "F4", "text": f"{y}년 ROE {r:.1f}% (순이익 {won(ni)} · 자기 돈 {won(eq)})",
                        "url": url, "tone": 1 if r >= ROE_GOOD else -1 if r < 0 else 0})  # fmt: skip
    evs = con.execute("select rcept_no, date, title, code, direction from disclosures"
                      " where ticker = ? and date >= ? and importance >= 2 and code != 'OTHER'"
                      " order by importance desc, date desc limit 5",
                      (ticker, (today - timedelta(days=EVENT_DAYS)).isoformat())).fetchall()  # fmt: skip
    for k, (rno, d, title, code, dr) in enumerate(sorted(evs, key=lambda r: r[1], reverse=True), 1):
        d = date.fromisoformat(d)
        tone = {1: " — 주주에게 반가운 쪽으로 분류", -1: " — 주주에게 걸리는 쪽으로 분류"}.get(dr, "")
        out.append({"id": f"D{k}", "text": f"{d.month}월 {d.day}일 {EVENT_KO[code]} 공시"
                    f" 「{title}」{tone}", "url": DART.format(rno), "tone": dr or 0})  # fmt: skip
    news = con.execute("select url, date, press, title from news where ticker = ? and date >= ?"
                       " order by date desc limit 5",
                       (ticker, (today - timedelta(days=NEWS_DAYS)).isoformat())).fetchall()  # fmt: skip
    # 목표주가·매수 같은 말이 든 기사는 싣지 않는다 — 옮기기만 해도 권유가 된다 (불변식 1)
    news = [n for n in news if not FORBIDDEN.search(n[3])]
    for k, (url, d, press, title) in enumerate(news, 1):
        d = date.fromisoformat(d)
        out.append({"id": f"N{k}", "text": f"{d.month}월 {d.day}일 {press or ''} 기사 제목 「{title}」",
                    "url": url, "tone": 0})  # fmt: skip
    return out


# --- ⑤ 쓰기 (AI) + 숫자 대조 검사 ---


def numbers(s: str) -> set[str]:
    """숫자 토큰 — 「333.6조원」 → '333.6', 「1,512건」 → '1512'. 부분 일치가 아니라 토큰으로 대조."""
    return {t.replace(",", "") for t in re.findall(r"\d[\d,]*(?:\.\d+)?", s)}


def check_note(note: dict, fs: list[dict]) -> dict:
    """글 전체 검사 — 하나라도 어기면 ValueError (글째 버린다).
    ① 문장마다 있는 사실 id ② 사실에 없는 숫자 금지 ③ 금지어 (사실 원문을 인용한 부분은 빼고 본다)
    ④ 좋게 본 것은 +1 사실만, 걱정되는 것은 −1 사실만 근거로 — 그런 사실이 있는데 비워 두면 탈락."""
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


def code_note(fs: list[dict]) -> dict:
    """AI 글이 검사에서 떨어졌을 때 — 사실 목록을 그대로 문장으로 (PRD §4.3)."""
    groups = (("회사 사정은 어떤가요?", "F"), ("요즘 무슨 일이 있었나요?", "D"), ("요즘 기사는요", "N"))
    secs = [{"title": t, "sentences": [{"text": f["text"] + ".", "refs": [f["id"]]}
                                       for f in fs if f["id"].startswith(p)]} for t, p in groups]  # fmt: skip
    side = {k: [{"text": f["text"] + ".", "refs": [f["id"]]} for f in fs if f["tone"] == sign]
            for k, sign in (("good", 1), ("concern", -1))}  # fmt: skip
    return {"headline": "이번 주 사실을 그대로 옮겼어요.", "summary": [],
            "sections": [s for s in secs if s["sentences"]], **side}


def finish(note: dict, fs: list[dict]) -> dict:
    """좋게 본 것·걱정되는 것은 **늘 두 칸 다** 보인다 — 해당 사실이 없으면 코드가 「없었어요」를 채운다."""
    seen = [f["id"] for f in fs if f["id"][0] in "FD"] or [fs[0]["id"]]
    for key, what in (("good", "좋게 볼"), ("concern", "걱정되는")):
        if not note.get(key):
            note[key] = [{"text": f"재무와 공시에서 {what} 쪽으로 분류된 건 없었어요.", "refs": seen}]
    note["tone_rule"] = TONE_RULE
    return note


def write(name: str, fs: list[dict], today: date) -> tuple[dict, str]:
    """(노트, writer) — writer 는 'llm:<모델>' 또는 'code'."""
    label = {1: "좋게 본 것", -1: "걱정되는 것", 0: "중립"}
    payload = {"today": today.isoformat(), "name": name, "facts": [{"id": f["id"], "text": f["text"], "tone": label[f["tone"]]} for f in fs]}
    got = llm.ask("writer", "note", payload, lambda j: check_note(j, fs))
    note, writer = (got, f"llm:{llm.MODELS['writer']}") if got else (code_note(fs), "code")
    return finish(note, fs), writer


# --- ⑥ 저장 ---


def week_of(today: date) -> str:
    """그 주 월요일 — 노트·설문의 주 단위."""
    return (today - timedelta(days=today.weekday())).isoformat()


def main(tickers: list[str], today: date) -> None:
    con = db.connect()
    print(f"공시 읽기 {read_disclosures(con)}건")
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
