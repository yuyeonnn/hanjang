"""국내 ETF 한 장 — DART 펀드공시(투자설명서) 표지만으로 쓴다 (data-rights §6).

가격·담은 종목·분배금 금액·보수 숫자는 쓸 수 있는 자료가 없어서 싣지 않는다. AI 를 부르지 않는다 —
문장은 우리가 정해 둔 것이고, 원문에서 가져오는 것은 이름·등급·날짜뿐이다. 노트 표(notes)에 같은 모양으로 넣어
카드·노트 화면·월요일 메일이 주식과 똑같이 보여 준다. 종목 코드는 KRX 자료라 쓰지 않고 펀드 이름에서 만든 id(ETF…)를 쓴다.
"""

import hashlib
import json
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta

from hanjang import db, notes, sources

# 상품 이름 앞의 브랜드 — 펀드 이름 「삼성KODEX 코스피증권상장지수투자신탁[주식]」에서 「KODEX 코스피」를 꺼낸다
BRANDS = (r"KODEX|TIGER|ACE|RISE|SOL|PLUS|HANARO|KIWOOM|TIMEFOLIO|WON|1Q|BNK|KOSEF|ARIRANG|KBSTAR|KoAct|마이티|파워|"
          r"히어로즈|에셋플러스|UNICORN|TRUSTON|VITA|FOCUS|마이다스|DAISHIN|KCGI|더제이|HK|ITF|TIME|IBK|TREX|아이엠에셋|DS")  # fmt: skip
# 따라가는 지수 → 쉬운 말. 확실한 것만 (모르면 지수 이름만 쓴다)
INDEX_PLAIN = (
    (r"코스피\s*200|KOSPI\s*200", "코스피 회사 가운데 덩치가 크고 거래가 많은 200곳"),
    (r"코스닥\s*150|KOSDAQ\s*150", "코스닥을 대표하는 회사 150곳"),
    (r"S&P\s*500", "미국 큰 회사 500곳"),
    (r"나스닥\s*100|NASDAQ\s*-?\s*100", "미국 나스닥 시장의 큰 회사 100곳(금융회사는 빠져요)"),
    (r"필라델피아\s*반도체|PHLX", "미국에 상장된 반도체 회사 30곳"),
    (r"국고채\s*3년", "만기가 3년쯤 남은 나라 빚(국고채)"),
    (r"국고채\s*10년", "만기가 10년쯤 남은 나라 빚(국고채)"),
    (r"^(KODEX|TIGER|ACE|RISE) 코스피$|^KOSPI$|^코스피$", "코스피에 상장된 회사 전체"),
)
# 이름에 드러난 구조 → 꼭 알아야 할 한 문장 (상품 설계에 대한 사실)
FEATURES = (
    (r"인버스\s*2X|인버스2X", "기초지수가 하루 움직인 것과 반대 방향으로 두 배만큼 움직이게 만든 상품이에요. 하루 단위로 맞추기 때문에 오래 들고 있으면 「반대로 두 배」와 결과가 크게 달라질 수 있어요."),
    (r"인버스", "기초지수가 하루 움직인 것과 반대 방향으로 움직이게 만든 상품이에요. 하루 단위로 맞추기 때문에 오래 들고 있으면 지수와 정확히 반대가 되지 않을 수 있어요."),
    (r"레버리지|2X", "기초지수가 하루 움직인 것의 두 배만큼 움직이게 만든 상품이에요. 하루 단위로 맞추기 때문에 오래 들고 있으면 「지수의 두 배」와 결과가 크게 달라질 수 있어요."),
    (r"커버드콜", "주식을 담으면서 그 주식을 정해진 값에 살 권리(콜옵션)를 팔고, 받은 돈을 분배금 재원으로 쓰는 구조예요. 대신 주가가 크게 오를 때 오른 몫의 일부를 포기해요."),
    (r"\(합성", "주식을 직접 사지 않고 증권사와 맺은 계약(스와프)으로 지수만큼의 수익을 받아요. 그래서 계약 상대 증권사의 위험이 함께 있어요."),
    (r"액티브", "지수를 그대로 따라가지 않고, 운용을 맡은 사람이 종목을 골라 비교 지수보다 나은 결과를 목표로 운용해요."),
    (r"TotalReturn|TR(?![A-Za-z])", "분배금을 나눠 주지 않고 그 돈을 다시 투자하는 방식이에요."),
    (r"\((합성\s*)?H\)", "환율이 오르내려 생기는 손익을 줄이는 장치(환헤지)를 해 둔 상품이에요."),
)
MATURITY = re.compile(r"(\d{2})-(\d{2})\s*(국고채|특수채|금융채|회사채|은행채|채권|국공채|우량)")
# 투자설명서를 고친 이유 → 쉬운 말. 앞의 것이 이긴다 (운용역 「변경」과 운용규모 「업데이트」를 가른다)
CHANGES = (
    (r"해지|상장\s*폐지", "상품을 끝내는 것(해지·상장 폐지)과 관련된 내용이 있어요"),
    (r"기초지수\s*(변경|명칭)", "따라가는 지수가 바뀌었어요"),
    (r"보수", "보수(해마다 떼는 비용)에 관한 내용이 바뀌었어요"),
    (r"분배", "분배금을 주는 규칙이 바뀌었어요"),
    (r"운용역\s*변경|운용전문인력\s*변경|책임운용", "운용을 맡은 사람이 바뀌었어요"),
    (r"투자전략|투자목적", "투자 방법에 관한 내용이 바뀌었어요"),
    (r"업데이트|갱신|운용실적|투자실적", "운용 실적 같은 숫자를 정기적으로 새로 고쳤어요"),
)
RISK_SCALE = "1등급이 가장 출렁임이 크고 6등급이 가장 작아요"
CANT = ("오늘 가격, 지금 담고 있는 종목, 분배금 금액, 보수(해마다 떼는 비용) 숫자는 한장이 쓸 수 있는 자료에 없어요. "
        "보수는 투자설명서 원문에, 나머지는 증권사 앱에서 확인해 주세요.")  # fmt: skip


def fund_name(report_nm: str) -> str | None:
    """「[기재정정]투자설명서(집합투자증권)(삼성KODEX코스피증권상장지수투자신탁[주식])」 → 펀드 이름. ETF 투자설명서가 아니면 None."""
    nm = re.sub(r"^\s*\[[^\]]*\]", "", report_nm)
    m = re.match(r"투자설명서\(집합투자증권[^)]*\)\((.+)\)\s*$", nm)
    return m.group(1).strip() if m and "상장지수" in m.group(1) else None


def short(name: str) -> str:
    """펀드 이름 → 사람들이 부르는 상품 이름 「KODEX 코스피」 「TIGER 유로스탁스50(합성 H)」."""
    m = re.search(rf"({BRANDS})(?!{BRANDS})", name)  # 「IBKIBK200」 — 운용사 이름과 브랜드가 같으면 뒤의 것
    s = name[m.start():] if m else name
    cut = re.search(r"(증권|특별자산|부동산|파생상품|혼합자산|재간접)?(자)?상장지수", s)
    tail = re.search(r"\((합성\s*)?H\)|\(합성\)", s[cut.start():]) if cut else None
    s = s[: cut.start()] if cut else s
    if m:
        s = re.sub(rf"^({BRANDS})\s*", r"\1 ", s)
    if tail:
        s += "(" + re.sub(r"합성\s*H", "합성 H", tail.group(0)[1:-1]) + ")"
    return s.strip()


def ticker_of(name: str) -> str:
    return "ETF" + hashlib.md5(name.encode()).hexdigest()[:5]


def parse_cover(text: str) -> dict:
    """투자설명서·간이투자설명서 표지 → {risk, risk_label, index, asset, risks, manager, as_of, first, change}. 없는 칸은 빠진다."""
    t = re.sub(r"\s+", " ", text)
    out: dict = {}
    if m := re.search(r"투자위험등급\s*(\d)\s*등급\s*\[?\s*(매우 높은|다소 높은|높은|보통|낮은|매우 낮은) 위험", t):
        out["risk"], out["risk_label"] = int(m[1]), m[2] + " 위험"
    if m := re.search(r"[“\"]\s*([^“”\"]{2,60}?)\s*[”\"]\s*[을를]\s*기초지수", t):
        out["index"] = m[1].strip()
    if m := re.search(r"이 투자신탁은\s*(.{1,30}?)\s*[을를]\s*법\s*시행령\s*제\s*94조", t):
        out["asset"] = m[1].strip()
    if m := re.search(r"따라서\s*(.{5,240}?)\s*등이 있으므로", t):
        out["risks"] = [x.strip() for x in re.split(r",|ㆍ|·", m[1]) if x.strip()][:5]
    if m := re.search(r"집합투자업자\s*명칭\s*:\s*(\S+?)(주식회사|\(주\)|㈜|\s)", t):
        out["manager"] = m[1]
    if m := re.search(r"작\s*성\s*기\s*준\s*일\s*:?\s*(\d{4})\s*[.년]\s*(\d{1,2})\s*[.월]\s*(\d{1,2})", t):
        out["as_of"] = date(int(m[1]), int(m[2]), int(m[3])).isoformat()
    if m := re.search(r"최초\s*제출일\s*:?\s*(\d{4})\s*[.년]\s*(\d{1,2})", t):
        out["first"] = f"{m[1]}-{int(m[2]):02d}"
    head = t[: t.find("투자위험등급")] if "정정" in t[:200] and "투자위험등급" in t else ""  # 정정신고 표지 = 이번에 고친 이유
    if ch := next((say for pat, say in CHANGES if re.search(pat, head)), None):
        out["change"] = ch
    return out


def note(name: str, info: dict, rcept_no: str, filed: str) -> tuple[list, dict]:
    """(사실, 노트 본문) — 노트 화면이 읽는 모양 그대로. 모든 문장의 근거는 투자설명서 한 장(F1)."""
    s = short(name)
    facts = [{"id": "F1", "text": f"{name} 투자설명서 ({filed})", "url": notes.DART.format(rcept_no), "tone": 0, "slots": {}}]

    def say(text):
        return {"text": text, "refs": ["F1"]}

    idx = info.get("index")
    plain = next((p for pat, p in INDEX_PLAIN if re.search(pat, idx or "") or re.search(pat, s)), None)
    feats = [f for pat, f in FEATURES if re.search(pat, name)]
    if (m := MATURITY.search(name)) and not feats:
        feats.append(f"이름의 「{m[1]}-{m[2]}」는 20{m[1]}년 {int(m[2])}월에 담은 채권의 만기가 오고 운용을 마치도록 만든 상품이라는 뜻이에요.")
    kind = re.search(r"투자신탁\s*[\[(]([^\])]+)[\])]", name)
    asset = info.get("asset") or (kind and kind[1].split("-")[0])

    what = []
    if idx:
        what.append(f"{s}{notes.josa(s, '는')} 「{idx}」{notes.josa(idx, '를')} 따라가도록 만든 ETF예요.")
        if plain:
            what.append(f"이 지수는 {plain}{notes.josa(plain, '를')} 한데 묶은 거예요.")
    elif plain:
        what.append(f"{s}{notes.josa(s, '는')} {plain}{notes.josa(plain, '를')} 한꺼번에 담는 ETF예요.")
    else:
        what.append(f"{s}{notes.josa(s, '는')} 여러 자산을 한 바구니에 담아 주식처럼 사고파는 상품(ETF)이에요.")
    if asset:
        what.append(f"주로 {asset}에 투자해요.")
    what += feats
    if info.get("manager"):
        what.append(f"운용은 {info['manager']}{notes.josa(info['manager'], '가')} 맡고 있어요" + (f", {info['first'][:4]}년부터 있던 상품이에요." if info.get("first") else "."))

    risk = []
    if info.get("risk"):
        risk.append(f"운용사가 실제로 값이 얼마나 출렁였는지를 보고 매긴 위험 등급은 6단계 가운데 {info['risk']}등급({info['risk_label']})이에요. {RISK_SCALE}.")
    if info.get("risks"):
        risk.append(f"투자설명서는 {', '.join(info['risks'])} 같은 위험을 먼저 적어 두었어요.")
    risk.append("ETF 도 예금이 아니라서 넣은 돈보다 줄어들 수 있어요.")

    secs = [{"title": "무엇을 담는 상자인가요?", "sentences": [say(x) for x in what]},
            {"title": "얼마나 출렁일 수 있나요?", "sentences": [say(x) for x in risk]}]  # fmt: skip
    if info.get("change"):
        d = date.fromisoformat(filed)
        secs.append({"title": "투자설명서에서 바뀐 것", "sentences": [say(f"{d.month}월 {d.day}일에 투자설명서를 고쳤어요 — {info['change']}.")]})
    secs.append({"title": "여기서 못 보여드리는 것", "sentences": [say(CANT)]})
    head = (f"{s}{notes.josa(s, '는')} {plain}{notes.josa(plain, '를')} 한꺼번에 담는 상자예요." if plain else what[0])
    # 요약은 머리말 다음 이야기 — 위험 등급 · 이번에 바뀐 것 (머리말을 되풀이하지 않는다)
    summary = ([say(risk[0].split(". ")[0] + ".")] if info.get("risk") else []) + (
        [say(f"최근 투자설명서를 고쳤는데, {info['change']}.")] if info.get("change") and "정기적으로" not in info["change"] else [])
    summary = summary or [say(what[1] if len(what) > 1 else what[0])]
    body = {"headline": head, "summary": summary, "sections": secs, "links": {"F1": facts[0]["url"]}}
    return facts, body


def filings(dart: "sources.Dart", start: date, end: date) -> dict[str, tuple[str, str]]:
    """그 사이 낸 ETF 투자설명서 — {펀드 이름: (접수번호, 날짜)}, 같은 펀드는 가장 새것. 운용사는 비상장이라 corp_cls 없이 90일씩."""
    out: dict[str, tuple[str, str]] = {}
    lo = start
    while lo <= end:
        hi = min(end, lo + timedelta(days=89))
        page = 1
        while True:
            j = dart._list("list.json", bgn_de=lo.strftime("%Y%m%d"), end_de=hi.strftime("%Y%m%d"), pblntf_ty="G",
                           page_no=page, page_count=100)  # fmt: skip
            for r in j["list"]:
                if (n := fund_name(r["report_nm"])) and (n not in out or r["rcept_no"] > out[n][0]):
                    out[n] = (r["rcept_no"], sources._ymd(r["rcept_dt"]).isoformat())
            if page >= j["total_page"]:
                break
            page += 1
        lo = hi + timedelta(days=1)
    return out


def main(today: date, con: sqlite3.Connection | None = None, dart: "sources.Dart | None" = None) -> None:
    con, dart = con or db.connect(), dart or sources.Dart()
    # 처음엔 1년 남짓(ETF 는 해마다 한 번은 투자설명서를 새로 낸다), 그다음부터는 지난 열흘만
    (n,) = con.execute("select count(*) from etfs").fetchone()
    got = filings(dart, today - timedelta(days=400 if n == 0 else 10), today)
    for name, (rno, filed) in got.items():
        t = ticker_of(name)
        con.execute("insert into stocks (ticker, name, active) values (?, ?, 0) on conflict(ticker) do update set name = excluded.name", (t, short(name)))
        con.execute("insert into etfs (ticker, name, rcept_no, filed) values (?, ?, ?, ?) on conflict(ticker) do update set"
                    " rcept_no = excluded.rcept_no, filed = excluded.filed where excluded.rcept_no > etfs.rcept_no", (t, name, rno, filed))  # fmt: skip
    con.commit()
    # 누가 담은 ETF 만 원문을 연다 — 새 투자설명서가 나왔을 때만 다시
    held = con.execute("select e.ticker, e.name, e.rcept_no, e.filed, e.info, e.read_rcept from etfs e"
                       " where e.ticker in (select ticker from holdings)").fetchall()  # fmt: skip
    wrote = 0
    for t, name, rno, filed, info, read in held:
        if read != rno:
            text = dart.doc_text(rno, every=True)
            if not text:  # 원문 서비스 점검 등 — 내일 다시
                continue
            info = json.dumps(parse_cover(text), ensure_ascii=False)
            con.execute("update etfs set info = ?, read_rcept = ? where ticker = ?", (info, rno, t))
        if not info:
            continue
        facts, body = note(name, json.loads(info), rno, filed)
        con.execute("insert or replace into notes values (?, ?, ?, ?, ?, ?)",
                    (t, notes.week_of(today), json.dumps(facts, ensure_ascii=False), json.dumps(body, ensure_ascii=False),
                     "code:etf", datetime.now().isoformat()))  # fmt: skip
        wrote += 1
    con.commit()
    print(f"ETF 투자설명서 {len(got)}개 (전체 {n + len(got) if n == 0 else n}개) · 한 장 {wrote}개 · DART {dart.calls}콜")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(date.today())
