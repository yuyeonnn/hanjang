"""캘린더 — 내 종목 일정·공모주"""

import calendar
import re
from datetime import date

from hanjang import learn, notes, sources
from hanjang.notepage import AHEAD_SHORT, CHIP, EVENT_EXPLAIN, EVENT_SHORT, FLAG, TIPS, TIP_DEFAULT, TONE_TAG, clean_title, short_name
from hanjang.ui import bottom_nav, e, page, top_bar


class CalendarPages:
    # ---- 캘린더 (시안 _4) ----

    def calendar(self, uid: int, month: str | None, today: date | None = None, sort: str | None = None) -> str:
        """④ 캘린더 — 한 달 달력. 주말·공휴일은 빨간 숫자, 칸 안에 내 종목의 공시.
        앞으로의 일정(events — 공시 원문에서 읽은 실적 발표·주총·배당)은 테두리 칩으로 따로 보인다."""
        today = today or date.today()
        y, m = (int(x) for x in month.split("-")) if month and re.fullmatch(r"\d{4}-\d{2}", month) else (today.year, today.month)
        y, m = (y, m) if 1 <= m <= 12 and 2000 <= y <= 2100 else (today.year, today.month)
        weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(y, m)  # 일요일부터
        lo, hi = weeks[0][0].isoformat(), weeks[-1][-1].isoformat()
        hol = dict(self.con.execute("select date, name from holidays where date between ? and ?", (lo, hi)))
        if (end := date(y, 12, 31)).weekday() < 5 and m == 12:
            hol.setdefault(end.isoformat(), "증시 휴장")  # 연말 휴장 — 공휴일 자료엔 없다
        rows = self.con.execute(
            "select d.date, s.name, d.code, d.title, d.rcept_no, d.direction, s.ticker, d.amount, d.importance from disclosures d"
            " join holdings h on h.ticker = d.ticker and h.user_id = ? join stocks s on s.ticker = d.ticker"
            " where d.date between ? and ? and d.importance >= 2 and d.code != 'OTHER' order by d.date",
            (uid, lo, hi)).fetchall()  # fmt: skip
        # 같은 날 같은 회사의 같은 종류 공시는 하나로 묶는다 — 계약 두 건, 자사주 취득·소각이 같은 말로 두 번 나오지 않게 (사용자 10/9)
        grouped: dict[tuple, list] = {}
        for r in rows:
            grouped.setdefault((r[0], r[6], r[2]), []).append(r)
        by: dict[str, list] = {}
        for (d, _, _), rs in grouped.items():
            by.setdefault(d, []).append(rs)
        macro = sources.macro_events(lo, hi)
        has_us = self.con.execute("select 1 from holdings h join stocks s using(ticker) where h.user_id = ? and s.market = 'US'", (uid,)).fetchone()
        macro = [x for x in macro if x[1] != "휴장" or has_us]  # 미국 휴장일은 미국 종목을 담은 사람에게만
        macro_by: dict[str, list] = {}
        for x in macro:
            macro_by.setdefault(x[0], []).append(x)
        # 내 종목 회사채 — 납입일(돈이 실제로 들어오는 날)에 칩. 같은 신고서의 회차(2년물·3년물)는 하나로
        bonds = self.con.execute(
            "select b.rcept_no, min(b.pay_date), s.name, s.ticker, sum(b.amount), group_concat(b.maturity), group_concat(b.uses, '|'), max(b.lead)"
            " from bonds b join holdings h on h.ticker = b.ticker and h.user_id = ? join stocks s on s.ticker = b.ticker"
            " where b.pay_date between ? and ? group by b.rcept_no order by 2", (uid, lo, hi)).fetchall()  # fmt: skip
        bond_by: dict[str, list] = {}
        for x in bonds:
            bond_by.setdefault(x[1], []).append(x)
        # 공모주 — 시장 전체(내 종목 아님). 한 달 수십 곳이라 칩은 청약 첫날·상장 예정일에만, 금리·물가 칩 뒤에
        ipos = self.con.execute("select name, sub_start, sub_end, list_date, price, total, lead, uses, rcept_no from ipos"
                                " where sub_start between ? and ? or list_date between ? and ? order by sub_start", (lo, hi, lo, hi)).fetchall()  # fmt: skip
        ipo_by: dict[str, list] = {}
        for x in ipos:
            ipo_by.setdefault(x[1], []).append((x[0], "청약", x[8]))
            if x[3]:
                ipo_by.setdefault(x[3], []).append((x[0], "상장", x[8]))
        ahead: dict[str, list] = {}  # 공시에서 읽은 일정(실적 발표·주총·배당 기준일·지급일) — 테두리 칩으로 지난 공시와 구분
        for d, name, kind, what, rno in self.con.execute(
                "select e.date, s.name, e.kind, e.title, e.rcept_no from events e join holdings h on h.ticker = e.ticker and h.user_id = ?"
                " join stocks s on s.ticker = e.ticker where e.date between ? and ? order by e.date", (uid, lo, hi)):  # fmt: skip
            ahead.setdefault(d, []).append((name, kind, what, rno))
        mine = sorted((rs for rs in grouped.values() if rs[0][0][:7] == f"{y}-{m:02d}"), key=lambda rs: rs[0][0], reverse=True)  # 최신순
        kinds: dict[str, int] = {}
        for rs in mine:
            kinds[rs[0][2]] = kinds.get(rs[0][2], 0) + 1
        prev = f"{y - (m == 1)}-{(m - 2) % 12 + 1:02d}"
        nxt = f"{y + (m == 12)}-{m % 12 + 1:02d}"
        cells = []
        for wk in weeks:
            for i, d in enumerate(wk):
                iso = d.isoformat()
                if d.month != m:
                    num = f'<span class="font-label-micro text-label-micro lg:text-[14px] text-outline-variant">{d.day}</span>'
                elif d == today:
                    num = (f'<div class="flex items-center justify-between"><span class="w-5 h-5 flex items-center justify-center rounded-full bg-primary-container text-on-primary font-label-micro text-label-micro font-bold">{d.day}</span>'
                           '<span class="text-[8px] text-primary-container font-semibold">오늘</span></div>')  # fmt: skip
                elif iso in hol:  # 공휴일은 시안대로 검은 숫자 + 이름 (사용자 10/7: 시안 그대로)
                    num = f'<span class="font-label-micro text-label-micro lg:text-[14px] text-on-surface font-medium">{d.day}</span>'
                elif i in (0, 6):  # 주말은 빨간 숫자
                    num = f'<span class="font-label-micro text-label-micro lg:text-[14px] text-tertiary font-semibold">{d.day}</span>'
                else:
                    num = f'<span class="font-label-micro text-label-micro lg:text-[14px] text-on-surface">{d.day}</span>'
                cell = num
                if iso in hol and d.month == m:
                    cell += f'<span class="text-[8px] lg:text-[11px] text-on-surface-variant leading-tight line-clamp-1 mt-0.5">{e(hol[iso])}</span>'
                # 칸 안 칩은 한 줄 — 넘치면 말줄임(…), 전체 이름은 마우스를 올리면·오른쪽 목록에서. 칸마다 셋까지, 나머지는 「+N」 (사용자 10/9: 줄바꿈이 별로)
                chips = []
                for rs in by.get(iso, []) if d.month == m else []:
                    _, name, code, _, rno, dr, _, _, _ = rs[0]
                    tint = {1: "bg-secondary-fixed text-on-secondary-fixed-variant", -1: "bg-tertiary-fixed text-on-tertiary-fixed-variant"}.get(dr, "bg-surface-container-high text-on-surface-variant")
                    many = f" {len(rs)}건" if len(rs) > 1 else ""
                    chips.append(f'<span title="{e(name)} {e(EVENT_SHORT.get(code, ""))}{many}" class="{CHIP} {tint}">'
                                 f"<span class='lg:hidden'>{e(short_name(name))}</span><span class='hidden lg:inline'>{e(name)}</span> {e(EVENT_SHORT.get(code, ''))}{many}</span>")  # fmt: skip
                for rno, _, name, _, total, *_ in bond_by.get(iso, []) if d.month == m else []:
                    chips.append(f'<span title="{e(name)} 회사채 {e(notes.won(total))}" class="{CHIP} bg-surface-container-high text-on-surface-variant">'
                                 f"<span class='lg:hidden'>{e(short_name(name))} 채권</span><span class='hidden lg:inline'>{e(name)} 회사채 {e(notes.won(total))}</span></span>")  # fmt: skip
                for name, kind, what, rno in ahead.get(iso, []) if d.month == m else []:
                    chips.append(f'<span title="{e(name)} {e(what)}" class="{CHIP} border border-primary/40 text-primary">'
                                 f"<span class='lg:hidden'>{e(short_name(name))} {AHEAD_SHORT.get(kind, '')}</span><span class='hidden lg:inline'>{e(name)} {e(what)}</span></span>")  # fmt: skip
                for _, kind, nat, what in macro_by.get(iso, []) if d.month == m else []:
                    chips.append(f'<span title="{e(what)}" class="{CHIP} border border-dashed border-outline-variant text-on-surface-variant">'
                                 f"<span class='lg:hidden'>{FLAG[nat]} {e(kind)}</span><span class='hidden lg:inline'>{e(what)}</span></span>")  # fmt: skip
                for name, what, rno in ipo_by.get(iso, []) if d.month == m else []:
                    chips.append(f'<span title="{e(name)} 공모주 {what}" class="{CHIP} border border-secondary/50 text-secondary">'
                                 f"<span class='lg:hidden'>{e(short_name(name))} {what}</span><span class='hidden lg:inline'>{e(name)} 공모주 {what}</span></span>")  # fmt: skip
                cell += "".join(chips[:3]) + (f'<span class="mt-0.5 text-[9px] lg:text-[11px] text-outline">+{len(chips) - 3}</span>' if len(chips) > 3 else "")
                pick = f' data-day="{iso}" onclick="pickDay(this.dataset.day)"' if d.month == m else ""  # 칸 어디를 눌러도(칩 포함) 그날 일정 — 칩은 원문 링크가 아니다(사용자 10/10: 누르면 원문으로 넘어가 힘들다) 일정
                cells.append(f'<div{pick} class="min-h-[52px] lg:min-h-[112px] p-1 lg:p-2 rounded-lg flex flex-col justify-start lg:border-t lg:border-surface-container-high {"" if d.month != m else "cursor-pointer hover:bg-surface-container-low"}">{cell}</div>')
        items = []
        minor = set()  # 「이 달의 일정」 목록에서 뺄 것 — 달력 칸·그날 일정에는 그대로 (사용자 10/10: 너무 많다, 덜 중요한 건 빼)
        for rs in mine:
            d, name, code, title, rno, dr, t, _, imp = rs[0]
            if not (dr or imp >= 3 or (code == "EARNINGS" and not re.match(r"판매|예비", title) and "예고" not in title)):
                minor.add(len(items))  # 좋고 나쁨이 없는 보통 공시(판매 대수 알림·실적 발표 예고 등)
            dd = date.fromisoformat(d)
            label, chip = TONE_TAG.get(dr or 0, TONE_TAG[0])
            src = ("SEC 공시: " if "-" in rno else "DART 공시: ") + " · ".join(dict.fromkeys(re.sub(r"^\[[^\]]*\]", "", r[3]) + (f" {notes.won(r[7])} 규모" if r[7] else "") for r in rs))
            title = clean_title(title, code) + (f" 외 {len(rs) - 1}건" if len(rs) > 1 else "")
            items.append((1, d, f'<article class="py-3.5 border-b border-surface-container-high flex flex-col gap-1 transition-colors hover:bg-surface-container-low/40"><div class="flex items-center justify-between">'
                         f'<span class="font-label-micro text-label-micro text-on-surface-variant">{dd.month}월 {dd.day}일 ({"월화수목금토일"[dd.weekday()]}) · {e(name)} ({e(t)})</span>'
                         f'<span class="font-label-micro text-label-micro px-2 py-0.5 rounded-full {chip} font-semibold">{label}</span></div>'
                         f'<h3 class="font-headline-sm text-headline-sm text-on-surface font-semibold">{e(title)}</h3>'
                         f'<p class="font-body-compact text-body-compact text-on-surface-variant leading-relaxed">{e(EVENT_EXPLAIN.get(code, ""))}</p>'
                         f'<div class="flex items-center gap-1.5 text-on-surface-variant font-citation-ref text-citation-ref pt-0.5"><span class="material-symbols-outlined {"text-tertiary" if dr == -1 else "text-primary"} text-[15px]">{"info" if dr == -1 else "verified"}</span><a href="{e(self.src(rno))}" target="_blank" rel="noopener" class="underline underline-offset-2 decoration-outline-variant hover:text-on-surface">{e(src)}</a></div></article>'))  # fmt: skip
        soon = [(d, *x) for d in sorted(ahead) if d[:7] == f"{y}-{m:02d}" for x in ahead[d]]
        items += [(0, d, f'<article class="py-3.5 border-b border-surface-container-high flex items-center justify-between gap-2">'
                 f'<span class="font-body-compact text-body-compact text-on-surface"><span class="text-on-surface-variant">{(dd := date.fromisoformat(d)).month}월 {dd.day}일 ({"월화수목금토일"[dd.weekday()]})</span> · {e(name)} <b>{e(what)}</b></span>'
                 f'<span class="flex items-center gap-2 flex-shrink-0"><a href="{e(self.src(rno))}" target="_blank" rel="noopener" class="underline underline-offset-2 decoration-outline-variant hover:text-on-surface font-citation-ref text-citation-ref text-on-surface-variant">원문</a><span class="font-label-micro text-label-micro px-2 py-0.5 rounded-full border border-primary/40 text-primary font-semibold">일정</span></span></article>')
                  for d, name, _, what, rno in soon]  # fmt: skip
        for rno, pay, name, t, total, mats, uses, lead in bonds:  # 내 종목 회사채 — 공시와 같은 자리
            if pay[:7] != f"{y}-{m:02d}":
                continue
            dp = date.fromisoformat(pay)
            say = "회사가 채권을 팔아 돈을 빌려요."
            items.append((1, pay, f'<article class="py-3.5 border-b border-surface-container-high flex flex-col gap-1">'
                          f'<div class="flex items-center justify-between"><span class="font-label-micro text-label-micro text-on-surface-variant">{dp.month}월 {dp.day}일 ({"월화수목금토일"[dp.weekday()]}) 납입 · {e(name)} ({e(t)})</span>'
                          '<span class="font-label-micro text-label-micro px-2 py-0.5 rounded-full bg-surface-container-high text-on-surface-variant font-semibold">회사채</span></div>'
                          f'<h3 class="font-headline-sm text-headline-sm text-on-surface font-semibold">{e(name)} 회사채 {e(notes.won(total))}</h3>'
                          f'<p class="font-body-compact text-body-compact text-on-surface-variant leading-relaxed">{e(say)}</p>'
                          f'<a href="{e(self.src(rno))}" target="_blank" rel="noopener" class="underline underline-offset-2 decoration-outline-variant hover:text-on-surface self-start font-citation-ref text-citation-ref text-on-surface-variant pt-0.5">출처: DART 증권신고서(채무증권)</a></article>'))  # fmt: skip
        for name, a, b, listed, price, total, lead, uses, rno in ipos:  # 공모주 — 맨 뒤 (금리·물가가 더 많은 사람에게 닿는다)
            d = a if a[:7] == f"{y}-{m:02d}" else listed if listed and listed[:7] == f"{y}-{m:02d}" else None
            if not d:
                continue
            da, db_ = date.fromisoformat(a), date.fromisoformat(b)
            say = "새로 상장하려는 회사가 주식을 팔아 돈을 모아요."
            minor.add(len(items))  # 공모주는 한 달 수십 곳 — 목록에선 한 줄로 모은다
            items.append((9, d, f'<article class="py-3.5 border-b border-surface-container-high flex flex-col gap-1">'
                          f'<div class="flex items-center justify-between"><span class="font-label-micro text-label-micro text-on-surface-variant">{da.month}월 {da.day}일 ~ {db_.month}월 {db_.day}일 청약 · 시장 전체</span>'
                          '<span class="font-label-micro text-label-micro px-2 py-0.5 rounded-full border border-secondary/50 text-secondary font-semibold">공모주</span></div>'
                          f'<h3 class="font-headline-sm text-headline-sm text-on-surface font-semibold">{e(name)} 공모주 청약</h3>'
                          f'<p class="font-body-compact text-body-compact text-on-surface-variant leading-relaxed">{e(say)}</p>'
                          f'<a href="{e(self.src(rno))}" target="_blank" rel="noopener" class="underline underline-offset-2 decoration-outline-variant hover:text-on-surface self-start font-citation-ref text-citation-ref text-on-surface-variant pt-0.5">출처: DART 증권신고서(지분증권)</a></article>', {x for x in (a, listed) if x}))  # fmt: skip
        for d, kind, nat, what in macro:  # 시장 일정 — 내 종목 일정·공시 다음, 금리 → 물가 → 선거 → 고용
            if d[:7] != f"{y}-{m:02d}":
                continue
            dd, (who, url) = date.fromisoformat(d), sources.MACRO_SOURCE[nat + kind]
            items.append((1 + sources.MACRO_RANK[kind], d, f'<article class="py-3.5 border-b border-surface-container-high flex flex-col gap-1">'
                          f'<div class="flex items-center justify-between"><span class="font-label-micro text-label-micro text-on-surface-variant">{dd.month}월 {dd.day}일 ({"월화수목금토일"[dd.weekday()]}) · 시장 전체</span>'
                          '<span class="font-label-micro text-label-micro px-2 py-0.5 rounded-full border border-dashed border-outline-variant text-on-surface-variant font-semibold">시장 일정</span></div>'
                          f'<h3 class="font-headline-sm text-headline-sm text-on-surface font-semibold">{e(what)}</h3>'
                          f'<p class="font-body-compact text-body-compact text-on-surface-variant leading-relaxed">{e(sources.MACRO_EXPLAIN[(kind, nat)])}</p>'
                          f'<a href="{e(url)}" target="_blank" rel="noopener" class="underline underline-offset-2 decoration-outline-variant hover:text-on-surface self-start font-citation-ref text-citation-ref text-on-surface-variant pt-0.5">일정 출처: {e(who)}</a></article>'))  # fmt: skip
        ipo_n = len(minor & {i for i, x in enumerate(items) if x[0] == 9})
        items = [(*x[:3], x[3] if len(x) > 3 else {x[1]}, i in minor) for i, x in enumerate(items)]
        items.sort(key=lambda x: (x[0], x[1]))  # 관련 높은 순 — 내 종목 일정 → 내 종목 공시 → 시장 일정
        days: dict[str, list] = {}  # 달력에서 고른 날의 일정 — 같은 순서로, 공모주는 청약 첫날·상장일 둘 다. 덜 중요한 것도 여기엔 다
        for x in items:
            for dd_ in x[3]:
                days.setdefault(dd_, []).append(x[2])
        sort = "old" if sort in ("new", "old") else "rel"  # 이 달의 일정 — 관련 높은 순(기본) · 날짜순(1일부터). 최신순은 날짜순을 거꾸로 한 것뿐이라 뺐다(사용자 10/16) — 옛 주소 s=new 는 날짜순으로
        if sort != "rel":
            items.sort(key=lambda x: x[1])
        items = [x[2] for x in items if not x[4]]
        if ipo_n:
            items.append(f'<a href="#calendar-grid" class="py-3.5 border-b border-surface-container-high flex items-center justify-between gap-2 font-body-compact text-body-compact text-on-surface-variant hover:text-on-surface">'
                         f'<span class="flex items-center gap-2"><span class="material-symbols-outlined text-secondary text-[18px]">campaign</span>이 달 공모주 청약 {ipo_n}곳 — 달력 칸을 눌러 날마다 볼 수 있어요</span>'
                         '<span class="material-symbols-outlined text-[16px]">expand_less</span></a>')  # fmt: skip
        pick = today.isoformat() if (today.year, today.month) == (y, m) else f"{y}-{m:02d}-01"  # 처음엔 오늘, 다른 달이면 1일
        day_lists = "".join(f'<div data-list="{d}"{"" if d == pick else " hidden"}>{"".join(h)}</div>' for d, h in days.items() if d[:7] == f"{y}-{m:02d}")
        day_none = f'<p data-list="none" class="py-3.5 font-body-compact text-body-compact text-on-surface-variant"{" hidden" if pick in days else ""}>이 날은 일정이 없어요.</p>'
        pick_js = ("<script>function pickDay(d){var t=new Date(d+'T00:00');"
                   f"document.getElementById('day-title').textContent=d=='{today.isoformat()}'?'오늘 일정':(t.getMonth()+1)+'월 '+t.getDate()+'일 ('+'일월화수목금토'[t.getDay()]+') 일정';"
                   "var hit=false;document.querySelectorAll('[data-list]').forEach(function(x){var on=x.dataset.list==d;x.hidden=!on;hit=hit||on});"
                   "document.querySelector('[data-list=none]').hidden=hit;"
                   "document.querySelectorAll('[data-day]').forEach(function(c){c.classList.toggle('bg-primary-fixed',c.dataset.day==d)})}"
                   f"pickDay('{pick}')</script>")  # fmt: skip
        if not items:
            items.append('<p class="py-3.5 font-body-compact text-body-compact text-on-surface-variant">이 달엔 내 종목의 큰 공시가 없어요.</p>')
        # 이 달 일정에 나온 공시 종류마다 그에 맞는 읽기 팁 글 — 많이 나온 종류부터, 같은 글은 한 번, 최대 3편
        picks = {}
        for kind in sorted(kinds, key=kinds.get, reverse=True):
            picks.setdefault(learn.FOR_EVENT.get(kind, "disclosure"), kind)
        tips = "".join(
            f'<a href="/learn/{slug}" class="py-3 flex items-center gap-space-md"><div class="w-12 h-12 rounded-lg flex-shrink-0 bg-surface-container flex items-center justify-center"><span class="material-symbols-outlined text-primary text-[22px]">menu_book</span></div>'
            f'<div class="flex flex-col gap-0.5 min-w-0"><span class="font-label-micro text-label-micro text-outline">이 달 {e(EVENT_SHORT.get(kind, kind))} 공시와 관련</span>'
            f'<p class="font-body-compact text-body-compact text-on-surface font-semibold truncate">{e(learn.BY_SLUG[slug]["title"])}</p>'
            f'<span class="font-label-micro text-label-micro text-on-surface-variant truncate">{e(TIPS.get(kind, TIP_DEFAULT)[0])}</span></div>'
            '<span class="material-symbols-outlined text-outline text-[18px] ml-auto">chevron_right</span></a>'
            for slug, kind in list(picks.items())[:3]) or (
            '<a href="/learn/disclosure" class="py-3 flex items-center gap-space-md"><div class="w-12 h-12 rounded-lg flex-shrink-0 bg-surface-container flex items-center justify-center"><span class="material-symbols-outlined text-primary text-[22px]">menu_book</span></div>'
            f'<div class="flex flex-col gap-0.5 min-w-0"><p class="font-body-compact text-body-compact text-on-surface font-semibold">{e(learn.BY_SLUG["disclosure"]["title"])}</p>'
            f'<span class="font-label-micro text-label-micro text-on-surface-variant">{e(TIP_DEFAULT[0])}</span></div></a>')  # fmt: skip
        mix = " · ".join(f"{EVENT_SHORT.get(k, k)} {v}" for k, v in kinds.items()) or "큰 공시 없음"
        inner = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] lg:max-w-[1200px] mx-auto pt-14 pb-24 lg:pt-20 lg:pb-16 bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-6 gap-space-lg">'
                 '<header class="flex flex-col pt-space-xs gap-space-xs"><div class="flex items-center justify-between"><div class="flex items-baseline gap-space-xs">'
                 f'<h1 class="font-headline-lg text-headline-lg lg:text-[32px] lg:leading-[40px] text-on-surface tracking-tight">{y}년 {m}월</h1><span class="font-label-micro text-label-micro text-on-surface-variant">공시 타임라인</span></div>'
                 '<nav class="hidden lg:flex items-center gap-2 text-[13px]">'
                 f'<a class="flex items-center gap-0.5 px-3 py-1.5 rounded-full border border-outline-variant/60 text-on-surface-variant hover:bg-surface-container" href="/calendar?m={prev}"><span class="material-symbols-outlined text-[16px]">chevron_left</span>이전 달</a>'
                 f'<a class="px-3 py-1.5 rounded-full bg-primary text-on-primary font-semibold" href="/calendar">오늘</a>'
                 f'<a class="flex items-center gap-0.5 px-3 py-1.5 rounded-full border border-outline-variant/60 text-on-surface-variant hover:bg-surface-container" href="/calendar?m={nxt}">다음 달<span class="material-symbols-outlined text-[16px]">chevron_right</span></a></nav>'
                 '</div>'
                 '</header>'
                 '<section class="py-space-sm px-1 flex items-center justify-between border-b border-surface-container-high"><div class="flex items-center gap-space-sm"><span class="material-symbols-outlined text-primary text-[20px]">calendar_clock</span><div class="flex items-baseline gap-space-xs">'
                 f'<span class="font-label-regular text-label-regular text-on-surface font-semibold">이번 달 주목할 공시 {len(mine)}건</span><span class="font-label-micro text-label-micro text-on-surface-variant">{e(mix)}</span></div></div>'
                 '</section>'
                 '<div class="flex flex-col gap-space-lg lg:grid lg:grid-cols-[minmax(0,1fr)_380px] lg:gap-10 lg:items-start">'
                 '<section id="calendar-grid" class="flex flex-col gap-1 py-1 lg:rounded-2xl lg:border lg:border-surface-container-high lg:p-4"><div class="grid grid-cols-7 text-center font-label-micro text-label-micro font-semibold pb-1.5 lg:pb-2.5 lg:text-[13px] border-b border-surface-container-high/60"><span class="text-tertiary">일</span><span class="text-on-surface-variant">월</span><span class="text-on-surface-variant">화</span><span class="text-on-surface-variant">수</span><span class="text-on-surface-variant">목</span><span class="text-on-surface-variant">금</span><span class="text-tertiary">토</span></div>'
                 f'<div class="grid grid-cols-7 gap-1 lg:gap-0 pt-1 lg:pt-0">{"".join(cells)}</div>'
                 '<nav class="flex justify-center items-center gap-5 pt-2 text-[12px] text-outline">'
                 f'<a class="flex items-center hover:text-on-surface-variant" href="/calendar?m={prev}"><span class="material-symbols-outlined text-[14px]">chevron_left</span>이전 달</a>'
                 f'<a class="flex items-center hover:text-on-surface-variant" href="/calendar?m={nxt}">다음 달<span class="material-symbols-outlined text-[14px]">chevron_right</span></a></nav></section>'
                 '<aside class="flex flex-col gap-space-lg lg:sticky lg:top-20"><section class="flex flex-col mt-2 lg:mt-0"><div class="pb-2 border-b border-surface-container-highest"><h2 id="day-title" class="font-headline-md text-headline-md text-on-surface">오늘 일정</h2></div>'
                 f'{day_lists}{day_none}</section><section class="flex flex-col"><div class="flex items-center justify-between pb-2 border-b border-surface-container-highest"><div class="flex items-center gap-space-xs"><h2 class="font-headline-md text-headline-md text-on-surface">이 달의 일정</h2></div>'
                 '<a class="font-label-regular text-label-regular text-primary flex items-center hover:opacity-80 transition-opacity" href="https://dart.fss.or.kr" target="_blank" rel="noopener">전체 공시 원문<span class="material-symbols-outlined text-[15px] ml-0.5">arrow_forward</span></a></div>'
                 + '<nav id="month-list" class="scroll-mt-24 pt-2.5 pb-1 flex gap-1.5" aria-label="정렬">' + "".join(
                     f'<a href="/calendar?m={y}-{m:02d}&s={k}#month-list" class="px-3 py-1 rounded-full text-[12px] font-semibold border '
                     + ("bg-primary text-on-primary border-primary" if k == sort else "border-outline-variant/60 text-on-surface-variant hover:bg-surface-container") + f'">{label}</a>'
                     for k, label in (("rel", "관련 높은 순"), ("old", "날짜순"))) + "</nav>"
                 + f'<div class="flex flex-col">{"".join(items)}</div></section>'
                 '<section class="pt-4 border-t border-surface-container-high flex flex-col"><span class="font-label-regular text-label-regular text-primary font-bold">주주를 위한 읽기 팁</span>'
                 f'<div class="flex flex-col divide-y divide-surface-container-high/70">{tips}</div></section></aside></div>'
                 '<footer class="mt-2 text-center flex flex-col items-center gap-1"><div class="w-8 h-0.5 bg-surface-container-high rounded-full mb-1"></div><p class="font-citation-ref text-citation-ref text-on-surface-variant leading-relaxed max-w-[340px]">색 칩은 지난 공시, 테두리 칩은 공시에 적힌 앞으로의 일정(실적 발표·주총·배당), 점선 칩은 금리·물가·고용·선거 같은 시장 일정이에요. 공휴일: 한국천문연구원.</p></footer>'
                 "</div></main>" + bottom_nav("calendar") + pick_js)  # fmt: skip
        return page("캘린더", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)
