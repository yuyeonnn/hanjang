"""기업 노트 한 장을 그린다 — 사실 묶음·숫자 칸·일정 설명·인용. 글은 notes 가 쓰고 여기서는 모양만."""

import json
import re
from datetime import date
from urllib.parse import quote

from hanjang import notes
from hanjang.charts import DONUT, chapter, price_chart
from hanjang.ui import DART_VIEW, RULE, RULE_FLIP, avatar, e, industry_chip, logo, page


def business_block(biz: dict | None, rno: str | None) -> str:
    """무엇으로 돈을 버나요? — 회사 사업보고서 「사업의 내용」을 AI 가 요약(숫자는 원문 그대로인지 코드가 대조) + 부문별 매출 비중 막대."""
    if not biz:
        return ""
    segs = "".join(
        f'<div class="flex items-center gap-2 py-1"><span class="w-[44%] text-[12px] leading-4 text-on-surface-variant">{e(s["name"])}</span>'
        f'<span class="flex-1 h-2 rounded-full bg-surface-container overflow-hidden"><span class="block h-full bg-primary rounded-full" style="width:{min(float(s["share"][:-1]), 100):.1f}%"></span></span>'
        f'<span class="w-12 text-right text-[12px] font-semibold text-on-surface tabular-nums">{e(s["share"])}</span></div>' for s in biz.get("segments", []))  # fmt: skip
    url = rno if (rno or "").startswith("http") else DART_VIEW.format(rno)  # 미국은 report() 가 SEC 주소를 넘긴다
    link = f'<a class="text-outline underline" href="{url}" target="_blank" rel="noopener">{"연차 보고서(10-K) 원문" if url.startswith("https://www.sec.gov") else "사업보고서 원문"}</a>' if rno else ""
    return chapter("무엇으로 돈을 버나요?", " ".join(e(x) for x in biz["what"]),
                   (f'<div class="mt-space-xs"><div class="font-label-micro text-label-micro text-outline mb-1">부문별 매출 비중</div>{segs}</div>' if segs else "")
                   + f'<p class="font-label-micro text-label-micro text-outline">회사가 낸 {biz.get("year", "")}년 사업보고서를 요약했어요 · {link}</p>')  # fmt: skip


def ring(parts: list[tuple[float, str]], size: str = "w-20 h-20") -> str:
    """둘레 100 짜리 원 — (비율%, 색) 조각들을 이어 그린다. dasharray 가 곧 %."""
    acc, out = 0.0, []
    for pct, col in parts:
        out.append(f'<circle cx="21" cy="21" r="15.915" fill="none" stroke="{col}" stroke-width="7" '
                   f'stroke-dasharray="{pct:.2f} {100 - pct:.2f}" stroke-dashoffset="{25 - acc:.2f}"/>')  # fmt: skip
        acc += pct
    return f'<svg viewBox="0 0 42 42" class="{size} shrink-0">{"".join(out)}</svg>'


def money_blocks(fin: tuple | None, mid: dict | None = None) -> str:
    """회사 사정 아래 그림 둘 — ① 100원 팔면 얼마 남나(매출→영업이익→순이익) ② 빚과 내 돈(부채 : 자본).
    증권사 보고서의 손익·재무상태표를 그대로 옮기지 않고 질문 하나에 그림 하나 (사용자 10/9). 매출이 없는 금융사는 ①②를 그리지 않는다
    (예금이 빚으로 잡혀 부채비율이 뜻이 없다)."""
    if not fin:
        return ""
    mid = mid or {}
    y, rev, oi, ni, eq, li = fin
    if mid.get("금융"):  # 증권·은행·보험 — 고객 돈이 빚으로, 사고판 금액이 매출로 잡혀 두 그림 모두 다른 업종과 같은 잣대가 아니다 (사용자 10/9)
        roe = f" 대신 자기 돈으로 1년에 얼마를 벌었는지(ROE {ni / eq * 100:.1f}%)를 봐요." if ni is not None and eq and eq > 0 else ""
        return ('<div class="py-space-md my-space-xs border-b border-outline-variant/30"><div class="font-label-regular text-label-regular text-on-surface font-semibold">금융회사는 잣대가 달라요</div>'
                '<p class="mt-1 text-[13px] leading-relaxed text-on-surface-variant">고객이 맡긴 돈이 「빚」으로 잡혀 부채비율이 원래 수백~천 %이고, 사고판 금액이 「매출」로 잡혀 100원당 남긴 돈이 작게 나와요. '
                f'그래서 이 두 그림은 싣지 않아요.{e(roe)}</p>'
                '<a class="mt-1 inline-block text-[12px] text-primary underline" href="/learn/sector-finance">금융회사는 어떻게 봐요? →</a></div>')  # fmt: skip
    out = []
    if rev and rev > 0 and oi is not None and ni is not None:
        rows = [("매출 — 판 돈", rev, "bg-primary"), ("영업이익 — 본업으로 남긴 돈", oi, "bg-secondary"), ("순이익 — 세금·이자까지 내고 남은 돈", ni, "bg-secondary/60")]
        bars = "".join(
            f'<div class="flex items-center gap-3 py-1.5"><span class="w-[52%] text-[12px] leading-4 text-on-surface-variant">{e(k)}</span>'
            f'<span class="flex-1 h-2.5 rounded-full bg-surface-container overflow-hidden"><span class="block h-full {col} rounded-full" style="width:{max(min(v / rev * 100, 100), 0):.1f}%"></span></span>'
            f'<span class="w-11 text-right text-[12px] font-semibold tabular-nums {"text-tertiary" if v < 0 else "text-on-surface"}">{"적자" if v < 0 else f"{v / rev * 100:.0f}원"}</span></div>'
            for k, v, col in rows)  # fmt: skip
        usual = (f'<p class="text-[11px] text-outline mt-2">같은 업종({e(mid["업종"])}) {mid["곳수"]}곳 보통(중간값): 영업이익 {mid["백원당"]:.0f}원'
                 f'{". 이 업종은 원래 조금씩 남겨요" if mid["백원당"] < 5 else ""} · <a class="text-primary underline" href="/learn/sector-margin">업종마다 달라요</a></p>'
                 if mid.get("백원당") is not None else "")  # fmt: skip
        out.append(f'<div class="font-label-regular text-label-regular text-on-surface font-semibold mb-2">{y}년, 100원 팔면 얼마 남았나</div>{bars}{usual}')
        if eq and eq > 0 and li is not None:
            ratio = li / eq * 100
            a, b = eq / (eq + li) * 100, li / (eq + li) * 100
            out.append(f'<div class="mt-8 font-label-regular text-label-regular text-on-surface font-semibold">빚과 내 돈 — 부채비율 {ratio:,.0f}%</div>'
                       '<div class="mt-3 h-3 w-full rounded-full overflow-hidden flex">'
                       f'<span class="h-full bg-primary" style="width:{a:.1f}%"></span><span class="h-full" style="width:{b:.1f}%;background:#F4806A"></span></div>'
                       f'<div class="flex justify-between text-[11px] text-on-surface-variant mt-2"><span>내 돈(자본) {notes.won(eq)}</span><span>빚(부채) {notes.won(li)}</span></div>'
                       f'<p class="mt-1.5 text-[11px] leading-[18px] text-outline">내 돈 100원에 빚 {ratio:,.0f}원이 있다는 뜻이에요. '
                       + (f'같은 업종({e(mid["업종"])}) 보통(중간값)은 {mid["부채비율"]:,.0f}%예요. ' if mid.get("부채비율") is not None else "")
                       + (f'{e(mid["업종"])} 업종은 {e(mid["빚이유"])}. <a class="text-primary underline" href="/learn/sector-debt">더 보기</a>' if mid.get("빚이유")
                          else "" if mid.get("부채비율") is not None else "업종마다 보통 수준이 달라요.")
                       + '</p>')  # fmt: skip
    if not out:
        return ""
    return ('<div class="py-6 my-space-sm border-b border-outline-variant/30">' + "".join(out)
            + '<p class="mt-5 text-[11px] text-outline">연결재무제표 기준 · 자료: DART 사업보고서</p></div>')  # fmt: skip


def returns_html(divs: list[tuple], buys: list[tuple]) -> str:
    """주주에게 돌려준 돈 — 최근 해 배당 총액 + 최근 1년 자사주 취득 결정 금액. 기간이 달라 더하지 않고 나란히 (사용자 10/9 검토)."""
    rows = []
    if divs and divs[-1][2]:
        rows.append((f"{divs[-1][0]}년 배당", divs[-1][2], DONUT[0]))
    if buys:
        rows.append((f"최근 1년 자사주 사기로 한 돈 · {len(buys)}번", sum(a for _, a in buys), DONUT[3]))
    if len(rows) < 2:
        return ""
    top = max(v for _, v, _ in rows)
    bars = "".join(f'<div class="flex items-center gap-2 py-0.5"><span class="w-[46%] text-[12px] leading-4 text-on-surface-variant">{e(k)}</span>'
                   f'<span class="flex-1 h-2.5 rounded-full bg-surface-container overflow-hidden"><span class="block h-full rounded-full" style="width:{v / top * 100:.1f}%;background:{c}"></span></span>'
                   f'<span class="w-16 text-right text-[12px] font-semibold text-on-surface tabular-nums">{e(notes.won(v))}</span></div>' for k, v, c in rows)  # fmt: skip
    return ('<div class="py-2"><div class="font-label-regular text-label-regular text-on-surface font-semibold mb-1">배당만이 아니에요 — 자사주로 돌려준 것까지</div>'
            f'{bars}<p class="text-[11px] text-outline mt-1">자사주 금액은 회사가 「사기로 결정」한 금액이에요(실제 산 금액과 다를 수 있어요). 자료: DART 공시</p></div>')  # fmt: skip


def dividend_block(divs: list[tuple], fin: tuple | None = None, buys: list[tuple] | None = None) -> str:
    """주주에게 돌려준 것 — 해마다 주당 현금배당금(보통주) 막대 + 번 돈을 어떻게 썼나 도넛(배당 : 회사에 남김) + 최근 배당성향."""
    divs = [r for r in divs if r[1]]
    if not divs:
        return ""
    ring_html = ""
    if fin and fin[0] == divs[-1][0] and fin[3] and fin[3] > 0 and divs[-1][2]:
        ni, tot = fin[3], divs[-1][2]
        p = min(tot / ni * 100, 100)
        ring_html = (f'<div class="flex items-center gap-3 py-2"><div class="relative">{ring([(p, DONUT[0]), (100 - p, DONUT[6])], "w-[72px] h-[72px]")}'
                     f'<div class="absolute inset-0 flex items-center justify-center text-[12px] font-bold text-on-surface">{p:.0f}%</div></div>'
                     f'<ul class="text-[12px] text-on-surface"><li class="flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-sm" style="background:{DONUT[0]}"></span>배당으로 나눠 줌 {notes.won(tot)}</li>'
                     f'<li class="flex items-center gap-1.5 mt-1"><span class="w-2.5 h-2.5 rounded-sm" style="background:{DONUT[6]}"></span>회사에 남김 {notes.won(max(ni - tot, 0))}</li>'
                     f'<li class="text-[11px] text-outline mt-1">{fin[0]}년 순이익 {notes.won(ni)} 가운데</li></ul></div>')  # fmt: skip
    top = max(r[1] for r in divs)
    bars = "".join(f'<div class="flex-1 flex flex-col items-center gap-1"><span class="text-[10px] text-on-surface-variant tabular-nums">{r[1]:,}</span>'
                   f'<span class="w-full max-w-[28px] rounded-t bg-secondary/80" style="height:{max(r[1] / top * 72, 2):.0f}px"></span>'
                   f'<span class="text-[10px] text-outline">{r[0]}</span></div>' for r in divs)  # fmt: skip
    y, dps, total, payout = divs[-1]
    text = (f"{y}년에는 한 주에 {dps:,}원을 현금으로 나눠 줬어요" + (f"(배당 총액 {notes.won(total)})" if total else "") + "."
            + (f" 번 돈(순이익)의 {payout:.1f}%를 배당으로 쓴 셈이에요(배당성향)." if payout else ""))  # fmt: skip
    return chapter("주주에게 돌려준 것", e(text),
                   ring_html + returns_html(divs, buys or []) + f'<div class="flex items-end gap-1 h-[110px] pt-2">{bars}</div>'
                   '<p class="font-label-micro text-label-micro text-outline">주당 현금배당금(보통주, 원) · 자료: DART 「배당에 관한 사항」</p>')  # fmt: skip


# 위험 낱말 → 같이 볼 숫자. 앞에서부터 처음 맞는 것 하나. 값은 재무표(최근 두 해)에서 코드가 나눈다
WATCH = ((r"가격|수급|공급|시황|수요|경기|업황|경쟁|원가|판매", "영업이익률", lambda f: f[2] / f[1] * 100 if f[1] and f[1] > 0 and f[2] is not None else None),
         (r"부채|차입|금리|유동성|자금|이자", "부채비율", lambda f: f[5] / f[4] * 100 if f[4] and f[4] > 0 and f[5] is not None else None),
         (r"발주|수주|투자 계획|소비량|정책|주문", "매출", None))  # fmt: skip  매출은 금액과 전년 대비 변화로


def watch(risk: str, fins: list[tuple], used: set | None = None) -> str:
    """fins = [(연도, 매출, 영업이익, 순이익, 자본, 부채)] 최근 해부터. used = 이미 붙인 숫자 — 같은 숫자를 위험마다 되풀이하지 않는다."""
    used = set() if used is None else used
    for pat, name, calc in WATCH:
        if calc is None:  # 매출 — 금액 + 전년 대비
            if re.search(pat, risk) and name not in used and fins and fins[0][1]:
                used.add(name)
                chg = f" · 전년보다 {(fins[0][1] / fins[1][1] - 1) * 100:+.1f}%" if len(fins) > 1 and fins[1][1] and fins[1][1] > 0 else ""
                return f'<span class="block text-[12px] text-outline">살펴볼 숫자: 매출 {notes.won(fins[0][1])} ({fins[0][0]}년{chg})</span>'
            continue
        now = calc(fins[0]) if fins else None
        if re.search(pat, risk) and now is not None and name not in used:
            used.add(name)
            was = f" · {fins[1][0]}년 {v:.1f}%" if len(fins) > 1 and (v := calc(fins[1])) is not None else ""
            return f'<span class="block text-[12px] text-outline">살펴볼 숫자: {name} {now:.1f}% ({fins[0][0]}년{was})</span>'
    return ""


def risk_block(biz: dict | None, fins: list[tuple] | None = None) -> str:
    if not biz or not biz.get("risks"):
        return ""
    used: set = set()
    items = "".join(f'<li class="flex gap-2"><span class="material-symbols-outlined text-tertiary text-[16px] mt-1" aria-hidden="true">error</span><span>{e(r)}{watch(r, fins or [], used)}</span></li>' for r in biz["risks"])
    return chapter("회사가 꼽은 위험", f'<ul class="flex flex-col gap-1.5">{items}</ul>',
                   '<p class="font-label-micro text-label-micro text-outline">회사가 사업보고서에 스스로 적은 위험이에요. 한장의 판단이 아니에요.'
                   + (' 「살펴볼 숫자」는 그 위험과 관련해 이 노트에 있는 숫자예요. 앞날을 말하는 게 아니에요.' if used else "") + '</p>')  # fmt: skip


def safe_url(u: str) -> str:
    return u if u.startswith(("https://", "http://", "/learn/")) else "#"


# --- 우리가 쓴 고정 풀이 (공시 내용을 지어내지 않는다 — 낱말·공시 종류의 뜻만) ---


EVENT_EXPLAIN = {
    "BUYBACK": "회사가 자기 주식을 사들이거나 없애기로 했어요. 시중에 도는 주식 수가 줄어요.",
    "DIVIDEND": "번 돈의 일부를 주주에게 나눠 주기로 했어요.",
    "EARNINGS": "회사가 매출·이익 같은 실적을 알렸어요.",
    "MAJOR_CONTRACT": "큰 판매·공급 계약을 맺었어요.",
    "RIGHTS_ISSUE": "새 주식을 팔아 돈을 모으기로 했어요. 주식 수가 늘어요.",
    "BONUS_ISSUE": "주주에게 주식을 무상으로 더 나눠 주기로 했어요.",
    "CB_BW": "나중에 주식으로 바꿀 수 있는 채권을 냈어요. 바뀌면 주식 수가 늘어요.",
    "LAWSUIT": "소송이 걸렸거나 판결이 났어요.",
    "MA": "다른 회사와 합치거나 사업·회사를 사고팔기로 했어요.",
    "HOLDER_CHANGE": "큰 주주의 지분이 바뀌었어요.",
    "CLINICAL": "신약 임상 시험 소식이에요.",
    "TRADING_HALT": "거래가 멈추거나 관리 대상이 됐어요.",
    "RUMOR": "언론 보도나 소문에 대해 회사가 답했어요.",
    "FRAUD": "임직원의 횡령·배임 혐의와 관련된 공시예요.",
    "SPLIT": "주식 한 주를 여러 주로 쪼개기로 했어요.",
    "REVERSE_SPLIT": "여러 주를 한 주로 합치거나 자본을 줄이기로 했어요.",
}
EVENT_SHORT = {"BUYBACK": "자사주", "DIVIDEND": "배당", "EARNINGS": "실적", "MAJOR_CONTRACT": "계약",
               "RIGHTS_ISSUE": "증자", "BONUS_ISSUE": "무상증자", "CB_BW": "전환사채", "LAWSUIT": "소송",
               "MA": "합병·인수", "HOLDER_CHANGE": "대주주", "CLINICAL": "임상", "TRADING_HALT": "거래정지·관리",
               "RUMOR": "보도 해명", "FRAUD": "횡령·배임", "SPLIT": "분할", "REVERSE_SPLIT": "병합", "OTHER": "기타"}  # fmt: skip
TIPS = {  # 주주를 위한 읽기 팁 — 이 달에 가장 많은 공시 종류에 맞춰
    "BUYBACK": ("자사주 취득 공시는 소각 여부까지 함께 확인해요", "사둔 주식을 없애야(소각) 시중에 도는 주식 수가 실제로 줄어요."),
    "DIVIDEND": ("배당 공시는 기준일을 함께 확인해요", "기준일에 주식을 갖고 있어야 배당을 받아요."),
    "EARNINGS": ("실적 공시는 '잠정'인지 확인해요", "잠정 실적은 나중에 확정치와 조금 달라질 수 있어요."),
    "MAJOR_CONTRACT": ("계약 공시는 회사 매출에 비한 크기를 봐요", "같은 금액이라도 회사 크기에 따라 무게가 달라요."),
    "RIGHTS_ISSUE": ("유상증자는 모은 돈을 어디에 쓰는지 봐요", "시설 투자인지 빚 갚기인지에 따라 뜻이 달라요."),
    "CB_BW": ("전환사채는 전환 가격을 함께 봐요", "주식으로 바뀌면 주식 수가 늘어 기존 주주 몫이 묽어질 수 있어요."),
}
TIP_DEFAULT = ("공시 원문은 DART에서 누구나 볼 수 있어요", "번호를 누르면 금융감독원 전자공시 원문이 열려요.")
FACT_SHORT = {"F1": "매출", "F2": "영업이익", "F3": "부채비율", "F4": "ROE"}
# 출처 번호는 읽기를 방해하지 않게 — 본문보다 작은 회색 위첨자 (사용자 10/7). 누르면 출처 창
CITE = "align-super ml-0.5 text-[9px] leading-none font-normal hover:text-on-surface-variant transition-colors"
# 출처 번호 색 — 누가 말한 것인지 (사용자 10/9 검토: 사실과 해석을 나눠 보이게). 아래 「작성 기준」에 같은 색으로 풀이
CITE_TONE = {"F": "text-primary/70", "D": "text-secondary/80", "I": "text-secondary/80", "N": "text-outline/70"}


def short_name(name: str) -> str:
    """달력 칩용 — 「SK하이닉스」→「SK」, 「삼성전자」→「삼성」."""
    m = re.match(r"[A-Za-z&]+", name)
    return m[0] if m else name[:2]


def clean_title(title: str, code: str) -> str:
    """「[기재정정]주요사항보고서(자기주식취득결정)」 → 「자기주식취득결정 (자사주 매입)」."""
    t = re.sub(r"^\[[^\]]*\]", "", title).strip()
    t = re.sub(r"^주요사항보고서\((.+)\)$", r"\1", t)
    ko = notes.EVENT_KO.get(code, "")
    return f"{t} ({ko})" if ko and ko not in t and code != "OTHER" else t


def sentence(s: dict, seen: set | None = None) -> str:
    """문장 + 시안의 출처 단추 [F1] — 누르면 출처 창이 열린다 (모든 문장에 원문 링크, 불변식 2).
    seen = 이 노트에서 이미 보인 숫자들 — 숫자가 모두 앞에서 나온 괄호는 다시 싣지 않는다(같은 숫자 되풀이, 사용자 10/9 검토)."""
    btns = "".join(f'<button aria-label="출처 {e(r)} 보기" class="{CITE} {CITE_TONE.get(r[:1], "text-outline/70")}" onclick="toggleCitation(\'{e(r)}\')" type="button">[{e(r)}]</button>'
                   for r in s["refs"])  # fmt: skip
    text = notes.mend(s["text"])
    if seen is not None:
        def once(m):
            nums = set(re.findall(r"\d[\d,.]*", m[1]))
            if nums and nums <= seen and re.search(r"[원%]", m[1]):  # 금액·비율 괄호만 — 「(2021~2025년)」 같은 기간은 둔다
                return ""
            seen.update(nums)
            return m[0]
        text = re.sub(r"\(([^()]*\d[^()]*)\)", once, text)
    return f"{soften(text)}{btns}"


# 문단 나누기 — 근거 사실이 다루는 질문이 바뀌면 새 문단 (한 문단에 질문 하나, 사용자 10/9 검토)
TOPIC = {"F1": "실적", "F2": "실적", "F5": "실적", "F6": "흐름", "F7": "사업", "F10": "업종", "F3": "살림", "F4": "살림",
         "F8": "올해", "F9": "올해", "F11": "사업", "F12": "살림", "F13": "올해", "F14": "살림", "F15": "사업", "F16": "전망", "F17": "살림", "F18": "살림"}  # fmt: skip


def paras(sents: list[dict], seen: set) -> str:
    groups: list[list[str]] = []
    last = None
    for x in sents:
        topic = next((TOPIC[r] for r in x["refs"] if r in TOPIC), last)
        if topic != last or not groups:
            groups.append([])
        groups[-1].append(sentence(x, seen))
        last = topic
    if len(groups) == 1:
        return " ".join(groups[0])
    return "".join(f'<p class="{"mt-space-sm" if i else ""}">{" ".join(g)}</p>' for i, g in enumerate(groups))


def soften(text: str) -> str:
    """괄호 속 숫자 보조 설명은 작고 회색으로 — 「(9.0조원 · 7,921억원)(영업이익률 8.8%)」 처럼 본문을 끊지 않게 (사용자 10/9).
    붙어 있는 괄호 둘은 하나로 잇는다. 글은 바꾸지 않는다(숫자·출처 그대로)."""
    text = re.sub(r"\)\s*\(", " · ", e(text))
    return re.sub(r"\(([^()]*)\)", r'<span class="text-[12px] text-outline">(\1)</span>', text)


def cite_data(facts: list[dict]) -> dict:
    """출처 창에 넣을 실제 값 — 시안의 가짜 설명 대신 코드가 만든 사실 문장과 원문 링크."""
    out = {}
    for f in facts:
        k = f["id"][0]
        rno = re.search(r"rcpNo=(\d+)", f["url"])
        out[f["id"]] = {
            "badge": f"[{f['id']}]",
            "title": "한장 읽기 팁 · 업종별로 읽기" if f["url"].startswith("/learn/") else {"F": "금융감독원 전자공시시스템 (DART) · 사업보고서",
                      "D": "금융감독원 전자공시시스템 (DART) · 공시",
                      "I": "금융감독원 전자공시시스템 (DART) · 지분 보고"}.get(k, f"{f.get('slots', {}).get('매체', '')} 기사"),
            "body": notes.reword(f["text"]),
            "meta": f"공시접수번호: {rno[1]}" if rno else f"기사 날짜: {f.get('slots', {}).get('날짜', '')}",
            "url": safe_url(f["url"]),
        }  # fmt: skip
    return out


def metrics(fins: list[tuple]) -> str:
    """주요 실적 한눈에 보기 — 매출·영업이익을 전년과 올해 막대 둘로 (같은 잣대: 둘 중 큰 값이 꽉 찬 막대).
    fins = [(연도, 매출, 영업이익, 순이익, 자본, 부채)] 최근 해부터. 전년이 없으면 그리지 않는다."""
    if len(fins) < 2:
        return ""
    (y, *now), (py, *was) = fins[0], fins[1]
    cells = []
    for label, k in (("매출 — 판 돈", 0), ("영업이익 — 본업으로 남긴 돈", 1)):
        cur, prev = now[k], was[k]
        if cur is None or prev is None:
            continue
        top = max(abs(cur), abs(prev)) or 1
        _, _, chg = notes.trend(cur, prev)
        tone = "text-secondary" if chg.startswith("+") or chg == "흑자 전환" else "text-tertiary"
        bar = lambda v, col, yr: (f'<div class="flex items-center gap-3 mt-2.5"><span class="w-9 text-[11px] text-outline tabular-nums">{yr}</span>'
                                  f'<span class="flex-1 h-2 rounded-full bg-surface-container overflow-hidden"><span class="block h-full rounded-full {col}" style="width:{max(v, 0) / top * 100:.1f}%"></span></span>'
                                  f'<span class="w-16 text-right text-[12px] tabular-nums {"text-tertiary" if v < 0 else "text-on-surface"}">{e(notes.won(v))}</span></div>')  # fmt: skip
        cells.append(f'<div class="py-1"><div class="flex items-baseline justify-between mb-0.5"><span class="font-label-micro text-label-micro text-on-surface-variant">{e(label)}</span>'
                     f'<span class="font-label-micro text-label-micro {tone} font-semibold">{e(chg)}</span></div>'
                     + bar(prev, "bg-outline-variant", py) + bar(cur, "bg-primary", y) + "</div>")  # fmt: skip
    if not cells:
        return ""
    return ('<div class="py-6 my-space-sm border-y border-outline-variant/30"><div class="flex justify-between items-center mb-4">'
            '<span class="font-label-regular text-label-regular text-on-surface font-semibold">주요 실적 한눈에 보기</span>'
            f'<span class="font-label-micro text-label-micro text-on-surface-variant">{py}년 → {y}년</span></div>'
            f'<div class="grid grid-cols-1 sm:grid-cols-2 gap-x-12 gap-y-6">{"".join(cells)}</div></div>')  # fmt: skip


FILLED = "font-variation-settings:'FILL' 1,'wght' 600"  # 꽉 찬 검은 그림 — 톱니바퀴 같은 인포그래픽 모양


def figure(f: dict | None) -> str:
    """읽기 팁 인포그래픽 — 상자·흰 바탕 없이 큰 검은 그림과 글. flow 는 휴대폰에서 세로·넓은 화면에서 가로로 (사용자 10/10)."""
    if not f:
        return ""
    head = (f'<figure class="my-space-xl"><figcaption class="mb-5 text-[13px] font-semibold tracking-wide text-outline">{e(f["title"])}</figcaption>')
    icon = lambda name, size: f'<span class="material-symbols-outlined {size} text-on-surface leading-none" style="{FILLED}" aria-hidden="true">{e(name)}</span>'
    if f["type"] == "flow":
        n = len(f["steps"])
        parts = []
        for k, (ic, t, d) in enumerate(f["steps"]):
            parts.append(f'<li class="flex items-start gap-4 lg:flex-1 lg:flex-col lg:items-center lg:text-center lg:gap-3">{icon(ic, "text-[44px] lg:text-[56px]")}'
                         f'<span class="flex flex-col pt-1 lg:pt-0"><b class="text-[15px] leading-[22px] text-on-surface"><span class="text-primary mr-1">{k + 1}</span>{e(t)}</b>'
                         + (f'<span class="text-[13px] leading-[19px] text-on-surface-variant mt-0.5">{e(d)}</span>' if d else "") + "</span></li>")
            if k < n - 1:
                parts.append('<li aria-hidden="true" class="pl-3 lg:pl-0 lg:pt-4 text-outline-variant"><span class="material-symbols-outlined text-[22px] lg:hidden">arrow_downward</span>'
                             '<span class="material-symbols-outlined text-[26px] hidden lg:inline">arrow_forward</span></li>')
        return head + f'<ol class="flex flex-col gap-2 lg:flex-row lg:items-start lg:gap-3">{"".join(parts)}</ol></figure>'
    if f["type"] == "compare":
        (i1, c1), (i2, c2) = f["cols"]
        top = ('<div class="grid grid-cols-[28%_1fr_1fr] lg:grid-cols-[22%_1fr_1fr] gap-3 items-end pb-3"><span></span>'
               + "".join(f'<span class="flex flex-col items-start gap-1.5">{icon(ic, "text-[40px] lg:text-[52px]")}<b class="text-[15px] text-on-surface">{e(c)}</b></span>'
                         for ic, c in ((i1, c1), (i2, c2))) + "</div>")  # fmt: skip
        rows = "".join(f'<div class="grid grid-cols-[28%_1fr_1fr] lg:grid-cols-[22%_1fr_1fr] gap-3 py-2.5 text-[14px] leading-[21px]">'
                       f'<span class="text-on-surface-variant">{e(k)}</span><span class="text-on-surface">{e(x)}</span><span class="text-on-surface">{e(y)}</span></div>'
                       for k, x, y in f["rows"])  # fmt: skip
        return head + top + f'<div class="divide-y divide-surface-container-high">{rows}</div></figure>'
    if f["type"] == "equation":
        rows = "".join(f'<div class="flex items-baseline flex-wrap gap-x-2 gap-y-1 py-1"><span class="text-[15px] text-on-surface">{e(x)}</span><span class="text-[18px] text-outline">{e(op)}</span>'
                       f'<span class="text-[15px] text-on-surface">{e(y)}</span><span class="text-[18px] text-outline">=</span><b class="text-[20px] text-primary">{e(z)}</b></div>'
                       for x, op, y, z in f["rows"])  # fmt: skip
        return (head + f'<div class="flex items-center gap-5">{icon("calculate", "text-[56px] lg:text-[72px]")}'
                f'<div class="grid grid-cols-1 lg:grid-cols-2 gap-x-10 gap-y-1 flex-1">{rows}</div></div></figure>')
    note = f'<p class="mt-3 text-[13px] leading-[19px] text-on-surface-variant">{e(f["note"])}</p>' if f.get("note") else ""
    if f["type"] == "cards":  # 그림 카드 — 휴대폰 두 칸, 넓은 화면 네 칸
        items = "".join(f'<div class="flex flex-col gap-2">{icon(ic, "text-[40px] lg:text-[48px]")}<b class="text-[15px] leading-[21px] text-on-surface">{e(t)}</b>'
                        f'<span class="text-[13px] leading-[19px] text-on-surface-variant">{e(d)}</span></div>' for ic, t, d in f["items"])  # fmt: skip
        return head + f'<div class="grid grid-cols-2 lg:grid-cols-4 gap-x-5 gap-y-7">{items}</div>{note}</figure>'
    if f["type"] == "ladder":  # 먼저 받는 차례 — 왼쪽 맞춤 + 아래 화살표, 번호·배경·들여쓰기 없이 (사용자 10/10)
        arrow = '<span class="material-symbols-outlined text-[22px] text-outline-variant pl-2" aria-hidden="true">arrow_downward</span>'
        rows = arrow.join(f'<div class="flex items-center gap-3">{icon(ic, "text-[36px] lg:text-[44px]")}'
                          f'<span class="flex flex-col min-w-0"><b class="text-[15px] leading-[22px] text-on-surface">{e(t)}</b>'
                          f'<span class="text-[13px] leading-[19px] text-on-surface-variant">{e(d)}</span></span></div>'
                          for ic, t, d in f["steps"])  # fmt: skip
        return head + f'<div class="flex flex-col gap-1">{rows}</div>{note}</figure>'
    if f["type"] == "timeline":  # 때 — 휴대폰 세로 줄, 넓은 화면 가로 줄
        pts = "".join(f'<li class="relative flex gap-4 pb-6 last:pb-0 lg:flex-1 lg:flex-col lg:items-center lg:text-center lg:pb-0 lg:gap-2">'
                      f'<span class="w-14 shrink-0 pt-1 text-[13px] font-bold text-primary lg:w-auto lg:pt-0">{e(w)}</span>'
                      f'<span class="relative z-10 w-3.5 h-3.5 mt-1.5 shrink-0 rounded-full bg-primary ring-4 ring-surface lg:mt-0"></span>'
                      f'<span class="flex flex-col items-start lg:items-center gap-1">{icon(ic, "text-[34px] lg:text-[44px]")}<b class="text-[14px] text-on-surface">{e(t)}</b>'
                      f'<span class="text-[12px] leading-[17px] text-on-surface-variant">{e(d)}</span></span></li>' for w, ic, t, d in f["points"])  # fmt: skip
        line = '<span aria-hidden="true" class="absolute left-[78px] top-2 bottom-2 w-px bg-primary/30 lg:left-0 lg:right-0 lg:top-[38px] lg:bottom-auto lg:w-auto lg:h-px"></span>'
        return head + f'<ol class="relative flex flex-col lg:flex-row lg:gap-4">{line}{pts}</ol>{note}</figure>'
    if f["type"] == "bars":  # 막대 — 가장 큰 값을 꽉 찬 길이로
        top = max(v for _, _, v in f["items"]) or 1
        rows = "".join(f'<div class="flex items-center gap-3 py-1.5">{icon(ic, "text-[30px]")}<span class="w-20 shrink-0 text-[14px] text-on-surface">{e(t)}</span>'
                       f'<span class="flex-1 h-3 rounded-full bg-surface-container overflow-hidden"><span class="block h-full rounded-full bg-primary" style="width:{max(v / top * 100, 3):.0f}%"></span></span>'
                       f'<b class="w-12 text-right text-[14px] tabular-nums text-on-surface">{v}{e(f.get("unit", ""))}</b></div>' for ic, t, v in f["items"])  # fmt: skip
        return head + rows + note + "</figure>"
    if f["type"] == "lines":  # 꺾은선 — 같은 출발점에서 갈라지는 모양
        xs, series = f["x"], f["series"]
        vals = [v for _, ys in series for v in ys]
        lo, hi = min(vals) - 5, max(vals) + 5
        w, h, pad = 320, 150, 28
        px = lambda k: pad + k * (w - 2 * pad) / (len(xs) - 1)
        py = lambda v: 12 + (hi - v) / (hi - lo) * (h - 36)
        cols = ("#154539", "#F4806A")
        top = [max(ys[k] for _, ys in series) for k in range(len(xs))]  # 높은 쪽 숫자는 위, 낮은 쪽은 아래 — 겹치지 않게
        first = [next(ys for _, ys in series if ys[k] == top[k]) for k in range(len(xs))]  # 같은 값은 한 번만
        lines = "".join(f'<polyline fill="none" stroke="{c}" stroke-width="3" stroke-linejoin="round" points="{" ".join(f"{px(k):.1f},{py(v):.1f}" for k, v in enumerate(ys))}"/>'
                        + "".join(f'<circle cx="{px(k):.1f}" cy="{py(v):.1f}" r="4" fill="{c}"/><text x="{px(k):.1f}" y="{py(v) + (18 if v < top[k] else -9):.1f}" text-anchor="middle" font-size="12" font-weight="700" fill="{c}">{v}</text>'
                                  for k, v in enumerate(ys) if v != top[k] or ys is first[k]) for (_, ys), c in zip(series, cols))  # fmt: skip
        ticks = "".join(f'<text x="{px(k):.1f}" y="{h - 4}" text-anchor="middle" font-size="11" fill="#717975">{e(x)}</text>' for k, x in enumerate(xs))
        legend = "".join(f'<span class="flex items-center gap-1.5"><span class="w-4 h-1 rounded-full" style="background:{c}"></span>{e(n)}</span>' for (n, _), c in zip(series, cols))
        return (head + f'<div class="flex gap-4 mb-2 text-[13px] text-on-surface">{legend}</div>'
                f'<svg viewBox="0 0 {w} {h}" class="w-full max-w-[520px]" role="img" aria-label="{e(f["title"])}">{lines}{ticks}</svg>{note}</figure>')
    if f["type"] == "stack":  # 나눠 쌓은 막대 — 전체 하나를 몫으로 나눈다
        total = sum(v for _, v, _ in f["parts"]) or 1
        bar = "".join(f'<span class="h-full flex items-center justify-center text-[13px] font-bold text-on-primary" style="width:{v / total * 100:.0f}%;background:{c}">{v}</span>' for _, v, c in f["parts"])
        keys = "".join(f'<span class="flex items-center gap-1.5"><span class="w-3 h-3 rounded-sm" style="background:{c}"></span>{e(t)}</span>' for t, _, c in f["parts"])
        return (head + f'<div class="flex items-center gap-4">{icon("account_balance", "text-[44px] lg:text-[56px]")}<div class="flex-1 flex flex-col gap-2">'
                f'<b class="text-[14px] text-on-surface">{e(f["total"])}</b><div class="h-9 w-full rounded-lg overflow-hidden flex">{bar}</div>'
                f'<div class="flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-on-surface-variant">{keys}</div></div></div>{note}</figure>')
    return ""


WHO_ICONS = ("badge", "account_balance")  # 임원 거래·기관 지분 — 노트의 「임원·큰손은 어떻게 움직였나요?」(#who)로 간다. 그 밖은 「요즘 생긴 일」(#recent)


def md(made: str) -> str:
    """「2026-10-08T07:00」 → 「10월 8일」 — 노트를 쓴(고친) 날."""
    return f"{int(made[5:7])}월 {int(made[8:10])}일" if re.match(r"\d{4}-\d{2}-\d{2}", made or "") else ""


NEWS_TITLES = ("최근 소식", "이번 주 소식", "요즘 무슨")  # 공시·소식 절 — 새 이름과 옛 노트 이름


def redone(week: str, made: str) -> str:
    """주 중간에 다시 쓴 노트면 「 · 10월 8일 고침」 — 월요일에 쓴 그대로면 빈 글."""
    d = date.fromisoformat(made[:10]) if re.match(r"\d{4}-\d{2}-\d{2}", made or "") else None
    return f" · {d.month}월 {d.day}일 고침" if d and d.isoformat() > week else ""


def owners_block(owners: tuple | None) -> str:
    """노트 맨 밑 — 이 종목을 가진 유명 투자자(미국 13F)·기관(국내 5% 보고). 누르면 그 투자자의 포트폴리오로."""
    if not owners or not owners[2]:
        return ""
    title, note, rows = owners
    items = "".join(
        f'<a href="{e(href)}" class="py-3 flex items-center gap-3">{face}'
        f'<span class="flex flex-col min-w-0 flex-1"><span class="text-[15px] font-semibold text-on-surface truncate">{e(name)}</span>'
        f'<span class="text-[12px] text-on-surface-variant">{e(detail)}</span></span>'
        '<span class="material-symbols-outlined text-outline text-[18px]">chevron_right</span></a>' for name, href, face, detail in rows)  # fmt: skip
    return ('<section class="mb-12 flex flex-col gap-space-sm"><div class="flex items-center gap-2"><span class="w-2 h-2 rounded-full bg-primary"></span>'
            f'<h3 class="font-headline-md text-headline-md text-on-surface">{e(title)}</h3></div>'
            f'<div class="flex flex-col divide-y divide-surface-container-high/70">{items}</div>'
            f'<p class="font-label-micro text-label-micro text-outline leading-normal">{e(note)}</p></section>')  # fmt: skip


def render_note(name: str, ticker: str, week: str, body: dict, writer: str, facts: list[dict] | None = None,
                industry: str | None = None, initial: str = "", survey: str = "", made: str = "", homepage: str | None = None,
                stats: tuple[int, int, bool] = (0, 0, False), regram: str = "",
                prices: list | None = None, report: dict | None = None) -> str:
    """report = {"divs": [(연도, 주당배당, 총액, 배당성향)], "biz": 요약, "rno": 사업보고서}."""
    report = report or {}
    """stats = (이 주 노트를 연 횟수, 좋아요 수, 내가 눌렀나)."""
    facts = facts or []
    head = ('<header class="fixed top-0 w-full z-50 bg-surface/90 backdrop-blur-xl pt-safe"><div class="h-14 max-w-[480px] lg:max-w-[760px] mx-auto px-margin flex items-center justify-between"><div class="flex items-center gap-space-sm"><button class="w-11 h-11 flex items-center justify-center text-on-surface hover:text-primary transition-colors -ml-space-xs" onclick="location.href=\'/\'"><span class="material-symbols-outlined text-[22px]">arrow_back</span></button><h1 class="font-headline-sm text-headline-sm text-on-surface tracking-tight truncate max-w-[200px]">Note</h1></div><div class="flex items-center gap-space-sm">'
            + avatar(initial) + '</div></div></header>')  # fmt: skip
    parts = [
        # 머리 — 로고·이름 한 줄, 업종 · 날짜 · 읽음 한 줄 (글자를 줄였다, 사용자 10/8)
        f'<header class="mt-space-sm mb-space-lg"><div class="flex items-center gap-2.5">{logo(name, homepage, "w-10 h-10")}'
        f'<h2 class="font-display-editorial text-display-editorial text-on-surface font-semibold tracking-tight">{e(name)}</h2></div>'
        f'<p class="mt-1.5 flex items-center flex-wrap gap-x-2 gap-y-1 text-[12px] text-outline">{industry_chip(industry)}<span>{e(" · ".join(x for x in (md(made), f"읽음 {stats[0]:,}") if x))}</span></p></header>',
        price_chart(prices) if prices else "",
        f'<aside class="my-space-xl lg:my-10 text-center">{RULE}<p class="py-space-lg px-space-md font-body-reading-strong font-bold text-[18px] leading-[30px] lg:text-[20px] lg:leading-[34px] text-primary">{e(notes.mend(body["headline"]))}</p>{RULE_FLIP}</aside>',
    ]  # fmt: skip
    recent = ""
    if report.get("events"):  # 요즘 생긴 일 — 내 종목 카드에 뜬 그 문구들. 「좋게 볼 점과 주의해서 볼 점」 아래에 놓는다 (사용자 10/11)
        rows = "".join(
            f'<a href="{"#who" if icon in WHO_ICONS else e(href)}" class="py-3 flex items-start gap-2.5"><span class="material-symbols-outlined text-[18px] mt-0.5 {tint}">{icon}</span>'
            f'<span class="min-w-0 flex-1 flex flex-col gap-0.5"><span class="text-[15px] leading-[21px] font-semibold text-on-surface">{e(what)}</span>'
            f'<span class="text-[13px] leading-[19px] text-on-surface-variant">{e(sub)}</span></span>'
            f'<span class="shrink-0 pt-0.5 text-[12px] text-outline tabular-nums">{e(when)}</span></a>'
            for _, icon, tint, _, _, what, sub, when, href, _ in report["events"][:5])  # fmt: skip
        recent = ('<section id="recent" class="scroll-mt-20 mb-12"><div class="flex items-center gap-2"><span class="w-2 h-2 rounded-full bg-primary"></span>'
                  '<h3 class="font-headline-md text-headline-md text-on-surface">요즘 생긴 일</h3></div>'
                  f'<div class="mt-1 flex flex-col divide-y divide-surface-container-high/70">{rows}</div></section>')  # fmt: skip
    seen: set = set()  # 이 노트에서 이미 보인 숫자 — 뒤에서 같은 괄호를 되풀이하지 않게
    if body.get("summary"):
        parts.append('<section class="mb-12 pl-space-md py-1 border-l-2 border-primary/60"><div class="flex items-center gap-1.5 mb-1"><span class="material-symbols-outlined text-primary text-[18px]">auto_stories</span><span class="font-label-micro text-label-micro uppercase tracking-wider text-primary font-bold">한 장 요약</span></div>'
                     f'<p class="font-body-reading text-body-reading text-on-surface leading-relaxed">{" ".join(sentence(s, seen) for s in body["summary"])}</p></section>')  # fmt: skip
    parts.append(business_block(report.get("biz"), report.get("rno")))
    nd = sum(f["id"][0] == "D" for f in facts)
    good_d, bad_d = sum(f["id"][0] == "D" and f["tone"] == 1 for f in facts), sum(f["id"][0] == "D" and f["tone"] == -1 for f in facts)
    for sec in body["sections"]:
        text = paras(sec["sentences"], seen)
        extra = ""
        if sec["title"].startswith("회사 사정"):
            extra = metrics(report.get("fins") or []) + money_blocks(report.get("fin"), report.get("mid"))
        elif sec["title"].startswith(NEWS_TITLES):  # 「이번 주 소식」(공시+소식) · 옛 노트의 「요즘 무슨 일이 있었나요?」
            right = (f"좋게 볼 점 {good_d}" + (f" · 주의해서 볼 점 {bad_d}" if bad_d else "")) if good_d or bad_d else "분류 완료"
            extra = ('<div class="py-space-sm flex items-center justify-between border-t border-outline-variant/30 mt-space-xs"><div class="flex items-center gap-space-sm"><span class="material-symbols-outlined text-secondary text-[18px]">assignment_turned_in</span><div class="flex items-center gap-2">'
                     f'<span class="font-label-regular text-label-regular text-on-surface font-medium">최근 주요 공시 {nd}건 집계</span><span class="font-label-micro text-label-micro text-on-surface-variant">· DART 기준 자동 분류</span></div></div>'
                     f'<span class="font-label-micro text-label-micro text-secondary font-semibold">{e(right)}</span></div>'
                     + (('<div class="pt-space-sm pb-1 flex flex-col gap-1.5"><div class="font-label-micro text-label-micro text-outline font-semibold uppercase">언론 키워드 흐름</div><div class="flex flex-wrap gap-2">'
                         + "".join(f'<span class="py-0.5 text-on-surface-variant text-label-micro font-label-micro">{e(k)}</span>' for k in body["keywords"]) + "</div></div>")
                        if body.get("keywords") else "")
                     + '<p class="font-label-micro text-label-micro text-outline leading-normal">소식은 회사 뉴스룸이 RSS 로 내보낸 제목·요약문만 보고 한장이 새로 쓴 글이에요. 기사 본문은 받지 않아요. 번호를 누르면 원문이 열려요.</p>'
                     # 언론 기사는 쓸 권리가 없어 싣지 않는다(data-rights §5.2) — 대신 검색 결과로 가는 길만. 데이터를 가져오지 않는 링크는 복제·전송이 아니다
                     + f'<a class="font-label-regular text-label-regular text-primary underline" target="_blank" rel="noopener" href="https://search.naver.com/search.naver?where=news&amp;sort=1&amp;query={quote(name)}">'
                     f'{e(name)} 최근 뉴스 찾아보기 (네이버 뉴스 검색으로 이동) →</a>')  # fmt: skip
        elif sec["title"].startswith("임원·큰손"):
            extra = ('<p class="font-label-micro text-label-micro text-outline leading-normal">임원 보고에는 회사에서 받은 주식(보상)도 들어가요. '
                     "누가 늘리고 줄였는지는 사실일 뿐, 따라 사고팔라는 뜻이 아니에요.</p>")  # fmt: skip
        parts.append(chapter(sec["title"], text, extra, "who" if sec["title"].startswith("임원·큰손") else ""))
        if sec["title"].startswith(NEWS_TITLES):
            parts.append(dividend_block(report.get("divs", []), report.get("fin"), report.get("buys")))
    if not any(s["title"].startswith(NEWS_TITLES) for s in body["sections"]):
        parts.append(dividend_block(report.get("divs", []), report.get("fin"), report.get("buys")))
    parts.append(risk_block(report.get("biz"), report.get("fins")))

    def filled(key):  # 옛 노트의 「분류된 것 없음」 자리 채움 문장도 빈 칸으로 본다
        return [] if body.get(f"{key}_title") == "분류된 것 없음" else body.get(key) or []

    if filled("good") or filled("concern"):
        def side(label, title, items, bar, chip, ink):
            if not items:
                return ""
            return (f'<div class="pl-space-md py-1 border-l-2 {bar} flex flex-col gap-1"><div class="flex items-center gap-1.5">'
                    f'<span class="px-2 py-0.5 rounded text-label-micro font-label-micro font-semibold {chip}">{label}</span>'
                    f'<span class="font-label-regular text-label-regular {ink} font-semibold">{e(title)}</span></div>'
                    f'<p class="font-body-reading text-body-reading text-on-surface leading-relaxed">{" ".join(sentence(s, seen) for s in items)}</p></div>')  # fmt: skip
        parts.append('<section class="mb-12 flex flex-col gap-space-md"><div class="flex items-center gap-2"><span class="w-2 h-2 rounded-full bg-primary"></span><h3 class="font-headline-md text-headline-md text-on-surface">좋게 볼 점과 주의해서 볼 점</h3></div>'
                     + side("좋게 볼 점", body.get("good_title", ""), filled("good"), "border-secondary/60", "bg-secondary-container text-on-secondary-container", "text-secondary")
                     + side("주의해서 볼 점", body.get("concern_title", ""), filled("concern"), "border-tertiary/60", "bg-tertiary-fixed text-on-tertiary-fixed-variant", "text-tertiary")
                     + '<span class="font-label-micro text-label-micro text-outline leading-normal pt-1">좋게 볼 점·주의해서 볼 점은 코드가 정한 기준으로 나눴어요. 좋고 나쁨의 결론이 아니라 살펴볼 거리예요. 기준은 매출·영업이익 증감, 부채비율, ROE, 공시 종류. <a class="underline" href="/method">기준 보기</a></span></section>')  # fmt: skip
    parts.append(recent)
    src = "기사·공시·재무" if any(f["id"][0] == "N" for f in facts) else "공시·재무"
    how = (f"{src}에서 코드가 뽑은 사실을 바탕으로 AI가 문장을 다듬었어요. 숫자는 코드가 원문과 대조했어요."
           if writer.startswith("llm") else f"{src}에서 코드가 뽑은 사실을 그대로 옮겼어요.")  # fmt: skip
    if any("sec.gov" in f.get("url", "") for f in facts):  # 미국 회사 — 원문은 SEC, 금액은 달러(원화는 한국은행 환율로 코드가 곱함)
        how += " 미국 회사라 원문은 미국 증권거래위원회(SEC) 공시예요. 금액은 달러가 먼저, 원화는 한국은행 환율로 계산해 괄호에 적었어요."
    views, likes, liked = stats
    faces = "".join('<span class="w-7 h-7 rounded-full bg-surface-container-high border-2 border-surface flex items-end justify-center overflow-hidden -ml-2 first:ml-0">'
                    '<span class="material-symbols-outlined text-outline text-[22px] translate-y-1" style="font-variation-settings: \'FILL\' 1;">person</span></span>'
                    for _ in range(min(likes, 3)))  # fmt: skip  누가 눌렀는지는 보여주지 않는다 — 모양만
    parts.append(f'<div class="mb-space-lg flex items-center justify-end gap-space-md"><form method="post" action="/like" class="flex items-center gap-space-sm"><input type="hidden" name="t" value="{e(ticker)}"><input type="hidden" name="w" value="{e(week)}">'
                 f'<button type="submit" aria-pressed="{"true" if liked else "false"}" aria-label="좋아요{" 취소" if liked else ""}" class="w-10 h-10 rounded-full flex items-center justify-center border {"border-tertiary/40 bg-tertiary-fixed/50" if liked else "border-outline-variant/60"} transition-colors">'
                 f'<span class="material-symbols-outlined text-[20px] {"text-tertiary" if liked else "text-outline"}" style="font-variation-settings: \'FILL\' {1 if liked else 0};">favorite</span></button>'
                 f'<span class="flex items-center">{faces}</span><span class="font-label-regular text-label-regular text-on-surface-variant font-semibold">좋아요 {likes:,}개</span></form>{regram}</div>')  # fmt: skip
    parts.append(owners_block(report.get("owners")))
    parts.append(survey)
    parts.append('<footer class="pt-space-lg pb-space-lg mt-space-sm border-t border-outline-variant/40 flex flex-col gap-space-sm"><div class="flex items-center gap-1.5 text-on-surface font-headline-sm text-headline-sm font-semibold"><span class="material-symbols-outlined text-primary text-[20px]">verified</span><span class="">작성 기준 및 검증 안내</span></div>'
                 f'<p class="font-body-compact text-body-compact text-on-surface-variant leading-relaxed">{how} 번호 색은 누가 말한 것인지 알려줘요. <span class="text-primary">[F]</span> 재무제표로 한장이 계산 · <span class="text-secondary">[D]·[I]</span> 회사·주주가 낸 공시 · <span class="text-outline">[N]</span> 언론 기사. 작은 번호를 누르면 금융감독원 전자공시(DART){"나 기사" if src.startswith("기사") else ""} 원문이 열려요. <a class="text-primary underline" href="/method">계산 방법</a></p>'
                 '<div class="pt-1"><p class="font-label-regular text-label-regular text-on-surface leading-relaxed font-medium">사라·팔아라는 의견도, 목표주가도, 앞으로의 예측도 없어요. 투자 판단은 본인이 해요.</p></div></footer>')  # fmt: skip
    dialog = ('<div class="fixed inset-0 z-50 bg-on-surface/40 backdrop-blur-sm hidden items-end justify-center px-margin pb-6" id="citation-dialog" onclick="closeCitation(event)"><div class="bg-surface-container-lowest w-full max-w-[440px] rounded-2xl p-space-lg shadow-xl flex flex-col gap-space-sm" onclick="event.stopPropagation()"><div class="flex items-center justify-between"><div class="flex items-center gap-2"><span class="px-2 py-0.5 rounded font-citation-ref text-citation-ref bg-primary-fixed text-on-primary-fixed font-bold" id="citation-badge"></span><span class="font-label-regular text-label-regular font-bold text-on-surface" id="citation-title"></span></div><button class="w-8 h-8 rounded-full flex items-center justify-center text-on-surface-variant hover:bg-surface-container" onclick="hideCitation()" type="button"><span class="material-symbols-outlined text-[20px]">close</span></button></div><div class="font-body-compact text-body-compact text-on-surface-variant leading-relaxed" id="citation-body"></div><div class="flex items-center justify-between pt-2"><span class="font-label-micro text-label-micro text-outline font-mono" id="citation-meta"></span><a class="inline-flex items-center gap-1 font-label-regular text-label-regular text-primary font-semibold hover:underline" href="#" id="citation-link" rel="noopener noreferrer" target="_blank">원문 확인<span class="material-symbols-outlined text-[14px]">open_in_new</span></a></div></div></div>'
              # JSON 안의 </script> 를 막으려고 < 를 < 로
              "<script>const citations = " + json.dumps(cite_data(facts), ensure_ascii=False).replace("<", "\\u003c") + ";"
              "function toggleCitation(id){const d=citations[id];if(!d)return;document.getElementById('citation-badge').innerText=d.badge;document.getElementById('citation-title').innerText=d.title;document.getElementById('citation-body').innerText=d.body;document.getElementById('citation-meta').innerText=d.meta;document.getElementById('citation-link').href=d.url;const g=document.getElementById('citation-dialog');g.classList.remove('hidden');g.classList.add('flex');}"
              "function hideCitation(){const g=document.getElementById('citation-dialog');g.classList.add('hidden');g.classList.remove('flex');}"
              "function closeCitation(ev){if(ev.target.id==='citation-dialog')hideCitation();}</script>")  # fmt: skip
    inner = (head + '<main class="flex flex-col relative w-full max-w-[480px] lg:max-w-[760px] mx-auto pt-14 pb-safe bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-space-xl">'
             + "".join(parts) + dialog + "</div></main>")  # fmt: skip
    if report.get("us"):
        inner = us_words(inner)
    return page(name, "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)


US_WORDS = (  # 노트 화면의 국내(DART) 안내 → 미국(SEC) 안내. 노트 본문(AI 글)은 건드리지 않는다
    (re.compile(r"회사가 낸 \d+년 사업보고서를 요약했어요"), "회사가 SEC 에 낸 최근 연차 보고서(10-K)를 요약했어요"),
    (re.compile(r"· DART 기준 자동 분류"), "· SEC 8-K 번호로 자동 분류"),
    (re.compile(r"임원 보고에는 회사에서 받은 주식\(보상\)도 들어가요\. 누가 늘리고 줄였는지는"),
     "미국은 시장에서 실제로 사고판 거래만 셌어요(회사에서 받은 보상 주식은 뺐어요). 누가 사고팔았는지는"),
    (re.compile(r"회사가 사업보고서에 스스로 적은 위험"), "회사가 연차 보고서(10-K)에 스스로 적은 위험"),
    (re.compile(r"금융감독원 전자공시\(DART\) 원문이 열려요"), "미국 증권거래위원회(SEC) 공시 원문이 열려요"),
    (re.compile(r"소식은 회사 뉴스룸이 RSS 로 내보낸 제목·요약문만 보고 한장이 새로 쓴 글이에요\. 기사 본문은 받지 않아요\. "), ""),
)


def us_words(html_: str) -> str:
    for pat, new in US_WORDS:
        html_ = pat.sub(new, html_)
    return html_


FLAG = {"KR": "한", "US": "미"}  # 국기 이모지는 윈도우에서 「KR」 글자로 나와서 쓰지 않는다
CHIP = "block mt-0.5 lg:mt-1 px-0.5 lg:px-1.5 py-0.5 lg:py-1 rounded text-[9px] lg:text-[12px] font-semibold leading-tight tracking-tighter lg:tracking-normal truncate"  # 캘린더 칸 칩 — 한 줄, 넘치면 …
AHEAD_SHORT = {"EARNINGS": "실적", "AGM": "주총", "DIVIDEND": "배당", "OTHER": "IR"}  # 달력 칸이 좁아 한 낱말로
TONE_TAG = {1: ("긍정", "bg-secondary-fixed/70 text-on-secondary-fixed-variant"),
            -1: ("부정", "bg-tertiary-fixed text-on-tertiary-fixed-variant"),
            0: ("중립", "bg-surface-container text-on-surface-variant")}  # fmt: skip
