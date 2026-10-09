"""미국 유명 투자자 — SEC 13F(운용 자산 1억 달러가 넘는 투자자가 분기 끝 45일 안에 내는 미국 주식 보유 신고).
미국 정부 자료라 자유롭게 쓴다(docs/stage3-us.md 「약관 확인」). 매일 실행에서 투자자마다 공시 목록 한 번 —
새 13F 가 나온 투자자만 보유 표를 다시 받는다. 13F 에는 티커가 없어 CUSIP 으로 우리 종목과 맞춘다(cusip_us.txt).
정치인 주식 거래 신고(STOCK Act)는 미국 법이 상업적 사용을 막아 뺐다 — 전문가 확인 뒤에 (사용자 10/10)."""

import re
from datetime import date
from pathlib import Path
from xml.etree import ElementTree

from hanjang import db, us

# 키 → (사람 · 회사, CIK, 소개, 홈페이지 — 로고를 찾는 열쇠). 소개는 널리 알려진 사실만
GURUS = {
    "buffett": ("워런 버핏 · 버크셔 해서웨이", 1067983, "워런 버핏이 이끌어 온 회사예요. 좋은 회사를 오래 들고 가는 투자로 유명해요.", "berkshirehathaway.com"),
    "cathie": ("캐시 우드 · ARK 인베스트", 1697748, "캐시 우드가 이끄는 운용사예요. 인공지능·로봇·유전자 같은 새 기술 회사에 많이 투자해요.", "ark-funds.com"),
    "burry": ("마이클 버리 · 사이언", 1649339, "영화 「빅쇼트」의 실제 주인공 마이클 버리의 회사예요.", None),
    "ackman": ("빌 애크먼 · 퍼싱 스퀘어", 1336528, "빌 애크먼이 이끄는 운용사예요. 적은 수의 회사에 크게 투자해요.", "pershingsquare.com"),
    "dalio": ("레이 달리오 · 브리지워터", 1350694, "레이 달리오가 세운 회사로, 세계에서 가장 큰 헤지펀드 가운데 하나예요.", "bridgewater.com"),
    "druckenmiller": ("스탠리 드러켄밀러 · 듀케인", 1536411, "스탠리 드러켄밀러가 자기 돈을 굴리는 회사예요.", None),
    "tepper": ("데이비드 테퍼 · 아팔루사", 1656456, "데이비드 테퍼가 이끄는 운용사예요.", None),
    "lilu": ("리 루 · 히말라야 캐피털", 1709323, "리 루가 이끄는 운용사예요. 찰리 멍거가 높이 평가한 투자자로 알려져 있어요.", None),
    "soros": ("조지 소로스 · 소로스 펀드", 1029160, "조지 소로스가 세운 운용사예요.", None),
}  # fmt: skip
CUSIPS = Path(__file__).parent / "cusip_us.txt"


def cusip_map() -> dict[str, str]:
    """CUSIP → 우리 티커. 한 회사의 여러 주식(알파벳 A·C, 버크셔 A·B)은 같은 티커로."""
    out = {}
    for ln in CUSIPS.read_text(encoding="utf-8").splitlines():
        if ln.strip() and not ln.startswith("#"):
            t, *cs = ln.split()
            out.update({c: t for c in cs})
    return out


def parse(xml: str) -> list[tuple[str, str, int, int]]:
    """13F 정보표 → [(CUSIP, 회사 이름, 금액 달러, 주식 수)]. 같은 CUSIP 은 더한다(운용 담당이 나뉘어 여러 줄).
    풋·콜(옵션)과 채권(PRN)은 뺀다 — 주식을 가진 것이 아니다."""
    xml = re.sub(r'\sxmlns(:\w+)?="[^"]+"', "", xml)
    xml = re.sub(r'\s\w+:\w+="[^"]*"', "", re.sub(r"<(/?)\w+:", r"<\1", xml))  # 이름공간 머리말(ns1:)과 xsi:schemaLocation 같은 속성
    got: dict[str, list] = {}
    for it in ElementTree.fromstring(xml).iter("infoTable"):
        if it.findtext("putCall") or it.findtext("shrsOrPrnAmt/sshPrnamtType") != "SH":
            continue
        c = it.findtext("cusip").strip().upper()
        row = got.setdefault(c, [it.findtext("nameOfIssuer").strip(), 0, 0])
        row[1] += int(float(it.findtext("value") or 0))
        row[2] += int(float(it.findtext("shrsOrPrnAmt/sshPrnamt") or 0))
    # 2023년부터 금액은 달러지만 옛 습관대로 천 달러로 내는 곳이 있다(듀케인) — 1주 값이 대부분 1달러 아래면 천 달러로 본다
    # ponytail: 한 주 값 가운뎃값으로 가른다 — 동전주만 든 투자자가 생기면 신고서 표지(primary_doc)를 보도록
    prices = sorted(v / s for _, v, s in got.values() if s)
    k = 1000 if prices and prices[len(prices) // 2] < 1 else 1
    return [(c, n, v * k, s) for c, (n, v, s) in got.items()]


def latest(sec: us.Edgar, cik: int) -> tuple[str, str, str] | None:
    """가장 최근 13F-HR (접수 번호, 기준일, 신고일). 고친 신고(13F-HR/A)는 보지 않는다."""
    r = sec.submissions(cik)["filings"]["recent"]
    i = next((k for k, f in enumerate(r["form"]) if f == "13F-HR"), None)
    return (r["accessionNumber"][i], r["reportDate"][i], r["filingDate"][i]) if i is not None else None


def table(sec: us.Edgar, cik: int, accn: str) -> str:
    folder = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn.replace('-', '')}"
    names = [x["name"] for x in sec._get(f"{folder}/index.json").json()["directory"]["item"]]
    xml = next(n for n in names if n.endswith(".xml") and n != "primary_doc.xml")
    return sec._get(f"{folder}/{xml}").text


def main(today: date | None = None, con=None, sec=None) -> None:
    con, sec, n = con or db.connect(), sec or us.Edgar(), 0
    tickers = cusip_map()
    for key, (_, cik, _, _) in GURUS.items():
        got = latest(sec, cik)
        if not got or con.execute("select 1 from guru_holdings where guru = ? and accn = ?", (key, got[0])).fetchone():
            continue  # 새 신고가 없으면 그대로
        merged: dict[str, list] = {}  # 우리 종목은 티커로 합친다 — 알파벳 A·C 가 두 줄로 나오지 않게
        for c, name, v, s in parse(table(sec, cik, got[0])):
            row = merged.setdefault(tickers.get(c, c), [c, name, 0, 0])
            row[2] += v
            row[3] += s
        total = sum(v for _, _, v, _ in merged.values()) or 1
        con.execute("delete from guru_holdings where guru = ?", (key,))
        con.executemany("insert into guru_holdings values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [(key, c, name, tickers.get(c), v, s, v / total * 100, *got) for c, name, v, s in merged.values()])  # fmt: skip
        con.commit()
        n += 1
    print(f"유명 투자자 13F — 새 신고 {n}곳 · SEC {sec.calls}콜")


if __name__ == "__main__":
    main()
