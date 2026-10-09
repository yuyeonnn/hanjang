# 배포 — 작은 리눅스 서버 한 대 (PRD §7)

> 우분투 서버 1대 · 사용자 `hanjang` · 코드 `/srv/hanjang`. 화면 서버는 127.0.0.1:8000, 앞에서 **Caddy** 가 https 를 맡는다.
> 매일 07:00(한국 시간) 실행은 systemd 타이머. 설정 파일은 [deploy/](../deploy).

> **지금 서버** (2026-10-08): 구글 클라우드 `education-508407` 프로젝트의 `hanjang` (us-central1-a · e2-micro · Debian 13) · https://34-44-40-196.sslip.io
> 들어가기: `ssh -i ~/.ssh/hanjang-deploy hanjang-deploy@34.44.40.196` · 저장소는 서버의 읽기 전용 키(GitHub deploy key `hanjang-server`)로 받는다.
> 아래 1~3 은 [deploy/setup.sh](../deploy/setup.sh) 가 한 번에 한다: `.env` 를 `/tmp/hanjang.env` 로 올리고 `sudo sh setup.sh <도메인>`.
> 무료 크레딧은 2026-12 중순(67일)에 끝난다 — 그 전에 결제 계정으로 올려야 서버가 멈추지 않는다(e2-micro 미국 1대는 그 뒤에도 무료 범위).

## 1. 처음 한 번

```bash
sudo adduser --disabled-password hanjang
sudo mkdir -p /srv/hanjang && sudo chown hanjang /srv/hanjang
sudo -u hanjang git clone <저장소 주소> /srv/hanjang
sudo -u hanjang sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
cd /srv/hanjang && sudo -u hanjang /home/hanjang/.local/bin/uv sync --frozen
```

`.env` — [.env.example](../.env.example) 을 복사해 값을 채운다.

```bash
sudo -u hanjang cp .env.example .env && sudo -u hanjang chmod 600 .env
sudo -u hanjang nano .env
```

첫 데이터와 노트 (몇 분 · AI 비용 약 $2):

```bash
sudo -u hanjang /home/hanjang/.local/bin/uv run --frozen python -m hanjang.daily
```

## 2. 늘 켜 두기 · 매일 실행

```bash
sudo cp deploy/hanjang-web.service deploy/hanjang-daily.service deploy/hanjang-daily.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hanjang-web hanjang-daily.timer
systemctl list-timers hanjang-daily.timer   # 다음 실행 시각 확인
```

## 3. https (Caddy)

```bash
sudo apt install -y caddy
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile   # 도메인을 실제 것으로 고친다
sudo systemctl reload caddy
```

도메인의 A 레코드가 서버 IP 를 가리키면 Caddy 가 인증서를 저절로 받는다. `.env` 의 `BASE_URL` 을 `https://<도메인>` 으로 — 그래야 로그인 쿠키에 `Secure` 가 붙는다.
방화벽은 80·443 만 연다(8000 은 열지 않는다). 내 도메인으로 옮기는 순서는 [launch.md](launch.md) 「도메인 옮기기」.

## 4. 고칠 때

```bash
cd /srv/hanjang && sudo -u hanjang git pull && sudo -u hanjang /home/hanjang/.local/bin/uv sync --frozen
sudo systemctl restart hanjang-web
```

## 5. 볼 곳

| 무엇 | 명령 |
|---|---|
| 화면 서버 로그 (로그인 링크 요청 등) | `journalctl -u hanjang-web -f` |
| 매일 실행 결과 (노트 몇 장 · 비용) | `journalctl -u hanjang-daily -n 50` |
| AI 비용 (오늘 · 이번 달 · 한 달 예상 · 일감별) | `cd /srv/hanjang && sudo -u hanjang /home/hanjang/.local/bin/uv run python -m hanjang.cost` |
| 시험 판정 숫자 (주차별 재방문 · 돈 내고도 보겠다) | `cd /srv/hanjang && sudo -u hanjang /home/hanjang/.local/bin/uv run python -m hanjang.trial trial-1` |
| 백업 (최근 14일) | `ls /srv/hanjang/data/backup` |
| 백업에서 되돌리기 | `sudo systemctl stop hanjang-web && cp data/backup/hanjang-YYYYMMDD.db data/hanjang.db && sudo systemctl start hanjang-web` |
| 상태 한눈에 | https://34-44-40-196.sslip.io/health — `ok` 면 정상, 아니면 `db` · `daily` · `disk` 중 문제인 것 |

## 감시와 백업 (2026-10-10)

**누가 알려 주나** — 메일이 안 오면 잘 돌고 있는 것.

| 무엇이 잘못되면 | 누가 · 어디로 |
|---|---|
| 사이트가 안 열림 · 매일 실행이 30시간 넘게 안 돎 · DB · 디스크 10% 미만 | 구글 클라우드 모니터링이 5분마다 미국·아시아·유럽에서 `/health` 를 연다 → 두 곳 넘게 5분 이상 실패하면 **psiobinq@gmail.com** (업타임 체크 `hanjang-health`, 알림 정책 「한장 — 사이트 또는 매일 실행 이상」) |
| 매일 실행이 도중에 실패 · 서버 밖 백업 실패 · OpenAI 크레딧 소진 | 서버가 직접 운영자 Gmail(`.env` 의 `SMTP_USER`)로 |

**서버 밖 백업** — 매일 실행이 백업을 만든 뒤 압축해 `gs://hanjang-backup-education-508407/` 에 올린다(같은 날 두 번이면 시각을 붙여 따로).
- 버킷: us-central1 · 공개 차단 · **14일 지나면 저절로 삭제**(처리방침 3항과 같게).
- 서버의 열쇠: `data/gcs-backup.json`(git 밖, 600) — 계정 `hanjang-backup@…` 은 이 버킷에 **넣기만** 된다. 서버가 털려도 백업을 읽거나 지우지 못한다. `.env` 의 `BACKUP_BUCKET` 이 없으면 건너뛴다.
- 되돌리기(서버가 통째로 없어졌을 때) — 내 컴퓨터에서:
  ```bash
  gcloud storage ls gs://hanjang-backup-education-508407/
  gcloud storage cp gs://hanjang-backup-education-508407/hanjang-YYYYMMDD-HHMMSS.db.gz . && gunzip hanjang-YYYYMMDD-HHMMSS.db.gz
  ```
  새 서버를 `deploy/setup.sh` 로 세운 뒤 이 파일을 `/srv/hanjang/data/hanjang.db` 로 올리고 `sudo systemctl restart hanjang-web`. 백업 안의 이메일은 개인정보다 — 다 쓰면 내 컴퓨터의 사본을 지운다.
- 열쇠를 바꿀 때: `gcloud iam service-accounts keys create` → 서버 `data/gcs-backup.json` 교체 → 옛 열쇠 `keys delete`.

**도메인을 옮기면** 감시 주소도 바꾼다 — 업타임 체크의 주소는 고칠 수 없어 새로 만든다: `gcloud monitoring uptime create hanjang-health --resource-type=uptime-url --resource-labels=host=<새 도메인>,project_id=education-508407 --protocol=https --path=/health --period=5 --timeout=10 --matcher-content=ok --matcher-type=contains-string --regions=usa-iowa,asia-pacific,europe` → 알림 정책 조건의 `check_id` 를 새 이름으로 고침 → 옛 체크(`hanjang-health-bDwzkNMaS98`) 지움.

## 6. 내 컴퓨터 (개발)

한장은 **자기 파이썬 환경** `C:\venvs\hanjang` 을 쓴다 — 퀀트점프 환경(`C:\venvs\quantjump`)과 섞이면 한쪽 설치가 다른 쪽 패키지를 바꾼다(2026-10-08 실제로 일어남).
윈도우 사용자 환경 변수 `UV_PROJECT_ENVIRONMENT` 가 퀀트점프를 가리키므로, 한장 명령 앞에는 늘 이것을 붙인다:

```powershell
$env:UV_PROJECT_ENVIRONMENT = "C:\venvs\hanjang"; uv run pytest
```

화면 미리보기(`.claude/launch.json`)는 이 환경의 파이썬을 바로 부른다.
