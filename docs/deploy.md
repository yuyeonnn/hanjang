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
방화벽은 80·443 만 연다(8000 은 열지 않는다).

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
| 시험 판정 숫자 (주차별 재방문 · 돈 내고도 보겠다) | `cd /srv/hanjang && sudo -u hanjang /home/hanjang/.local/bin/uv run python -m hanjang.trial trial-1` |
| 백업 (최근 14일) | `ls /srv/hanjang/data/backup` |
| 백업에서 되돌리기 | `sudo systemctl stop hanjang-web && cp data/backup/hanjang-YYYYMMDD.db data/hanjang.db && sudo systemctl start hanjang-web` |

## 6. 내 컴퓨터 (개발)

한장은 **자기 파이썬 환경** `C:\venvs\hanjang` 을 쓴다 — 퀀트점프 환경(`C:\venvs\quantjump`)과 섞이면 한쪽 설치가 다른 쪽 패키지를 바꾼다(2026-10-08 실제로 일어남).
윈도우 사용자 환경 변수 `UV_PROJECT_ENVIRONMENT` 가 퀀트점프를 가리키므로, 한장 명령 앞에는 늘 이것을 붙인다:

```powershell
$env:UV_PROJECT_ENVIRONMENT = "C:\venvs\hanjang"; uv run pytest
```

화면 미리보기(`.claude/launch.json`)는 이 환경의 파이썬을 바로 부른다.
