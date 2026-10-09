"""국민연금 주식 포트폴리오 — 한국과 미국을 하나로(사용자 10/10: 구분 없이 많이 가진 순, 파이도 비중으로).
한국은 국민연금이 낸 연간 공시(공공데이터포털 「국민연금공단_국내주식 투자정보」 — 이용허락범위 제한 없음, 연말 기준 종목별 평가액),
미국은 같은 날의 SEC 13F. 달러는 그날 한국은행 환율(731Y003)로 원화. 시세를 우리가 곱하지 않는다 — 금액은 국민연금·SEC 가 낸 숫자 그대로.
다른 기관은 한국 보유 금액을 공개하지 않아(5% 보고는 지분율만) 합칠 수 없다 — KRX 시세 계약 뒤에 (docs/data-rights.md)."""

import re
from datetime import date, timedelta

import httpx

from hanjang import db, gurus, sources, us

PAGE = "https://www.data.go.kr/data/3070507/fileData.do"  # 국민연금공단_국내주식 투자정보 — 해마다 같은 자리에 새 파일
CIK = 1608046  # National Pension Service (13F)
UA = {"User-Agent": "Mozilla/5.0 (Hanjang)"}


def latest_file() -> tuple[date, str]:
    """(기준일, 내려받을 주소) — 데이터셋 페이지의 파일 이름 「…_20251231」과 내려받기 링크."""
    html = httpx.get(PAGE, headers=UA, timeout=60, follow_redirects=True).text
    day = re.search(r"국민연금공단_국내주식 투자정보_(\d{8})", html)
    link = re.search(r"fileDownload\.do\?atchFileId=(FILE_\d+)&(?:amp;)?fileDetailSn=(\d+)", html)
    if not (day and link):
        raise RuntimeError("국민연금 국내주식 파일을 찾지 못함 — 공공데이터포털 페이지 모양이 바뀌었나")
    d = day.group(1)
    return date(int(d[:4]), int(d[4:6]), int(d[6:])), f"https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId={link.group(1)}&fileDetailSn={link.group(2)}"


def parse_kr(raw: bytes) -> list[tuple[str, float, float]]:
    """CSV(번호,종목명,평가액(억 원),자산군 내 비중,지분율) → [(종목명, 평가액 원, 지분율 %)]. 0억 원(사실상 다 판 것)은 뺀다."""
    out = []
    for ln in raw.decode("cp949").splitlines()[1:]:
        parts = ln.split(",")
        if len(parts) >= 5 and parts[2].strip() and float(parts[2]) > 0:
            out.append((parts[1].strip(), float(parts[2]) * 1e8, float(parts[4] or 0)))
    return out


def filing_at(sec, period: date) -> str | None:
    """그 분기 말 기준 13F-HR 접수 번호 — 한국 공시와 같은 날로 맞춘다."""
    r = sec.submissions(CIK)["filings"]["recent"]
    return next((a for f, a, d in zip(r["form"], r["accessionNumber"], r["reportDate"]) if f == "13F-HR" and d == period.isoformat()), None)


def main(today: date | None = None, con=None, sec=None) -> None:
    con, sec = con or db.connect(), sec or us.Edgar()
    asof, url = latest_file()
    if con.execute("select 1 from nps_port where asof = ?", (asof.isoformat(),)).fetchone():
        return  # 새 연간 공시가 없으면 그대로
    accn = filing_at(sec, asof)
    if not accn:
        print(f"국민연금 — {asof} 13F 가 아직 없음")
        return
    fx = sources.ecos("ECOS:731Y003:0000003", asof - timedelta(days=10), asof)[-1][1]  # 그날(휴일이면 그 앞) 원/달러
    kr = parse_kr(httpx.get(url, headers={**UA, "Referer": PAGE}, timeout=60, follow_redirects=True).content)
    names = dict(con.execute("select name, ticker from stocks where market is not 'US'").fetchall())
    tickers, merged = gurus.cusip_map(), {}
    for c, issuer, v, _ in gurus.parse(gurus.table(sec, CIK, accn)):
        row = merged.setdefault(tickers.get(c, c), [issuer, tickers.get(c), 0])
        row[2] += v
    rows = [(asof.isoformat(), "KR", n, names.get(n), won, stake) for n, won, stake in kr]
    rows += [(asof.isoformat(), "US", issuer, t, v * fx, None) for issuer, t, v in merged.values()]
    con.execute("delete from nps_port")
    con.executemany("insert into nps_port values (?, ?, ?, ?, ?, ?)", rows)
    con.execute("insert or replace into nps_meta values (?, ?, ?)", (asof.isoformat(), fx, accn))
    con.commit()
    print(f"국민연금 한국 {len(kr)}종목 + 미국 {len(merged)}종목 ({asof}, 1달러 {fx:,.1f}원)")


if __name__ == "__main__":
    main()
