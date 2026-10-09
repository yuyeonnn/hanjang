"""피드의 「최근 소식」 — 사건(공시·5% 대량보유 보고) 하나마다 기사 한 편(제목 + 문단, 본문 1,200~1,700자). `python -m hanjang.articles`
재료: 공시 원문(DART) · 회사 소개(사업보고서) · 재무 · 같은 무렵 소식(RSS 제목·요약문) · 앞으로의 일정.
숫자는 재료에 적힌 것만 그대로 옮길 수 있다(코드가 토큰으로 대조) · 금지어 · 예측 · 짐작이면 글째 버린다(그 사건은 기사 없이 넘어간다).
매일 실행(daily)이 노트 다음에 부른다. 같은 사건은 다시 쓰지 않는다."""

import json
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta

from hanjang import db, llm, notes, sources

DAYS = 14  # 이 기간의 사건만
BUYSELL = re.compile(r"샀|팔았|사들|팔아|담았|매입|처분")
GUESS = re.compile(r"려는 (걸|것)|(걸|것)으로 볼 수|걸로 볼 수|걸 수도|셈일 수|의도|긍정적|부정적|호재|악재|영향을 (줄|미칠) 수|바빠지|바빠진|기대돼|기대가")  # 회사의 속뜻을 짐작하는 말
MAX_PER_RUN = 30  # 한 번에 쓰는 기사 수 상한 (비용) — 담은 종목의 사건부터
MIN_CHARS = 900  # 본문이 이보다 짧으면 다시 쓰게 한다 (뉴닉 분량 — 사용자 10/8)


def events(con: sqlite3.Connection, today: date) -> list[dict]:
    """아직 기사가 없는 최근 사건 — 담은 종목 먼저, 최신 먼저. 사실 하나(E1)로 만든다."""
    since = (today - timedelta(days=DAYS)).isoformat()
    held = {t for (t,) in con.execute("select distinct ticker from holdings")}
    out = []
    for rno, t, d, raw, code, dr in con.execute(
            "select rcept_no, ticker, date, title, code, direction from disclosures where date >= ? and importance >= 2"
            " and code is not null and code != 'OTHER' and rcept_no not in (select ref from articles)"
            " and ticker in (select ticker from stocks where market = 'KR')", (since,)):  # 미국 기사는 아직 (원문이 영어) # fmt: skip
        day = date.fromisoformat(d)
        dd = f"{day.month}월 {day.day}일"
        title = re.sub(r"\s+", " ", re.sub(r"^\[[^\]]*\]\s*", "", raw)).strip()  # 「[기재정정]」 같은 머리표는 뺀다
        what = f" — 무슨 일: {notes.plain(title)}" if notes.plain(title) else ""
        out.append({"ref": rno, "ticker": t, "date": d, "kind": code, "fact": {
            "id": "E1", "text": f"{dd} {notes.EVENT_KO[code]} 공시 「{title}」{what}", "url": notes.DART.format(rno), "tone": dr or 0,
            "slots": {"날짜": dd, "종류": notes.EVENT_KO[code], "제목": f"「{title}」"}}})  # fmt: skip
    for rno, t, d, who, chg, rate in con.execute(
            "select rcept_no, ticker, date, who, change, rate from insiders where kind = '5%' and date >= ?"
            " and rcept_no not in (select ref from articles)", (since,)):  # fmt: skip
        day = date.fromisoformat(d)
        dd = f"{day.month}월 {day.day}일"
        way = f", 직전 보고보다 보유 주식 {abs(chg):,}주 {'늘림' if chg > 0 else '줄임'}" if chg else ""
        slots = {"날짜": dd, "누가": who} | ({"비율": f"{rate:.2f}%"} if rate is not None else {}) | (
            {"주식": f"{abs(chg):,}주", "방향": "늘렸" if chg > 0 else "줄였"} if chg else {})
        out.append({"ref": rno, "ticker": t, "date": d, "kind": "HOLDER_CHANGE", "fact": {
            "id": "E1", "text": f"{dd} {who}의 5% 이상 대량보유 보고" + (f" — 보유 비율 {rate:.2f}%" if rate is not None else "") + way,
            "url": notes.DART.format(rno), "tone": 0, "slots": slots}})  # fmt: skip
    out.sort(key=lambda x: x["date"], reverse=True)  # 최신 먼저
    # 한 회사의 같은 종류 사건은 기사 한 편 — 이미 이 기간에 쓴 종류도 건너뛴다 (제목이 겹치는 기사 줄줄이 방지)
    done = set(con.execute("select ticker, kind from articles where date >= ?", (since,)).fetchall())
    seen, keep = set(), []
    for x in out:
        if (x["ticker"], x["kind"]) not in done | seen:
            seen.add((x["ticker"], x["kind"]))
            keep.append(x)
    out = keep
    return sorted(out, key=lambda x: x["ticker"] not in held)  # 그중 담은 종목 먼저 (정렬은 안정적)


def clean_doc(raw: str, n: int = 3000) -> str:
    """공시 원문 글 → 앞의 서식(CSS)과 뒤의 「관련공시」를 떼고 한 줄로. 큰 금액은 「큰 숫자 읽기」로 덧붙인다 —
    AI 가 「약 1,645억」처럼 쓰고 싶을 때 계산하지 않고 이 모양을 그대로 옮기게(숫자 대조에 들어간다)."""
    body = re.sub(r"^.*\}\s*", "", raw, flags=re.S).split("※ 관련공시")[0]
    body = re.sub(r"\s*\n\s*", " | ", body).strip(" |")[:n]
    big = dict.fromkeys(m for m in re.findall(r"\d{1,3}(?:,\d{3})+", body) if int(m.replace(",", "")) >= 10_000)

    def read(m):  # 1억 넘으면 금액 모양(「1,645억」)과 정확한 값, 그 아래는 「96만 8,091」
        n = int(m.replace(",", ""))
        return f"{notes.won(n).removesuffix('원')}(정확히 {notes.korean_num(n)})" if n >= 10**8 else notes.korean_num(n)

    return body + (" || 큰 숫자 읽기: " + " · ".join(f"{m} → {read(m)}" for m in big) if big else "")


def materials(con: sqlite3.Connection, ev: dict, today: date, doc: str) -> list[dict]:
    """기사 재료 — E1(사건 + 원문) · B1(회사 소개) · F(재무) · N(소식) · S(앞으로의 일정). AI 에겐 id·text(·doc) 만 준다."""
    fs = [ev["fact"] | ({"doc": doc} if doc else {})]
    biz = con.execute("select body, rcept_no from business where ticker = ?", (ev["ticker"],)).fetchone()
    if biz:
        b = json.loads(biz[0])
        segs = " · ".join(f"{x['name']} {x['share']}" for x in b.get("segments", []))
        fs.append({"id": "B1", "text": " ".join(b.get("what", [])) + (f" 부문별 매출 비중({b.get('year')}년): {segs}" if segs else ""),
                   "url": notes.DART.format(biz[1])})  # fmt: skip
    fs += [f for f in notes.facts(con, ev["ticker"], today) if f["id"][0] in "FN"]
    for k, (d, what, rno) in enumerate(con.execute(
            "select date, title, rcept_no from events where ticker = ? and date between ? and ? order by date limit 4",
            (ev["ticker"], today.isoformat(), (today + timedelta(days=90)).isoformat())), 1):  # fmt: skip
        day = date.fromisoformat(d)
        fs.append({"id": f"S{k}", "text": f"{day.month}월 {day.day}일 {what}", "url": notes.DART.format(rno) if rno else ""})
    return fs


def items(j: dict) -> list[dict]:
    return j["paragraphs"]


def check(j: dict, fs: list[dict]) -> dict:
    by = {f["id"]: f for f in fs}
    holder = "대량보유" in fs[0]["text"]  # 지분 보고는 「늘렸·줄였」로만 — 사고판 것인지는 보고서만으로 모른다
    title = j["title"].strip()
    e1 = notes.numbers(fs[0]["text"] + " " + fs[0].get("doc", ""))  # 제목 숫자도 사건 원문에 있는 것만
    if not title or len(title) > 40 or notes.numbers(title) - e1 or notes.FORBIDDEN.search(title) or notes.PREDICT.search(title) or GUESS.search(title):
        raise ValueError(f"제목: {title!r}")
    if holder and BUYSELL.search(title):
        raise ValueError(f"지분 보고를 사고팜으로: {title!r}")
    if not 3 <= len(j["paragraphs"]) <= 10:
        raise ValueError("문단 수")
    n_titles = [t for f in fs if f["id"][0] == "N" and (t := re.search(r"「([^」]*)」", f["text"]))]
    years = set(re.findall(r"(?<!\d)(?:19|20)\d\d(?=년)", " ".join(f["text"] + " " + f.get("doc", "") for f in fs)))
    for x in items(j):
        text, refs = x["text"], x["refs"]
        if not refs or not set(refs) <= set(by):
            raise ValueError(f"근거 없는 문장: {text!r}")
        # 근거 재료의 숫자 + 사건 원문(E1)의 숫자(같은 금액을 언론은 「6천722억」, 원문은 「6,722억」으로 쓴다) + 연도
        src = set().union(*(notes.numbers(by[r]["text"] + " " + by[r].get("doc", "")) for r in refs)) | e1 | years
        if bad := notes.numbers(text) - src:
            raise ValueError(f"재료에 없는 숫자 {bad}: {text!r}")
        if notes.LONGNUM.search(text):
            raise ValueError(f"읽기 힘든 숫자: {text!r}")
        if notes.CALC.search(text):
            raise ValueError(f"AI 가 한 셈: {text!r}")
        if notes.FORBIDDEN.search(text) or GUESS.search(text) or (notes.PREDICT.search(text) and not all(r[0] == "N" for r in refs)):
            raise ValueError(f"금지어·예측·짐작: {text!r}")
        if holder and BUYSELL.search(text):
            raise ValueError("지분 보고를 사고팜으로")
        if any(f"「{t[1]}」" in text for t in n_titles):
            raise ValueError(f"소식 제목 인용: {text!r}")
    if (n := sum(len(x["text"]) for x in items(j))) < MIN_CHARS:
        raise ValueError(f"너무 짧음 {n}자")
    return {"title": title, "paragraphs": j["paragraphs"]}


def schema(fs: list[dict]) -> dict:
    para = {"type": "object", "additionalProperties": False, "required": ["text", "refs"],
            "properties": {"text": {"type": "string"}, "refs": {"type": "array", "items": {"type": "string", "enum": [f["id"] for f in fs]}}}}
    return {"type": "object", "additionalProperties": False, "required": ["title", "paragraphs"],
            "properties": {"title": {"type": "string"}, "paragraphs": {"type": "array", "items": para}}}  # fmt: skip


def write(con: sqlite3.Connection, ev: dict, today: date, dart: "sources.Dart | None" = None) -> dict | None:
    name = con.execute("select name from stocks where ticker = ?", (ev["ticker"],)).fetchone()[0]
    try:
        doc = clean_doc((dart or sources.Dart()).doc_text(ev["ref"]))
    except Exception:  # noqa: BLE001  원문을 못 받으면 요약 한 줄로만 (그래도 쓴다)
        doc = ""
    fs = materials(con, ev, today, doc)
    payload = {"today": today.isoformat(), "name": name,
               "facts": [{"id": f["id"], "text": f["text"]} | ({"doc": f["doc"]} if f.get("doc") else {}) for f in fs]}  # fmt: skip
    got = llm.ask("writer", "article", payload, lambda j: check(j, fs), schema(fs), prompt_file="article")
    return got and got | {"links": {f["id"]: f["url"] for f in fs if f.get("url")}}


def main(today: date, limit: int = MAX_PER_RUN) -> None:
    con = db.connect()
    made, dart = 0, sources.Dart()
    for ev in events(con, today)[:limit]:
        a = write(con, ev, today, dart)
        if a:
            con.execute("insert or ignore into articles (ref, ticker, date, kind, body, made_at) values (?, ?, ?, ?, ?, ?)",
                        (ev["ref"], ev["ticker"], ev["date"], ev["kind"], json.dumps(a, ensure_ascii=False), datetime.now().isoformat()))  # fmt: skip
            con.commit()
            made += 1
    print(f"기사 {made}편 · AI {llm.spent['calls']}콜 ${llm.spent['usd']:.3f}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(date.today())
