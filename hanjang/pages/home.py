"""내 종목(첫 화면)·종목 담기·캡처 읽기·기업 노트·설문"""

import hashlib
import json
import re
import threading
from datetime import date, datetime, timedelta
from urllib.parse import quote

from hanjang import llm, morning, notes, sources, tree
from hanjang.notepage import WHO_ICONS, render_note
from hanjang.pwa import EMPTY_CARDS, INSTALL_HINT
from hanjang.sources import industry_label
from hanjang.ui import FIRST, MAX_STOCKS, SCAN_HOURLY, bottom_nav, e, logo, page, top_bar


class HomePages:
    def stocks_v(self) -> str:
        """종목 목록의 내용 지문 — 주소(?v=)에 붙인다. 브라우저가 하루 저장해 두므로, 내용(순서 포함)이 바뀌면 주소도 바뀌어야 새로 받는다
        (종목 수만 세면 순서를 바꿔도 옛 목록이 남는다 — 눌러 보기 10/11)."""
        return self.cached("stocks_v", lambda: hashlib.sha256(self.stocks_js().encode()).hexdigest()[:10])

    def stocks_js(self) -> str:
        """노트가 있는 종목 먼저(검색하면 위에), 그다음 상장사 전체. 업종은 DART 업종 코드에서 (받아 둔 종목만). 186KB 를 매번 만들지 않게 cached."""
        return self.cached("stocks_js", self._stocks_js)

    def _stocks_js(self) -> str:
        rows = [{"t": t, "n": n, "l": "미국" if m == "US" else "ETF" if t.startswith("ETF") else industry_label(c) or ""} for t, n, c, m in
                self.con.execute("select ticker, name, induty_code, market from stocks s left join (select ticker, count(*) n from holdings group by ticker) h"
                                 " using (ticker) order by active desc, coalesce(n, 0) desc, market, name")]  # 많이 담긴 종목 먼저 — 시가총액은 쓸 권리가 없어 모른다. 담은 수는 한 번에 센다(종목마다 세면 3,000명에서 4초)  # fmt: skip
        return "window.STOCKS=" + json.dumps(rows, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c") + ";"

    def match(self, q: str) -> str | None:
        """이름·코드 → 종목 코드. 띄어쓰기·대소문자는 무시한다(「삼성 SDI」→ 삼성SDI)."""
        key = re.sub(r"\s+", "", q).upper()
        row = self.con.execute("select ticker from stocks where (ticker = ? or upper(replace(name, ' ', '')) = ?) order by active desc",
                               (key, key)).fetchone()  # 상장사 전체 (코스닥 포함) — 노트가 없던 종목은 다음 아침에 생긴다  # fmt: skip
        return row[0] if row else None

    def add_many(self, uid: int, names: list[str]) -> tuple[list[str], list[str], bool]:
        """(담은 것, 못 찾은 것, 20개가 차서 멈췄나). 이미 담은 종목은 담은 것으로 센다."""
        added, unknown = [], []
        for q in dict.fromkeys(x.strip() for x in names if x.strip()):
            t = self.match(q)
            if not t:
                unknown.append(q)
                continue
            (n,) = self.con.execute("select count(*) from holdings where user_id = ?", (uid,)).fetchone()
            have = self.con.execute("select 1 from holdings where user_id = ? and ticker = ?", (uid, t)).fetchone()
            if not have and n >= MAX_STOCKS:
                return added, unknown, True
            self.con.execute("insert or ignore into holdings values (?, ?, ?)", (uid, t, datetime.now().isoformat()))
            added.append(self.con.execute("select name from stocks where ticker = ?", (t,)).fetchone()[0])
            if not self.con.execute("select 1 from notes where ticker = ?", (t,)).fetchone():
                self.start_first(t)
        self.con.commit()
        return added, unknown, False

    def start_first(self, ticker: str) -> None:
        """노트가 없는 종목을 담으면 그 종목만 바로 받아 첫 노트를 쓴다 — 따로 띄운 실에서 (화면은 기다리지 않는다).
        같은 종목을 여러 사람이 동시에 담아도 한 번만."""
        row = self.con.execute("select market from stocks where ticker = ?", (ticker,)).fetchone()
        if ticker.startswith("ETF") or (row and row[0] != "KR"):  # ETF·미국은 DART 에서 받을 것이 없다 — 각자의 받기가 맡는다
            return
        with self.making_lock:
            if ticker in self.making:
                return
            self.making.add(ticker)

        def run():
            try:
                FIRST(ticker)
            finally:
                with self.making_lock:
                    self.making.discard(ticker)

        threading.Thread(target=run, daemon=True).start()

    @staticmethod
    def added_msg(added: list[str], unknown: list[str], full: bool) -> str:
        parts = [f"{len(added)}종목을 담았어요 ({', '.join(added[:5])}{' 외' if len(added) > 5 else ''})."] if added else []
        if unknown:
            parts.append(f"「{', '.join(unknown[:5])}」은(는) 찾지 못했어요. 국내는 회사 이름이나 종목 코드 6자리, 미국은 티커(NVDA)로 다시 찾아 주세요.")
        if full:
            parts.append(f"종목은 {MAX_STOCKS}개까지 담을 수 있어요.")
        return " ".join(parts) or "담을 종목을 찾지 못했어요."

    def add(self, uid: int, q: str):
        """한 종목, 또는 쉼표·줄바꿈·띄어쓰기로 여러 종목을 한 번에 (「삼성전자, SK하이닉스」)."""
        if not q:
            return self.see("/")
        names = [q] if self.match(q) else [w for part in re.split(r"[,\n;/·]+", q)
                                           for w in ([part] if self.match(part) else part.split())]  # fmt: skip
        added, unknown, full = self.add_many(uid, names)
        if len(names) == 1 and added and not full:
            return self.see("/")
        return self.see("/?msg=" + quote(self.added_msg(added, unknown, full)))

    def scan(self, uid: int, img: str):
        """보유 종목 캡처 → AI 가 종목 이름만 읽는다 → 코드가 우리 종목과 맞춰 담는다. 사진은 저장하지 않는다."""
        def reply(msg, code="200 OK"):
            return code, [("Content-Type", "application/json; charset=utf-8")], json.dumps({"msg": msg}, ensure_ascii=False)

        if not re.match(r"data:image/(jpeg|png|webp);base64,", img):
            return reply("사진을 읽지 못했어요. 캡처 사진(JPG·PNG)을 골라 주세요.", "400 Bad Request")
        now = self.clock()
        times = [t for t in self.scans.get(uid, []) if now - t < 3600]
        if len(times) >= SCAN_HOURLY:
            return reply("사진 읽기는 한 시간에 10번까지예요. 잠시 뒤에 다시 해 주세요.", "429 Too Many Requests")
        self.scans[uid] = times + [now]
        schema = {"type": "object", "additionalProperties": False, "required": ["names"],
                  "properties": {"names": {"type": "array", "items": {"type": "string"}}}}  # fmt: skip
        try:
            with self.outside():  # AI 가 사진을 읽는 수십 초 동안 다른 화면은 돈다
                got = llm.ask("scan", "holdings", {}, lambda j: [str(x) for x in j["names"]][:40], schema, image=img)
        except RuntimeError:
            got = None
        if not got:
            return reply("사진에서 종목을 찾지 못했어요. 증권사 앱의 「보유 종목」 화면을 캡처해 주세요.")
        return reply(self.added_msg(*self.add_many(uid, got)))

    # ---- 내 종목 (시안 _3) ----

    def cards(self, uid: int, msg: str | None, sort: str | None = None) -> str:
        order = "s.name" if sort == "name" else "h.added_at"
        rows = self.con.execute(
            "select s.ticker, s.name, n.week, n.body, n.facts, s.homepage, s.market from holdings h join stocks s using(ticker)"
            " left join notes n on n.ticker = s.ticker and n.week ="
            " (select max(week) from notes where ticker = s.ticker)"
            f" where h.user_id = ? order by {order}", (uid,)).fetchall()  # fmt: skip
        out = []
        happened: dict[str, list] = {}
        for c in self.my_events(uid):
            happened.setdefault(c[9], []).append(c)
        both = len({r[6] for r in rows}) > 1  # 국내·미국을 둘 다 담았을 때만 거르기 칩
        for t, name, week, body, facts, home, mkt in rows:  # facts 는 지금 카드에 안 쓴다 (상태 줄은 사용자 요청 10/7로 뺐다)
            b = json.loads(body) if body else {}
            head = (b.get("headline") and notes.mend(b["headline"])) or ("첫 노트를 만들고 있어요. 1~2분 뒤 새로고침해 보세요." if t in self.making else
                                          "새로 담은 종목이에요. 공시 자료를 받는 대로 첫 노트가 나와요(보통 다음 아침 7시).")
            event, status = "", "<span></span>"  # status = 「노트 읽기 →」를 오른쪽에 두는 왼쪽 자리
            if (evs := happened.get(t)):  # 이 종목에 생긴 일 — 노트 핵심 한 줄 아래에. 누르면 노트의 그 대목으로 (임원·큰손은 #who, 그 밖은 #recent)
                _, icon, tint, _, _, what, _, when, _, _ = evs[0]
                event = (f'<a href="/n/{e(t)}#{"who" if icon in WHO_ICONS else "recent"}" class="mt-2 block"><p class="text-[15px] leading-[22px] font-semibold text-on-surface">'
                         f'<span class="material-symbols-outlined text-[17px] align-[-3px] mr-1 {tint}">{icon}</span>{e(what)}</p></a>')  # 회색 설명 줄은 카드에서 뺐다 — 노트에 있다 (사용자 10/11)  # fmt: skip
                status = f'<span class="text-[12px] text-outline">{e(when)}{f" · 소식 {len(evs) - 1}건 더" if len(evs) > 1 else ""}</span>'
            out.append(f'<article class="py-4 relative transition-all group" data-stock-id="{e(t)}" data-market="{e(mkt)}"><div class="flex items-start justify-between"><div class="flex items-center gap-2">'
                       f'{logo(name, home, "w-7 h-7")}<a href="/n/{e(t)}"><h2 class="font-headline-sm text-headline-sm text-on-surface font-semibold hover:underline">{e(name)}</h2></a><span class="font-citation-ref text-citation-ref text-outline px-1.5 py-0.5 rounded bg-surface-container-low">{e("ETF" if t.startswith("ETF") else t)}</span>{'<span class="font-citation-ref text-citation-ref text-secondary px-1.5 py-0.5 rounded bg-secondary-fixed/50 font-semibold">미국</span>' if mkt == "US" else ""}<span class="font-label-micro text-label-micro text-outline-variant">{e(week or "")}</span></div>'
                       f'<form method="post" action="/remove"><input type="hidden" name="t" value="{e(t)}"><button aria-label="{e(name)} 삭제" class="w-6 h-6 rounded-full flex items-center justify-center text-outline hover:text-tertiary hover:bg-surface-container transition-colors" type="submit"><span class="material-symbols-outlined text-[16px]">close</span></button></form></div>'
                       f'<a href="/n/{e(t)}"><p class="font-body-reading text-body-reading text-on-surface mt-2 tracking-tight">{e(head)}</p></a>{event}'
                       f'<div class="mt-3 flex items-center justify-between">{status}<a class="font-label-micro text-label-micro text-primary flex items-center gap-0.5 hover:underline font-semibold" href="/n/{e(t)}">노트 읽기<span class="material-symbols-outlined text-[14px]">arrow_forward</span></a></div></article>')  # fmt: skip
        note = (f'<p class="font-label-micro text-label-micro text-tertiary px-margin pt-2">{e(msg)}</p>' if msg else "")
        demo = self.is_demo(uid)  # 둘러보는 손님 — 제목만 「예시 종목」. 담기 등을 누르면 흐린 덮개(web.GUEST_GATE)
        inner = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] lg:max-w-[1200px] mx-auto pt-14 pb-24 lg:pt-20 lg:pb-16 bg-surface min-h-screen"><div class="flex flex-col w-full flex-1">'
                 '<section class="sticky top-0 z-30 bg-surface/95 backdrop-blur-md px-margin py-3 border-b border-surface-container-high transition-all duration-200"><div class="relative w-full">'
                 '<form method="post" action="/add" class="h-11 w-full bg-surface-container-lowest rounded-xl flex items-center px-3 border border-surface-container-high/60 focus-within:border-primary-container focus-within:bg-surface-container-lowest transition-all"><span class="material-symbols-outlined text-outline text-[20px] mr-2">search</span>'
                 '<input autocomplete="off" class="w-full bg-transparent text-on-surface font-body-compact text-body-compact placeholder:text-outline focus:outline-none" id="stock-search-input" name="q" placeholder="종목 이름 또는 코드로 담기" type="text">'
                 '<button class="shrink-0 ml-1.5 px-3 py-1 bg-primary text-on-primary rounded-lg font-label-micro text-label-micro font-semibold shadow-sm active:scale-95 transition-transform" id="btn-quick-add" type="submit">담기</button>'
                 '<label class="shrink-0 ml-1 w-8 h-8 flex items-center justify-center rounded-lg text-on-surface-variant hover:bg-surface-container cursor-pointer" aria-label="보유 종목 캡처로 담기 (사진을 AI 에 보내 종목 이름을 읽어요)" title="보유 종목 캡처로 담기 — 사진을 AI(OpenAI)에 보내 종목 이름을 읽어요. 저장하지 않아요">'
                 '<span class="material-symbols-outlined text-[20px]">photo_camera</span><input accept="image/*" class="hidden" id="scan-input" type="file"></label></form>'
                 '<div class="hidden absolute left-0 right-0 top-12 mt-1 bg-surface-container-lowest rounded-xl shadow-sm border border-surface-container-high/70 overflow-hidden z-40" id="search-flyout"><div class="p-1.5 flex flex-col gap-0.5" id="search-results"></div></div>'
                 "</div></section>"
                 + '<div class="hidden fixed inset-0 z-[60] bg-surface/90 backdrop-blur-sm flex-col items-center justify-center gap-3 px-margin text-center" id="scan-wait" role="status">'
                 + tree.line("wait") +
                 '<p class="font-headline-sm text-headline-sm text-on-surface">분석 중…</p>'
                 '<p class="font-body-compact text-body-compact text-on-surface-variant">캡처에서 종목 이름만 읽고 있어요. 사진은 저장하지 않아요.</p></div>'
                 + note
                 + '<header class="px-margin pt-5 pb-2"><div class="flex items-baseline justify-between mb-1"><div class="flex items-center gap-2"><h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight">' + ("예시 종목" if demo else "내 종목") + '</h1>'
                 f'<span class="font-label-regular text-label-regular text-outline" id="stock-count-badge">{len(rows)} / {MAX_STOCKS}개</span></div>'
                 f'<a class="font-label-micro text-label-micro text-outline hover:text-on-surface transition-colors flex items-center gap-0.5" href="/?sort={"added" if sort == "name" else "name"}"><span class="material-symbols-outlined text-[15px]">tune</span>정렬</a></div>'
                 '</header>'
                 # 아침 한 장 — 내 종목 소식 · 이번 주 · 꿀팁 (docs/growth.md §3-1). 화면에선 AI 를 부르지 않는다(문장은 매일 실행이 미리)
                 + (f'<div class="px-margin pb-2">{morning.html(morning.build(self.con, [r[0] for r in rows], date.today(), uid))}</div>' if rows else "")
                 # 전체 / 국내 / 미국 — 스위치가 아니라 보기 거르기 (노트·메일은 늘 둘 다, docs/stage3-us.md)
                 + ('<nav class="px-margin pb-1 flex gap-1.5" id="market-chips">' + "".join(
                     f'<button type="button" data-m="{m}" class="mchip px-3 py-1 rounded-full text-[12px] font-semibold border {"bg-primary text-on-primary border-primary" if m == "all" else "border-outline-variant/60 text-on-surface-variant"}">{label}</button>'
                     for m, label in (("all", "전체"), ("KR", "국내"), ("US", "미국")))
                    + '</nav><script>document.querySelectorAll(".mchip").forEach(b=>b.onclick=()=>{const m=b.dataset.m;'
                    'document.querySelectorAll(".mchip").forEach(x=>{const on=x===b;x.className=x.className.replace(/bg-primary text-on-primary border-primary|border-outline-variant[/]60 text-on-surface-variant/,on?"bg-primary text-on-primary border-primary":"border-outline-variant/60 text-on-surface-variant")});'
                    'document.querySelectorAll("#stock-list>article").forEach(a=>a.style.display=(m==="all"||a.dataset.market===m)?"":"none")});</script>' if both else "")
                 + f'<section class="px-margin flex flex-col divide-y divide-surface-container-high/80 lg:grid lg:grid-cols-2 lg:gap-x-12 lg:divide-y-0 lg:[&>*]:border-b lg:[&>*]:border-surface-container-high/80" id="stock-list">{"".join(out) or EMPTY_CARDS}</section>'
                 '<footer class="mt-auto px-margin pt-16 pb-6 flex flex-col items-center justify-center gap-1.5 opacity-80"><p class="font-label-micro text-label-micro text-outline text-center flex items-center justify-center gap-1.5"><span class="material-symbols-outlined text-[13px]">mark_email_unread</span>월요일 아침마다 새 노트가 와요. 새 공시·기사가 나오면 매일 아침 고쳐 써요.</p><div class="flex items-center gap-3 text-outline font-label-micro text-label-micro"><span class="">업데이트: 매일 07:00 (바뀐 종목만)</span><span class="">·</span><span class="">공시 데이터: DART 전자공시</span></div>'
                 + ('<a class="font-label-micro text-label-micro text-primary font-semibold underline underline-offset-4 py-1" href="/admin">운영자 인사이트</a>' if self.is_admin(uid) else "")  # 운영자에게만
                 + '<button class="font-label-micro text-label-micro text-outline hover:text-on-surface transition-colors underline underline-offset-4 py-2" onclick="if(confirm(\'현재 계정에서 로그아웃할까요?\'))location.href=\'/logout\'" type="button">로그아웃</button></footer></div>'
                 # 자동완성 — 상장사 전체는 /stocks.js 로 따로 (하루 캐시, 100KB 남짓)
                 f'<script src="/stocks.js?v={self.stocks_v()}"></script><script>'
                 "const STOCKS=window.STOCKS||[];"
                 "const inp=document.getElementById('stock-search-input'),fly=document.getElementById('search-flyout'),res=document.getElementById('search-results');"
                 "function esc(s){return s.replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}"
                 "function draw(){const q=inp.value.trim();if(!q){fly.classList.add('hidden');return;}const Q=q.toUpperCase();const all=STOCKS.filter(s=>s.n.toUpperCase().includes(Q)||s.t.startsWith(Q)),first=s=>s.n.toUpperCase().startsWith(Q)||s.t.startsWith(Q);"
                 "const hit=[...all.filter(first),...all.filter(s=>!first(s))].slice(0,6);"
                 "res.innerHTML=hit.map((s,i)=>"
                 "'<form method=\"post\" action=\"/add\" onclick=\"if(event.target!==this.lastChild)this.requestSubmit()\" class=\"group flex items-center justify-between p-2.5 rounded-lg cursor-pointer hover:bg-surface-container transition-colors\"><input type=\"hidden\" name=\"q\" value=\"'+s.t+'\"><div class=\"flex items-center gap-2 min-w-0\"><span class=\"w-7 h-7 rounded-full bg-primary-fixed text-primary flex items-center justify-center font-body-reading-strong text-[12px]\">'+esc(s.n[0])+'</span><div class=\"flex flex-col min-w-0\"><div class=\"flex items-center gap-1.5\"><span class=\"font-headline-sm text-headline-sm text-on-surface\">'+esc(s.n)+'</span><span class=\"font-citation-ref text-citation-ref text-outline\">'+(s.t.startsWith('ETF')?'':s.t)+'</span></div><span class=\"font-label-micro text-label-micro text-on-surface-variant truncate\">'+esc(s.l)+'</span></div></div>'"
                 "+'<button class=\"px-2.5 py-1 bg-primary-container text-on-primary font-label-micro text-label-micro rounded-lg shadow-sm hover:opacity-90 active:scale-95 transition-all\" type=\"submit\">+ 담기</button>'+'</form>').join('');"
                 "fly.classList.toggle('hidden',hit.length===0);}"
                 "inp.addEventListener('input',draw);inp.addEventListener('focus',draw);"
                 "document.addEventListener('click',ev=>{if(!inp.contains(ev.target)&&!fly.contains(ev.target))fly.classList.add('hidden');});"
                 # 캡처 → 브라우저에서 1600px 로 줄여 JPEG 로 → /scan. 끝나면 결과 문장과 함께 새로 그린다
                 "const sc=document.getElementById('scan-input'),wait=document.getElementById('scan-wait');"
                 "sc.addEventListener('change',async()=>{const f=sc.files[0];if(!f)return;"
                 "if(!confirm('캡처에서 종목 이름을 읽으려고 이 사진을 AI(OpenAI, 미국)에 보내요.\\n한장은 사진을 저장하지 않고, 읽어 낸 종목 이름만 담아요.\\n계좌번호·금액이 보이면 가리고 올려도 돼요.\\n\\n보낼까요?')){sc.value='';return;}"
                 "wait.classList.remove('hidden');wait.classList.add('flex');"
                 "try{const bmp=await createImageBitmap(f);const k=Math.min(1,1600/Math.max(bmp.width,bmp.height));const c=document.createElement('canvas');"
                 "c.width=Math.round(bmp.width*k);c.height=Math.round(bmp.height*k);c.getContext('2d').drawImage(bmp,0,0,c.width,c.height);"
                 "const r=await fetch('/scan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({img:c.toDataURL('image/jpeg',0.85)})});"
                 "const j=await r.json();location.href='/?msg='+encodeURIComponent(j.msg);}"
                 "catch(err){location.href='/?msg='+encodeURIComponent('사진을 읽지 못했어요. 다시 해 주세요.');}});</script></main>"
                 + INSTALL_HINT + bottom_nav("cards"))  # fmt: skip
        return page("내 종목", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    # ---- 설문 (시안에 없는 칸 — 시험 판정에 꼭 필요해 노트 끝에, 시안과 같은 모양으로) ----

    def trial_week(self, uid: int) -> int:
        """시험 몇 주째인가 — 가입한 날이 1주째 (ERD views 의 주차 계산과 같은 기준)."""
        (created,) = self.con.execute("select created_at from users where id = ?", (uid,)).fetchone()
        return (date.today() - date.fromisoformat(created[:10])).days // 7 + 1

    def survey(self, uid: int, ticker: str, week: str, thanks: bool) -> str:
        """주간 설문 (PRD F7) — 1~5 + 한 줄. 6주째부터 「돈 내고도 보겠다」."""
        done = self.con.execute("select 1 from feedback where user_id = ? and ticker = ? and week = ?",
                                (uid, ticker, week)).fetchone()  # fmt: skip
        if thanks or done:
            return ('<section class="mb-space-xl pl-space-md py-1 border-l-2 border-primary/60"><p class="font-body-compact text-body-compact text-on-surface">'
                    "이번 주 노트에 대한 의견 고마워요. 다음 주 노트에 참고할게요.</p></section>")  # fmt: skip
        chip = "px-2.5 py-1 rounded-full border border-outline-variant/60 font-label-micro text-label-micro text-on-surface flex items-center gap-1"
        pay = ('<p class="font-label-regular text-label-regular text-on-surface font-semibold mt-space-sm">이 노트를 돈을 내고도 보시겠어요? 낸다면 한 달에 얼마까지?</p><div class="flex flex-wrap gap-2">'
               + "".join(f'<label class="{chip}"><input type="radio" name="pay" value="{v}" required>{t}</label>'
                         for v, t in ((0, "안 내요"), (1000, "1천 원"), (3000, "3천 원"), (5000, "5천 원"), (10000, "1만 원 이상")))
               + "</div>") if self.trial_week(uid) >= 6 else ""  # fmt: skip
        return (f'<form method="post" action="/feedback" class="mb-space-xl flex flex-col gap-space-sm pt-space-lg border-t border-outline-variant/40">'
                f'<input type="hidden" name="t" value="{e(ticker)}"><input type="hidden" name="w" value="{e(week)}">'
                '<div class="flex items-center gap-2"><span class="w-2 h-2 rounded-full bg-primary"></span><h3 class="font-headline-md text-headline-md text-on-surface">이 노트가 도움이 됐나요?</h3></div>'
                '<input type="range" name="h" min="1" max="5" step="1" value="3" aria-label="도움 정도 1~5" class="w-full accent-primary cursor-pointer">'
                '<div class="flex justify-between px-1 -mt-1 font-label-micro text-label-micro text-on-surface-variant">' + "".join(f"<span>{i}</span>" for i in range(1, 6))
                + '</div><div class="flex justify-between font-label-micro text-label-micro text-outline"><span>별로예요</span><span>아주 좋아요</span></div>'
                + pay + '<input class="w-full font-body-compact text-body-compact bg-surface-container-low text-on-surface placeholder:text-outline rounded-lg px-4 py-3 focus:outline-none" maxlength="300" name="c" placeholder="한 줄 의견 (선택)">'
                '<button class="w-full py-3 bg-primary text-on-primary font-body-reading-strong text-body-reading-strong rounded-lg shadow-sm" type="submit">보내기</button></form>')  # fmt: skip

    def feedback(self, uid: int, form: dict):
        ticker, week, h = form.get("t", ""), form.get("w", ""), form.get("h", "")
        if not (h.isdigit() and 1 <= int(h) <= 5 and re.fullmatch(r"\d{6}", ticker)
                and re.fullmatch(r"\d{4}-\d{2}-\d{2}", week)):
            return self.see("/")
        pay = form.get("pay")
        self.con.execute("insert into feedback (user_id, ticker, week, helpful, would_pay, comment, at)"
                         " values (?, ?, ?, ?, ?, ?, ?)",
                         (uid, ticker, week, int(h), int(pay) if pay and pay.isdigit() else None,
                          form.get("c", "")[:300], datetime.now().isoformat()))  # fmt: skip
        self.con.commit()
        return self.see(f"/n/{ticker}?thanks=1")

    # ---- 기업 노트 (시안 _1) ----

    def note(self, uid: int, ticker: str, thanks: bool = False):
        row = self.con.execute(
            "select s.name, n.week, n.body, n.writer, n.facts, s.induty_code, n.made_at, s.homepage from stocks s join notes n using(ticker)"
            " where s.ticker = ? order by n.week desc limit 1", (ticker,)).fetchone()  # fmt: skip
        if not row:
            return "404 Not Found", [], self.simple("없음", "이 종목은 아직 노트가 없어요. <a class='text-primary underline' href='/'>내 종목</a>")
        name, week, body, writer, facts, ind, made, home = row
        (views,) = self.con.execute("select count(*) from views where page = 'note' and ticker = ? and at >= ?", (ticker, week)).fetchone()
        (likes,) = self.con.execute("select count(*) from likes where ticker = ? and week = ?", (ticker, week)).fetchone()
        liked = bool(self.con.execute("select 1 from likes where user_id = ? and ticker = ? and week = ?", (uid, ticker, week)).fetchone())
        return "200 OK", [], render_note(name, ticker, week, json.loads(body), writer, json.loads(facts), ind,
                                         self.initial(uid), self.survey(uid, ticker, week, thanks), made, home, (views, likes, liked),
                                         self.regram_form(uid, "note", ticker, week),
                                         prices=self.con.execute("select date, close from prices where ticker = ? order by date", (ticker,)).fetchall()
                                         if sources.price_dev() else None, report=self.report(ticker) | {"owners": self.owners(ticker), "events": self.my_events(uid, ticker=ticker)})  # fmt: skip

    def report(self, ticker: str) -> dict:
        if self.con.execute("select 1 from stocks where ticker = ? and market = 'US'", (ticker,)).fetchone():
            # 미국 — 「한눈에 보기」 그림·배당 막대는 원 단위·DART 서식이라 넘기지 않는다(달러 숫자에 「원」이 붙었다, 10/10). 같은 숫자는 본문에 있다
            biz = self.con.execute("select body, rcept_no from business where ticker = ?", (ticker,)).fetchone()
            return {"divs": [], "biz": json.loads(biz[0]) if biz else None, "rno": self.src(biz[1]) if biz else None,
                    "fin": None, "fins": None, "buys": [], "mid": {}, "us": True}  # fmt: skip
        divs = self.con.execute("select fiscal_year, dps, total, payout from dividends where ticker = ? order by fiscal_year", (ticker,)).fetchall()
        biz = self.con.execute("select body, rcept_no from business where ticker = ?", (ticker,)).fetchone()
        fins = self.con.execute("select fiscal_year, revenue, operating_income, net_income, equity, liabilities from financials"
                                " where ticker = ? order by fiscal_year desc limit 2", (ticker,)).fetchall()  # fmt: skip
        fin = fins[0] if fins else None
        buys = self.con.execute("select date, amount from disclosures where ticker = ? and code = 'BUYBACK' and amount > 0 and date >= ?",
                                (ticker, (date.today() - timedelta(days=365)).isoformat())).fetchall()  # fmt: skip
        return {"divs": divs, "biz": json.loads(biz[0]) if biz else None, "rno": (self.src(biz[1]) if "-" in biz[1] else biz[1]) if biz else None, "fin": fin, "fins": fins, "buys": buys,
                "mid": notes.industry_mid(self.con, ticker)}
