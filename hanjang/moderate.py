"""신고 처리 — 운영자가 서버에서 (이용 규칙 /rules: 24시간 안에 확인).
`python -m hanjang.moderate`            처리 안 한 신고 목록
`python -m hanjang.moderate wipe 12`    12번의 닉네임·자기소개·사진을 지운다 (다시 들어오면 닉네임부터 새로 정한다)
`python -m hanjang.moderate ban 12`     프로필을 지우고 계정을 막는다 (다시 로그인해도 못 쓴다) · `unban 12` 로 푼다
`python -m hanjang.moderate ok 12`      문제없음 — 신고만 닫는다"""

import sqlite3
import sys
from datetime import datetime

from hanjang import db


def pending(con: sqlite3.Connection) -> list[tuple]:
    return con.execute("select r.target_id, u.nickname, u.bio, u.photo is not null, group_concat(distinct r.why), count(*), min(r.at)"
                       " from reports r left join users u on u.id = r.target_id where r.done_at is null group by r.target_id order by min(r.at)").fetchall()  # fmt: skip


def act(con: sqlite3.Connection, what: str, uid: int) -> None:
    if what in ("wipe", "ban"):  # 남에게 보이는 것을 모두 지운다 — 닉네임이 없으면 어디에도 나오지 않는다
        con.execute("update users set nickname = null, bio = null, photo = null, photo_at = null, rules_at = null where id = ?", (uid,))
    if what in ("ban", "unban"):
        con.execute("update users set banned = ? where id = ?", (1 if what == "ban" else 0, uid))
    if what != "unban":
        con.execute("update reports set done_at = ? where target_id = ? and done_at is null", (datetime.now().isoformat(), uid))
    con.commit()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    con = db.connect()
    if len(sys.argv) == 3 and sys.argv[1] in ("wipe", "ban", "unban", "ok") and sys.argv[2].isdigit():
        act(con, sys.argv[1], int(sys.argv[2]))
        print(f"{sys.argv[1]} #{sys.argv[2]} 처리했어요")
    else:
        rows = pending(con)
        print(f"처리 안 한 신고 {len(rows)}명" if rows else "처리할 신고가 없어요")
        for uid, nick, bio, photo, why, n, at in rows:
            print(f"#{uid} {nick or '(닉네임 없음)'} · {why} · {n}건 · {at[:16]} · 소개: {bio or '-'} · 사진 {'있음' if photo else '없음'}")
