"""앱처럼 — 매니페스트·서비스 워커·오프라인 화면·홈 화면 추가 안내 (TWA 포장의 재료)."""

import json

from hanjang import tree


# 홈 화면에 추가 · 플레이스토어 포장(TWA) — 앱 정보 한 장과 서비스 워커. 서비스 워커는 화면을 저장해 두지 않는다(노트는 늘 새것):
# 인터넷이 끊겼을 때만 미리 받아 둔 「연결이 끊겼어요」 화면을 보여 준다 (흰 화면·브라우저 오류 대신 — 앱 심사가 보는 것)
MANIFEST = json.dumps({
    "name": "한장 — 한눈에 읽는 장", "short_name": "한장", "lang": "ko", "start_url": "/", "scope": "/", "id": "/",
    "display": "standalone", "background_color": "#fcf8fb", "theme_color": "#154539",
    "description": "공시·재무·소식을 이어서, 내 종목이 지금 어떤 상황인지 쉬운 글로 설명합니다.", "categories": ["finance", "education"],
    "icons": [{"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
              {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
              {"src": "/static/icon-maskable.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}],
}, ensure_ascii=False)  # fmt: skip
SW = ("const C='hanjang-1';self.addEventListener('install',ev=>{ev.waitUntil(caches.open(C).then(c=>c.add('/offline')));self.skipWaiting();});"
      "self.addEventListener('activate',ev=>{ev.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==C).map(k=>caches.delete(k)))));self.clients.claim();});"
      "self.addEventListener('fetch',ev=>{if(ev.request.mode==='navigate')ev.respondWith(fetch(ev.request).catch(()=>caches.match('/offline')));});")
OFFLINE = ('<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
           '<title>연결이 끊겼어요 · 한장</title><style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;'
           'background:#fcf8fb;color:#1b1b1d;font-family:system-ui,sans-serif;word-break:keep-all;text-align:center}main{padding:24px;max-width:360px}'
           'h1{font-size:20px;color:#154539}p{color:#404945;line-height:1.7}button{margin-top:12px;padding:12px 20px;border:0;border-radius:8px;background:#154539;color:#fff;font-size:15px}</style></head>'
           '<body><main>' + tree.line("oops") + '<h1>인터넷 연결이 끊겼어요</h1><p>한장은 매일 새로 쓴 노트를 보여 드려서, 연결이 돌아오면 바로 이어서 볼 수 있어요.</p>'
           '<button onclick="location.reload()">다시 열기</button></main></body></html>')  # fmt: skip
PWA_TAGS = ('<link rel="manifest" href="/manifest.webmanifest"><meta name="theme-color" content="#154539">'
            '<link rel="apple-touch-icon" href="/static/apple-touch-icon.png"><link rel="icon" href="/static/icon-192.png" type="image/png">'
            "<script>if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js');</script>")


# 내 종목이 하나도 없을 때 — 처음 온 사람이 빈 화면만 보던 것 (눌러 보기 10/11)
EMPTY_CARDS = ('<div class="py-10 flex flex-col items-center text-center gap-2 lg:col-span-2">'
               '<span class="material-symbols-outlined text-primary text-[30px]">search</span>'
               '<b class="font-body-reading-strong text-body-reading-strong text-on-surface">가진 종목을 담아 보세요</b>'
               '<p class="font-body-compact text-body-compact text-on-surface-variant">위 칸에 회사 이름을 넣으면 그 회사의 노트가 여기에 쌓여요.<br>'
               '여러 종목은 쉼표로 한 번에 — 예: 삼성전자, SK하이닉스<br>카메라 단추로 증권사 앱의 보유 종목 화면을 올려도 돼요.</p></div>')

# 「홈 화면에 추가」 안내 — 내 종목 화면, 휴대폰에서만. 아이폰은 앱 없이 이것만 둔다(docs/launch.md: 웹을 감싼 앱은 심사에서 잘 떨어진다).
# 아이폰·아이패드 사파리: 설치 단추를 띄울 길이 없어 「공유 → 홈 화면에 추가」를 글로 알린다. 안드로이드 크롬: 브라우저가 설치할 수 있다고 알려 오면(beforeinstallprompt) 단추를 보인다.
# 이미 홈 화면 앱으로 열었거나 한 번 닫은 사람에겐 다시 안 보인다(이 브라우저에만 기억 — 서버에 남기지 않는다).
INSTALL_HINT = (
    '<div class="hidden lg:hidden fixed bottom-16 left-0 right-0 z-40 px-margin pb-safe" id="a2hs"><div class="max-w-[480px] mx-auto flex items-start gap-3 rounded-xl bg-surface-container-lowest border border-outline-variant/50 shadow-sm px-space-md py-3">'
    '<span class="material-symbols-outlined text-primary text-[20px] mt-0.5">install_mobile</span>'
    '<div class="flex-1 min-w-0"><b class="font-label-regular text-label-regular text-on-surface font-semibold">홈 화면에 추가하면 앱처럼 열려요</b>'
    '<p class="font-label-micro text-label-micro text-on-surface-variant leading-normal mt-0.5" id="a2hs-how"></p>'
    '<button class="hidden mt-2 px-3 py-1 bg-primary text-on-primary rounded-lg font-label-micro text-label-micro font-semibold" id="a2hs-go" type="button">설치</button></div>'
    '<button aria-label="안내 닫기" class="shrink-0 text-outline hover:text-on-surface" id="a2hs-x" type="button"><span class="material-symbols-outlined text-[18px]">close</span></button></div></div>'
    "<script>(()=>{const box=document.getElementById('a2hs'),how=document.getElementById('a2hs-how'),go=document.getElementById('a2hs-go');"
    "let seen=false;try{seen=localStorage.getItem('a2hs')==='x'}catch(e){}"
    "if(seen||matchMedia('(display-mode: standalone)').matches||navigator.standalone)return;"
    "const show=()=>box.classList.remove('hidden');"
    "document.getElementById('a2hs-x').onclick=()=>{box.classList.add('hidden');try{localStorage.setItem('a2hs','x')}catch(e){}};"
    "const ua=navigator.userAgent,ios=/iphone|ipad|ipod/i.test(ua)||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1);"
    "if(ios){how.textContent=/crios|fxios|edgios|kakaotalk|naver|instagram|fban|fbav/i.test(ua)?'사파리로 연 다음, 아래 공유 단추(네모에서 화살표가 나오는 모양) → 「홈 화면에 추가」를 눌러 주세요.':'아래 공유 단추(네모에서 화살표가 나오는 모양) → 「홈 화면에 추가」를 눌러 주세요.';show();return;}"
    "addEventListener('beforeinstallprompt',ev=>{ev.preventDefault();how.textContent='주소창 없이 바로 열리고, 홈 화면에 아이콘이 생겨요.';go.classList.remove('hidden');"
    "go.onclick=async()=>{ev.prompt();await ev.userChoice;box.classList.add('hidden');};show();});"
    "addEventListener('appinstalled',()=>box.classList.add('hidden'));})();</script>")
