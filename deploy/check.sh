#!/bin/sh
# 올린 뒤 확인 — 내 컴퓨터에서: sh deploy/check.sh   (node 가 있어야 한다)
# 서버가 실제로 만드는 화면 20여 개를 꺼내 상태와 스크립트 문법을 보고, 바깥 주소로도 한 번 열어 본다. 문제가 있으면 실패로 끝난다.
# 왜: 테스트는 화면의 글자만 본다 — 스크립트 하나가 깨진 채 올라가 검색 자동완성·캡처 올리기가 멈춘 적이 있다(2026-10-11).
set -eu
HERE="$(dirname "$0")"
# 접속 정보는 저장소에 두지 않는다 — 환경변수나 내 컴퓨터 .env 의 HANJANG_SSH(계정@서버)·HANJANG_KEY(키 파일)
envval() { if [ -f "$HERE/../.env" ]; then sed -n "s/^$1=//p" "$HERE/../.env" | tail -1; fi; }
HOST="${HANJANG_SSH:-$(envval HANJANG_SSH)}"
KEY="${HANJANG_KEY:-$(envval HANJANG_KEY)}"
URL="${HANJANG_URL:-https://hanjangapp.com}"
[ -n "$HOST" ] && [ -n "$KEY" ] || { echo "HANJANG_SSH(계정@서버)·HANJANG_KEY(키 파일)를 환경변수나 .env 에 넣는다"; exit 1; }

ssh -i "$KEY" -o BatchMode=yes "$HOST" 'cd /srv/hanjang && sudo -u hanjang /srv/hanjang/.venv/bin/python -X utf8 -m hanjang.smoke' | node "$HERE/check.js"

# 화면 서버가 켜질 때까지 기다린다 — 다시 켠 직후 curl 을 하면 502 가 나와 헷갈린다. 20초 안에 안 켜지면 실패(10/12: 시작 코드의 이름 하나가 빠져 켜지지 못한 적이 있다)
ssh -i "$KEY" -o BatchMode=yes "$HOST" 'for i in 1 2 3 4 5 6 7 8 9 10; do systemctl is-active --quiet hanjang-web && exit 0; sleep 2; done; echo "화면 서버가 20초 안에 켜지지 않았다:"; sudo journalctl -u hanjang-web --since "-2 min" --no-pager -o cat | grep -A3 Traceback | tail -8; exit 1'
for p in / /privacy /health; do
	code=$(curl -s -o /dev/null -w "%{http_code}" "$URL$p")
	echo "바깥에서 $p → $code"
	[ "$code" = 200 ] || [ "$p" = /health ] || exit 1
done
ssh -i "$KEY" -o BatchMode=yes "$HOST" 'systemctl is-active hanjang-web >/dev/null && echo "화면 서버 켜짐" || { echo "화면 서버 꺼짐"; exit 1; }; n=$(sudo journalctl -u hanjang-web --since "-5 min" --no-pager -o cat | grep -c "Traceback" || true); echo "최근 5분 오류 기록 ${n}건"; [ "$n" = 0 ]'
