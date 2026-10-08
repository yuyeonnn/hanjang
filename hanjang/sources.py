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


def is_common(ticker: str) -> bool:
    """보통주만 — 우선주는 끝자리가 0 이 아니다 (005930 삼성전자 / 005935 삼성전자우)."""
    return bool(re.fullmatch(r"\d{5}0", ticker))


def top_kospi(rows: list[dict], n: int) -> list[tuple[str, str]]:
    """시세 한 날치 → 코스피 보통주 시총 상위 n 개 (종목코드, 이름). 순수 함수."""
    xs = [r for r in rows if r.get("mrktCtg") == "KOSPI" and is_common(r.get("srtnCd", ""))]
    xs.sort(key=lambda r: -int(r.get("mrktTotAmt") or 0))
    return [(r["srtnCd"], r["itmsNm"]) for r in xs[:n]]


def kospi_universe(n: int = 100) -> list[tuple[str, str]]:
    """가장 최근 거래일 하나. 주말·휴일이면 하루씩 거슬러 간다.
    ponytail: 서비스 때는 공개된 코스피200 구성 목록 등으로 바꾼다 (시세는 상업 이용 금지)."""
    e = env()
    key, base = e["DATA_GO_KR_SERVICE_KEY"], e["DATA_GO_KR_BASE_URL"]
    d = date.today()
    for _ in range(10):
        d -= timedelta(days=1)
        body = _get(f"{base}/GetStockSecuritiesInfoService/getStockPriceInfo", key,
                    serviceKey=key, resultType="json", numOfRows=5000,
                    basDt=d.strftime("%Y%m%d")).json()["response"]["body"]  # fmt: skip
        if body["totalCount"]:
            items = body["items"]["item"]
            return top_kospi(items if isinstance(items, list) else [items], n)
    raise RuntimeError("최근 10일 시세가 비었다")


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

    def disclosures(self, start: date, end: date, tickers: set[str]) -> list[Disclosure]:
        """유가증권 전체를 90일씩 받아 우리 종목만 남긴다 (corp_code 없이 부르면 3개월 제한)."""
        out, lo = [], start
        while lo <= end:
            hi = min(end, lo + timedelta(days=89))
            for form in self.FORMS:
                page = 1
                while True:
                    j = self._list("list.json", bgn_de=lo.strftime("%Y%m%d"),
                                   end_de=hi.strftime("%Y%m%d"), corp_cls="Y", pblntf_ty=form,
                                   last_reprt_at="Y", page_no=page, page_count=100)  # 정정공시는 최종본만  # fmt: skip
                    out += [d for d in parse_disclosures(j["list"]) if d.ticker in tickers]
                    if page >= j["total_page"]:
                        break
                    page += 1
            lo = hi + timedelta(days=1)
        return out

    def financials(self, tickers: list[str], year: int) -> list[Financial]:
        """다중회사 주요계정(사업보고서) — 100개씩 1콜. 연결이 있으면 연결, 없으면 별도."""
        corps = self.corps()
        codes = [corps[t] for t in tickers if t in corps]
        rows: list[dict] = []
        for i in range(0, len(codes), 100):
            rows += self._list("fnlttMultiAcnt.json", corp_code=",".join(codes[i : i + 100]),
                               bsns_year=str(year), reprt_code="11011")["list"]  # fmt: skip
        return parse_financials(rows, year)

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

    def buybacks(self, ticker: str, start: date, end: date) -> dict[str, int]:
        """자기주식 취득 결정의 취득 예정 금액(보통주, 원) — {접수번호: 금액}. 주요사항보고서 전용 API."""
        cc = self.corps().get(ticker)
        if not cc:
            return {}
        rows = self._list("tsstkAqDecsn.json", corp_code=cc, bgn_de=start.strftime("%Y%m%d"),
                          end_de=end.strftime("%Y%m%d"))["list"]  # fmt: skip
        return {r["rcept_no"]: v for r in rows if (v := _won(r.get("aqpln_prc_ostk")))}


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

    return {"overview": cut(r"<TITLE[^>]*>\s*1\.\s*사업의\s*개요", r"<TITLE[^>]*>\s*3\.", 7000),
            "etc": cut(r"<TITLE[^>]*>\s*7\.\s*기타\s*참고\s*사항", r"<TITLE[^>]*>\s*III\.", 12000)}  # fmt: skip


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
    "ECOS:731Y001:0000001": "원/달러 환율",
    "ECOS:817Y002:010200000": "국고채 3년",
}


# 읽기 팁 「오래 갖고 있으면」 글의 재료 — OECD 주가지수(월평균, 2015=100). 작성기관 OECD (CC BY 4.0, data-rights §2-1).
# ECOS 일별 코스피(802Y001)는 작성기관이 한국거래소라 쓰지 않는다
INDEX = {"ECOS:902Y002:KOR": "한국", "ECOS:902Y002:USA": "미국"}


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


# --- 뉴스: 구글 뉴스 RSS — 제목·매체·링크만. ⚠️ 개발 중 개인용만 (data-rights §5) ---


def news_dev() -> bool:
    """`.env` 에 NEWS_DEV=1 일 때만 기사를 받고 노트에 싣는다 — 내 컴퓨터에서 나 혼자 볼 때.
    서버(.env 에 없음)는 늘 꺼진다: 남에게 보이는 곳에 개인용 기사가 나가지 않게."""
    return env().get("NEWS_DEV") == "1"


@dataclass(frozen=True)
class News:
    url: str
    published: datetime
    title: str
    press: str | None


def news(name: str, count: int = 5) -> list[News]:
    q = name if len(name) > 2 else f'"{name}" 주가'  # 두 글자 이름은 엉뚱한 기사를 끌어온다
    r = httpx.get("https://news.google.com/rss/search", timeout=20, follow_redirects=True,
                  params={"q": q + " when:7d", "hl": "ko", "gl": "KR", "ceid": "KR:ko"})  # fmt: skip
    r.raise_for_status()
    return parse_news(r.text, count)


ROBOTS_UA = "Mozilla/5.0 (hanjang dev; personal use)"
_robots: dict = {}
BLOCKED = re.compile(r"403 ERROR|Request blocked|Just a moment|Access Denied|Attention Required|404 Not Found", re.I)


def robots_ok(url: str) -> bool:
    """그 사이트 robots.txt 가 이 주소를 허용하나 — 호스트별 한 번. 못 받으면 False (우회하지 않는다)."""
    from urllib.parse import urlparse
    from urllib.robotparser import RobotFileParser

    host = urlparse(url).netloc
    if host not in _robots:
        rp = RobotFileParser()
        try:
            rp.parse(httpx.get(f"https://{host}/robots.txt", headers={"User-Agent": ROBOTS_UA},
                               timeout=15, follow_redirects=True).text.splitlines())  # fmt: skip
        except httpx.HTTPError:
            rp = None
        _robots[host] = rp
    return bool(_robots[host] and _robots[host].can_fetch(ROBOTS_UA, url))


def md_text(md: str) -> str:
    """Jina 마크다운 → 평문: 이미지·링크 주소·제목 기호·강조를 벗기고 공백을 합친다."""
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", md)
    md = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", md)
    md = re.sub(r"[#*_>`|]+", " ", md)
    return re.sub(r"\s+", " ", md).strip()


def jina_body(text: str, title: str, n: int = 2000) -> str:
    """Jina Reader 응답 → 본문 평문. 기사 제목이 나오는 자리부터 자른다(앞쪽 사이트 메뉴를 건너뛴다)."""
    head, _, md = text.rpartition("Markdown Content:")
    if t := re.search(r"^Title: *(\S.*)$", head, re.M):
        title = t[1]
    letters = re.findall(r"[0-9A-Za-z가-힣]", title)[:12]
    if len(letters) >= 6 and (m := re.search(r"[^0-9A-Za-z가-힣]{0,4}".join(map(re.escape, letters)), md)):
        md = md[m.start():]
    return md_text(md)[:n]


def read_article(url: str, title: str) -> tuple[str, str]:
    """구글 뉴스 링크 → (언론사 원문 주소, 본문 앞 2,000자). ⚠️ 개발 중 개인용만 (data-rights §5).
    본문은 글쓰기 입력으로만 쓰고 저장하지 않는다. robots 가 막으면 본문은 안 받는다. 어디서 실패하든 제목만으로 계속."""
    from googlenewsdecoder import gnewsdecoder  # 구글이 방식을 바꾸면 깨진다 — 실패는 정상 경로

    try:
        got = gnewsdecoder(url)
    except Exception:  # noqa: BLE001
        return url, ""
    orig = str(got.get("decoded_url") or "") if (got.get("status") or got.get("success")) else ""
    if not orig or "news.google.com" in orig or not robots_ok(orig):
        return orig or url, ""
    try:
        r = httpx.get("https://r.jina.ai/" + orig, timeout=30, follow_redirects=True)
    except httpx.HTTPError:
        return orig, ""
    body = jina_body(r.text, title) if r.status_code == 200 else ""
    return orig, "" if BLOCKED.search(body[:300]) else body


def parse_news(xml: str, count: int = 5) -> list[News]:
    """제목 끝의 「 - 매체」 꼬리를 떼고 매체는 `<source>` 에서 읽는다."""
    out = []
    for it in ElementTree.fromstring(xml).findall(".//item")[:count]:
        link, when = it.findtext("link"), it.findtext("pubDate")
        if not link or not when:
            continue
        src = it.find("source")
        press = (src.text or "").strip() if src is not None else None
        title = html.unescape(re.sub(r"<[^>]+>", "", it.findtext("title") or "")).strip()
        while press and title.endswith(f" - {press}"):  # 꼬리가 두 번 붙어 오기도 한다
            title = title[: -len(press) - 3].strip()
        out.append(News(link, parsedate_to_datetime(when), title, press or None))
    return out
