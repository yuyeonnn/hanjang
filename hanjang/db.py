"""SQLite 한 파일 — 표 정의는 docs/erd.md 가 정본. 같은 데이터를 다시 넣어도 PK 로 덮어쓴다(멱등).
prices · betas 는 아직 만들지 않는다 — 시세를 쓸 권리가 없다 (docs/data-rights.md §4)."""

import sqlite3

from hanjang.sources import ROOT

PATH = ROOT / "data" / "hanjang.db"

SCHEMA = """
create table if not exists stocks (
  ticker text primary key, name text not null, corp_code text, active integer not null default 1);
create table if not exists financials (
  ticker text not null references stocks, fiscal_year integer not null,
  revenue integer, operating_income integer, net_income integer, equity integer, liabilities integer,
  rcept_no text not null, basis text, primary key (ticker, fiscal_year));
create table if not exists disclosures (
  rcept_no text primary key, ticker text not null references stocks, date text not null,
  title text not null, code text, importance integer, direction integer, risk_tags text,
  new_share real, quote text, read_model text, read_at text);
create table if not exists macro (
  series_id text not null, date text not null, value real not null,
  primary key (series_id, date));
create table if not exists news (
  url text primary key, ticker text not null references stocks, date text not null,
  press text, title text not null);
create table if not exists insiders (
  rcept_no text primary key, ticker text not null references stocks, date text not null, kind text not null,
  who text not null, change integer, rate real, rate_chg real);
create table if not exists dividends (
  ticker text not null references stocks, fiscal_year integer not null, dps integer, total integer, payout real,
  primary key (ticker, fiscal_year));
create table if not exists quarters (
  ticker text not null references stocks, year integer not null, q integer not null,
  revenue integer, operating_income integer, revenue_prev integer, op_prev integer,
  revenue_ytd integer, op_ytd integer, revenue_ytd_prev integer, op_ytd_prev integer,
  rcept_no text not null, basis text, primary key (ticker, year, q));
create table if not exists business (
  ticker text primary key references stocks, rcept_no text not null, body text not null, read_model text, read_at text);
create table if not exists prices (
  ticker text not null references stocks, date text not null, close integer not null, primary key (ticker, date));
create table if not exists articles (
  id integer primary key, ref text unique not null, ticker text not null references stocks, date text not null,
  kind text not null, body text not null, made_at text not null);
create table if not exists big_pairs (
  inst text not null, corp_code text not null, stock_code text not null, corp_name text not null, corp_cls text,
  primary key (inst, corp_code));
create table if not exists big_holdings (
  inst text not null, stock_code text not null, corp_name text not null, corp_cls text, rate real not null,
  rate_chg real, date text not null, rcept_no text not null, primary key (inst, stock_code));
create table if not exists holidays (date text primary key, name text not null);
create table if not exists sics (cik integer primary key, sic text not null);
create table if not exists alerted (rcept_no text primary key);  -- 그날 바로 알린 공시 — 공시마다 한 번 (daily.watch)
create table if not exists nps_port (asof text not null, market text not null, name text not null, ticker text, won real not null, stake real);
create table if not exists nps_meta (asof text primary key, fx real not null, accn text not null);
create table if not exists guru_holdings (
  guru text not null, cusip text not null, issuer text not null, ticker text, value real not null, shares real not null,
  weight real not null, accn text not null, period text not null, filed text not null, primary key (guru, cusip));
create table if not exists filings (
  accession text primary key, ticker text not null references stocks, form text not null, date text not null, at text,
  items text, doc text, filed_us text);
create table if not exists outlooks (ticker text primary key references stocks, accession text not null, date text not null, body text not null);
create table if not exists skipped (accession text primary key, ticker text not null);
create table if not exists flows (
  ticker text not null references stocks, period_start text not null, period_end text not null, months integer,
  buyback real, dividends real, sbc real, accn text, primary key (ticker, period_start, period_end));
create table if not exists etfs (
  ticker text primary key references stocks, name text not null, rcept_no text not null, filed text not null,
  info text, read_rcept text);
create table if not exists bonds (
  rcept_no text not null, tm text not null, ticker text not null references stocks, pay_date text not null, amount integer not null,
  maturity text, rate text, lead text, uses text, primary key (rcept_no, tm));
create table if not exists ipos (
  corp_code text primary key, rcept_no text not null, name text not null, sub_start text not null, sub_end text not null,
  pay_date text, list_date text, price integer, total integer, lead text, uses text);
create table if not exists events (
  ticker text not null references stocks, date text not null, kind text not null,
  title text not null, rcept_no text, primary key (ticker, date, kind));
create table if not exists notes (
  ticker text not null references stocks, week text not null, facts text not null,
  body text not null, writer text not null, made_at text not null, primary key (ticker, week));
create table if not exists users (
  id integer primary key, email text unique not null, cohort text, created_at text not null);
create table if not exists holdings (
  user_id integer not null references users, ticker text not null references stocks,
  added_at text not null, primary key (user_id, ticker));
create table if not exists views (
  id integer primary key, user_id integer not null references users, page text not null,
  ticker text, at text not null);
create table if not exists likes (
  user_id integer not null references users, ticker text not null references stocks, week text not null,
  at text not null, primary key (user_id, ticker, week));
create table if not exists follows (
  follower_id integer not null references users, followee_id integer not null references users,
  at text not null, primary key (follower_id, followee_id));
create table if not exists quiz_done (
  user_id integer not null references users, slug text not null, at text not null, primary key (user_id, slug));
create table if not exists regrams (
  id integer primary key, user_id integer not null references users, kind text not null, ref text not null,
  week text not null default '', comment text, at text not null, unique (user_id, kind, ref, week));
create table if not exists article_tries (ref text primary key, n integer not null, at text not null);
create table if not exists saves (
  id integer primary key, user_id integer not null references users, kind text not null, ref text not null,
  week text not null default '', comment text, at text not null, unique (user_id, kind, ref, week));
create table if not exists highlights (
  id integer primary key, user_id integer not null references users, page text not null,
  s integer not null, e integer not null, text text not null, color text not null, at text not null);
create table if not exists blocks (
  user_id integer not null references users, blocked_id integer not null references users, at text not null,
  primary key (user_id, blocked_id));
create table if not exists reports (
  id integer primary key, user_id integer not null references users, target_id integer not null,
  why text not null, at text not null, done_at text);
create table if not exists feedback (
  id integer primary key, user_id integer not null references users, ticker text, week text,
  helpful integer, would_pay integer, comment text, at text not null);
"""


def tune(con: sqlite3.Connection) -> sqlite3.Connection:
    """연결마다 — 파일에 남지 않는 설정 (DB 점검 10/11, 서버 디스크 실측).
    synchronous=normal: WAL 에서는 커밋마다 디스크 확인(fsync)을 기다리지 않는다 — 서버에서 커밋 한 번 2.4ms → 0.04ms.
      화면을 열 때마다 열어본 기록을 쓰는데, 요청을 한 번에 하나씩 처리하니 그 2.4ms 가 모두의 기다림이었다.
      앱이 죽어도 안전하고, 운영체제가 통째로 죽거나 정전일 때만 마지막 몇 건을 잃는다(하루 백업이 있다).
    cache_size 16MB: DB(6.5MB) 전체가 메모리에 올라간다. temp_store: 정렬·그룹 작업을 디스크가 아니라 메모리에서."""
    con.execute("pragma synchronous = normal")
    con.execute("pragma cache_size = -16000")
    con.execute("pragma temp_store = memory")
    return con


def connect(path=PATH, threads: bool = False) -> sqlite3.Connection:
    """threads=True: 화면 서버처럼 여러 실이 연결 하나를 돌려 쓸 때(잠금은 쓰는 쪽이 건다)."""
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=30, check_same_thread=not threads)  # 매일 실행이 쓰는 동안 화면이 읽고 써도 잠깐 기다린다
    con.execute("pragma journal_mode = wal")  # 읽기와 쓰기가 서로 막지 않게 (파일에 남는다)
    tune(con)
    con.execute("pragma foreign_keys = on")
    con.executescript(SCHEMA)
    migrate(con)
    return con


# 표 구조 변경 — 번호 순서로 한 번씩만. 몇 번까지 적용했는지는 DB 파일 안(pragma user_version)에 남는다.
# 새 열·색인이 필요하면 **맨 끝에** 한 줄 더한다(앞 줄은 고치지 않는다 — 이미 적용된 DB 에는 다시 돌지 않는다).
# 번호 없이 열을 더하던 때의 DB(2026-10-11 이전)는 이미 있는 열을 건너뛰며 번호를 맞춘다.
MIGRATIONS = (
    "alter table financials add column basis text",
    "alter table stocks add column induty_code text",
    "alter table disclosures add column amount integer",
    "alter table disclosures add column plain text",  # 아침 한 장 — 코드 풀이가 없는 공시의 AI 한 문장(공시마다 한 번). 빈 칸 = 물어봤지만 못 씀
    "alter table articles add column photo text",  # 피드 기사 사진 — 한 번 고르면 피드와 기사 화면이 늘 같은 사진 (사용자 10/9)
    "alter table users add column notices_seen text",  # 알림을 마지막으로 본 때 — 그 뒤의 새 팔로우만 빨간 점
    "alter table users add column mail_on integer not null default 1",  # 주간 안내 메일 켜짐(1)/꺼짐(0)
    "alter table users add column days integer",  # 내 나무 — 들어온 날 수(누적). 열어본 기록(views)은 180일 뒤 지워져도 나무는 줄지 않게
    "alter table users add column last_day text",  # 내 나무 — 마지막으로 센 날
    "alter table users add column private integer not null default 0",  # 비공개 계정 (사용자 10/10)
    "alter table follows add column ok integer not null default 1",  # 비공개 계정 팔로우는 요청(ok 0) → 수락하면 1
    "alter table users add column nickname text",  # 남에게 보이는 이름 (이메일은 안 보인다)
    "alter table users add column bio text",  # 자기소개
    "alter table users add column rules_at text",  # 이용 규칙에 동의한 때 — 남에게 보이는 프로필을 만들기 전에 (앱 마켓의 사용자 콘텐츠 요구, 10/11)
    "alter table users add column banned integer not null default 0",  # 운영자가 막은 계정 (python -m hanjang.moderate ban)
    "alter table users add column photo blob",  # 프로필 사진(256px JPEG)
    "alter table users add column photo_at text",  # 사진 바꾼 때(캐시 무효화)
    "alter table stocks add column homepage text",  # 회사 홈페이지 도메인 — 로고(Brandfetch)를 찾는다
    "alter table big_holdings add column induty_code text",
    "alter table guru_holdings add column sic text",
    "alter table news add column summary text",  # RSS 요약문 — 기사 본문이 아니다
    # 미국 주식 (docs/stage3-us.md 1주차) — 시장·SEC 번호·업종·회계연도 끝 · 기간·통화·주당순이익 · 임원 거래의 계획 표시·단가
    "alter table stocks add column market text not null default 'KR'",
    "alter table stocks add column cik integer",
    "alter table stocks add column sic text",
    "alter table stocks add column fye text",
    "alter table financials add column period_start text",
    "alter table financials add column period_end text",
    "alter table financials add column currency text",
    "alter table financials add column eps real",
    "alter table quarters add column period_start text",
    "alter table quarters add column period_end text",
    "alter table quarters add column currency text",
    "alter table quarters add column eps real",
    "alter table insiders add column planned integer",
    "alter table insiders add column price real",
    "create unique index if not exists users_nickname on users (nickname collate nocase)",
    # 화면이 자주 묻는 조회 — 색인이 없으면 표 전체를 훑는다. 요청을 한 번에 하나씩 처리하니 훑는 시간이 곧 모두의 기다림이다 (DB 점검 10/11)
    "create index if not exists views_note on views (page, ticker, at)",  # 이 주 노트를 연 횟수 · 시험 판정
    "create index if not exists views_user on views (user_id, at)",
    "create index if not exists follows_to on follows (followee_id, ok)",
    "create index if not exists highlights_page on highlights (user_id, page)",
    "create index if not exists news_stock on news (ticker, date)",
    "create index if not exists disclosures_stock on disclosures (ticker, date)",
    "create index if not exists regrams_ref on regrams (kind, ref, week)",
    "create index if not exists likes_note on likes (ticker, week)",
    "create index if not exists views_week on views (page, at)",  # 피드 「이번 주 한장」 — 지난 7일 열람을 센다. 열람 30만 줄에서 35ms → 범위만 (규모 점검 10/11)
    # 로그인 요청 기록·코드 — 메모리에 두면 서버를 다시 켤 때(올릴 때마다) 로그인하던 사람의 코드가 사라졌다 (10/12)
    "create table if not exists login_hits (key text not null, at real not null)",  # key: 이메일 · ip:주소 · * (전체)
    "create index if not exists login_hits_key on login_hits (key, at)",
    "create table if not exists login_codes (email text primary key, code text not null, expires real not null, tries integer not null default 0)",
    # 정부 소식 — 정책브리핑 정책뉴스의 제목·주소만(공공누리 제1유형). labels: 걸리는 업종 이름표를 「|반도체|조선|」 모양으로 (data-rights §7, 10/14)
    "create table if not exists policy_news (id text primary key, date text not null, minister text, title text not null, url text not null, labels text not null)",
    "create index if not exists policy_news_date on policy_news (date)",
)


def migrate(con: sqlite3.Connection) -> int:
    """아직 적용하지 않은 번호부터 끝까지 — 적용한 수를 돌려준다. 화면 서버·매일 실행·테스트가 DB 를 열 때마다 부른다(이미 끝났으면 0)."""
    (done,) = con.execute("pragma user_version").fetchone()
    for n, sql in enumerate(MIGRATIONS[done:], done + 1):
        try:
            con.execute(sql)
        except sqlite3.OperationalError as err:
            if "duplicate column" not in str(err):  # 번호 없이 열을 더하던 때의 DB — 이미 있는 열은 건너뛴다
                raise
        con.execute(f"pragma user_version = {n}")
    con.commit()
    return len(MIGRATIONS) - done


VIEWS_DAYS, NEWS_DAYS = 180, 60  # 열어본 기록 · 뉴스룸 소식을 두는 날 수 (개인정보 처리방침 3항과 같게)


def tidy(con: sqlite3.Connection, today) -> dict[str, int]:
    """오래돼 더 쓰지 않는 줄을 지운다 — 매일 실행이 부른다. 지운 줄 수를 돌려준다.
    열어본 기록: 시험 판정(6주)과 「이 주에 몇 번 읽혔나」에만 쓰니 반년이면 넉넉하다. 소식: 노트는 최근 10일 것만 쓴다.
    노트·공시·재무는 지우지 않는다 — 한 해에 수십 MB 로 작고, 지난 노트는 리그램·좋아요가 가리킨다."""
    from datetime import timedelta

    out = {"views": con.execute("delete from views where at < ?", ((today - timedelta(days=VIEWS_DAYS)).isoformat(),)).rowcount,
           "news": con.execute("delete from news where date < ?", ((today - timedelta(days=NEWS_DAYS)).isoformat(),)).rowcount,
           "policy_news": con.execute("delete from policy_news where date < ?", ((today - timedelta(days=NEWS_DAYS)).isoformat(),)).rowcount}
    con.commit()
    return out
