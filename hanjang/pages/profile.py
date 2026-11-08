"""프로필·설정·팔로우·알림·닉네임·차단·신고"""

import base64
import binascii
import json
import sqlite3
from datetime import date, datetime, timedelta
from urllib.parse import quote

from hanjang import mail, notes, sources, tree
from hanjang.ui import BAD, BIO_MAX, MAX_STOCKS, NICK, PHOTO_MAX, REPORT_WHY, ago, bottom_nav, e, kdate, logo, page, photo_url, top_bar


class ProfilePages:
    # ---- 내 프로필 (시안에 없는 화면 — 같은 디자인 말투로. 가진 정보만) ----

    def profile(self, uid: int) -> str:
        """내 프로필 — 남이 보는 모양 그대로(이름·자기소개·팔로워·리그램). 설정은 오른쪽 위 톱니바퀴."""
        email, nick, bio, at = self.con.execute("select email, nickname, bio, photo_at from users where id = ?", (uid,)).fetchone()
        inner = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] lg:max-w-[760px] mx-auto pt-14 pb-24 lg:pt-20 lg:pb-16 bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-6">'
                 f'<header class="pt-5 flex items-center gap-space-md">{self.face(nick or email, "w-14 h-14", photo_url(uid, at))}<div class="flex flex-col min-w-0 flex-1">'
                 f'<h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight truncate">{e(nick or "내 프로필")}</h1>{self.follow_line(uid)}</div>'
                 '<a href="/me/settings" aria-label="설정" class="w-10 h-10 rounded-full flex items-center justify-center text-on-surface-variant hover:bg-surface-container"><span class="material-symbols-outlined text-[22px]">settings</span></a></header>'
                 + (f'<p class="mt-space-md font-body-compact text-body-compact text-on-surface whitespace-pre-line">{e(bio)}</p>' if bio else "")
                 + self.my_tree(uid)  # 내 나무는 맨 위, 위아래로 넉넉히 띄워서
                 + self.regram_list("where r.user_id = ?", (uid,), "내 리그램", mine=True)
                 + self.suggest(uid)
                 + "</div></main>" + bottom_nav("me"))  # fmt: skip
        return page("내 프로필", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    def my_tree(self, uid: int, today: date | None = None, nick: str | None = None) -> str:
        """내 나무 — 들어온 날이 쌓일수록 자라는 나무와 최근 석 달 잔디. 들어온 날 = 화면을 한 번이라도 연 날(views).
        nick 을 주면 남의 프로필에 보이는 모양 — 나무·날 수·잔디(「다음 단계까지 며칠」만 본인에게). 비공개 계정은 부르는 쪽이 거른다."""
        today = today or date.today()
        counts = dict(self.con.execute("select substr(at, 1, 10), count(*) from views where user_id = ? group by 1", (uid,)).fetchall())
        if nick is None:
            counts.setdefault(today.isoformat(), 1)  # 지금 이 화면을 보고 있다
        n = self.con.execute("select days from users where id = ?", (uid,)).fetchone()[0] or len(counts)  # 누적 — 기록이 지워져도 줄지 않는다
        name, left = tree.stage(n)
        grass, came = tree.grass(counts, today)
        title = "내 나무" if nick is None else f"{e(nick)}의 나무"
        nxt = f" · {dict(tree.STAGES)[n + left]}까지 {left}일" if left and nick is None else ""  # 「다음 단계까지 며칠」은 본인에게만
        return ('<section class="mt-space-xl mb-12 pb-space-xl border-b border-surface-container-high"><div class="flex items-center gap-2"><span class="w-2 h-2 shrink-0 rounded-full bg-primary"></span>'
                f'<h2 class="text-[16px] font-bold text-on-surface">{title}</h2></div>'
                f'<div class="mx-auto w-full max-w-[300px]">{tree.svg(n)}</div>'
                f'<p class="text-center text-[16px] font-bold text-primary">{e(name)}</p>'
                f'<p class="mt-0.5 text-center font-body-compact text-body-compact text-on-surface-variant">지금까지 {n}일 들어왔어요{e(nxt)}</p>'
                f'<p class="mt-12 mb-2 text-center font-label-regular text-label-regular text-on-surface-variant">최근 석 달 · {came}일 들어왔어요</p>'
                f'{grass}</section>')  # fmt: skip

    def settings(self, uid: int, msg: str | None = None) -> str:
        email, created, mail_on, nick, bio, private, at = self.con.execute(
            "select email, created_at, mail_on, nickname, bio, private, photo_at from users where id = ?", (uid,)).fetchone()  # fmt: skip
        (held,) = self.con.execute("select count(*) from holdings where user_id = ?", (uid,)).fetchone()
        # 주간 안내 메일 켜기/끄기 — 누르면 바로 바뀐다 (답장 같은 절차 없이, 사용자 10/7)
        knob = "translate-x-5" if mail_on else "translate-x-0"
        track = "bg-primary" if mail_on else "bg-surface-container-highest"
        switch = (f'<form method="post" action="/me/mail" class="py-3.5 flex items-center justify-between"><span class="flex items-center gap-2 font-body-compact text-body-compact text-on-surface-variant">'
                  '<span class="material-symbols-outlined text-primary text-[18px]">mark_email_unread</span><span class="flex flex-col"><span>안내 메일</span>'
                  '<span class="font-label-micro text-label-micro text-outline">월요일 소식지 · 화~토 아침 한 통</span></span></span>'
                  f'<button aria-label="안내 메일 {"끄기" if mail_on else "켜기"}" aria-pressed="{"true" if mail_on else "false"}" type="submit" class="flex items-center gap-2">'
                  f'<span class="font-label-micro text-label-micro {"text-primary" if mail_on else "text-outline"} font-semibold">{"ON" if mail_on else "OFF"}</span>'
                  f'<span class="w-11 h-6 rounded-full p-0.5 {track} transition-colors"><span class="block w-5 h-5 rounded-full bg-surface-container-lowest shadow-sm transition-transform {knob}"></span></span></button></form>')  # fmt: skip
        lock = (f'<form method="post" action="/me/private" class="py-3.5 flex items-center justify-between gap-3"><span class="flex flex-col">'
                '<span class="flex items-center gap-2 font-body-compact text-body-compact text-on-surface-variant"><span class="material-symbols-outlined text-primary text-[18px]">lock</span>비공개 계정</span>'
                '<span class="font-label-micro text-label-micro text-outline">켜면 내가 수락한 사람만 나무와 리그램, 팔로워 목록을 봐요</span></span>'
                f'<button aria-label="비공개 계정 {"끄기" if private else "켜기"}" aria-pressed="{"true" if private else "false"}" type="submit" class="flex items-center gap-2 shrink-0">'
                f'<span class="font-label-micro text-label-micro {"text-primary" if private else "text-outline"} font-semibold">{"ON" if private else "OFF"}</span>'
                f'<span class="w-11 h-6 rounded-full p-0.5 {"bg-primary" if private else "bg-surface-container-highest"} transition-colors"><span class="block w-5 h-5 rounded-full bg-surface-container-lowest shadow-sm transition-transform {"translate-x-5" if private else "translate-x-0"}"></span></span></button></form>')  # fmt: skip

        def row(icon, label, value):
            return (f'<div class="py-3.5 flex items-center justify-between"><span class="flex items-center gap-2 font-body-compact text-body-compact text-on-surface-variant">'
                    f'<span class="material-symbols-outlined text-primary text-[18px]">{icon}</span>{label}</span>'
                    f'<span class="font-body-reading-strong text-body-compact text-on-surface">{value}</span></div>')  # fmt: skip

        def go(icon, label, href):
            return (f'<a href="{href}" class="py-3.5 flex items-center justify-between"><span class="flex items-center gap-2 font-body-compact text-body-compact text-on-surface-variant">'
                    f'<span class="material-symbols-outlined text-primary text-[18px]">{icon}</span>{label}</span>'
                    '<span class="material-symbols-outlined text-outline text-[20px]">chevron_right</span></a>')  # fmt: skip

        field = "w-full font-body-compact text-body-compact bg-surface-container-low rounded-lg px-4 py-3 focus:outline-none"
        photo = ('<div class="mt-space-lg flex items-center gap-space-md">'
                 '<label class="relative cursor-pointer" aria-label="프로필 사진 바꾸기">' + self.face(nick or email, "w-20 h-20", photo_url(uid, at))
                 + '<span class="absolute -bottom-0.5 -right-0.5 w-7 h-7 rounded-full bg-primary text-on-primary flex items-center justify-center border-2 border-surface">'
                 '<span class="material-symbols-outlined text-[16px]">photo_camera</span></span><input accept="image/*" class="hidden" id="photo-input" type="file"></label>'
                 '<div class="flex flex-col gap-1"><span class="font-label-regular text-label-regular text-on-surface font-semibold">프로필 사진</span>'
                 + ('<form method="post" action="/me/photo/delete"><button class="font-label-micro text-label-micro text-outline underline" type="submit">사진 지우기</button></form>' if at else "")
                 + '</div></div>'
                 # 고른 사진 → 동그라미 안에서 끌어 옮기고 크기를 맞춘 뒤(인스타그램처럼) 보이는 부분만 256px JPEG → /me/photo
                 '<div class="hidden fixed inset-0 z-[70] bg-on-background/80 flex-col items-center justify-center gap-4 px-margin" id="crop">'
                 '<p class="font-label-regular text-label-regular text-surface">끌어서 옮기고, 아래 막대로 크기를 맞춰요</p>'
                 '<div class="relative w-[280px] h-[280px] overflow-hidden rounded-xl bg-black touch-none select-none" id="stage">'
                 '<img alt="" class="absolute top-0 left-0 max-w-none origin-top-left pointer-events-none" id="crop-img">'
                 '<div class="absolute inset-0 rounded-full pointer-events-none" style="box-shadow:0 0 0 999px rgba(0,0,0,.55)"></div></div>'
                 '<input class="w-[280px] accent-primary" id="zoom" max="3" min="1" step="0.01" type="range" value="1" aria-label="사진 크기">'
                 '<div class="flex gap-3"><button class="px-5 py-2 rounded-lg border border-surface/60 text-surface font-label-regular text-label-regular" id="crop-cancel" type="button">취소</button>'
                 '<button class="px-5 py-2 rounded-lg bg-primary text-on-primary font-label-regular text-label-regular font-semibold" id="crop-ok" type="button">이대로 저장</button></div></div>'
                 "<script>(()=>{const S=280,box=document.getElementById('crop'),stage=document.getElementById('stage'),im=document.getElementById('crop-img'),zoom=document.getElementById('zoom');"
                 "let base=1,k=1,x=0,y=0,drag=null;"
                 "const clamp=()=>{const w=im.naturalWidth*base*k,h=im.naturalHeight*base*k;x=Math.min(0,Math.max(S-w,x));y=Math.min(0,Math.max(S-h,y));"
                 "im.style.transform=`translate(${x}px,${y}px) scale(${base*k})`;};"
                 "const open=()=>{box.classList.remove('hidden');box.classList.add('flex');},close=()=>{box.classList.add('hidden');box.classList.remove('flex');};"
                 "document.getElementById('photo-input').addEventListener('change',ev=>{const f=ev.target.files[0];if(!f)return;im.onload=()=>{"
                 "base=S/Math.min(im.naturalWidth,im.naturalHeight);k=1;zoom.value=1;x=(S-im.naturalWidth*base)/2;y=(S-im.naturalHeight*base)/2;clamp();open();};"
                 "im.src=URL.createObjectURL(f);});"
                 "stage.addEventListener('pointerdown',e=>{drag=[e.clientX-x,e.clientY-y];stage.setPointerCapture(e.pointerId);});"
                 "stage.addEventListener('pointermove',e=>{if(!drag)return;x=e.clientX-drag[0];y=e.clientY-drag[1];clamp();});"
                 "stage.addEventListener('pointerup',()=>drag=null);"
                 "zoom.addEventListener('input',()=>{const c=S/2,old=base*k;k=+zoom.value;const now=base*k;x=c-(c-x)*now/old;y=c-(c-y)*now/old;clamp();});"
                 "document.getElementById('crop-cancel').onclick=()=>{close();document.getElementById('photo-input').value='';};"
                 "document.getElementById('crop-ok').onclick=async()=>{const sc=base*k,c=document.createElement('canvas');c.width=c.height=256;"
                 "c.getContext('2d').drawImage(im,-x/sc,-y/sc,S/sc,S/sc,0,0,256,256);"
                 "try{const r=await fetch('/me/photo',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({img:c.toDataURL('image/jpeg',0.85)})});"
                 "const j=await r.json();location.href='/me/settings'+(j.msg?'?msg='+encodeURIComponent(j.msg):'');}"
                 "catch(err){location.href='/me/settings?msg='+encodeURIComponent('사진을 바꾸지 못했어요. 다시 해 주세요.');}};})();</script>")  # fmt: skip
        inner = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] lg:max-w-[760px] mx-auto pt-14 pb-24 lg:pt-20 lg:pb-16 bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-6">'
                 '<a class="pt-5 flex items-center gap-space-xs text-on-surface-variant hover:text-primary" href="/me"><span class="material-symbols-outlined text-[18px]">arrow_back</span>'
                 '<span class="font-label-regular text-label-regular font-medium">내 프로필</span></a>'
                 '<h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight mt-space-sm">설정</h1>'
                 f'<span class="font-body-compact text-body-compact text-on-surface-variant truncate">{e(email)}</span>'
                 + (f'<p class="mt-space-sm font-body-compact text-body-compact text-tertiary" role="alert">{e(msg)}</p>' if msg else "")
                 + photo + '<form method="post" action="/me/profile" class="mt-space-lg flex flex-col gap-space-sm">'
                 '<label class="font-label-regular text-label-regular text-on-surface" for="nick">닉네임</label>'
                 f'<input class="{field}" id="nick" name="nickname" maxlength="20" required value="{e(nick or "")}">'
                 '<label class="font-label-regular text-label-regular text-on-surface" for="bio">자기소개</label>'
                 f'<textarea class="{field}" id="bio" name="bio" maxlength="{BIO_MAX}" rows="2">{e(bio or "")}</textarea>'
                 '<button class="self-end px-4 py-2 rounded-lg bg-primary text-on-primary font-label-regular text-label-regular font-semibold" type="submit">저장</button></form>'
                 '<section class="mt-space-lg flex flex-col divide-y divide-surface-container-high/80 border-y border-surface-container-high">'
                 + go("bookmark", "내 저장 목록", "/me/saved") + go("favorite", "내 좋아요 목록", "/me/liked")
                 + row("event", "가입한 날", kdate(created[:10]))
                 + row("inventory_2", "담은 종목", f'<a class="text-primary" href="/">{held} / {MAX_STOCKS}개</a>')
                 + switch + lock + go("description", "이용 규칙", "/rules") + "</section>" + self.blocked_list(uid) +
                 '<button class="mt-space-xl w-full py-3 rounded-lg border border-outline-variant/60 text-on-surface-variant font-body-reading-strong text-body-compact hover:bg-surface-container-low transition-colors" '
                 'onclick="if(confirm(\'현재 계정에서 로그아웃할까요?\'))location.href=\'/logout\'" type="button">로그아웃</button>'
                 '<form method="post" action="/me/delete" onsubmit="return confirm(\'탈퇴하면 이메일과 담은 종목, 기록이 모두 지워지고 되돌릴 수 없어요. 탈퇴할까요?\')">'
                 '<button class="mt-space-sm w-full py-3 font-label-regular text-label-regular text-tertiary hover:underline" type="submit">탈퇴하기</button></form>'
                 '<p class="mt-space-lg flex justify-center gap-3 font-label-micro text-label-micro text-outline"><a class="underline" href="/privacy">개인정보 처리방침</a><span>·</span><a class="underline" href="/method">계산 방법</a></p>'
                 '</div></main>' + bottom_nav("me"))  # fmt: skip
        return page("설정", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    # ---- 팔로우 · 리그램 · 피드 (뉴닉 「뉴니커」처럼 — 좋아한 글을 내 팔로워에게) ----

    def counts(self, uid: int) -> tuple[int, int]:
        q = "select count(*) from follows where {} = ? and ok = 1"
        return (self.con.execute(q.format("followee_id"), (uid,)).fetchone()[0],
                self.con.execute(q.format("follower_id"), (uid,)).fetchone()[0])  # fmt: skip

    @staticmethod
    def face(name: str, size: str = "w-9 h-9", photo: str | None = None) -> str:
        inside = f'<img alt="" class="w-full h-full object-cover" src="{e(photo)}">' if photo else e((name or "?")[:1].upper())
        return (f'<span class="{size} shrink-0 overflow-hidden rounded-full bg-primary-fixed text-primary flex items-center justify-center font-label-regular text-label-regular font-semibold">'
                f'{inside}</span>')  # fmt: skip

    def follow_line(self, uid: int, see: bool = True) -> str:
        """「팔로워 N | 팔로잉 N」 — 비공개 계정을 남이 보면 숫자만(목록으로 가는 링크 없이)."""
        fer, fing = self.counts(uid)
        tag = (lambda tab: f'<a class="hover:underline" href="/f/{uid}?tab={tab}">') if see else (lambda tab: "<span>")
        end = "</a>" if see else "</span>"
        return (f'<p class="font-label-regular text-label-regular text-on-surface-variant">{tag("followers")}팔로워 <b class="text-on-surface">{fer:,}</b>{end}'
                f'<span class="mx-2 text-outline-variant">|</span>{tag("following")}팔로잉 <b class="text-on-surface">{fing:,}</b>{end}</p>')  # fmt: skip

    def follow_button(self, uid: int, other: int, back: str) -> str:
        """목록·알림 줄 오른쪽 — 이미 팔로우하면 「팔로잉」(회색, 누르면 취소), 아니면 「팔로우」(초록). 나 자신은 없음."""
        if other == uid:
            return ""
        label, on = self.follow_state(uid, other)
        cls = "bg-surface-container text-on-surface" if on else "bg-primary text-on-primary"
        return (f'<form method="post" action="/follow" class="shrink-0"><input type="hidden" name="u" value="{other}"><input type="hidden" name="back" value="{e(back)}">'
                f'<button type="submit" class="px-4 py-1.5 rounded-lg text-[13px] font-semibold {cls}">{label}</button></form>')  # fmt: skip

    def follow_state(self, uid: int, other: int) -> tuple[str, bool]:
        """단추 글자 — 「팔로잉」(수락됨) · 「요청됨」(비공개 계정에 보낸 요청, 누르면 취소) · 「팔로우」."""
        row = self.con.execute("select ok from follows where follower_id = ? and followee_id = ?", (uid, other)).fetchone()
        return ("팔로잉" if row[0] else "요청됨", True) if row else ("팔로우", False)

    def can_see(self, uid: int, other: int) -> bool:
        """비공개 계정의 리그램·팔로워 목록은 본인과 수락된 팔로워만."""
        row = self.con.execute("select private from users where id = ?", (other,)).fetchone()
        return uid == other or not (row and row[0]) or bool(self.con.execute(
            "select 1 from follows where follower_id = ? and followee_id = ? and ok = 1", (uid, other)).fetchone())

    def person_row(self, uid: int, other: int, nick: str, bio: str | None, pat: str | None, back: str, note: str = "") -> str:
        return (f'<div class="py-3 flex items-center gap-3"><a href="/u/{other}" class="flex items-center gap-3 min-w-0 flex-1">{self.face(nick, "w-12 h-12", photo_url(other, pat))}'
                f'<span class="flex flex-col min-w-0"><b class="text-[15px] text-on-surface truncate">{e(nick)}</b>'
                f'<span class="text-[13px] text-on-surface-variant truncate">{note or e(bio or "")}</span></span></a>{self.follow_button(uid, other, back)}</div>')  # fmt: skip

    def follow_page(self, uid: int, who: int, tab: str):
        """인스타그램처럼 — 위에 「팔로워 N명 | 팔로잉 N명」 탭, 아래에 사람 목록과 팔로우 단추."""
        row = self.con.execute("select nickname from users where id = ?", (who,)).fetchone()
        if not row:
            return "404 Not Found", [], self.simple("없음", "없는 사람이에요.")
        tab = tab if tab in ("followers", "following") else "followers"
        if not self.can_see(uid, who):
            return self.see(f"/u/{who}")
        fer, fing = self.counts(who)
        col, by = ("follower_id", "followee_id") if tab == "followers" else ("followee_id", "follower_id")
        people = self.con.execute(f"select u.id, u.nickname, u.bio, u.photo_at from follows f join users u on u.id = f.{col}"
                                  f" where f.{by} = ? and f.ok = 1 and u.nickname is not null order by f.at desc", (who,)).fetchall()  # fmt: skip
        back = f"/f/{who}?tab={tab}"
        tabs = "".join(f'<a href="/f/{who}?tab={k}" class="flex-1 text-center py-3 text-[15px] {"font-semibold text-on-surface border-b-2 border-on-surface" if k == tab else "text-on-surface-variant border-b border-surface-container-high"}">{label} {n:,}명</a>'
                       for k, label, n in (("followers", "팔로워", fer), ("following", "팔로잉", fing)))  # fmt: skip
        rows = "".join(self.person_row(uid, i, n, b, p, back) for i, n, b, p in people)
        none = f'<p class="py-10 text-center text-[14px] text-outline">{"아직 팔로워가 없어요." if tab == "followers" else "아직 팔로우한 사람이 없어요."}</p>'
        home = "/me" if who == uid else f"/u/{who}"
        inner = (top_bar(self.initial(uid)) + '<main class="w-full max-w-[480px] lg:max-w-[760px] mx-auto pt-14 pb-24 lg:pt-20 min-h-screen"><div class="px-margin">'
                 f'<div class="flex items-center gap-3 py-3"><a href="{home}" aria-label="뒤로" class="text-on-surface"><span class="material-symbols-outlined">arrow_back</span></a>'
                 f'<h1 class="text-[20px] font-semibold text-on-surface">{e(row[0] or "")}</h1></div>'
                 f'<nav class="flex">{tabs}</nav><div class="flex flex-col">{rows or none}</div></div></main>' + bottom_nav("me"))  # fmt: skip
        return "200 OK", [], page("팔로워" if tab == "followers" else "팔로잉", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    def fresh(self, uid: int, since: str) -> tuple[list, list]:
        """알림거리 (since 뒤, 최근 7일 안) — 팔로우한 사람의 새 리그램, 내가 담은 종목의 새 소식.
        담은 종목은 남에게 알리지 않는다 — 본인 알림에만 쓴다."""
        since = max(since, (datetime.now() - timedelta(days=7)).isoformat())
        regs = self.con.execute("select r.at, u.id, u.nickname, u.photo_at, r.kind, r.ref, r.week from regrams r join users u on u.id = r.user_id"
                                " where r.user_id in (select followee_id from follows where follower_id = ? and ok = 1) and r.at > ?"
                                " order by r.at desc limit 30", (uid, since)).fetchall()  # fmt: skip
        arts = self.con.execute("select a.made_at, a.id, a.body, s.name, s.homepage from articles a join stocks s using(ticker)"
                                " where a.ticker in (select ticker from holdings where user_id = ?) and a.made_at > ?"
                                " order by a.made_at desc limit 30", (uid, since)).fetchall()  # fmt: skip
        return regs, arts

    def notices(self, uid: int):
        """알림 — 팔로우 · 팔로우한 사람의 새 리그램 · 내 종목 새 소식, 최신 먼저. 이 화면을 열면 빨간 점이 사라진다."""
        seen = self.con.execute("select coalesce(notices_seen, '') from users where id = ?", (uid,)).fetchone()[0]
        rows = self.con.execute("select u.id, u.nickname, u.bio, u.photo_at, f.at from follows f join users u on u.id = f.follower_id"
                                " where f.followee_id = ? and f.ok = 1 and u.nickname is not null order by f.at desc limit 50", (uid,)).fetchall()  # fmt: skip
        asks = self.con.execute("select u.id, u.nickname, u.photo_at, f.at from follows f join users u on u.id = f.follower_id"
                                " where f.followee_id = ? and f.ok = 0 order by f.at desc", (uid,)).fetchall()  # fmt: skip
        regs, arts = self.fresh(uid, "")
        self.con.execute("update users set notices_seen = ? where id = ?", (datetime.now().isoformat(), uid))
        self.con.commit()
        new = lambda at: "bg-primary-fixed/30 -mx-margin px-margin" if at > seen else ""  # noqa: E731
        events = [(at, f'<div class="{new(at)}">' + self.person_row(uid, i, n, b, p, "/me/notices", f"회원님을 팔로우하기 시작했어요 · {ago(at)}") + "</div>")
                  for i, n, b, p, at in rows]  # fmt: skip
        for at, i, n, p, kind, ref, _ in regs:
            if (hit := self.regram_target(kind, ref)):
                events.append((at, f'<a href="{e(hit[0])}" class="py-3 flex items-center gap-3 {new(at)}">{self.face(n, "w-12 h-12", photo_url(i, p))}'
                                   f'<span class="flex flex-col min-w-0"><span class="text-[14px] text-on-surface"><b>{e(n)}</b>님이 리그램했어요</span>'
                                   f'<span class="text-[13px] text-on-surface-variant truncate">{e(hit[1])} · {ago(at)}</span></span></a>'))  # fmt: skip
        for at, aid, body, name, home in arts:
            events.append((at, f'<a href="/a/{aid}" class="py-3 flex items-center gap-3 {new(at)}">{logo(name, home, "w-12 h-12")}'
                               f'<span class="flex flex-col min-w-0"><span class="text-[14px] text-on-surface">내 종목 <b>{e(name)}</b> 새 소식</span>'
                               f'<span class="text-[13px] text-on-surface-variant truncate">{e(json.loads(body)["title"])} · {ago(at)}</span></span></a>'))  # fmt: skip
        items = "".join(h for _, h in sorted(events, key=lambda x: x[0], reverse=True))
        none = '<p class="py-10 text-center text-[14px] text-outline">아직 알림이 없어요. 누가 팔로우하거나, 팔로우한 사람이 리그램하거나, 내 종목에 새 소식이 나오면 여기에 알려 드려요.</p>'

        def answer(i, label, yes, cls):
            return (f'<form method="post" action="/follow/answer"><input type="hidden" name="u" value="{i}"><input type="hidden" name="yes" value="{yes}">'
                    f'<button type="submit" class="px-3 py-1.5 rounded-lg text-[13px] font-semibold {cls}">{label}</button></form>')  # fmt: skip
        items = "".join(
            f'<div class="py-3 flex items-center gap-3"><a href="/u/{i}" class="flex items-center gap-3 min-w-0 flex-1">{self.face(n, "w-12 h-12", photo_url(i, p))}'
            f'<span class="flex flex-col min-w-0"><b class="text-[15px] text-on-surface truncate">{e(n or "")}</b>'
            f'<span class="text-[13px] text-on-surface-variant truncate">팔로우를 요청했어요 · {ago(at)}</span></span></a>'
            + answer(i, "수락", 1, "bg-primary text-on-primary") + answer(i, "삭제", 0, "bg-surface-container text-on-surface") + "</div>"
            for i, n, p, at in asks) + items  # fmt: skip
        inner = (top_bar(self.initial(uid)) + '<main class="w-full max-w-[480px] lg:max-w-[760px] mx-auto pt-14 pb-24 lg:pt-20 min-h-screen"><div class="px-margin">'
                 '<h1 class="py-3 text-[20px] font-semibold text-on-surface">알림</h1>'
                 f'<div class="flex flex-col">{items or none}</div></div></main>' + bottom_nav("me"))  # fmt: skip
        return "200 OK", [], page("알림", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    def save_photo(self, uid: int, img: str):
        """프로필 사진 — JPEG 만, 작게(PHOTO_MAX). 브라우저가 이미 256px 정사각형으로 잘라 보낸다."""
        def reply(msg="", code="200 OK"):
            return code, [("Content-Type", "application/json; charset=utf-8")], json.dumps({"msg": msg}, ensure_ascii=False)

        head = "data:image/jpeg;base64,"
        try:
            raw = base64.b64decode(img[len(head):], validate=True) if img.startswith(head) else b""
        except binascii.Error:
            raw = b""
        if not raw.startswith(b"\xff\xd8\xff") or len(raw) > PHOTO_MAX:
            return reply("사진을 바꾸지 못했어요. 다른 사진으로 해 주세요.", "400 Bad Request")
        self.con.execute("update users set photo = ?, photo_at = ? where id = ?", (raw, datetime.now().isoformat(timespec="seconds"), uid))
        self.con.commit()
        return reply()

    def nick_error(self, uid: int, nick: str) -> str:
        """닉네임 검사 — 문제가 없으면 빈 글. 겹침은 대소문자를 무시하고 본다(DB 유일 색인과 같게)."""
        if not NICK.fullmatch(nick):
            return "닉네임은 한글·영문·숫자·_ 2~20자로 정해 주세요."
        if notes.FORBIDDEN.search(nick) or BAD.search(nick):
            return "닉네임에 쓸 수 없는 말이 들어 있어요."
        if self.con.execute("select 1 from users where nickname = ? collate nocase and id != ?", (nick, uid)).fetchone():
            return f"「{nick}」은(는) 이미 누가 쓰고 있어요. 다른 닉네임으로 해 주세요."
        return ""

    def welcome_page(self, nick: str = "", error: str = "", agreed: bool = False) -> str:
        inner = ('<main class="flex flex-col relative w-full max-w-[480px] lg:max-w-[760px] mx-auto bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pt-16 pb-12">'
                 '<span class="font-display-editorial text-display-editorial text-primary tracking-tight">한장</span>'
                 '<h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight mt-space-md">닉네임을 정해 주세요</h1>'
                 '<p class="font-body-compact text-body-compact text-on-surface-variant mt-1">다른 사람에게는 이메일 대신 이 이름이 보여요. 한글·영문·숫자 2~20자, 다른 사람과 겹칠 수 없어요.</p>'
                 '<form method="post" action="/welcome" class="mt-space-lg flex flex-col gap-space-sm">'
                 f'<input autofocus class="w-full font-body-reading text-body-reading bg-surface-container-low rounded-lg px-4 py-3.5 focus:outline-none" maxlength="20" name="nickname" required value="{e(nick)}">'
                 # 이용 규칙 동의 — 닉네임·소개·사진이 남에게 보이기 전에 (앱 마켓이 사용자 콘텐츠가 있는 앱에 요구한다)
                 + '<label class="flex items-start gap-2 font-label-regular text-label-regular text-on-surface-variant"><input class="mt-0.5 accent-primary" name="rules" required type="checkbox" value="1"' + (" checked" if agreed else "") + '>'
                 '<span>[필수] <a class="text-primary underline" href="/rules" target="_blank">이용 규칙</a>에 동의해요 — 욕설·사칭·종목 추천·광고는 올리지 않아요</span></label>'
                 + (f'<p class="font-body-compact text-body-compact text-tertiary" role="alert">{e(error)}</p>' if error else "")
                 + '<button class="w-full py-3.5 bg-primary text-on-primary font-body-reading-strong text-body-reading-strong rounded-lg shadow-sm" type="submit">시작하기</button></form>'
                 '</div></main>')  # fmt: skip
        return page("닉네임", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    def welcome(self, uid: int, nick: str, agreed: bool = False):
        if err := self.nick_error(uid, nick):
            return "200 OK", [], self.welcome_page(nick, err, agreed)
        if not agreed:
            return "200 OK", [], self.welcome_page(nick, "이용 규칙에 동의해야 시작할 수 있어요.")
        try:
            self.con.execute("update users set nickname = ?, rules_at = ? where id = ?", (nick, datetime.now().isoformat(), uid))
            self.con.commit()
        except sqlite3.IntegrityError:  # 거의 같은 때 누가 먼저 가져간 경우
            return "200 OK", [], self.welcome_page(nick, f"「{nick}」은(는) 이미 누가 쓰고 있어요. 다른 닉네임으로 해 주세요.", agreed)
        return self.see("/")

    def save_profile(self, uid: int, nick: str, bio: str):
        if err := self.nick_error(uid, nick):  # 닉네임은 바꿀 수는 있어도 비울 수는 없다
            return self.see("/me/settings?msg=" + quote(err))
        if len(bio) > BIO_MAX or notes.FORBIDDEN.search(bio):
            return self.see("/me/settings?msg=" + quote("자기소개에 종목을 사라·팔라는 말이나 추천은 쓸 수 없어요."))
        if BAD.search(bio):
            return self.see("/me/settings?msg=" + quote("자기소개에 욕설·광고·연락처·바깥 링크는 쓸 수 없어요."))
        try:
            self.con.execute("update users set nickname = ?, bio = ? where id = ?", (nick, bio or None, uid))
            self.con.commit()
        except sqlite3.IntegrityError:
            return self.see("/me/settings?msg=" + quote(f"「{nick}」은(는) 이미 누가 쓰고 있어요."))
        return self.see("/me")  # 저장하면 바뀐 내 프로필로

    def blocked(self, uid: int) -> set[int]:
        """내가 차단했거나 나를 차단한 사람 — 서로 보이지 않는다."""
        return {a if a != uid else b for a, b in self.con.execute("select user_id, blocked_id from blocks where user_id = ? or blocked_id = ?", (uid, uid))}

    def blocked_list(self, uid: int) -> str:
        """설정 화면 — 차단한 사람. 찾기에 안 나오니 푸는 길은 여기(이름을 누르면 「차단 풀기」가 있는 화면)."""
        rows = self.con.execute("select u.id, u.nickname from blocks b join users u on u.id = b.blocked_id where b.user_id = ? order by b.at desc", (uid,)).fetchall()
        if not rows:
            return ""
        return ('<section class="mt-space-lg"><h2 class="font-label-regular text-label-regular text-on-surface font-semibold">차단한 사람</h2><div class="mt-1 flex flex-col">'
                + "".join(f'<a class="py-2 font-body-compact text-body-compact text-primary underline" href="/u/{i}">{e(n or "(이름 없음)")}</a>' for i, n in rows) + "</div></section>")

    def block(self, uid: int, other: int):
        """차단(한 번 더 누르면 풀기) — 서로의 팔로우·요청을 지운다. 그래서 피드에도 저절로 안 나온다."""
        if not self.con.execute("delete from blocks where user_id = ? and blocked_id = ?", (uid, other)).rowcount:
            self.con.execute("insert into blocks values (?, ?, ?)", (uid, other, datetime.now().isoformat()))
            self.con.execute("delete from follows where (follower_id = ? and followee_id = ?) or (follower_id = ? and followee_id = ?)", (uid, other, other, uid))
        self.con.commit()
        return self.see(f"/u/{other}")

    def report_user(self, uid: int, other: int, why: str):
        """신고 — 적어 두고 운영자에게 바로 메일. 같은 사람을 여러 번 눌러도 처리 전에는 한 건. 처리는 `python -m hanjang.moderate`."""
        why = why if why in REPORT_WHY else "기타"
        if not self.con.execute("select 1 from reports where user_id = ? and target_id = ? and done_at is null", (uid, other)).fetchone():
            self.con.execute("insert into reports (user_id, target_id, why, at) values (?, ?, ?, ?)", (uid, other, why, datetime.now().isoformat()))
            self.con.commit()
            nick, bio, has_photo = self.con.execute("select nickname, bio, photo is not null from users where id = ?", (other,)).fetchone()
            if to := sources.env().get("SMTP_USER"):
                with self.outside():
                    mail.send(to, f"[한장] 신고 — {why}", f"신고된 사람: #{other} {nick or '(닉네임 없음)'}\n자기소개: {bio or '(없음)'}\n프로필 사진: {'있음' if has_photo else '없음'}\n"
                              f"프로필: {mail.base_url()}/u/{other}\n신고한 사람: #{uid}\n\n24시간 안에 확인해요(이용 규칙). 서버에서:\n"
                              f"  프로필 지우기  python -m hanjang.moderate wipe {other}\n  계정 막기      python -m hanjang.moderate ban {other}\n  문제없음       python -m hanjang.moderate ok {other}")  # fmt: skip
        return "200 OK", [], self.simple("신고", f"신고를 받았어요. 운영자가 24시간 안에 확인해요. <a class='text-primary underline' href='/u/{other}'>돌아가기</a>")

    def user_page(self, uid: int, other: int):
        row = self.con.execute("select nickname, bio, photo_at from users where id = ? and nickname is not null", (other,)).fetchone()
        mine = self.con.execute("select 1 from blocks where user_id = ? and blocked_id = ?", (uid, other)).fetchone()
        if not row or (other in self.blocked(uid) and not mine):  # 닉네임이 없는 사람 · 나를 차단한 사람은 보이지 않는다
            return "404 Not Found", [], self.simple("없음", "없는 사람이에요. <a class='text-primary underline' href='/feed'>피드</a>")
        nick, bio, pat = row
        if mine:  # 내가 차단한 사람 — 이름과 풀기 단추만
            return "200 OK", [], self.simple(nick, f"<b>{e(nick)}</b> 님을 차단했어요. 서로의 프로필과 리그램이 보이지 않아요."
                                             f"<form method='post' action='/block' class='mt-4'><input type='hidden' name='u' value='{other}'>"
                                             "<button class='text-primary underline' type='submit'>차단 풀기</button></form>"
                                             "<a class='mt-4 inline-block text-primary underline' href='/feed'>피드로 돌아가기</a>")
        # 신고·차단 — 눈에 띄지 않게 접어 둔다 (앱 마켓의 사용자 콘텐츠 요구: 신고 · 차단 · 빠른 처리)
        more = ('<details class="mt-space-lg"><summary class="font-label-micro text-label-micro text-outline cursor-pointer">신고 · 차단</summary>'
                '<div class="mt-2 flex flex-col gap-3 rounded-xl border border-outline-variant/50 px-space-md py-3">'
                f'<form method="post" action="/report" class="flex flex-col gap-2"><input type="hidden" name="u" value="{other}">'
                '<span class="font-label-regular text-label-regular text-on-surface font-semibold">이 프로필 신고하기</span>'
                + "".join(f'<label class="flex items-center gap-2 font-body-compact text-body-compact text-on-surface-variant"><input class="accent-primary" name="why" required type="radio" value="{w}">{w}</label>' for w in REPORT_WHY)
                + '<button class="self-start font-label-regular text-label-regular text-tertiary underline" type="submit">신고 보내기</button></form>'
                f'<form method="post" action="/block" onsubmit="return confirm(\'차단하면 서로 팔로우가 풀리고, 서로의 프로필과 리그램이 보이지 않아요. 차단할까요?\')"><input type="hidden" name="u" value="{other}">'
                '<button class="font-label-regular text-label-regular text-tertiary underline" type="submit">이 사람 차단하기</button></form>'
                '<a class="font-label-micro text-label-micro text-outline underline" href="/rules">이용 규칙</a></div></details>')  # fmt: skip
        label, on = self.follow_state(uid, other)
        btn = "border border-outline-variant/60 text-on-surface-variant" if on else "bg-primary text-on-primary"
        shut = ('<div class="mt-space-xl py-10 flex flex-col items-center gap-2 border-t border-surface-container-high text-center">'
                '<span class="material-symbols-outlined text-outline text-[30px]">lock</span>'
                '<b class="font-body-reading-strong text-body-compact text-on-surface">비공개 계정이에요</b>'
                '<span class="font-body-compact text-body-compact text-on-surface-variant">팔로우 요청을 수락하면 나무와 리그램, 팔로워 목록을 볼 수 있어요.</span></div>')  # fmt: skip
        see = self.can_see(uid, other)
        inner = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] lg:max-w-[1200px] mx-auto pt-14 pb-24 lg:pt-20 lg:pb-16 bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-6">'
                 f'<header class="pt-5 flex items-center gap-space-md">{self.face(nick, "w-14 h-14", photo_url(other, pat))}<div class="flex flex-col min-w-0 flex-1">'
                 f'<div class="flex items-center gap-2 min-w-0"><h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight truncate">{e(nick)}</h1></div>{self.follow_line(other, see)}</div>'
                 f'<form method="post" action="/follow"><input type="hidden" name="u" value="{other}"><button class="px-4 py-2 rounded-lg font-label-regular text-label-regular font-semibold {btn}" type="submit">{label}</button></form></header>'
                 + (f'<p class="mt-space-md font-body-compact text-body-compact text-on-surface whitespace-pre-line">{e(bio)}</p>' if bio else "")
                 + ((self.my_tree(other, nick=nick) + self.regram_list("where r.user_id = ?", (other,), f"{nick}의 리그램", mine=True)) if see else shut)
                 + (more if other != uid else "")
                 + "</div></main>" + bottom_nav("feed"))  # fmt: skip
        return "200 OK", [], page(nick, "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)
