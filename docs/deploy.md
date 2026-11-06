# 배포 — 작은 리눅스 서버 한 대 (PRD §7)

> 우분투 서버 1대 · 사용자 `hanjang` · 코드 `/srv/hanjang`. 화면 서버는 127.0.0.1:8000, 앞에서 **Caddy** 가 https 를 맡는다.
> 매일 07:00(한국 시간) 실행은 systemd 타이머. 설정 파일은 [deploy/](../deploy).

> **지금 서버** (2026-10-08): 구글 클라우드 `education-508407` 프로젝트의 `hanjang` (us-central1-a · e2-micro · Debian 13) · https://hanjangapp.com (2026-10-12 부터 · 옛 주소 34-44-40-196.sslip.io 는 새 주소로 넘어간다)
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

**올린 뒤에는 꼭** 내 컴퓨터에서 (node 필요):

```bash
sh deploy/check.sh
```

서버가 실제로 만드는 화면 20여 개(로그인·내 종목·노트·피드·캘린더·설정 …)를 꺼내 **상태와 화면 속 스크립트 문법**을 보고, 바깥 주소로도 열어 본다. 문제가 있으면 `✗` 와 함께 실패로 끝난다.
테스트(`pytest`)는 화면의 글자만 본다 — 2026-10-11 에 스크립트 하나가 깨진 채 올라가 내 종목 화면의 검색 자동완성·캡처 올리기가 멈춰 있었다. 「사이트가 200 으로 열린다」는 확인이 아니다.
진짜 DB 에는 아무것도 쓰지 않는다(`hanjang/smoke.py` — 메모리 사본에서 그린다). 누르는 동작(담기·좋아요·차단 …)까지 보려면 브라우저로 직접 눌러 본다.

## 5. 볼 곳

| 무엇 | 명령 |
|---|---|
| 화면 서버 로그 (로그인 링크 요청 등) | `journalctl -u hanjang-web -f` |
| 매일 실행 결과 (노트 몇 장 · 비용) | `journalctl -u hanjang-daily -n 50` |
| AI 비용 (오늘 · 이번 달 · 한 달 예상 · 일감별) | `cd /srv/hanjang && sudo -u hanjang /home/hanjang/.local/bin/uv run python -m hanjang.cost` |
| 시험 판정 숫자 (주차별 재방문 · 돈 내고도 보겠다) | `cd /srv/hanjang && sudo -u hanjang /home/hanjang/.local/bin/uv run python -m hanjang.trial trial-1` |
| 백업 (최근 14일) | `ls /srv/hanjang/data/backup` |
| 백업에서 되돌리기 | `sudo systemctl stop hanjang-web && cp data/backup/hanjang-YYYYMMDD.db data/hanjang.db && sudo systemctl start hanjang-web` |
| 상태 한눈에 | https://hanjangapp.com/health — `ok` 면 정상, 아니면 `db` · `daily` · `disk` 중 문제인 것 |

## 주소 (2026-10-12)

**https://hanjangapp.com** — Cloudflare 에서 등록(1년, 자동 연장 · 사용자 계정). DNS 는 Cloudflare, A 레코드 `@`·`www` → `34.44.40.196`, **Proxy 꺼짐(DNS only)** — 켜면 Caddy 가 인증서를 못 받는다.
서버 `/etc/caddy/sites/hanjang.caddy`: `hanjangapp.com` 가 화면 서버로, `www.hanjangapp.com` 와 옛 주소 `34-44-40-196.sslip.io` 는 새 주소로 넘긴다(301, 경로 그대로). 옛 설정은 `/etc/caddy/hanjang.caddy.bak-20261012`.
메일 속 링크는 `.env` 의 `BASE_URL=https://hanjangapp.com`. 로그인 쿠키는 주소마다 따로라, 옛 주소로 로그인해 있던 사람은 새 주소에서 한 번 다시 로그인한다.
서버 IP 가 바뀌면 Cloudflare 의 A 레코드 두 줄만 고치면 된다(주소는 그대로).

## 감시와 백업 (2026-10-10)

**누가 알려 주나** — 메일이 안 오면 잘 돌고 있는 것.

| 무엇이 잘못되면 | 누가 · 어디로 |
|---|---|
| 사이트가 안 열림 · 매일 실행이 30시간 넘게 안 돎 · DB · 디스크 10% 미만 | 구글 클라우드 모니터링이 5분마다 미국·아시아·유럽에서 `/health` 를 연다 → 두 곳 넘게 5분 이상 실패하면 **psiobinq@gmail.com** (업타임 체크 `hanjang-health`, 알림 정책 「한장 — 사이트 또는 매일 실행 이상」) |
| 매일 실행이 도중에 실패 · 서버 밖 백업 실패 · OpenAI 크레딧 소진 | 서버가 직접 운영자 Gmail(`.env` 의 `SMTP_USER`)로 |
| DART 점검(주말에 잦다) | 멈추지 않는다 — DART 가 필요한 일(국내 받기·사업보고서 읽기·ETF·큰손)만 건너뛰고 나머지는 돈다. 운영자 Gmail 로 하루 한 번 알리고, **13시·19시에 다시 해 본다**(아침에 끝까지 돌았으면 바로 끝남). 어디까지 됐는지는 `data/daily.json` |

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

### 연속 백업 (Litestream, 2026-10-12)

하루 한 번 백업만으로는 마지막 하루치(담기·좋아요·팔로우)를 잃을 수 있어, **Litestream** 이 DB 의 WAL 을 1초마다 서버 밖으로 복사한다.

- 서버: `/etc/litestream.yml`(DB 경로·저장소), `/etc/systemd/system/litestream.service.d/hanjang.conf`(hanjang 사용자로 · 열쇠 `data/gcs-backup.json`). `systemctl status litestream`.
- 저장소: `gs://hanjang-litestream-education-508407/hanjang.db/` — 하루 백업 버킷과 **따로**(이 열쇠는 여기서만 지울 수 있다). 72시간 보관.
- **복구** (서버에서, 화면 서버를 먼저 끈다):

```bash
sudo systemctl stop hanjang-web litestream
sudo -u hanjang mv /srv/hanjang/data/hanjang.db /srv/hanjang/data/hanjang.db.bad
sudo -u hanjang env GOOGLE_APPLICATION_CREDENTIALS=/srv/hanjang/data/gcs-backup.json litestream restore -o /srv/hanjang/data/hanjang.db gs://hanjang-litestream-education-508407/hanjang.db
sudo systemctl start litestream hanjang-web
```

- 10/12 에 `/tmp` 로 복구해 `pragma integrity_check` ok 를 확인했다. 특정 시각으로 돌아가려면 `-timestamp 2026-10-12T00:00:00Z` 를 더한다.

## 데이터가 쌓이는 속도와 지우는 주기 (2026-10-11 점검 — DB 6.5MB · 사용자 11명)

| 무엇 | 지금 | 늘어나는 속도 | 지우는 때 |
|---|---|---|---|
| 열어본 기록 `views` | 911줄 | 사람마다 하루 10줄쯤 — 1,000명이면 하루 1만 줄(약 0.6MB) | **180일 지나면** 매일 실행이 지움 |
| 노트 `notes` | 103장 · 1.2MB | 한 주에 종목 수만큼(100종목 = 약 0.75MB, 한 해 약 40MB) | 안 지움 — 지난 노트는 리그램·좋아요가 가리킨다. 500MB 를 넘으면 다시 본다 |
| 뉴스룸 소식 `news` | 46줄 | 하루 몇 줄 | **60일 지나면** 지움 (노트는 최근 10일 것만 쓴다) |
| 공시 `disclosures` | 1,618줄 | 석 달에 1,600줄(한 해 약 1.2MB) | 안 지움 |
| 유명 투자자 보유 `guru_holdings` | 11,830줄 · 1.7MB | 분기마다 새 신고만큼 | 안 지움 |
| 형광펜 `highlights` | 3줄 | 한 화면에 칠할 수 있는 개수·글자 수에 한도(`HL_PER_PAGE`·`HL_MAX`) | 사용자가 지우거나 탈퇴할 때 |
| 리그램·저장·좋아요·팔로우·차단 | 수십 줄 | 글 하나에 사람마다 한 줄 — 글 수 × 사람 수가 천장 | 탈퇴할 때 |
| 백업 `data/backup` · 버킷 | DB 크기 × 14 | DB 와 함께 | **14일** (처리방침 3항) |
| 로그인·코드·캡처 요청 기록 | 서버 메모리 | 주소·IP 마다 한 칸 | 한 시간 지난 것은 2,000칸이 넘으면 비움 · 서버를 다시 켜면 전부 |
| AI 비용 기록 `llm_cost.csv` | 64KB | 하루 약 16KB(한 해 6MB) | 안 지움 |
| 서버 기록(journald) | 80MB | — | systemd 기본 한도(디스크의 10%)에서 저절로 돌려 씀 |

- 디스크 10GB 중 4.0GB 사용(대부분 운영체제·파이썬 환경). 이 속도면 DB 가 디스크를 채우는 일은 수천 명·몇 해 뒤다 — `/health` 가 남은 디스크 10% 미만이면 알린다.
- 화면이 자주 묻는 조회에는 색인이 있다(`db.connect` 끝) — 요청을 한 번에 하나씩 처리하니, 표 전체를 훑는 조회 하나가 모두의 기다림이 된다.
- **빠르게 하려고 둔 것 (10/11 실측)**: ① `synchronous=normal` — 서버 디스크에서 커밋 한 번 2.4ms → 0.04ms(화면마다 열어본 기록을 쓰니, 요청을 하나씩 처리하는 구조에선 모두의 기다림이었다). ② 매일 실행 뒤에만 바뀌는 큰 조각은 메모리에 한 번 만들어 둔다(`App.cached`: 종목 목록 186KB 9.7→0.2ms · 국민연금 45→0.7ms · 유명 투자자 6.5→0.6ms · 읽기 팁 5.5→0.7ms). 다른 연결(매일 실행)이 쓰면 `pragma data_version` 이 바뀌어 저절로 새로 만든다 — 사람이 하는 일(좋아요·팔로우)은 캐시와 무관. ③ 화면이 자주 묻는 조회에 색인. 나머지 화면은 1~6ms 라 캐시를 두지 않았다(오래된 화면을 보여줄 위험만 는다).
- 캐시가 걱정되는 때: 서버에서 DB 를 손으로 고치면(sqlite3 로) 그것도 「다른 연결」이라 바로 반영된다. 서버 메모리는 캐시 전부 합쳐 1MB 미만.
- 형광펜은 캐시가 아니라 DB 에 있다(화면을 열 때 `/hl?p=` 로 불러온다). 노트가 새로 쓰여 칠한 글귀가 사라지면 그 줄은 화면에 안 보인 채 남는다 — 작아서 그대로 둔다.

## 메모리 (2026-10-11 점검 — 서버 964MB · 스왑 1GB)

| 누가 | 얼마 | 비고 |
|---|---|---|
| 화면 서버 | 평소 40MB · 최대 70MB | 한도 300MB(`MemoryMax`) — 넘으면 다시 켜진다. 운영체제가 먼저 죽이지 않게 점수를 낮춤 |
| 매일 실행 | 가장 큰 단계(미국 받기)만큼 — 고치기 전 250~354MB | 400MB 에서 누르고 600MB 에서 멈춘다. 메모리가 모자라면 화면 서버 대신 이쪽이 죽는다 |
| 구글 모니터링 에이전트(ops agent) | 약 120MB | 서버 CPU·메모리 그래프용. `/health` 감시와는 무관 — 지우면 그만큼 남는다 |
| Caddy · journald · 그 밖 | 약 200MB | |

- **고친 것**: ① `uv run` 대신 파이썬을 바로 부른다(uv 가 옆에서 36MB) ② 매일 실행의 국내 받기·미국 받기는 따로 띄운 파이썬에서(`daily.apart`) — 끝나면 메모리가 돌아온다. 한 프로세스에서 다 돌리면 쌓였다 ③ 미국 받기는 다음 회사를 읽기 전에 앞 회사 자료를 놓는다 ④ DART 회사 목록(30MB)은 바이트 그대로 한 덩이씩 ⑤ 큰 본문(6MB)은 로그인한 사람의 사진 두 곳만, 동시에 3건까지 — 전에는 누구든 어느 주소로든 보낼 수 있었다.
- 화면 서버가 메모리에 두는 것: DB 캐시 16MB 까지 · `App.cached` 1MB 미만 · 로그인 요청 기록(2,000칸이 넘으면 비움). 접속마다 스레드 하나(끝나면 사라진다).
- 볼 곳: `systemctl show hanjang-web -p MemoryCurrent -p MemoryPeak` · 매일 실행은 `journalctl -u hanjang-daily | grep "memory peak"` · 전체 `free -m` · 메모리 부족으로 죽은 적 `journalctl -k | grep -i oom`.

## 6. 내 컴퓨터 (개발)

한장은 **자기 파이썬 환경** `C:\venvs\hanjang` 을 쓴다 — 퀀트점프 환경(`C:\venvs\quantjump`)과 섞이면 한쪽 설치가 다른 쪽 패키지를 바꾼다(2026-10-08 실제로 일어남).
윈도우 사용자 환경 변수 `UV_PROJECT_ENVIRONMENT` 가 퀀트점프를 가리키므로, 한장 명령 앞에는 늘 이것을 붙인다:

```powershell
$env:UV_PROJECT_ENVIRONMENT = "C:\venvs\hanjang"; uv run pytest
```

화면 미리보기 설정은 이 환경의 파이썬을 바로 부른다.
