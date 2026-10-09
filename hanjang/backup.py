"""DB 백업 — 하루 한 장, 최근 14장만 (개인정보 처리방침 3항과 같게). `python -m hanjang.backup` · 매일 실행(daily)이 먼저 부른다.
SQLite 의 온라인 백업이라 화면 서버가 켜져 있어도 된다."""

import gzip
import os
import subprocess
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

import httpx

from hanjang import db
from hanjang.sources import env

KEEP = 14
KEY = db.PATH.parent / "gcs-backup.json"  # 서버에만 — 버킷 하나에 「넣기」만 되는 계정 (docs/deploy.md 「서버 밖 백업」)


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


def offsite(path: Path, key: Path = KEY) -> str | None:
    """서버 밖(구글 클라우드 저장소)에 압축해 한 벌 — 서버 디스크가 통째로 망가져도 돌아갈 수 있게.
    계정은 「넣기」만 된다: 서버가 털려도 백업을 지우거나 읽지 못한다. 14일 지난 것은 버킷이 저절로 지운다(처리방침 3항).
    .env 에 BACKUP_BUCKET 이 없으면(내 컴퓨터) 건너뛴다."""
    bucket = env().get("BACKUP_BUCKET")
    if not bucket or not key.exists():
        return None
    token = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True, check=True,
                           env={**os.environ, "CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE": str(key), "CLOUDSDK_CORE_DISABLE_PROMPTS": "1"}).stdout.strip()  # fmt: skip
    name = f"{path.stem}-{datetime.now():%H%M%S}.db.gz"  # 같은 날 두 번 돌아도 덮어쓰지 않는다(덮어쓰기 권한이 없다)
    r = httpx.post(f"https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o",
                   params={"uploadType": "media", "name": name, "ifGenerationMatch": "0"},
                   headers={"Authorization": f"Bearer {token}", "Content-Type": "application/gzip"},
                   content=gzip.compress(path.read_bytes()), timeout=120)  # fmt: skip
    r.raise_for_status()
    return f"gs://{bucket}/{name}"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"백업 {backup(date.today())}")
