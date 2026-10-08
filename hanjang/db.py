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
create table if not exists business (
  ticker text primary key references stocks, rcept_no text not null, body text not null, read_model text, read_at text);
create table if not exists prices (
  ticker text not null references stocks, date text not null, close integer not null, primary key (ticker, date));
create table if not exists articles (
  id integer primary key, ref text unique not null, ticker text not null references stocks, date text not null,
  kind text not null, body text not null, made_at text not null);
create table if not exists holidays (date text primary key, name text not null);
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
    con = sqlite3.connect(path)
    con.execute("pragma foreign_keys = on")
    con.executescript(SCHEMA)
    # ponytail: 열 추가는 이렇게 한 줄씩. 늘어나면 번호 붙인 마이그레이션으로
    for table, col, typ in (("financials", "basis", "text"), ("stocks", "induty_code", "text"),
                            ("disclosures", "amount", "integer"),
                            ("users", "mail_on", "integer not null default 1"),  # 주간 안내 메일 켜짐(1)/꺼짐(0)
                            ("users", "nickname", "text"), ("users", "bio", "text"),
                            ("users", "photo", "blob"), ("users", "photo_at", "text"),
                            ("stocks", "homepage", "text")):  # 회사 홈페이지 도메인 — 로고(Brandfetch)를 찾는다  # 프로필 사진(256px JPEG) · 바꾼 때(캐시 무효화)  # 남에게 보이는 이름·자기소개 (이메일은 안 보인다)  # fmt: skip
        if col not in {r[1] for r in con.execute(f"pragma table_info({table})")}:
            con.execute(f"alter table {table} add column {col} {typ}")
    con.execute("create unique index if not exists users_nickname on users (nickname collate nocase)")
    return con
