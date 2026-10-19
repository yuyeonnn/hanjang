"""그림 — 막대·도넛·꺾은선 (SVG 를 글자로 만든다)."""

import json

from hanjang import gurus, notes, sources
from hanjang.ui import e


DONUT = ("#154539", "#2a5649", "#40695c", "#5b8172", "#7b9a8d", "#9db5aa", "#c0d1c9", "#e1e9e5")  # 진한 초록부터 — 한장 색


def groups(labels: list[str | None], w: list[float]) -> list[tuple[str, tuple[float, int]]]:
    """업종별 (합, 곳 수) — 큰 7개 + 나머지는 기타 하나로."""
    cnt: dict[str, list] = {}
    for x, v in zip(labels, w):
        k = cnt.setdefault(x or "기타", [0, 0])
        k[0] += v
        k[1] += 1
    top = sorted(((k, v) for k, v in cnt.items() if k != "기타"), key=lambda kv: -kv[1][0])[:7]
    rest = [sum(v) for v in zip(*(cnt[k] for k in cnt if k not in dict(top)))] or [0, 0]
    return top + ([("기타", rest)] if rest[1] else [])


def bars(labels: list[str | None], weights: list[float], unit: str = "종목", note: str = "") -> str:
    """업종 — 가로로 긴 막대 하나를 비율대로 나누고, 밑에 두 줄씩 이름. 도넛보다 크기 차이가 한눈에 (사용자 10/10)."""
    if not labels:
        return ""
    parts, total = groups(labels, weights), sum(weights) or 1
    segs = "".join(f'<span class="h-full" style="width:{v / total * 100:.2f}%;background:{col}" title="{e(k)} {v / total * 100:.0f}%"></span>'
                   for (k, (v, _)), col in zip(parts, DONUT))  # fmt: skip
    keys = "".join(f'<li class="flex items-center gap-2 min-w-0"><span class="w-2.5 h-2.5 rounded-sm shrink-0" style="background:{col}"></span>'
                   f'<span class="flex-1 text-[13px] text-on-surface truncate">{e(k)}</span>'
                   f'<span class="text-[13px] font-semibold text-on-surface tabular-nums">{v / total * 100:.0f}%</span>'
                   f'<span class="hidden sm:inline w-9 text-right text-[11px] text-outline tabular-nums">{n}{unit}</span></li>'
                   for (k, (v, n)), col in zip(parts, DONUT))  # fmt: skip
    return ('<section class="mt-space-xl"><h2 class="font-headline-sm text-headline-sm text-on-surface">어떤 업종에 많이 가졌나</h2>'
            f'<div class="mt-3 flex h-2.5 w-full rounded-full overflow-hidden gap-[2px] bg-surface">{segs}</div>'  # 막대는 얇게 (사용자 10/10: 조금만 줄여)
            f'<ul class="mt-4 grid grid-cols-2 gap-x-5 gap-y-2.5">{keys}</ul>'
            + (f'<p class="mt-3 text-[11px] text-outline">{e(note)}</p>' if note else "") + "</section>")  # fmt: skip


def pie(items: list[tuple[str, float]], title: str = "가장 많이 가진 종목", n: int = 5) -> str:
    """포트폴리오 파이 — 금액이 큰 n 종목만(기타 없이). 원은 가운데, 양옆에 반듯한 이름 목록(사용자 10/10).
    오른쪽 반의 조각은 오른쪽 목록(왼쪽 정렬), 왼쪽 반은 왼쪽 목록(오른쪽 정렬). 이름은 자기 조각 높이에 — 선이 거의 수평(사용자 10/10).
    겹치면 위아래로 비킨다. 조각에서 이름 옆 색 네모까지 곧은 선 — 글자는 HTML 이라 위치를 그린 뒤에 PIE_LINES 가 재서 긋는다(화면 크기가 바뀌면 다시).
    items = [(이름, 금액)] 큰 순. 13F 금액은 한 사람·한 기관의 돈이라 더하면 포트폴리오 비중이다."""
    import math

    total = sum(v for _, v in items)
    if not items or total <= 0:
        return ""
    # 기타는 그리지 않는다 — 상위 n 종목끼리 원을 나누고, 글자는 전체 중 비중 그대로(사용자 10/10)
    parts = [(k, v / total * 100) for k, v in items[:n]]
    cols, shown = DONUT, sum(p for _, p in parts)
    slices, sides, a = [], {True: [], False: []}, -math.pi * parts[0][1] / shown  # 가장 큰 조각을 3시 방향 가운데로
    for (k, pct), col in zip(parts, cols):
        b = a + pct / shown * 2 * math.pi
        x1, y1, x2, y2 = 50 + 48 * math.cos(a), 50 + 48 * math.sin(a), 50 + 48 * math.cos(b), 50 + 48 * math.sin(b)
        slices.append(f'<circle cx="50" cy="50" r="48" fill="{col}"/>' if pct >= shown - 0.01 else
                      f'<path d="M50 50 L{x1:.2f} {y1:.2f} A48 48 0 {1 if b - a > math.pi else 0} 1 {x2:.2f} {y2:.2f} Z" fill="{col}" stroke="#ffffff" stroke-width="1"/>')  # fmt: skip
        m = (a + b) / 2
        sides[math.cos(m) >= 0].append((math.sin(m), k, pct, col, m))
        a = b

    def column(right: bool) -> str:
        # 휴대폰·태블릿은 이름 밑에 %(같은 크기), 컴퓨터 화면이면 한 줄 — 긴 이름은 칸 안에서 말줄임
        rows = "".join(
            f'<li class="absolute inset-x-0 flex items-start gap-1.5 {"" if right else "flex-row-reverse"}" style="top:calc({50 + 48 * math.sin(m):.1f}% - 10px)">'
            f'<span data-ang="{m:.4f}" class="w-2.5 h-2.5 mt-[5px] rounded-sm shrink-0" style="background:{col}"></span>'
            f'<span class="min-w-0 flex flex-col lg:flex-row lg:gap-1.5 {"items-start" if right else "items-end"}">'
            f'<span class="max-w-full text-[13px] leading-5 text-on-surface-variant truncate">{e(k)}</span>'
            f'<span class="text-[13px] leading-5 font-semibold text-on-surface tabular-nums shrink-0">{pct:.1f}%</span></span></li>'
            for _, k, pct, col, m in sorted(sides[right]))  # fmt: skip
        return f'<ul class="relative flex-1 min-w-0 self-stretch">{rows}</ul>'

    return (f'<section class="mt-space-lg"><h2 class="font-headline-sm text-headline-sm text-on-surface">{e(title)}</h2>'
            + (f'<p class="mt-2 inline-flex items-center gap-1 px-2 py-1 rounded-md bg-surface-container text-[13px] text-on-surface-variant">'
               f'<span class="material-symbols-outlined text-[16px] text-primary">info</span>기타는 빼고 상위 {len(parts)}종목만 그렸어요 (전체의 {shown:.0f}%)</p>' if shown < 99.95 else "")  # 꼭 보이게 (사용자 10/10)
            + '<div data-pie class="relative mt-2 py-6 flex items-start gap-6 lg:gap-10">' + column(False)
            + f'<svg viewBox="0 0 100 100" class="w-36 h-36 lg:w-52 lg:h-52 shrink-0" role="img" aria-label="{e(title)}">{"".join(slices)}</svg>'
            + column(True) + '<svg class="absolute inset-0 w-full h-full pointer-events-none overflow-visible"></svg></div></section>' + PIE_LINES)  # fmt: skip


# 파이 이름 놓기 · 선 긋기. 이름(색 네모 가운데)을 조각 가장자리 높이에 두고, 겹치면 아래로 밀고, 넘치면 위로 당긴다(원 위아래 24px 여유).
# 한쪽에 이름이 많아 원보다 높아지면 상자를 키운다(원은 가운데 그대로). 선은 조각 가장자리 → 색 네모 앞 — 거의 수평
PIE_LINES = """<script>(function(){if(window.pieLines)return;
function place(box){var o=box.getBoundingClientRect(),pie=box.querySelector('svg[role=img]').getBoundingClientRect(),lay=box.lastElementChild;
var cx=pie.left+pie.width/2-o.left,cy=pie.top+pie.height/2-o.top,r=pie.width*0.48,H=o.height,need=0,out='';
[true,false].forEach(function(right){var it=[].slice.call(box.querySelectorAll('[data-ang]')).filter(function(d){return (Math.cos(+d.dataset.ang)>=0)==right})
.map(function(d){var li=d.closest('li'),a=+d.dataset.ang,off=d.offsetTop+d.offsetHeight/2,uo=li.parentNode.getBoundingClientRect().top-o.top;return {d:d,li:li,a:a,off:off,uo:uo,h:li.offsetHeight,t:cy+r*Math.sin(a)-off-uo}}).sort(function(x,y){return x.t-y.t});
for(var i=1;i<it.length;i++)it[i].t=Math.max(it[i].t,it[i-1].t+it[i-1].h+6);
var n=it.length;if(n){var uo=it[0].uo,over=it[n-1].t+it[n-1].h-(H-uo);if(over>0)it.forEach(function(x){x.t-=over});var under=-uo-it[0].t;if(under>0)it.forEach(function(x){x.t+=under});
need=Math.max(need,it[n-1].t+it[n-1].h-it[0].t)}
it.forEach(function(x){x.li.style.top=x.t+'px';var px=cx+r*Math.cos(x.a),py=cy+r*Math.sin(x.a),y=x.uo+x.t+x.off,q=x.d.getBoundingClientRect(),tx=right?q.left-o.left-4:q.right-o.left+4;
out+='<line x1="'+px+'" y1="'+py+'" x2="'+tx+'" y2="'+y+'" stroke="#c0c8c4" stroke-width="1"/>'})});
lay.innerHTML=out;return need>H+1?need:0}
window.pieLines=function(){document.querySelectorAll('[data-pie]').forEach(function(box){box.style.minHeight='';var need=place(box);if(need){box.style.minHeight=need+'px';place(box)}})};
addEventListener('load',pieLines);addEventListener('resize',pieLines);document.fonts&&document.fonts.ready.then(pieLines);})();pieLines&&pieLines();</script>"""


def ind_tag(kr: str | None = None, sic: str | None = None, issuer: str = "") -> str:
    """종목 이름 옆 회색 작은 글씨 「#반도체」 — 한국은 통계청 업종, 미국은 SEC 산업분류(짧은 이름을 아는 것만, 아니면 큰 업종). 상자·배경 없이(사용자 10/10)."""
    name = sources.industry_label(kr) if kr else (notes.SIC_LABEL.get(sic or "") or gurus.sector(sic, issuer))
    name = "ETF" if name and name.startswith("ETF") else name
    return f'<span class="shrink-0 text-[12px] font-normal text-outline">#{e(name)}</span>' if name else ""


TOP_LIST = 20  # 「많이 가진 순서」는 어디서나 20종목까지 — 유명 투자자·국민연금·다른 기관 모두 같게(사용자 10/10)


def issuer_name(issuer: str, ours: str | None) -> str:
    """13F 회사 이름 — 우리 종목이면 한글 이름, 아니면 대문자 줄임말을 보기 좋게(「MAGNA INTL INC」→「Magna Intl Inc」)."""
    if not ours and gurus.sector("", issuer) == "ETF(지수 펀드)":  # 「INVESCO EXCH TRADED FD TR II …」 → 「Invesco ETF」
        return issuer.split()[0].title() + " ETF"
    return ours or (issuer.title() if issuer.isupper() else issuer)


def price_chart(points: list[tuple[str, int]]) -> str:
    """토스처럼 — 종가 선 · 기간 안 최고·최저 · 1주/3달/1년. 올랐으면 빨강, 내렸으면 파랑(국내 관례).
    ⚠️ 개발 중 개인용만(PRICE_DEV) — 남에게 보이는 서버엔 그리지 않는다."""
    if len(points) < 5:
        return ""
    data = json.dumps([[d, v] for d, v in points])
    last, prev = points[-1][1], points[-2][1]
    diff = last - prev
    tone = "text-[#e0464c]" if diff > 0 else "text-[#3182f6]" if diff < 0 else "text-on-surface-variant"
    btn = "px-3 py-1 rounded-lg font-label-regular text-label-regular text-on-surface-variant"
    return ('<figure class="mb-space-lg">'
            f'<div class="flex items-baseline gap-2"><span class="font-headline-lg text-headline-lg text-on-surface">{last:,}원</span>'
            f'<span class="font-label-regular text-label-regular {tone}">어제보다 {diff:+,}원 ({diff / prev * 100:+.1f}%)</span></div>'
            '<svg id="pc" viewBox="0 0 340 170" class="w-full h-auto mt-2" role="img" aria-label="주가 흐름"></svg>'
            '<div class="flex justify-around mt-1">' + "".join(f'<button type="button" class="{btn}" data-d="{d}">{t}</button>' for d, t in ((7, "1주"), (91, "3달"), (365, "1년")))
            + '</div><p class="mt-1 font-label-micro text-label-micro text-tertiary">⚠️ 개발용 — 주가는 개인용으로만 받은 것이라 남에게 보여주면 안 돼요. 하루 늦은 종가예요.</p></figure>'
            "<script>(()=>{const P=" + data + ";const svg=document.getElementById('pc');"
            "function draw(days){const end=new Date(P[P.length-1][0]);const from=new Date(end-days*864e5);const p=P.filter(x=>new Date(x[0])>=from);"
            "const v=p.map(x=>x[1]);const hi=Math.max(...v),lo=Math.min(...v);const W=340,H=170,T=22,B=22,span=(hi-lo)||1;"
            "const X=i=>8+i*(W-16)/Math.max(p.length-1,1),Y=y=>T+(hi-y)/span*(H-T-B);"
            "const up=v[v.length-1]>=v[0],c=up?'#e0464c':'#3182f6';const hiI=v.indexOf(hi),loI=v.indexOf(lo);"
            "const lbl=(i,y,t,dy)=>{const x=Math.min(Math.max(X(i),48),W-48);return `<text x='${x}' y='${Y(y)+dy}' text-anchor='middle' font-size='11' fill='${c}'>${t} ${y.toLocaleString()}원</text>`};"
            "svg.innerHTML=`<polyline fill='none' stroke='${c}' stroke-width='2' stroke-linejoin='round' points='${p.map((x,i)=>X(i)+','+Y(x[1])).join(' ')}'/>`"
            "+`<circle cx='${X(hiI)}' cy='${Y(hi)}' r='2.5' fill='${c}'/>`+`<circle cx='${X(loI)}' cy='${Y(lo)}' r='2.5' fill='${c}'/>`"
            "+lbl(hiI,hi,'최고',-8)+lbl(loI,lo,'최저',16);"
            "document.querySelectorAll('[data-d]').forEach(b=>b.classList.toggle('bg-surface-container-high',+b.dataset.d===days));}"
            "document.querySelectorAll('[data-d]').forEach(b=>b.onclick=()=>draw(+b.dataset.d));draw(91);})();</script>")  # fmt: skip


def chapter(title: str, body: str, extra: str = "", anchor: str = "") -> str:
    return (f'<article {f"""id="{anchor}" """ if anchor else ""}class="scroll-mt-20 mb-12 flex flex-col gap-space-sm"><div class="flex items-center gap-2"><span class="w-2 h-2 rounded-full bg-primary"></span>'
            f'<h3 class="font-headline-md text-headline-md text-on-surface">{e(title)}</h3></div>'
            f'<div class="font-body-reading text-body-reading text-on-surface leading-loose">{body}</div>{extra}</article>')  # fmt: skip


def index_chart(got: dict) -> str:
    """한국·미국 주가지수 선 그림 — 세로는 로그 눈금(같은 % 변화가 같은 높이). 한국 자료가 시작된 달부터."""
    import math

    start = got["한국"]["from"]
    lines = {n: [(d, v) for d, v in g["series"] if d >= start] for n, g in got.items()}
    ds = sorted({d for pts in lines.values() for d, _ in pts})
    lo, hi = (f(math.log(v) for pts in lines.values() for _, v in pts) for f in (min, max))
    W, H, P = 340, 180, 24

    def xy(d, v):
        return f"{P + (ds.index(d) / (len(ds) - 1)) * (W - P - 4):.1f},{H - 18 - (math.log(v) - lo) / (hi - lo) * (H - 30):.1f}"

    # 실선 + 색으로만 구분 — 점선은 끊겨 보이고, 화면 폭에 따라 굵기가 변하지 않게 non-scaling-stroke (사용자 10/9)
    color = {"한국": "#154539", "미국": "#b4532a"}
    polys = "".join(f'<polyline stroke="{color.get(n, "#717975")}" fill="none" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke" points="{" ".join(xy(d, v) for d, v in pts)}"/>'
                    for n, pts in lines.items())  # fmt: skip
    years = sorted({d[:4] for d in ds if d[:4].endswith(("0", "5")) and d[5:7] == "01"})
    ticks = "".join(f'<text x="{xy(f"{y}-01-01", math.exp(lo)).split(",")[0]}" y="{H - 4}" font-size="9" text-anchor="middle" fill="currentColor" class="text-outline">{y}</text>'
                    for y in years if f"{y}-01-01" in ds and int(y) % 10 == 0)  # fmt: skip
    legend = " ".join(f'<span class="inline-flex items-center gap-1"><span class="w-4 h-[2px] rounded-full" style="background:{color.get(n, "#717975")}"></span>{e(n)}</span>' for n in lines)
    return ('<figure class="my-space-md max-w-[560px]"><figcaption class="font-label-regular text-label-regular text-on-surface font-semibold mb-1">주가지수 흐름 (로그 눈금)</figcaption>'
            f'<svg viewBox="0 0 {W} {H}" class="w-full h-auto" role="img" aria-label="한국과 미국 주가지수 흐름">{polys}{ticks}</svg>'
            f'<div class="flex gap-3 font-label-micro text-label-micro text-on-surface-variant">{legend}</div></figure>')  # fmt: skip


# 금리 다섯 가지의 색 — 모두 실선, 색으로만 구분 (점선은 끊겨 보인다, 사용자 10/9)
RATE_LOOK = {"기준금리": "#9aa19d", "국고채 3년": "#154539", "국고채 10년": "#5f9e88", "회사채 AA-": "#c8902e", "회사채 BBB-": "#a33a24"}


def rate_ladder(now: dict, month: str) -> str:
    """그달 금리 사다리 — 낮은 것부터 막대. 신용·기간에 따라 이자가 어떻게 달라지는지 한눈에."""
    top = max(now.values())
    rows = "".join(f'<div class="flex items-center gap-2 py-1"><span class="w-20 font-label-regular text-label-regular text-on-surface">{e(n)}</span>'
                   f'<div class="flex-1 h-2.5 rounded-full bg-surface-container overflow-hidden"><div class="h-full rounded-full" style="width:{v / top * 100:.0f}%;background:{RATE_LOOK[n]}"></div></div>'
                   f'<span class="w-12 text-right font-label-regular text-label-regular text-on-surface font-semibold">{v:.2f}%</span></div>'
                   for n, v in sorted(now.items(), key=lambda x: x[1]))  # fmt: skip
    return (f'<figure class="my-space-md max-w-[560px]"><figcaption class="font-label-regular text-label-regular text-on-surface font-semibold mb-1">{int(month[:4])}년 {int(month[5:7])}월 금리 (연, 월평균)</figcaption>'
            f'{rows}<p class="font-label-micro text-label-micro text-outline mt-1">자료: 한국은행 ECOS</p></figure>')


def rate_chart(got: dict) -> str:
    """금리 다섯 가지의 흐름 — 세로는 % 그대로, 달마다."""
    ds = sorted({d for pts in got.values() for d, _ in pts})
    hi = max(v for pts in got.values() for _, v in pts)
    W, H, P = 340, 190, 24
    pos = {d: i for i, d in enumerate(ds)}

    def xy(d, v):
        return f"{P + pos[d] / (len(ds) - 1) * (W - P - 4):.1f},{H - 18 - v / hi * (H - 30):.1f}"

    polys = "".join(f'<polyline stroke="{RATE_LOOK[n]}" fill="none" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke" points="{" ".join(xy(d, v) for d, v in pts)}"/>' for n, pts in got.items())
    grid = "".join(f'<text x="2" y="{H - 18 - y / hi * (H - 30) + 3:.1f}" font-size="9" fill="currentColor" class="text-outline">{y}%</text>'
                   for y in range(0, int(hi) + 1, 5))  # fmt: skip
    ticks = "".join(f'<text x="{xy(d, 0).split(",")[0]}" y="{H - 4}" font-size="9" text-anchor="middle" fill="currentColor" class="text-outline">{d[:4]}</text>'
                    for d in ds if d[5:7] == "01" and int(d[:4]) % 5 == 0)  # fmt: skip
    legend = " ".join(f'<span class="inline-flex items-center gap-1"><span class="w-4 h-[2px] rounded-full" style="background:{RATE_LOOK[n]}"></span>{e(n)}</span>' for n in got)
    return ('<figure class="my-space-md max-w-[560px]"><figcaption class="font-label-regular text-label-regular text-on-surface font-semibold mb-1">금리 흐름 (연 %, 월평균)</figcaption>'
            f'<svg viewBox="0 0 {W} {H}" class="w-full h-auto" role="img" aria-label="기준금리·국고채·회사채 금리 흐름">{grid}{polys}{ticks}</svg>'
            f'<div class="flex flex-wrap gap-x-3 gap-y-1 font-label-micro text-label-micro text-on-surface-variant">{legend}</div>'
            '<p class="font-label-micro text-label-micro text-outline mt-1">자료: 한국은행 ECOS</p></figure>')


def loss_bars(got: dict) -> str:
    """보유 기간별 「손해였던 비율」 막대 — 한국·미국 나란히."""
    labels = [r["label"] for r in got["한국"]["rows"]]
    color = {"한국": "bg-primary", "미국": "bg-secondary"}
    rows = []
    for lab in labels:
        cells = []
        for n, g in got.items():
            r = next((x for x in g["rows"] if x["label"] == lab), None)
            if r:
                w = round(r["loss"] * 100)
                cells.append(f'<div class="flex items-center gap-2"><span class="w-7 font-label-micro text-label-micro text-outline">{e(n)}</span>'
                             f'<div class="flex-1 h-2 rounded-full bg-surface-container overflow-hidden"><div class="{color.get(n, "bg-outline")} h-full rounded-full" style="width:{w}%"></div></div>'
                             f'<span class="w-9 text-right font-label-micro text-label-micro text-on-surface">{w}%</span></div>')  # fmt: skip
        rows.append(f'<div class="flex items-start gap-3 py-1.5"><span class="w-10 pt-0.5 font-label-regular text-label-regular text-on-surface font-semibold">{e(lab)}</span><div class="flex-1 flex flex-col gap-1">{"".join(cells)}</div></div>')
    return ('<figure class="my-space-md"><figcaption class="font-label-regular text-label-regular text-on-surface font-semibold">이만큼 들고 있었다면 — 손해였던 비율</figcaption>'
            '<p class="font-label-micro text-label-micro text-on-surface-variant mb-1">아무 달에나 사서 그 기간 뒤에 팔았다고 치고, 손해였던 경우를 셌어요.</p>'
            + "".join(rows)
            + '<p class="font-label-micro text-label-micro text-outline mt-1">자료: OECD 주가지수(월평균, 2015=100) · 한국은행 ECOS에서 받음. 배당은 빠져 있고, 하루하루 출렁임은 이보다 커요.</p></figure>')  # fmt: skip
