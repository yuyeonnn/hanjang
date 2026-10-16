"""운영자 인사이트 — 누가 언제 어디서 들어와 가입했고, 그 뒤 얼마나 쓰는지 (사용자 10/16). `.env` 의 ADMIN_EMAILS 에 적힌 운영자만 연다.
손님 기록(visits)은 무작위 번호 쿠키(g) 하나로 묶은 것뿐이다 — 이름·이메일·IP 는 없다. 가입하면 그 번호의 지난 기록에 회원 번호가 붙는다.
회원 기록은 users·views·holdings 에서 읽는다. 예시 계정(persona)·둘러보기 계정·운영자 본인은 숫자에서 뺀다."""

from datetime import date, timedelta

from hanjang import sources
from hanjang.personas import DEMO_EMAIL
from hanjang.ui import e, page

PAGE_NAMES = {"cards": "내 종목", "note": "노트", "feed": "피드", "calendar": "캘린더", "learn": "읽기 팁", "article": "읽기 팁 글", "me": "프로필", "user": "남의 프로필"}
CELL = "padding:6px 8px;border-bottom:1px solid #e6e1e5;vertical-align:top"


def when(at: str | None) -> str:
    """「2026-10-16T09:12:33」 → 「10/16 09:12」."""
    return f"{at[5:7]}/{at[8:10]} {at[11:16]}" if at and len(at) >= 16 else (at or "—")


def table(head: list[str], rows: list[list[str]]) -> str:
    """칸 안의 글은 이미 이스케이프한 HTML."""
    th = "".join(f'<th style="{CELL};text-align:left;white-space:nowrap;color:#5b605d;font-weight:600">{h}</th>' for h in head)
    tr = "".join("<tr>" + "".join(f'<td style="{CELL}">{c}</td>' for c in r) + "</tr>" for r in rows)
    return f'<div style="overflow-x:auto"><table style="border-collapse:collapse;font-size:13px;min-width:100%"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'


def section(title: str, body: str, note: str = "") -> str:
    return (f'<section style="margin-top:28px"><h2 class="font-headline-sm text-headline-sm text-primary">{title}</h2>'
            + (f'<p class="text-[12px] text-on-surface-variant" style="margin:2px 0 8px">{note}</p>' if note else '<div style="height:8px"></div>') + body + "</section>")


class InsightPages:
    def admins(self) -> set[str]:
        return {x.strip().lower() for x in sources.env().get("ADMIN_EMAILS", "").split(",") if x.strip()}

    def is_admin(self, uid: int) -> bool:
        row = self.con.execute("select email from users where id = ?", (uid,)).fetchone()
        return bool(row and row[0] in self.admins())

    def skip_ids(self) -> list[int]:
        """숫자에서 뺄 계정 — 예시 계정·둘러보기·운영자."""
        admins = sorted(self.admins())
        return [r[0] for r in self.con.execute(
            f"select id from users where email like '%@persona.hanjang.local' or email = ? or email in ({','.join('?' * len(admins)) or 'null'})", (DEMO_EMAIL, *admins))]

    def insights(self, days: int) -> str:
        q, skip = self.con.execute, self.skip_ids()
        no = f"coalesce(uid, 0) not in ({','.join('?' * len(skip)) or 'null'})"
        today = date.today()
        lo = (today - timedelta(days=days - 1)).isoformat()
        came = q(f"select count(distinct gid) from visits where kind = 'open' and at >= ? and {no}", (lo, *skip)).fetchone()[0]
        gated = q(f"select count(distinct gid) from visits where kind = 'gate' and at >= ? and {no}", (lo, *skip)).fetchone()[0]
        joined = q(f"select count(*) from users where created_at >= ? and id not in ({','.join('?' * len(skip)) or 'null'})", (lo, *skip)).fetchone()[0]
        rate = f"{joined / came:.0%}" if came else "—"
        tabs = " ".join(f'<a href="/admin?d={d}" style="padding:4px 10px;border-radius:999px;border:1px solid #c4c7c5;{"background:#154539;color:#fff" if d == days else ""}">{d}일</a>' for d in (7, 30, 90))
        funnel = table(["손님으로 들어온 사람", "가입하려다 막힌 사람", "가입한 사람", "가입률"], [[f"<b>{came}</b>", f"<b>{gated}</b>", f"<b>{joined}</b>", rate]])
        refs = q(f"select coalesce(nullif(ref, ''), '직접·알 수 없음'), count(distinct gid) from visits where kind = 'open' and at >= ? and {no} group by 1 order by 2 desc limit 12", (lo, *skip)).fetchall()
        walls = q(f"select path, count(distinct gid) from visits where kind = 'gate' and at >= ? and {no} group by 1 order by 2 desc limit 12", (lo, *skip)).fetchall()
        daily = []
        for i in range(min(days, 14)):  # 최근 두 주만 — 더 길면 0 줄만 이어진다
            d = (today - timedelta(days=i)).isoformat()
            nxt = (today - timedelta(days=i - 1)).isoformat()
            c, g = (q(f"select count(distinct gid) from visits where kind = ? and at >= ? and at < ? and {no}", (k, d, nxt, *skip)).fetchone()[0] for k in ("open", "gate"))
            j = q(f"select count(*) from users where created_at >= ? and created_at < ? and id not in ({','.join('?' * len(skip)) or 'null'})", (d, nxt, *skip)).fetchone()[0]
            a = q(f"select count(distinct user_id) from views where at >= ? and at < ? and user_id not in ({','.join('?' * len(skip)) or 'null'})", (d, nxt, *skip)).fetchone()[0]
            daily.append([f"{d[5:7]}/{d[8:]}", str(c), str(g), str(j), str(a)])
        week = (today - timedelta(days=6)).isoformat()
        members = []
        for uid, email, nick, created, cohort, held, active, last, recent, first, ref, wall in q(
                "select u.id, u.email, u.nickname, u.created_at, u.cohort,"
                " (select count(*) from holdings h where h.user_id = u.id),"
                " (select count(distinct substr(at, 1, 10)) from views v where v.user_id = u.id),"
                " (select max(at) from views v where v.user_id = u.id),"
                " (select count(*) from views v where v.user_id = u.id and at >= ?),"
                " (select min(at) from visits w where w.uid = u.id),"
                " (select ref from visits w where w.uid = u.id and kind = 'open' order by at limit 1),"
                " (select group_concat(path, ' · ') from (select path from visits w where w.uid = u.id and kind = 'gate' order by at limit 3))"
                " from users u where u.email not like '%@persona.hanjang.local' and u.email != ? order by u.created_at desc", (week, DEMO_EMAIL)):
            tag = " <span style='color:#8a6d00'>(운영자)</span>" if email in self.admins() else ""
            members.append([f'<a class="text-primary underline" href="/admin/u/{uid}">{e(email)}</a>{tag}', e(nick or "—"), when(created),
                            e(when(first)) + (f"<br><span style='color:#5b605d'>{e(ref)}</span>" if ref else ""), e(wall or "—"),
                            str(held), f"{active}일", when(last), str(recent), e(cohort or "")])
        body = (f'<main class="w-full max-w-[1100px] mx-auto px-margin pt-8 pb-16"><h1 class="font-headline-lg text-headline-lg">인사이트</h1>'
                f'<p class="text-[12px] text-on-surface-variant" style="margin:4px 0 12px">예시 계정·둘러보기·운영자는 숫자에서 뺐어요. 손님 기록은 무작위 번호 쿠키로만 묶여 있어요(이름·이메일·IP 없음).</p>'
                f'<nav style="display:flex;gap:6px;font-size:13px">{tabs}</nav>'
                + section("깔때기", funnel, "들어온 사람 = 그 기간에 한 번이라도 화면을 연 브라우저 수. 막힌 사람 = 둘러보다 담기·프로필 같은 것을 눌러 가입 화면을 본 브라우저 수.")
                + section("어디서 들어왔나", table(["들어온 곳", "사람"], [[e(r), str(n)] for r, n in refs]) if refs else "<p>아직 기록이 없어요.</p>",
                          "링크를 누른 곳의 주소 이름 · utm_source · 초대 링크 묶음. 비어 있으면 주소를 직접 쳤거나 앱·메신저 안에서 열린 것.")
                + section("가입 화면을 본 까닭", table(["누른 것", "사람"], [[e(p), str(n)] for p, n in walls]) if walls else "<p>아직 기록이 없어요.</p>")
                + section("날마다", table(["날", "들어온 사람", "막힌 사람", "가입", "쓴 회원"], daily), "쓴 회원 = 그날 화면을 하나라도 연 회원 수.")
                + section(f"회원 {len(members)}명", table(["이메일", "닉네임", "가입", "처음 온 때 · 경로", "가입 전 누른 것", "담은 종목", "들어온 날", "마지막", "최근 7일 열람", "초대 묶음"], members),
                          "이메일을 누르면 그 사람이 언제 무엇을 봤는지 나와요.")
                + "</main>")
        return page("인사이트", "bg-surface font-body-reading text-on-surface", body)

    def insight_user(self, uid: int) -> str | None:
        q = self.con.execute
        row = q("select email, nickname, created_at, cohort, mail_on from users where id = ?", (uid,)).fetchone()
        if not row:
            return None
        email, nick, created, cohort, mail_on = row
        held = q("select s.name, h.added_at from holdings h join stocks s using(ticker) where h.user_id = ? order by h.added_at", (uid,)).fetchall()
        days = q("select substr(at, 1, 10), count(*), group_concat(distinct page) from views where user_id = ? group by 1 order by 1 desc limit 60", (uid,)).fetchall()
        recent = q("select v.at, v.page, s.name from views v left join stocks s on s.ticker = v.ticker where v.user_id = ? order by v.at desc limit 100", (uid,)).fetchall()
        visits = q("select at, kind, path, ref from visits where uid = ? order by at limit 100", (uid,)).fetchall()
        name = {"open": "들어옴", "gate": "가입 화면", "signup": "가입", "login": "로그인"}
        body = (f'<main class="w-full max-w-[900px] mx-auto px-margin pt-8 pb-16"><a class="text-primary underline text-[13px]" href="/admin">← 인사이트</a>'
                f'<h1 class="font-headline-lg text-headline-lg" style="margin-top:8px">{e(nick or "닉네임 없음")}</h1>'
                f'<p class="text-[13px] text-on-surface-variant">{e(email)} · 가입 {when(created)}' + (f" · 초대 묶음 {e(cohort)}" if cohort else "") + f' · 메일 {"받음" if mail_on else "끔"}</p>'
                + section(f"담은 종목 {len(held)}개", table(["종목", "담은 때"], [[e(n), when(a)] for n, a in held]))
                + section("방문·가입 기록", table(["때", "일", "화면·누른 것", "들어온 곳"], [[when(a), name.get(k, k), e(p or ""), e(r or "")] for a, k, p, r in visits]) if visits else "<p>기록 이전에 가입한 분이에요(방문 기록은 10/16부터).</p>")
                + section("날마다 연 화면", table(["날", "열람", "화면"], [[d[5:].replace("-", "/"), str(n), e(" · ".join(PAGE_NAMES.get(x, x) for x in (pg or "").split(",")))] for d, n, pg in days]))
                + section("최근 연 화면 100개", table(["때", "화면", "종목"], [[when(a), e(PAGE_NAMES.get(p, p)), e(s or "")] for a, p, s in recent]))
                + "</main>")
        return page("인사이트", "bg-surface font-body-reading text-on-surface", body)
