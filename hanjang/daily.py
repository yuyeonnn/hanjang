"""매일 아침 한 번에 — 받기 → 노트 → (월요일만) 안내 메일. `python -m hanjang.daily` (매일 07:00 예약 실행).
월요일은 그 주 노트를 전부 새로 쓰고, 화~일은 사실이 바뀐 종목만 다시 쓴다(밤비처럼 「자주 받고, 바뀐 것만 쓴다」).
단계 하나가 실패해도 다음 단계는 돈다(실패한 단계는 운영자에게 메일). DART 가 쉬는 날엔 DART 가 필요한 일만 건너뛰고, 13시·19시에 다시 해 본다.
안내 메일은 받기와 노트가 다 된 날만 — 빈 노트로 보내지 않게."""

import json
import sqlite3
import subprocess
import sys
import traceback
from datetime import date, timedelta

from hanjang import articles, backup, collect, db, etf, gurus, holders, morning, nps, llm, mail, notes, personas, sources, us


def src(con: sqlite3.Connection, rno: str | None) -> str:
    """일정의 원문 — 국내 접수번호는 DART, 미국 접수번호(「-」가 있다)는 SEC 공시 목록."""
    if not rno:
        return ""
    if "-" not in rno:
        return notes.DART.format(rno)
    row = con.execute("select s.cik from filings f join stocks s using(ticker) where f.accession = ?", (rno,)).fetchone()
    return f"https://www.sec.gov/Archives/edgar/data/{row[0]}/{rno.replace('-', '')}/{rno}-index.htm" if row else ""


def notify(con: sqlite3.Connection, week: str) -> int:
    """담은 종목 중 이번 주 노트가 있는 사용자에게만 한 통씩 — 프로필에서 메일을 끈 사람은 빼고.
    한 통에 담은 종목 노트 전부 + 보내는 날부터 7일 캘린더 (휴장일 · 내 종목 일정)."""
    rows = con.execute(
        "select u.id, u.email, s.ticker, s.name, n.body, n.facts from users u join holdings h on h.user_id = u.id join stocks s using(ticker)"
        " join notes n on n.ticker = s.ticker and n.week = ? where u.mail_on = 1 order by u.id, h.added_at", (week,)).fetchall()  # fmt: skip
    by: dict[tuple, list[dict]] = {}
    for uid, email, t, name, body, facts in rows:
        fin = con.execute("select fiscal_year, revenue, operating_income from financials where ticker = ?"
                          " order by fiscal_year desc limit 5", (t,)).fetchall()[::-1]  # 노트 화면 그림과 같은 숫자
        by.setdefault((uid, email), []).append({"ticker": t, "name": name, "body": json.loads(body), "facts": json.loads(facts), "fin": fin})
    lo, hi = week, (date.fromisoformat(week) + timedelta(days=6)).isoformat()
    hol = con.execute("select date, name from holidays where date between ? and ? order by date", (lo, hi)).fetchall()
    for (uid, email), stocks in by.items():
        # events = 공시 원문에서 읽은 앞으로의 일정 (collect — 실적 발표·주총·배당 기준일·지급일)
        evs = con.execute(
            "select e.date, s.name, e.kind, e.title, e.rcept_no from events e join holdings h on h.ticker = e.ticker and h.user_id = ?"
            " join stocks s on s.ticker = e.ticker where e.date between ? and ? order by e.date", (uid, lo, hi)).fetchall()  # fmt: skip
        evs = [(d, n, t, "", src(con, r), 0) for d, n, _, t, r in evs]  # 칩에는 쉬운 말(「실적 발표」)
        evs += [(d, {"KR": "한국", "US": "미국"}[nat], {"금리": "금리 결정", "선거": "선거", "휴장": "증시 휴장"}.get(kind, kind + " 발표"), "", sources.MACRO_SOURCE[nat + kind][1], 0)
                for d, kind, nat, _ in sources.macro_events(lo, hi)
                if kind != "휴장" or any(s["ticker"][:1].isalpha() and not s["ticker"].startswith("ETF") for s in stocks)]  # 미국 휴장은 미국 종목이 있을 때만  # 시장 일정 — 금리·물가·고용·선거  # fmt: skip
        mail.send(email, *mail.weekly_mail(week, stocks, evs, hol))
    return len(by)


STATE = db.PATH.parent / "daily.json"  # 오늘 실행이 어디까지 됐나 — 오후 다시 돌기(13시·19시 타이머)가 읽는다


def today_state(today: date) -> dict:
    try:
        s = json.loads(STATE.read_text(encoding="utf-8"))
        return s if s.get("date") == today.isoformat() else {}
    except (OSError, ValueError):
        return {}


def apart(code: str) -> None:
    """메모리를 많이 쓰는 단계는 따로 띄운 파이썬에서 — 끝나면 그 메모리가 운영체제로 돌아간다.
    한 프로세스에서 다 돌리면 앞 단계가 쓴 메모리가 잘 돌아오지 않고 쌓여, 1GB 서버에서 350MB 까지 올랐다(미국 받기 혼자 185MB · 메모리 점검 10/11).
    출력은 그대로 서버 기록에 찍히고, 실패하면 예외(CalledProcessError)로 올라와 step 이 알린다. AI 를 쓰는 단계는 여기 넣지 않는다(비용 합계·상한이 이 프로세스에 있다)."""
    subprocess.run([sys.executable, "-X", "utf8", "-c", "import sys; sys.stdout.reconfigure(encoding='utf-8'); " + code], check=True)


def brief(con: sqlite3.Connection, today: date) -> int:
    """아침 소식 메일 — 「아침 한 장」과 같은 내용을, 내 종목에 새 소식이 있거나 오늘·내일 내 종목 일정이 있는 사람에게만 한 통.
    안내 메일을 끈 사람·막힌 계정·종목을 안 담은 사람은 빼고. 한 사람이 실패해도 나머지는 보낸다."""
    soon, n = (today + timedelta(days=1)).isoformat(), 0
    for uid, email in con.execute("select id, email from users where mail_on = 1 and coalesce(banned, 0) = 0").fetchall():
        tickers = [t for (t,) in con.execute("select ticker from holdings where user_id = ? order by added_at", (uid,))]
        if not tickers:
            continue
        m = morning.build(con, tickers, today, uid)
        if not (m["news"] or any(x.get("url") and x["date"] <= soon for x in m["week"])):
            continue  # 새로 알릴 것이 없으면 보내지 않는다 — 알림은 적게, 정확하게
        try:
            mail.send(email, *mail.morning_mail(m, morning.text(m)))
            n += 1
        except Exception as err:  # noqa: BLE001
            print(f"아침 소식 메일 실패 (사용자 {uid}) — {type(err).__name__}", file=sys.stderr)
    return n


def main(today: date) -> None:
    """하루 세 번 불린다(07·13·19시). 아침에 끝까지 돌았으면 오후엔 바로 끝난다. DART 가 쉬는 날(점검)엔 DART 가 필요한 일만 건너뛰고
    나머지는 어제까지의 자료로 끝까지 돈다 — 오후에 DART 가 돌아오면 그때 마저 한다(월요일 안내 메일도 그때).
    단계 하나가 실패해도 다음 단계는 돈다. 실패한 단계는 운영자에게 알리고, 끝에 실패로 끝낸다(journalctl·systemctl 에 보이게)."""
    before = today_state(today)
    if before.get("complete"):
        print("오늘은 이미 끝까지 돌았어요 — 건너뜀")
        return
    dart_up = sources.Dart().up()
    if before and not before.get("failed") and not dart_up:
        print("DART 가 아직 쉬는 중 — 아침에 한 것 말고 더 할 일이 없어요")
        return
    failed: list[str] = []

    def step(name: str, fn, *a, **k) -> bool:
        try:
            fn(*a, **k)
            return True
        except Exception as err:  # noqa: BLE001
            failed.append(name)
            print(f"{name} 실패 — {type(err).__name__}: {err}", file=sys.stderr)
            alert(err, f"{name} 실패 — 나머지는 계속")
            return False

    if not dart_up:
        print("DART 점검 — 국내 받기·사업보고서 읽기·ETF·큰손은 건너뛰고 나머지는 어제까지의 자료로")
        if "dart" not in before and (to := sources.env().get("SMTP_USER")):  # 하루 한 번만
            mail.send(to, "[한장] DART 점검 — 국내 받기는 건너뛰고 나머지는 돌았어요",
                      "DART 가 대답하지 않아(점검) 국내 공시·재무 받기, 사업보고서 읽기, ETF, 큰손은 건너뛰었어요. 13시·19시에 다시 해 봐요. 할 일은 없어요.")
    monday = today.weekday() == 0 and dart_up and not before.get("mailed")  # 새 자료 없이 그 주 노트를 다 새로 쓰거나 안내 메일을 보내지 않는다
    saved = backup.backup(today)  # 받기 전에 — 오늘 실행이 DB 를 망가뜨려도 어제 것으로 돌아갈 수 있게
    print(f"백업 {saved}")
    try:
        print(f"서버 밖 백업 {backup.offsite(saved)}")
    except Exception as err:  # 서버 밖에 못 올려도 오늘 노트는 쓴다 — 운영자에게만 알린다
        alert(err, "서버 밖 백업 실패")
    day = f"date.fromisoformat('{today.isoformat()}')"
    got = step("국내 받기", apart, f"from datetime import date; from hanjang import collect; collect.main({day}, {dart_up})")
    step("미국 받기", apart, f"from datetime import date; from hanjang import us; us.main({day})")  # 미국 주식 받기 (SEC) — 노트·화면은 아직 (docs/stage3-us.md)
    step("미국 읽기", us.read, today)  # 미국 10-K 사업 설명 · 실적 전망 (AI) — 새 보고서만
    wrote = step("노트", notes.main, [], today, only_changed=not monday, read=dart_up, carry=monday, batch=True)  # 월요일 — 사실이 그대로인 노트는 옮겨 적는다
    if dart_up:
        step("ETF", etf.main, today)  # 담은 ETF 한 장 — 투자설명서 표지로, AI 없이
    step("기사", articles.main, today)  # 피드 「최근 소식」 — 새 사건마다 기사 한 편 (원문을 못 받으면 쓰지 않는다)
    step("아침 한 장", lambda: print(f"아침 한 장 문장 {morning.prepare(db.connect(), today)}건"))  # 코드 풀이가 없는 공시만 AI 한 문장 — 공시마다 한 번
    if dart_up:
        step("큰손", holders.main, today)  # 큰손 포트폴리오 — 최근 일주일 대량보유 보고만 더한다
    step("유명 투자자", gurus.main, today)  # 미국 유명 투자자 13F — 새 신고가 나온 사람만 다시 받는다
    step("정리", lambda: print(f"정리 — 지운 줄 {db.tidy(db.connect(), today)}"))  # 반년 지난 열어본 기록 · 두 달 지난 소식
    step("국민연금", nps.main, today)  # 국민연금 한국+미국 — 1년에 한 번 새 공시(공공데이터포털), 같은 날 13F
    if sources.env().get("DEMO") == "1":  # 둘러보기 예시 사람들 — 활동 시각을 다시 「최근」으로
        step("예시 사람", lambda: print(f"예시 사람 {personas.seed(db.connect())}명"))
    mailed = bool(before.get("mailed"))
    if monday and got and wrote:  # 빈 노트로 안내 메일을 보내지 않게 — 받기와 노트가 다 된 날만
        mailed = step("안내 메일", lambda: print(f"안내 메일 {notify(db.connect(), notes.week_of(today))}명"))
    # 아침 소식 메일 — 하루 한 번, 화~토(월요일은 소식지가 나가고, 일요일은 토요일에 이미 금요일 소식을 보냈다)
    briefed = bool(before.get("briefed"))
    if not briefed and got and 1 <= today.weekday() <= 5:
        briefed = step("아침 소식 메일", lambda: print(f"아침 소식 메일 {brief(db.connect(), today)}명"))
    if llm.spent.get("no_credit") and (to := sources.env().get("SMTP_USER")):  # 멈추진 않았지만 운영자는 알아야 한다
        mail.send(to, "[한장] OpenAI 크레딧 소진 — 오늘 노트는 코드 문장으로", "platform.openai.com 결제(Billing)에서 크레딧을 채우면 다음 실행부터 AI 글로 돌아와요.")
    STATE.write_text(json.dumps({"date": today.isoformat(), "dart": dart_up, "failed": failed, "mailed": mailed, "briefed": briefed,
                                 "complete": dart_up and not failed}, ensure_ascii=False), encoding="utf-8")  # fmt: skip
    if failed:
        raise SystemExit(f"실패한 단계: {', '.join(failed)}")


def alert(err: BaseException, what: str = "매일 실행 실패") -> None:
    """실패하면 운영자(보내는 Gmail 계정)에게 바로 알린다 — 서버 로그를 매일 들여다보지 않아도 되게. 메일이 안 오면 잘 돈 것."""
    to = sources.env().get("SMTP_USER")
    if to:
        mail.send(to, f"[한장] {what} — {type(err).__name__}", "".join(traceback.format_exception(err)))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        main(date.today())
    except Exception as err:
        alert(err)
        raise
