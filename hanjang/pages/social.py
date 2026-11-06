"""리그램·저장·밑줄·사람 찾기"""

import html
import json
import re
from datetime import datetime, timedelta
from urllib.parse import quote

from hanjang import learn, notes
from hanjang.notepage import FILLED
from hanjang.ui import HL_MAX, HL_PAGE, HL_PER_PAGE, Photos, QUOTE_MAX, QUOTE_MIN, TAGS, bottom_nav, e, mini, note_card, page, photo_url, row, top_bar


class SocialPages:
    def regram_target(self, kind: str, ref: str) -> tuple[str, str] | None:
        """리그램한 것의 (주소, 이름) — 알림 한 줄에 쓴다. 없어진 것이면 None."""
        if kind == "note":
            hit = self.con.execute("select name from stocks where ticker = ?", (ref,)).fetchone()
            return (f"/n/{ref}", f"{hit[0]} 노트") if hit else None
        if kind == "article":
            hit = self.con.execute("select body from articles where id = ?", (int(ref) if ref.isdigit() else -1,)).fetchone()
            return (f"/a/{ref}", json.loads(hit[0])["title"]) if hit else None
        a = learn.BY_SLUG.get(ref)
        return (f"/learn/{ref}", a["title"]) if a else None

    def regram_form(self, uid: int, kind: str, ref: str, week: str) -> str:
        """노트·읽기 팁 글 아래 — 리그램(한 줄 코멘트는 선택). 이미 했으면 취소 버튼."""
        done = self.con.execute("select 1 from regrams where user_id = ? and kind = ? and ref = ? and week = ?", (uid, kind, ref, week)).fetchone()
        (n,) = self.con.execute("select count(*) from regrams where kind = ? and ref = ? and week = ?", (kind, ref, week)).fetchone()
        undo = '<input type="hidden" name="undo" value="1">' if done else ""
        return (f'<form method="post" action="/regram" class="flex items-center gap-1.5"><input type="hidden" name="k" value="{e(kind)}"><input type="hidden" name="r" value="{e(ref)}"><input type="hidden" name="w" value="{e(week)}">{undo}'
                f'<button type="submit" aria-pressed="{"true" if done else "false"}" aria-label="리그램{" 취소" if done else ""} — 내 팔로워의 피드에 보여요" title="리그램 — 내 팔로워의 피드에 보여요" '
                f'class="w-10 h-10 rounded-full flex items-center justify-center border {"border-secondary/40 bg-secondary-container/60 text-secondary" if done else "border-outline-variant/60 text-outline"} transition-colors">'
                f'<span class="material-symbols-outlined text-[20px]">repeat</span></button>'
                f'<span class="font-label-regular text-label-regular text-on-surface-variant font-semibold">{n:,}</span></form>'
                + self.save_form(uid, kind, ref, week))  # fmt: skip

    def save_form(self, uid: int, kind: str, ref: str, week: str) -> str:
        """저장 — 나만 본다(숫자 없음). 설정 「내 저장 목록」에 모인다."""
        done = self.con.execute("select 1 from saves where user_id = ? and kind = ? and ref = ? and week = ?", (uid, kind, ref, week)).fetchone()
        undo = '<input type="hidden" name="undo" value="1">' if done else ""
        return (f'<form method="post" action="/save" class="ml-2 flex items-center"><input type="hidden" name="k" value="{e(kind)}"><input type="hidden" name="r" value="{e(ref)}"><input type="hidden" name="w" value="{e(week)}">{undo}'
                f'<button type="submit" aria-pressed="{"true" if done else "false"}" aria-label="저장{" 취소" if done else ""} — 나만 봐요" title="저장 — 내 저장 목록에 모여요" '
                f'class="w-10 h-10 rounded-full flex items-center justify-center border {"border-primary/40 bg-primary-fixed/60 text-primary" if done else "border-outline-variant/60 text-outline"} transition-colors">'
                f'<span class="material-symbols-outlined text-[20px]" style="{FILLED if done else ""}">bookmark</span></button></form>')  # fmt: skip

    def kept(self, uid: int, which: str) -> str:
        """설정 → 내 저장 목록 · 내 좋아요 목록 (나만 본다)."""
        title, src, none = (("내 저장 목록", "saves r", "아직 저장한 글이 없어요. 글 아래 책갈피 단추를 누르면 여기에 모여요.") if which == "saved" else
                            ("내 좋아요 목록", "(select user_id, 'note' kind, ticker ref, week, null comment, at from likes) r", "아직 좋아요를 누른 노트가 없어요."))  # fmt: skip
        body = self.regram_list("where r.user_id = ?", (uid,), title, mine=True, src=src)
        inner = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] lg:max-w-[760px] mx-auto pt-14 pb-24 lg:pt-20 lg:pb-16 bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-6">'
                 '<a class="pt-5 flex items-center gap-space-xs text-on-surface-variant hover:text-primary" href="/me/settings"><span class="material-symbols-outlined text-[18px]">arrow_back</span>'
                 '<span class="font-label-regular text-label-regular font-medium">설정</span></a>'
                 + (body or f'<h1 class="mt-space-lg font-headline-sm text-headline-sm text-on-surface">{title}</h1><p class="py-10 text-center text-[14px] text-outline">{none}</p>')
                 + "</div></main>" + bottom_nav("me"))  # fmt: skip
        return page(title, "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    def share_quote(self, uid: int, pg: str, text: str):
        """고른 글귀를 내 프로필에 — 그 글의 리그램에 글귀 한 줄을 붙인다(글 하나에 하나, 다시 하면 바뀐다).
        글귀가 실제로 그 글 안에 있을 때만 — 인용인 척 「사세요」 같은 제 말을 올리지 못하게."""
        def reply(msg):
            return "200 OK", [("Content-Type", "application/json; charset=utf-8")], json.dumps({"msg": msg}, ensure_ascii=False)

        text = " ".join(text.split())
        m = HL_PAGE.fullmatch(pg)
        if not m or not QUOTE_MIN <= len(text) <= QUOTE_MAX or notes.FORBIDDEN.search(text):
            return reply(f"{QUOTE_MIN}~{QUOTE_MAX}자만 공유할 수 있어요")
        if not self.con.execute("select nickname from users where id = ?", (uid,)).fetchone()[0]:
            return reply("닉네임을 먼저 정해 주세요")
        kind, ref, week = {"n": "note", "a": "article"}.get(m[1], "learn"), pg.split("/", 2)[2], ""
        if kind == "note":
            (week,) = self.con.execute("select max(week) from notes where ticker = ?", (ref,)).fetchone()
            shown = self.note(uid, ref, False) if week else None
        elif kind == "article":
            shown = self.article(uid, int(ref)) if ref.isdigit() else None
        else:
            shown = self.learn(uid, ref) if ref in learn.BY_SLUG else None
        squash = lambda x: re.sub(r"\s+", "", x)  # noqa: E731 — 줄바꿈·문단 사이 빈칸은 견주지 않는다
        if not shown or not shown[0].startswith("200") or squash(text) not in squash(html.unescape(TAGS.sub("", shown[2]))):
            return reply("글에 있는 문장만 공유할 수 있어요")
        now = datetime.now().isoformat()
        self.con.execute("insert or ignore into regrams (user_id, kind, ref, week, at) values (?, ?, ?, ?, ?)", (uid, kind, ref, week, now))
        self.con.execute("update regrams set comment = ?, at = ? where user_id = ? and kind = ? and ref = ? and week = ?", (text, now, uid, kind, ref, week))
        self.con.commit()
        return reply("내 프로필에 올렸어요")

    def highlight(self, uid: int, method: str, path: str, form: dict, query: dict):
        """형광펜 — GET /hl?p=화면 → 칠한 곳들 · POST /hl 칠하기 · POST /hl/del 지우기. 모두 내 것만."""
        def reply(data):
            return "200 OK", [("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store")], json.dumps(data, ensure_ascii=False)

        if method == "GET":
            rows = self.con.execute("select id, s, e, text, color from highlights where user_id = ? and page = ? order by id", (uid, query.get("p", ""))).fetchall()
            return reply([{"id": i, "s": s, "e": e, "t": t, "c": c} for i, s, e, t, c in rows])
        if path == "/hl/del":
            self.con.execute("delete from highlights where id = ? and user_id = ?", (int(form["id"]) if form.get("id", "").isdigit() else -1, uid))
            self.con.commit()
            return reply({})
        pg, t, c = form.get("p", ""), form.get("t", ""), form.get("c", "")
        s, e2 = (int(form[k]) if form.get(k, "").isdigit() else -1 for k in ("s", "e"))
        (n,) = self.con.execute("select count(*) from highlights where user_id = ? and page = ?", (uid, pg)).fetchone()
        if not HL_PAGE.fullmatch(pg) or not 0 <= s < e2 or not t.strip() or len(t) > HL_MAX or c not in ("y", "g", "p", "b") or n >= HL_PER_PAGE:
            return reply({})
        cur = self.con.execute("insert into highlights (user_id, page, s, e, text, color, at) values (?, ?, ?, ?, ?, ?, ?)",
                               (uid, pg, s, e2, t, c, datetime.now().isoformat()))  # fmt: skip
        self.con.commit()
        return reply({"id": cur.lastrowid})

    def regram(self, uid: int, form: dict, table: str = "regrams"):
        kind, ref, week = form.get("k", ""), form.get("r", ""), form.get("w", "")
        back = {"note": f"/n/{quote(ref)}", "article": f"/a/{quote(ref)}"}.get(kind, f"/learn/{quote(ref)}")
        ok = (kind == "note" and self.con.execute("select 1 from notes where ticker = ? and week = ?", (ref, week)).fetchone()) or (
            kind == "learn" and ref in learn.BY_SLUG and week == "") or (
            kind == "article" and ref.isdigit() and week == "" and self.con.execute("select 1 from articles where id = ?", (int(ref),)).fetchone())
        if not ok:
            return self.see("/feed")
        if form.get("undo"):
            self.con.execute(f"delete from {table} where user_id = ? and kind = ? and ref = ? and week = ?", (uid, kind, ref, week))
            self.con.commit()
            return self.see(back)
        if table == "regrams" and not self.con.execute("select nickname from users where id = ?", (uid,)).fetchone()[0]:  # 저장은 나만 보니 닉네임이 없어도 된다
            return self.see("/me/settings?msg=" + quote("리그램하려면 닉네임을 먼저 정해 주세요. 팔로워에게 이 이름으로 보여요."))
        self.con.execute(f"insert or ignore into {table} (user_id, kind, ref, week, at) values (?, ?, ?, ?, ?)",
                         (uid, kind, ref, week, datetime.now().isoformat()))  # fmt: skip
        self.con.commit()
        return self.see(back)

    def regram_list(self, where: str, args: tuple, title: str, mine: bool = False, photos: "Photos | None" = None, src: str = "regrams r") -> str:
        """글 카드 목록 — 리그램(src 기본) · 저장(saves r) · 좋아요(likes 를 같은 모양으로 바꾼 것)."""
        photos = photos or Photos()
        rows = self.con.execute(
            f"select r.user_id, u.nickname, r.kind, r.ref, r.week, r.comment, r.at, u.photo_at from {src} join users u on u.id = r.user_id "
            + where + " order by r.at desc limit 50", args).fetchall()  # fmt: skip
        cards = []
        for who, nick, kind, ref, week, comment, at, pat in rows:
            d = at[:10].replace("-", ".")
            if kind == "note":
                hit = self.con.execute("select s.name, n.body, s.homepage from stocks s join notes n on n.ticker = s.ticker and n.week = ?"
                                       " where s.ticker = ?", (week, ref)).fetchone()  # fmt: skip
                if not hit:
                    continue
                card = lambda top, h=notes.mend(json.loads(hit[1])["headline"]), n=hit[0], home=hit[2], t=ref: note_card(t, n, home, h, d, top)
            elif kind == "article":
                hit = self.con.execute("select a.id, a.kind, a.body, a.date, s.name, s.induty_code from articles a join stocks s using(ticker) where a.id = ?",
                                       (int(ref) if ref.isdigit() else -1,)).fetchone()  # fmt: skip
                if not hit:
                    continue
                aid, k, body, adate, name, ind = hit
                b = json.loads(body)
                img = self.article_photo(aid, k, ind, name, photos)
                card = lambda top, b=b, img=img, name=name, aid=aid, adate=adate: row(f"/a/{aid}", img, b["title"], b["paragraphs"][0]["text"], name, adate.replace("-", "."), top)
            else:
                a = learn.BY_SLUG.get(ref)
                if not a:
                    continue
                mark = '<span class="w-7 h-7 rounded-full bg-primary-fixed text-primary flex items-center justify-center"><span class="material-symbols-outlined text-[16px]">menu_book</span></span>'
                card = lambda top, a=a, ref=ref, mark=mark: mini(f"/learn/{ref}", mark, a["title"], a["lead"].replace("**", ""), "읽기 팁", d, top)
            top = "" if mine else (f'<a href="/u/{who}" class="flex items-center gap-2">{self.face(nick, "w-6 h-6", photo_url(who, pat))}'
                                   f'<span class="font-label-regular text-label-regular text-on-surface-variant"><b class="text-on-surface font-semibold">{e(nick)}</b>님이 리그램</span></a>')  # fmt: skip
            if comment:  # 공유한 글귀 — 글에서 고른 문장 그대로 (share_quote 가 글 안에 있는지 확인한 것)
                top += (f'<blockquote class="border-l-4 border-primary pl-3 py-0.5 text-[16px] leading-[26px] text-on-surface font-medium">'
                        f'<a href="{e({"note": "/n/", "article": "/a/"}.get(kind, "/learn/") + ref)}">“{e(comment)}”</a></blockquote>')  # fmt: skip
            cards.append(card(top))
        if not cards:
            return ""
        body = "".join(cards)
        return (f'<section class="mt-space-lg"><h2 class="font-headline-sm text-headline-sm text-on-surface">{e(title)}</h2>'
                f'<div class="flex flex-col divide-y divide-surface-container-high/80">{body}</div></section>')  # fmt: skip

    def people(self, uid: int, q: str) -> str:
        if not q:
            return ""
        rows = self.con.execute("select id, nickname, bio, photo_at from users where nickname is not null and id != ? and nickname like ?"
                                " limit 40", (uid, f"%{q}%")).fetchall()  # fmt: skip
        gone = self.blocked(uid)  # 차단한·차단당한 사람은 찾기에도 안 나온다
        rows = [r for r in rows if r[0] not in gone][:20]
        items = "".join(f'<a href="/u/{i}" class="py-space-sm flex items-center gap-space-sm">{self.face(n, photo=photo_url(i, p))}<span class="flex flex-col min-w-0">'
                        f'<span class="font-label-regular text-label-regular text-on-surface font-semibold">{e(n)}</span>'
                        f'<span class="font-label-micro text-label-micro text-on-surface-variant truncate">{e(b or "")}</span></span></a>' for i, n, b, p in rows)  # fmt: skip
        none = '<p class="py-2 font-body-compact text-body-compact text-outline">그런 닉네임이 없어요.</p>'
        return f'<div class="mt-space-sm flex flex-col divide-y divide-surface-container-high/80">{items or none}</div>'

    def suggest(self, uid: int) -> str:
        """추천 프로필 — 최근 2주에 활발한 사람(리그램 ×2 + 좋아요 + 팔로워) 순, 이미 팔로우했거나 요청한 사람은 빼고.
        활발한 사람이 없어도 비우지 않는다 — 사람이 적은 처음엔 누구라도 보여야 팔로우가 시작된다.
        담은 종목으로는 고르지 않는다 — 공개하지 않은 보유 종목이 드러나므로."""
        since = (datetime.now() - timedelta(days=14)).isoformat()
        rows = self.con.execute(
            "select u.id, u.nickname, u.photo_at,"
            " (select count(*) from regrams r where r.user_id = u.id and r.at >= ?) rg,"
            " (select count(*) from likes l where l.user_id = u.id and l.at >= ?) lk,"
            " (select count(*) from follows f where f.followee_id = u.id and f.ok = 1) fer"
            " from users u where u.nickname is not null and u.id != ? and u.id not in (select followee_id from follows where follower_id = ?)",
            (since, since, uid, uid)).fetchall()  # fmt: skip
        gone = self.blocked(uid)
        rows = sorted((r for r in rows if r[0] not in gone), key=lambda r: (-(r[3] * 2 + r[4] + r[5]), r[1]))[:10]
        if not rows:
            return ""

        cards = "".join(
            f'<div class="shrink-0 w-[132px] flex flex-col items-center gap-1.5 text-center"><a href="/u/{i}" class="flex flex-col items-center gap-1.5 min-w-0 w-full">'
            f'{self.face(n, "w-16 h-16", photo_url(i, p))}<b class="text-[14px] text-on-surface truncate w-full">{e(n)}</b>'
            f'</a>{self.follow_button(uid, i, "/me")}</div>'
            for i, n, p, rg, lk, fer in rows)  # fmt: skip
        return (f'<section id="suggest" class="mt-space-lg"><div class="flex items-center justify-between"><h2 class="font-headline-sm text-headline-sm text-on-surface">추천 프로필</h2>'
                '<button type="button" aria-label="추천 프로필 닫기" class="p-1 text-outline hover:text-on-surface" onclick="try{sessionStorage.setItem(\'hideSuggest\',\'1\')}catch(e){}this.closest(\'section\').remove()">'
                '<span class="material-symbols-outlined text-[22px]">close</span></button></div>'
                f'<div class="mt-space-sm -mx-margin px-margin flex gap-4 overflow-x-auto pb-2">{cards}</div></section>'
                "<script>try{if(sessionStorage.getItem('hideSuggest'))document.getElementById('suggest').remove()}catch(e){}</script>")  # fmt: skip
