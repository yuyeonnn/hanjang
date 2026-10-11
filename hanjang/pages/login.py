"""로그인·둘러보기·상태 확인 화면"""

import hmac
import json
import secrets
import shutil
import sqlite3
import time
from datetime import datetime
from urllib.parse import quote

from hanjang import db, mail, sources
from hanjang.auth import CODE_TRIES, LINK_TTL, LOGIN_ALL_HOURLY, LOGIN_GAP, LOGIN_HOURLY, LOGIN_IP_HOURLY, login_token, session_cookie
from hanjang.ui import COHORT, DEMO_EMAIL, DEMO_STOCKS, e, page, row


class LoginPages:
    # ---- 로그인 (시안 _2) ----

    def login_page(self, sent: str | None = None, error: str = "", cohort: str = "") -> str:
        hidden = f'<input type="hidden" name="c" value="{cohort}">' if COHORT.fullmatch(cohort) else ""
        box = (f'<p class="font-body-compact text-body-compact text-tertiary mt-3" role="alert">{e(error)}</p>' if error else "") + ("" if not sent else (
            '<div class="flex flex-col bg-secondary-container/40 rounded-lg p-4 mt-4 transition-all" id="success-box"><div class="flex items-start gap-3"><div class="flex-shrink-0 w-8 h-8 rounded-full bg-secondary-container flex items-center justify-center mt-0.5"><span class="material-symbols-outlined text-on-secondary-container text-lg" style="font-variation-settings: \'FILL\' 1;">mark_email_read</span></div><div class="flex flex-col flex-1 min-w-0"><div class="flex items-center gap-1.5 mb-1"><span class="font-label-micro text-label-micro bg-primary text-on-primary px-1.5 py-0.5 rounded">발송 완료</span>'
            f'<span class="font-body-reading-strong text-body-compact text-on-surface truncate" id="target-email-preview">{e(sent)}</span></div>'
            '<p class="font-body-compact text-body-compact text-on-secondary-container">위 주소로 로그인 링크와 6자리 코드를 보냈어요. 15분 안에 메일 속 링크를 누르거나, 코드를 아래에 넣어 주세요.</p>'
            # 코드 넣기 — 앱(웹뷰)이나 홈 화면에 추가한 한장에서는 메일의 링크가 다른 브라우저로 열려 로그인이 안 이어진다. 코드는 어디서든 된다 (앱 출시 준비 10/11)
            f'<form method="post" action="/login/code" class="mt-2.5 flex items-center gap-2"><input type="hidden" name="email" value="{e(sent)}">{hidden}'
            '<input aria-label="메일로 받은 6자리 코드" autocomplete="one-time-code" autofocus inputmode="numeric" maxlength="6" name="code" pattern="[0-9]{6}" placeholder="6자리 코드" required '
            'class="flex-1 min-w-0 font-body-reading text-body-reading bg-surface-container-lowest text-on-surface placeholder:text-outline rounded-lg px-4 py-2.5 focus:outline-none tracking-widest">'
            '<button class="shrink-0 px-4 py-2.5 bg-primary text-on-primary font-label-regular text-label-regular font-semibold rounded-lg" type="submit">확인</button></form>'
            '<div class="flex flex-col gap-1 mt-2.5 pt-2.5 border-t border-outline-variant/30"><p class="font-label-micro text-label-micro text-outline">메일이 오지 않았나요? 스팸함을 보거나 잠시 뒤에 다시 받아 보세요.</p>'
            f'<form method="post" action="/login"><input type="hidden" name="email" value="{e(sent)}"><input type="hidden" name="agree" value="1">{hidden}<button class="self-start font-label-regular text-label-regular text-primary font-semibold underline underline-offset-2 hover:opacity-80 transition-opacity mt-1" id="resend-btn" type="submit">링크 다시 보내기</button></form></div></div></div></div>'
            # 이 상자는 폼 아래에 있어 휴대폰에선 화면 밖이다 — 뜨자마자 보이게 내린다. 자동 초점(autofocus)만으로는 안 된다: 아이폰은 사용자가 누르지 않은 초점을 무시한다 (눌러 보기 10/11)
            "<script>document.getElementById('success-box').scrollIntoView({block:'center'});</script>"))  # fmt: skip
        inner = ('<main class="flex flex-col relative w-full max-w-[480px] lg:max-w-[760px] mx-auto bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-12">'
                 '<div class="flex flex-col items-center text-center mt-6 mb-8"><div class="relative flex items-center justify-center w-20 h-20 rounded-full bg-surface-container-low shadow-sm mb-5"><svg class="w-9 h-9 text-primary" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.75" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" x2="8" y1="13" y2="13"></line><line x1="16" x2="8" y1="17" y2="17"></line><line x1="10" x2="8" y1="9" y2="9"></line></svg><div class="absolute -bottom-1 -right-1 flex items-center justify-center w-6 h-6 rounded-full bg-secondary-container shadow-xs"><span class="material-symbols-outlined text-on-secondary-container text-xs" style="font-variation-settings: \'FILL\' 1;">auto_stories</span></div></div>'
                 '<span class="font-display-editorial text-display-editorial text-primary tracking-tight">한장</span><span class="font-label-micro text-label-micro text-outline uppercase tracking-widest mt-1">Hanjang · Weekly Financial Letter</span>'
                 '<h1 class="font-headline-sm text-headline-sm text-on-surface mt-4 max-w-[280px] leading-relaxed">내 주식이 지금 어떤 상황인지,<br>쉬운 글 한 장으로.</h1>'
                 '<p class="font-body-compact text-body-compact text-on-surface-variant mt-2 max-w-[300px]">숫자 뒤에 숨겨진 회사의 진짜 이야기와 사업 흐름을 담백하게 정리해 드립니다.</p></div>'
                 '<div class="w-full rounded-xl flex flex-col relative overflow-hidden px-1.5"><form class="flex flex-col w-full relative z-10" id="magic-link-form" method="post" action="/login">' + hidden
                 + '<div class="flex items-center justify-between mb-2"><label class="font-label-regular text-label-regular text-on-surface flex items-center gap-1.5" for="email-input"><span class="material-symbols-outlined text-primary text-base">mail</span>이메일 주소</label><span class="font-label-micro text-label-micro text-outline">비밀번호 없는 간편 시작</span></div>'
                 '<div class="relative flex items-center w-full"><input class="w-full font-body-reading text-body-reading bg-surface-container-low text-on-surface placeholder:text-outline rounded-lg px-4 py-3.5 focus:outline-none focus:bg-surface-container-lowest transition-all" id="email-input" name="email" placeholder="name@example.com" required="" type="email">'
                 '<button aria-label="이메일 지우기" class="hidden absolute right-3 text-outline hover:text-on-surface p-1 transition-colors" id="clear-btn" onclick="clearInput()" type="button"><span class="material-symbols-outlined text-lg">cancel</span></button></div>'
                 '<label class="flex items-start gap-2 mt-3 font-label-regular text-label-regular text-on-surface-variant"><input class="mt-0.5 accent-primary" name="agree" required type="checkbox" value="1">'
                 '<span>[필수] 이메일 수집·이용에 동의해요 — <a class="text-primary underline" href="/privacy" target="_blank">개인정보 처리방침</a></span></label>'
                 f'<button class="w-full py-3.5 bg-primary text-on-primary font-body-reading-strong text-body-reading-strong rounded-lg shadow-sm hover:opacity-95 active:scale-[0.99] transition-all mt-3 flex items-center justify-center gap-2" id="submit-btn" type="submit"><span class="">{"링크 다시 받기" if sent else "시작하기"}</span><span class="material-symbols-outlined text-base">{"refresh" if sent else "arrow_forward"}</span></button>'
                 '<p class="font-label-regular text-label-regular text-outline text-center mt-3 leading-relaxed">비밀번호 없이, 메일로 온 링크를 누르면 시작돼요. 받는 개인정보는 이메일 하나뿐이에요.</p>'
                 '<a class="block text-center mt-2 font-label-regular text-label-regular text-primary underline underline-offset-2" href="/help/login">로그인 링크가 안 와요</a></form>'
                 + ('<a class="mt-3 w-full py-3 rounded-lg border border-outline-variant/70 text-on-surface font-body-reading-strong text-body-compact flex items-center justify-center gap-1" href="/demo">'
                    '<span class="material-symbols-outlined text-[18px]">visibility</span>로그인 없이 둘러보기</a>' if sources.env().get("DEMO") == "1" else "")
                 + box + '</div>'
                 '<div class="mt-8 flex flex-col gap-4"><div class="grid grid-cols-2 gap-4 pt-2 border-t border-outline-variant/30"><div class="flex flex-col gap-1"><div class="flex items-center gap-1.5 text-primary"><span class="material-symbols-outlined text-base">description</span><span class="font-body-reading-strong text-label-regular">공시 기반 해설</span></div><p class="font-label-micro text-label-micro text-on-surface-variant leading-relaxed">어려운 DART 공시와 분기 보고서를 일상 언어로 풀어냅니다.</p></div><div class="flex flex-col gap-1"><div class="flex items-center gap-1.5 text-secondary"><span class="material-symbols-outlined text-base">spa</span><span class="font-body-reading-strong text-label-regular">소음 없는 담백함</span></div><p class="font-label-micro text-label-micro text-on-surface-variant leading-relaxed">빨강·파랑 시세창 대신 기업 본질을 천천히 읽는 시간.</p></div></div>'
                 '<div class="text-center px-4 mt-4"><div class="inline-flex items-center justify-center gap-2 mb-2"><span class="w-4 h-[1px] bg-outline-variant"></span><span class="font-citation-ref text-citation-ref text-outline">한장의 약속</span><span class="w-4 h-[1px] bg-outline-variant"></span></div><p class="font-label-regular text-label-regular text-outline leading-relaxed">이해를 위한 서비스예요. 수익률을 장담하거나 종목을 추천하지 않아요.</p></div></div></div>'
                 "<script>const emailInput=document.getElementById('email-input');const clearBtn=document.getElementById('clear-btn');"
                 "emailInput.addEventListener('input',(ev)=>{clearBtn.classList.toggle('hidden',ev.target.value.length===0);});"
                 "function clearInput(){emailInput.value='';clearBtn.classList.add('hidden');emailInput.focus();}</script></main>")  # fmt: skip
        return page("로그인", "bg-surface font-body-reading text-on-surface pt-safe pb-safe flex flex-col min-h-screen", inner)

    def health(self, now: float | None = None):
        """화면 서버가 대답하고 · DB 가 열리고 · 매일 실행이 30시간 안에 돌았고(그때 백업을 만든다) · 디스크가 10% 넘게 남았나.
        문제가 있으면 503 과 무엇이 문제인지 한 낱말씩 (사용자 정보는 싣지 않는다)."""
        bad = []
        try:
            self.con.execute("select 1 from users limit 1").fetchall()
        except sqlite3.Error:
            bad.append("db")
        backups = list((db.PATH.parent / "backup").glob("hanjang-*.db"))
        if not backups or (now or time.time()) - max(p.stat().st_mtime for p in backups) > 30 * 3600:
            bad.append("daily")
        disk = shutil.disk_usage(db.PATH.parent)
        if disk.free < disk.total * 0.1:
            bad.append("disk")
        return ("503 Service Unavailable" if bad else "200 OK"), [("Content-Type", "text/plain; charset=utf-8"), ("Cache-Control", "no-store")], " ".join(bad) or "ok"

    def assetlinks(self):
        pkg, sha = sources.env().get("TWA_PACKAGE", ""), sources.env().get("TWA_SHA256", "")
        if not (pkg and sha):
            return "404 Not Found", [], self.simple("없음", "없는 화면이에요.")
        body = [{"relation": ["delegate_permission/common.handle_all_urls"],
                 "target": {"namespace": "android_app", "package_name": pkg, "sha256_cert_fingerprints": [x.strip() for x in sha.split(",")]}}]
        return "200 OK", [("Content-Type", "application/json")], json.dumps(body)

    def is_demo(self, uid: int) -> bool:
        row = self.con.execute("select email from users where id = ?", (uid,)).fetchone()
        return bool(row and row[0] == DEMO_EMAIL)

    def demo(self):
        if sources.env().get("DEMO") != "1":
            return "404 Not Found", [], self.simple("없음", "없는 화면이에요. <a class='text-primary underline' href='/'>처음으로</a>")
        self.con.execute("insert or ignore into users (email, created_at, nickname, mail_on) values (?, ?, '둘러보기', 0)",
                         (DEMO_EMAIL, datetime.now().isoformat()))  # fmt: skip
        self.con.execute("update users set rules_at = coalesce(rules_at, created_at) where email = ?", (DEMO_EMAIL,))  # 공용 계정 — 닉네임이 정해져 있어 규칙 동의 관문을 지나게
        (u,) = self.con.execute("select id from users where email = ?", (DEMO_EMAIL,)).fetchone()
        for t in DEMO_STOCKS:
            if self.con.execute("select 1 from stocks where ticker = ?", (t,)).fetchone():
                self.con.execute("insert or ignore into holdings values (?, ?, ?)", (u, t, datetime.now().isoformat()))
        self.con.commit()
        return self.see("/", ("Set-Cookie", session_cookie(u, self.secret, self.clock(), 86400)))

    def start(self, email: str, cohort: str = ""):
        """이 이메일로 로그인 — 계정이 없으면 만든다. 초대 링크 묶음은 처음 한 번만 붙는다."""
        self.con.execute("insert or ignore into users (email, created_at) values (?, ?)", (email, datetime.now().isoformat()))
        if COHORT.fullmatch(cohort):
            self.con.execute("update users set cohort = ? where email = ? and cohort is null", (cohort, email))
        self.con.commit()
        (u,) = self.con.execute("select id from users where email = ?", (email,)).fetchone()
        return self.see("/", ("Set-Cookie", session_cookie(u, self.secret, self.clock())))

    def login(self, email: str, agreed: bool = False, cohort: str = ""):
        if "@" not in email or len(email) > 200:
            return "200 OK", [], self.login_page()
        if not agreed:
            return "200 OK", [], self.login_page(error="개인정보 수집·이용에 동의해야 시작할 수 있어요.", cohort=cohort)
        # 누구든 메일로 온 링크를 눌러야 들어온다 — 남의 이메일을 넣어 남의 계정에 들어가거나, 남의 이메일로 가입하지 못하게 (공개 출시 준비 10/10)
        now = self.clock()
        times = [t for t in self.sent.get(email, []) if now - t < 3600]
        if (times and now - times[-1] < LOGIN_GAP) or len(times) >= LOGIN_HOURLY:
            return "429 Too Many Requests", [], self.login_page(error="링크를 방금 보냈어요. 메일함을 먼저 확인하고, 잠시 뒤에 다시 요청해 주세요.", cohort=cohort)
        ip = "ip:" + getattr(self.local, "ip", "")
        by_ip, by_all = ([t for t in self.sent.get(k, []) if now - t < 3600] for k in (ip, "*"))
        if len(by_ip) >= LOGIN_IP_HOURLY or len(by_all) >= LOGIN_ALL_HOURLY:
            return "429 Too Many Requests", [], self.login_page(error="로그인 요청이 너무 많아요. 한 시간쯤 뒤에 다시 해 주세요.", cohort=cohort)
        if len(self.sent) > 2000:  # 한 시간 지난 요청 기록·만료된 코드를 비운다 — 주소·IP 마다 한 칸씩 끝없이 늘지 않게
            self.sent = {k: v for k, v in self.sent.items() if v and now - v[-1] < 3600}
            self.codes = {k: v for k, v in self.codes.items() if now <= v[1]}
        self.sent |= {email: times + [now], ip: by_ip + [now], "*": by_all + [now]}
        link = f"{mail.base_url()}/auth?t={quote(login_token(email, self.secret, now))}" + (f"&c={cohort}" if COHORT.fullmatch(cohort) else "")
        # 앱 심사자(구글·애플)는 메일을 받을 수 없다 — .env 에 정해 둔 주소로는 메일 없이, 정해 둔 코드로 들어온다. 나머지(15분·5번 틀리면 버림·한 시간 5번)는 같다
        # ponytail: 6자리 고정 코드 — 주소까지 알아도 한 시간 25번(100만 가지)이고 빈 일반 계정일 뿐이다. 심사가 끝나면 .env 에서 지운다
        fixed = sources.env().get("REVIEW_CODE", "") if email == sources.env().get("REVIEW_EMAIL", "").strip().lower() else ""
        review = len(fixed) == 6 and fixed.isdigit()
        code = fixed if review else f"{secrets.randbelow(10**6):06d}"
        self.codes[email] = [code, now + LINK_TTL, 0]  # ponytail: 메모리에 — 서버를 다시 켜면 코드는 사라지고 링크만 남는다(링크는 서명이라 그대로 된다)
        if not review:
            with self.outside():  # 메일 서버와 주고받는 수 초 동안 다른 화면은 돈다
                mail.send(email, *mail.login_mail(link, code))  # SMTP 설정이 없으면 서버 콘솔에 찍힌다
        return "200 OK", [], self.login_page(email, cohort=cohort)

    def login_code(self, email: str, code: str, cohort: str = ""):
        """메일로 받은 6자리 코드로 들어온다. 틀리면 CODE_TRIES 번까지 — 넘으면 그 코드는 버리고 새로 받아야 한다
        (6자리는 100만 가지라 마구 넣어 볼 수 있다. 코드 하나에 5번, 새 코드는 한 시간에 5통 → 한 시간에 많아야 25번)."""
        row = self.codes.get(email)
        if not row or self.clock() > row[1]:
            self.codes.pop(email, None)
            return "200 OK", [], self.login_page(error="코드가 만료됐어요. 이메일을 넣고 새로 받아 주세요.", cohort=cohort)
        if not hmac.compare_digest(row[0], code.strip()):
            row[2] += 1
            if row[2] >= CODE_TRIES:
                del self.codes[email]
                return "200 OK", [], self.login_page(error="코드를 여러 번 틀렸어요. 이메일을 넣고 새로 받아 주세요.", cohort=cohort)
            return "200 OK", [], self.login_page(email, error=f"코드가 맞지 않아요. 메일의 숫자 6자리를 다시 봐 주세요. ({CODE_TRIES - row[2]}번 남음)", cohort=cohort)
        del self.codes[email]  # 한 번만 쓴다
        return self.start(email, cohort)
