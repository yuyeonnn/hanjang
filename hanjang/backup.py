"""DB 백업 — 하루 한 장, 최근 14장만 (개인정보 처리방침 3항과 같게). `python -m hanjang.backup` · 매일 실행(daily)이 먼저 부른다.
SQLite 의 온라인 백업이라 화면 서버가 켜져 있어도 된다."""

import sqlite3
import sys
from datetime import date
from pathlib import Path

from hanjang import db

KEEP = 14


def backup(today: date, src: Path = db.PATH, dst: Path | None = None) -> Path:
    dst = dst or src.parent / "backup"
    dst.mkdir(parents=True, exist_ok=True)
    out = dst / f"hanjang-{today:%Y%m%d}.db"
    a, b = sqlite3.connect(src), sqlite3.connect(out)
    try:
        a.backup(b)
    finally:  # sqlite3 의 with 는 닫지 않는다 — 열린 채면 윈도우에서 옛 백업을 못 지운다
        a.close()
        b.close()
    for old in sorted(dst.glob("hanjang-*.db"))[:-KEEP]:  # 이름이 날짜순이라 정렬 = 시간순
        old.unlink()
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"백업 {backup(date.today())}")
