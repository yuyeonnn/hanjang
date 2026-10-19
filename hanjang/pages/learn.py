"""읽기 팁·공개 문서(처리방침·계산 방법·이용 규칙)"""

import re
from datetime import date, datetime, timedelta
from hanjang import quiz

from hanjang import gurus, holders, learn, notes, policy, sources, tree
from hanjang.charts import index_chart, issuer_name, loss_bars, pie, rate_chart, rate_ladder
from hanjang.notepage import figure
from hanjang.ui import RULE, RULE_FLIP, book_face, bottom_nav, e, guru_face, kdate, logo, page, top_bar


# 읽기 팁 분류마다 아이콘(Material Symbols) — 로드맵의 동그라미에
CAT_ICON = {"처음 시작": "flag", "상품 이해": "inventory_2", "회사 읽기": "apartment", "공시 읽기": "description", "업종별로 읽기": "factory",
            "시장 일정": "event", "미국 주식": "public", "생각 정리": "psychology", "책에서 배우기": "menu_book"}  # fmt: skip


class LearnPages:
    # ---- 공개 페이지: 개인정보 처리방침 · 계산 방법 (로그인 없이) ----

    def doc(self, path: str, uid: int | None) -> str:
        contact = sources.env().get("PRIVACY_CONTACT", "")
        title, parts = {"/privacy": ("개인정보 처리방침", policy.privacy(contact)), "/method": ("계산 방법", policy.method()),
                        "/help/login": ("로그인 링크가 안 와요", policy.login_help(contact)), "/rules": ("이용 규칙", policy.rules(contact))}[path]  # fmt: skip
        body = "".join(
            f'<section class="mt-space-lg"><h2 class="font-headline-sm text-headline-sm text-primary mb-space-xs">{e(h)}</h2>'
            + "".join(f'<p class="font-body-compact text-body-compact text-on-surface leading-relaxed mb-space-sm">{self.marked(x)}</p>' for x in ps)
            + "</section>" for h, ps in parts)  # fmt: skip
        inner = ('<main class="flex flex-col relative w-full max-w-[480px] lg:max-w-[760px] mx-auto bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pt-space-lg pb-24">'
                 '<a class="flex items-center gap-space-xs text-on-surface-variant hover:text-primary" href="/"><span class="material-symbols-outlined text-[18px]">arrow_back</span>'
                 '<span class="font-label-regular text-label-regular font-medium">한장</span></a>'
                 f'<h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight mt-space-md">{e(title)}</h1>'
                 f'<p class="font-label-micro text-label-micro text-outline mt-1">마지막 고침 {policy.UPDATED}</p>{body}</div></main>'
                 + (bottom_nav("me") if uid else ""))  # fmt: skip
        return page(title, "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    # ---- 읽기 팁 (시안에 없는 화면 — 같은 디자인 말투로) ----

    @staticmethod
    def marked(text: str) -> str:
        """「**핵심 말**」 → 진한 초록 굵은 글씨. 나머지는 그대로 이스케이프."""
        return re.sub(r"\*\*(.+?)\*\*", r'<strong class="font-semibold text-primary">\1</strong>', e(text))

    def flow(self, paras: list[str]) -> str:
        """읽기 팁 본문 — 짧은 문단을 둘씩 묶어 한 덩어리로, 줄 간격은 노트보다 조금 촘촘하게.
        한두 문장짜리 문단이 하나씩 떨어져 보여 글이 끊겨 읽히던 것 (사용자 10/10)."""
        groups = [" ".join(paras[k:k + 2]) for k in range(0, len(paras), 2)]
        return "".join(f'<p class="font-body-reading text-body-reading text-on-surface leading-[1.8] mb-5">{self.marked(g)}</p>' for g in groups)

    @staticmethod
    def related(slug: str) -> str:
        """글 아래 「함께 읽으면 좋은 팁」 — 이어 읽을 글 세 편 (사용자 10/10)."""
        items = [learn.BY_SLUG[x] for x in learn.RELATED.get(slug, []) if x in learn.BY_SLUG]
        if not items:
            return ""
        return ('<section class="mt-space-xl pt-space-md border-t border-surface-container-high"><h2 class="font-headline-sm text-headline-sm text-on-surface mb-1">함께 읽으면 좋은 팁</h2>'
                '<div class="flex flex-col divide-y divide-surface-container-high/80">'
                + "".join(f'<a href="/learn/{e(x["slug"])}" class="py-3 flex items-center justify-between gap-space-sm group"><span class="flex flex-col min-w-0">'
                          f'<span class="text-[12px] text-primary font-semibold">{e(x["cat"])}</span>'
                          f'<span class="font-body-reading-strong text-body-reading-strong text-on-surface group-hover:underline">{e(x["title"])}</span></span>'
                          '<span class="material-symbols-outlined text-primary text-[18px]">chevron_right</span></a>' for x in items)
                + "</div></section>")  # fmt: skip

    def today_big(self, today: date) -> str:
        """읽기 팁 맨 위 — 오늘의 큰손. 미국 보유 신고(13F)가 있는 투자자·기관을 하루에 한 곳씩 돌린다(사용자 10/19: 매일 들어올 까닭).
        이름·사진·종목 수·금액·기준일 + 큰 5종목 파이 + 전체 보기. 따라 사고팔라는 뜻이 아니라고 함께 적는다."""
        # 13F 는 분기 끝 45일 안에 나온다 — 가장 최근 신고도 길어야 넉 달 반 전. 200일이 넘은 곳은 신고가 끊긴 것이라 돌리지 않는다
        # (2026-10-19 확인: 마이클 버리의 사이언은 2025-09-30 기준이 마지막 · 퍼싱 스퀘어는 2026-06-30 분을 다른 회사 신고로 넘겼다고 13F-NT 만 냈다)
        fresh = (today - timedelta(days=200)).isoformat()
        keys = [k for (k,) in self.con.execute("select guru from guru_holdings group by guru having max(period) >= ? order by guru", (fresh,))
                if k in gurus.GURUS or k in holders.BIG]
        if not keys:
            return ""
        key = keys[today.toordinal() % len(keys)]
        rows = self.con.execute("select g.issuer, g.value, g.period, s.name from guru_holdings g left join stocks s on s.ticker = g.ticker"
                                " where g.guru = ? order by g.value desc", (key,)).fetchall()  # fmt: skip
        if key in gurus.GURUS:
            name, intro, face, href = gurus.GURUS[key][0], gurus.GURUS[key][2], guru_face(key, "w-14 h-14"), f"/learn/guru/{key}"
        else:
            name, intro = holders.BIG[key][0], holders.BIG[key][2]
            face, href = logo(name, self.BIG_HOME.get(key), "w-14 h-14"), f"/learn/big/{key}"
        total = sum(r[1] for r in rows)
        return ('<section class="mt-space-lg">'
                '<div class="flex items-center gap-1.5 text-primary font-label-regular text-label-regular font-bold"><span class="material-symbols-outlined text-[18px]">travel_explore</span>오늘의 큰손</div>'
                f'<a href="{href}" class="mt-space-sm flex items-center gap-space-md group">{face}<div class="flex flex-col min-w-0">'
                f'<span class="font-headline-md text-headline-md text-on-surface group-hover:underline">{e(name)}</span>'
                f'<span class="text-[12px] text-outline">미국 주식 {len(rows):,}종목 · {e(notes.usd(total))} · {kdate(rows[0][2])} 기준</span></div></a>'
                f'<p class="mt-space-sm font-body-compact text-body-compact text-on-surface">{e(intro)}</p>'
                + pie([(issuer_name(r[0], r[3]), r[1]) for r in rows])
                + f'<div class="mt-space-sm flex justify-end"><a href="{href}" class="font-label-regular text-label-regular text-primary font-semibold hover:underline">전체 보기 →</a></div></section>')  # fmt: skip

    def learn_top(self, today: date) -> str:
        """읽기 팁 맨 위 — 오늘의 읽기 팁: 어려운 말 하나를 한 줄로, 날마다 차례로 (사용자 10/19: 「오늘의 한 문제」 대신)."""
        word, line, slug = learn.TERMS[today.toordinal() % len(learn.TERMS)]
        more = f'<a href="/learn/{slug}" class="mt-1 self-start font-label-regular text-label-regular text-primary font-semibold hover:underline">더 읽기 →</a>' if slug else ""
        return ('<section class="mt-space-lg rounded-xl bg-primary-fixed/40 border-l-4 border-primary px-space-md py-space-md flex flex-col gap-1.5">'
                '<span class="flex items-center gap-1 font-label-regular text-label-regular text-primary font-bold"><span class="material-symbols-outlined text-[18px]">lightbulb</span>오늘의 읽기 팁</span>'
                f'<p class="font-body-reading text-body-reading text-on-surface"><b>{e(word)}</b> — {e(line)}</p>{more}</section>')  # fmt: skip

    def learn(self, uid: int, slug: str):
        wrap = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] lg:max-w-[760px] mx-auto pt-14 pb-24 lg:pt-20 lg:pb-16 bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-6">')
        end = ('<p class="font-label-micro text-label-micro text-outline text-center py-space-lg">설명을 위한 글이에요. 특정 종목이나 상품을 추천하지 않아요.</p></div></main>'
               + bottom_nav("learn"))
        if slug.startswith("big/"):  # 큰손 포트폴리오 한 곳
            return self.big(uid, slug[4:], wrap, end)
        if slug.startswith("guru/"):  # 미국 유명 투자자 한 명
            return self.guru(uid, slug[5:], wrap, end)
        a = learn.BY_SLUG.get(slug)
        if slug == "long-short":  # 숫자를 DB 의 지수로 채운 글
            a = learn.long_short(self.con) or a
        if slug == "rates":  # 숫자를 DB 의 금리로 채운 글
            a = learn.rates(self.con) or a
        if slug and not a:
            return "404 Not Found", [], self.simple("없음", "없는 글이에요. <a class='text-primary underline' href='/learn'>읽기 팁</a>")
        if a:
            stamps = quiz.done(self.con, uid)
            qs = quiz.questions(slug)
            if not qs and slug not in stamps:  # 숫자를 DB 로 채우는 글(금리·오래 들기)은 문제가 없다 — 읽으면 도장
                self.con.execute("insert or ignore into quiz_done values (?, ?, ?)", (uid, slug, datetime.now().isoformat()))
                self.con.commit()
            more_label, more_url = a["more"]
            face, credit = book_face(slug)
            inner = (wrap + '<div class="flex items-center py-space-sm"><a class="flex items-center gap-space-xs text-on-surface-variant hover:text-primary transition-colors" href="/learn"><span class="material-symbols-outlined text-[18px]">arrow_back</span>'
                     f'<span class="font-label-regular text-label-regular font-medium">읽기 팁</span></a><span class="ml-2 px-2 py-0.5 rounded-full bg-primary text-on-primary font-label-micro text-label-micro font-semibold">{e(a["cat"])}</span></div>'
                     f'<div style="display:flex;align-items:flex-end;gap:8px"><h1 class="font-display-editorial text-display-editorial text-on-surface font-semibold tracking-tight" style="flex:1;min-width:0;align-self:center;padding-bottom:14px">{e(a["title"])}</h1>{tree.perch("calm", 84)}</div>'  # 나무가 띠 위에 선다
                     + f'<aside class="my-space-xl lg:my-10 text-center" style="margin-top:0">{RULE}<p class="py-space-lg px-space-md font-body-reading-strong font-bold text-[18px] leading-[30px] lg:text-[20px] lg:leading-[34px] text-primary">{self.marked(a["lead"])}</p>{RULE_FLIP}</aside>'
                     + '<div class="block">' + face + self.flow(a["body"][:1]) + '<div class="clear-both"></div></div>'
                     + figure(learn.FIGURE.get(slug))
                     + (index_chart(a["charts"]) + loss_bars(a["charts"]) if a.get("charts") else "")
                     + (rate_ladder(a["now"], a["month"]) + rate_chart(a["rates"]) if a.get("rates") else "")
                     + '<div class="relative overflow-hidden">' + self.flow(a["body"][1:] + [x.replace("**", "") for x in learn.STORY.get(slug, [])])
                     + quiz.stamp(slug in stamps) + "</div>"  # 다 맞힌 글엔 본문 오른쪽 아래에 도장 — 가장자리에 걸쳐 조금 잘리게 (사용자 10/12)
                     + '<section class="mt-space-sm mb-space-lg rounded-xl bg-primary-fixed/40 border-l-4 border-primary px-space-md py-space-md flex flex-col gap-1.5"><span class="flex items-center gap-1 font-label-regular text-label-regular text-primary font-bold"><span class="material-symbols-outlined text-[18px]">lightbulb</span>기억할 것</span>'
                     + "".join(f'<p class="flex items-start gap-1.5 font-body-compact text-body-compact text-on-surface"><span class="material-symbols-outlined text-primary text-[16px] mt-0.5">check_circle</span><span>{self.marked(x)}</span></p>' for x in a["points"])
                     + f'</section><a class="inline-flex items-center gap-1 font-label-regular text-label-regular text-primary font-semibold hover:underline" href="{e(more_url)}" target="_blank" rel="noopener">더 알아보기: {e(more_label)}<span class="material-symbols-outlined text-[14px]">open_in_new</span></a>'
                     + quiz.block(slug, qs, slug in stamps, "세 문제로 확인하기", "다 맞혔어요. 이 글에 도장이 찍혔어요.") + quiz.JS
                     + self.related(slug) + credit
                     + '<div class="mt-space-lg flex justify-end">' + self.regram_form(uid, "learn", slug, "") + "</div>" + end)  # fmt: skip
            return "200 OK", [], page(a["title"], "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)
        # 글 목록 — 단계 로드맵(사용자 10/19: 도장은 뒤로, 단계적으로 깨는 길). 분류 하나가 한 단계 — 그 단계 글에 다 도장을 받으면 깬다.
        # 지금 단계(아직 못 깬 첫 단계)만 펼쳐 두고, 깬 단계는 ✓, 앞으로의 단계는 접어 둔다(눌러서 미리 읽을 수는 있다)
        stamps = quiz.done(self.con, uid)

        def mark(sl: str) -> str:
            cls, icon, label = (("bg-primary text-on-primary", "verified", "도장 받음") if sl in stamps else
                                ("border border-outline-variant text-outline-variant", "circle", "아직 도장 없음"))  # fmt: skip
            return f'<span aria-label="{label}" title="{label}" class="mt-0.5 w-7 h-7 shrink-0 rounded-full flex items-center justify-center {cls}"><span class="material-symbols-outlined text-[16px]">{icon}</span></span>'

        by = {c: [x for x in learn.ARTICLES if x["cat"] == c] for c in learn.CATS}
        cur = next((i for i, c in enumerate(learn.CATS) if not all(x["slug"] in stamps for x in by[c])), len(learn.CATS))
        got_all, n_all = sum(x["slug"] in stamps for x in learn.ARTICLES), len(learn.ARTICLES)

        def stage(i: int, c: str) -> str:
            arts = by[c]
            n = sum(x["slug"] in stamps for x in arts)
            icon = CAT_ICON.get(c, "menu_book")
            dot = (f'<span class="w-8 h-8 shrink-0 rounded-full {"bg-primary text-on-primary" if i <= cur else "border border-outline-variant bg-surface-container-lowest text-outline"} flex items-center justify-center">'
                   f'<span class="material-symbols-outlined text-[18px]" style="font-variation-settings:\'FILL\' 1">{"check" if i < cur else icon}</span></span>')  # fmt: skip
            tag = ("다 읽었어요" if i < cur else "지금 읽는 곳" if i == cur else "")
            bar = (f'<span class="mt-1.5 block h-1.5 w-full max-w-[220px] rounded-full bg-surface-container-high overflow-hidden"><span class="block h-full bg-primary rounded-full" style="width:{n / len(arts) * 100:.0f}%"></span></span>'
                   if i == cur else "")  # fmt: skip
            return (f'<details class="relative" style="padding-left:44px"{" open" if i == cur else ""}>'
                    f'<summary class="cursor-pointer py-3 flex items-center gap-3" style="list-style:none;margin-left:-44px">{dot}'
                    f'<span class="flex flex-col min-w-0 flex-1"><span class="flex items-center gap-2">'
                    + (f'<span class="px-1.5 py-px rounded text-[10px] font-semibold {"bg-primary text-on-primary" if i == cur else "bg-surface-container-high text-on-surface-variant"}">{tag}</span>' if tag else "")
                    + f'</span><span class="font-headline-sm text-headline-sm {"text-on-surface" if i <= cur else "text-on-surface-variant"}">{e(c)}</span>{bar}</span>'
                    f'<span class="text-[12px] text-on-surface-variant shrink-0">{n} / {len(arts)}</span></summary>'
                    '<div class="flex flex-col divide-y divide-surface-container-high/80 pb-2">'
                    + "".join(f'<a href="/learn/{e(x["slug"])}" class="py-3.5 flex items-start justify-between gap-space-sm"><div class="flex flex-col gap-0.5"><span class="font-body-reading-strong text-body-reading-strong text-on-surface">{e(x["title"])}</span>'
                              f'<span class="font-body-compact text-body-compact text-on-surface-variant">{e(x["lead"].replace("**", ""))}</span></div>{mark(x["slug"])}</a>' for x in arts)
                    + "</div></details>")  # fmt: skip

        now = (f"지금 「{learn.CATS[cur]}」를 읽고 있어요 — 글마다 세 문제를 맞히면 다음으로" if cur < len(learn.CATS) else "모든 글에 도장을 받았어요")
        groups = ('<section class="mt-space-xl pt-space-md border-t border-surface-container-high"><style>details>summary::-webkit-details-marker{display:none}</style>'
                  f'<div class="flex items-end justify-between gap-2"><div class="flex flex-col"><h2 class="font-headline-md text-headline-md text-primary border-l-4 border-primary pl-2 leading-none">나의 로드맵</h2>'
                  f'<span class="mt-2 font-body-compact text-body-compact text-on-surface-variant">{e(now)}</span></div>'
                  f'<span class="text-[12px] text-on-surface-variant shrink-0">도장 {got_all} / {n_all}</span></div>'
                  '<div class="relative mt-space-sm"><span class="absolute bg-surface-container-high" style="left:15px;top:20px;bottom:20px;width:2px"></span>'
                  + "".join(stage(i, c) for i, c in enumerate(learn.CATS)) + "</div></section>")  # fmt: skip
        inner = (wrap + '<header class="pt-5"><h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight">읽기 팁</h1>'
                 '<p class="font-body-compact text-body-compact text-on-surface-variant mt-1">주식을 처음 시작할 때 알아 두면 좋은 기초를 쉬운 말로 풀었어요.</p></header>'
                 + self.cached(f"today-big:{date.today()}", lambda: self.today_big(date.today())) + self.learn_top(date.today()) + groups + self.cached("learn", lambda: self.guru_list() + self.big_list()) + end)  # fmt: skip
        return "200 OK", [], page("읽기 팁", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)
