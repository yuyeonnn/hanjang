#!/bin/sh
# docs/deploy.md 1~3 을 한 번에. 다시 돌려도 괜찮다(이미 된 건 건너뛴다).
# 쓰는 법: .env 를 /tmp/hanjang.env 로 올려 두고 → sudo sh setup.sh <도메인>
# 도메인이 없으면 IP 로 된 무료 주소: 34-64-1-2.sslip.io
set -eu
DOMAIN="$1"
REPO=git@github.com:yuyeonnn/hanjang.git
UV=/home/hanjang/.local/bin/uv

# 80·443 을 이미 다른 프로그램(caddy 말고)이 쓰면 멈춘다 — 기존 서비스를 건드리지 않으려고
if ss -ltnp | grep -E ':(80|443)\b' | grep -vq caddy; then
	echo "80/443 을 다른 프로그램이 쓰고 있어요:"; ss -ltnp | grep -E ':(80|443)\b'; exit 1
fi
if ss -ltn | grep -q ':8000\b' && ! systemctl is-active -q hanjang-web; then
	echo "8000 을 다른 프로그램이 쓰고 있어요"; exit 1
fi

command -v git >/dev/null || { apt-get update && apt-get install -y git curl; }
# 메모리 1GB 서버 — 설치·노트 만들 때 모자라지 않게 스왑 1GB
if ! swapon --show | grep -q .; then
	fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
	echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

id hanjang >/dev/null 2>&1 || adduser --disabled-password --gecos "" hanjang
mkdir -p /srv/hanjang && chown hanjang /srv/hanjang
[ -d /srv/hanjang/.git ] || sudo -u hanjang git clone "$REPO" /srv/hanjang
sudo -u hanjang git -C /srv/hanjang pull --ff-only
[ -x "$UV" ] || sudo -u hanjang sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
cd /srv/hanjang && sudo -u hanjang "$UV" sync --frozen

if [ -f /tmp/hanjang.env ]; then
	install -o hanjang -m 600 /tmp/hanjang.env /srv/hanjang/.env && rm /tmp/hanjang.env
fi
sed -i '/^NEWS_DEV=/d' .env  # 기사는 개인용만 — 서버에는 넣지 않는다
sed -i "s|^BASE_URL=.*|BASE_URL=https://$DOMAIN|" .env

cp deploy/hanjang-web.service deploy/hanjang-daily.service deploy/hanjang-daily.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now hanjang-daily.timer
systemctl enable hanjang-web && systemctl restart hanjang-web

command -v caddy >/dev/null || { apt-get update && apt-get install -y caddy; }
mkdir -p /etc/caddy/sites
sed "s/hanjang.example.com/$DOMAIN/" deploy/Caddyfile > /etc/caddy/sites/hanjang.caddy
grep -q 'import sites/\*' /etc/caddy/Caddyfile 2>/dev/null || echo 'import sites/*' >> /etc/caddy/Caddyfile
systemctl reload caddy || systemctl restart caddy

sleep 3
curl -fsS -o /dev/null -w "화면 서버: %{http_code}\n" http://127.0.0.1:8000/
systemctl list-timers hanjang-daily.timer --no-pager
echo "열기: https://$DOMAIN"
