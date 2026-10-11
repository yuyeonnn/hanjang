"""읽기 팁·공개 문서(처리방침·계산 방법·이용 규칙)"""

import re
from datetime import date, datetime
from hanjang import quiz

from hanjang import learn, policy, sources
from hanjang.charts import groups, index_chart, loss_bars, rate_chart, rate_ladder
from hanjang.notepage import figure, paras
from hanjang.ui import RULE, RULE_FLIP, book_face, bottom_nav, e, mark, page, top_bar


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

    def learn_top(self, uid: int, stamps: set) -> str:
        """읽기 팁 맨 위 — 오늘의 한 문제(그 자리에서 푼다) (사용자 10/12)."""
        key, q = quiz.daily(self.con, uid, date.today())
        return quiz.block(key, [q], key in stamps, "오늘의 한 문제", "맞혔어요. 내일 새 문제가 나와요.") + quiz.JS

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
            qs = quiz.questions(self.con, uid, slug)
            if not qs and slug not in stamps:  # 숫자를 DB 로 채우는 글(금리·오래 들기)은 문제가 없다 — 읽으면 도장
                self.con.execute("insert or ignore into quiz_done values (?, ?, ?)", (uid, slug, datetime.now().isoformat()))
                self.con.commit()
            more_label, more_url = a["more"]
            face, credit = book_face(slug)
            inner = (wrap + '<div class="flex items-center py-space-sm"><a class="flex items-center gap-space-xs text-on-surface-variant hover:text-primary transition-colors" href="/learn"><span class="material-symbols-outlined text-[18px]">arrow_back</span>'
                     f'<span class="font-label-regular text-label-regular font-medium">읽기 팁</span></a><span class="ml-2 px-2 py-0.5 rounded-full bg-primary text-on-primary font-label-micro text-label-micro font-semibold">{e(a["cat"])}</span></div>'
                     f'<h1 class="font-display-editorial text-display-editorial text-on-surface font-semibold tracking-tight mb-space-sm">{e(a["title"])}</h1>'
                     + f'<aside class="my-space-xl lg:my-10 text-center">{RULE}<p class="py-space-lg px-space-md font-body-reading-strong font-bold text-[18px] leading-[30px] lg:text-[20px] lg:leading-[34px] text-primary">{self.marked(a["lead"])}</p>{RULE_FLIP}</aside>'
                     + '<div class="block">' + face + self.flow(a["body"][:1]) + '<div class="clear-both"></div></div>'
                     + figure(learn.FIGURE.get(slug))
                     + (index_chart(a["charts"]) + loss_bars(a["charts"]) if a.get("charts") else "")
                     + (rate_ladder(a["now"], a["month"]) + rate_chart(a["rates"]) if a.get("rates") else "")
                     + self.flow(a["body"][1:] + [x.replace("**", "") for x in learn.STORY.get(slug, [])])
                     + '<section class="mt-space-sm mb-space-lg rounded-xl bg-primary-fixed/40 border-l-4 border-primary px-space-md py-space-md flex flex-col gap-1.5"><span class="flex items-center gap-1 font-label-regular text-label-regular text-primary font-bold"><span class="material-symbols-outlined text-[18px]">lightbulb</span>기억할 것</span>'
                     + "".join(f'<p class="flex items-start gap-1.5 font-body-compact text-body-compact text-on-surface"><span class="material-symbols-outlined text-primary text-[16px] mt-0.5">check_circle</span><span>{self.marked(x)}</span></p>' for x in a["points"])
                     + f'</section><a class="inline-flex items-center gap-1 font-label-regular text-label-regular text-primary font-semibold hover:underline" href="{e(more_url)}" target="_blank" rel="noopener">더 알아보기: {e(more_label)}<span class="material-symbols-outlined text-[14px]">open_in_new</span></a>'
                     + quiz.block(slug, qs, slug in stamps, "세 문제로 확인하기", "다 맞혔어요. 이 글에 도장이 찍혔어요.") + quiz.JS
                     + self.related(slug) + credit
                     + '<div class="mt-space-lg flex justify-end">' + self.regram_form(uid, "learn", slug, "") + "</div>" + end)  # fmt: skip
            return "200 OK", [], page(a["title"], "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)
        # 글 목록 — 놓인 차례가 곧 읽는 차례. 글마다 오른쪽 끝에 도장(다 맞힘) · 옅은 체크(읽음) · 빈 동그라미 (사용자 10/12: 따로 떼지 말고 글 옆에)
        stamps = quiz.done(self.con, uid)
        read = {r[0] for r in self.con.execute("select distinct ticker from views where user_id = ? and page = 'learn' and ticker is not null", (uid,))}

        def mark(sl: str) -> str:
            cls, icon, label = (("bg-primary text-on-primary", "verified", "도장 받음") if sl in stamps else
                                ("bg-primary-fixed text-primary", "check", "읽음") if sl in read else ("border border-outline-variant text-outline-variant", "circle", "아직 안 읽음"))  # fmt: skip
            return f'<span aria-label="{label}" title="{label}" class="mt-0.5 w-7 h-7 shrink-0 rounded-full flex items-center justify-center {cls}"><span class="material-symbols-outlined text-[16px]">{icon}</span></span>'

        groups = "".join(
            f'<section class="mt-space-xl pt-space-md border-t border-surface-container-high"><div class="flex items-center justify-between mb-space-sm"><h2 class="font-headline-md text-headline-md text-primary border-l-4 border-primary pl-2 leading-none">{e(c)}</h2>'
            f'<span class="text-[12px] text-on-surface-variant">도장 {sum(x["slug"] in stamps for x in arts)} / {len(arts)}</span></div>'
            f'<div class="flex flex-col divide-y divide-surface-container-high/80">'
            + "".join(f'<a href="/learn/{e(x["slug"])}" class="py-3.5 flex items-start justify-between gap-space-sm"><div class="flex flex-col gap-0.5"><span class="font-body-reading-strong text-body-reading-strong text-on-surface">{e(x["title"])}</span>'
                      f'<span class="font-body-compact text-body-compact text-on-surface-variant">{e(x["lead"].replace("**", ""))}</span></div>{mark(x["slug"])}</a>'
                      for x in arts) + "</div></section>" for c in learn.CATS for arts in [[x for x in learn.ARTICLES if x["cat"] == c]])  # fmt: skip
        inner = (wrap + '<header class="pt-5"><h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight">읽기 팁</h1>'
                 '<p class="font-body-compact text-body-compact text-on-surface-variant mt-1">주식을 처음 시작할 때 알아 두면 좋은 기초를 쉬운 말로 풀었어요.</p></header>'
                 + self.learn_top(uid, stamps) + groups + self.cached("learn", lambda: self.guru_list() + self.big_list()) + end)  # fmt: skip
        return "200 OK", [], page("읽기 팁", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)
