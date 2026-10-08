"""피드의 「최근 소식」 — 사건(공시·5% 대량보유 보고) 하나마다 뉴닉식 짧은 기사 한 편. `python -m hanjang.articles`
노트와 같은 규칙: 숫자는 빈칸으로(코드가 채운다) · 사실에 없는 숫자 · 금지어 · 예측 말투면 글째 버린다(그 사건은 기사 없이 넘어간다).
매일 실행(daily)이 노트 다음에 부른다. 같은 사건은 다시 쓰지 않는다."""

import json
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta

from hanjang import db, llm, notes

DAYS = 14  # 이 기간의 사건만
BUYSELL = re.compile(r"샀|팔았|사들|팔아|담았|매입|처분")
GUESS = re.compile(r"려는 (걸|것)|(걸|것)으로 볼 수|걸로 볼 수|걸 수도|셈일 수|의도|긍정적|부정적|호재|악재|영향을 (줄|미칠) 수|바빠지|바빠진|기대돼|기대가")  # 회사의 속뜻을 짐작하는 말
MAX_PER_RUN = 30  # 한 번에 쓰는 기사 수 상한 (비용) — 담은 종목의 사건부터


def events(con: sqlite3.Connection, today: date) -> list[dict]:
    """아직 기사가 없는 최근 사건 — 담은 종목 먼저, 최신 먼저. 사실 하나(E1)로 만든다."""
    since = (today - timedelta(days=DAYS)).isoformat()
    held = {t for (t,) in con.execute("select distinct ticker from holdings")}
    out = []
    for rno, t, d, raw, code, dr in con.execute(
            "select rcept_no, ticker, date, title, code, direction from disclosures where date >= ? and importance >= 2"
            " and code is not null and code != 'OTHER' and rcept_no not in (select ref from articles)", (since,)):  # fmt: skip
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


def check(j: dict, fs: list[dict]) -> dict:
    by = {f["id"]: f for f in fs}
    holder = "대량보유" in fs[0]["text"]  # 지분 보고는 「늘렸·줄였」로만 — 사고판 것인지는 보고서만으로 모른다
    allowed = set().union(*(notes.numbers(f["text"]) for f in fs))
    title = j["title"].strip()
    if not title or len(title) > 40 or re.search(r"\d", title) or notes.FORBIDDEN.search(title) or notes.PREDICT.search(title) or GUESS.search(title):
        raise ValueError(f"제목: {title!r}")
    if holder and BUYSELL.search(title):
        raise ValueError(f"지분 보고를 사고팜으로: {title!r}")
    paras = [notes.fill(p, by) for p in j["paragraphs"]]
    if holder and any(BUYSELL.search(p["text"]) for p in paras):
        raise ValueError("지분 보고를 사고팜으로")
    if not 2 <= len(paras) <= 5:
        raise ValueError("문단 수")
    for p in paras:
        if not p["refs"] or not set(p["refs"]) <= set(by):
            raise ValueError(f"근거 없는 문단: {p['text']!r}")
        if bad := notes.numbers(p["text"]) - allowed:
            raise ValueError(f"사실에 없는 숫자 {bad}")
        if notes.FORBIDDEN.search(p["text"]) or notes.PREDICT.search(p["text"]) or GUESS.search(p["text"]):
            raise ValueError(f"금지어·예측·짐작: {p['text']!r}")
    return {"title": title, "paragraphs": paras}


def schema(fs: list[dict]) -> dict:
    para = {"type": "object", "additionalProperties": False, "required": ["text", "refs"],
            "properties": {"text": {"type": "string"}, "refs": {"type": "array", "items": {"type": "string", "enum": [f["id"] for f in fs]}}}}
    return {"type": "object", "additionalProperties": False, "required": ["title", "paragraphs"],
            "properties": {"title": {"type": "string"}, "paragraphs": {"type": "array", "items": para}}}  # fmt: skip


def write(con: sqlite3.Connection, ev: dict, today: date) -> dict | None:
    name = con.execute("select name from stocks where ticker = ?", (ev["ticker"],)).fetchone()[0]
    ctx = [f for f in notes.facts(con, ev["ticker"], today, news=False) if f["id"][0] == "F"]
    fs = [ev["fact"], *ctx]
    payload = {"today": today.isoformat(), "name": name,
               "facts": [{"id": f["id"], "text": f["text"], "slots": [f"{{{f['id']}.{k}}}" for k in f["slots"]]} for f in fs]}  # fmt: skip
    got = llm.ask("writer", "article", payload, lambda j: check(j, fs), schema(fs), prompt_file="article")
    return got and got | {"links": {f["id"]: f["url"] for f in fs}}


def main(today: date, limit: int = MAX_PER_RUN) -> None:
    con = db.connect()
    made = 0
    for ev in events(con, today)[:limit]:
        a = write(con, ev, today)
        if a:
            con.execute("insert or ignore into articles (ref, ticker, date, kind, body, made_at) values (?, ?, ?, ?, ?, ?)",
                        (ev["ref"], ev["ticker"], ev["date"], ev["kind"], json.dumps(a, ensure_ascii=False), datetime.now().isoformat()))  # fmt: skip
            con.commit()
            made += 1
    print(f"기사 {made}편 · AI {llm.spent['calls']}콜 ${llm.spent['usd']:.3f}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(date.today())
