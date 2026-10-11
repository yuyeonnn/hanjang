"""큰손 포트폴리오·유명 투자자"""

from hanjang import gurus, holders, notes, sources
from hanjang.charts import TOP_LIST, bars, ind_tag, issuer_name, pie
from hanjang.ui import DART_VIEW, PEOPLE, e, guru_face, kdate, logo, page, row, sector


class BigPages:
    def big_list(self) -> str:
        counts = dict(self.con.execute("select inst, count(*) from big_holdings group by inst").fetchall())
        rows = [(k, v) for k, v in holders.BIG.items() if counts.get(k)]
        if not rows:
            return ""
        rows.sort(key=lambda kv: -counts[kv[0]])
        items = "".join(
            f'<a href="/learn/big/{k}" class="py-3.5 flex items-center gap-space-md">{logo(name, self.BIG_HOME.get(k), "w-10 h-10")}'
            f'<span class="flex flex-col min-w-0 flex-1"><span class="font-body-reading-strong text-body-compact text-on-surface">{e(name)}</span>'
            f'<span class="font-label-micro text-label-micro text-on-surface-variant truncate">{e(intro)}</span></span>'
            f'<span class="text-[12px] text-outline shrink-0">{counts[k]:,}종목</span></a>' for k, (name, _, intro) in rows)  # fmt: skip
        return ('<section class="mt-space-xl pt-space-md border-t border-surface-container-high"><h2 class="font-headline-md text-headline-md text-primary border-l-4 border-primary pl-2 leading-none">큰손 포트폴리오</h2>'
                '<p class="mt-2 font-body-compact text-body-compact text-on-surface-variant">국민연금·운용사 같은 기관이 5% 넘게 가진 회사들이에요. 공시로 알려진 것만 보여요.</p>'
                f'<div class="flex flex-col divide-y divide-surface-container-high/80">{items}</div></section>')  # fmt: skip

    def nps_portfolio(self, after_pie: str = "") -> str:
        """국민연금 주식 — 한국(국민연금 연간 공시 평가액)과 미국(같은 날 13F, 한국은행 환율로 원화)을 금액 큰 순 하나로. 파이도 그 비중."""
        rows = self.con.execute(
            "select p.market, p.name, p.ticker, p.won, s.name, s.homepage, exists(select 1 from notes n where n.ticker = p.ticker),"
            " coalesce(s.induty_code, (select b.induty_code from big_holdings b where b.stock_code = p.ticker limit 1)), s.sic"
            " from nps_port p left join stocks s on s.ticker = p.ticker order by p.won desc").fetchall()  # fmt: skip
        meta = self.con.execute("select asof, fx from nps_meta order by asof desc limit 1").fetchone()
        if not rows or not meta:
            return ""
        total = sum(r[3] for r in rows)
        n_kr = sum(r[0] == "KR" for r in rows)

        def label(r):
            mkt, name, _, _, kname, *_ = r
            return name if mkt == "KR" else issuer_name(name, kname)

        def line(i, r):
            mkt, name, t, won, _, home, has_note, kr, sic = r
            tag = ('<span class="ml-1.5 px-1.5 py-px rounded text-[10px] font-semibold align-middle '
                   + ("bg-surface-container-high text-on-surface-variant\">한국" if mkt == "KR" else "bg-secondary-container text-on-secondary-container\">미국") + "</span>")
            inner = (f'<span class="w-5 text-right text-[12px] text-outline tabular-nums">{i}</span>{logo(label(r), home, "w-9 h-9")}'
                     f'<span class="flex flex-col min-w-0 flex-1"><span class="flex items-baseline gap-1.5 min-w-0"><span class="text-[15px] font-semibold text-on-surface truncate">{e(label(r))}{tag}</span>'
                     f'{ind_tag(kr if mkt == "KR" else None, sic, name)}</span>'
                     f'<span class="text-[12px] text-on-surface-variant">비중 {won / total * 100:.1f}% · {e(sources.won_short(won))}</span></span>')  # fmt: skip
            return f'<a href="/n/{e(t)}" class="py-3 flex items-center gap-3">{inner}</a>' if has_note else f'<div class="py-3 flex items-center gap-3">{inner}</div>'

        return ('<section class="mt-space-xl pt-space-md border-t border-surface-container-high"><h2 class="font-headline-md text-headline-md text-on-surface">주식 포트폴리오 · 한국+미국</h2>'
                + pie([(label(r), r[3]) for r in rows]) + after_pie
                + '<div class="mt-space-sm flex flex-col divide-y divide-surface-container-high/70">' + "".join(line(i, r) for i, r in enumerate(rows[:TOP_LIST], 1)) + "</div>"
                + (f'<p class="pt-2 text-[12px] text-outline">외 {len(rows) - TOP_LIST:,}종목</p>' if len(rows) > TOP_LIST else "")
                + '<p class="mt-2 text-[11px] text-outline leading-relaxed">한국 주식은 국민연금이 공개한 종목별 평가액(공공데이터포털 「국민연금공단_국내주식 투자정보」), '
                + f'미국 주식은 같은 날 미국 증권거래위원회(SEC)에 낸 보유 신고(13F)예요. 달러는 그날 한국은행 환율(1달러 {meta[1]:,.1f}원)로 바꿨어요. '
                + f'한국 {n_kr:,}종목 · 미국 {len(rows) - n_kr:,}종목. 1년에 한 번 나오는 공시라 지금과 다를 수 있어요.</p></section>')  # fmt: skip

    def us_portfolio(self, key: str, after_pie: str = "") -> str:
        """기관의 미국 주식 — 13F 로 보유 전체가 공개된다(국내 5% 보고와 달리). 파이 + 큰 10종목."""
        rows = self.con.execute(
            "select g.issuer, g.ticker, g.value, g.weight, g.period, s.name, s.homepage, exists(select 1 from notes n where n.ticker = g.ticker),"
            " coalesce(nullif(g.sic, ''), s.sic)"
            " from guru_holdings g left join stocks s on s.ticker = g.ticker where g.guru = ? order by g.value desc", (key,)).fetchall()  # fmt: skip
        if not rows:
            return ""
        total = sum(r[2] for r in rows)

        def line(i, r):
            issuer, t, value, weight, _, kname, khome, has_note, sic = r
            label = issuer_name(issuer, kname)
            inner = (f'<span class="w-5 text-right text-[12px] text-outline tabular-nums">{i}</span>{logo(label, khome, "w-9 h-9")}'
                     f'<span class="flex flex-col min-w-0 flex-1"><span class="flex items-baseline gap-1.5 min-w-0"><span class="text-[15px] font-semibold text-on-surface truncate">{e(label)}</span>{ind_tag(sic=sic, issuer=issuer)}</span>'
                     f'<span class="text-[12px] text-on-surface-variant">비중 {weight:.1f}% · {e(notes.usd(value))}</span></span>')  # fmt: skip
            return f'<a href="/n/{e(t)}" class="py-3 flex items-center gap-3">{inner}</a>' if has_note else f'<div class="py-3 flex items-center gap-3">{inner}</div>'

        return ('<section class="mt-space-xl pt-space-md border-t border-surface-container-high"><h2 class="font-headline-md text-headline-md text-on-surface">미국 주식 포트폴리오</h2>'
                f'<p class="mt-1 text-[12px] text-outline">미국 주식 {len(rows):,}종목 · {e(notes.usd(total))} · {kdate(rows[0][4])} 기준</p>'
                + pie([(issuer_name(r[0], r[5]), r[2]) for r in rows]) + after_pie
                + '<div class="mt-space-sm flex flex-col divide-y divide-surface-container-high/70">' + "".join(line(i, r) for i, r in enumerate(rows[:TOP_LIST], 1)) + "</div>"
                + (f'<p class="pt-2 text-[12px] text-outline">외 {len(rows) - TOP_LIST:,}종목</p>' if len(rows) > TOP_LIST else "")
                + '<p class="mt-2 text-[11px] text-outline leading-relaxed">미국은 큰 투자자가 분기마다 미국 주식 보유 전체를 미국 증권거래위원회(SEC)에 신고해요(13F). '
                "분기가 끝나고 45일 안에 나와서 지금과 다를 수 있어요. 미국 밖 주식은 들어 있지 않아요.</p></section>")  # fmt: skip

    def owners(self, ticker: str) -> tuple:
        """(제목, 설명, [(이름, 링크, 홈페이지, 한 줄)]) — 미국은 13F 유명 투자자(비중 큰 순), 국내는 5% 넘게 가진 기관(지분 큰 순)."""
        got = self.con.execute("select guru, weight, period from guru_holdings where ticker = ? order by weight desc", (ticker,)).fetchall()
        if got:  # 유명 투자자가 먼저, 그다음 기관 — 블랙록처럼 모든 종목을 조금씩 가진 곳이 위를 덮지 않게
            rows = ([(gurus.GURUS[k][0], f"/learn/guru/{k}", guru_face(k, "w-9 h-9"), f"포트폴리오의 {w:.1f}% · {kdate(p)} 기준") for k, w, p in got if k in gurus.GURUS]
                    + [(holders.BIG[k][0], f"/learn/big/{k}", logo(holders.BIG[k][0], self.BIG_HOME.get(k), "w-9 h-9"), f"미국 주식의 {w:.1f}% · {kdate(p)} 기준")
                       for k, w, p in got if k in holders.BIG and k not in gurus.GURUS])  # fmt: skip
            return ("이 종목을 가진 유명 투자자·기관",
                    "미국 투자자가 분기마다 내는 보유 신고(SEC 13F)예요. 분기가 끝나고 45일 안에 나와서 지금과 다를 수 있어요. 따라 사고팔라는 뜻이 아니에요.", rows)
        kr = self.con.execute("select inst, rate, date from big_holdings where stock_code = ? order by rate desc", (ticker,)).fetchall()
        rows = [(holders.BIG[k][0], f"/learn/big/{k}", logo(holders.BIG[k][0], self.BIG_HOME.get(k), "w-9 h-9"), f"지분 {r:.2f}% · {kdate(d)} 보고")
                for k, r, d in kr if k in holders.BIG]  # fmt: skip
        return ("이 종목을 5% 넘게 가진 기관", "5% 넘게 가지면 내는 대량보유 보고(DART)로 알려진 것만이에요. 따라 사고팔라는 뜻이 아니에요.", rows)

    def guru_list(self) -> str:
        got = {k: n for k, n in self.con.execute("select guru, count(*) from guru_holdings group by guru")}
        keys = [k for k in gurus.GURUS if k in got]
        if not keys:
            return ""
        items = "".join(
            f'<a href="/learn/guru/{k}" class="py-3.5 flex items-center gap-space-md">{guru_face(k)}'
            f'<span class="flex flex-col min-w-0 flex-1"><span class="font-body-reading-strong text-body-compact text-on-surface">{e(gurus.GURUS[k][0])}</span>'
            f'<span class="font-label-micro text-label-micro text-on-surface-variant truncate">{e(gurus.GURUS[k][2])}</span></span>'
            f'<span class="text-[12px] text-outline shrink-0">{got[k]:,}종목</span></a>' for k in keys)  # fmt: skip
        return ('<section class="mt-space-xl pt-space-md border-t border-surface-container-high"><h2 class="font-headline-md text-headline-md text-primary border-l-4 border-primary pl-2 leading-none">미국 유명 투자자</h2>'
                '<p class="mt-2 font-body-compact text-body-compact text-on-surface-variant">워런 버핏·캐시 우드 같은 투자자가 분기마다 미국 증권거래위원회(SEC)에 낸 보유 종목이에요.</p>'
                f'<div class="flex flex-col divide-y divide-surface-container-high/80">{items}</div></section>')  # fmt: skip

    def guru(self, uid: int, key: str, wrap: str, end: str):
        if key not in gurus.GURUS:
            return "404 Not Found", [], self.simple("없음", "없는 투자자예요. <a class='text-primary underline' href='/learn'>읽기 팁</a>")
        name, cik, intro, home = gurus.GURUS[key]
        def build():
            rows = self.con.execute(
                "select g.issuer, g.ticker, g.value, g.weight, g.period, g.filed, g.accn, s.name, s.homepage,"
                " exists(select 1 from notes n where n.ticker = g.ticker), g.sic from guru_holdings g left join stocks s on s.ticker = g.ticker"
                " where g.guru = ? order by g.value desc", (key,)).fetchall()  # fmt: skip
            if not rows:
                return None
            period, filed, accn = rows[0][4], rows[0][5], rows[0][6]
            total = sum(r[2] for r in rows)
            sec_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn.replace('-', '')}/"
            top_pie = pie([(issuer_name(r[0], r[7]), r[2]) for r in rows])
            pie_ = bars([gurus.sector(r[10], r[0]) for r in rows], [r[2] for r in rows], "종목",
                        "가진 종목을 금액으로 큰 업종(SEC 산업분류)에 나눈 비율이에요. 업종을 못 찾은 회사는 기타에 넣었어요.")

            def row(i, r):
                issuer, t, value, weight, _, _, _, kname, khome, has_note, sic = r
                label = issuer_name(issuer, kname)
                inner = (f'<span class="w-5 text-right text-[12px] text-outline tabular-nums">{i}</span>{logo(label, khome, "w-9 h-9")}'
                         f'<span class="flex flex-col min-w-0 flex-1"><span class="flex items-baseline gap-1.5 min-w-0"><span class="text-[15px] font-semibold text-on-surface truncate">{e(label)}</span>{ind_tag(sic=sic, issuer=issuer)}</span>'
                         f'<span class="text-[12px] text-on-surface-variant">비중 {weight:.1f}% · {e(notes.usd(value))}</span></span>')  # fmt: skip
                if has_note:  # 우리 노트가 있는 종목만 누르면 노트로
                    return f'<a href="/n/{e(t)}" class="py-3 flex items-center gap-3">{inner}<span class="material-symbols-outlined text-outline text-[18px]">chevron_right</span></a>'
                return f'<div class="py-3 flex items-center gap-3">{inner}</div>'

            top = rows[:TOP_LIST]
            body = (f'<div class="flex items-center py-space-sm"><a class="flex items-center gap-space-xs text-on-surface-variant hover:text-primary" href="/learn"><span class="material-symbols-outlined text-[18px]">arrow_back</span><span class="font-label-regular text-label-regular font-medium">읽기 팁</span></a></div>'
                    f'<header class="flex items-center gap-space-md">{guru_face(key, "w-14 h-14")}<div class="flex flex-col"><h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight">{e(name)}</h1>'
                    f'<span class="text-[12px] text-outline">미국 주식 {len(rows):,}종목 · {e(notes.usd(total))} · {kdate(period)} 기준</span></div></header>'
                    f'<p class="mt-space-md font-body-compact text-body-compact text-on-surface">{e(intro)}</p>' + top_pie + pie_
                    + '<section class="mt-space-lg"><h2 class="font-headline-sm text-headline-sm text-on-surface">많이 가진 순서</h2><div class="flex flex-col divide-y divide-surface-container-high/70">'
                    + "".join(row(i, r) for i, r in enumerate(top, 1)) + "</div>"
                    + (f'<p class="pt-2 text-[12px] text-outline">외 {len(rows) - len(top):,}종목</p>' if len(rows) > len(top) else "") + "</section>"
                    + '<p class="mt-space-md text-[11px] text-outline leading-relaxed">미국은 운용 자산이 1억 달러가 넘는 투자자가 분기마다 미국 주식 보유를 신고해요(13F). '
                    + f'{kdate(period)} 기준, {kdate(filed)}에 낸 신고예요. 분기가 끝나고 45일 안에 나와서 지금은 다를 수 있고, 미국 밖 주식·현금·공매도는 들어 있지 않아요. '
                    + f'따라 사고팔라는 뜻이 아니에요. 자료: <a class="underline" href="{e(sec_url)}" target="_blank" rel="noopener">SEC 13F 원문</a>'
                    + (f' · 사진: <a class="underline" href="{e(PEOPLE[key][2])}" target="_blank" rel="noopener">{e(PEOPLE[key][0])}</a>, {e(PEOPLE[key][1])}, 위키미디어 공용'
                       if key in PEOPLE else "") + '</p>')  # fmt: skip
            return body

        body = self.cached(f"guru:{key}", build)
        if body is None:
            return "404 Not Found", [], self.simple("없음", "아직 받은 신고가 없어요. <a class='text-primary underline' href='/learn'>읽기 팁</a>")
        return "200 OK", [], page(name, "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", wrap + body + end)

    def big(self, uid: int, key: str, wrap: str, end: str):
        if key not in holders.BIG:
            return "404 Not Found", [], self.simple("없음", "없는 기관이에요. <a class='text-primary underline' href='/learn'>읽기 팁</a>")
        name, _, intro = holders.BIG[key]
        def build():
            (n_us,) = self.con.execute("select count(*) from guru_holdings where guru = ?", (key,)).fetchone()
            (n_all,) = self.con.execute("select count(*) from nps_port").fetchone() if key == "nps" else (0,)
            us_n = f" · 한국·미국 주식 {n_all:,}종목" if n_all else f" · 미국 주식 {n_us:,}종목" if n_us else ""
            rows = self.con.execute(
                "select b.stock_code, b.corp_name, b.rate, b.rate_chg, b.date, b.rcept_no, s.ticker is not null, s.homepage"
                " from big_holdings b left join stocks s on s.ticker = b.stock_code where b.inst = ? order by b.rate desc", (key,)).fetchall()  # fmt: skip
            inds = [x for (x,) in self.con.execute("select induty_code from big_holdings where inst = ?", (key,))]
            industry = bars([sector(x) for x in inds], [1] * len(inds), "곳", "한국에서 5% 넘게 가진 회사들을 큰 업종(통계청 산업분류)으로 나눠 센 비율이에요. 위 그림과 기준이 달라요.")
            # 파이 → 업종 → 많이 가진 순서. 「최근 늘리고 줄인 회사」·「지분이 큰 순서」는 뺐다(너무 자세하다, 사용자 10/10 — 5% 보고는 종목 노트 맨 밑에 남아 있다)
            port = self.nps_portfolio(industry) if key == "nps" else ""
            port = port or self.us_portfolio(key, industry)

            def row(i, r):  # 미국 신고가 없는 기관(신한·KB 등)만 — 5% 넘게 가진 회사가 이 페이지의 전부라 남긴다
                code, corp, rate, _, d, rno, ours, home = r
                href = f"/n/{code}" if ours else DART_VIEW.format(rno)
                return (f'<a href="{e(href)}" {"" if ours else "target=_blank rel=noopener"} class="py-3 flex items-center gap-3">'
                        f'<span class="w-5 text-right text-[12px] text-outline tabular-nums">{i}</span>{logo(corp, home, "w-9 h-9")}'
                        f'<span class="flex flex-col min-w-0 flex-1"><span class="text-[15px] font-semibold text-on-surface truncate">{e(corp)}</span>'
                        f'<span class="text-[12px] text-on-surface-variant">지분 {rate:.2f}%</span></span></a>')  # fmt: skip

            kr_only = ("" if port else industry
                       + '<section class="mt-space-lg"><h2 class="font-headline-sm text-headline-sm text-on-surface">5% 넘게 가진 회사</h2><div class="flex flex-col divide-y divide-surface-container-high/70">'
                       + "".join(row(i, r) for i, r in enumerate(rows, 1)) + "</div></section>"
                       + '<p class="mt-space-md text-[11px] text-outline leading-relaxed">한국엔 기관의 보유 종목 전체를 알리는 제도가 없어서, 5% 넘게 가진 회사만 보여요(대량보유 보고). '
                       "따라 사고팔라는 뜻이 아니에요. 자료: DART</p>")  # fmt: skip
            body = (f'<div class="flex items-center py-space-sm"><a class="flex items-center gap-space-xs text-on-surface-variant hover:text-primary" href="/learn"><span class="material-symbols-outlined text-[18px]">arrow_back</span><span class="font-label-regular text-label-regular font-medium">읽기 팁</span></a></div>'
                    f'<header class="flex items-center gap-space-md">{logo(name, self.BIG_HOME.get(key), "w-14 h-14")}<div class="flex flex-col"><h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight">{e(name)}</h1>'
                    f'<span class="text-[12px] text-outline">5% 넘게 가진 회사 {len(rows):,}곳{us_n}</span></div></header>'
                    f'<p class="mt-space-md font-body-compact text-body-compact text-on-surface">{e(intro)}</p>' + port + kr_only)  # fmt: skip
            return body

        body = self.cached(f"big:{key}", build)
        return "200 OK", [], page(name, "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", wrap + body + end)
