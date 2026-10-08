"""큰손 포트폴리오 — 전체 상장사(코스피·코스닥)의 5% 대량보유 보고에서 기관별로 「5% 넘게 가진 종목」을 모은다.
한국엔 미국 13F 같은 보유 전체 공시가 없어서, 5% 넘는 것만 보인다. 개인(오너 등)은 모으지 않는다 — 기관만.
`python -m hanjang.holders` (처음엔 3년치, 그다음 매일 실행이 최근 일주일만 더한다)."""

import re
import sqlite3
import sys
from datetime import date, timedelta

from hanjang import db, sources

# 보여줄 기관 — 보고자 이름(DART flr_nm·repror)을 띄어쓰기·대소문자 없이 비교할 열쇠말, 한 줄 소개
BIG = {
    "nps": ("국민연금", ("국민연금공단",), "우리나라 국민의 노후 자금을 굴리는 곳이에요. 국내 주식을 가장 많이 가진 기관이에요."),
    "blackrock": ("블랙록", ("blackrock",), "세계에서 가장 큰 자산운용사예요. 지수를 따라가는 펀드(ETF)를 많이 운용해요."),
    "capital": ("캐피털그룹", ("capitalresearch", "capitalgroup"), "미국의 오래된 자산운용사예요. 오래 들고 가는 투자로 알려져 있어요."),
    "samsungam": ("삼성자산운용", ("삼성자산운용",), "삼성 계열 자산운용사예요. 국내 ETF를 많이 운용해요."),
    "miraeam": ("미래에셋자산운용", ("미래에셋자산운용",), "국내 대형 자산운용사예요. ETF와 해외 투자를 많이 해요."),
    "shinhanam": ("신한자산운용", ("신한자산운용",), "신한금융 계열 자산운용사예요."),
    "kbam": ("KB자산운용", ("kb자산운용",), "KB금융 계열 자산운용사예요."),
    "kitm": ("한국투자신탁운용", ("한국투자신탁운용",), "한국투자금융 계열 자산운용사예요."),
    "align": ("얼라인파트너스", ("얼라인파트너스",), "주주의 목소리를 내는 「행동주의」 펀드예요. 회사에 주주환원을 요구하기도 해요."),
    "silchester": ("실체스터", ("silchester",), "영국의 해외 주식 투자사예요. 저평가된 회사에 오래 투자하는 편이에요."),
    "pzena": ("피즈나", ("pzena",), "미국의 가치투자 운용사예요."),
}  # fmt: skip


def who(name: str) -> str | None:
    """보고자 이름 → BIG 의 열쇠. 없으면 None."""
    k = re.sub(r"[\s,.()㈜]", "", name or "").lower()
    return next((key for key, (_, alias, _) in BIG.items() if any(a in k for a in alias)), None)


def scan(con: sqlite3.Connection, start: date, end: date, dart: sources.Dart) -> set[str]:
    """기간 안의 대량보유 보고(D001) 목록에서 BIG 기관 것만 모아 둔다 — 회사·기관 짝을 찾는 용도(지분율은 refresh 에서)."""
    touched, lo = set(), start
    while lo <= end:
        hi = min(end, lo + timedelta(days=89))  # 회사를 안 정하면 석 달씩만
        page = 1
        while True:
            j = dart._list("list.json", bgn_de=lo.strftime("%Y%m%d"), end_de=hi.strftime("%Y%m%d"),
                           pblntf_detail_ty="D001", page_no=page, page_count=100)  # fmt: skip
            for r in j["list"]:
                key = who(r.get("flr_nm", ""))
                if key and r.get("stock_code") and r.get("corp_cls") in ("Y", "K"):
                    con.execute("insert or ignore into big_pairs values (?, ?, ?, ?, ?)",
                                (key, r["corp_code"], r["stock_code"], r["corp_name"], r["corp_cls"]))  # fmt: skip
                    touched.add(r["corp_code"])
            if page >= int(j.get("total_page") or 0):
                break
            page += 1
        con.commit()
        lo = hi + timedelta(days=1)
    return touched


def refresh(con: sqlite3.Connection, dart: sources.Dart, corps: list[str] | None = None) -> int:
    """회사마다 대량보유 이력(majorstock)을 받아, BIG 기관의 가장 최근 보고로 지분율·증감을 적는다. 5% 아래로 내려가면 지운다."""
    rows = con.execute("select distinct corp_code, stock_code, corp_name, corp_cls from big_pairs").fetchall()
    n = 0
    for cc, code, name, cls in rows:
        if corps and cc not in corps:
            continue
        latest = {}
        for r in dart._list("majorstock.json", corp_code=cc)["list"]:
            key = who(r.get("repror", ""))
            if key and (key not in latest or r["rcept_no"] > latest[key]["rcept_no"]):
                latest[key] = r
        for key, r in latest.items():
            rate = sources._num(r.get("stkrt"))
            if rate is None or rate < 5:
                con.execute("delete from big_holdings where inst = ? and stock_code = ?", (key, code))
                continue
            con.execute("insert or replace into big_holdings (inst, stock_code, corp_name, corp_cls, rate, rate_chg, date, rcept_no)"
                        " values (?, ?, ?, ?, ?, ?, ?, ?)",
                        (key, code, name, cls, rate, sources._num(r.get("stkrt_irds")), r["rcept_dt"], r["rcept_no"]))  # fmt: skip
            n += 1
        con.commit()
    # 업종 코드 — 도넛(업종별로 몇 곳)용. 회사마다 한 번만
    for (code,) in con.execute("select distinct stock_code from big_holdings where induty_code is null").fetchall():
        con.execute("update big_holdings set induty_code = ? where stock_code = ?", (dart.company(code)[0] or "", code))
    con.commit()
    return n


def main(today: date, backfill: bool = False) -> None:
    con, dart = db.connect(), sources.Dart()
    start = today - timedelta(days=3 * 365 if backfill else 7)
    touched = scan(con, start, today, dart)
    # 처음엔 전부, 그다음엔 새 보고가 나온 회사만 다시 본다
    n = refresh(con, dart, None if backfill else list(touched)) if backfill or touched else 0
    print(f"큰손 보고가 나온 회사 {len(touched)}곳 · 보유 {n}건 · DART {dart.calls}콜")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(date.today(), backfill="--backfill" in sys.argv)
