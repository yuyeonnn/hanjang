"""피드 — 기사·이번 주 한장·내 종목 소식"""

import json
from datetime import date, datetime, timedelta

from hanjang import holders, notes
from hanjang.notepage import CITE, EVENT_EXPLAIN, clean_title, safe_url
from hanjang.ui import Photos, bottom_nav, e, gist, kday, logo, page, story, top_bar


class FeedPages:
    def article_photo(self, aid: int, kind: str, ind: str | None, name: str, photos: "Photos | None" = None) -> str:
        """기사 사진 — 처음 고를 때 사건 종류에 맞는 주제(증자는 돈, 계약은 계약서…)로 고르고 저장한다.
        그 뒤로 피드와 기사 화면이 같은 사진을 쓴다."""
        got = self.con.execute("select photo from articles where id = ?", (aid,)).fetchone()
        if got and got[0] and not (photos and got[0] in photos.used):
            if photos:
                photos.used.add(got[0])
            return got[0]
        # 처음이거나, 이 화면에 이미 나온 사진이면 새로 고르고 저장한다 — 기사마다 따로 고르던 때 같은 계약서 사진이 나란히 붙었다
        img = (photos or Photos()).pick(kind, ind, name)
        self.con.execute("update articles set photo = ? where id = ?", (img, aid))
        self.con.commit()
        return img

    def latest(self, uid: int, photos: "Photos") -> str:
        """최근 소식 — 사건마다 쓴 기사. 최신 날짜 먼저(내 종목이라고 옛 기사가 맨 위에 붙박이지 않게 — 사용자 10/11), 같은 날 안에선 내 종목 먼저.
        같은 날·같은 무게의 기사끼리는 12시간마다 차례를 섞는다 — 새 기사는 하루 한 번(07:00) 들어와서, 그 사이에도 화면이 달라 보이게."""
        slot = int(self.clock() // (12 * 3600))
        rows = self.con.execute(
            "select a.id, a.kind, a.date, a.body, s.name, s.induty_code, a.ticker in (select ticker from holdings where user_id = ?) mine"
            " from articles a join stocks s using(ticker) order by a.date desc, mine desc, (a.id * 7919 + ?) % 97, a.id desc limit 30", (uid, slot)).fetchall()  # fmt: skip
        if not rows:
            return ""
        items = "".join(
            story(f"/a/{i}", self.article_photo(i, k, ind, name, photos),
                  (b := json.loads(body))["title"], b["paragraphs"][0]["text"], name + (" · 내 종목" if mine else ""), d.replace("-", "."))
            for i, k, d, body, name, ind, mine in rows)  # fmt: skip
        return (f'<section class="mt-space-lg"><h2 class="font-headline-sm text-headline-sm text-on-surface">최근 소식</h2>'
                f'<div class="flex flex-col lg:grid lg:grid-cols-2 lg:gap-x-14">{items}</div></section>')  # fmt: skip

    def article(self, uid: int, aid: int):
        row = self.con.execute("select a.ticker, a.kind, a.date, a.body, s.name, s.induty_code from articles a join stocks s using(ticker)"
                               " where a.id = ?", (aid,)).fetchone()  # fmt: skip
        if not row:
            return "404 Not Found", [], self.simple("없음", "없는 기사예요. <a class='text-primary underline' href='/feed'>피드</a>")
        t, kind, d, body, name, ind = row
        b = json.loads(body)
        img = self.article_photo(aid, kind, ind, name)

        def strong(text: str, marks: list[str]) -> str:
            """강조할 말(articles.emphasize 가 고른, 본문에 그대로 있는 말)만 읽기 팁처럼 진한 초록 굵은 글씨로. 겹치면 먼저 고른 것만."""
            spans: list[tuple[int, int]] = []
            for m in marks:
                i = text.find(m)
                if i >= 0 and all(i >= b or i + len(m) <= a for a, b in spans):
                    spans.append((i, i + len(m)))
            out, k = "", 0
            for a, b in sorted(spans):
                out += e(text[k:a]) + f'<strong class="font-semibold text-primary">{e(text[a:b])}</strong>'
                k = b
            return out + e(text[k:])

        def cite(p):  # 출처 번호 → 원문 바로 열기 (작은 회색 위첨자)
            return strong(p["text"], p.get("marks", [])) + "".join(f'<a class="{CITE}" href="{e(safe_url(b["links"].get(r, "#")))}" target="_blank" rel="noopener">[{e(r)}]</a>' for r in p["refs"])

        paras = "".join(f'<p class="text-[15px] leading-[27px] text-on-surface mb-4">{cite(p)}</p>' for p in b["paragraphs"])
        inner = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] lg:max-w-[760px] mx-auto pt-14 pb-24 lg:pt-20 lg:pb-16 bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-6">'
                 '<a class="pt-4 flex items-center gap-space-xs text-on-surface-variant hover:text-primary" href="/feed"><span class="material-symbols-outlined text-[18px]">arrow_back</span><span class="font-label-regular text-label-regular">피드</span></a>'
                 f'<h1 class="mt-space-sm text-[22px] leading-[30px] font-bold tracking-tight text-on-surface">{e(b["title"])}</h1>'
                 f'<p class="mt-1 text-[12px] text-outline">{e(name)} · {e(d.replace("-", "."))}</p>'
                 f'<img alt="" class="mt-space-md w-full aspect-[16/10] object-cover rounded-xl" src="{e(img)}">'
                 '<p class="mt-1 text-right text-[11px] text-outline">주제 사진 · Unsplash</p>'
                 f'<article class="mt-space-md">{paras}</article>'
                 + '<div class="mt-space-sm mb-space-sm flex justify-end">' + self.regram_form(uid, "article", str(aid), "") + "</div>"
                 f'<a class="mt-space-sm flex items-center justify-between rounded-xl border border-outline-variant/50 px-space-md py-3" href="/n/{e(t)}">'
                 f'<span class="flex items-center gap-2">{logo(name, self.con.execute("select homepage from stocks where ticker = ?", (t,)).fetchone()[0], "w-8 h-8")}'
                 f'<span class="text-[14px] font-semibold text-on-surface">{e(name)} 분석 보고서 보기</span></span><span class="material-symbols-outlined text-outline">chevron_right</span></a>'
                 '<p class="mt-space-md text-[11px] text-outline leading-relaxed">공시 원문·사업보고서·재무·회사 뉴스룸 요약문을 바탕으로 AI가 쓴 글이에요. 숫자는 코드가 원문과 대조했어요. 작은 번호를 누르면 원문이 열려요. 사라·팔아라는 뜻이 아니에요.</p>'
                 + "</div></main>" + bottom_nav("feed"))  # fmt: skip
        return "200 OK", [], page(b["title"], "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    def popular(self, photos: "Photos") -> str:
        """팔로우한 사람의 리그램이 없을 때 — 이번 주 노트를 많이 읽힌 순서로."""
        rows = self.con.execute(
            "select s.ticker, s.name, n.body, s.induty_code, n.made_at,"
            " (select count(*) from views v where v.page = 'note' and v.ticker = s.ticker and v.at >= n.week) c"
            " from notes n join stocks s using(ticker) where n.week = (select max(week) from notes) order by c desc, s.name limit 20").fetchall()  # fmt: skip
        cards = "".join(story(f"/n/{t}", photos.pick(None, ind, name), notes.mend(json.loads(b)["headline"]), gist(json.loads(b)), name, made[:10].replace("-", "."))
                        for t, name, b, ind, made, c in rows)  # fmt: skip
        return (f'<section class="mt-space-lg"><h2 class="font-headline-sm text-headline-sm text-on-surface">많이 읽은 노트</h2>'
                f'<div class="flex flex-col lg:grid lg:grid-cols-2 lg:gap-x-14">{cards}</div></section>')  # fmt: skip

    def tally(self, end: datetime) -> tuple[list, list]:
        """end 앞 7일 — 담은 종목 [(ticker, name, 담은 사람, 담은 사람)] · 읽은 노트 [(ticker, name, 읽은 사람, 조회수)], 많은 순."""
        a, b = (end - timedelta(days=7)).isoformat(), end.isoformat()
        held = self.con.execute("select s.ticker, s.name, count(*), count(*) from holdings h join stocks s using(ticker) where h.added_at >= ? and h.added_at < ?"
                                " group by s.ticker order by count(*) desc, s.name", (a, b)).fetchall()  # fmt: skip
        read = self.con.execute("select s.ticker, s.name, count(distinct v.user_id), count(*) from views v join stocks s using(ticker) where v.page = 'note' and v.at >= ? and v.at < ?"
                                " group by s.ticker order by count(distinct v.user_id) desc, count(*) desc, s.name", (a, b)).fetchall()  # fmt: skip
        return held, read

    def this_week(self) -> str:
        """이번 주 한장 — 몇 명인지는 적지 않고 오르내림만 (배민 순위처럼, 사용자 10/10). 정각마다 새로 센다.
        하루 전보다 담은 사람·조회수가 조금이라도 늘면 ▲, 줄면 ▼, 같으면 – (NEW 는 쓰지 않는다, 사용자 10/10).
        3명 이상일 때만 순위에 — 사람이 적을 때 누가 무엇을 담았는지 짐작되지 않게."""
        now = datetime.now().replace(minute=0, second=0, microsecond=0)
        return self.cached(f"week:{now.isoformat()}", lambda: self._this_week(now))  # 정각마다 한 번만 센다 — 피드를 열 때마다 세면 열람 30만 줄에서 70ms 가 모두의 기다림 (규모 점검 10/11)

    def _this_week(self, now: datetime) -> str:
        cur, prev = self.tally(now), self.tally(now - timedelta(days=1))
        up = '<span class="text-[#E5534B] text-[12px]" aria-label="올랐어요">▲</span>'
        down = '<span class="text-[#3B7DDD] text-[12px]" aria-label="내렸어요">▼</span>'
        same = '<span class="text-outline-variant text-[12px]" aria-label="그대로">–</span>'

        def col(title, rows, before):
            rows = [r for r in rows if r[2] >= 3][:5]
            if not rows:
                return ""
            was = {t: v for t, _, _, v in before}
            mark = lambda t, v: up if v > was.get(t, 0) else down if v < was.get(t, 0) else same  # noqa: E731
            items = "".join(f'<a href="/n/{e(t)}" class="py-2.5 flex items-center gap-3"><b class="w-5 text-[16px] text-on-surface tabular-nums">{k + 1}</b>'
                            f'<span class="flex-1 text-[15px] text-on-surface truncate">{e(n)}</span>{mark(t, v)}</a>'
                            for k, (t, n, _, v) in enumerate(rows))  # fmt: skip
            return f'<div><h3 class="text-[13px] font-semibold text-outline">{title}</h3><div class="flex flex-col">{items}</div></div>'

        body = col("많이 담은 종목", cur[0], prev[0]) + col("많이 읽은 노트", cur[1], prev[1])
        when = f'{"오전" if now.hour < 12 else "오후"} {now.hour % 12 or 12}시 업데이트'
        return (f'<section class="mt-space-lg"><h2 class="font-headline-sm text-headline-sm text-on-surface">이번 주 한장</h2>'
                f'<div class="mt-space-sm"><p class="text-[13px] text-outline mb-2">{when}</p>'
                f'<div class="grid grid-cols-1 lg:grid-cols-2 gap-x-14 gap-y-4">{body}</div></div></section>') if body else ""

    def my_events(self, uid: int, today: date | None = None, ticker: str | None = None) -> list[tuple]:
        """담은 종목에 생긴 일 — 점수 큰 순. 「내 종목」 카드가 종목마다 맨 위 것을 보여 준다(피드의 「오늘의 내 종목」을 옮김, 사용자 10/11).
        재료: ① 최근 7일 큰 공시 ② 앞으로 14일 일정(실적 발표·주총·배당) ③ 큰손 움직임(기관 5% 지분 변화 30일 · 임원 거래 14일).
        점수 = 종류의 무게 − 날짜가 먼 만큼. 내 종목만 — 남의 글·추천이 아니라 사실만 모은다.
        [(점수, 아이콘, 색, 종목 이름, 홈페이지, 한 줄, 작은 글, 날짜 표시, 링크, 종목코드)]"""
        today = today or date.today()
        iso = today.isoformat()
        back = lambda n: (today - timedelta(days=n)).isoformat()  # noqa: E731
        mine = "join holdings h on h.ticker = s.ticker and h.user_id = ?"
        if ticker:  # 노트 화면 — 담았든 아니든 그 종목 하나의 일
            mine, uid = "join (select ? as tk) x on x.tk = s.ticker", ticker
        cards = []  # (점수, 아이콘, 색, 종목 이름, 홈페이지, 한 줄, 작은 글, 날짜 표시, 링크)

        def ago(d: str) -> str:
            n = (today - date.fromisoformat(d)).days
            return "오늘" if n <= 0 else "어제" if n == 1 else f"{n}일 전"

        for rno, d, title, code, imp, dr, t, name, home, aid in self.con.execute(
                "select d.rcept_no, d.date, d.title, d.code, d.importance, d.direction, s.ticker, s.name, s.homepage,"
                " (select a.id from articles a where a.ref = d.rcept_no)"
                f" from disclosures d join stocks s on s.ticker = d.ticker {mine}"
                " where d.date between ? and ? and d.importance >= 2 and d.code != 'OTHER' order by d.date desc", (uid, back(7), iso)):  # fmt: skip
            n = (today - date.fromisoformat(d)).days
            cards.append((100 - 10 * n + 5 * (imp or 0), "campaign", "text-primary", name, home, clean_title(title, code),
                          EVENT_EXPLAIN.get(code, ""), ago(d), f"/a/{aid}" if aid else f"/n/{t}", t))
        for d, kind, what, t, name, home in self.con.execute(
                f"select e.date, e.kind, e.title, s.ticker, s.name, s.homepage from events e join stocks s on s.ticker = e.ticker {mine}"
                " where e.date between ? and ? order by e.date", (uid, iso, (today + timedelta(days=14)).isoformat())):  # fmt: skip
            n = (date.fromisoformat(d) - today).days
            cards.append((95 - 5 * n, "event_upcoming", "text-secondary", name, home, what,
                          f'{kday(d)}에 예정돼 있어요.', "오늘" if n == 0 else f"D-{n}", "/calendar", t))
        for inst, rate, chg, d, t, name, home in self.con.execute(
                f"select b.inst, b.rate, b.rate_chg, b.date, s.ticker, s.name, s.homepage from big_holdings b join stocks s on s.ticker = b.stock_code {mine}"
                " where b.rate_chg is not null and b.rate_chg != 0 and b.date >= ? order by b.date desc", (uid, back(30))):  # fmt: skip
            if inst not in holders.BIG:
                continue
            n = (today - date.fromisoformat(d)).days
            who = holders.BIG[inst][0]
            cards.append((70 - 2 * n, "account_balance", "text-tertiary", name, home, f'{who}{notes.josa(who, "이")} 지분을 {"늘렸어요" if chg > 0 else "줄였어요"}',
                          f"지분 {rate:.2f}% ({chg:+.2f}%p) — 5% 넘게 가진 기관이 낸 보고예요.", ago(d), f"/learn/big/{inst}", t))
        for t, name, home, cnt, net, last in self.con.execute(
                f"select s.ticker, s.name, s.homepage, count(*), sum(i.change), max(i.date) from insiders i join stocks s on s.ticker = i.ticker {mine}"
                " where i.kind = '임원' and i.date >= ? group by s.ticker", (uid, back(14))):  # fmt: skip
            n = (today - date.fromisoformat(last)).days
            side = "사들인 쪽이 많아요" if (net or 0) > 0 else "판 쪽이 많아요" if (net or 0) < 0 else "사고판 양이 비슷해요"
            cards.append((60 - 3 * n, "badge", "text-outline", name, home, f"임원 주식 거래 보고 {cnt}건", f"최근 2주 동안 {side}. 회사에서 받은 보상 주식도 들어 있을 수 있어요.", ago(last), f"/n/{t}", t))
        cards.sort(key=lambda c: -c[0])
        return cards

    def feed(self, uid: int, q: str) -> str:
        mine = "where r.user_id in (select followee_id from follows where follower_id = ? and ok = 1) or r.user_id = ?"
        (n,) = self.con.execute("select count(*) from regrams r " + mine, (uid, uid)).fetchone()
        photos = Photos()
        news = self.latest(uid, photos)
        body = self.this_week() + news + (self.regram_list(mine, (uid, uid), "팔로우한 사람들의 리그램", photos=photos) if n else "") + ("" if news or n else self.popular(photos))
        inner = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] lg:max-w-[1200px] mx-auto pt-14 pb-24 lg:pt-20 lg:pb-16 bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-6">'
                 '<header class="pt-5"><h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight">피드</h1></header>'
                 + '<form method="get" action="/feed" class="mt-space-md flex items-center gap-space-sm bg-surface-container-low rounded-xl px-4 py-2.5"><span class="material-symbols-outlined text-outline text-[20px]">person_search</span>'
                 f'<input class="flex-1 bg-transparent font-body-compact text-body-compact focus:outline-none" name="q" value="{e(q)}" placeholder="닉네임으로 사람 찾기"></form>'
                 + self.people(uid, q) + body
                 + "</div></main>" + bottom_nav("feed"))  # fmt: skip
        return page("피드", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)
