"""외부 데이터 받기 — DART · ECOS · 공공데이터포털(유니버스용) · 구글 뉴스.
퀀트점프 `backend/quantjump/adapters.py` 에서 복사해 줄였다 (2026-10-07). 비중·예측·토스·야후는 가져오지 않았다.
사용권은 docs/data-rights.md — 시세는 **화면에 쓰지 않는다**(유니버스 고르기에만), 뉴스는 개발 중 개인용만."""

import html
import io
import re
import time
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree

import httpx

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"


def env() -> dict[str, str]:
    """`.env` 한 파일 — KEY=VALUE 줄만. 없으면 빈 것."""
    f = ROOT / ".env"
    if not f.exists():
        return {}
    pairs = (ln.split("=", 1) for ln in f.read_text(encoding="utf-8").splitlines() if "=" in ln)
    return {k.strip(): v.strip() for k, v in pairs}


def _ymd(s: str) -> date:
    """「20261008」 · 월별은 「202608」 → 그 달 1일."""
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]) if len(s) >= 8 else 1)


def _won(s: str | None) -> int | None:
    s = (s or "").replace(",", "").strip()
    return int(s) if re.fullmatch(r"-?\d+", s) else None


def _get(url: str, secret: str, **params) -> httpx.Response:
    """GET 3회 재시도. 키가 주소에 들어가니 예외 문자열에서 지운다 (퀀트점프 사고 #8)."""
    err = ""
    for attempt in range(3):
        try:
            r = httpx.get(url, params=params, timeout=60, follow_redirects=True)
            r.raise_for_status()
            return r
        except httpx.HTTPError as e:
            err = type(e).__name__
            time.sleep(2**attempt)
    raise RuntimeError(f"{url.replace(secret, '***')}: {err} (3 tries)")


# --- 유니버스: 코스피 시가총액 상위 (공공데이터포털 — 고르기에만 쓰고 저장·표시하지 않는다) ---


UNIVERSE = ROOT / "hanjang" / "universe.txt"
MACRO_EVENTS = ROOT / "hanjang" / "macro_events.txt"
MACRO_RANK = {"금리": 1, "물가": 2, "선거": 3, "고용": 4}  # 캘린더 목록 정렬 — 주식과 이어지는 정도
MACRO_EXPLAIN = {  # 한 줄로, 숫자 없이 (사용자 10/9: 길다)
    ("금리", "KR"): "한국은행이 기준금리를 정하는 날이에요.",
    ("금리", "US"): "미국 중앙은행이 기준금리를 정하는 날이에요.",
    ("물가", "KR"): "지난달 물가가 얼마나 올랐는지 나오는 날이에요.",
    ("물가", "US"): "미국의 지난달 물가가 나오는 날이에요.",
    ("고용", "KR"): "지난달 일자리가 얼마나 늘었는지 나오는 날이에요.",
    ("고용", "US"): "미국의 지난달 일자리 수가 나오는 날이에요.",
    ("선거", "US"): "미국 의회 의원을 뽑는 중간선거예요.",
}  # fmt: skip
MACRO_SOURCE = {"KR금리": ("한국은행", "https://www.bok.or.kr"), "US금리": ("미 연준", "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"),
                "KR물가": ("국가데이터처", "https://mods.go.kr"), "KR고용": ("국가데이터처", "https://mods.go.kr"),
                "US물가": ("미 노동통계국", "https://www.bls.gov/schedule/news_release/cpi.htm"),
                "US고용": ("미 노동통계국", "https://www.bls.gov/schedule/news_release/empsit.htm"), "US선거": ("미 연방선거위원회", "https://www.fec.gov")}  # fmt: skip


def macro_events(lo: str, hi: str) -> list[tuple[str, str, str, str]]:
    """시장 일정 [(날짜, 종류, 나라, 이름)] — macro_events.txt (손으로 갱신). lo~hi 안의 것만, 날짜순."""
    rows = (tuple(x.strip() for x in ln.split("|")) for ln in MACRO_EVENTS.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#"))
    return sorted(r for r in rows if len(r) == 4 and lo <= r[0] <= hi)


def kospi_universe() -> list[tuple[str, str]]:
    """종목 목록 [(종목코드, 이름)] — universe.txt (손으로 갱신). 시세 API 를 부르지 않는다 (data-rights §4)."""
    rows = (ln.split(maxsplit=1) for ln in UNIVERSE.read_text(encoding="utf-8").splitlines() if ln and not ln.startswith("#"))
    return [(t, n.strip()) for t, n in rows]


def price_dev() -> bool:
    """`.env` 에 PRICE_DEV=1 일 때만 주가를 받고 화면에 그린다 — 내 컴퓨터에서 나 혼자 볼 때.
    시세는 「상업 금지 · 제3자 제공 금지」(data-rights §4). 서버(.env 에 없음)는 늘 꺼진다."""
    return env().get("PRICE_DEV") == "1"


def prices(ticker: str, since: date) -> list[tuple[date, int]]:
    """공공데이터포털 주식시세 — 그 종목의 일별 종가 [(날짜, 종가)], 오래된 것부터. ⚠️ 개발 중 개인용만."""
    e = env()
    key, base = e["DATA_GO_KR_SERVICE_KEY"], e["DATA_GO_KR_BASE_URL"]
    body = _get(f"{base}/GetStockSecuritiesInfoService/getStockPriceInfo", key, serviceKey=key, resultType="json",
                numOfRows=1000, likeSrtnCd=ticker, beginBasDt=since.strftime("%Y%m%d")).json()["response"]["body"]  # fmt: skip
    items = (body.get("items") or {}).get("item") or []
    items = items if isinstance(items, list) else [items]
    return sorted((_ymd(r["basDt"]), int(r["clpr"])) for r in items if r.get("srtnCd") == ticker and r.get("clpr"))


def holidays(year: int) -> list[tuple[date, str]]:
    """공휴일·대체공휴일 — 한국천문연구원 특일 정보 (이용허락범위 제한 없음). 1년 한 콜."""
    key = env()["DATA_GO_KR_SERVICE_KEY"]
    url = "https://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getRestDeInfo"
    body = _get(url, key, serviceKey=key, solYear=str(year), _type="json", numOfRows=100).json()
    return parse_holidays(body["response"]["body"])


def parse_holidays(body: dict) -> list[tuple[date, str]]:
    items = body["items"]["item"] if body.get("totalCount") else []
    items = items if isinstance(items, list) else [items]  # 1건이면 dict 로 온다
    return [(_ymd(str(i["locdate"])), i["dateName"]) for i in items if i.get("isHoliday") == "Y"]


# --- DART ---


@dataclass(frozen=True)
class Disclosure:
    rcept_no: str
    ticker: str
    day: date
    title: str


@dataclass(frozen=True)
class Insider:
    """지분 보고 한 건 — 임원·주요주주 소유보고(kind 「임원」) 또는 5% 대량보유 보고(kind 「5%」).
    임원은 이름을 받지 않고 직위만(이름은 노트에 쓸 일이 없다). 5% 보고자는 기관 이름 그대로."""
    rcept_no: str
    ticker: str
    day: date
    kind: str
    who: str
    change: int | None  # 보유 주식 수 증감(주)
    rate: float | None  # 보유 비율 % (5% 보고만)
    rate_chg: float | None  # 직전 보고 대비 %p (5% 보고만)


@dataclass(frozen=True)
class Financial:
    ticker: str
    fiscal_year: int
    revenue: int | None
    operating_income: int | None
    net_income: int | None
    equity: int | None
    liabilities: int | None
    rcept_no: str
    basis: str = "CFS"  # CFS 연결 · OFS 별도 — 연결이 없는 회사만 별도. 섞이면 비교가 깨지니 기록한다


class Dart:
    """OpenDART. 일 20,000 콜 한도를 코드로 지킨다."""

    LIMIT = 19_000
    # 정기공시(사업보고서) · 주요사항 · 거래소 · 기타. D(임원 소유)는 잡음이 너무 많다
    FORMS = ("A", "B", "I", "E")
    ACCOUNTS = {
        "매출액": "revenue",
        "영업이익": "operating_income",
        "영업이익(손실)": "operating_income",  # 은행·보험·증권. 금융회사는 「매출액」이 없다 — 빈칸이 맞다
        "당기순이익(손실)": "net_income",
        "당기순이익": "net_income",
        "자본총계": "equity",
        "부채총계": "liabilities",
    }

    def __init__(self) -> None:
        e = env()
        self.key, self.base, self.calls, self._corps = (
            e["OPEN_DART_API_KEY"], e["OPEN_DART_BASE_URL"], 0, None)  # fmt: skip

    def _call(self, path: str, **params) -> httpx.Response:
        if self.calls >= self.LIMIT:
            raise RuntimeError(f"DART 일 한도 보호: {self.calls} 콜")
        self.calls += 1
        return _get(f"{self.base}/{path}", self.key, crtfc_key=self.key, **params)

    def _list(self, path: str, **params) -> dict:
        """status 000 → 그대로 · 013(없음) → 빈 목록 · 그 밖은 예외."""
        j = self._call(path, **params).json()
        if j["status"] == "013":
            return {"list": [], "total_page": 0}
        if j["status"] != "000":
            raise RuntimeError(f"DART {path}: status {j['status']} {j.get('message')}")
        return j

    def corps(self) -> dict[str, str]:
        """종목코드 → corp_code. 전체 목록 zip 을 하루 캐시한다."""
        if self._corps is None:
            f = CACHE / "dart_corp.xml"
            if not f.exists() or time.time() - f.stat().st_mtime > 86_400:
                z = zipfile.ZipFile(io.BytesIO(self._call("corpCode.xml").content))
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(z.read(z.namelist()[0]))
            self._corps = parse_corps(f.read_text(encoding="utf-8"))
        return self._corps

    def _pages(self, start: date, end: date, **params) -> list[dict]:
        """공시 목록 — 코스피(Y)·코스닥(K) 전체를 90일씩, 끝 쪽까지 (corp_code 없이 부르면 3개월 제한)."""
        out, lo = [], start
        while lo <= end:
            hi = min(end, lo + timedelta(days=89))
            for cls in ("Y", "K"):
                page = 1
                while True:
                    j = self._list("list.json", bgn_de=lo.strftime("%Y%m%d"), end_de=hi.strftime("%Y%m%d"),
                                   corp_cls=cls, page_no=page, page_count=100, **params)  # fmt: skip
                    out += j["list"]
                    if page >= j["total_page"]:
                        break
                    page += 1
            lo = hi + timedelta(days=1)
        return out

    def disclosures(self, start: date, end: date, tickers: set[str]) -> list[Disclosure]:
        """우리 종목 공시만 남긴다. 정정공시는 최종본만."""
        return [d for form in self.FORMS for d in parse_disclosures(self._pages(start, end, pblntf_ty=form, last_reprt_at="Y"))
                if d.ticker in tickers]  # fmt: skip

    def listed(self, today: date) -> list[tuple[str, str]]:
        """지금 상장된 코스피·코스닥 회사 [(종목코드, 이름)] — 최근 반년 안에 정기보고서(사업·반기·분기)를 낸 회사.
        DART 회사 목록(corpCode)에는 상장 폐지된 회사도 종목코드를 단 채 남아 있다. 시세 API 는 쓰지 않는다 (data-rights §4)."""
        rows = self._pages(today - timedelta(days=180), today, pblntf_ty="A")
        return list({r["stock_code"]: r["corp_name"].strip() for r in rows if re.fullmatch(r"\d{6}", r.get("stock_code") or "")}.items())

    def financials(self, tickers: list[str], year: int) -> list[Financial]:
        """다중회사 주요계정(사업보고서) — 100개씩 1콜. 연결이 있으면 연결, 없으면 별도."""
        corps = self.corps()
        codes = [corps[t] for t in tickers if t in corps]
        rows: list[dict] = []
        for i in range(0, len(codes), 100):
            rows += self._list("fnlttMultiAcnt.json", corp_code=",".join(codes[i : i + 100]),
                               bsns_year=str(year), reprt_code="11011")["list"]  # fmt: skip
        return parse_financials(rows, year)

    def quarters(self, tickers: list[str], year: int) -> "list[Quarter]":  # Quarter 는 아래에 — 서버 파이썬 3.13 은 따옴표가 있어야 한다
        """그해 1분기·반기·3분기 보고서의 매출·영업이익 — 100개씩 1콜 × 보고서 셋. 아직 안 나온 보고서는 빈 목록."""
        corps = self.corps()
        codes = [corps[t] for t in tickers if t in corps]
        out: list[Quarter] = []
        for q, code in QUARTER_REPORTS.items():
            for i in range(0, len(codes), 100):
                rows = self._list("fnlttMultiAcnt.json", corp_code=",".join(codes[i : i + 100]), bsns_year=str(year), reprt_code=code)["list"]
                out += parse_quarters(rows, year, q)
        return out

    def company(self, ticker: str) -> tuple[str | None, str | None]:
        """회사 개황 — (업종 코드(통계청 한국표준산업분류 「264」「64992」), 홈페이지 도메인 「samsung.com」)."""
        cc = self.corps().get(ticker)
        j = self._call("company.json", corp_code=cc).json() if cc else {}
        return j.get("induty_code"), domain(j.get("hm_url"))

    def business_text(self, ticker: str, year: int) -> tuple[str | None, dict[str, str]]:
        """그해 사업보고서 「II. 사업의 내용」 — (접수번호, {"overview", "etc"}). 정정본은 고친 부분만 붙어 있을 때가 있어
        최신 판부터 차례로 열어 본문이 있는 첫 판을 쓴다. 원문은 저장하지 않고 읽기(AI)의 입력으로만 쓴다."""
        cc = self.corps().get(ticker)
        if not cc:
            return None, {}
        rows = self._list("list.json", corp_code=cc, bgn_de=f"{year + 1}0101", end_de=f"{year + 1}1231",
                          pblntf_ty="A", page_count=50)["list"]  # fmt: skip
        for rno in sorted((r["rcept_no"] for r in rows if "사업보고서" in r["report_nm"] and f"({year}.12)" in r["report_nm"]), reverse=True):
            raw = self._call("document.xml", rcept_no=rno).content
            if raw[:2] != b"PK":  # 파일 없음(014) 등 — 다음 판
                continue
            z = zipfile.ZipFile(io.BytesIO(raw))
            text = parse_report(z.read(max(z.namelist(), key=lambda n: z.getinfo(n).file_size)).decode("utf-8", "ignore"))
            if text["overview"]:
                return rno, text
        return None, {}

    def dividends(self, ticker: str, year: int) -> list[tuple[int, int | None, int | None, float | None]]:
        """배당에 관한 사항 — 그해 사업보고서가 주는 3년치 [(연도, 주당 현금배당금(보통주, 원), 현금배당금총액(원), 연결 배당성향 %)]."""
        cc = self.corps().get(ticker)
        if not cc:
            return []
        rows = self._list("alotMatter.json", corp_code=cc, bsns_year=str(year), reprt_code="11011")["list"]
        return parse_dividends(rows, year)

    def insiders(self, ticker: str, since: date) -> list[Insider]:
        """임원·주요주주 소유보고(elestock) + 5% 대량보유 보고(majorstock) — since 이후 것만. 둘 다 회사별 전체 이력을 준다."""
        cc = self.corps().get(ticker)
        if not cc:
            return []
        rows = [("임원", r) for r in self._list("elestock.json", corp_code=cc)["list"]]
        rows += [("5%", r) for r in self._list("majorstock.json", corp_code=cc)["list"]]
        return [x for kind, r in rows if (x := parse_insider(kind, r, ticker)).day >= since]

    def doc_text(self, rcept_no: str, every: bool = False) -> str:
        """공시 원문을 글자로 — 표는 칸마다 줄을 바꾼다(_flat). 파일이 없으면 빈 글.
        보통은 가장 큰 파일(본문) 하나, every=True 면 XML 파일 전부 (ETF 는 기초지수가 첨부 간이투자설명서 표지에 있다)."""
        raw = self._call("document.xml", rcept_no=rcept_no).content
        if raw[:2] != b"PK":
            return ""
        z = zipfile.ZipFile(io.BytesIO(raw))
        names = [n for n in z.namelist() if n.lower().endswith(".xml")] or z.namelist() if every else [max(z.namelist(), key=lambda n: z.getinfo(n).file_size)]
        return " ".join(_flat(z.read(n).decode("utf-8", "ignore")) for n in names)

    def ipos(self, start: date, end: date) -> "list[Ipo]":  # Ipo 는 아래에 — 서버 3.13 은 따옴표가 있어야 한다
        """그 사이 증권신고서(지분증권)를 낸 비상장 회사(corp_cls E)의 일반공모 — 회사마다 주요정보 1콜. 철회한 회사는 뺀다."""
        rows = self._list("list.json", bgn_de=start.strftime("%Y%m%d"), end_de=end.strftime("%Y%m%d"), corp_cls="E",
                          pblntf_detail_ty="C001", page_count=100)["list"]  # ponytail: 100건(석 달 공모 수십 건)이 넘으면 쪽 넘기기  # fmt: skip
        gone = {r["corp_code"] for r in rows if "철회" in r["report_nm"]}
        corps = dict.fromkeys(r["corp_code"] for r in rows if "증권신고서" in r["report_nm"] and r["corp_code"] not in gone)
        out = []
        for cc in corps:
            j = self._call("estkRs.json", corp_code=cc, bgn_de=start.strftime("%Y%m%d"), end_de=end.strftime("%Y%m%d")).json()
            if j.get("status") == "000" and (x := parse_ipo(j)):
                out.append(x)
        return out

    def bonds(self, start: date, end: date, tickers: set[str]) -> "list[Bond]":  # Bond 는 아래에 — 서버 3.13 은 따옴표
        """우리 종목이 그 사이 낸 증권신고서(채무증권) → 회사마다 주요정보 1콜."""
        rows = self._pages(start, end, pblntf_detail_ty="C002")
        corps = dict.fromkeys(r["corp_code"] for r in rows if r.get("stock_code") in tickers and "증권신고서(채무증권)" in r["report_nm"])
        out = []
        for cc in corps:
            j = self._call("bdRs.json", corp_code=cc, bgn_de=start.strftime("%Y%m%d"), end_de=end.strftime("%Y%m%d")).json()
            if j.get("status") == "000":
                out += parse_bonds(j)
        return out

    def buybacks(self, ticker: str, start: date, end: date) -> dict[str, int]:
        """자기주식 취득 결정의 취득 예정 금액(보통주, 원) — {접수번호: 금액}. 주요사항보고서 전용 API."""
        cc = self.corps().get(ticker)
        if not cc:
            return {}
        rows = self._list("tsstkAqDecsn.json", corp_code=cc, bgn_de=start.strftime("%Y%m%d"),
                          end_de=end.strftime("%Y%m%d"))["list"]  # fmt: skip
        return {r["rcept_no"]: v for r in rows if (v := _won(r.get("aqpln_prc_ostk")))}


# --- 공모주 — 새로 상장하려는 회사의 증권신고서(지분증권). 사실만 옮긴다 («청약할 만하다» 없음, 불변식 1) ---


@dataclass(frozen=True)
class Ipo:
    rcept_no: str
    corp_code: str
    name: str
    sub_start: date  # 일반 청약 첫날 · 마지막 날
    sub_end: date
    pay: date | None  # 납입일
    price: int | None  # 신고서에 적힌 1주 가격 (수요예측 전이면 희망 가격의 아래 끝일 수 있다 — 화면에 「신고서 기준」으로)
    total: int | None  # 모으는 돈 (원)
    lead: str  # 대표 주관 증권사
    uses: str  # 자금 쓰임 「시설자금 1,549억원 · 운영자금 …」


def _kdate(s: str) -> date | None:
    """「2026년 10월 07일」 → date."""
    m = re.search(r"(20\d\d)\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", s or "")
    return date(int(m[1]), int(m[2]), int(m[3])) if m else None


def parse_ipo(j: dict) -> Ipo | None:
    """estkRs.json (증권신고서 주요정보 · 지분증권) → 공모 한 건. 일반공모가 아니면(주주배정 증자 등) None."""
    g = {x["title"]: x["list"] for x in j.get("group", [])}
    gen, kind = (g.get("일반사항") or [{}])[-1], (g.get("증권의종류") or [{}])[-1]
    a, b = (re.split(r"~", gen.get("sbd", "")) + [""])[:2]
    start, end = _kdate(a), _kdate(b) or _kdate(a)
    if "일반공모" not in kind.get("slmthn", "") or not start:
        return None
    lead = next((r["actnmn"] for r in g.get("인수인정보", []) if r.get("actsen") == "대표"), "")
    uses = " · ".join(f"{r['se']} {won_short(v)}" for r in g.get("자금의사용목적", [])
                      if (v := _won(r.get("amt"))) and "제비용" not in r.get("se", ""))  # fmt: skip
    return Ipo(gen["rcept_no"], gen["corp_code"], gen["corp_name"].strip(), start, end, _kdate(gen.get("pymd", "")),
               _won(kind.get("slprc")), _won(kind.get("slta")), lead, uses)


def won_short(x: int) -> str:
    """원 → 「1,549억원」 「2.1조원」 — notes.won 과 같은 모양 (sources 는 notes 를 부르지 않는다)."""
    return f"{x / 10**12:,.1f}조원" if x >= 10**12 else f"{x / 10**8:,.0f}억원" if x >= 10**8 else f"{x / 10**4:,.0f}만원"


def parse_listing_day(text: str) -> date | None:
    """투자설명서 원문의 「상장 예정일」 · 「매매개시 예정일」 뒤 첫 날짜."""
    m = re.search(r"(상장|매매\s*개시)\s*예정\s*일[^0-9]{0,40}(20\d\d)\s*[년.\-]\s*(\d{1,2})\s*[월.\-]\s*(\d{1,2})", text)
    return date(int(m[2]), int(m[3]), int(m[4])) if m else None


# --- 회사채 — 상장사가 낸 증권신고서(채무증권). 사실만 옮긴다 ---


@dataclass(frozen=True)
class Bond:
    """회사채 한 회차 — 같은 신고서에 2년물·3년물처럼 회차가 여럿일 수 있다. 원 단위."""
    rcept_no: str
    tm: str  # 회차 「51-1」
    corp_code: str
    pay: date  # 납입일 = 돈이 실제로 들어오는 날
    amount: int  # 권면 총액
    maturity: date | None
    rate: str | None  # 이자율 — 수요예측 전 신고서엔 「-」
    lead: str
    uses: dict[str, int]  # 자금 쓰임 {구분: 원}


def parse_bonds(j: dict) -> list[Bond]:
    """bdRs.json (증권신고서 주요정보 · 채무증권) → 회차마다 하나. 파생결합사채(증권사 ELS 류)는 회사채가 아니라 뺀다."""
    g = {x["title"]: x["list"] for x in j.get("group", [])}
    out = []
    for r in g.get("일반사항", []):
        tm, pay, amt = (r.get("tm") or "").strip(), _kdate(r.get("pymd", "")), _won(r.get("fta")) or _won(r.get("slta"))
        if not pay or not amt or "파생결합" in r.get("bdnmn", ""):
            continue
        lead = next((x["actnmn"] for x in g.get("인수인정보", []) if (x.get("tm") or "").strip() == tm and x.get("actsen") == "대표"), "")
        uses: dict[str, int] = {}
        for x in g.get("자금의사용목적", []):
            if (x.get("tm") or "").strip() == tm and (v := _won(x.get("amt"))) and "제비용" not in x.get("se", ""):
                uses[x["se"].strip()] = uses.get(x["se"].strip(), 0) + v
        rate = (r.get("intr") or "").strip()
        out.append(Bond(r["rcept_no"], tm, r["corp_code"], pay, amt, _kdate(r.get("rpd", "")),
                        rate if re.search(r"\d", rate) else None, lead, uses))  # fmt: skip
    return out


# 앞으로의 일정이 적힌 공시 — 거래소 서식이라 「항목 이름」 다음 줄에 날짜가 온다. 자회사 공시는 그 회사 일정이 아니라 뺀다
SCHEDULE = re.compile(r"기업설명회|주주총회소집결의|현금ㆍ현물배당결정|현금ㆍ현물배당을위한주주명부폐쇄")


def has_schedule(title: str) -> bool:
    t = title.replace(" ", "")
    return bool(SCHEDULE.search(t)) and "자회사" not in t


def parse_schedule(title: str, text: str) -> list[tuple[date, str, str]]:
    """공시 원문 → [(날짜, 종류 EARNINGS·DIVIDEND·AGM·OTHER, 쉬운 말 한 줄)]. 날짜가 「-」면 그 일정은 없다."""
    if not has_schedule(title):
        return []
    t = title.replace(" ", "")
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    def after(label: str) -> str:
        """그 항목 이름 바로 다음 줄 — 「-」 칸이 뒤 항목의 날짜를 빌려 오지 않게 한 줄만 본다."""
        i = next((i for i, ln in enumerate(lines) if re.fullmatch(rf"(\d+\.\s*)?{label}", ln)), None)
        return lines[i + 1] if i is not None and i + 1 < len(lines) else ""

    def day(label: str) -> date | None:
        m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", after(label))
        return date(*map(int, m.groups())) if m else None

    out = []
    if "기업설명회" in t and (d := day("일시")):
        earn = "실적" in after("개최목적")
        out.append((d, "EARNINGS" if earn else "OTHER", "실적 발표" if earn else "기업설명회"))
    elif "주주총회소집결의" in t and (d := day("일시")):
        out.append((d, "AGM", "임시 주총" if "임시" in after("구분") else "정기 주총"))
    elif "배당결정" in t:
        out += [(d, "DIVIDEND", "배당 기준일")] if (d := day("배당기준일")) else []
        out += [(d, "DIVIDEND", "배당금 지급")] if (d := day("배당금지급 예정일자")) else []
    elif "주주명부폐쇄" in t and (d := day("기준일")):
        out.append((d, "DIVIDEND", "배당 기준일"))
    return out


def _num(s: str | None) -> float | None:
    s = (s or "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _flat(xml: str) -> str:
    t = re.sub(r"</(TR|P|TITLE)>", "\n", xml)
    t = re.sub(r"</T[DHE]>", " | ", t)
    t = html.unescape(re.sub(r"<[^>]+>", "", t))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", t)).strip()


def parse_report(xml: str) -> dict[str, str]:
    """사업보고서 본문에서 「1. 사업의 개요」~「3. 원재료」, 「7. 기타 참고사항」~「III.」 를 꺼낸다(제목 모양이 회사마다 조금씩 다르다)."""
    def cut(start, end, n):
        a = re.search(start, xml)
        if not a:
            return ""
        b = re.search(end, xml[a.end():])
        return _flat(xml[a.start(): a.end() + (b.start() if b else 400_000)])[:n]

    seg = re.search(r">\s*\d+\.\s*(영업부문|부문별\s*보고|부문\s*정보)[^<]{0,20}<", xml)  # 연결재무제표 주석의 첫 「영업부문」 — 부문별 매출·영업이익 표
    return {"overview": cut(r"<TITLE[^>]*>\s*1\.\s*사업의\s*개요", r"<TITLE[^>]*>\s*3\.", 7000),
            "etc": cut(r"<TITLE[^>]*>\s*7\.\s*기타\s*참고\s*사항", r"<TITLE[^>]*>\s*III\.", 12000),
            "segment": _flat(xml[seg.start(): seg.start() + 80_000])[:7000] if seg else ""}  # fmt: skip


def parse_dividends(rows: list[dict], year: int) -> list[tuple[int, int | None, int | None, float | None]]:
    def pick(se, kind=None):
        r = next((r for r in rows if (r.get("se") or "").replace(" ", "") == se and (kind is None or r.get("stock_knd") == kind)), {})
        return [r.get(k) for k in ("thstrm", "frmtrm", "lwfr")]

    dps, total, payout = pick("주당현금배당금(원)", "보통주"), pick("현금배당금총액(백만원)"), pick("(연결)현금배당성향(%)")
    out = []
    for i in range(3):
        d, t, p = _won(dps[i]), _won(total[i]), _num(payout[i])
        if d is not None or t is not None:
            out.append((year - i, d, None if t is None else t * 1_000_000, p))
    return out


def parse_insider(kind: str, r: dict, ticker: str) -> Insider:
    if kind == "임원":
        who = "주요주주" if "주요주주" in (r.get("isu_main_shrholdr") or "") else (r.get("isu_exctv_ofcps") or "임원").strip()
        chg, rate, rchg = _num(r.get("sp_stock_lmp_irds_cnt")), None, None
    else:
        who, chg = (r.get("repror") or "").strip(), _num(r.get("stkqy_irds"))
        rate, rchg = _num(r.get("stkrt")), _num(r.get("stkrt_irds"))
    return Insider(r["rcept_no"], ticker, date.fromisoformat(r["rcept_dt"]), kind, who,
                   None if chg is None else int(chg), rate, rchg)  # fmt: skip


def parse_corps(xml: str) -> dict[str, str]:
    """`<list>` 한 덩어리씩 — 태그를 건너뛰는 정규식은 비상장사 뒤에서 다음 회사 코드를 가로챈다."""
    out = {}
    for block in re.findall(r"<list>(.*?)</list>", xml, re.S):
        code = re.search(r"<corp_code>(\d+)</corp_code>", block)
        stock = re.search(r"<stock_code>(\d{6})</stock_code>", block)
        if code and stock:
            out[stock.group(1)] = code.group(1)
    return out


def parse_disclosures(rows: list[dict]) -> list[Disclosure]:
    return [
        Disclosure(r["rcept_no"], r["stock_code"], _ymd(r["rcept_dt"]), r["report_nm"].strip())
        for r in rows
        if re.fullmatch(r"\d{6}", r.get("stock_code") or "")
    ]


QUARTER_REPORTS = {1: "11013", 2: "11012", 3: "11014"}  # 1분기 · 반기 · 3분기 보고서


@dataclass(frozen=True)
class Quarter:
    """분기 보고서 한 장 — 그 분기 3개월(q) · 올해 누적(ytd) · 1년 전 같은 때(prev). 원 단위."""
    ticker: str
    year: int
    q: int
    revenue: int | None
    operating_income: int | None
    revenue_prev: int | None
    op_prev: int | None
    revenue_ytd: int | None
    op_ytd: int | None
    revenue_ytd_prev: int | None
    op_ytd_prev: int | None
    rcept_no: str
    basis: str


def parse_quarters(rows: list[dict], year: int, q: int) -> list[Quarter]:
    """다중회사 주요계정(분기·반기 보고서) → 회사마다 한 줄. 연결이 있으면 연결. 손익은 「thstrm」= 그 분기 3개월, 「_add」= 누적."""
    by: dict[tuple, dict] = {}
    for r in rows:
        col = {"매출액": "rev", "영업이익": "op", "영업이익(손실)": "op"}.get(r["account_nm"].replace(" ", ""))
        if col and r.get("stock_code") and r.get("sj_div", "IS") in ("IS", "CIS"):
            v = by.setdefault((r["stock_code"], r["fs_div"]), {"_r": r})
            v[col] = (_won(r.get("thstrm_amount")), _won(r.get("frmtrm_amount")),
                      _won(r.get("thstrm_add_amount")) or _won(r.get("thstrm_amount")),
                      _won(r.get("frmtrm_add_amount")) or _won(r.get("frmtrm_amount")))  # fmt: skip
    out = []
    for (tkr, fs), v in by.items():
        if fs == "OFS" and (tkr, "CFS") in by:
            continue
        rev, op = v.get("rev", (None,) * 4), v.get("op", (None,) * 4)
        out.append(Quarter(tkr, year, q, rev[0], op[0], rev[1], op[1], rev[2], op[2], rev[3], op[3], v["_r"]["rcept_no"], fs))
    return out


def parse_financials(rows: list[dict], year: int) -> list[Financial]:
    by: dict[tuple, dict] = {}
    for r in rows:
        col = Dart.ACCOUNTS.get(r["account_nm"].replace(" ", ""))
        if col and r.get("stock_code"):
            by.setdefault((r["stock_code"], r["fs_div"]), {"_r": r})[col] = _won(r["thstrm_amount"])
    out = []
    for (tkr, fs), v in by.items():
        if fs == "OFS" and (tkr, "CFS") in by:  # 연결이 있으면 별도는 버린다
            continue
        r = v.pop("_r")
        vals = {c: v.get(c) for c in set(Dart.ACCOUNTS.values())}
        out.append(Financial(tkr, year, **vals, rcept_no=r["rcept_no"], basis=fs))
    return out


# 업종 이름표 — 통계청 한국표준산업분류(고시 · 저작권법 제7조로 자유 이용) 코드를 쉬운 말로 줄인 우리 이름.
# 코드 앞자리가 가장 길게 맞는 것을 쓴다. 없으면 이름표를 달지 않는다(지어내지 않는다)
INDUSTRY = {
    "2611": "반도체", "2612": "반도체", "262": "전자부품", "26": "전자·통신장비",
    "28202": "2차전지", "282": "전지", "2830": "전선·케이블", "28": "전기장비",
    "20423": "화장품", "20": "화학", "311": "조선", "313": "항공우주", "3191": "철도차량", "31": "운송장비",
    "252": "방위산업", "25": "금속가공", "5821": "게임", "58": "소프트웨어",
    "64992": "지주회사", "641": "은행", "64": "금융", "6612": "증권", "66": "금융서비스",
    "10": "식료품", "12": "담배", "19": "석유정제", "21": "제약·바이오", "22": "타이어·고무", "24": "철강·금속",
    "29": "기계", "30": "자동차", "35": "전력·가스", "41": "건설", "46": "무역·도매", "50": "해운", "51": "항공",
    "52": "물류", "59": "엔터테인먼트", "61": "통신", "62": "IT 서비스", "63": "인터넷 플랫폼", "65": "보험",
    "70": "연구개발", "72": "엔지니어링", "96": "생활 서비스",
}  # fmt: skip


def domain(url: str | None) -> str | None:
    """「www.samsung.com/sec」·「http://www.skhynix.com」 → 「samsung.com」 — 로고를 찾을 때 쓴다."""
    host = re.sub(r"^[a-z]+://", "", (url or "").strip().lower()).split("/")[0].split(":")[0]
    host = host.removeprefix("www.")
    return host if re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", host) else None


def industry_label(code: str | None) -> str | None:
    for n in range(len(code or ""), 1, -1):
        if code[:n] in INDUSTRY:
            return INDUSTRY[code[:n]]
    return None


# --- 한국은행 ECOS ---

MACRO = {  # 쓸 지표 — 출처 표시 「한국은행 ECOS」 (data-rights §2)
    "ECOS:731Y003:0000003": "원/달러 환율",  # 한국은행 작성(종가 15:30). 731Y001 은 작성기관이 서울외국환중개라 쓰지 않는다 (data-rights §2, 10/9)
    "ECOS:817Y002:010200000": "국고채 3년",
}


# 읽기 팁 「오래 갖고 있으면」 글의 재료 — OECD 주가지수(월평균, 2015=100). 작성기관 OECD (CC BY 4.0, data-rights §2-1).
# ECOS 일별 코스피(802Y001)는 작성기관이 한국거래소라 쓰지 않는다
INDEX = {"ECOS:902Y002:KOR": "한국", "ECOS:902Y002:USA": "미국"}
# 읽기 팁 「금리」 그림 — 월평균, 작성기관 한국은행 (data-rights §2 · §6). 순서 = 그림 범례 순서
RATES = {"ECOS:722Y001:0101000": "기준금리", "ECOS:721Y001:5020000": "국고채 3년", "ECOS:721Y001:5050000": "국고채 10년",
         "ECOS:721Y001:7020000": "회사채 AA-", "ECOS:721Y001:7030000": "회사채 BBB-"}


def ecos(series_id: str, start: date, end: date, cycle: str = "D") -> list[tuple[date, float]]:
    key = env()["ECOS_API_KEY"]
    _, stat, item = series_id.split(":")
    fmt = "%Y%m%d" if cycle == "D" else "%Y%m"
    url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/100000/{stat}/{cycle}/"
           f"{start:{fmt}}/{end:{fmt}}/{item}")  # fmt: skip
    return parse_ecos(_get(url, key).json(), series_id)


def parse_ecos(body: dict, series_id: str) -> list[tuple[date, float]]:
    if "StatisticSearch" not in body:  # INFO-200 = 데이터 없음
        if body.get("RESULT", {}).get("CODE") == "INFO-200":
            return []
        raise RuntimeError(f"ECOS {series_id}: {body.get('RESULT')}")
    return [(_ymd(r["TIME"]), float(r["DATA_VALUE"])) for r in body["StatisticSearch"]["row"]
            if r["DATA_VALUE"] not in (None, "", "-")]  # fmt: skip


# --- 소식: 회사 뉴스룸 RSS + 언론사 RSS 의 제목·요약문·링크만 (data-rights §5) ---
# 언론사·회사가 배포용으로 직접 내보내는 피드다. 기사 본문은 받지도 저장하지도 않는다 — 글은 AI 가 제목·요약문만 보고 새로 쓴다.

PRESS_FEEDS = {  # 2026-10-08 열리는 것 확인 — 경제·산업·증권면. 같은 기사가 여러 피드에 나와도 url 이 열쇠라 한 번만 저장된다
    "https://www.yna.co.kr/rss/economy.xml": "연합뉴스", "https://www.yna.co.kr/rss/industry.xml": "연합뉴스",
    "https://www.yna.co.kr/rss/market.xml": "연합뉴스",
    "https://www.hankyung.com/feed/economy": "한국경제", "https://www.hankyung.com/feed/finance": "한국경제",
    "https://www.mk.co.kr/rss/30100041/": "매일경제", "https://www.mk.co.kr/rss/50200011/": "매일경제",
    "https://biz.chosun.com/arc/outboundfeeds/rss/?outputType=xml": "조선비즈",
    "https://biz.chosun.com/arc/outboundfeeds/rss/category/stock/?outputType=xml": "조선비즈",
    "https://rss.mt.co.kr/mt_news.xml": "머니투데이", "https://www.asiae.co.kr/rss/stock.htm": "아시아경제",
    "https://www.newsis.com/RSS/economy.xml": "뉴시스", "https://rss.etnews.com/Section901.xml": "전자신문",
    "https://rss.donga.com/economy.xml": "동아일보",
}  # fmt: skip
NEWSROOMS = ROOT / "hanjang" / "newsrooms.txt"  # 종목코드 → 회사 뉴스룸 RSS (손으로 갱신 · 없는 회사는 언론 피드만)


@dataclass(frozen=True)
class News:
    url: str
    published: datetime
    title: str
    press: str
    summary: str = ""  # RSS description — 언론사가 내보낸 요약문. 없으면 빈 글


def newsrooms() -> dict[str, str]:
    rows = (ln.split(maxsplit=1) for ln in NEWSROOMS.read_text(encoding="utf-8").splitlines() if ln and not ln.startswith("#"))
    return {t: u.strip() for t, u in rows}


def fetch_rss(url: str, press: str) -> list[News]:
    r = httpx.get(url, timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (hanjang)"})
    r.raise_for_status()
    return parse_rss(r.text, press)


def _plain(s: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def parse_rss(xml: str, press: str) -> list[News]:
    out = []
    for it in ElementTree.fromstring(xml).iter("item"):
        link, when = (it.findtext("link") or "").strip(), it.findtext("pubDate")
        if not link or not when:
            continue
        try:
            d = parsedate_to_datetime(when)
        except (TypeError, ValueError):
            continue
        out.append(News(link, d, _plain(it.findtext("title")), press, _plain(it.findtext("description"))[:300]))
    return out


def mentions(name: str, title: str) -> bool:
    """제목에 그 회사 이름이 낱말로 들어 있나 — 「LG」가 「LG전자」에, 「기아」가 「기아차」에 걸리지 않게 앞뒤에 글자가 없어야 한다."""
    return re.search(rf"(?<![0-9A-Za-z가-힣]){re.escape(name)}(?![0-9A-Za-z가-힣])", title) is not None
