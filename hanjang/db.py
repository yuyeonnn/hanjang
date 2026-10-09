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
create table if not exists regrams (
  id integer primary key, user_id integer not null references users, kind text not null, ref text not null,
  week text not null default '', comment text, at text not null, unique (user_id, kind, ref, week));
create table if not exists feedback (
  id integer primary key, user_id integer not null references users, ticker text, week text,
  helpful integer, would_pay integer, comment text, at text not null);
"""


def connect(path=PATH) -> sqlite3.Connection:
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=30)  # 매일 실행이 쓰는 동안 화면이 읽고 써도 잠깐 기다린다
    con.execute("pragma journal_mode = wal")  # 읽기와 쓰기가 서로 막지 않게 (파일에 남는다)
    con.execute("pragma foreign_keys = on")
    con.executescript(SCHEMA)
    # ponytail: 열 추가는 이렇게 한 줄씩. 늘어나면 번호 붙인 마이그레이션으로
    for table, col, typ in (("financials", "basis", "text"), ("stocks", "induty_code", "text"),
                            ("disclosures", "amount", "integer"),
                            ("users", "mail_on", "integer not null default 1"),  # 주간 안내 메일 켜짐(1)/꺼짐(0)
                            ("users", "nickname", "text"), ("users", "bio", "text"),
                            ("users", "photo", "blob"), ("users", "photo_at", "text"),
                            ("stocks", "homepage", "text"), ("big_holdings", "induty_code", "text"),
                            ("news", "summary", "text")):  # RSS 요약문 — 기사 본문이 아니다  # 회사 홈페이지 도메인 — 로고(Brandfetch)를 찾는다  # 프로필 사진(256px JPEG) · 바꾼 때(캐시 무효화)  # 남에게 보이는 이름·자기소개 (이메일은 안 보인다)  # fmt: skip
        if col not in {r[1] for r in con.execute(f"pragma table_info({table})")}:
            con.execute(f"alter table {table} add column {col} {typ}")
    con.execute("create unique index if not exists users_nickname on users (nickname collate nocase)")
    return con
