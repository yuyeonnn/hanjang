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
    """`.env` 한 파일 — KEY=VALUE 줄만."""
    f = ROOT / ".env"
    pairs = (ln.split("=", 1) for ln in f.read_text(encoding="utf-8").splitlines() if "=" in ln)
    return {k.strip(): v.strip() for k, v in pairs}


def _ymd(s: str) -> date:
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


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
class Financial:
    ticker: str
    fiscal_year: int
    revenue: int | None
    operating_income: int | None
    net_income: int | None
    equity: int | None
    liabilities: int | None
    rcept_no: str


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
                                   page_no=page, page_count=100)  # fmt: skip
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
        out.append(Financial(tkr, year, **vals, rcept_no=r["rcept_no"]))
    return out


# --- 한국은행 ECOS ---

MACRO = {  # 쓸 지표 — 출처 표시 「한국은행 ECOS」 (data-rights §2)
    "ECOS:731Y001:0000001": "원/달러 환율",
    "ECOS:817Y002:010200000": "국고채 3년",
}


def ecos(series_id: str, start: date, end: date) -> list[tuple[date, float]]:
    key = env()["ECOS_API_KEY"]
    _, stat, item = series_id.split(":")
    url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/100000/{stat}/D/"
           f"{start:%Y%m%d}/{end:%Y%m%d}/{item}")  # fmt: skip
    return parse_ecos(_get(url, key).json(), series_id)


def parse_ecos(body: dict, series_id: str) -> list[tuple[date, float]]:
    if "StatisticSearch" not in body:  # INFO-200 = 데이터 없음
        if body.get("RESULT", {}).get("CODE") == "INFO-200":
            return []
        raise RuntimeError(f"ECOS {series_id}: {body.get('RESULT')}")
    return [(_ymd(r["TIME"]), float(r["DATA_VALUE"])) for r in body["StatisticSearch"]["row"]
            if r["DATA_VALUE"] not in (None, "", "-")]  # fmt: skip


# --- 뉴스: 구글 뉴스 RSS — 제목·매체·링크만. ⚠️ 개발 중 개인용만 (data-rights §5) ---


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
