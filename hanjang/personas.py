"""예시 사람들 — 처음 사람이 적을 때 피드·추천·순위가 비어 보이지 않게 (사용자 10/10: 실제 사용자에게도 다 보이게).

「예시 계정」 표시는 붙이지 않는다(사용자 10/10). 실제 사용자를 먼저 팔로우하지는 않는다.
20명 시험을 셀 때는 이메일이 DOMAIN 으로 끝나는 계정을 빼고 센다.
.env DEMO=1 일 때 매일 실행이 다시 깔아 활동 시각을 「최근」으로 유지한다. 손으로: python -m hanjang.personas
"""

import random
import sys
from datetime import datetime, timedelta

from hanjang import db, learn, notes, sources

DOMAIN = "@persona.hanjang.local"
DEMO_EMAIL = "demo@hanjang.local"

# 열쇠, 닉네임, 자기소개, 담은 종목, 리그램할 읽기 팁 — 자기소개는 금지어 검사를 통과해야 한다(사라·추천·목표가…)
PEOPLE = [
    ("chip", "minsu_k", "반도체 회사 다녀요. 메모리 실적 나오는 날만 챙겨봄", ["005930", "000660", "042700", "402340"], ["statements", "ratios"]),
    ("bear", "soyeon92", "배당 주는 회사 위주로 조금씩 모으는 중", ["105560", "055550", "033780", "017670", "086790"], ["dividend", "book-bogle"]),
    ("ship", "퇴근길2호선", "출근길에 조선 방산 수주 공시 읽어요", ["010140", "009540", "042660", "012450", "005380"], ["sector-debt", "disclosure"]),
    ("first", "지수의첫월급", "작년에 첫 월급 받고 시작했어요. 아직 배우는 중", ["005930", "035420", "005380", "105560"], ["start", "stock-bond", "fund-etf"]),
    ("bio", "하늘다람쥐", "제약 바이오 공시 공부 중입니다", ["207940", "068270", "128940", "326030"], ["sector-margin"]),
    ("car", "jaehyun_drive", "차 좋아해서 현대차 기아 공시까지 보게 됨", ["005380", "000270", "012330", "161390"], ["fx"]),
    ("turtle", "거북이걸음", "오래 들고 가는 편. 실적 발표 날만 봐요", ["005930", "105560", "005380", "035720", "000660"], ["book-buffett", "book-graham", "diversify"]),
    ("night", "달밤산책", "자기 전에 재무제표 한 장", ["000660", "055550", "035420", "207940"], ["statements", "book-marks"]),
]
DEMO_FOLLOWS = ["chip", "bear", "ship", "first", "turtle"]  # 둘러보기 계정이 팔로우하는 사람 — 피드에 리그램이 흐른다
FOLLOWS_DEMO = ["first", "car", "night"]


def seed(con, now: datetime | None = None) -> int:
    """예시 사람들을 (다시) 깐다 — 활동은 지우고 지금 기준 최근 2주 안에 새로. 깐 사람 수."""
    now = now or datetime.now()
    week = con.execute("select max(week) from notes").fetchone()[0]
    noted = {t for (t,) in con.execute("select ticker from notes where week = ?", (week,))}
    con.execute("insert or ignore into users (email, created_at, nickname, mail_on) values (?, ?, '둘러보기', 0)", (DEMO_EMAIL, now.isoformat()))
    demo = con.execute("select id from users where email = ?", (DEMO_EMAIL,)).fetchone()[0]
    ids = {}
    for key, nick, bio, _, _ in PEOPLE:
        assert not notes.FORBIDDEN.search(bio), bio
        con.execute("insert or ignore into users (email, created_at, mail_on) values (?, ?, 0)", (key + DOMAIN, (now - timedelta(days=30)).isoformat()))
        ids[key] = con.execute("select id from users where email = ?", (key + DOMAIN,)).fetchone()[0]
        con.execute("update users set nickname = ?, bio = ? where id = ?", (nick, bio, ids[key]))
    mine = tuple(ids.values())
    marks = ",".join("?" * len(mine))
    for table, col in (("regrams", "user_id"), ("likes", "user_id"), ("views", "user_id"), ("holdings", "user_id")):
        con.execute(f"delete from {table} where {col} in ({marks})", mine)
    con.execute(f"delete from follows where follower_id in ({marks}) or followee_id in ({marks})", mine + mine)
    con.execute("delete from regrams where user_id = ?", (demo,))

    def ago(rng, lo, hi):  # lo~hi 시간 전
        return (now - timedelta(hours=rng.uniform(lo, hi))).isoformat()

    for key, _, _, tickers, slugs in PEOPLE:
        rng, u = random.Random(key + now.date().isoformat()), ids[key]  # 날마다 다르게 — 순위가 하루 전과 달라져 오르내림이 생긴다
        held = [t for t in tickers if t in noted]
        for t in held:
            con.execute("insert or ignore into holdings values (?, ?, ?)", (u, t, ago(rng, 2, 190)))  # 이번 주 한장 — 하루 안에 생긴 것(▲)도, 7일이 지나 빠지는 것(▼)도 있게
            for _ in range(rng.randint(1, 3)):
                con.execute("insert into views (user_id, page, ticker, at) values (?, 'note', ?, ?)", (u, t, ago(rng, 1, 190)))
            if rng.random() < 0.6:
                con.execute("insert or ignore into likes values (?, ?, ?, ?)", (u, t, week, ago(rng, 1, 240)))
        for t in rng.sample(held, min(2, len(held))):
            con.execute("insert or ignore into regrams (user_id, kind, ref, week, at) values (?, 'note', ?, ?, ?)", (u, t, week, ago(rng, 1, 300)))
        for s in slugs:
            if s in learn.BY_SLUG:
                con.execute("insert or ignore into regrams (user_id, kind, ref, week, at) values (?, 'learn', ?, '', ?)", (u, s, ago(rng, 3, 300)))
        art = con.execute(f"select id from articles where ticker in ({','.join('?' * len(held))}) order by date desc limit 1", held).fetchone() if held else None
        if art:
            con.execute("insert or ignore into regrams (user_id, kind, ref, week, at) values (?, 'article', ?, '', ?)", (u, str(art[0]), ago(rng, 1, 100)))
        for other in rng.sample([k for k in ids if k != key], 3):
            con.execute("insert or ignore into follows (follower_id, followee_id, at) values (?, ?, ?)", (u, ids[other], ago(rng, 50, 600)))
    rng = random.Random("demo")
    for key in DEMO_FOLLOWS:
        con.execute("insert or ignore into follows (follower_id, followee_id, at) values (?, ?, ?)", (demo, ids[key], ago(rng, 100, 600)))
    for key in FOLLOWS_DEMO:
        con.execute("insert or ignore into follows (follower_id, followee_id, at) values (?, ?, ?)", (ids[key], demo, ago(rng, 2, 120)))
    con.commit()
    return len(ids)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sources.env().get("DEMO") != "1":
        sys.exit("DEMO=1 일 때만 깐다 (.env)")
    print(f"예시 사람 {seed(db.connect())}명")
