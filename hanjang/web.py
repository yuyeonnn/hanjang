"""모바일 웹 (PRD §3·§6) — 표준 라이브러리 WSGI 하나. 사용자 20명이라 프레임워크가 필요 없다.
`uv run python -m hanjang.web` → http://localhost:8000
화면: 로그인 → ② 내 종목 카드 → ③ 기업 노트 · ④ 캘린더. 열 때마다 `views` 한 행 (시험 판정의 원천).
**화면 모양은 Stitch 시안(2026-10-07 둘째 판, docs/design.md)을 그대로 옮겼다** — 클래스·배치·문구를 바꾸지 않는다.
시안의 예시 내용 자리는 전부 실제 데이터로 채운다(사진·그림은 쓸 권리가 없어 회색 빈 칸)."""

import calendar
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import shutil
import sqlite3
import sys
import threading
import traceback
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, quote

from hanjang import db, gurus, holders, learn, llm, mail, morning, notes, personas, policy, sources, tree


def FIRST(ticker: str) -> bool:  # 새 종목 바로 받기 — 테스트에서 바꿔 끼운다
    if not ticker[:1].isdigit() and not ticker.startswith("ETF"):  # 미국 티커(영문) — SEC 에서
        from hanjang import us
        return us.first(ticker)
    from hanjang import collect

    return collect.first(ticker)
from hanjang.sources import env, industry_label

MAX_STOCKS = 20  # PRD F2
COHORT = re.compile(r"[a-z0-9-]{1,20}")  # 시험 묶음 이름 — 초대 링크 /?c=trial-1 (python -m hanjang.trial 이 센다)
NICK = re.compile(r"[가-힣A-Za-z0-9_]{2,20}")  # 남에게 보이는 이름 — 이메일은 절대 보이지 않는다
BIO_MAX = 150
CODE_TRIES = 5  # 로그인 코드를 틀릴 수 있는 횟수 — 넘으면 그 코드는 버린다
REPORT_WHY = ("욕설·혐오·성적인 표현", "사칭·남의 사진", "종목 추천·리딩방·광고", "기타")
# 닉네임·자기소개에 쓸 수 없는 말 (이용 규칙 /rules) — 욕설 · 리딩방·광고 유도 · 연락처와 바깥 링크. 다 막지는 못한다: 빠져나간 것은 신고 → 운영자가 지운다
BAD = re.compile(r"씨발|시발|ㅅㅂ|ㅆㅂ|병신|ㅂㅅ|좆|존나|개새|새끼|fuck|shit|bitch|섹스|야동"
                 r"|리딩|수익 ?보장|원금 ?보장|무료 ?추천|종목 ?추천|단톡|오픈 ?채팅|open\.kakao|카톡|텔레그램|t\.me|https?://|www\.|\d{2,3}[- .]\d{3,4}[- .]\d{4}", re.I)
BODY_MAX = 6_000_000  # 요청 본문 상한 — 캡처 사진(브라우저에서 줄여 보낸다)도 이 안에
FORM_MAX = 64_000  # 사진이 아닌 요청(폼) 본문 상한. 큰 본문은 로그인한 사람의 사진 두 곳(BIG_POSTS)만 받는다
BIG_POSTS = ("/scan", "/me/photo")
BIG_AT_ONCE = 3  # 큰 본문을 동시에 받는 수 — 한 건이 메모리에서 본문의 서너 배(6MB → 20MB 남짓)를 쓴다. 1GB 서버를 채우지 못하게 (메모리 점검 10/11)
PHOTO_MAX = 300_000  # 프로필 사진 — 브라우저가 256px JPEG 로 줄여 보낸다. 이보다 크면 받지 않는다
SCAN_HOURLY = 10
DEMO_EMAIL = "demo@hanjang.local"  # 둘러보기 계정 — .env DEMO=1 일 때만. 보기만 된다
DEMO_STOCKS = ("005930", "000660", "105560", "010140")  # 한 사람이 한 시간에 캡처를 읽힐 수 있는 횟수 (AI 비용)
LINK_TTL = 15 * 60  # 로그인 링크 15분
LOGIN_GAP, LOGIN_HOURLY = 60, 5  # 같은 주소로 링크는 1분에 한 번, 한 시간에 다섯 번까지 (메일 폭탄·발송 계정 정지 막기)
# 주소를 바꿔 가며 요청하면 위 제한을 피해 남의 메일함에 뿌리고 Gmail 하루 한도(약 500통)를 다 쓸 수 있다 — 한 곳(IP)·전체에도 한도 (보안 점검 10/11)
LOGIN_IP_HOURLY, LOGIN_ALL_HOURLY = 10, 60
# 이 사이트의 스크립트·글꼴·그림만 — 남의 스크립트가 끼어들거나 폼이 밖으로 나가지 못하게. 화면에 인라인 스크립트가 많아 'unsafe-inline' 은 둔다
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data: blob: https://cdn.brandfetch.io; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'")
e = html.escape


# --- 서명: 로그인 링크와 쿠키 (세션 표 없이 — ERD 「안 만든 것」) ---


def sign(value: str, secret: str) -> str:
    return value + "." + hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()[:32]


def unsign(token: str, secret: str) -> str | None:
    value, _, _ = token.rpartition(".")
    return value if value and hmac.compare_digest(sign(value, secret), token) else None


SESSION_TTL = 90 * 86400  # 로그인 쿠키는 발급 뒤 90일 — 서버가 센다(브라우저의 Max-Age 는 정직한 브라우저만 지킨다)
# 날짜 없는 옛 쿠키(「사용자 번호」만 서명)는 이날까지만 받고, 그 사이 들어오면 날짜가 든 새 쿠키로 바꿔 준다 — 아무도 갑자기 로그아웃되지 않게.
# 이날이 지나면 옛 쿠키는 통하지 않는다(새 나간 쿠키가 영영 쓰이던 구멍, 보안 점검 10/11). ponytail: 2026-11-15 뒤엔 이 줄과 legacy 갈래를 지운다
LEGACY_UNTIL = datetime(2026, 11, 15).timestamp()


def session_cookie(uid: int, secret: str, now: float, age: int = SESSION_TTL) -> str:
    ck = f"s={sign(f'{uid}|{int(now)}', secret)}; Path=/; HttpOnly; SameSite=Lax; Max-Age={age}"
    return ck + ("; Secure" if mail.base_url().startswith("https://") else "")


def read_session(token: str, secret: str, now: float) -> tuple[int | None, bool]:
    """쿠키 → (사용자 번호, 옛 쿠키라 새로 구워 줘야 하나). 서명이 틀리거나 90일이 지났으면 (None, False)."""
    v = unsign(token, secret)
    if not v:
        return None, False
    uid, _, at = v.partition("|")
    if not uid.isdigit():
        return None, False
    if at:
        return (int(uid), False) if at.isdigit() and now - int(at) <= SESSION_TTL else (None, False)
    return (int(uid), True) if now < LEGACY_UNTIL else (None, False)


def login_token(email: str, secret: str, now: float) -> str:
    return sign(f"{email}|{int(now) + LINK_TTL}", secret)


def check_login(token: str, secret: str, now: float) -> str | None:
    """링크 → 이메일. 서명이 틀리거나 15분이 지났으면 None."""
    v = unsign(token, secret)
    if not v or "|" not in v:
        return None
    email, _, exp = v.rpartition("|")
    return email if exp.isdigit() and now <= int(exp) else None


# --- 시안 공통 머리 (Stitch 시안의 <head> 그대로) ---

HEAD = """<meta charset="utf-8"><meta content="width=device-width, initial-scale=1.0, viewport-fit=cover" name="viewport"><link href="https://fonts.googleapis.com" rel="preconnect"><link crossorigin="" href="https://fonts.gstatic.com" rel="preconnect"><link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&amp;family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,600;1,6..72,400&amp;display=swap" rel="preload" as="style" onload="this.onload=null;this.rel='stylesheet'"><noscript><link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&amp;family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,600;1,6..72,400&amp;display=swap" rel="stylesheet"></noscript>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@400,0..1&amp;display=block" rel="stylesheet"><style>@layer base{html,body{width:100vw;margin:0;padding:0;}body{overscroll-behavior:none;}.pb-safe{padding-bottom:env(safe-area-inset-bottom,0px);}.pt-safe{padding-top:env(safe-area-inset-top,0px);}main>:first-child{margin-top:0!important;}main>:last-child{margin-bottom:0!important;}}::-webkit-scrollbar{display:none;}body{word-break:keep-all;overflow-wrap:anywhere;}p,h1,h2,h3,li,span{text-wrap:pretty;}</style>"""


# 카카오톡·문자로 링크를 보낼 때 뜨는 미리보기 카드 — 어느 쪽을 보내도 같은 소개 (로그인 같은 화면 이름은 빼고)
SHARE_TITLE = "한장 — 내 주식, 쉬운 글 한 장"
SHARE_DESC = "공시·재무·소식을 이어서, 내 종목이 지금 어떤 상황인지 쉬운 글로 설명합니다."


def share_tags() -> str:
    img = f"{mail.base_url()}/static/og.png"
    return (f'<meta property="og:type" content="website"><meta property="og:site_name" content="한장">'
            f'<meta property="og:title" content="{SHARE_TITLE}"><meta property="og:description" content="{SHARE_DESC}">'
            f'<meta name="description" content="{SHARE_DESC}"><meta property="og:image" content="{img}">'
            f'<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">'
            f'<meta name="twitter:card" content="summary_large_image">')  # fmt: skip


# 좋아요·리그램은 화면을 다시 불러오지 않는다 — 누르면 맨 위로 튀어 올라가던 것 (사용자 10/9).
# 보내고 나서 같은 화면을 받아 이 두 단추 묶음만 바꿔 끼운다(숫자·눌림 상태가 서버 기준 그대로). 자바스크립트가 없으면 예전처럼 새로 불러온다
STAY = ("<script>document.addEventListener('submit',async ev=>{const f=ev.target;const a=f.getAttribute('action');"
        "if(a!=='/like'&&a!=='/regram'&&a!=='/follow'&&a!=='/save')return;ev.preventDefault();const sel='form[action=\"/like\"],form[action=\"/regram\"],form[action=\"/follow\"],form[action=\"/save\"]';"
        "try{await fetch(a,{method:'POST',body:new URLSearchParams(new FormData(f,ev.submitter))});"
        "const doc=new DOMParser().parseFromString(await (await fetch(location.href)).text(),'text/html');"
        "const old=[...document.querySelectorAll(sel)],neu=[...doc.querySelectorAll(sel)];"
        "if(old.length===neu.length)old.forEach((x,i)=>x.replaceWith(document.importNode(neu[i],true)));else location.reload();}"
        "catch(err){f.submit();}});</script>")


# 형광펜 — 노트·소식·읽기 팁 글을 끌어서 고르면 색 네 가지와 「복사」가 뜬다. 칠한 곳은 서버에 남아 다시 열어도 보인다 (사용자 10/10).
# 자리는 글자 위치(s~e)와 그 글귀로 기억한다 — 글이 조금 바뀌어 위치가 어긋나면 같은 글귀를 찾아 칠하고, 없으면 건너뛴다.
# 칠한 곳을 누르면 「지우기」(누를 때 고른 글이 풀리며 띠가 바로 사라지던 것을 막는다 — 다른 곳을 누르면 닫힌다). 단추·아이콘 글자는 세지 않는다(좋아요 숫자가 바뀌어도 위치가 안 밀리게)
HL = r"""<script>(()=>{const P=location.pathname;if(!/^\/(n|a|learn)\/./.test(P))return;const root=document.querySelector('main');if(!root)return;
const C={y:'#FFF3A3',g:'#C9F2D0',p:'#FFD3E0',b:'#CFE6FF'};let bar=null,timer=0;
const nodes=()=>{const w=document.createTreeWalker(root,NodeFilter.SHOW_TEXT,{acceptNode:n=>n.parentElement.closest('script,style,form,button,nav,figure,svg,.material-symbols-outlined,#hlbar')?NodeFilter.FILTER_REJECT:NodeFilter.FILTER_ACCEPT});const a=[];let n;while(n=w.nextNode())a.push(n);return a;};
const text=()=>nodes().map(n=>n.data).join('');
const off=(node,o)=>{const r=document.createRange();r.setStart(root,0);r.setEnd(node,o);let pos=0;for(const n of nodes()){if(n===node)return pos+o;if(r.comparePoint(n,n.data.length)<=0)pos+=n.data.length;else break;}return pos;};
const paint=(s,e,c,id)=>{let pos=0;for(const n of nodes()){const len=n.data.length,a=Math.max(s,pos),b=Math.min(e,pos+len);if(a<b){let t=n;if(a>pos)t=t.splitText(a-pos);if(b-a<t.data.length)t.splitText(b-a);
const m=document.createElement('mark');m.dataset.hl=id;m.style.cssText='background:'+(C[c]||C.y)+';color:inherit;border-radius:2px;cursor:pointer';t.replaceWith(m);m.appendChild(t);}pos+=len;}};
const hide=()=>{if(bar){bar.remove();bar=null;}};
const btn=(label,css,fn)=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.style.cssText=css;b.addEventListener('mousedown',ev=>ev.preventDefault());b.addEventListener('click',fn);return b;};
const show=(rect,items)=>{hide();bar=document.createElement('div');bar.id='hlbar';
bar.style.cssText='position:fixed;z-index:80;display:flex;align-items:center;gap:10px;padding:8px 12px;border-radius:999px;background:#1b1b1d;color:#fff;box-shadow:0 4px 16px rgba(0,0,0,.25);font-size:13px';
items.forEach(x=>bar.appendChild(x));document.body.appendChild(bar);const w=bar.offsetWidth;
if(matchMedia('(pointer:coarse)').matches){bar.style.left=Math.max(8,(innerWidth-w)/2)+'px';bar.style.bottom='84px';}
else{bar.style.left=Math.min(innerWidth-w-8,Math.max(8,rect.left+rect.width/2-w/2))+'px';bar.style.top=(rect.top>64?rect.top-48:rect.bottom+8)+'px';}};
const post=(url,data)=>fetch(url,{method:'POST',body:new URLSearchParams(data)}).then(r=>r.json()).catch(()=>({}));
const pick=()=>{const sel=getSelection();if(!sel.rangeCount||sel.isCollapsed){if(bar&&bar.dataset.del)return;return hide();}const r=sel.getRangeAt(0);if(!root.contains(r.commonAncestorContainer)||r.commonAncestorContainer.parentElement?.closest('#hlbar'))return hide();
const s=off(r.startContainer,r.startOffset),e=off(r.endContainer,r.endOffset),t=text().slice(s,e);if(!t.trim()||t.length>500)return hide();
const dots=Object.keys(C).map(c=>btn('','width:24px;height:24px;border-radius:50%;border:2px solid #fff;background:'+C[c],async()=>{const j=await post('/hl',{p:P,s,e,t,c});paint(s,e,c,j.id||'');sel.removeAllRanges();hide();}));
dots[0].setAttribute('aria-label','노랑');dots[1].setAttribute('aria-label','초록');dots[2].setAttribute('aria-label','분홍');dots[3].setAttribute('aria-label','파랑');
show(r.getBoundingClientRect(),[...dots,btn('복사','color:#fff;padding:2px 6px;font-weight:600',async ev=>{try{await navigator.clipboard.writeText(sel.toString());ev.target.textContent='복사했어요';setTimeout(hide,700);}catch(err){hide();}}),
btn('공유','color:#fff;padding:2px 6px;font-weight:600',async ev=>{const j=await post('/hl/share',{p:P,t});ev.target.textContent=j.msg||'공유하지 못했어요';setTimeout(hide,1400);})]);};
document.addEventListener('selectionchange',()=>{clearTimeout(timer);timer=setTimeout(pick,250);});
root.addEventListener('click',ev=>{const m=ev.target.closest('mark[data-hl]');if(!m||!getSelection().isCollapsed)return;ev.preventDefault();const id=m.dataset.hl;
show(m.getBoundingClientRect(),[btn('형광펜 지우기','color:#fff;padding:2px 6px;font-weight:600',()=>{if(id)post('/hl/del',{id});
root.querySelectorAll('mark[data-hl]').forEach(x=>{if(x.dataset.hl===id){const par=x.parentNode;x.replaceWith(...x.childNodes);par.normalize();}});hide();}),
btn('공유','color:#fff;padding:2px 6px;font-weight:600',async ev=>{const t=[...root.querySelectorAll('mark[data-hl]')].filter(x=>x.dataset.hl===id).map(x=>x.textContent).join('');const j=await post('/hl/share',{p:P,t});ev.target.textContent=j.msg||'공유하지 못했어요';setTimeout(hide,1400);})]);bar.dataset.del='1';});
document.addEventListener('mousedown',ev=>{if(bar&&bar.dataset.del&&!ev.target.closest('#hlbar,mark[data-hl]'))hide();});
document.addEventListener('scroll',()=>{if(bar&&getSelection().isCollapsed)hide();},{passive:true});
fetch('/hl?p='+encodeURIComponent(P)).then(r=>r.json()).then(list=>{for(const h of list){const T=text();let s=h.s,e=h.e;if(T.slice(s,e)!==h.t){const i=T.indexOf(h.t);if(i<0)continue;s=i;e=i+h.t.length;}paint(s,e,h.c,String(h.id));}}).catch(()=>{});
})();</script>"""
HL_PAGE = re.compile(r"/(n|a|learn)/[A-Za-z0-9_\-./%]{1,80}")
HL_MAX, HL_PER_PAGE = 500, 100  # 한 번에 칠하는 글자 수 · 한 화면에 남기는 개수
QUOTE_MIN, QUOTE_MAX = 5, 200  # 프로필에 공유하는 글귀 길이
TAGS = re.compile(r"<(script|style)\b.*?</\1>|<[^>]+>", re.S)


# 홈 화면에 추가 · 플레이스토어 포장(TWA) — 앱 정보 한 장과 서비스 워커. 서비스 워커는 화면을 저장해 두지 않는다(노트는 늘 새것):
# 인터넷이 끊겼을 때만 미리 받아 둔 「연결이 끊겼어요」 화면을 보여 준다 (흰 화면·브라우저 오류 대신 — 앱 심사가 보는 것)
MANIFEST = json.dumps({
    "name": "한장 — 내 주식, 쉬운 글 한 장", "short_name": "한장", "lang": "ko", "start_url": "/", "scope": "/", "id": "/",
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


def page(title: str, body_attr: str, inner: str) -> str:
    return (f'<!DOCTYPE html><html lang="ko"><head>{HEAD}{CSS_TAG}{share_tags()}{PWA_TAGS}<title>{e(title)} · 한장</title></head>'
            f'<body class="{body_attr}">{inner}{STAY}{HL}</body></html>')  # fmt: skip


# 업종마다 작은 그림 하나 — 노트 머리에 귀엽게 (사용자 10/10: 톱니바퀴 같은 것). Material Symbols(Apache 2.0) 아이콘 이름
INDUSTRY_ICON = {"반도체": "memory", "전자부품": "developer_board", "전자·통신장비": "devices", "통신": "cell_tower",
                 "은행": "account_balance", "금융": "account_balance", "금융서비스": "account_balance", "증권": "candlestick_chart", "보험": "health_and_safety",
                 "지주회사": "domain", "제약·바이오": "medication", "연구개발": "biotech", "화학": "science", "석유정제": "oil_barrel",
                 "2차전지": "battery_charging_full", "전지": "battery_charging_full", "자동차": "directions_car", "타이어·고무": "tire_repair",
                 "조선": "directions_boat", "해운": "sailing", "무역·도매": "storefront", "물류": "local_shipping", "건설": "construction",
                 "엔지니어링": "engineering", "기계": "settings", "전기장비": "electric_bolt", "전선·케이블": "cable", "전력·가스": "bolt",
                 "항공우주": "rocket_launch", "방위산업": "shield", "항공": "flight", "철강·금속": "hardware", "금속가공": "hardware",
                 "인터넷 플랫폼": "language", "소프트웨어": "code", "IT 서비스": "dns", "게임": "sports_esports", "화장품": "spa",
                 "식료품": "restaurant", "엔터테인먼트": "music_note", "철도차량": "train", "담배": "local_florist", "생활 서비스": "home"}  # fmt: skip


def industry_chip(code: str | None) -> str:
    """노트 머리 — 업종 그림 + 이름 (예: ⚙ 기계). 업종을 모르면 빈 문자열."""
    label = industry_label(code)
    if not label:
        return ""
    icon = INDUSTRY_ICON.get(label, "category")
    return (f'<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-primary-fixed/60 text-primary">'
            f'<span class="material-symbols-outlined text-[15px]" aria-hidden="true">{icon}</span><span class="text-[12px] font-semibold">{e(label)}</span></span>')  # fmt: skip


def ago(at: str) -> str:
    """알림 시각 — 「방금」「12분 전」「3시간 전」「10월 9일」."""
    try:
        secs = (datetime.now() - datetime.fromisoformat(at)).total_seconds()
    except ValueError:
        return ""
    if secs < 60:
        return "방금"
    if secs < 3600:
        return f"{int(secs // 60)}분 전"
    if secs < 86400:
        return f"{int(secs // 3600)}시간 전"
    d = datetime.fromisoformat(at)
    return f"{d.month}월 {d.day}일"


class Me(str):
    """위쪽 동그라미에 넣을 것(사진 주소나 첫 글자) + 안 읽은 알림 수 — avatar() 가 알림 단추를 함께 그린다."""
    unread = 0


def bell(unread: int) -> str:
    dot = (f'<span class="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 rounded-full bg-tertiary text-on-tertiary text-[10px] leading-4 text-center font-semibold">{min(unread, 99)}</span>'
           if unread else "")  # fmt: skip
    return (f'<a href="/me/notices" aria-label="알림{f" {unread}개" if unread else ""}" class="relative w-8 h-8 flex items-center justify-center text-on-surface-variant hover:text-on-surface">'
            f'<span class="material-symbols-outlined text-[22px]">notifications</span>{dot}</a>')  # fmt: skip


def avatar(initial: str) -> str:
    """시안의 프로필 사진 자리 — 사진(「/p/…」 주소)이 있으면 사진, 없으면 첫 글자 동그라미. 누르면 내 프로필. 옆에 알림 단추."""
    if isinstance(initial, Me):
        return bell(initial.unread) + _avatar(initial)
    return _avatar(initial)


def _avatar(initial: str) -> str:
    inside = (f'<img alt="" class="w-full h-full object-cover" src="{e(initial)}">' if initial.startswith("/p/") else e(initial.upper()))
    return (f'<a href="/me" aria-label="내 프로필" class="w-8 h-8 rounded-full overflow-hidden bg-surface-container-high flex items-center justify-center '
            f'text-on-surface-variant font-label-regular text-label-regular hover:bg-surface-container-highest transition-colors">{inside}</a>')  # fmt: skip


# 업종 → 분위기 사진 (Unsplash 무료 라이선스, hanjang/static/photos/SOURCES.md). 회사 사진이 아니라 주제 사진이다
STATIC = Path(__file__).parent / "static"
# 화면 CSS — tailwind.config.js 로 미리 만든 파일. 내용이 바뀌면 주소(?v=)도 바뀌어 브라우저가 새로 받는다
CSS_TAG = f'<link rel="stylesheet" href="/static/app.css?v={hashlib.sha256((STATIC / "app.css").read_bytes()).hexdigest()[:10]}">'
PHOTO = {"반도체": "semiconductor", "전자부품": "electronics", "전자·통신장비": "electronics", "통신": "telecom",
         "은행": "bank", "금융서비스": "bank", "증권": "securities", "보험": "insurance", "지주회사": "holding",
         "제약·바이오": "bio", "연구개발": "bio", "화학": "chemical", "석유정제": "chemical",
         "2차전지": "battery", "전지": "battery", "자동차": "auto", "타이어·고무": "auto",
         "조선": "shipbuilding", "해운": "shipping", "무역·도매": "shipping", "물류": "logistics",
         "건설": "construction", "엔지니어링": "construction", "기계": "construction",
         "전기장비": "power", "전선·케이블": "power", "전력·가스": "power",
         "항공우주": "aero", "방위산업": "aero", "항공": "aero", "철강·금속": "steel",
         "인터넷 플랫폼": "internet", "소프트웨어": "internet", "IT 서비스": "internet", "게임": "game",
         "화장품": "cosmetics", "식료품": "food", "엔터테인먼트": "entertainment", "철도차량": "rail"}  # fmt: skip


KIND_PHOTO = {"LAWSUIT": "lawsuit", "DIVIDEND": "dividend", "BUYBACK": "dividend", "MAJOR_CONTRACT": "contract"}


# 피드 사진 묶음 — 사건 종류·업종마다 고를 주제 (static/photos/pool/<주제><번호>.jpg). 한 화면에 같은 사진은 두 번 안 쓴다
KIND_TOPICS = {"MAJOR_CONTRACT": ("contract", "docs", "meeting"), "DIVIDEND": ("money",), "BUYBACK": ("money", "chart"),
               "LAWSUIT": ("docs",), "EARNINGS": ("chart", "docs"), "RIGHTS_ISSUE": ("money", "chart"), "CB_BW": ("money", "chart"),
               "MA": ("meeting", "contract", "building"), "HOLDER_CHANGE": ("building", "chart", "meeting"), "CLINICAL": ("lab", "pills")}
INDUSTRY_TOPICS = {"semiconductor": ("chip", "server"), "electronics": ("chip",), "telecom": ("server",), "internet": ("server",),
                   "game": ("server",), "bio": ("lab", "pills"), "shipbuilding": ("ship",), "shipping": ("ship",),
                   "logistics": ("ship",), "construction": ("site",), "power": ("powerplant",), "chemical": ("factory", "powerplant"),
                   "steel": ("factory",), "auto": ("robot", "factory"), "battery": ("robot", "factory"), "aero": ("factory",),
                   "bank": ("building", "money"), "securities": ("chart", "building"), "insurance": ("building",),
                   "holding": ("building", "meeting"), "seoul": ("city",)}  # fmt: skip


class Photos:
    """한 화면 안에서 사진을 겹치지 않게 고른다 — 사건 종류 주제 → 업종 사진 → 업종 주제 → 남은 아무 사진 순서."""

    def __init__(self):
        self.used: set[str] = set()
        self.pool = sorted(f"/static/photos/pool/{p.name}" for p in (STATIC / "photos" / "pool").glob("*.jpg"))

    def topic(self, t: str) -> list[str]:
        return [p for p in self.pool if re.sub(r"\d+\.jpg$", "", p.rsplit("/", 1)[1]) == t]

    def pick(self, kind: str | None, induty_code: str | None, name: str = "") -> str:
        main = photo_for(induty_code, name)
        key = main.rsplit("/", 1)[1][:-4]
        cands = ([f"/static/photos/{KIND_PHOTO[kind]}.jpg"] if kind in KIND_PHOTO else [])
        cands += [p for t in KIND_TOPICS.get(kind or "", ()) for p in self.topic(t)]
        cands += [main] + [p for t in INDUSTRY_TOPICS.get(key, ()) for p in self.topic(t)] + self.pool
        got = next((p for p in cands if p not in self.used), cands[0])  # 다 썼으면(사진보다 글이 많으면) 그때만 겹친다
        self.used.add(got)
        return got


def photo_for(induty_code: str | None, name: str = "") -> str:
    label = industry_label(induty_code) or ""
    key = "bank" if label == "지주회사" and "금융" in name else PHOTO.get(label, "seoul")  # 금융지주는 은행 사진
    return f"/static/photos/{key}.jpg"


def story(href: str, img: str, title: str, excerpt: str, source: str, day: str, top: str = "") -> str:
    """뉴닉식 한 줄 — 왼쪽 사진, 오른쪽 제목 · 두 줄 요약 · 출처와 날짜. 글씨는 작게, 줄 사이는 넉넉히 (사용자 10/8)."""
    return (f'<article class="py-4 lg:py-6 flex flex-col gap-2">{top}<a href="{e(href)}" class="flex gap-3.5 items-start lg:flex-col lg:gap-4 group">'
            f'<img alt="" loading="lazy" class="w-[36%] max-w-[148px] aspect-[4/3] lg:w-full lg:max-w-none lg:aspect-[16/9] object-cover rounded-lg lg:rounded-2xl shrink-0 bg-surface-container" src="{e(img)}">'
            '<span class="min-w-0 flex flex-col gap-1 lg:gap-2 pt-0.5">'
            f'<span class="text-[15px] leading-[21px] lg:text-[21px] lg:leading-[30px] font-semibold tracking-tight text-on-surface line-clamp-2 lg:group-hover:underline">{e(title)}</span>'
            f'<span class="text-[13px] leading-[19px] lg:text-[15px] lg:leading-[25px] text-on-surface-variant line-clamp-2 lg:line-clamp-3">{e(excerpt)}</span>'
            f'<span class="mt-0.5 text-[11px] leading-4 lg:text-[13px] text-outline"><b class="text-on-surface-variant font-medium">{e(source)}</b>  {e(day)}</span>'
            "</span></a></article>")  # fmt: skip


def note_card(t: str, name: str, home: str | None, head: str, day: str, top: str = "") -> str:
    """노트 리그램 — 내 종목 카드와 같은 모양: 로고 · 이름 · 종목 코드 · 날짜 / 한 줄 요약 / 「노트 읽기 →」 (사용자 10/9)."""
    return (f'<article class="py-4 flex flex-col gap-2">{top}<div class="flex items-center gap-2">{logo(name, home, "w-7 h-7")}'
            f'<a href="/n/{e(t)}"><h3 class="font-headline-sm text-headline-sm text-on-surface font-semibold hover:underline">{e(name)}</h3></a>'
            f'<span class="font-citation-ref text-citation-ref text-outline px-1.5 py-0.5 rounded bg-surface-container-low">{e(t)}</span>'
            f'<span class="font-label-micro text-label-micro text-outline-variant">{e(day)}</span></div>'
            f'<a href="/n/{e(t)}"><p class="font-body-reading text-body-reading text-on-surface tracking-tight">{e(head)}</p></a>'
            f'<div class="flex justify-end"><a class="font-label-micro text-label-micro text-primary flex items-center gap-0.5 hover:underline font-semibold" href="/n/{e(t)}">노트 읽기'
            '<span class="material-symbols-outlined text-[14px]">arrow_forward</span></a></div></article>')  # fmt: skip


def row(href: str, img: str, title: str, excerpt: str, source: str, day: str, top: str = "") -> str:
    """피드 기사 리그램 — 뉴닉식 한 줄: 왼쪽 작은 사진 · 제목 · 두 줄 요약 · 출처와 날짜. 넓은 화면에서도 사진은 작게 (사용자 10/9)."""
    return (f'<article class="py-4 flex flex-col gap-2">{top}<a href="{e(href)}" class="flex gap-4 items-start group">'
            f'<img alt="" loading="lazy" class="w-[36%] max-w-[180px] aspect-[4/3] object-cover rounded-xl shrink-0 bg-surface-container" src="{e(img)}">'
            '<span class="min-w-0 flex flex-col gap-1 pt-0.5">'
            f'<span class="text-[15px] leading-[22px] lg:text-[18px] lg:leading-[26px] font-semibold tracking-tight text-on-surface line-clamp-2 group-hover:underline">{e(title)}</span>'
            f'<span class="text-[13px] leading-[19px] lg:text-[15px] lg:leading-[23px] text-on-surface-variant line-clamp-2">{e(excerpt)}</span>'
            f'<span class="mt-0.5 text-[11px] leading-4 lg:text-[13px] text-outline"><b class="text-on-surface-variant font-medium">{e(source)}</b>  {e(day)}</span>'
            "</span></a></article>")  # fmt: skip


def mini(href: str, mark: str, title: str, excerpt: str, source: str, day: str, top: str = "") -> str:
    """리그램 카드 — 큰 사진 없이 내 종목 카드처럼: 로고(또는 아이콘) · 이름 · 한 줄 요약 · 두 줄 설명 (사용자 10/9: 사진이 너무 커요)."""
    return (f'<article class="py-4 flex flex-col gap-2">{top}<a href="{e(href)}" class="flex flex-col gap-1.5 group">'
            f'<span class="flex items-center gap-2">{mark}<b class="text-[15px] font-semibold text-on-surface">{e(source)}</b>'
            f'<span class="text-[12px] text-outline">{e(day)}</span></span>'
            f'<span class="text-[16px] leading-[24px] font-medium text-on-surface group-hover:underline">{e(title)}</span>'
            f'<span class="text-[13px] leading-[20px] text-on-surface-variant line-clamp-2">{e(excerpt)}</span></a></article>')  # fmt: skip


def gist(body: dict) -> str:
    """요약 한 줄 — 한 장 요약의 첫 문장, 없으면 첫 절의 첫 문장."""
    first = body.get("summary") or next((s["sentences"] for s in body.get("sections", []) if s["sentences"]), [])
    return notes.mend(first[0]["text"]) if first else ""


# 로고를 못 쓸 때의 표시 — 그룹 대표색 동그라미 + 짧은 이름. 로고 모양은 따라 그리지 않는다(색·글자만).
# (이름 앞부분, 보일 글자, 바탕색, 글자색) — 앞에서부터 처음 맞는 것
GROUP = (("삼성", "삼성", "#1428A0", "#fff"), ("SK", "SK", "#EA002C", "#fff"), ("LG", "LG", "#A50034", "#fff"),
         ("LIG", "LIG", "#00205B", "#fff"), ("LS", "LS", "#0A3D91", "#fff"), ("KB", "KB", "#FFBC00", "#3d2f00"),
         ("KT&G", "KT&G", "#C8102E", "#fff"), ("KT", "KT", "#ED1C24", "#fff"), ("HD", "HD", "#0A2F6B", "#fff"),
         ("현대", "현대", "#002C5F", "#fff"), ("기아", "KIA", "#05141F", "#fff"), ("한화", "한화", "#F37321", "#fff"),
         ("포스코", "POSCO", "#05507D", "#fff"), ("POSCO", "POSCO", "#05507D", "#fff"), ("두산", "두산", "#005EB8", "#fff"),
         ("카카오", "kakao", "#FFE812", "#3a1d1d"), ("NAVER", "N", "#03C75A", "#fff"), ("신한", "신한", "#0046FF", "#fff"),
         ("하나", "하나", "#008485", "#fff"), ("우리", "우리", "#0067AC", "#fff"), ("DB", "DB", "#00854A", "#fff"),
         ("GS", "GS", "#005A9C", "#fff"), ("CJ", "CJ", "#EF3E33", "#fff"), ("한국전력", "KEPCO", "#00A0E2", "#fff"),
         ("한전", "KEPCO", "#00A0E2", "#fff"), ("셀트리온", "셀트", "#4A2A8C", "#fff"), ("NH", "NH", "#0B7A3E", "#fff"),
         ("BNK", "BNK", "#D6001C", "#fff"), ("JB", "JB", "#00479D", "#fff"), ("HMM", "HMM", "#003A70", "#fff"),
         ("S-Oil", "S-OIL", "#FFD100", "#1d2a57"), ("한진", "한진", "#004C97", "#fff"), ("대한항공", "KAL", "#0064DE", "#fff"),
         ("메리츠", "메리츠", "#E4002B", "#fff"), ("미래에셋", "미래", "#F58220", "#fff"), ("키움", "키움", "#E5006E", "#fff"),
         ("하이브", "HYBE", "#111111", "#fff"), ("크래프톤", "KRAF", "#111111", "#fff"))  # fmt: skip
OTHER = ("#154539", "#2f5d50", "#5a3e8c", "#0e6e8c", "#8c5a0e", "#8c2f2f", "#3e5a8c", "#4a6b2f")  # 그 밖의 회사 — 이름마다 정해진 색


def mark(name: str, size: str = "w-9 h-9") -> str:
    hit = next((g for g in GROUP if name.startswith(g[0])), None)
    if hit:
        text, bg, fg = hit[1], hit[2], hit[3]
    else:
        text, bg, fg = name[:1], OTHER[sum(map(ord, name)) % len(OTHER)], "#fff"
    fs = {1: "13px", 2: "11px" if text.isascii() else "10px"}.get(len(text), "8px" if len(text) <= 4 else "7px")
    return (f'<span class="{size} shrink-0 rounded-full flex items-center justify-center font-bold tracking-tight leading-none" '
            f'style="background:{bg};color:{fg};font-size:{fs}">{e(text)}</span>')  # fmt: skip


def logo(name: str, homepage: str | None, size: str = "w-9 h-9") -> str:
    """회사 로고 동그라미 — Brandfetch Logo API(무료·출처 표시 의무 없음, .env BRANDFETCH_CLIENT_ID).
    키나 도메인이 없거나 로고를 못 찾으면 첫 글자 동그라미. 로고는 「이 회사」를 알려주는 데만 쓴다(상표적 사용 아님)."""
    letter = mark(name, size)
    key = env().get("BRANDFETCH_CLIENT_ID", "")
    if not (key and homepage):
        return letter
    src = f"https://cdn.brandfetch.io/{quote(homepage)}/w/96/h/96/fallback/404?c={quote(key)}"
    return (f'<span class="{size} shrink-0 rounded-full overflow-hidden bg-surface-container-lowest border border-outline-variant/40 flex items-center justify-center">'
            f'<img alt="{e(name)} 로고" class="w-full h-full object-contain" loading="lazy" src="{e(src)}" '
            f'onerror="this.parentNode.outerHTML={e(json.dumps(letter))}"></span>')  # fmt: skip


DART_VIEW = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"


def business_block(biz: dict | None, rno: str | None) -> str:
    """무엇으로 돈을 버나요? — 회사 사업보고서 「사업의 내용」을 AI 가 요약(숫자는 원문 그대로인지 코드가 대조) + 부문별 매출 비중 막대."""
    if not biz:
        return ""
    segs = "".join(
        f'<div class="flex items-center gap-2 py-1"><span class="w-[44%] text-[12px] leading-4 text-on-surface-variant">{e(s["name"])}</span>'
        f'<span class="flex-1 h-2 rounded-full bg-surface-container overflow-hidden"><span class="block h-full bg-primary rounded-full" style="width:{min(float(s["share"][:-1]), 100):.1f}%"></span></span>'
        f'<span class="w-12 text-right text-[12px] font-semibold text-on-surface tabular-nums">{e(s["share"])}</span></div>' for s in biz.get("segments", []))  # fmt: skip
    url = rno if (rno or "").startswith("http") else DART_VIEW.format(rno)  # 미국은 report() 가 SEC 주소를 넘긴다
    link = f'<a class="text-outline underline" href="{url}" target="_blank" rel="noopener">{"연차 보고서(10-K) 원문" if url.startswith("https://www.sec.gov") else "사업보고서 원문"}</a>' if rno else ""
    return chapter("무엇으로 돈을 버나요?", " ".join(e(x) for x in biz["what"]),
                   (f'<div class="mt-space-xs"><div class="font-label-micro text-label-micro text-outline mb-1">부문별 매출 비중</div>{segs}</div>' if segs else "")
                   + f'<p class="font-label-micro text-label-micro text-outline">회사가 낸 {biz.get("year", "")}년 사업보고서를 요약했어요 · {link}</p>')  # fmt: skip


def ring(parts: list[tuple[float, str]], size: str = "w-20 h-20") -> str:
    """둘레 100 짜리 원 — (비율%, 색) 조각들을 이어 그린다. dasharray 가 곧 %."""
    acc, out = 0.0, []
    for pct, col in parts:
        out.append(f'<circle cx="21" cy="21" r="15.915" fill="none" stroke="{col}" stroke-width="7" '
                   f'stroke-dasharray="{pct:.2f} {100 - pct:.2f}" stroke-dashoffset="{25 - acc:.2f}"/>')  # fmt: skip
        acc += pct
    return f'<svg viewBox="0 0 42 42" class="{size} shrink-0">{"".join(out)}</svg>'


def money_blocks(fin: tuple | None, mid: dict | None = None) -> str:
    """회사 사정 아래 그림 둘 — ① 100원 팔면 얼마 남나(매출→영업이익→순이익) ② 빚과 내 돈(부채 : 자본).
    증권사 보고서의 손익·재무상태표를 그대로 옮기지 않고 질문 하나에 그림 하나 (사용자 10/9). 매출이 없는 금융사는 ①②를 그리지 않는다
    (예금이 빚으로 잡혀 부채비율이 뜻이 없다)."""
    if not fin:
        return ""
    mid = mid or {}
    y, rev, oi, ni, eq, li = fin
    if mid.get("금융"):  # 증권·은행·보험 — 고객 돈이 빚으로, 사고판 금액이 매출로 잡혀 두 그림 모두 다른 업종과 같은 잣대가 아니다 (사용자 10/9)
        roe = f" 대신 자기 돈으로 1년에 얼마를 벌었는지(ROE {ni / eq * 100:.1f}%)를 봐요." if ni is not None and eq and eq > 0 else ""
        return ('<div class="py-space-md my-space-xs border-b border-outline-variant/30"><div class="font-label-regular text-label-regular text-on-surface font-semibold">금융회사는 잣대가 달라요</div>'
                '<p class="mt-1 text-[13px] leading-relaxed text-on-surface-variant">고객이 맡긴 돈이 「빚」으로 잡혀 부채비율이 원래 수백~천 %이고, 사고판 금액이 「매출」로 잡혀 100원당 남긴 돈이 작게 나와요. '
                f'그래서 이 두 그림은 싣지 않아요.{e(roe)}</p>'
                '<a class="mt-1 inline-block text-[12px] text-primary underline" href="/learn/sector-finance">금융회사는 어떻게 봐요? →</a></div>')  # fmt: skip
    out = []
    if rev and rev > 0 and oi is not None and ni is not None:
        rows = [("매출 — 판 돈", rev, "bg-primary"), ("영업이익 — 본업으로 남긴 돈", oi, "bg-secondary"), ("순이익 — 세금·이자까지 내고 남은 돈", ni, "bg-secondary/60")]
        bars = "".join(
            f'<div class="flex items-center gap-3 py-1.5"><span class="w-[52%] text-[12px] leading-4 text-on-surface-variant">{e(k)}</span>'
            f'<span class="flex-1 h-2.5 rounded-full bg-surface-container overflow-hidden"><span class="block h-full {col} rounded-full" style="width:{max(min(v / rev * 100, 100), 0):.1f}%"></span></span>'
            f'<span class="w-11 text-right text-[12px] font-semibold tabular-nums {"text-tertiary" if v < 0 else "text-on-surface"}">{"적자" if v < 0 else f"{v / rev * 100:.0f}원"}</span></div>'
            for k, v, col in rows)  # fmt: skip
        usual = (f'<p class="text-[11px] text-outline mt-2">같은 업종({e(mid["업종"])}) {mid["곳수"]}곳 보통(중간값): 영업이익 {mid["백원당"]:.0f}원'
                 f'{". 이 업종은 원래 조금씩 남겨요" if mid["백원당"] < 5 else ""} · <a class="text-primary underline" href="/learn/sector-margin">업종마다 달라요</a></p>'
                 if mid.get("백원당") is not None else "")  # fmt: skip
        out.append(f'<div class="font-label-regular text-label-regular text-on-surface font-semibold mb-2">{y}년, 100원 팔면 얼마 남았나</div>{bars}{usual}')
        if eq and eq > 0 and li is not None:
            ratio = li / eq * 100
            a, b = eq / (eq + li) * 100, li / (eq + li) * 100
            out.append(f'<div class="mt-8 font-label-regular text-label-regular text-on-surface font-semibold">빚과 내 돈 — 부채비율 {ratio:,.0f}%</div>'
                       '<div class="mt-3 h-3 w-full rounded-full overflow-hidden flex">'
                       f'<span class="h-full bg-primary" style="width:{a:.1f}%"></span><span class="h-full" style="width:{b:.1f}%;background:#F4806A"></span></div>'
                       f'<div class="flex justify-between text-[11px] text-on-surface-variant mt-2"><span>내 돈(자본) {notes.won(eq)}</span><span>빚(부채) {notes.won(li)}</span></div>'
                       f'<p class="mt-1.5 text-[11px] leading-[18px] text-outline">내 돈 100원에 빚 {ratio:,.0f}원이 있다는 뜻이에요. '
                       + (f'같은 업종({e(mid["업종"])}) 보통(중간값)은 {mid["부채비율"]:,.0f}%예요. ' if mid.get("부채비율") is not None else "")
                       + (f'{e(mid["업종"])} 업종은 {e(mid["빚이유"])}. <a class="text-primary underline" href="/learn/sector-debt">더 보기</a>' if mid.get("빚이유")
                          else "" if mid.get("부채비율") is not None else "업종마다 보통 수준이 달라요.")
                       + '</p>')  # fmt: skip
    if not out:
        return ""
    return ('<div class="py-6 my-space-sm border-b border-outline-variant/30">' + "".join(out)
            + '<p class="mt-5 text-[11px] text-outline">연결재무제표 기준 · 자료: DART 사업보고서</p></div>')  # fmt: skip


def returns_html(divs: list[tuple], buys: list[tuple]) -> str:
    """주주에게 돌려준 돈 — 최근 해 배당 총액 + 최근 1년 자사주 취득 결정 금액. 기간이 달라 더하지 않고 나란히 (사용자 10/9 검토)."""
    rows = []
    if divs and divs[-1][2]:
        rows.append((f"{divs[-1][0]}년 배당", divs[-1][2], DONUT[0]))
    if buys:
        rows.append((f"최근 1년 자사주 사기로 한 돈 · {len(buys)}번", sum(a for _, a in buys), DONUT[3]))
    if len(rows) < 2:
        return ""
    top = max(v for _, v, _ in rows)
    bars = "".join(f'<div class="flex items-center gap-2 py-0.5"><span class="w-[46%] text-[12px] leading-4 text-on-surface-variant">{e(k)}</span>'
                   f'<span class="flex-1 h-2.5 rounded-full bg-surface-container overflow-hidden"><span class="block h-full rounded-full" style="width:{v / top * 100:.1f}%;background:{c}"></span></span>'
                   f'<span class="w-16 text-right text-[12px] font-semibold text-on-surface tabular-nums">{e(notes.won(v))}</span></div>' for k, v, c in rows)  # fmt: skip
    return ('<div class="py-2"><div class="font-label-regular text-label-regular text-on-surface font-semibold mb-1">배당만이 아니에요 — 자사주로 돌려준 것까지</div>'
            f'{bars}<p class="text-[11px] text-outline mt-1">자사주 금액은 회사가 「사기로 결정」한 금액이에요(실제 산 금액과 다를 수 있어요). 자료: DART 공시</p></div>')  # fmt: skip


def dividend_block(divs: list[tuple], fin: tuple | None = None, buys: list[tuple] | None = None) -> str:
    """주주에게 돌려준 것 — 해마다 주당 현금배당금(보통주) 막대 + 번 돈을 어떻게 썼나 도넛(배당 : 회사에 남김) + 최근 배당성향."""
    divs = [r for r in divs if r[1]]
    if not divs:
        return ""
    ring_html = ""
    if fin and fin[0] == divs[-1][0] and fin[3] and fin[3] > 0 and divs[-1][2]:
        ni, tot = fin[3], divs[-1][2]
        p = min(tot / ni * 100, 100)
        ring_html = (f'<div class="flex items-center gap-3 py-2"><div class="relative">{ring([(p, DONUT[0]), (100 - p, DONUT[6])], "w-[72px] h-[72px]")}'
                     f'<div class="absolute inset-0 flex items-center justify-center text-[12px] font-bold text-on-surface">{p:.0f}%</div></div>'
                     f'<ul class="text-[12px] text-on-surface"><li class="flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-sm" style="background:{DONUT[0]}"></span>배당으로 나눠 줌 {notes.won(tot)}</li>'
                     f'<li class="flex items-center gap-1.5 mt-1"><span class="w-2.5 h-2.5 rounded-sm" style="background:{DONUT[6]}"></span>회사에 남김 {notes.won(max(ni - tot, 0))}</li>'
                     f'<li class="text-[11px] text-outline mt-1">{fin[0]}년 순이익 {notes.won(ni)} 가운데</li></ul></div>')  # fmt: skip
    top = max(r[1] for r in divs)
    bars = "".join(f'<div class="flex-1 flex flex-col items-center gap-1"><span class="text-[10px] text-on-surface-variant tabular-nums">{r[1]:,}</span>'
                   f'<span class="w-full max-w-[28px] rounded-t bg-secondary/80" style="height:{max(r[1] / top * 72, 2):.0f}px"></span>'
                   f'<span class="text-[10px] text-outline">{r[0]}</span></div>' for r in divs)  # fmt: skip
    y, dps, total, payout = divs[-1]
    text = (f"{y}년에는 한 주에 {dps:,}원을 현금으로 나눠 줬어요" + (f"(배당 총액 {notes.won(total)})" if total else "") + "."
            + (f" 번 돈(순이익)의 {payout:.1f}%를 배당으로 쓴 셈이에요(배당성향)." if payout else ""))  # fmt: skip
    return chapter("주주에게 돌려준 것", e(text),
                   ring_html + returns_html(divs, buys or []) + f'<div class="flex items-end gap-1 h-[110px] pt-2">{bars}</div>'
                   '<p class="font-label-micro text-label-micro text-outline">주당 현금배당금(보통주, 원) · 자료: DART 「배당에 관한 사항」</p>')  # fmt: skip


# 위험 낱말 → 같이 볼 숫자. 앞에서부터 처음 맞는 것 하나. 값은 재무표(최근 두 해)에서 코드가 나눈다
WATCH = ((r"가격|수급|공급|시황|수요|경기|업황|경쟁|원가|판매", "영업이익률", lambda f: f[2] / f[1] * 100 if f[1] and f[1] > 0 and f[2] is not None else None),
         (r"부채|차입|금리|유동성|자금|이자", "부채비율", lambda f: f[5] / f[4] * 100 if f[4] and f[4] > 0 and f[5] is not None else None),
         (r"발주|수주|투자 계획|소비량|정책|주문", "매출", None))  # fmt: skip  매출은 금액과 전년 대비 변화로


def watch(risk: str, fins: list[tuple], used: set | None = None) -> str:
    """fins = [(연도, 매출, 영업이익, 순이익, 자본, 부채)] 최근 해부터. used = 이미 붙인 숫자 — 같은 숫자를 위험마다 되풀이하지 않는다."""
    used = set() if used is None else used
    for pat, name, calc in WATCH:
        if calc is None:  # 매출 — 금액 + 전년 대비
            if re.search(pat, risk) and name not in used and fins and fins[0][1]:
                used.add(name)
                chg = f" · 전년보다 {(fins[0][1] / fins[1][1] - 1) * 100:+.1f}%" if len(fins) > 1 and fins[1][1] and fins[1][1] > 0 else ""
                return f'<span class="block text-[12px] text-outline">살펴볼 숫자: 매출 {notes.won(fins[0][1])} ({fins[0][0]}년{chg})</span>'
            continue
        now = calc(fins[0]) if fins else None
        if re.search(pat, risk) and now is not None and name not in used:
            used.add(name)
            was = f" · {fins[1][0]}년 {v:.1f}%" if len(fins) > 1 and (v := calc(fins[1])) is not None else ""
            return f'<span class="block text-[12px] text-outline">살펴볼 숫자: {name} {now:.1f}% ({fins[0][0]}년{was})</span>'
    return ""


def risk_block(biz: dict | None, fins: list[tuple] | None = None) -> str:
    if not biz or not biz.get("risks"):
        return ""
    used: set = set()
    items = "".join(f'<li class="flex gap-2"><span class="material-symbols-outlined text-tertiary text-[16px] mt-1" aria-hidden="true">error</span><span>{e(r)}{watch(r, fins or [], used)}</span></li>' for r in biz["risks"])
    return chapter("회사가 꼽은 위험", f'<ul class="flex flex-col gap-1.5">{items}</ul>',
                   '<p class="font-label-micro text-label-micro text-outline">회사가 사업보고서에 스스로 적은 위험이에요. 한장의 판단이 아니에요.'
                   + (' 「살펴볼 숫자」는 그 위험과 관련해 이 노트에 있는 숫자예요. 앞날을 말하는 게 아니에요.' if used else "") + '</p>')  # fmt: skip


# 큰 업종 — 통계청 산업분류 코드 앞 두 자리로 묶는다 (도넛 조각을 열 개 안쪽으로)
SECTOR = [((10, 12), "식품·생활"), ((13, 19), "식품·생활"), ((20, 20), "화학·소재"), ((21, 21), "제약·바이오"),
          ((22, 23), "화학·소재"), ((24, 25), "철강·금속"), ((26, 27), "전자·반도체"), ((28, 29), "기계·전기"),
          ((30, 31), "자동차·운송장비"), ((32, 34), "식품·생활"), ((35, 36), "에너지"), ((41, 42), "건설"),
          ((45, 47), "유통"), ((49, 52), "운송·물류"), ((55, 56), "식품·생활"), ((58, 63), "IT·통신"),
          ((64, 66), "금융"), ((70, 70), "제약·바이오"), ((71, 71), "지주회사"), ((72, 73), "IT·통신")]  # fmt: skip


def sector(code: str | None) -> str | None:
    d = int(code[:2]) if code and code[:2].isdigit() else None
    return next((name for (lo, hi), name in SECTOR if d is not None and lo <= d <= hi), None)


DONUT = ("#154539", "#2a5649", "#40695c", "#5b8172", "#7b9a8d", "#9db5aa", "#c0d1c9", "#e1e9e5")  # 진한 초록부터 — 한장 색


def groups(labels: list[str | None], w: list[float]) -> list[tuple[str, tuple[float, int]]]:
    """업종별 (합, 곳 수) — 큰 7개 + 나머지는 기타 하나로."""
    cnt: dict[str, list] = {}
    for x, v in zip(labels, w):
        k = cnt.setdefault(x or "기타", [0, 0])
        k[0] += v
        k[1] += 1
    top = sorted(((k, v) for k, v in cnt.items() if k != "기타"), key=lambda kv: -kv[1][0])[:7]
    rest = [sum(v) for v in zip(*(cnt[k] for k in cnt if k not in dict(top)))] or [0, 0]
    return top + ([("기타", rest)] if rest[1] else [])


def bars(labels: list[str | None], weights: list[float], unit: str = "종목", note: str = "") -> str:
    """업종 — 가로로 긴 막대 하나를 비율대로 나누고, 밑에 두 줄씩 이름. 도넛보다 크기 차이가 한눈에 (사용자 10/10)."""
    if not labels:
        return ""
    parts, total = groups(labels, weights), sum(weights) or 1
    segs = "".join(f'<span class="h-full" style="width:{v / total * 100:.2f}%;background:{col}" title="{e(k)} {v / total * 100:.0f}%"></span>'
                   for (k, (v, _)), col in zip(parts, DONUT))  # fmt: skip
    keys = "".join(f'<li class="flex items-center gap-2 min-w-0"><span class="w-2.5 h-2.5 rounded-sm shrink-0" style="background:{col}"></span>'
                   f'<span class="flex-1 text-[13px] text-on-surface truncate">{e(k)}</span>'
                   f'<span class="text-[13px] font-semibold text-on-surface tabular-nums">{v / total * 100:.0f}%</span>'
                   f'<span class="hidden sm:inline w-9 text-right text-[11px] text-outline tabular-nums">{n}{unit}</span></li>'
                   for (k, (v, n)), col in zip(parts, DONUT))  # fmt: skip
    return ('<section class="mt-space-xl"><h2 class="font-headline-sm text-headline-sm text-on-surface">어떤 업종에 많이 가졌나</h2>'
            f'<div class="mt-3 flex h-2.5 w-full rounded-full overflow-hidden gap-[2px] bg-surface">{segs}</div>'  # 막대는 얇게 (사용자 10/10: 조금만 줄여)
            f'<ul class="mt-4 grid grid-cols-2 gap-x-5 gap-y-2.5">{keys}</ul>'
            + (f'<p class="mt-3 text-[11px] text-outline">{e(note)}</p>' if note else "") + "</section>")  # fmt: skip


def pie(items: list[tuple[str, float]], title: str = "가장 많이 가진 종목", n: int = 5) -> str:
    """포트폴리오 파이 — 금액이 큰 n 종목만(기타 없이). 원은 가운데, 양옆에 반듯한 이름 목록(사용자 10/10).
    오른쪽 반의 조각은 오른쪽 목록(왼쪽 정렬), 왼쪽 반은 왼쪽 목록(오른쪽 정렬). 이름은 자기 조각 높이에 — 선이 거의 수평(사용자 10/10).
    겹치면 위아래로 비킨다. 조각에서 이름 옆 색 네모까지 곧은 선 — 글자는 HTML 이라 위치를 그린 뒤에 PIE_LINES 가 재서 긋는다(화면 크기가 바뀌면 다시).
    items = [(이름, 금액)] 큰 순. 13F 금액은 한 사람·한 기관의 돈이라 더하면 포트폴리오 비중이다."""
    import math

    total = sum(v for _, v in items)
    if not items or total <= 0:
        return ""
    # 기타는 그리지 않는다 — 상위 n 종목끼리 원을 나누고, 글자는 전체 중 비중 그대로(사용자 10/10)
    parts = [(k, v / total * 100) for k, v in items[:n]]
    cols, shown = DONUT, sum(p for _, p in parts)
    slices, sides, a = [], {True: [], False: []}, -math.pi * parts[0][1] / shown  # 가장 큰 조각을 3시 방향 가운데로
    for (k, pct), col in zip(parts, cols):
        b = a + pct / shown * 2 * math.pi
        x1, y1, x2, y2 = 50 + 48 * math.cos(a), 50 + 48 * math.sin(a), 50 + 48 * math.cos(b), 50 + 48 * math.sin(b)
        slices.append(f'<circle cx="50" cy="50" r="48" fill="{col}"/>' if pct >= shown - 0.01 else
                      f'<path d="M50 50 L{x1:.2f} {y1:.2f} A48 48 0 {1 if b - a > math.pi else 0} 1 {x2:.2f} {y2:.2f} Z" fill="{col}" stroke="#fcf8fb" stroke-width="1"/>')  # fmt: skip
        m = (a + b) / 2
        sides[math.cos(m) >= 0].append((math.sin(m), k, pct, col, m))
        a = b

    def column(right: bool) -> str:
        # 휴대폰·태블릿은 이름 밑에 %(같은 크기), 컴퓨터 화면이면 한 줄 — 긴 이름은 칸 안에서 말줄임
        rows = "".join(
            f'<li class="absolute inset-x-0 flex items-start gap-1.5 {"" if right else "flex-row-reverse"}" style="top:calc({50 + 48 * math.sin(m):.1f}% - 10px)">'
            f'<span data-ang="{m:.4f}" class="w-2.5 h-2.5 mt-[5px] rounded-sm shrink-0" style="background:{col}"></span>'
            f'<span class="min-w-0 flex flex-col lg:flex-row lg:gap-1.5 {"items-start" if right else "items-end"}">'
            f'<span class="max-w-full text-[13px] leading-5 text-on-surface-variant truncate">{e(k)}</span>'
            f'<span class="text-[13px] leading-5 font-semibold text-on-surface tabular-nums shrink-0">{pct:.1f}%</span></span></li>'
            for _, k, pct, col, m in sorted(sides[right]))  # fmt: skip
        return f'<ul class="relative flex-1 min-w-0 self-stretch">{rows}</ul>'

    return (f'<section class="mt-space-lg"><h2 class="font-headline-sm text-headline-sm text-on-surface">{e(title)}</h2>'
            + (f'<p class="mt-2 inline-flex items-center gap-1 px-2 py-1 rounded-md bg-surface-container text-[13px] text-on-surface-variant">'
               f'<span class="material-symbols-outlined text-[16px] text-primary">info</span>기타는 빼고 상위 {len(parts)}종목만 그렸어요 (전체의 {shown:.0f}%)</p>' if shown < 99.95 else "")  # 꼭 보이게 (사용자 10/10)
            + '<div data-pie class="relative mt-2 py-6 flex items-start gap-6 lg:gap-10">' + column(False)
            + f'<svg viewBox="0 0 100 100" class="w-36 h-36 lg:w-52 lg:h-52 shrink-0" role="img" aria-label="{e(title)}">{"".join(slices)}</svg>'
            + column(True) + '<svg class="absolute inset-0 w-full h-full pointer-events-none overflow-visible"></svg></div></section>' + PIE_LINES)  # fmt: skip


# 파이 이름 놓기 · 선 긋기. 이름(색 네모 가운데)을 조각 가장자리 높이에 두고, 겹치면 아래로 밀고, 넘치면 위로 당긴다(원 위아래 24px 여유).
# 한쪽에 이름이 많아 원보다 높아지면 상자를 키운다(원은 가운데 그대로). 선은 조각 가장자리 → 색 네모 앞 — 거의 수평
PIE_LINES = """<script>(function(){if(window.pieLines)return;
function place(box){var o=box.getBoundingClientRect(),pie=box.querySelector('svg[role=img]').getBoundingClientRect(),lay=box.lastElementChild;
var cx=pie.left+pie.width/2-o.left,cy=pie.top+pie.height/2-o.top,r=pie.width*0.48,H=o.height,need=0,out='';
[true,false].forEach(function(right){var it=[].slice.call(box.querySelectorAll('[data-ang]')).filter(function(d){return (Math.cos(+d.dataset.ang)>=0)==right})
.map(function(d){var li=d.closest('li'),a=+d.dataset.ang,off=d.offsetTop+d.offsetHeight/2,uo=li.parentNode.getBoundingClientRect().top-o.top;return {d:d,li:li,a:a,off:off,uo:uo,h:li.offsetHeight,t:cy+r*Math.sin(a)-off-uo}}).sort(function(x,y){return x.t-y.t});
for(var i=1;i<it.length;i++)it[i].t=Math.max(it[i].t,it[i-1].t+it[i-1].h+6);
var n=it.length;if(n){var uo=it[0].uo,over=it[n-1].t+it[n-1].h-(H-uo);if(over>0)it.forEach(function(x){x.t-=over});var under=-uo-it[0].t;if(under>0)it.forEach(function(x){x.t+=under});
need=Math.max(need,it[n-1].t+it[n-1].h-it[0].t)}
it.forEach(function(x){x.li.style.top=x.t+'px';var px=cx+r*Math.cos(x.a),py=cy+r*Math.sin(x.a),y=x.uo+x.t+x.off,q=x.d.getBoundingClientRect(),tx=right?q.left-o.left-4:q.right-o.left+4;
out+='<line x1="'+px+'" y1="'+py+'" x2="'+tx+'" y2="'+y+'" stroke="#c0c8c4" stroke-width="1"/>'})});
lay.innerHTML=out;return need>H+1?need:0}
window.pieLines=function(){document.querySelectorAll('[data-pie]').forEach(function(box){box.style.minHeight='';var need=place(box);if(need){box.style.minHeight=need+'px';place(box)}})};
addEventListener('load',pieLines);addEventListener('resize',pieLines);document.fonts&&document.fonts.ready.then(pieLines);})();pieLines&&pieLines();</script>"""


def ind_tag(kr: str | None = None, sic: str | None = None, issuer: str = "") -> str:
    """종목 이름 옆 회색 작은 글씨 「#반도체」 — 한국은 통계청 업종, 미국은 SEC 산업분류(짧은 이름을 아는 것만, 아니면 큰 업종). 상자·배경 없이(사용자 10/10)."""
    name = sources.industry_label(kr) if kr else (notes.SIC_LABEL.get(sic or "") or gurus.sector(sic, issuer))
    name = "ETF" if name and name.startswith("ETF") else name
    return f'<span class="shrink-0 text-[12px] font-normal text-outline">#{e(name)}</span>' if name else ""


TOP_LIST = 20  # 「많이 가진 순서」는 어디서나 20종목까지 — 유명 투자자·국민연금·다른 기관 모두 같게(사용자 10/10)


def issuer_name(issuer: str, ours: str | None) -> str:
    """13F 회사 이름 — 우리 종목이면 한글 이름, 아니면 대문자 줄임말을 보기 좋게(「MAGNA INTL INC」→「Magna Intl Inc」)."""
    if not ours and gurus.sector("", issuer) == "ETF(지수 펀드)":  # 「INVESCO EXCH TRADED FD TR II …」 → 「Invesco ETF」
        return issuer.split()[0].title() + " ETF"
    return ours or (issuer.title() if issuer.isupper() else issuer)


def price_chart(points: list[tuple[str, int]]) -> str:
    """토스처럼 — 종가 선 · 기간 안 최고·최저 · 1주/3달/1년. 올랐으면 빨강, 내렸으면 파랑(국내 관례).
    ⚠️ 개발 중 개인용만(PRICE_DEV) — 남에게 보이는 서버엔 그리지 않는다."""
    if len(points) < 5:
        return ""
    data = json.dumps([[d, v] for d, v in points])
    last, prev = points[-1][1], points[-2][1]
    diff = last - prev
    tone = "text-[#e0464c]" if diff > 0 else "text-[#3182f6]" if diff < 0 else "text-on-surface-variant"
    btn = "px-3 py-1 rounded-lg font-label-regular text-label-regular text-on-surface-variant"
    return ('<figure class="mb-space-lg">'
            f'<div class="flex items-baseline gap-2"><span class="font-headline-lg text-headline-lg text-on-surface">{last:,}원</span>'
            f'<span class="font-label-regular text-label-regular {tone}">어제보다 {diff:+,}원 ({diff / prev * 100:+.1f}%)</span></div>'
            '<svg id="pc" viewBox="0 0 340 170" class="w-full h-auto mt-2" role="img" aria-label="주가 흐름"></svg>'
            '<div class="flex justify-around mt-1">' + "".join(f'<button type="button" class="{btn}" data-d="{d}">{t}</button>' for d, t in ((7, "1주"), (91, "3달"), (365, "1년")))
            + '</div><p class="mt-1 font-label-micro text-label-micro text-tertiary">⚠️ 개발용 — 주가는 개인용으로만 받은 것이라 남에게 보여주면 안 돼요. 하루 늦은 종가예요.</p></figure>'
            "<script>(()=>{const P=" + data + ";const svg=document.getElementById('pc');"
            "function draw(days){const end=new Date(P[P.length-1][0]);const from=new Date(end-days*864e5);const p=P.filter(x=>new Date(x[0])>=from);"
            "const v=p.map(x=>x[1]);const hi=Math.max(...v),lo=Math.min(...v);const W=340,H=170,T=22,B=22,span=(hi-lo)||1;"
            "const X=i=>8+i*(W-16)/Math.max(p.length-1,1),Y=y=>T+(hi-y)/span*(H-T-B);"
            "const up=v[v.length-1]>=v[0],c=up?'#e0464c':'#3182f6';const hiI=v.indexOf(hi),loI=v.indexOf(lo);"
            "const lbl=(i,y,t,dy)=>{const x=Math.min(Math.max(X(i),48),W-48);return `<text x='${x}' y='${Y(y)+dy}' text-anchor='middle' font-size='11' fill='${c}'>${t} ${y.toLocaleString()}원</text>`};"
            "svg.innerHTML=`<polyline fill='none' stroke='${c}' stroke-width='2' stroke-linejoin='round' points='${p.map((x,i)=>X(i)+','+Y(x[1])).join(' ')}'/>`"
            "+`<circle cx='${X(hiI)}' cy='${Y(hi)}' r='2.5' fill='${c}'/>`+`<circle cx='${X(loI)}' cy='${Y(lo)}' r='2.5' fill='${c}'/>`"
            "+lbl(hiI,hi,'최고',-8)+lbl(loI,lo,'최저',16);"
            "document.querySelectorAll('[data-d]').forEach(b=>b.classList.toggle('bg-surface-container-high',+b.dataset.d===days));}"
            "document.querySelectorAll('[data-d]').forEach(b=>b.onclick=()=>draw(+b.dataset.d));draw(91);})();</script>")  # fmt: skip


def photo_url(uid: int, at: str | None) -> str | None:
    return f"/p/{uid}.jpg?v={quote(at)}" if at else None


def top_bar(initial: str) -> str:
    return ('<header class="fixed top-0 w-full z-50 bg-surface/90 backdrop-blur-xl pt-safe lg:border-b lg:border-surface-container-high"><div class="h-14 max-w-[480px] lg:max-w-[1200px] mx-auto px-margin lg:px-8 flex items-center justify-between"><div class="flex items-center gap-space-sm"><a href="/" class="font-display-editorial text-headline-md text-primary tracking-tight">한장</a><span class="text-on-surface-variant font-label-micro text-label-micro uppercase tracking-wider pl-space-xs">Editorial Digest</span></div><div class="flex items-center gap-space-sm">'
            + avatar(initial) + "</div></div></header>")  # fmt: skip


TABS = (("cards", "/", "newspaper", "내 종목"), ("feed", "/feed", "dynamic_feed", "피드"), ("calendar", "/calendar", "calendar_today", "캘린더"),
        ("learn", "/learn", "menu_book", "읽기 팁"), ("me", "/me", "person", "프로필"))  # fmt: skip


def bottom_nav(tab: str) -> str:
    on = "transition-colors text-primary-container font-semibold"
    off = "text-on-surface-variant hover:text-on-surface transition-colors"
    top = ('<nav aria-label="메뉴" class="hidden lg:flex fixed top-0 left-1/2 -translate-x-1/2 z-[60] h-14 items-center gap-1">'
           + "".join(f'<a {"aria-current=page " if tab == k else ""}class="px-3.5 py-1.5 rounded-full text-[14px] '
                     f'{"bg-primary/10 text-primary font-semibold" if tab == k else "text-on-surface-variant hover:text-on-surface hover:bg-surface-container"}" href="{href}">{label}</a>'
                     for k, href, icon, label in TABS)
           + "</nav>")  # fmt: skip
    return top + ('<nav class="lg:hidden fixed bottom-0 w-full z-50 pb-safe bg-surface/90 backdrop-blur-xl"><div class="max-w-[480px] mx-auto h-14 flex items-center justify-around px-1">'
            + "".join(f'<a {"aria-current=page " if tab == k else ""}class="flex flex-col items-center justify-center min-w-[44px] min-h-[44px] px-1 {on if tab == k else off}" href="{href}">'
                      f'<span class="material-symbols-outlined text-[22px]">{icon}</span><span class="font-label-micro text-label-micro mt-0.5">{label}</span></a>'
                      for k, href, icon, label in TABS)
            + "</div></nav>")  # fmt: skip


def safe_url(u: str) -> str:
    return u if u.startswith(("https://", "http://", "/learn/")) else "#"


# --- 우리가 쓴 고정 풀이 (공시 내용을 지어내지 않는다 — 낱말·공시 종류의 뜻만) ---


EVENT_EXPLAIN = {
    "BUYBACK": "회사가 자기 주식을 사들이거나 없애기로 했어요. 시중에 도는 주식 수가 줄어요.",
    "DIVIDEND": "번 돈의 일부를 주주에게 나눠 주기로 했어요.",
    "EARNINGS": "회사가 매출·이익 같은 실적을 알렸어요.",
    "MAJOR_CONTRACT": "큰 판매·공급 계약을 맺었어요.",
    "RIGHTS_ISSUE": "새 주식을 팔아 돈을 모으기로 했어요. 주식 수가 늘어요.",
    "BONUS_ISSUE": "주주에게 주식을 무상으로 더 나눠 주기로 했어요.",
    "CB_BW": "나중에 주식으로 바꿀 수 있는 채권을 냈어요. 바뀌면 주식 수가 늘어요.",
    "LAWSUIT": "소송이 걸렸거나 판결이 났어요.",
    "MA": "다른 회사와 합치거나 사업·회사를 사고팔기로 했어요.",
    "HOLDER_CHANGE": "큰 주주의 지분이 바뀌었어요.",
    "CLINICAL": "신약 임상 시험 소식이에요.",
    "TRADING_HALT": "거래가 멈추거나 관리 대상이 됐어요.",
    "SPLIT": "주식 한 주를 여러 주로 쪼개기로 했어요.",
    "REVERSE_SPLIT": "여러 주를 한 주로 합치거나 자본을 줄이기로 했어요.",
}
EVENT_SHORT = {"BUYBACK": "자사주", "DIVIDEND": "배당", "EARNINGS": "실적", "MAJOR_CONTRACT": "계약",
               "RIGHTS_ISSUE": "증자", "BONUS_ISSUE": "무상증자", "CB_BW": "전환사채", "LAWSUIT": "소송",
               "MA": "합병·인수", "HOLDER_CHANGE": "대주주", "CLINICAL": "임상", "TRADING_HALT": "거래정지·관리",
               "SPLIT": "분할", "REVERSE_SPLIT": "병합", "OTHER": "기타"}  # fmt: skip
TIPS = {  # 주주를 위한 읽기 팁 — 이 달에 가장 많은 공시 종류에 맞춰
    "BUYBACK": ("자사주 취득 공시는 소각 여부까지 함께 확인해요", "사둔 주식을 없애야(소각) 시중에 도는 주식 수가 실제로 줄어요."),
    "DIVIDEND": ("배당 공시는 기준일을 함께 확인해요", "기준일에 주식을 갖고 있어야 배당을 받아요."),
    "EARNINGS": ("실적 공시는 '잠정'인지 확인해요", "잠정 실적은 나중에 확정치와 조금 달라질 수 있어요."),
    "MAJOR_CONTRACT": ("계약 공시는 회사 매출에 비한 크기를 봐요", "같은 금액이라도 회사 크기에 따라 무게가 달라요."),
    "RIGHTS_ISSUE": ("유상증자는 모은 돈을 어디에 쓰는지 봐요", "시설 투자인지 빚 갚기인지에 따라 뜻이 달라요."),
    "CB_BW": ("전환사채는 전환 가격을 함께 봐요", "주식으로 바뀌면 주식 수가 늘어 기존 주주 몫이 묽어질 수 있어요."),
}
TIP_DEFAULT = ("공시 원문은 DART에서 누구나 볼 수 있어요", "번호를 누르면 금융감독원 전자공시 원문이 열려요.")
FACT_SHORT = {"F1": "매출", "F2": "영업이익", "F3": "부채비율", "F4": "ROE"}
# 출처 번호는 읽기를 방해하지 않게 — 본문보다 작은 회색 위첨자 (사용자 10/7). 누르면 출처 창
CITE = "align-super ml-0.5 text-[9px] leading-none font-normal hover:text-on-surface-variant transition-colors"
# 출처 번호 색 — 누가 말한 것인지 (사용자 10/9 검토: 사실과 해석을 나눠 보이게). 아래 「작성 기준」에 같은 색으로 풀이
CITE_TONE = {"F": "text-primary/70", "D": "text-secondary/80", "I": "text-secondary/80", "N": "text-outline/70"}


def short_name(name: str) -> str:
    """달력 칩용 — 「SK하이닉스」→「SK」, 「삼성전자」→「삼성」."""
    m = re.match(r"[A-Za-z&]+", name)
    return m[0] if m else name[:2]


def clean_title(title: str, code: str) -> str:
    """「[기재정정]주요사항보고서(자기주식취득결정)」 → 「자기주식취득결정 (자사주 매입)」."""
    t = re.sub(r"^\[[^\]]*\]", "", title).strip()
    t = re.sub(r"^주요사항보고서\((.+)\)$", r"\1", t)
    ko = notes.EVENT_KO.get(code, "")
    return f"{t} ({ko})" if ko and ko not in t and code != "OTHER" else t


def sentence(s: dict, seen: set | None = None) -> str:
    """문장 + 시안의 출처 단추 [F1] — 누르면 출처 창이 열린다 (모든 문장에 원문 링크, 불변식 2).
    seen = 이 노트에서 이미 보인 숫자들 — 숫자가 모두 앞에서 나온 괄호는 다시 싣지 않는다(같은 숫자 되풀이, 사용자 10/9 검토)."""
    btns = "".join(f'<button aria-label="출처 {e(r)} 보기" class="{CITE} {CITE_TONE.get(r[:1], "text-outline/70")}" onclick="toggleCitation(\'{e(r)}\')" type="button">[{e(r)}]</button>'
                   for r in s["refs"])  # fmt: skip
    text = notes.mend(s["text"])
    if seen is not None:
        def once(m):
            nums = set(re.findall(r"\d[\d,.]*", m[1]))
            if nums and nums <= seen and re.search(r"[원%]", m[1]):  # 금액·비율 괄호만 — 「(2021~2025년)」 같은 기간은 둔다
                return ""
            seen.update(nums)
            return m[0]
        text = re.sub(r"\(([^()]*\d[^()]*)\)", once, text)
    return f"{soften(text)}{btns}"


# 문단 나누기 — 근거 사실이 다루는 질문이 바뀌면 새 문단 (한 문단에 질문 하나, 사용자 10/9 검토)
TOPIC = {"F1": "실적", "F2": "실적", "F5": "실적", "F6": "흐름", "F7": "사업", "F10": "업종", "F3": "살림", "F4": "살림",
         "F8": "올해", "F9": "올해", "F11": "사업", "F12": "살림", "F13": "올해", "F14": "살림", "F15": "사업", "F16": "전망", "F17": "살림", "F18": "살림"}  # fmt: skip


def paras(sents: list[dict], seen: set) -> str:
    groups: list[list[str]] = []
    last = None
    for x in sents:
        topic = next((TOPIC[r] for r in x["refs"] if r in TOPIC), last)
        if topic != last or not groups:
            groups.append([])
        groups[-1].append(sentence(x, seen))
        last = topic
    if len(groups) == 1:
        return " ".join(groups[0])
    return "".join(f'<p class="{"mt-space-sm" if i else ""}">{" ".join(g)}</p>' for i, g in enumerate(groups))


def soften(text: str) -> str:
    """괄호 속 숫자 보조 설명은 작고 회색으로 — 「(9.0조원 · 7,921억원)(영업이익률 8.8%)」 처럼 본문을 끊지 않게 (사용자 10/9).
    붙어 있는 괄호 둘은 하나로 잇는다. 글은 바꾸지 않는다(숫자·출처 그대로)."""
    text = re.sub(r"\)\s*\(", " · ", e(text))
    return re.sub(r"\(([^()]*)\)", r'<span class="text-[12px] text-outline">(\1)</span>', text)


def cite_data(facts: list[dict]) -> dict:
    """출처 창에 넣을 실제 값 — 시안의 가짜 설명 대신 코드가 만든 사실 문장과 원문 링크."""
    out = {}
    for f in facts:
        k = f["id"][0]
        rno = re.search(r"rcpNo=(\d+)", f["url"])
        out[f["id"]] = {
            "badge": f"[{f['id']}]",
            "title": "한장 읽기 팁 · 업종별로 읽기" if f["url"].startswith("/learn/") else {"F": "금융감독원 전자공시시스템 (DART) · 사업보고서",
                      "D": "금융감독원 전자공시시스템 (DART) · 공시",
                      "I": "금융감독원 전자공시시스템 (DART) · 지분 보고"}.get(k, f"{f.get('slots', {}).get('매체', '')} 기사"),
            "body": notes.reword(f["text"]),
            "meta": f"공시접수번호: {rno[1]}" if rno else f"기사 날짜: {f.get('slots', {}).get('날짜', '')}",
            "url": safe_url(f["url"]),
        }  # fmt: skip
    return out


def metrics(fins: list[tuple]) -> str:
    """주요 실적 한눈에 보기 — 매출·영업이익을 전년과 올해 막대 둘로 (같은 잣대: 둘 중 큰 값이 꽉 찬 막대).
    fins = [(연도, 매출, 영업이익, 순이익, 자본, 부채)] 최근 해부터. 전년이 없으면 그리지 않는다."""
    if len(fins) < 2:
        return ""
    (y, *now), (py, *was) = fins[0], fins[1]
    cells = []
    for label, k in (("매출 — 판 돈", 0), ("영업이익 — 본업으로 남긴 돈", 1)):
        cur, prev = now[k], was[k]
        if cur is None or prev is None:
            continue
        top = max(abs(cur), abs(prev)) or 1
        _, _, chg = notes.trend(cur, prev)
        tone = "text-secondary" if chg.startswith("+") or chg == "흑자 전환" else "text-tertiary"
        bar = lambda v, col, yr: (f'<div class="flex items-center gap-3 mt-2.5"><span class="w-9 text-[11px] text-outline tabular-nums">{yr}</span>'
                                  f'<span class="flex-1 h-2 rounded-full bg-surface-container overflow-hidden"><span class="block h-full rounded-full {col}" style="width:{max(v, 0) / top * 100:.1f}%"></span></span>'
                                  f'<span class="w-16 text-right text-[12px] tabular-nums {"text-tertiary" if v < 0 else "text-on-surface"}">{e(notes.won(v))}</span></div>')  # fmt: skip
        cells.append(f'<div class="py-1"><div class="flex items-baseline justify-between mb-0.5"><span class="font-label-micro text-label-micro text-on-surface-variant">{e(label)}</span>'
                     f'<span class="font-label-micro text-label-micro {tone} font-semibold">{e(chg)}</span></div>'
                     + bar(prev, "bg-outline-variant", py) + bar(cur, "bg-primary", y) + "</div>")  # fmt: skip
    if not cells:
        return ""
    return ('<div class="py-6 my-space-sm border-y border-outline-variant/30"><div class="flex justify-between items-center mb-4">'
            '<span class="font-label-regular text-label-regular text-on-surface font-semibold">주요 실적 한눈에 보기</span>'
            f'<span class="font-label-micro text-label-micro text-on-surface-variant">{py}년 → {y}년</span></div>'
            f'<div class="grid grid-cols-1 sm:grid-cols-2 gap-x-12 gap-y-6">{"".join(cells)}</div></div>')  # fmt: skip


FILLED = "font-variation-settings:'FILL' 1,'wght' 600"  # 꽉 찬 검은 그림 — 톱니바퀴 같은 인포그래픽 모양


def figure(f: dict | None) -> str:
    """읽기 팁 인포그래픽 — 상자·흰 바탕 없이 큰 검은 그림과 글. flow 는 휴대폰에서 세로·넓은 화면에서 가로로 (사용자 10/10)."""
    if not f:
        return ""
    head = (f'<figure class="my-space-xl"><figcaption class="mb-5 text-[13px] font-semibold tracking-wide text-outline">{e(f["title"])}</figcaption>')
    icon = lambda name, size: f'<span class="material-symbols-outlined {size} text-on-surface leading-none" style="{FILLED}" aria-hidden="true">{e(name)}</span>'
    if f["type"] == "flow":
        n = len(f["steps"])
        parts = []
        for k, (ic, t, d) in enumerate(f["steps"]):
            parts.append(f'<li class="flex items-start gap-4 lg:flex-1 lg:flex-col lg:items-center lg:text-center lg:gap-3">{icon(ic, "text-[44px] lg:text-[56px]")}'
                         f'<span class="flex flex-col pt-1 lg:pt-0"><b class="text-[15px] leading-[22px] text-on-surface"><span class="text-primary mr-1">{k + 1}</span>{e(t)}</b>'
                         + (f'<span class="text-[13px] leading-[19px] text-on-surface-variant mt-0.5">{e(d)}</span>' if d else "") + "</span></li>")
            if k < n - 1:
                parts.append('<li aria-hidden="true" class="pl-3 lg:pl-0 lg:pt-4 text-outline-variant"><span class="material-symbols-outlined text-[22px] lg:hidden">arrow_downward</span>'
                             '<span class="material-symbols-outlined text-[26px] hidden lg:inline">arrow_forward</span></li>')
        return head + f'<ol class="flex flex-col gap-2 lg:flex-row lg:items-start lg:gap-3">{"".join(parts)}</ol></figure>'
    if f["type"] == "compare":
        (i1, c1), (i2, c2) = f["cols"]
        top = ('<div class="grid grid-cols-[28%_1fr_1fr] lg:grid-cols-[22%_1fr_1fr] gap-3 items-end pb-3"><span></span>'
               + "".join(f'<span class="flex flex-col items-start gap-1.5">{icon(ic, "text-[40px] lg:text-[52px]")}<b class="text-[15px] text-on-surface">{e(c)}</b></span>'
                         for ic, c in ((i1, c1), (i2, c2))) + "</div>")  # fmt: skip
        rows = "".join(f'<div class="grid grid-cols-[28%_1fr_1fr] lg:grid-cols-[22%_1fr_1fr] gap-3 py-2.5 text-[14px] leading-[21px]">'
                       f'<span class="text-on-surface-variant">{e(k)}</span><span class="text-on-surface">{e(x)}</span><span class="text-on-surface">{e(y)}</span></div>'
                       for k, x, y in f["rows"])  # fmt: skip
        return head + top + f'<div class="divide-y divide-surface-container-high">{rows}</div></figure>'
    if f["type"] == "equation":
        rows = "".join(f'<div class="flex items-baseline flex-wrap gap-x-2 gap-y-1 py-1"><span class="text-[15px] text-on-surface">{e(x)}</span><span class="text-[18px] text-outline">{e(op)}</span>'
                       f'<span class="text-[15px] text-on-surface">{e(y)}</span><span class="text-[18px] text-outline">=</span><b class="text-[20px] text-primary">{e(z)}</b></div>'
                       for x, op, y, z in f["rows"])  # fmt: skip
        return (head + f'<div class="flex items-center gap-5">{icon("calculate", "text-[56px] lg:text-[72px]")}'
                f'<div class="grid grid-cols-1 lg:grid-cols-2 gap-x-10 gap-y-1 flex-1">{rows}</div></div></figure>')
    note = f'<p class="mt-3 text-[13px] leading-[19px] text-on-surface-variant">{e(f["note"])}</p>' if f.get("note") else ""
    if f["type"] == "cards":  # 그림 카드 — 휴대폰 두 칸, 넓은 화면 네 칸
        items = "".join(f'<div class="flex flex-col gap-2">{icon(ic, "text-[40px] lg:text-[48px]")}<b class="text-[15px] leading-[21px] text-on-surface">{e(t)}</b>'
                        f'<span class="text-[13px] leading-[19px] text-on-surface-variant">{e(d)}</span></div>' for ic, t, d in f["items"])  # fmt: skip
        return head + f'<div class="grid grid-cols-2 lg:grid-cols-4 gap-x-5 gap-y-7">{items}</div>{note}</figure>'
    if f["type"] == "ladder":  # 먼저 받는 차례 — 왼쪽 맞춤 + 아래 화살표, 번호·배경·들여쓰기 없이 (사용자 10/10)
        arrow = '<span class="material-symbols-outlined text-[22px] text-outline-variant pl-2" aria-hidden="true">arrow_downward</span>'
        rows = arrow.join(f'<div class="flex items-center gap-3">{icon(ic, "text-[36px] lg:text-[44px]")}'
                          f'<span class="flex flex-col min-w-0"><b class="text-[15px] leading-[22px] text-on-surface">{e(t)}</b>'
                          f'<span class="text-[13px] leading-[19px] text-on-surface-variant">{e(d)}</span></span></div>'
                          for ic, t, d in f["steps"])  # fmt: skip
        return head + f'<div class="flex flex-col gap-1">{rows}</div>{note}</figure>'
    if f["type"] == "timeline":  # 때 — 휴대폰 세로 줄, 넓은 화면 가로 줄
        pts = "".join(f'<li class="relative flex gap-4 pb-6 last:pb-0 lg:flex-1 lg:flex-col lg:items-center lg:text-center lg:pb-0 lg:gap-2">'
                      f'<span class="w-14 shrink-0 pt-1 text-[13px] font-bold text-primary lg:w-auto lg:pt-0">{e(w)}</span>'
                      f'<span class="relative z-10 w-3.5 h-3.5 mt-1.5 shrink-0 rounded-full bg-primary ring-4 ring-surface lg:mt-0"></span>'
                      f'<span class="flex flex-col items-start lg:items-center gap-1">{icon(ic, "text-[34px] lg:text-[44px]")}<b class="text-[14px] text-on-surface">{e(t)}</b>'
                      f'<span class="text-[12px] leading-[17px] text-on-surface-variant">{e(d)}</span></span></li>' for w, ic, t, d in f["points"])  # fmt: skip
        line = '<span aria-hidden="true" class="absolute left-[78px] top-2 bottom-2 w-px bg-primary/30 lg:left-0 lg:right-0 lg:top-[38px] lg:bottom-auto lg:w-auto lg:h-px"></span>'
        return head + f'<ol class="relative flex flex-col lg:flex-row lg:gap-4">{line}{pts}</ol>{note}</figure>'
    if f["type"] == "bars":  # 막대 — 가장 큰 값을 꽉 찬 길이로
        top = max(v for _, _, v in f["items"]) or 1
        rows = "".join(f'<div class="flex items-center gap-3 py-1.5">{icon(ic, "text-[30px]")}<span class="w-20 shrink-0 text-[14px] text-on-surface">{e(t)}</span>'
                       f'<span class="flex-1 h-3 rounded-full bg-surface-container overflow-hidden"><span class="block h-full rounded-full bg-primary" style="width:{max(v / top * 100, 3):.0f}%"></span></span>'
                       f'<b class="w-12 text-right text-[14px] tabular-nums text-on-surface">{v}{e(f.get("unit", ""))}</b></div>' for ic, t, v in f["items"])  # fmt: skip
        return head + rows + note + "</figure>"
    if f["type"] == "lines":  # 꺾은선 — 같은 출발점에서 갈라지는 모양
        xs, series = f["x"], f["series"]
        vals = [v for _, ys in series for v in ys]
        lo, hi = min(vals) - 5, max(vals) + 5
        w, h, pad = 320, 150, 28
        px = lambda k: pad + k * (w - 2 * pad) / (len(xs) - 1)
        py = lambda v: 12 + (hi - v) / (hi - lo) * (h - 36)
        cols = ("#154539", "#F4806A")
        top = [max(ys[k] for _, ys in series) for k in range(len(xs))]  # 높은 쪽 숫자는 위, 낮은 쪽은 아래 — 겹치지 않게
        first = [next(ys for _, ys in series if ys[k] == top[k]) for k in range(len(xs))]  # 같은 값은 한 번만
        lines = "".join(f'<polyline fill="none" stroke="{c}" stroke-width="3" stroke-linejoin="round" points="{" ".join(f"{px(k):.1f},{py(v):.1f}" for k, v in enumerate(ys))}"/>'
                        + "".join(f'<circle cx="{px(k):.1f}" cy="{py(v):.1f}" r="4" fill="{c}"/><text x="{px(k):.1f}" y="{py(v) + (18 if v < top[k] else -9):.1f}" text-anchor="middle" font-size="12" font-weight="700" fill="{c}">{v}</text>'
                                  for k, v in enumerate(ys) if v != top[k] or ys is first[k]) for (_, ys), c in zip(series, cols))  # fmt: skip
        ticks = "".join(f'<text x="{px(k):.1f}" y="{h - 4}" text-anchor="middle" font-size="11" fill="#717975">{e(x)}</text>' for k, x in enumerate(xs))
        legend = "".join(f'<span class="flex items-center gap-1.5"><span class="w-4 h-1 rounded-full" style="background:{c}"></span>{e(n)}</span>' for (n, _), c in zip(series, cols))
        return (head + f'<div class="flex gap-4 mb-2 text-[13px] text-on-surface">{legend}</div>'
                f'<svg viewBox="0 0 {w} {h}" class="w-full max-w-[520px]" role="img" aria-label="{e(f["title"])}">{lines}{ticks}</svg>{note}</figure>')
    if f["type"] == "stack":  # 나눠 쌓은 막대 — 전체 하나를 몫으로 나눈다
        total = sum(v for _, v, _ in f["parts"]) or 1
        bar = "".join(f'<span class="h-full flex items-center justify-center text-[13px] font-bold text-on-primary" style="width:{v / total * 100:.0f}%;background:{c}">{v}</span>' for _, v, c in f["parts"])
        keys = "".join(f'<span class="flex items-center gap-1.5"><span class="w-3 h-3 rounded-sm" style="background:{c}"></span>{e(t)}</span>' for t, _, c in f["parts"])
        return (head + f'<div class="flex items-center gap-4">{icon("account_balance", "text-[44px] lg:text-[56px]")}<div class="flex-1 flex flex-col gap-2">'
                f'<b class="text-[14px] text-on-surface">{e(f["total"])}</b><div class="h-9 w-full rounded-lg overflow-hidden flex">{bar}</div>'
                f'<div class="flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-on-surface-variant">{keys}</div></div></div>{note}</figure>')
    return ""


def chapter(title: str, body: str, extra: str = "") -> str:
    return ('<article class="mb-12 flex flex-col gap-space-sm"><div class="flex items-center gap-2"><span class="w-2 h-2 rounded-full bg-primary"></span>'
            f'<h3 class="font-headline-md text-headline-md text-on-surface">{e(title)}</h3></div>'
            f'<div class="font-body-reading text-body-reading text-on-surface leading-loose">{body}</div>{extra}</article>')  # fmt: skip


def index_chart(got: dict) -> str:
    """한국·미국 주가지수 선 그림 — 세로는 로그 눈금(같은 % 변화가 같은 높이). 한국 자료가 시작된 달부터."""
    import math

    start = got["한국"]["from"]
    lines = {n: [(d, v) for d, v in g["series"] if d >= start] for n, g in got.items()}
    ds = sorted({d for pts in lines.values() for d, _ in pts})
    lo, hi = (f(math.log(v) for pts in lines.values() for _, v in pts) for f in (min, max))
    W, H, P = 340, 180, 24

    def xy(d, v):
        return f"{P + (ds.index(d) / (len(ds) - 1)) * (W - P - 4):.1f},{H - 18 - (math.log(v) - lo) / (hi - lo) * (H - 30):.1f}"

    # 실선 + 색으로만 구분 — 점선은 끊겨 보이고, 화면 폭에 따라 굵기가 변하지 않게 non-scaling-stroke (사용자 10/9)
    color = {"한국": "#154539", "미국": "#b4532a"}
    polys = "".join(f'<polyline stroke="{color.get(n, "#717975")}" fill="none" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke" points="{" ".join(xy(d, v) for d, v in pts)}"/>'
                    for n, pts in lines.items())  # fmt: skip
    years = sorted({d[:4] for d in ds if d[:4].endswith(("0", "5")) and d[5:7] == "01"})
    ticks = "".join(f'<text x="{xy(f"{y}-01-01", math.exp(lo)).split(",")[0]}" y="{H - 4}" font-size="9" text-anchor="middle" fill="currentColor" class="text-outline">{y}</text>'
                    for y in years if f"{y}-01-01" in ds and int(y) % 10 == 0)  # fmt: skip
    legend = " ".join(f'<span class="inline-flex items-center gap-1"><span class="w-4 h-[2px] rounded-full" style="background:{color.get(n, "#717975")}"></span>{e(n)}</span>' for n in lines)
    return ('<figure class="my-space-md max-w-[560px]"><figcaption class="font-label-regular text-label-regular text-on-surface font-semibold mb-1">주가지수 흐름 (로그 눈금)</figcaption>'
            f'<svg viewBox="0 0 {W} {H}" class="w-full h-auto" role="img" aria-label="한국과 미국 주가지수 흐름">{polys}{ticks}</svg>'
            f'<div class="flex gap-3 font-label-micro text-label-micro text-on-surface-variant">{legend}</div></figure>')  # fmt: skip


# 금리 다섯 가지의 색 — 모두 실선, 색으로만 구분 (점선은 끊겨 보인다, 사용자 10/9)
RATE_LOOK = {"기준금리": "#9aa19d", "국고채 3년": "#154539", "국고채 10년": "#5f9e88", "회사채 AA-": "#c8902e", "회사채 BBB-": "#a33a24"}


def rate_ladder(now: dict, month: str) -> str:
    """그달 금리 사다리 — 낮은 것부터 막대. 신용·기간에 따라 이자가 어떻게 달라지는지 한눈에."""
    top = max(now.values())
    rows = "".join(f'<div class="flex items-center gap-2 py-1"><span class="w-20 font-label-regular text-label-regular text-on-surface">{e(n)}</span>'
                   f'<div class="flex-1 h-2.5 rounded-full bg-surface-container overflow-hidden"><div class="h-full rounded-full" style="width:{v / top * 100:.0f}%;background:{RATE_LOOK[n]}"></div></div>'
                   f'<span class="w-12 text-right font-label-regular text-label-regular text-on-surface font-semibold">{v:.2f}%</span></div>'
                   for n, v in sorted(now.items(), key=lambda x: x[1]))  # fmt: skip
    return (f'<figure class="my-space-md max-w-[560px]"><figcaption class="font-label-regular text-label-regular text-on-surface font-semibold mb-1">{int(month[:4])}년 {int(month[5:7])}월 금리 (연, 월평균)</figcaption>'
            f'{rows}<p class="font-label-micro text-label-micro text-outline mt-1">자료: 한국은행 ECOS</p></figure>')


def rate_chart(got: dict) -> str:
    """금리 다섯 가지의 흐름 — 세로는 % 그대로, 달마다."""
    ds = sorted({d for pts in got.values() for d, _ in pts})
    hi = max(v for pts in got.values() for _, v in pts)
    W, H, P = 340, 190, 24
    pos = {d: i for i, d in enumerate(ds)}

    def xy(d, v):
        return f"{P + pos[d] / (len(ds) - 1) * (W - P - 4):.1f},{H - 18 - v / hi * (H - 30):.1f}"

    polys = "".join(f'<polyline stroke="{RATE_LOOK[n]}" fill="none" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke" points="{" ".join(xy(d, v) for d, v in pts)}"/>' for n, pts in got.items())
    grid = "".join(f'<text x="2" y="{H - 18 - y / hi * (H - 30) + 3:.1f}" font-size="9" fill="currentColor" class="text-outline">{y}%</text>'
                   for y in range(0, int(hi) + 1, 5))  # fmt: skip
    ticks = "".join(f'<text x="{xy(d, 0).split(",")[0]}" y="{H - 4}" font-size="9" text-anchor="middle" fill="currentColor" class="text-outline">{d[:4]}</text>'
                    for d in ds if d[5:7] == "01" and int(d[:4]) % 5 == 0)  # fmt: skip
    legend = " ".join(f'<span class="inline-flex items-center gap-1"><span class="w-4 h-[2px] rounded-full" style="background:{RATE_LOOK[n]}"></span>{e(n)}</span>' for n in got)
    return ('<figure class="my-space-md max-w-[560px]"><figcaption class="font-label-regular text-label-regular text-on-surface font-semibold mb-1">금리 흐름 (연 %, 월평균)</figcaption>'
            f'<svg viewBox="0 0 {W} {H}" class="w-full h-auto" role="img" aria-label="기준금리·국고채·회사채 금리 흐름">{grid}{polys}{ticks}</svg>'
            f'<div class="flex flex-wrap gap-x-3 gap-y-1 font-label-micro text-label-micro text-on-surface-variant">{legend}</div>'
            '<p class="font-label-micro text-label-micro text-outline mt-1">자료: 한국은행 ECOS</p></figure>')


def loss_bars(got: dict) -> str:
    """보유 기간별 「손해였던 비율」 막대 — 한국·미국 나란히."""
    labels = [r["label"] for r in got["한국"]["rows"]]
    color = {"한국": "bg-primary", "미국": "bg-secondary"}
    rows = []
    for lab in labels:
        cells = []
        for n, g in got.items():
            r = next((x for x in g["rows"] if x["label"] == lab), None)
            if r:
                w = round(r["loss"] * 100)
                cells.append(f'<div class="flex items-center gap-2"><span class="w-7 font-label-micro text-label-micro text-outline">{e(n)}</span>'
                             f'<div class="flex-1 h-2 rounded-full bg-surface-container overflow-hidden"><div class="{color.get(n, "bg-outline")} h-full rounded-full" style="width:{w}%"></div></div>'
                             f'<span class="w-9 text-right font-label-micro text-label-micro text-on-surface">{w}%</span></div>')  # fmt: skip
        rows.append(f'<div class="flex items-start gap-3 py-1.5"><span class="w-10 pt-0.5 font-label-regular text-label-regular text-on-surface font-semibold">{e(lab)}</span><div class="flex-1 flex flex-col gap-1">{"".join(cells)}</div></div>')
    return ('<figure class="my-space-md"><figcaption class="font-label-regular text-label-regular text-on-surface font-semibold">이만큼 들고 있었다면 — 손해였던 비율</figcaption>'
            '<p class="font-label-micro text-label-micro text-on-surface-variant mb-1">아무 달에나 사서 그 기간 뒤에 팔았다고 치고, 손해였던 경우를 셌어요.</p>'
            + "".join(rows)
            + '<p class="font-label-micro text-label-micro text-outline mt-1">자료: OECD 주가지수(월평균, 2015=100) · 한국은행 ECOS에서 받음. 배당은 빠져 있고, 하루하루 출렁임은 이보다 커요.</p></figure>')  # fmt: skip


def md(made: str) -> str:
    """「2026-10-08T07:00」 → 「10월 8일」 — 노트를 쓴(고친) 날."""
    return f"{int(made[5:7])}월 {int(made[8:10])}일" if re.match(r"\d{4}-\d{2}-\d{2}", made or "") else ""


NEWS_TITLES = ("최근 소식", "이번 주 소식", "요즘 무슨")  # 공시·소식 절 — 새 이름과 옛 노트 이름


def redone(week: str, made: str) -> str:
    """주 중간에 다시 쓴 노트면 「 · 10월 8일 고침」 — 월요일에 쓴 그대로면 빈 글."""
    d = date.fromisoformat(made[:10]) if re.match(r"\d{4}-\d{2}-\d{2}", made or "") else None
    return f" · {d.month}월 {d.day}일 고침" if d and d.isoformat() > week else ""


# 노트 한 줄 요약 위아래 선 — 신문 괘선처럼 굵은 실선 + 점선, 주 색 초록 (사용자 10/9)
RULE = '<div class="border-t-2 border-primary"></div><div class="mt-[3px] border-t-2 border-dotted border-primary"></div>'
RULE_FLIP = '<div class="border-t-2 border-dotted border-primary"></div><div class="mt-[3px] border-t-2 border-primary"></div>'


def guru_face(key: str, size: str = "w-10 h-10") -> str:
    """유명 투자자 얼굴 — 위키미디어 공용의 자유 이용 사진(static/people, 출처는 SOURCES.txt). 없으면 회사 로고·글자 동그라미."""
    name, _, _, home = gurus.GURUS[key]
    if key not in PEOPLE:
        return logo(name, home, size)
    who, lic, _ = PEOPLE[key]
    return (f'<span class="{size} shrink-0 rounded-full overflow-hidden bg-surface-container border border-outline-variant/40">'
            f'<img alt="{e(name)}" title="사진: {e(who)} · {e(lic)} · 위키미디어 공용" class="w-full h-full object-cover object-[50%_20%]" '
            f'loading="lazy" src="/static/people/{key}.jpg"></span>')  # fmt: skip


def people_credits() -> dict[str, tuple[str, str, str]]:
    f = STATIC / "people" / "SOURCES.txt"
    rows = [ln.split("|") for ln in f.read_text(encoding="utf-8").splitlines() if ln and not ln.startswith("#")] if f.exists() else []
    return {k: (who, lic, url) for k, who, lic, url in rows}


PEOPLE = people_credits()  # 키 → (찍은 사람, 이용 허락, 원본 주소)
BOOK_FACE = {"book-graham": "graham", "book-buffett": "buffett", "book-bogle": "bogle", "book-marks": "marks"}  # 책 글 → 지은이 사진 (자유 이용 사진이 없는 린치·말킬·피셔·하우절은 없음)


def book_face(slug: str) -> tuple[str, str]:
    """책에서 배우기 — (글 첫머리에 띄워 글이 옆으로 흐르는 지은이 얼굴, 맨 밑 출처 한 줄) (사용자 10/10). 사진이 없으면 둘 다 빈 글."""
    key = BOOK_FACE.get(slug)
    if key not in PEOPLE:
        return "", ""
    who, lic, url = PEOPLE[key]
    return (f'<img alt="" class="float-left w-20 h-20 lg:w-24 lg:h-24 mr-4 mb-2 mt-1 rounded-full object-cover object-[50%_20%] bg-surface-container" src="/static/people/{key}.jpg">',
            f'<a class="block mt-space-md text-[12px] text-outline hover:underline" href="{e(url)}" target="_blank" rel="noopener">사진: {e(who)} · {e(lic)} · 위키미디어 공용</a>')  # fmt: skip


def kdate(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.year}년 {d.month}월 {d.day}일"


def owners_block(owners: tuple | None) -> str:
    """노트 맨 밑 — 이 종목을 가진 유명 투자자(미국 13F)·기관(국내 5% 보고). 누르면 그 투자자의 포트폴리오로."""
    if not owners or not owners[2]:
        return ""
    title, note, rows = owners
    items = "".join(
        f'<a href="{e(href)}" class="py-3 flex items-center gap-3">{face}'
        f'<span class="flex flex-col min-w-0 flex-1"><span class="text-[15px] font-semibold text-on-surface truncate">{e(name)}</span>'
        f'<span class="text-[12px] text-on-surface-variant">{e(detail)}</span></span>'
        '<span class="material-symbols-outlined text-outline text-[18px]">chevron_right</span></a>' for name, href, face, detail in rows)  # fmt: skip
    return ('<section class="mb-12 flex flex-col gap-space-sm"><div class="flex items-center gap-2"><span class="w-2 h-2 rounded-full bg-primary"></span>'
            f'<h3 class="font-headline-md text-headline-md text-on-surface">{e(title)}</h3></div>'
            f'<div class="flex flex-col divide-y divide-surface-container-high/70">{items}</div>'
            f'<p class="font-label-micro text-label-micro text-outline leading-normal">{e(note)}</p></section>')  # fmt: skip


def render_note(name: str, ticker: str, week: str, body: dict, writer: str, facts: list[dict] | None = None,
                industry: str | None = None, initial: str = "", survey: str = "", made: str = "", homepage: str | None = None,
                stats: tuple[int, int, bool] = (0, 0, False), regram: str = "",
                prices: list | None = None, report: dict | None = None) -> str:
    """report = {"divs": [(연도, 주당배당, 총액, 배당성향)], "biz": 요약, "rno": 사업보고서}."""
    report = report or {}
    """stats = (이 주 노트를 연 횟수, 좋아요 수, 내가 눌렀나)."""
    facts = facts or []
    head = ('<header class="fixed top-0 w-full z-50 bg-surface/90 backdrop-blur-xl pt-safe"><div class="h-14 max-w-[480px] lg:max-w-[760px] mx-auto px-margin flex items-center justify-between"><div class="flex items-center gap-space-sm"><button class="w-11 h-11 flex items-center justify-center text-on-surface hover:text-primary transition-colors -ml-space-xs" onclick="location.href=\'/\'"><span class="material-symbols-outlined text-[22px]">arrow_back</span></button><h1 class="font-headline-sm text-headline-sm text-on-surface tracking-tight truncate max-w-[200px]">Note</h1></div><div class="flex items-center gap-space-sm">'
            + avatar(initial) + '</div></div></header>')  # fmt: skip
    parts = [
        # 머리 — 로고·이름 한 줄, 업종 · 날짜 · 읽음 한 줄 (글자를 줄였다, 사용자 10/8)
        f'<header class="mt-space-sm mb-space-lg"><div class="flex items-center gap-2.5">{logo(name, homepage, "w-10 h-10")}'
        f'<h2 class="font-display-editorial text-display-editorial text-on-surface font-semibold tracking-tight">{e(name)}</h2></div>'
        f'<p class="mt-1.5 flex items-center flex-wrap gap-x-2 gap-y-1 text-[12px] text-outline">{industry_chip(industry)}<span>{e(" · ".join(x for x in (md(made), f"읽음 {stats[0]:,}") if x))}</span></p></header>',
        price_chart(prices) if prices else "",
        f'<aside class="my-space-xl lg:my-10 text-center">{RULE}<p class="py-space-lg px-space-md font-body-reading-strong font-bold text-[18px] leading-[30px] lg:text-[20px] lg:leading-[34px] text-primary">{e(notes.mend(body["headline"]))}</p>{RULE_FLIP}</aside>',
    ]  # fmt: skip
    seen: set = set()  # 이 노트에서 이미 보인 숫자 — 뒤에서 같은 괄호를 되풀이하지 않게
    if body.get("summary"):
        parts.append('<section class="mb-12 pl-space-md py-1 border-l-2 border-primary/60"><div class="flex items-center gap-1.5 mb-1"><span class="material-symbols-outlined text-primary text-[18px]">auto_stories</span><span class="font-label-micro text-label-micro uppercase tracking-wider text-primary font-bold">한 장 요약</span></div>'
                     f'<p class="font-body-reading text-body-reading text-on-surface leading-relaxed">{" ".join(sentence(s, seen) for s in body["summary"])}</p></section>')  # fmt: skip
    parts.append(business_block(report.get("biz"), report.get("rno")))
    nd = sum(f["id"][0] == "D" for f in facts)
    good_d, bad_d = sum(f["id"][0] == "D" and f["tone"] == 1 for f in facts), sum(f["id"][0] == "D" and f["tone"] == -1 for f in facts)
    for sec in body["sections"]:
        text = paras(sec["sentences"], seen)
        extra = ""
        if sec["title"].startswith("회사 사정"):
            extra = metrics(report.get("fins") or []) + money_blocks(report.get("fin"), report.get("mid"))
        elif sec["title"].startswith(NEWS_TITLES):  # 「이번 주 소식」(공시+소식) · 옛 노트의 「요즘 무슨 일이 있었나요?」
            right = (f"좋게 볼 점 {good_d}" + (f" · 주의해서 볼 점 {bad_d}" if bad_d else "")) if good_d or bad_d else "분류 완료"
            extra = ('<div class="py-space-sm flex items-center justify-between border-t border-outline-variant/30 mt-space-xs"><div class="flex items-center gap-space-sm"><span class="material-symbols-outlined text-secondary text-[18px]">assignment_turned_in</span><div class="flex items-center gap-2">'
                     f'<span class="font-label-regular text-label-regular text-on-surface font-medium">최근 주요 공시 {nd}건 집계</span><span class="font-label-micro text-label-micro text-on-surface-variant">· DART 기준 자동 분류</span></div></div>'
                     f'<span class="font-label-micro text-label-micro text-secondary font-semibold">{e(right)}</span></div>'
                     + (('<div class="pt-space-sm pb-1 flex flex-col gap-1.5"><div class="font-label-micro text-label-micro text-outline font-semibold uppercase">언론 키워드 흐름</div><div class="flex flex-wrap gap-2">'
                         + "".join(f'<span class="py-0.5 text-on-surface-variant text-label-micro font-label-micro">{e(k)}</span>' for k in body["keywords"]) + "</div></div>")
                        if body.get("keywords") else "")
                     + '<p class="font-label-micro text-label-micro text-outline leading-normal">소식은 회사 뉴스룸이 RSS 로 내보낸 제목·요약문만 보고 한장이 새로 쓴 글이에요. 기사 본문은 받지 않아요. 번호를 누르면 원문이 열려요.</p>'
                     # 언론 기사는 쓸 권리가 없어 싣지 않는다(data-rights §5.2) — 대신 검색 결과로 가는 길만. 데이터를 가져오지 않는 링크는 복제·전송이 아니다
                     + f'<a class="font-label-regular text-label-regular text-primary underline" target="_blank" rel="noopener" href="https://search.naver.com/search.naver?where=news&amp;sort=1&amp;query={quote(name)}">'
                     f'{e(name)} 최근 뉴스 찾아보기 (네이버 뉴스 검색으로 이동) →</a>')  # fmt: skip
        elif sec["title"].startswith("임원·큰손"):
            extra = ('<p class="font-label-micro text-label-micro text-outline leading-normal">임원 보고에는 회사에서 받은 주식(보상)도 들어가요. '
                     "누가 늘리고 줄였는지는 사실일 뿐, 따라 사고팔라는 뜻이 아니에요.</p>")  # fmt: skip
        parts.append(chapter(sec["title"], text, extra))
        if sec["title"].startswith(NEWS_TITLES):
            parts.append(dividend_block(report.get("divs", []), report.get("fin"), report.get("buys")))
    if not any(s["title"].startswith(NEWS_TITLES) for s in body["sections"]):
        parts.append(dividend_block(report.get("divs", []), report.get("fin"), report.get("buys")))
    parts.append(risk_block(report.get("biz"), report.get("fins")))

    def filled(key):  # 옛 노트의 「분류된 것 없음」 자리 채움 문장도 빈 칸으로 본다
        return [] if body.get(f"{key}_title") == "분류된 것 없음" else body.get(key) or []

    if filled("good") or filled("concern"):
        def side(label, title, items, bar, chip, ink):
            if not items:
                return ""
            return (f'<div class="pl-space-md py-1 border-l-2 {bar} flex flex-col gap-1"><div class="flex items-center gap-1.5">'
                    f'<span class="px-2 py-0.5 rounded text-label-micro font-label-micro font-semibold {chip}">{label}</span>'
                    f'<span class="font-label-regular text-label-regular {ink} font-semibold">{e(title)}</span></div>'
                    f'<p class="font-body-reading text-body-reading text-on-surface leading-relaxed">{" ".join(sentence(s, seen) for s in items)}</p></div>')  # fmt: skip
        parts.append('<section class="mb-12 flex flex-col gap-space-md"><div class="flex items-center gap-2"><span class="w-2 h-2 rounded-full bg-primary"></span><h3 class="font-headline-md text-headline-md text-on-surface">좋게 볼 점과 주의해서 볼 점</h3></div>'
                     + side("좋게 볼 점", body.get("good_title", ""), filled("good"), "border-secondary/60", "bg-secondary-container text-on-secondary-container", "text-secondary")
                     + side("주의해서 볼 점", body.get("concern_title", ""), filled("concern"), "border-tertiary/60", "bg-tertiary-fixed text-on-tertiary-fixed-variant", "text-tertiary")
                     + '<span class="font-label-micro text-label-micro text-outline leading-normal pt-1">좋게 볼 점·주의해서 볼 점은 코드가 정한 기준으로 나눴어요. 좋고 나쁨의 결론이 아니라 살펴볼 거리예요. 기준은 매출·영업이익 증감, 부채비율, ROE, 공시 종류. <a class="underline" href="/method">기준 보기</a></span></section>')  # fmt: skip
    src = "기사·공시·재무" if any(f["id"][0] == "N" for f in facts) else "공시·재무"
    how = (f"{src}에서 코드가 뽑은 사실을 바탕으로 AI가 문장을 다듬었어요. 숫자는 코드가 원문과 대조했어요."
           if writer.startswith("llm") else f"{src}에서 코드가 뽑은 사실을 그대로 옮겼어요.")  # fmt: skip
    if any("sec.gov" in f.get("url", "") for f in facts):  # 미국 회사 — 원문은 SEC, 금액은 달러(원화는 한국은행 환율로 코드가 곱함)
        how += " 미국 회사라 원문은 미국 증권거래위원회(SEC) 공시예요. 금액은 달러가 먼저, 원화는 한국은행 환율로 계산해 괄호에 적었어요."
    views, likes, liked = stats
    faces = "".join('<span class="w-7 h-7 rounded-full bg-surface-container-high border-2 border-surface flex items-end justify-center overflow-hidden -ml-2 first:ml-0">'
                    '<span class="material-symbols-outlined text-outline text-[22px] translate-y-1" style="font-variation-settings: \'FILL\' 1;">person</span></span>'
                    for _ in range(min(likes, 3)))  # fmt: skip  누가 눌렀는지는 보여주지 않는다 — 모양만
    parts.append(f'<div class="mb-space-lg flex items-center justify-end gap-space-md"><form method="post" action="/like" class="flex items-center gap-space-sm"><input type="hidden" name="t" value="{e(ticker)}"><input type="hidden" name="w" value="{e(week)}">'
                 f'<button type="submit" aria-pressed="{"true" if liked else "false"}" aria-label="좋아요{" 취소" if liked else ""}" class="w-10 h-10 rounded-full flex items-center justify-center border {"border-tertiary/40 bg-tertiary-fixed/50" if liked else "border-outline-variant/60"} transition-colors">'
                 f'<span class="material-symbols-outlined text-[20px] {"text-tertiary" if liked else "text-outline"}" style="font-variation-settings: \'FILL\' {1 if liked else 0};">favorite</span></button>'
                 f'<span class="flex items-center">{faces}</span><span class="font-label-regular text-label-regular text-on-surface-variant font-semibold">좋아요 {likes:,}개</span></form>{regram}</div>')  # fmt: skip
    parts.append(owners_block(report.get("owners")))
    parts.append(survey)
    parts.append('<footer class="pt-space-lg pb-space-lg mt-space-sm border-t border-outline-variant/40 flex flex-col gap-space-sm"><div class="flex items-center gap-1.5 text-on-surface font-headline-sm text-headline-sm font-semibold"><span class="material-symbols-outlined text-primary text-[20px]">verified</span><span class="">작성 기준 및 검증 안내</span></div>'
                 f'<p class="font-body-compact text-body-compact text-on-surface-variant leading-relaxed">{how} 번호 색은 누가 말한 것인지 알려줘요. <span class="text-primary">[F]</span> 재무제표로 한장이 계산 · <span class="text-secondary">[D]·[I]</span> 회사·주주가 낸 공시 · <span class="text-outline">[N]</span> 언론 기사. 작은 번호를 누르면 금융감독원 전자공시(DART){"나 기사" if src.startswith("기사") else ""} 원문이 열려요. <a class="text-primary underline" href="/method">계산 방법</a></p>'
                 '<div class="pt-1"><p class="font-label-regular text-label-regular text-on-surface leading-relaxed font-medium">사라·팔아라는 의견도, 목표주가도, 앞으로의 예측도 없어요. 투자 판단은 본인이 해요.</p></div></footer>')  # fmt: skip
    dialog = ('<div class="fixed inset-0 z-50 bg-on-surface/40 backdrop-blur-sm hidden items-end justify-center px-margin pb-6" id="citation-dialog" onclick="closeCitation(event)"><div class="bg-surface-container-lowest w-full max-w-[440px] rounded-2xl p-space-lg shadow-xl flex flex-col gap-space-sm" onclick="event.stopPropagation()"><div class="flex items-center justify-between"><div class="flex items-center gap-2"><span class="px-2 py-0.5 rounded font-citation-ref text-citation-ref bg-primary-fixed text-on-primary-fixed font-bold" id="citation-badge"></span><span class="font-label-regular text-label-regular font-bold text-on-surface" id="citation-title"></span></div><button class="w-8 h-8 rounded-full flex items-center justify-center text-on-surface-variant hover:bg-surface-container" onclick="hideCitation()" type="button"><span class="material-symbols-outlined text-[20px]">close</span></button></div><div class="font-body-compact text-body-compact text-on-surface-variant leading-relaxed" id="citation-body"></div><div class="flex items-center justify-between pt-2"><span class="font-label-micro text-label-micro text-outline font-mono" id="citation-meta"></span><a class="inline-flex items-center gap-1 font-label-regular text-label-regular text-primary font-semibold hover:underline" href="#" id="citation-link" rel="noopener noreferrer" target="_blank">원문 확인<span class="material-symbols-outlined text-[14px]">open_in_new</span></a></div></div></div>'
              # JSON 안의 </script> 를 막으려고 < 를 < 로
              "<script>const citations = " + json.dumps(cite_data(facts), ensure_ascii=False).replace("<", "\\u003c") + ";"
              "function toggleCitation(id){const d=citations[id];if(!d)return;document.getElementById('citation-badge').innerText=d.badge;document.getElementById('citation-title').innerText=d.title;document.getElementById('citation-body').innerText=d.body;document.getElementById('citation-meta').innerText=d.meta;document.getElementById('citation-link').href=d.url;const g=document.getElementById('citation-dialog');g.classList.remove('hidden');g.classList.add('flex');}"
              "function hideCitation(){const g=document.getElementById('citation-dialog');g.classList.add('hidden');g.classList.remove('flex');}"
              "function closeCitation(ev){if(ev.target.id==='citation-dialog')hideCitation();}</script>")  # fmt: skip
    inner = (head + '<main class="flex flex-col relative w-full max-w-[480px] lg:max-w-[760px] mx-auto pt-14 pb-safe bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-space-xl">'
             + "".join(parts) + dialog + "</div></main>")  # fmt: skip
    if report.get("us"):
        inner = us_words(inner)
    return page(name, "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)


US_WORDS = (  # 노트 화면의 국내(DART) 안내 → 미국(SEC) 안내. 노트 본문(AI 글)은 건드리지 않는다
    (re.compile(r"회사가 낸 \d+년 사업보고서를 요약했어요"), "회사가 SEC 에 낸 최근 연차 보고서(10-K)를 요약했어요"),
    (re.compile(r"· DART 기준 자동 분류"), "· SEC 8-K 번호로 자동 분류"),
    (re.compile(r"임원 보고에는 회사에서 받은 주식\(보상\)도 들어가요\. 누가 늘리고 줄였는지는"),
     "미국은 시장에서 실제로 사고판 거래만 셌어요(회사에서 받은 보상 주식은 뺐어요). 누가 사고팔았는지는"),
    (re.compile(r"회사가 사업보고서에 스스로 적은 위험"), "회사가 연차 보고서(10-K)에 스스로 적은 위험"),
    (re.compile(r"금융감독원 전자공시\(DART\) 원문이 열려요"), "미국 증권거래위원회(SEC) 공시 원문이 열려요"),
    (re.compile(r"소식은 회사 뉴스룸이 RSS 로 내보낸 제목·요약문만 보고 한장이 새로 쓴 글이에요\. 기사 본문은 받지 않아요\. "), ""),
)


def us_words(html_: str) -> str:
    for pat, new in US_WORDS:
        html_ = pat.sub(new, html_)
    return html_


FLAG = {"KR": "한", "US": "미"}  # 국기 이모지는 윈도우에서 「KR」 글자로 나와서 쓰지 않는다
CHIP = "block mt-0.5 lg:mt-1 px-0.5 lg:px-1.5 py-0.5 lg:py-1 rounded text-[9px] lg:text-[12px] font-semibold leading-tight tracking-tighter lg:tracking-normal truncate"  # 캘린더 칸 칩 — 한 줄, 넘치면 …
AHEAD_SHORT = {"EARNINGS": "실적", "AGM": "주총", "DIVIDEND": "배당", "OTHER": "IR"}  # 달력 칸이 좁아 한 낱말로
TONE_TAG = {1: ("긍정", "bg-secondary-fixed/70 text-on-secondary-fixed-variant"),
            -1: ("부정", "bg-tertiary-fixed text-on-tertiary-fixed-variant"),
            0: ("중립", "bg-surface-container text-on-surface-variant")}  # fmt: skip


# --- 앱 ---


class App:
    def __init__(self, con: sqlite3.Connection, secret: str, clock=time.time) -> None:
        self.con, self.secret, self.clock = con, secret, clock
        # 요청은 한 번에 하나씩 — DB 연결 하나를 돌려 쓴다. 화면 하나가 수 ms 라 이 규모에선 이게 가장 빠르고 공평하다
        # (부하 시험 10/10: 실마다 연결을 열면 초당 250건 → 60건, 느린 요청 16초). 대신 메일·AI 처럼 느린 바깥 일 동안엔 잠금을 놓는다(outside)
        self.turn = threading.Lock()
        self.local = threading.local()
        self.making: set[str] = set()  # 지금 첫 노트를 만드는 종목 (담자마자 바로 받기)
        self.making_lock = threading.Lock()  # 화면 서버는 여러 실에서 돈다 — 같은 종목을 두 번 받지 않게
        self.sent: dict[str, list[float]] = {}  # ponytail: 링크 요청 시각을 메모리에 — 서버를 다시 켜면 비워진다. 여러 대면 DB 로
        self.codes: dict[str, list] = {}  # 이메일 → [코드, 만료 시각, 틀린 횟수]
        self.uploads = threading.Semaphore(BIG_AT_ONCE)
        self.memo: dict = {}  # cached() — 매일 실행 뒤에만 바뀌는 큰 조각(종목 목록 186KB · 국민연금·유명 투자자 페이지)
        self.scans: dict[int, list[float]] = {}  # ponytail: 캡처 읽기 시각 — 메모리에. 여러 대면 DB 로

    def cached(self, name: str, build):
        """매일 실행(다른 연결)이 쓰기 전까지는 한 번 만든 것을 돌려준다 — `pragma data_version` 은 다른 연결이 커밋할 때마다 바뀐다.
        이 연결이 직접 쓰는 표(열어본 기록·좋아요·팔로우…)는 여기 넣는 조각과 상관없다. 버전이 바뀌면 통째로 비운다 (DB 점검 10/11)."""
        v = self.con.execute("pragma data_version").fetchone()[0]
        if self.memo.get("v") != v:
            self.memo = {"v": v}
        if name not in self.memo:
            self.memo[name] = build()
        return self.memo[name]

    @contextmanager
    def outside(self):
        """느린 바깥 일(로그인 메일·AI 사진 읽기, 수 초) 동안 잠금을 놓아 다른 사람의 화면이 돌게 한다.
        이 안에서는 DB 를 쓰지 않는다 — 연결을 다른 요청이 쓰고 있다."""
        held = getattr(self.local, "held", False)
        if held:
            self.turn.release()
        try:
            yield
        finally:
            if held:
                self.turn.acquire()

    def __call__(self, environ, start_response):
        method, path = environ["REQUEST_METHOD"], environ.get("PATH_INFO", "/")
        cookie = dict(c.strip().split("=", 1) for c in environ.get("HTTP_COOKIE", "").split(";") if "=" in c)
        uid, renew = read_session(cookie.get("s", ""), self.secret, self.clock())
        n = int(environ.get("CONTENT_LENGTH") or 0) if method == "POST" else 0
        # 본문을 읽기 전에 거른다 — 전에는 로그인하지 않은 누구든 어느 주소로든 6MB 를 보낼 수 있었고, 여럿이 한꺼번에 보내면 메모리가 찼다
        if n > (BODY_MAX if uid and path in BIG_POSTS else FORM_MAX):
            start_response("413 Payload Too Large", [("Content-Type", "text/plain; charset=utf-8")])
            return ["사진이 너무 커요".encode()]
        big = n > FORM_MAX
        if big and not self.uploads.acquire(blocking=False):
            start_response("503 Service Unavailable", [("Content-Type", "application/json; charset=utf-8"), ("Retry-After", "5")])
            return [json.dumps({"msg": "지금 사진을 읽는 사람이 많아요. 잠시 뒤에 다시 해 주세요."}, ensure_ascii=False).encode()]
        try:
            return self.respond(environ, start_response, method, path, n, cookie, uid, renew)
        except Exception:  # 무엇이 잘못됐든 사용자는 「다시 불러오기」를 본다. 까닭은 서버 기록에 (journalctl -u hanjang-web)
            traceback.print_exc()
            try:
                self.con.rollback()
            except sqlite3.Error:
                pass
            body = page("문제가 생겼어요", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen",
                        '<main class="w-full max-w-[480px] mx-auto px-margin pt-14 flex flex-col items-center text-center">'
                        f'<div class="mt-12">{tree.line("oops")}</div><p class="mt-space-md font-body-reading text-body-reading">앗, 뭔가 문제가 있는 것 같아요!</p>'
                        '<button class="mt-space-lg px-5 py-3 rounded-lg bg-primary text-on-primary font-body-reading-strong text-body-compact" onclick="location.reload()" type="button">다시 불러오기</button></main>')  # fmt: skip
            start_response("500 Internal Server Error", [("Content-Type", "text/html; charset=utf-8")])
            return [body.encode()]
        finally:
            if big:
                self.uploads.release()

    def respond(self, environ, start_response, method, path, n, cookie, uid, renew):
        form = {}
        if method == "POST":
            raw = environ["wsgi.input"].read(n).decode()
            if environ.get("CONTENT_TYPE", "").startswith("application/json"):
                form = {"_json": json.loads(raw or "{}")}
            else:
                form = {k: v[0] for k, v in parse_qs(raw).items()}
            del raw
        query = {k: v[0] for k, v in parse_qs(environ.get("QUERY_STRING", "")).items()}
        self.local.ip = (environ.get("HTTP_X_FORWARDED_FOR") or environ.get("REMOTE_ADDR") or "").split(",")[-1].strip()  # 앞의 Caddy 가 붙여 준 마지막 값이 실제 접속 주소
        with self.turn:
            self.local.held = True
            try:
                status, headers, body = self.route(method, path, form, query, uid)
            finally:
                self.local.held = False
        if renew and not any(k == "Set-Cookie" for k, _ in headers):  # 옛 쿠키 → 날짜가 든 새 쿠키로 (로그아웃·탈퇴처럼 쿠키를 지우는 응답은 그대로)
            headers = [*headers, ("Set-Cookie", session_cookie(uid, self.secret, self.clock()))]
        kind = [] if any(k == "Content-Type" for k, _ in headers) else [("Content-Type", "text/html; charset=utf-8"), ("Content-Security-Policy", CSP)]
        start_response(status, [*kind, ("X-Content-Type-Options", "nosniff"),
                                ("X-Frame-Options", "DENY"), ("Referrer-Policy", "same-origin"), *headers])  # fmt: skip
        return [body if isinstance(body, bytes) else body.encode()]

    def see(self, to: str, *headers) -> tuple:
        return "303 See Other", [("Location", to), *headers], ""

    def log(self, uid: int, page_: str, ticker: str | None = None) -> None:
        try:
            now = datetime.now().isoformat()
            self.con.execute("insert into views (user_id, page, ticker, at) values (?, ?, ?, ?)", (uid, page_, ticker, now))
            # 들어온 날 수 — 하루에 한 번만 더한다. 처음엔 남아 있는 기록의 날 수에서 시작 (내 나무, 10/11)
            self.con.execute("update users set days = coalesce(days, (select count(distinct substr(at, 1, 10)) from views where user_id = ? and substr(at, 1, 10) < ?)) + 1,"
                             " last_day = ? where id = ? and coalesce(last_day, '') != ?", (uid, now[:10], now[:10], uid, now[:10]))  # fmt: skip
            self.con.commit()
        except sqlite3.OperationalError:  # DB 가 잠깐 잠겨도 화면은 보여 준다 — 기록 한 줄을 잃는 쪽이 낫다
            self.con.rollback()

    def initial(self, uid: int) -> str:
        """위쪽 동그라미에 넣을 것 — 사진 주소, 없으면 닉네임 첫 글자(정하기 전이면 이메일 첫 글자)."""
        row = self.con.execute("select coalesce(nickname, email), photo_at, coalesce(notices_seen, '') from users where id = ?", (uid,)).fetchone()
        me = Me((photo_url(uid, row[1]) or row[0][:1]) if row else "?")
        if row:
            regs, arts = self.fresh(uid, row[2])
            me.unread = self.con.execute("select count(*) from follows where followee_id = ? and at > ?", (uid, row[2])).fetchone()[0] + len(regs) + len(arts)
        return me

    def simple(self, title: str, msg: str) -> str:
        art = tree.line("oops" if title == "없음" else "calm")  # 없는 화면엔 걱정스러운 얼굴, 그 밖의 안내엔 웃는 얼굴
        return page(title, "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen",
                    f'<main class="w-full max-w-[480px] lg:max-w-[760px] mx-auto px-margin pt-14 flex flex-col items-center text-center">'
                    f'<div class="mt-12">{art}</div><p class="mt-space-md font-body-reading text-body-reading">{msg}</p></main>')  # fmt: skip

    def route(self, method, path, form, query, uid):
        if path == "/login" and method == "POST":
            return self.login(form.get("email", "").strip().lower(), form.get("agree") == "1", form.get("c", ""))
        if path.startswith("/static/photos/") and re.fullmatch(r"(pool/)?[a-z]+\d*\.jpg", path[15:]) and (STATIC / "photos" / path[15:]).exists():
            return "200 OK", [("Content-Type", "image/jpeg"), ("Cache-Control", "public, max-age=604800")], (STATIC / "photos" / path[15:]).read_bytes()
        if path == "/stocks.js":  # 검색 자동완성 — 상장사 이름·코드는 공개 정보라 로그인 없이
            return "200 OK", [("Content-Type", "text/javascript; charset=utf-8"), ("Cache-Control", "public, max-age=86400")], self.stocks_js()
        if path.startswith("/static/people/") and path[15:-4] in PEOPLE and path.endswith(".jpg") and (STATIC / "people" / path[15:]).exists():
            return "200 OK", [("Content-Type", "image/jpeg"), ("Cache-Control", "public, max-age=604800")], (STATIC / "people" / path[15:]).read_bytes()
        if path == "/static/og.png":  # 링크 미리보기 그림
            return "200 OK", [("Content-Type", "image/png"), ("Cache-Control", "public, max-age=86400")], (STATIC / "og.png").read_bytes()
        if path in ("/static/icon-192.png", "/static/icon-512.png", "/static/icon-maskable.png", "/static/apple-touch-icon.png"):  # 홈 화면 아이콘
            return "200 OK", [("Content-Type", "image/png"), ("Cache-Control", "public, max-age=604800")], (STATIC / path[8:]).read_bytes()
        if path == "/static/app.css":  # 주소에 내용 지문(?v=)이 붙어 있어 오래 캐시해도 된다
            return "200 OK", [("Content-Type", "text/css; charset=utf-8"), ("Cache-Control", "public, max-age=31536000, immutable")], (STATIC / "app.css").read_bytes()
        if path == "/manifest.webmanifest":  # 「홈 화면에 추가」 · 플레이스토어 포장(TWA)의 재료
            return "200 OK", [("Content-Type", "application/manifest+json"), ("Cache-Control", "public, max-age=86400")], MANIFEST
        if path == "/sw.js":  # 서비스 워커 — 맨 위 주소에 있어야 사이트 전체를 맡는다
            return "200 OK", [("Content-Type", "text/javascript; charset=utf-8"), ("Cache-Control", "no-cache")], SW
        if path == "/health":  # 바깥 감시(구글 클라우드 모니터링)가 5분마다 연다 — 안 되면 운영자 메일
            return self.health()
        if path == "/robots.txt":  # 공개 페이지(로그인·처리방침·계산 방법)만 검색에 — 나머지는 어차피 로그인 화면
            return "200 OK", [("Content-Type", "text/plain; charset=utf-8")], "User-agent: *\nAllow: /\n"
        if path == "/offline":
            return "200 OK", [], OFFLINE
        if path == "/.well-known/assetlinks.json":  # 안드로이드 앱(TWA)이 이 사이트 것임을 증명 — 서명 키 지문을 .env 에 넣으면 열린다
            return self.assetlinks()
        if path == "/login/code" and method == "POST":
            return self.login_code(form.get("email", "").strip().lower(), form.get("code", ""), form.get("c", ""))
        if path in ("/privacy", "/method", "/help/login", "/rules"):  # 로그인 없이 열린다
            return "200 OK", [], self.doc(path, uid)
        if path == "/auth":
            email = check_login(query.get("t", ""), self.secret, self.clock())
            if not email:
                return "200 OK", [], self.simple("로그인", "링크가 만료됐거나 잘못됐어요. <a class='text-primary underline' href='/'>다시 받기</a>")
            return self.start(email, query.get("c", ""))
        if path == "/demo":  # 둘러보기 — 이메일 없이 공용 계정으로 (메일 보내기 전, 남에게 보여줄 때)
            return self.demo()
        if uid is None:
            return "200 OK", [], self.login_page(cohort=query.get("c", ""))
        if method == "POST" and self.is_demo(uid):  # 둘러보기는 보기만 — 여럿이 같이 쓰는 계정이라 바꾸지 않는다
            return "200 OK", [], self.simple("둘러보기", "둘러보기에서는 보기만 할 수 있어요. 직접 쓰려면 로그인해 주세요. "
                                             "<a class='text-primary underline' href='javascript:history.back()'>돌아가기</a>")
        if path == "/logout":
            return self.see("/", ("Set-Cookie", "s=; Path=/; Max-Age=0"))
        # 닉네임은 가입할 때 받는다 — 정하기 전엔 다른 화면으로 못 간다 (사람 찾기·피드에 쓰이니 겹치면 안 된다)
        # 이용 규칙 동의도 여기서 — 남에게 보이는 프로필을 만들기 전에 (이미 닉네임이 있는 사람도 한 번 동의를 받는다)
        me = self.con.execute("select nickname, rules_at, banned from users where id = ?", (uid,)).fetchone()
        if not me:  # 쿠키는 남았는데 계정이 없다(다른 기기에서 탈퇴) — 오류 화면 대신 쿠키를 지우고 처음으로
            return self.see("/", ("Set-Cookie", "s=; Path=/; Max-Age=0"))
        nick, agreed, banned = me
        if banned:  # 운영자가 막은 계정 — 쿠키를 지우고 알린다
            contact = env().get("PRIVACY_CONTACT", "")
            return "403 Forbidden", [("Set-Cookie", "s=; Path=/; Max-Age=0")], self.simple(
                "이용 제한", "이용 규칙을 어겨 이 계정은 쓸 수 없게 됐어요." + (f" 문의: {e(contact)}" if contact else "") + " <a class='text-primary underline' href='/rules'>이용 규칙</a>")
        if not nick or not agreed:
            if path == "/welcome" and method == "POST":
                return self.welcome(uid, form.get("nickname", "").strip(), form.get("rules") == "1")
            return "200 OK", [], self.welcome_page(nick or "")
        if path == "/welcome":
            return self.see("/")
        if path == "/add" and method == "POST":
            return self.add(uid, form.get("q", "").strip())
        if path.startswith("/p/") and path.endswith(".jpg") and path[3:-4].isdigit():  # 프로필 사진 (로그인한 사람만)
            row = self.con.execute("select photo from users where id = ? and photo is not null", (int(path[3:-4]),)).fetchone()
            if not row:
                return "404 Not Found", [], self.simple("없음", "사진이 없어요.")
            return "200 OK", [("Content-Type", "image/jpeg"), ("Cache-Control", "private, max-age=31536000")], bytes(row[0])
        if path == "/me/photo" and method == "POST":
            return self.save_photo(uid, (form.get("_json") or {}).get("img", ""))
        if path == "/me/photo/delete" and method == "POST":
            self.con.execute("update users set photo = null, photo_at = null where id = ?", (uid,))
            self.con.commit()
            return self.see("/me/settings")
        if path == "/scan" and method == "POST":
            return self.scan(uid, (form.get("_json") or {}).get("img", ""))
        if path == "/remove" and method == "POST":
            self.con.execute("delete from holdings where user_id = ? and ticker = ?", (uid, form.get("t")))
            self.con.commit()
            return self.see("/")
        if path == "/":
            self.log(uid, "cards")
            return "200 OK", [], self.cards(uid, query.get("msg"), query.get("sort"))
        if path.startswith("/n/"):
            ticker = path[3:]
            self.log(uid, "note", ticker)
            return self.note(uid, ticker, query.get("thanks") == "1")
        if path.startswith("/a/") and path[3:].isdigit():
            self.log(uid, "article", path[3:])
            return self.article(uid, int(path[3:]))
        if path == "/feed":
            self.log(uid, "feed")
            return "200 OK", [], self.feed(uid, query.get("q", "").strip())
        if path.startswith("/u/") and path[3:].isdigit():
            if int(path[3:]) == uid:
                return self.see("/me")
            self.log(uid, "user")
            return self.user_page(uid, int(path[3:]))
        if path in ("/block", "/report") and method == "POST":
            other = int(form["u"]) if form.get("u", "").isdigit() else 0
            if other == uid or not self.con.execute("select 1 from users where id = ?", (other,)).fetchone():
                return self.see("/feed")
            return self.block(uid, other) if path == "/block" else self.report_user(uid, other, form.get("why", ""))
        if path == "/follow" and method == "POST":  # 한 번 더 누르면 언팔로우
            other = int(form["u"]) if form.get("u", "").isdigit() else 0
            if other != uid and other not in self.blocked(uid) and self.con.execute("select 1 from users where id = ? and nickname is not null", (other,)).fetchone():
                if not self.con.execute("delete from follows where follower_id = ? and followee_id = ?", (uid, other)).rowcount:
                    shut = self.con.execute("select private from users where id = ?", (other,)).fetchone()[0]
                    self.con.execute("insert into follows (follower_id, followee_id, at, ok) values (?, ?, ?, ?)", (uid, other, datetime.now().isoformat(), 0 if shut else 1))
                self.con.commit()
            back = form.get("back", "")
            ok = re.fullmatch(r"/[A-Za-z0-9_/?=&%.\-]*", back) and not back.startswith("//")  # 「/\evil.com」 → 「//evil.com」 막기
            return self.see(back if ok else f"/u/{other}" if other else "/feed")
        if path == "/follow/answer" and method == "POST":  # 팔로우 요청 수락(1)·삭제(0)
            other = int(form["u"]) if form.get("u", "").isdigit() else 0
            if form.get("yes") == "1":
                self.con.execute("update follows set ok = 1 where follower_id = ? and followee_id = ?", (other, uid))
            else:
                self.con.execute("delete from follows where follower_id = ? and followee_id = ? and ok = 0", (other, uid))
            self.con.commit()
            return self.see("/me/notices")
        if path == "/regram" and method == "POST":
            return self.regram(uid, form)
        if path == "/save" and method == "POST":
            return self.regram(uid, form, table="saves")
        if path == "/hl/share" and method == "POST":
            return self.share_quote(uid, form.get("p", ""), form.get("t", ""))
        if path in ("/hl", "/hl/del"):
            return self.highlight(uid, method, path, form, query)
        if path in ("/me/saved", "/me/liked"):
            return "200 OK", [], self.kept(uid, path[4:])
        if path == "/me/profile" and method == "POST":
            return self.save_profile(uid, form.get("nickname", "").strip(), form.get("bio", "").strip())
        if path == "/like" and method == "POST":  # 한 번 더 누르면 취소
            t, w = form.get("t", ""), form.get("w", "")
            if self.con.execute("select 1 from notes where ticker = ? and week = ?", (t, w)).fetchone():
                if not self.con.execute("delete from likes where user_id = ? and ticker = ? and week = ?", (uid, t, w)).rowcount:
                    self.con.execute("insert into likes values (?, ?, ?, ?)", (uid, t, w, datetime.now().isoformat()))
                self.con.commit()
            return self.see(f"/n/{quote(t)}")
        if path == "/feedback" and method == "POST":
            return self.feedback(uid, form)
        if path == "/me/private" and method == "POST":  # 비공개 켜기/끄기 — 끄면 기다리던 요청은 모두 수락
            self.con.execute("update users set private = 1 - private where id = ?", (uid,))
            if not self.con.execute("select private from users where id = ?", (uid,)).fetchone()[0]:
                self.con.execute("update follows set ok = 1 where followee_id = ?", (uid,))
            self.con.commit()
            return self.see("/me/settings")
        if path == "/me/mail" and method == "POST":
            self.con.execute("update users set mail_on = 1 - mail_on where id = ?", (uid,))
            self.con.commit()
            return self.see("/me/settings")
        if path == "/me/delete" and method == "POST":
            # 탈퇴 — 이 사용자의 모든 행을 지운다 (되돌릴 수 없음, 화면에서 한 번 더 확인)
            for table, col in (("holdings", "user_id"), ("views", "user_id"), ("feedback", "user_id"), ("likes", "user_id"),
                               ("regrams", "user_id"), ("saves", "user_id"), ("highlights", "user_id"), ("follows", "follower_id"), ("follows", "followee_id"),
                               ("blocks", "user_id"), ("blocks", "blocked_id"), ("reports", "user_id"), ("reports", "target_id"), ("users", "id")):  # fmt: skip
                self.con.execute(f"delete from {table} where {col} = ?", (uid,))
            self.con.commit()
            return self.see("/", ("Set-Cookie", "s=; Path=/; Max-Age=0"))
        if path == "/me/notices":
            return self.notices(uid)
        if path.startswith("/f/") and path[3:].isdigit():
            return self.follow_page(uid, int(path[3:]), query.get("tab", "followers"))
        if path == "/me":
            self.log(uid, "me")
            return "200 OK", [], self.profile(uid)
        if path == "/me/settings":
            return "200 OK", [], self.settings(uid, query.get("msg"))
        if path == "/learn" or path.startswith("/learn/"):
            slug = path[7:]
            self.log(uid, "learn", slug or None)
            return self.learn(uid, slug)
        if path == "/calendar":
            self.log(uid, "calendar")
            return "200 OK", [], self.calendar(uid, query.get("m"), sort=query.get("s"))
        return "404 Not Found", [], self.simple("없음", "없는 화면이에요. <a class='text-primary underline' href='/'>처음으로</a>")

    # ---- 로그인 (시안 _2) ----

    def login_page(self, sent: str | None = None, error: str = "", cohort: str = "") -> str:
        hidden = f'<input type="hidden" name="c" value="{cohort}">' if COHORT.fullmatch(cohort) else ""
        box = (f'<p class="font-body-compact text-body-compact text-tertiary mt-3" role="alert">{e(error)}</p>' if error else "") + ("" if not sent else (
            '<div class="flex flex-col bg-secondary-container/40 rounded-lg p-4 mt-4 transition-all" id="success-box"><div class="flex items-start gap-3"><div class="flex-shrink-0 w-8 h-8 rounded-full bg-secondary-container flex items-center justify-center mt-0.5"><span class="material-symbols-outlined text-on-secondary-container text-lg" style="font-variation-settings: \'FILL\' 1;">mark_email_read</span></div><div class="flex flex-col flex-1 min-w-0"><div class="flex items-center gap-1.5 mb-1"><span class="font-label-micro text-label-micro bg-primary text-on-primary px-1.5 py-0.5 rounded">발송 완료</span>'
            f'<span class="font-body-reading-strong text-body-compact text-on-surface truncate" id="target-email-preview">{e(sent)}</span></div>'
            '<p class="font-body-compact text-body-compact text-on-secondary-container">위 주소로 로그인 링크와 6자리 코드를 보냈어요. 15분 안에 메일 속 링크를 누르거나, 코드를 아래에 넣어 주세요.</p>'
            # 코드 넣기 — 앱(웹뷰)이나 홈 화면에 추가한 한장에서는 메일의 링크가 다른 브라우저로 열려 로그인이 안 이어진다. 코드는 어디서든 된다 (앱 출시 준비 10/11)
            f'<form method="post" action="/login/code" class="mt-2.5 flex items-center gap-2"><input type="hidden" name="email" value="{e(sent)}">{hidden}'
            '<input aria-label="메일로 받은 6자리 코드" autocomplete="one-time-code" autofocus inputmode="numeric" maxlength="6" name="code" pattern="[0-9]{6}" placeholder="6자리 코드" required '
            'class="flex-1 min-w-0 font-body-reading text-body-reading bg-surface-container-lowest text-on-surface placeholder:text-outline rounded-lg px-4 py-2.5 focus:outline-none tracking-widest">'
            '<button class="shrink-0 px-4 py-2.5 bg-primary text-on-primary font-label-regular text-label-regular font-semibold rounded-lg" type="submit">확인</button></form>'
            '<div class="flex flex-col gap-1 mt-2.5 pt-2.5 border-t border-outline-variant/30"><p class="font-label-micro text-label-micro text-outline">메일이 오지 않았나요? 스팸함을 보거나 잠시 뒤에 다시 받아 보세요.</p>'
            f'<form method="post" action="/login"><input type="hidden" name="email" value="{e(sent)}"><input type="hidden" name="agree" value="1">{hidden}<button class="self-start font-label-regular text-label-regular text-primary font-semibold underline underline-offset-2 hover:opacity-80 transition-opacity mt-1" id="resend-btn" type="submit">링크 다시 보내기</button></form></div></div></div></div>'
            # 이 상자는 폼 아래에 있어 휴대폰에선 화면 밖이다 — 뜨자마자 보이게 내린다. 자동 초점(autofocus)만으로는 안 된다: 아이폰은 사용자가 누르지 않은 초점을 무시한다 (눌러 보기 10/11)
            "<script>document.getElementById('success-box').scrollIntoView({block:'center'});</script>"))  # fmt: skip
        inner = ('<main class="flex flex-col relative w-full max-w-[480px] lg:max-w-[760px] mx-auto bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-12">'
                 '<div class="flex flex-col items-center text-center mt-6 mb-8"><div class="relative flex items-center justify-center w-20 h-20 rounded-full bg-surface-container-low shadow-sm mb-5"><svg class="w-9 h-9 text-primary" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.75" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" x2="8" y1="13" y2="13"></line><line x1="16" x2="8" y1="17" y2="17"></line><line x1="10" x2="8" y1="9" y2="9"></line></svg><div class="absolute -bottom-1 -right-1 flex items-center justify-center w-6 h-6 rounded-full bg-secondary-container shadow-xs"><span class="material-symbols-outlined text-on-secondary-container text-xs" style="font-variation-settings: \'FILL\' 1;">auto_stories</span></div></div>'
                 '<span class="font-display-editorial text-display-editorial text-primary tracking-tight">한장</span><span class="font-label-micro text-label-micro text-outline uppercase tracking-widest mt-1">Hanjang · Weekly Financial Letter</span>'
                 '<h1 class="font-headline-sm text-headline-sm text-on-surface mt-4 max-w-[280px] leading-relaxed">내 주식이 지금 어떤 상황인지,<br>쉬운 글 한 장으로.</h1>'
                 '<p class="font-body-compact text-body-compact text-on-surface-variant mt-2 max-w-[300px]">숫자 뒤에 숨겨진 회사의 진짜 이야기와 사업 흐름을 담백하게 정리해 드립니다.</p></div>'
                 '<div class="w-full rounded-xl flex flex-col relative overflow-hidden px-1.5"><form class="flex flex-col w-full relative z-10" id="magic-link-form" method="post" action="/login">' + hidden
                 + '<div class="flex items-center justify-between mb-2"><label class="font-label-regular text-label-regular text-on-surface flex items-center gap-1.5" for="email-input"><span class="material-symbols-outlined text-primary text-base">mail</span>이메일 주소</label><span class="font-label-micro text-label-micro text-outline">비밀번호 없는 간편 시작</span></div>'
                 '<div class="relative flex items-center w-full"><input class="w-full font-body-reading text-body-reading bg-surface-container-low text-on-surface placeholder:text-outline rounded-lg px-4 py-3.5 focus:outline-none focus:bg-surface-container-lowest transition-all" id="email-input" name="email" placeholder="name@example.com" required="" type="email">'
                 '<button aria-label="이메일 지우기" class="hidden absolute right-3 text-outline hover:text-on-surface p-1 transition-colors" id="clear-btn" onclick="clearInput()" type="button"><span class="material-symbols-outlined text-lg">cancel</span></button></div>'
                 '<label class="flex items-start gap-2 mt-3 font-label-regular text-label-regular text-on-surface-variant"><input class="mt-0.5 accent-primary" name="agree" required type="checkbox" value="1">'
                 '<span>[필수] 이메일 수집·이용에 동의해요 — <a class="text-primary underline" href="/privacy" target="_blank">개인정보 처리방침</a></span></label>'
                 f'<button class="w-full py-3.5 bg-primary text-on-primary font-body-reading-strong text-body-reading-strong rounded-lg shadow-sm hover:opacity-95 active:scale-[0.99] transition-all mt-3 flex items-center justify-center gap-2" id="submit-btn" type="submit"><span class="">{"링크 다시 받기" if sent else "시작하기"}</span><span class="material-symbols-outlined text-base">{"refresh" if sent else "arrow_forward"}</span></button>'
                 '<p class="font-label-regular text-label-regular text-outline text-center mt-3 leading-relaxed">비밀번호 없이, 메일로 온 링크를 누르면 시작돼요. 받는 개인정보는 이메일 하나뿐이에요.</p>'
                 '<a class="block text-center mt-2 font-label-regular text-label-regular text-primary underline underline-offset-2" href="/help/login">로그인 링크가 안 와요</a></form>'
                 + ('<a class="mt-3 w-full py-3 rounded-lg border border-outline-variant/70 text-on-surface font-body-reading-strong text-body-compact flex items-center justify-center gap-1" href="/demo">'
                    '<span class="material-symbols-outlined text-[18px]">visibility</span>로그인 없이 둘러보기</a>' if env().get("DEMO") == "1" else "")
                 + box + '</div>'
                 '<div class="mt-8 flex flex-col gap-4"><div class="grid grid-cols-2 gap-4 pt-2 border-t border-outline-variant/30"><div class="flex flex-col gap-1"><div class="flex items-center gap-1.5 text-primary"><span class="material-symbols-outlined text-base">description</span><span class="font-body-reading-strong text-label-regular">공시 기반 해설</span></div><p class="font-label-micro text-label-micro text-on-surface-variant leading-relaxed">어려운 DART 공시와 분기 보고서를 일상 언어로 풀어냅니다.</p></div><div class="flex flex-col gap-1"><div class="flex items-center gap-1.5 text-secondary"><span class="material-symbols-outlined text-base">spa</span><span class="font-body-reading-strong text-label-regular">소음 없는 담백함</span></div><p class="font-label-micro text-label-micro text-on-surface-variant leading-relaxed">빨강·파랑 시세창 대신 기업 본질을 천천히 읽는 시간.</p></div></div>'
                 '<div class="text-center px-4 mt-4"><div class="inline-flex items-center justify-center gap-2 mb-2"><span class="w-4 h-[1px] bg-outline-variant"></span><span class="font-citation-ref text-citation-ref text-outline">한장의 약속</span><span class="w-4 h-[1px] bg-outline-variant"></span></div><p class="font-label-regular text-label-regular text-outline leading-relaxed">이해를 위한 서비스예요. 수익률을 장담하거나 종목을 추천하지 않아요.</p></div></div></div>'
                 "<script>const emailInput=document.getElementById('email-input');const clearBtn=document.getElementById('clear-btn');"
                 "emailInput.addEventListener('input',(ev)=>{clearBtn.classList.toggle('hidden',ev.target.value.length===0);});"
                 "function clearInput(){emailInput.value='';clearBtn.classList.add('hidden');emailInput.focus();}</script></main>")  # fmt: skip
        return page("로그인", "bg-surface font-body-reading text-on-surface pt-safe pb-safe flex flex-col min-h-screen", inner)

    def health(self, now: float | None = None):
        """화면 서버가 대답하고 · DB 가 열리고 · 매일 실행이 30시간 안에 돌았고(그때 백업을 만든다) · 디스크가 10% 넘게 남았나.
        문제가 있으면 503 과 무엇이 문제인지 한 낱말씩 (사용자 정보는 싣지 않는다)."""
        bad = []
        try:
            self.con.execute("select 1 from users limit 1").fetchall()
        except sqlite3.Error:
            bad.append("db")
        backups = list((db.PATH.parent / "backup").glob("hanjang-*.db"))
        if not backups or (now or time.time()) - max(p.stat().st_mtime for p in backups) > 30 * 3600:
            bad.append("daily")
        disk = shutil.disk_usage(db.PATH.parent)
        if disk.free < disk.total * 0.1:
            bad.append("disk")
        return ("503 Service Unavailable" if bad else "200 OK"), [("Content-Type", "text/plain; charset=utf-8"), ("Cache-Control", "no-store")], " ".join(bad) or "ok"

    def assetlinks(self):
        pkg, sha = env().get("TWA_PACKAGE", ""), env().get("TWA_SHA256", "")
        if not (pkg and sha):
            return "404 Not Found", [], self.simple("없음", "없는 화면이에요.")
        body = [{"relation": ["delegate_permission/common.handle_all_urls"],
                 "target": {"namespace": "android_app", "package_name": pkg, "sha256_cert_fingerprints": [x.strip() for x in sha.split(",")]}}]
        return "200 OK", [("Content-Type", "application/json")], json.dumps(body)

    def is_demo(self, uid: int) -> bool:
        row = self.con.execute("select email from users where id = ?", (uid,)).fetchone()
        return bool(row and row[0] == DEMO_EMAIL)

    def demo(self):
        if env().get("DEMO") != "1":
            return "404 Not Found", [], self.simple("없음", "없는 화면이에요. <a class='text-primary underline' href='/'>처음으로</a>")
        self.con.execute("insert or ignore into users (email, created_at, nickname, mail_on) values (?, ?, '둘러보기', 0)",
                         (DEMO_EMAIL, datetime.now().isoformat()))  # fmt: skip
        self.con.execute("update users set rules_at = coalesce(rules_at, created_at) where email = ?", (DEMO_EMAIL,))  # 공용 계정 — 닉네임이 정해져 있어 규칙 동의 관문을 지나게
        (u,) = self.con.execute("select id from users where email = ?", (DEMO_EMAIL,)).fetchone()
        for t in DEMO_STOCKS:
            if self.con.execute("select 1 from stocks where ticker = ?", (t,)).fetchone():
                self.con.execute("insert or ignore into holdings values (?, ?, ?)", (u, t, datetime.now().isoformat()))
        self.con.commit()
        return self.see("/", ("Set-Cookie", session_cookie(u, self.secret, self.clock(), 86400)))

    def start(self, email: str, cohort: str = ""):
        """이 이메일로 로그인 — 계정이 없으면 만든다. 초대 링크 묶음은 처음 한 번만 붙는다."""
        self.con.execute("insert or ignore into users (email, created_at) values (?, ?)", (email, datetime.now().isoformat()))
        if COHORT.fullmatch(cohort):
            self.con.execute("update users set cohort = ? where email = ? and cohort is null", (cohort, email))
        self.con.commit()
        (u,) = self.con.execute("select id from users where email = ?", (email,)).fetchone()
        return self.see("/", ("Set-Cookie", session_cookie(u, self.secret, self.clock())))

    def login(self, email: str, agreed: bool = False, cohort: str = ""):
        if "@" not in email or len(email) > 200:
            return "200 OK", [], self.login_page()
        if not agreed:
            return "200 OK", [], self.login_page(error="개인정보 수집·이용에 동의해야 시작할 수 있어요.", cohort=cohort)
        # 누구든 메일로 온 링크를 눌러야 들어온다 — 남의 이메일을 넣어 남의 계정에 들어가거나, 남의 이메일로 가입하지 못하게 (공개 출시 준비 10/10)
        now = self.clock()
        times = [t for t in self.sent.get(email, []) if now - t < 3600]
        if (times and now - times[-1] < LOGIN_GAP) or len(times) >= LOGIN_HOURLY:
            return "429 Too Many Requests", [], self.login_page(error="링크를 방금 보냈어요. 메일함을 먼저 확인하고, 잠시 뒤에 다시 요청해 주세요.", cohort=cohort)
        ip = "ip:" + getattr(self.local, "ip", "")
        by_ip, by_all = ([t for t in self.sent.get(k, []) if now - t < 3600] for k in (ip, "*"))
        if len(by_ip) >= LOGIN_IP_HOURLY or len(by_all) >= LOGIN_ALL_HOURLY:
            return "429 Too Many Requests", [], self.login_page(error="로그인 요청이 너무 많아요. 한 시간쯤 뒤에 다시 해 주세요.", cohort=cohort)
        if len(self.sent) > 2000:  # 한 시간 지난 요청 기록·만료된 코드를 비운다 — 주소·IP 마다 한 칸씩 끝없이 늘지 않게
            self.sent = {k: v for k, v in self.sent.items() if v and now - v[-1] < 3600}
            self.codes = {k: v for k, v in self.codes.items() if now <= v[1]}
        self.sent |= {email: times + [now], ip: by_ip + [now], "*": by_all + [now]}
        link = f"{mail.base_url()}/auth?t={quote(login_token(email, self.secret, now))}" + (f"&c={cohort}" if COHORT.fullmatch(cohort) else "")
        code = f"{secrets.randbelow(10**6):06d}"
        self.codes[email] = [code, now + LINK_TTL, 0]  # ponytail: 메모리에 — 서버를 다시 켜면 코드는 사라지고 링크만 남는다(링크는 서명이라 그대로 된다)
        with self.outside():  # 메일 서버와 주고받는 수 초 동안 다른 화면은 돈다
            mail.send(email, *mail.login_mail(link, code))  # SMTP 설정이 없으면 서버 콘솔에 찍힌다
        return "200 OK", [], self.login_page(email, cohort=cohort)

    def login_code(self, email: str, code: str, cohort: str = ""):
        """메일로 받은 6자리 코드로 들어온다. 틀리면 CODE_TRIES 번까지 — 넘으면 그 코드는 버리고 새로 받아야 한다
        (6자리는 100만 가지라 마구 넣어 볼 수 있다. 코드 하나에 5번, 새 코드는 한 시간에 5통 → 한 시간에 많아야 25번)."""
        row = self.codes.get(email)
        if not row or self.clock() > row[1]:
            self.codes.pop(email, None)
            return "200 OK", [], self.login_page(error="코드가 만료됐어요. 이메일을 넣고 새로 받아 주세요.", cohort=cohort)
        if not hmac.compare_digest(row[0], code.strip()):
            row[2] += 1
            if row[2] >= CODE_TRIES:
                del self.codes[email]
                return "200 OK", [], self.login_page(error="코드를 여러 번 틀렸어요. 이메일을 넣고 새로 받아 주세요.", cohort=cohort)
            return "200 OK", [], self.login_page(email, error=f"코드가 맞지 않아요. 메일의 숫자 6자리를 다시 봐 주세요. ({CODE_TRIES - row[2]}번 남음)", cohort=cohort)
        del self.codes[email]  # 한 번만 쓴다
        return self.start(email, cohort)

    def src(self, rno: str | None) -> str:
        """원문 주소 — 국내 접수번호(숫자)는 DART, 미국 접수번호(0001045810-26-000073)는 SEC 공시 목록 쪽."""
        if not rno:
            return "#"
        if "-" not in rno:
            return notes.DART.format(rno)
        row = self.con.execute("select s.cik from filings f join stocks s using(ticker) where f.accession = ?", (rno,)).fetchone()
        return f"https://www.sec.gov/Archives/edgar/data/{row[0]}/{rno.replace('-', '')}/{rno}-index.htm" if row else "#"

    def stocks_v(self) -> str:
        """종목 목록의 내용 지문 — 주소(?v=)에 붙인다. 브라우저가 하루 저장해 두므로, 내용(순서 포함)이 바뀌면 주소도 바뀌어야 새로 받는다
        (종목 수만 세면 순서를 바꿔도 옛 목록이 남는다 — 눌러 보기 10/11)."""
        return self.cached("stocks_v", lambda: hashlib.sha256(self.stocks_js().encode()).hexdigest()[:10])

    def stocks_js(self) -> str:
        """노트가 있는 종목 먼저(검색하면 위에), 그다음 상장사 전체. 업종은 DART 업종 코드에서 (받아 둔 종목만). 186KB 를 매번 만들지 않게 cached."""
        return self.cached("stocks_js", self._stocks_js)

    def _stocks_js(self) -> str:
        rows = [{"t": t, "n": n, "l": "미국" if m == "US" else "ETF" if t.startswith("ETF") else industry_label(c) or ""} for t, n, c, m in
                self.con.execute("select ticker, name, induty_code, market from stocks s order by active desc,"
                                 " (select count(*) from holdings h where h.ticker = s.ticker) desc, market, name")]  # 많이 담긴 종목 먼저 — 시가총액은 쓸 권리가 없어 모른다  # fmt: skip
        return "window.STOCKS=" + json.dumps(rows, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c") + ";"

    def match(self, q: str) -> str | None:
        """이름·코드 → 종목 코드. 띄어쓰기·대소문자는 무시한다(「삼성 SDI」→ 삼성SDI)."""
        key = re.sub(r"\s+", "", q).upper()
        row = self.con.execute("select ticker from stocks where (ticker = ? or upper(replace(name, ' ', '')) = ?) order by active desc",
                               (key, key)).fetchone()  # 상장사 전체 (코스닥 포함) — 노트가 없던 종목은 다음 아침에 생긴다  # fmt: skip
        return row[0] if row else None

    def add_many(self, uid: int, names: list[str]) -> tuple[list[str], list[str], bool]:
        """(담은 것, 못 찾은 것, 20개가 차서 멈췄나). 이미 담은 종목은 담은 것으로 센다."""
        added, unknown = [], []
        for q in dict.fromkeys(x.strip() for x in names if x.strip()):
            t = self.match(q)
            if not t:
                unknown.append(q)
                continue
            (n,) = self.con.execute("select count(*) from holdings where user_id = ?", (uid,)).fetchone()
            have = self.con.execute("select 1 from holdings where user_id = ? and ticker = ?", (uid, t)).fetchone()
            if not have and n >= MAX_STOCKS:
                return added, unknown, True
            self.con.execute("insert or ignore into holdings values (?, ?, ?)", (uid, t, datetime.now().isoformat()))
            added.append(self.con.execute("select name from stocks where ticker = ?", (t,)).fetchone()[0])
            if not self.con.execute("select 1 from notes where ticker = ?", (t,)).fetchone():
                self.start_first(t)
        self.con.commit()
        return added, unknown, False

    def start_first(self, ticker: str) -> None:
        """노트가 없는 종목을 담으면 그 종목만 바로 받아 첫 노트를 쓴다 — 따로 띄운 실에서 (화면은 기다리지 않는다).
        같은 종목을 여러 사람이 동시에 담아도 한 번만."""
        row = self.con.execute("select market from stocks where ticker = ?", (ticker,)).fetchone()
        if ticker.startswith("ETF") or (row and row[0] != "KR"):  # ETF·미국은 DART 에서 받을 것이 없다 — 각자의 받기가 맡는다
            return
        with self.making_lock:
            if ticker in self.making:
                return
            self.making.add(ticker)

        def run():
            try:
                FIRST(ticker)
            finally:
                with self.making_lock:
                    self.making.discard(ticker)

        threading.Thread(target=run, daemon=True).start()

    @staticmethod
    def added_msg(added: list[str], unknown: list[str], full: bool) -> str:
        parts = [f"{len(added)}종목을 담았어요 ({', '.join(added[:5])}{' 외' if len(added) > 5 else ''})."] if added else []
        if unknown:
            parts.append(f"「{', '.join(unknown[:5])}」은(는) 찾지 못했어요. 국내는 회사 이름이나 종목 코드 6자리, 미국은 티커(NVDA)로 다시 찾아 주세요.")
        if full:
            parts.append(f"종목은 {MAX_STOCKS}개까지 담을 수 있어요.")
        return " ".join(parts) or "담을 종목을 찾지 못했어요."

    def add(self, uid: int, q: str):
        """한 종목, 또는 쉼표·줄바꿈·띄어쓰기로 여러 종목을 한 번에 (「삼성전자, SK하이닉스」)."""
        if not q:
            return self.see("/")
        names = [q] if self.match(q) else [w for part in re.split(r"[,\n;/·]+", q)
                                           for w in ([part] if self.match(part) else part.split())]  # fmt: skip
        added, unknown, full = self.add_many(uid, names)
        if len(names) == 1 and added and not full:
            return self.see("/")
        return self.see("/?msg=" + quote(self.added_msg(added, unknown, full)))

    def scan(self, uid: int, img: str):
        """보유 종목 캡처 → AI 가 종목 이름만 읽는다 → 코드가 우리 종목과 맞춰 담는다. 사진은 저장하지 않는다."""
        def reply(msg, code="200 OK"):
            return code, [("Content-Type", "application/json; charset=utf-8")], json.dumps({"msg": msg}, ensure_ascii=False)

        if not re.match(r"data:image/(jpeg|png|webp);base64,", img):
            return reply("사진을 읽지 못했어요. 캡처 사진(JPG·PNG)을 골라 주세요.", "400 Bad Request")
        now = self.clock()
        times = [t for t in self.scans.get(uid, []) if now - t < 3600]
        if len(times) >= SCAN_HOURLY:
            return reply("사진 읽기는 한 시간에 10번까지예요. 잠시 뒤에 다시 해 주세요.", "429 Too Many Requests")
        self.scans[uid] = times + [now]
        schema = {"type": "object", "additionalProperties": False, "required": ["names"],
                  "properties": {"names": {"type": "array", "items": {"type": "string"}}}}  # fmt: skip
        try:
            with self.outside():  # AI 가 사진을 읽는 수십 초 동안 다른 화면은 돈다
                got = llm.ask("scan", "holdings", {}, lambda j: [str(x) for x in j["names"]][:40], schema, image=img)
        except RuntimeError:
            got = None
        if not got:
            return reply("사진에서 종목을 찾지 못했어요. 증권사 앱의 「보유 종목」 화면을 캡처해 주세요.")
        return reply(self.added_msg(*self.add_many(uid, got)))

    # ---- 내 종목 (시안 _3) ----

    def cards(self, uid: int, msg: str | None, sort: str | None = None) -> str:
        order = "s.name" if sort == "name" else "h.added_at"
        rows = self.con.execute(
            "select s.ticker, s.name, n.week, n.body, n.facts, s.homepage, s.market from holdings h join stocks s using(ticker)"
            " left join notes n on n.ticker = s.ticker and n.week ="
            " (select max(week) from notes where ticker = s.ticker)"
            f" where h.user_id = ? order by {order}", (uid,)).fetchall()  # fmt: skip
        out = []
        both = len({r[6] for r in rows}) > 1  # 국내·미국을 둘 다 담았을 때만 거르기 칩
        for t, name, week, body, facts, home, mkt in rows:  # facts 는 지금 카드에 안 쓴다 (상태 줄은 사용자 요청 10/7로 뺐다)
            b = json.loads(body) if body else {}
            head = (b.get("headline") and notes.mend(b["headline"])) or ("첫 노트를 만들고 있어요. 1~2분 뒤 새로고침해 보세요." if t in self.making else
                                          "새로 담은 종목이에요. 공시 자료를 받는 대로 첫 노트가 나와요(보통 다음 아침 7시).")
            more = " ".join(x["text"] for x in b.get("summary", [])[:4] if x["text"] != head)  # PC 에서만 — 넓은 화면엔 한 줄이 너무 짧다 (사용자 10/8)
            status = "<span></span>"  # 「노트 읽기 →」를 오른쪽에 두는 빈 자리
            out.append(f'<article class="py-4 relative transition-all group" data-stock-id="{e(t)}" data-market="{e(mkt)}"><div class="flex items-start justify-between"><div class="flex items-center gap-2">'
                       f'{logo(name, home, "w-7 h-7")}<a href="/n/{e(t)}"><h2 class="font-headline-sm text-headline-sm text-on-surface font-semibold hover:underline">{e(name)}</h2></a><span class="font-citation-ref text-citation-ref text-outline px-1.5 py-0.5 rounded bg-surface-container-low">{e("ETF" if t.startswith("ETF") else t)}</span>{'<span class="font-citation-ref text-citation-ref text-secondary px-1.5 py-0.5 rounded bg-secondary-fixed/50 font-semibold">미국</span>' if mkt == "US" else ""}<span class="font-label-micro text-label-micro text-outline-variant">{e(week or "")}</span></div>'
                       f'<form method="post" action="/remove"><input type="hidden" name="t" value="{e(t)}"><button aria-label="{e(name)} 삭제" class="w-6 h-6 rounded-full flex items-center justify-center text-outline hover:text-tertiary hover:bg-surface-container transition-colors" type="submit"><span class="material-symbols-outlined text-[16px]">close</span></button></form></div>'
                       f'<a href="/n/{e(t)}"><p class="font-body-reading text-body-reading text-on-surface mt-2 tracking-tight">{e(head)}</p>'
                       + (f'<p class="hidden lg:block mt-1.5 text-[14px] leading-[23px] text-on-surface-variant line-clamp-3">{e(more)}</p>' if more else "") + '</a>'
                       f'<div class="mt-3 flex items-center justify-between">{status}<a class="font-label-micro text-label-micro text-primary flex items-center gap-0.5 hover:underline font-semibold" href="/n/{e(t)}">노트 읽기<span class="material-symbols-outlined text-[14px]">arrow_forward</span></a></div></article>')  # fmt: skip
        note = (f'<p class="font-label-micro text-label-micro text-tertiary px-margin pt-2">{e(msg)}</p>' if msg else "")
        inner = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] lg:max-w-[1200px] mx-auto pt-14 pb-24 lg:pt-20 lg:pb-16 bg-surface min-h-screen"><div class="flex flex-col w-full flex-1">'
                 '<section class="sticky top-0 z-30 bg-surface/95 backdrop-blur-md px-margin py-3 border-b border-surface-container-high transition-all duration-200"><div class="relative w-full">'
                 '<form method="post" action="/add" class="h-11 w-full bg-surface-container-low/60 rounded-xl flex items-center px-3 border border-surface-container-high/60 focus-within:border-primary-container focus-within:bg-surface-container-lowest transition-all"><span class="material-symbols-outlined text-outline text-[20px] mr-2">search</span>'
                 '<input autocomplete="off" class="w-full bg-transparent text-on-surface font-body-compact text-body-compact placeholder:text-outline focus:outline-none" id="stock-search-input" name="q" placeholder="종목 이름 또는 코드로 담기" type="text">'
                 '<button class="shrink-0 ml-1.5 px-3 py-1 bg-primary text-on-primary rounded-lg font-label-micro text-label-micro font-semibold shadow-sm active:scale-95 transition-transform" id="btn-quick-add" type="submit">담기</button>'
                 '<label class="shrink-0 ml-1 w-8 h-8 flex items-center justify-center rounded-lg text-on-surface-variant hover:bg-surface-container cursor-pointer" aria-label="보유 종목 캡처로 담기 (사진을 AI 에 보내 종목 이름을 읽어요)" title="보유 종목 캡처로 담기 — 사진을 AI(OpenAI)에 보내 종목 이름을 읽어요. 저장하지 않아요">'
                 '<span class="material-symbols-outlined text-[20px]">photo_camera</span><input accept="image/*" class="hidden" id="scan-input" type="file"></label></form>'
                 '<div class="hidden fixed inset-0 z-[60] bg-surface/90 backdrop-blur-sm flex-col items-center justify-center gap-3 px-margin text-center" id="scan-wait" role="status">'
                 + tree.line("wait") +
                 '<p class="font-headline-sm text-headline-sm text-on-surface">분석 중…</p>'
                 '<p class="font-body-compact text-body-compact text-on-surface-variant">캡처에서 종목 이름만 읽고 있어요. 사진은 저장하지 않아요.</p></div>'
                 '<div class="hidden absolute left-0 right-0 top-12 mt-1 bg-surface-container-lowest rounded-xl shadow-sm border border-surface-container-high/70 overflow-hidden z-40" id="search-flyout"><div class="p-1.5 flex flex-col gap-0.5" id="search-results"></div></div>'
                 "</div></section>" + note
                 + '<header class="px-margin pt-5 pb-2"><div class="flex items-baseline justify-between mb-1"><div class="flex items-center gap-2"><h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight">내 종목</h1>'
                 f'<span class="font-label-regular text-label-regular text-outline" id="stock-count-badge">{len(rows)} / {MAX_STOCKS}개</span></div>'
                 f'<a class="font-label-micro text-label-micro text-outline hover:text-on-surface transition-colors flex items-center gap-0.5" href="/?sort={"added" if sort == "name" else "name"}"><span class="material-symbols-outlined text-[15px]">tune</span>정렬</a></div>'
                 '</header>'
                 # 아침 한 장 — 내 종목 소식 · 이번 주 · 꿀팁 (docs/growth.md §3-1). 화면에선 AI 를 부르지 않는다(문장은 매일 실행이 미리)
                 + (f'<div class="px-margin pb-2">{morning.html(morning.build(self.con, [r[0] for r in rows], date.today(), uid))}</div>' if rows else "")
                 # 전체 / 국내 / 미국 — 스위치가 아니라 보기 거르기 (노트·메일은 늘 둘 다, docs/stage3-us.md)
                 + ('<nav class="px-margin pb-1 flex gap-1.5" id="market-chips">' + "".join(
                     f'<button type="button" data-m="{m}" class="mchip px-3 py-1 rounded-full text-[12px] font-semibold border {"bg-primary text-on-primary border-primary" if m == "all" else "border-outline-variant/60 text-on-surface-variant"}">{label}</button>'
                     for m, label in (("all", "전체"), ("KR", "국내"), ("US", "미국")))
                    + '</nav><script>document.querySelectorAll(".mchip").forEach(b=>b.onclick=()=>{const m=b.dataset.m;'
                    'document.querySelectorAll(".mchip").forEach(x=>{const on=x===b;x.className=x.className.replace(/bg-primary text-on-primary border-primary|border-outline-variant[/]60 text-on-surface-variant/,on?"bg-primary text-on-primary border-primary":"border-outline-variant/60 text-on-surface-variant")});'
                    'document.querySelectorAll("#stock-list>article").forEach(a=>a.style.display=(m==="all"||a.dataset.market===m)?"":"none")});</script>' if both else "")
                 + f'<section class="px-margin flex flex-col divide-y divide-surface-container-high/80 lg:grid lg:grid-cols-2 lg:gap-x-12 lg:divide-y-0 lg:[&>*]:border-b lg:[&>*]:border-surface-container-high/80" id="stock-list">{"".join(out) or EMPTY_CARDS}</section>'
                 '<footer class="mt-auto px-margin pt-16 pb-6 flex flex-col items-center justify-center gap-1.5 opacity-80"><p class="font-label-micro text-label-micro text-outline text-center flex items-center justify-center gap-1.5"><span class="material-symbols-outlined text-[13px]">mark_email_unread</span>월요일 아침마다 새 노트가 와요. 새 공시·기사가 나오면 매일 아침 고쳐 써요.</p><div class="flex items-center gap-3 text-outline font-label-micro text-label-micro"><span class="">업데이트: 매일 07:00 (바뀐 종목만)</span><span class="">·</span><span class="">공시 데이터: DART 전자공시</span></div>'
                 '<button class="font-label-micro text-label-micro text-outline hover:text-on-surface transition-colors underline underline-offset-4 py-2" onclick="if(confirm(\'현재 계정에서 로그아웃할까요?\'))location.href=\'/logout\'" type="button">로그아웃</button></footer></div>'
                 # 자동완성 — 상장사 전체는 /stocks.js 로 따로 (하루 캐시, 100KB 남짓)
                 f'<script src="/stocks.js?v={self.stocks_v()}"></script><script>'
                 "const STOCKS=window.STOCKS||[];"
                 "const inp=document.getElementById('stock-search-input'),fly=document.getElementById('search-flyout'),res=document.getElementById('search-results');"
                 "function esc(s){return s.replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}"
                 "function draw(){const q=inp.value.trim();if(!q){fly.classList.add('hidden');return;}const Q=q.toUpperCase();const all=STOCKS.filter(s=>s.n.toUpperCase().includes(Q)||s.t.startsWith(Q)),first=s=>s.n.toUpperCase().startsWith(Q)||s.t.startsWith(Q);"
                 "const hit=[...all.filter(first),...all.filter(s=>!first(s))].slice(0,6);"
                 "res.innerHTML=hit.map((s,i)=>"
                 "'<form method=\"post\" action=\"/add\" onclick=\"if(event.target!==this.lastChild)this.requestSubmit()\" class=\"group flex items-center justify-between p-2.5 rounded-lg cursor-pointer hover:bg-surface-container transition-colors\"><input type=\"hidden\" name=\"q\" value=\"'+s.t+'\"><div class=\"flex items-center gap-2 min-w-0\"><span class=\"w-7 h-7 rounded-full bg-primary-fixed text-primary flex items-center justify-center font-body-reading-strong text-[12px]\">'+esc(s.n[0])+'</span><div class=\"flex flex-col min-w-0\"><div class=\"flex items-center gap-1.5\"><span class=\"font-headline-sm text-headline-sm text-on-surface\">'+esc(s.n)+'</span><span class=\"font-citation-ref text-citation-ref text-outline\">'+(s.t.startsWith('ETF')?'':s.t)+'</span></div><span class=\"font-label-micro text-label-micro text-on-surface-variant truncate\">'+esc(s.l)+'</span></div></div>'"
                 "+'<button class=\"px-2.5 py-1 bg-primary-container text-on-primary font-label-micro text-label-micro rounded-lg shadow-sm hover:opacity-90 active:scale-95 transition-all\" type=\"submit\">+ 담기</button>'+'</form>').join('');"
                 "fly.classList.toggle('hidden',hit.length===0);}"
                 "inp.addEventListener('input',draw);inp.addEventListener('focus',draw);"
                 "document.addEventListener('click',ev=>{if(!inp.contains(ev.target)&&!fly.contains(ev.target))fly.classList.add('hidden');});"
                 # 캡처 → 브라우저에서 1600px 로 줄여 JPEG 로 → /scan. 끝나면 결과 문장과 함께 새로 그린다
                 "const sc=document.getElementById('scan-input'),wait=document.getElementById('scan-wait');"
                 "sc.addEventListener('change',async()=>{const f=sc.files[0];if(!f)return;"
                 "if(!confirm('캡처에서 종목 이름을 읽으려고 이 사진을 AI(OpenAI, 미국)에 보내요.\\n한장은 사진을 저장하지 않고, 읽어 낸 종목 이름만 담아요.\\n계좌번호·금액이 보이면 가리고 올려도 돼요.\\n\\n보낼까요?')){sc.value='';return;}"
                 "wait.classList.remove('hidden');wait.classList.add('flex');"
                 "try{const bmp=await createImageBitmap(f);const k=Math.min(1,1600/Math.max(bmp.width,bmp.height));const c=document.createElement('canvas');"
                 "c.width=Math.round(bmp.width*k);c.height=Math.round(bmp.height*k);c.getContext('2d').drawImage(bmp,0,0,c.width,c.height);"
                 "const r=await fetch('/scan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({img:c.toDataURL('image/jpeg',0.85)})});"
                 "const j=await r.json();location.href='/?msg='+encodeURIComponent(j.msg);}"
                 "catch(err){location.href='/?msg='+encodeURIComponent('사진을 읽지 못했어요. 다시 해 주세요.');}});</script></main>"
                 + INSTALL_HINT + bottom_nav("cards"))  # fmt: skip
        return page("내 종목", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    # ---- 설문 (시안에 없는 칸 — 시험 판정에 꼭 필요해 노트 끝에, 시안과 같은 모양으로) ----

    def trial_week(self, uid: int) -> int:
        """시험 몇 주째인가 — 가입한 날이 1주째 (ERD views 의 주차 계산과 같은 기준)."""
        (created,) = self.con.execute("select created_at from users where id = ?", (uid,)).fetchone()
        return (date.today() - date.fromisoformat(created[:10])).days // 7 + 1

    def survey(self, uid: int, ticker: str, week: str, thanks: bool) -> str:
        """주간 설문 (PRD F7) — 1~5 + 한 줄. 6주째부터 「돈 내고도 보겠다」."""
        done = self.con.execute("select 1 from feedback where user_id = ? and ticker = ? and week = ?",
                                (uid, ticker, week)).fetchone()  # fmt: skip
        if thanks or done:
            return ('<section class="mb-space-xl pl-space-md py-1 border-l-2 border-primary/60"><p class="font-body-compact text-body-compact text-on-surface">'
                    "이번 주 노트에 대한 의견 고마워요. 다음 주 노트에 참고할게요.</p></section>")  # fmt: skip
        chip = "px-2.5 py-1 rounded-full border border-outline-variant/60 font-label-micro text-label-micro text-on-surface flex items-center gap-1"
        pay = ('<p class="font-label-regular text-label-regular text-on-surface font-semibold mt-space-sm">이 노트를 돈을 내고도 보시겠어요? 낸다면 한 달에 얼마까지?</p><div class="flex flex-wrap gap-2">'
               + "".join(f'<label class="{chip}"><input type="radio" name="pay" value="{v}" required>{t}</label>'
                         for v, t in ((0, "안 내요"), (1000, "1천 원"), (3000, "3천 원"), (5000, "5천 원"), (10000, "1만 원 이상")))
               + "</div>") if self.trial_week(uid) >= 6 else ""  # fmt: skip
        return (f'<form method="post" action="/feedback" class="mb-space-xl flex flex-col gap-space-sm pt-space-lg border-t border-outline-variant/40">'
                f'<input type="hidden" name="t" value="{e(ticker)}"><input type="hidden" name="w" value="{e(week)}">'
                '<div class="flex items-center gap-2"><span class="w-2 h-2 rounded-full bg-primary"></span><h3 class="font-headline-md text-headline-md text-on-surface">이 노트가 도움이 됐나요?</h3></div>'
                '<input type="range" name="h" min="1" max="5" step="1" value="3" aria-label="도움 정도 1~5" class="w-full accent-primary cursor-pointer">'
                '<div class="flex justify-between px-1 -mt-1 font-label-micro text-label-micro text-on-surface-variant">' + "".join(f"<span>{i}</span>" for i in range(1, 6))
                + '</div><div class="flex justify-between font-label-micro text-label-micro text-outline"><span>별로예요</span><span>아주 좋아요</span></div>'
                + pay + '<input class="w-full font-body-compact text-body-compact bg-surface-container-low text-on-surface placeholder:text-outline rounded-lg px-4 py-3 focus:outline-none" maxlength="300" name="c" placeholder="한 줄 의견 (선택)">'
                '<button class="w-full py-3 bg-primary text-on-primary font-body-reading-strong text-body-reading-strong rounded-lg shadow-sm" type="submit">보내기</button></form>')  # fmt: skip

    def feedback(self, uid: int, form: dict):
        ticker, week, h = form.get("t", ""), form.get("w", ""), form.get("h", "")
        if not (h.isdigit() and 1 <= int(h) <= 5 and re.fullmatch(r"\d{6}", ticker)
                and re.fullmatch(r"\d{4}-\d{2}-\d{2}", week)):
            return self.see("/")
        pay = form.get("pay")
        self.con.execute("insert into feedback (user_id, ticker, week, helpful, would_pay, comment, at)"
                         " values (?, ?, ?, ?, ?, ?, ?)",
                         (uid, ticker, week, int(h), int(pay) if pay and pay.isdigit() else None,
                          form.get("c", "")[:300], datetime.now().isoformat()))  # fmt: skip
        self.con.commit()
        return self.see(f"/n/{ticker}?thanks=1")

    # ---- 기업 노트 (시안 _1) ----

    def note(self, uid: int, ticker: str, thanks: bool = False):
        row = self.con.execute(
            "select s.name, n.week, n.body, n.writer, n.facts, s.induty_code, n.made_at, s.homepage from stocks s join notes n using(ticker)"
            " where s.ticker = ? order by n.week desc limit 1", (ticker,)).fetchone()  # fmt: skip
        if not row:
            return "404 Not Found", [], self.simple("없음", "이 종목은 아직 노트가 없어요. <a class='text-primary underline' href='/'>내 종목</a>")
        name, week, body, writer, facts, ind, made, home = row
        (views,) = self.con.execute("select count(*) from views where page = 'note' and ticker = ? and at >= ?", (ticker, week)).fetchone()
        (likes,) = self.con.execute("select count(*) from likes where ticker = ? and week = ?", (ticker, week)).fetchone()
        liked = bool(self.con.execute("select 1 from likes where user_id = ? and ticker = ? and week = ?", (uid, ticker, week)).fetchone())
        return "200 OK", [], render_note(name, ticker, week, json.loads(body), writer, json.loads(facts), ind,
                                         self.initial(uid), self.survey(uid, ticker, week, thanks), made, home, (views, likes, liked),
                                         self.regram_form(uid, "note", ticker, week),
                                         prices=self.con.execute("select date, close from prices where ticker = ? order by date", (ticker,)).fetchall()
                                         if sources.price_dev() else None, report=self.report(ticker) | {"owners": self.owners(ticker)})  # fmt: skip

    def report(self, ticker: str) -> dict:
        if self.con.execute("select 1 from stocks where ticker = ? and market = 'US'", (ticker,)).fetchone():
            # 미국 — 「한눈에 보기」 그림·배당 막대는 원 단위·DART 서식이라 넘기지 않는다(달러 숫자에 「원」이 붙었다, 10/10). 같은 숫자는 본문에 있다
            biz = self.con.execute("select body, rcept_no from business where ticker = ?", (ticker,)).fetchone()
            return {"divs": [], "biz": json.loads(biz[0]) if biz else None, "rno": self.src(biz[1]) if biz else None,
                    "fin": None, "fins": None, "buys": [], "mid": {}, "us": True}  # fmt: skip
        divs = self.con.execute("select fiscal_year, dps, total, payout from dividends where ticker = ? order by fiscal_year", (ticker,)).fetchall()
        biz = self.con.execute("select body, rcept_no from business where ticker = ?", (ticker,)).fetchone()
        fins = self.con.execute("select fiscal_year, revenue, operating_income, net_income, equity, liabilities from financials"
                                " where ticker = ? order by fiscal_year desc limit 2", (ticker,)).fetchall()  # fmt: skip
        fin = fins[0] if fins else None
        buys = self.con.execute("select date, amount from disclosures where ticker = ? and code = 'BUYBACK' and amount > 0 and date >= ?",
                                (ticker, (date.today() - timedelta(days=365)).isoformat())).fetchall()  # fmt: skip
        return {"divs": divs, "biz": json.loads(biz[0]) if biz else None, "rno": (self.src(biz[1]) if "-" in biz[1] else biz[1]) if biz else None, "fin": fin, "fins": fins, "buys": buys,
                "mid": notes.industry_mid(self.con, ticker)}

    # ---- 캘린더 (시안 _4) ----

    def calendar(self, uid: int, month: str | None, today: date | None = None, sort: str | None = None) -> str:
        """④ 캘린더 — 한 달 달력. 주말·공휴일은 빨간 숫자, 칸 안에 내 종목의 공시.
        앞으로의 일정(events — 공시 원문에서 읽은 실적 발표·주총·배당)은 테두리 칩으로 따로 보인다."""
        today = today or date.today()
        y, m = (int(x) for x in month.split("-")) if month and re.fullmatch(r"\d{4}-\d{2}", month) else (today.year, today.month)
        y, m = (y, m) if 1 <= m <= 12 and 2000 <= y <= 2100 else (today.year, today.month)
        weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(y, m)  # 일요일부터
        lo, hi = weeks[0][0].isoformat(), weeks[-1][-1].isoformat()
        hol = dict(self.con.execute("select date, name from holidays where date between ? and ?", (lo, hi)))
        if (end := date(y, 12, 31)).weekday() < 5 and m == 12:
            hol.setdefault(end.isoformat(), "증시 휴장")  # 연말 휴장 — 공휴일 자료엔 없다
        rows = self.con.execute(
            "select d.date, s.name, d.code, d.title, d.rcept_no, d.direction, s.ticker, d.amount, d.importance from disclosures d"
            " join holdings h on h.ticker = d.ticker and h.user_id = ? join stocks s on s.ticker = d.ticker"
            " where d.date between ? and ? and d.importance >= 2 and d.code != 'OTHER' order by d.date",
            (uid, lo, hi)).fetchall()  # fmt: skip
        # 같은 날 같은 회사의 같은 종류 공시는 하나로 묶는다 — 계약 두 건, 자사주 취득·소각이 같은 말로 두 번 나오지 않게 (사용자 10/9)
        grouped: dict[tuple, list] = {}
        for r in rows:
            grouped.setdefault((r[0], r[6], r[2]), []).append(r)
        by: dict[str, list] = {}
        for (d, _, _), rs in grouped.items():
            by.setdefault(d, []).append(rs)
        macro = sources.macro_events(lo, hi)
        has_us = self.con.execute("select 1 from holdings h join stocks s using(ticker) where h.user_id = ? and s.market = 'US'", (uid,)).fetchone()
        macro = [x for x in macro if x[1] != "휴장" or has_us]  # 미국 휴장일은 미국 종목을 담은 사람에게만
        macro_by: dict[str, list] = {}
        for x in macro:
            macro_by.setdefault(x[0], []).append(x)
        # 내 종목 회사채 — 납입일(돈이 실제로 들어오는 날)에 칩. 같은 신고서의 회차(2년물·3년물)는 하나로
        bonds = self.con.execute(
            "select b.rcept_no, min(b.pay_date), s.name, s.ticker, sum(b.amount), group_concat(b.maturity), group_concat(b.uses, '|'), max(b.lead)"
            " from bonds b join holdings h on h.ticker = b.ticker and h.user_id = ? join stocks s on s.ticker = b.ticker"
            " where b.pay_date between ? and ? group by b.rcept_no order by 2", (uid, lo, hi)).fetchall()  # fmt: skip
        bond_by: dict[str, list] = {}
        for x in bonds:
            bond_by.setdefault(x[1], []).append(x)
        # 공모주 — 시장 전체(내 종목 아님). 한 달 수십 곳이라 칩은 청약 첫날·상장 예정일에만, 금리·물가 칩 뒤에
        ipos = self.con.execute("select name, sub_start, sub_end, list_date, price, total, lead, uses, rcept_no from ipos"
                                " where sub_start between ? and ? or list_date between ? and ? order by sub_start", (lo, hi, lo, hi)).fetchall()  # fmt: skip
        ipo_by: dict[str, list] = {}
        for x in ipos:
            ipo_by.setdefault(x[1], []).append((x[0], "청약", x[8]))
            if x[3]:
                ipo_by.setdefault(x[3], []).append((x[0], "상장", x[8]))
        ahead: dict[str, list] = {}  # 공시에서 읽은 일정(실적 발표·주총·배당 기준일·지급일) — 테두리 칩으로 지난 공시와 구분
        for d, name, kind, what, rno in self.con.execute(
                "select e.date, s.name, e.kind, e.title, e.rcept_no from events e join holdings h on h.ticker = e.ticker and h.user_id = ?"
                " join stocks s on s.ticker = e.ticker where e.date between ? and ? order by e.date", (uid, lo, hi)):  # fmt: skip
            ahead.setdefault(d, []).append((name, kind, what, rno))
        mine = sorted((rs for rs in grouped.values() if rs[0][0][:7] == f"{y}-{m:02d}"), key=lambda rs: rs[0][0], reverse=True)  # 최신순
        kinds: dict[str, int] = {}
        for rs in mine:
            kinds[rs[0][2]] = kinds.get(rs[0][2], 0) + 1
        prev = f"{y - (m == 1)}-{(m - 2) % 12 + 1:02d}"
        nxt = f"{y + (m == 12)}-{m % 12 + 1:02d}"
        cells = []
        for wk in weeks:
            for i, d in enumerate(wk):
                iso = d.isoformat()
                if d.month != m:
                    num = f'<span class="font-label-micro text-label-micro lg:text-[14px] text-outline-variant">{d.day}</span>'
                elif d == today:
                    num = (f'<div class="flex items-center justify-between"><span class="w-5 h-5 flex items-center justify-center rounded-full bg-primary-container text-on-primary font-label-micro text-label-micro font-bold">{d.day}</span>'
                           '<span class="text-[8px] text-primary-container font-semibold">오늘</span></div>')  # fmt: skip
                elif iso in hol:  # 공휴일은 시안대로 검은 숫자 + 이름 (사용자 10/7: 시안 그대로)
                    num = f'<span class="font-label-micro text-label-micro lg:text-[14px] text-on-surface font-medium">{d.day}</span>'
                elif i in (0, 6):  # 주말은 빨간 숫자
                    num = f'<span class="font-label-micro text-label-micro lg:text-[14px] text-tertiary font-semibold">{d.day}</span>'
                else:
                    num = f'<span class="font-label-micro text-label-micro lg:text-[14px] text-on-surface">{d.day}</span>'
                cell = num
                if iso in hol and d.month == m:
                    cell += f'<span class="text-[8px] lg:text-[11px] text-on-surface-variant leading-tight line-clamp-1 mt-0.5">{e(hol[iso])}</span>'
                # 칸 안 칩은 한 줄 — 넘치면 말줄임(…), 전체 이름은 마우스를 올리면·오른쪽 목록에서. 칸마다 셋까지, 나머지는 「+N」 (사용자 10/9: 줄바꿈이 별로)
                chips = []
                for rs in by.get(iso, []) if d.month == m else []:
                    _, name, code, _, rno, dr, _, _, _ = rs[0]
                    tint = {1: "bg-secondary-fixed text-on-secondary-fixed-variant", -1: "bg-tertiary-fixed text-on-tertiary-fixed-variant"}.get(dr, "bg-surface-container-high text-on-surface-variant")
                    many = f" {len(rs)}건" if len(rs) > 1 else ""
                    chips.append(f'<span title="{e(name)} {e(EVENT_SHORT.get(code, ""))}{many}" class="{CHIP} {tint}">'
                                 f"<span class='lg:hidden'>{e(short_name(name))}</span><span class='hidden lg:inline'>{e(name)}</span> {e(EVENT_SHORT.get(code, ''))}{many}</span>")  # fmt: skip
                for rno, _, name, _, total, *_ in bond_by.get(iso, []) if d.month == m else []:
                    chips.append(f'<span title="{e(name)} 회사채 {e(notes.won(total))}" class="{CHIP} bg-surface-container-high text-on-surface-variant">'
                                 f"<span class='lg:hidden'>{e(short_name(name))} 채권</span><span class='hidden lg:inline'>{e(name)} 회사채 {e(notes.won(total))}</span></span>")  # fmt: skip
                for name, kind, what, rno in ahead.get(iso, []) if d.month == m else []:
                    chips.append(f'<span title="{e(name)} {e(what)}" class="{CHIP} border border-primary/40 text-primary">'
                                 f"<span class='lg:hidden'>{e(short_name(name))} {AHEAD_SHORT.get(kind, '')}</span><span class='hidden lg:inline'>{e(name)} {e(what)}</span></span>")  # fmt: skip
                for _, kind, nat, what in macro_by.get(iso, []) if d.month == m else []:
                    chips.append(f'<span title="{e(what)}" class="{CHIP} border border-dashed border-outline-variant text-on-surface-variant">'
                                 f"<span class='lg:hidden'>{FLAG[nat]} {e(kind)}</span><span class='hidden lg:inline'>{e(what)}</span></span>")  # fmt: skip
                for name, what, rno in ipo_by.get(iso, []) if d.month == m else []:
                    chips.append(f'<span title="{e(name)} 공모주 {what}" class="{CHIP} border border-secondary/50 text-secondary">'
                                 f"<span class='lg:hidden'>{e(short_name(name))} {what}</span><span class='hidden lg:inline'>{e(name)} 공모주 {what}</span></span>")  # fmt: skip
                cell += "".join(chips[:3]) + (f'<span class="mt-0.5 text-[9px] lg:text-[11px] text-outline">+{len(chips) - 3}</span>' if len(chips) > 3 else "")
                pick = f' data-day="{iso}" onclick="pickDay(this.dataset.day)"' if d.month == m else ""  # 칸 어디를 눌러도(칩 포함) 그날 일정 — 칩은 원문 링크가 아니다(사용자 10/10: 누르면 원문으로 넘어가 힘들다) 일정
                cells.append(f'<div{pick} class="min-h-[52px] lg:min-h-[112px] p-1 lg:p-2 rounded-lg flex flex-col justify-start lg:border-t lg:border-surface-container-high {"lg:bg-surface-container-low/60" if d.month != m else "cursor-pointer hover:bg-surface-container-low"}">{cell}</div>')
        items = []
        minor = set()  # 「이 달의 일정」 목록에서 뺄 것 — 달력 칸·그날 일정에는 그대로 (사용자 10/10: 너무 많다, 덜 중요한 건 빼)
        for rs in mine:
            d, name, code, title, rno, dr, t, _, imp = rs[0]
            if not (dr or imp >= 3 or (code == "EARNINGS" and not re.match(r"판매|예비", title) and "예고" not in title)):
                minor.add(len(items))  # 좋고 나쁨이 없는 보통 공시(판매 대수 알림·실적 발표 예고 등)
            dd = date.fromisoformat(d)
            label, chip = TONE_TAG.get(dr or 0, TONE_TAG[0])
            src = ("SEC 공시: " if "-" in rno else "DART 공시: ") + " · ".join(dict.fromkeys(re.sub(r"^\[[^\]]*\]", "", r[3]) + (f" {notes.won(r[7])} 규모" if r[7] else "") for r in rs))
            title = clean_title(title, code) + (f" 외 {len(rs) - 1}건" if len(rs) > 1 else "")
            items.append((1, d, f'<article class="py-3.5 border-b border-surface-container-high flex flex-col gap-1 transition-colors hover:bg-surface-container-low/40"><div class="flex items-center justify-between">'
                         f'<span class="font-label-micro text-label-micro text-on-surface-variant">{dd.month}월 {dd.day}일 ({"월화수목금토일"[dd.weekday()]}) · {e(name)} ({e(t)})</span>'
                         f'<span class="font-label-micro text-label-micro px-2 py-0.5 rounded-full {chip} font-semibold">{label}</span></div>'
                         f'<h3 class="font-headline-sm text-headline-sm text-on-surface font-semibold">{e(title)}</h3>'
                         f'<p class="font-body-compact text-body-compact text-on-surface-variant leading-relaxed">{e(EVENT_EXPLAIN.get(code, ""))}</p>'
                         f'<div class="flex items-center gap-1.5 text-on-surface-variant font-citation-ref text-citation-ref pt-0.5"><span class="material-symbols-outlined {"text-tertiary" if dr == -1 else "text-primary"} text-[15px]">{"info" if dr == -1 else "verified"}</span><a href="{e(self.src(rno))}" target="_blank" rel="noopener" class="underline underline-offset-2 decoration-outline-variant hover:text-on-surface">{e(src)}</a></div></article>'))  # fmt: skip
        soon = [(d, *x) for d in sorted(ahead) if d[:7] == f"{y}-{m:02d}" for x in ahead[d]]
        items += [(0, d, f'<article class="py-3.5 border-b border-surface-container-high flex items-center justify-between gap-2">'
                 f'<span class="font-body-compact text-body-compact text-on-surface"><span class="text-on-surface-variant">{(dd := date.fromisoformat(d)).month}월 {dd.day}일 ({"월화수목금토일"[dd.weekday()]})</span> · {e(name)} <b>{e(what)}</b></span>'
                 f'<span class="flex items-center gap-2 flex-shrink-0"><a href="{e(self.src(rno))}" target="_blank" rel="noopener" class="underline underline-offset-2 decoration-outline-variant hover:text-on-surface font-citation-ref text-citation-ref text-on-surface-variant">원문</a><span class="font-label-micro text-label-micro px-2 py-0.5 rounded-full border border-primary/40 text-primary font-semibold">일정</span></span></article>')
                  for d, name, _, what, rno in soon]  # fmt: skip
        for rno, pay, name, t, total, mats, uses, lead in bonds:  # 내 종목 회사채 — 공시와 같은 자리
            if pay[:7] != f"{y}-{m:02d}":
                continue
            dp = date.fromisoformat(pay)
            say = "회사가 채권을 팔아 돈을 빌려요."
            items.append((1, pay, f'<article class="py-3.5 border-b border-surface-container-high flex flex-col gap-1">'
                          f'<div class="flex items-center justify-between"><span class="font-label-micro text-label-micro text-on-surface-variant">{dp.month}월 {dp.day}일 ({"월화수목금토일"[dp.weekday()]}) 납입 · {e(name)} ({e(t)})</span>'
                          '<span class="font-label-micro text-label-micro px-2 py-0.5 rounded-full bg-surface-container-high text-on-surface-variant font-semibold">회사채</span></div>'
                          f'<h3 class="font-headline-sm text-headline-sm text-on-surface font-semibold">{e(name)} 회사채 {e(notes.won(total))}</h3>'
                          f'<p class="font-body-compact text-body-compact text-on-surface-variant leading-relaxed">{e(say)}</p>'
                          f'<a href="{e(self.src(rno))}" target="_blank" rel="noopener" class="underline underline-offset-2 decoration-outline-variant hover:text-on-surface self-start font-citation-ref text-citation-ref text-on-surface-variant pt-0.5">출처: DART 증권신고서(채무증권)</a></article>'))  # fmt: skip
        for name, a, b, listed, price, total, lead, uses, rno in ipos:  # 공모주 — 맨 뒤 (금리·물가가 더 많은 사람에게 닿는다)
            d = a if a[:7] == f"{y}-{m:02d}" else listed if listed and listed[:7] == f"{y}-{m:02d}" else None
            if not d:
                continue
            da, db_ = date.fromisoformat(a), date.fromisoformat(b)
            say = "새로 상장하려는 회사가 주식을 팔아 돈을 모아요."
            minor.add(len(items))  # 공모주는 한 달 수십 곳 — 목록에선 한 줄로 모은다
            items.append((9, d, f'<article class="py-3.5 border-b border-surface-container-high flex flex-col gap-1">'
                          f'<div class="flex items-center justify-between"><span class="font-label-micro text-label-micro text-on-surface-variant">{da.month}월 {da.day}일 ~ {db_.month}월 {db_.day}일 청약 · 시장 전체</span>'
                          '<span class="font-label-micro text-label-micro px-2 py-0.5 rounded-full border border-secondary/50 text-secondary font-semibold">공모주</span></div>'
                          f'<h3 class="font-headline-sm text-headline-sm text-on-surface font-semibold">{e(name)} 공모주 청약</h3>'
                          f'<p class="font-body-compact text-body-compact text-on-surface-variant leading-relaxed">{e(say)}</p>'
                          f'<a href="{e(self.src(rno))}" target="_blank" rel="noopener" class="underline underline-offset-2 decoration-outline-variant hover:text-on-surface self-start font-citation-ref text-citation-ref text-on-surface-variant pt-0.5">출처: DART 증권신고서(지분증권)</a></article>', {x for x in (a, listed) if x}))  # fmt: skip
        for d, kind, nat, what in macro:  # 시장 일정 — 내 종목 일정·공시 다음, 금리 → 물가 → 선거 → 고용
            if d[:7] != f"{y}-{m:02d}":
                continue
            dd, (who, url) = date.fromisoformat(d), sources.MACRO_SOURCE[nat + kind]
            items.append((1 + sources.MACRO_RANK[kind], d, f'<article class="py-3.5 border-b border-surface-container-high flex flex-col gap-1">'
                          f'<div class="flex items-center justify-between"><span class="font-label-micro text-label-micro text-on-surface-variant">{dd.month}월 {dd.day}일 ({"월화수목금토일"[dd.weekday()]}) · 시장 전체</span>'
                          '<span class="font-label-micro text-label-micro px-2 py-0.5 rounded-full border border-dashed border-outline-variant text-on-surface-variant font-semibold">시장 일정</span></div>'
                          f'<h3 class="font-headline-sm text-headline-sm text-on-surface font-semibold">{e(what)}</h3>'
                          f'<p class="font-body-compact text-body-compact text-on-surface-variant leading-relaxed">{e(sources.MACRO_EXPLAIN[(kind, nat)])}</p>'
                          f'<a href="{e(url)}" target="_blank" rel="noopener" class="underline underline-offset-2 decoration-outline-variant hover:text-on-surface self-start font-citation-ref text-citation-ref text-on-surface-variant pt-0.5">일정 출처: {e(who)}</a></article>'))  # fmt: skip
        ipo_n = len(minor & {i for i, x in enumerate(items) if x[0] == 9})
        items = [(*x[:3], x[3] if len(x) > 3 else {x[1]}, i in minor) for i, x in enumerate(items)]
        items.sort(key=lambda x: (x[0], x[1]))  # 관련 높은 순 — 내 종목 일정 → 내 종목 공시 → 시장 일정
        days: dict[str, list] = {}  # 달력에서 고른 날의 일정 — 같은 순서로, 공모주는 청약 첫날·상장일 둘 다. 덜 중요한 것도 여기엔 다
        for x in items:
            for dd_ in x[3]:
                days.setdefault(dd_, []).append(x[2])
        sort = sort if sort in ("new", "old") else "rel"  # 이 달의 일정 — 관련 높은 순(기본) · 최신순 · 날짜순
        if sort != "rel":
            items.sort(key=lambda x: x[1], reverse=sort == "new")
        items = [x[2] for x in items if not x[4]]
        if ipo_n:
            items.append(f'<a href="#calendar-grid" class="py-3.5 border-b border-surface-container-high flex items-center justify-between gap-2 font-body-compact text-body-compact text-on-surface-variant hover:text-on-surface">'
                         f'<span class="flex items-center gap-2"><span class="material-symbols-outlined text-secondary text-[18px]">campaign</span>이 달 공모주 청약 {ipo_n}곳 — 달력 칸을 눌러 날마다 볼 수 있어요</span>'
                         '<span class="material-symbols-outlined text-[16px]">expand_less</span></a>')  # fmt: skip
        pick = today.isoformat() if (today.year, today.month) == (y, m) else f"{y}-{m:02d}-01"  # 처음엔 오늘, 다른 달이면 1일
        day_lists = "".join(f'<div data-list="{d}"{"" if d == pick else " hidden"}>{"".join(h)}</div>' for d, h in days.items() if d[:7] == f"{y}-{m:02d}")
        day_none = f'<p data-list="none" class="py-3.5 font-body-compact text-body-compact text-on-surface-variant"{" hidden" if pick in days else ""}>이 날은 일정이 없어요.</p>'
        pick_js = ("<script>function pickDay(d){var t=new Date(d+'T00:00');"
                   f"document.getElementById('day-title').textContent=d=='{today.isoformat()}'?'오늘 일정':(t.getMonth()+1)+'월 '+t.getDate()+'일 ('+'일월화수목금토'[t.getDay()]+') 일정';"
                   "var hit=false;document.querySelectorAll('[data-list]').forEach(function(x){var on=x.dataset.list==d;x.hidden=!on;hit=hit||on});"
                   "document.querySelector('[data-list=none]').hidden=hit;"
                   "document.querySelectorAll('[data-day]').forEach(function(c){c.classList.toggle('bg-primary-fixed',c.dataset.day==d)})}"
                   f"pickDay('{pick}')</script>")  # fmt: skip
        if not items:
            items.append('<p class="py-3.5 font-body-compact text-body-compact text-on-surface-variant">이 달엔 내 종목의 큰 공시가 없어요.</p>')
        # 이 달 일정에 나온 공시 종류마다 그에 맞는 읽기 팁 글 — 많이 나온 종류부터, 같은 글은 한 번, 최대 3편
        picks = {}
        for kind in sorted(kinds, key=kinds.get, reverse=True):
            picks.setdefault(learn.FOR_EVENT.get(kind, "disclosure"), kind)
        tips = "".join(
            f'<a href="/learn/{slug}" class="py-3 flex items-center gap-space-md"><div class="w-12 h-12 rounded-lg flex-shrink-0 bg-surface-container flex items-center justify-center"><span class="material-symbols-outlined text-primary text-[22px]">menu_book</span></div>'
            f'<div class="flex flex-col gap-0.5 min-w-0"><span class="font-label-micro text-label-micro text-outline">이 달 {e(EVENT_SHORT.get(kind, kind))} 공시와 관련</span>'
            f'<p class="font-body-compact text-body-compact text-on-surface font-semibold truncate">{e(learn.BY_SLUG[slug]["title"])}</p>'
            f'<span class="font-label-micro text-label-micro text-on-surface-variant truncate">{e(TIPS.get(kind, TIP_DEFAULT)[0])}</span></div>'
            '<span class="material-symbols-outlined text-outline text-[18px] ml-auto">chevron_right</span></a>'
            for slug, kind in list(picks.items())[:3]) or (
            '<a href="/learn/disclosure" class="py-3 flex items-center gap-space-md"><div class="w-12 h-12 rounded-lg flex-shrink-0 bg-surface-container flex items-center justify-center"><span class="material-symbols-outlined text-primary text-[22px]">menu_book</span></div>'
            f'<div class="flex flex-col gap-0.5 min-w-0"><p class="font-body-compact text-body-compact text-on-surface font-semibold">{e(learn.BY_SLUG["disclosure"]["title"])}</p>'
            f'<span class="font-label-micro text-label-micro text-on-surface-variant">{e(TIP_DEFAULT[0])}</span></div></a>')  # fmt: skip
        mix = " · ".join(f"{EVENT_SHORT.get(k, k)} {v}" for k, v in kinds.items()) or "큰 공시 없음"
        inner = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] lg:max-w-[1200px] mx-auto pt-14 pb-24 lg:pt-20 lg:pb-16 bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-6 gap-space-lg">'
                 '<header class="flex flex-col pt-space-xs gap-space-xs"><div class="flex items-center justify-between"><div class="flex items-baseline gap-space-xs">'
                 f'<h1 class="font-headline-lg text-headline-lg lg:text-[32px] lg:leading-[40px] text-on-surface tracking-tight">{y}년 {m}월</h1><span class="font-label-micro text-label-micro text-on-surface-variant">공시 타임라인</span></div>'
                 '<nav class="hidden lg:flex items-center gap-2 text-[13px]">'
                 f'<a class="flex items-center gap-0.5 px-3 py-1.5 rounded-full border border-outline-variant/60 text-on-surface-variant hover:bg-surface-container" href="/calendar?m={prev}"><span class="material-symbols-outlined text-[16px]">chevron_left</span>이전 달</a>'
                 f'<a class="px-3 py-1.5 rounded-full bg-primary text-on-primary font-semibold" href="/calendar">오늘</a>'
                 f'<a class="flex items-center gap-0.5 px-3 py-1.5 rounded-full border border-outline-variant/60 text-on-surface-variant hover:bg-surface-container" href="/calendar?m={nxt}">다음 달<span class="material-symbols-outlined text-[16px]">chevron_right</span></a></nav>'
                 '</div>'
                 '<p class="font-body-compact text-body-compact text-on-surface-variant">관심 기업의 주요 의사결정과 공시 기록을 날짜별로 천천히 짚어드려요.</p></header>'
                 '<section class="py-space-sm px-1 flex items-center justify-between border-b border-surface-container-high"><div class="flex items-center gap-space-sm"><span class="material-symbols-outlined text-primary text-[20px]">calendar_clock</span><div class="flex items-baseline gap-space-xs">'
                 f'<span class="font-label-regular text-label-regular text-on-surface font-semibold">이번 달 주목할 공시 {len(mine)}건</span><span class="font-label-micro text-label-micro text-on-surface-variant">{e(mix)}</span></div></div>'
                 '</section>'
                 '<div class="flex flex-col gap-space-lg lg:grid lg:grid-cols-[minmax(0,1fr)_380px] lg:gap-10 lg:items-start">'
                 '<section id="calendar-grid" class="flex flex-col gap-1 py-1 lg:rounded-2xl lg:border lg:border-surface-container-high lg:p-4"><div class="grid grid-cols-7 text-center font-label-micro text-label-micro font-semibold pb-1.5 lg:pb-2.5 lg:text-[13px] border-b border-surface-container-high/60"><span class="text-tertiary">일</span><span class="text-on-surface-variant">월</span><span class="text-on-surface-variant">화</span><span class="text-on-surface-variant">수</span><span class="text-on-surface-variant">목</span><span class="text-on-surface-variant">금</span><span class="text-tertiary">토</span></div>'
                 f'<div class="grid grid-cols-7 gap-1 lg:gap-0 pt-1 lg:pt-0">{"".join(cells)}</div>'
                 '<nav class="flex justify-center items-center gap-5 pt-2 text-[12px] text-outline">'
                 f'<a class="flex items-center hover:text-on-surface-variant" href="/calendar?m={prev}"><span class="material-symbols-outlined text-[14px]">chevron_left</span>이전 달</a>'
                 f'<a class="flex items-center hover:text-on-surface-variant" href="/calendar?m={nxt}">다음 달<span class="material-symbols-outlined text-[14px]">chevron_right</span></a></nav></section>'
                 '<aside class="flex flex-col gap-space-lg lg:sticky lg:top-20"><section class="flex flex-col mt-2 lg:mt-0"><div class="pb-2 border-b border-surface-container-highest"><h2 id="day-title" class="font-headline-md text-headline-md text-on-surface">오늘 일정</h2></div>'
                 f'{day_lists}{day_none}</section><section class="flex flex-col"><div class="flex items-center justify-between pb-2 border-b border-surface-container-highest"><div class="flex items-center gap-space-xs"><h2 class="font-headline-md text-headline-md text-on-surface">이 달의 일정</h2></div>'
                 '<a class="font-label-regular text-label-regular text-primary flex items-center hover:opacity-80 transition-opacity" href="https://dart.fss.or.kr" target="_blank" rel="noopener">전체 공시 원문<span class="material-symbols-outlined text-[15px] ml-0.5">arrow_forward</span></a></div>'
                 + '<nav id="month-list" class="scroll-mt-24 pt-2.5 pb-1 flex gap-1.5" aria-label="정렬">' + "".join(
                     f'<a href="/calendar?m={y}-{m:02d}&s={k}#month-list" class="px-3 py-1 rounded-full text-[12px] font-semibold border '
                     + ("bg-primary text-on-primary border-primary" if k == sort else "border-outline-variant/60 text-on-surface-variant hover:bg-surface-container") + f'">{label}</a>'
                     for k, label in (("rel", "관련 높은 순"), ("new", "최신순"), ("old", "날짜순"))) + "</nav>"
                 + f'<div class="flex flex-col">{"".join(items)}</div></section>'
                 '<section class="pt-4 border-t border-surface-container-high flex flex-col"><span class="font-label-regular text-label-regular text-primary font-bold">주주를 위한 읽기 팁</span>'
                 f'<div class="flex flex-col divide-y divide-surface-container-high/70">{tips}</div></section></aside></div>'
                 '<footer class="mt-2 text-center flex flex-col items-center gap-1"><div class="w-8 h-0.5 bg-surface-container-high rounded-full mb-1"></div><p class="font-citation-ref text-citation-ref text-on-surface-variant leading-relaxed max-w-[340px]">색 칩은 지난 공시, 테두리 칩은 공시에 적힌 앞으로의 일정(실적 발표·주총·배당), 점선 칩은 금리·물가·고용·선거 같은 시장 일정이에요. 공휴일: 한국천문연구원.</p></footer>'
                 "</div></main>" + bottom_nav("calendar") + pick_js)  # fmt: skip
        return page("캘린더", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)


    # ---- 내 프로필 (시안에 없는 화면 — 같은 디자인 말투로. 가진 정보만) ----

    def profile(self, uid: int) -> str:
        """내 프로필 — 남이 보는 모양 그대로(이름·자기소개·팔로워·리그램). 설정은 오른쪽 위 톱니바퀴."""
        email, nick, bio, at = self.con.execute("select email, nickname, bio, photo_at from users where id = ?", (uid,)).fetchone()
        inner = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] lg:max-w-[760px] mx-auto pt-14 pb-24 lg:pt-20 lg:pb-16 bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-6">'
                 f'<header class="pt-5 flex items-center gap-space-md">{self.face(nick or email, "w-14 h-14", photo_url(uid, at))}<div class="flex flex-col min-w-0 flex-1">'
                 f'<h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight truncate">{e(nick or "내 프로필")}</h1>{self.follow_line(uid)}</div>'
                 '<a href="/me/settings" aria-label="설정" class="w-10 h-10 rounded-full flex items-center justify-center text-on-surface-variant hover:bg-surface-container"><span class="material-symbols-outlined text-[22px]">settings</span></a></header>'
                 + (f'<p class="mt-space-md font-body-compact text-body-compact text-on-surface whitespace-pre-line">{e(bio)}</p>' if bio else "")
                 + self.my_tree(uid)  # 내 나무는 맨 위, 위아래로 넉넉히 띄워서 (사용자 10/11)
                 + self.regram_list("where r.user_id = ?", (uid,), "내 리그램", mine=True)
                 + self.suggest(uid)
                 + "</div></main>" + bottom_nav("me"))  # fmt: skip
        return page("내 프로필", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    def my_tree(self, uid: int, today: date | None = None, nick: str | None = None) -> str:
        """내 나무 — 들어온 날이 쌓일수록 자라는 나무와 최근 석 달 잔디 (사용자 10/11). 들어온 날 = 화면을 한 번이라도 연 날(views).
        nick 을 주면 남의 프로필에 보이는 모양 — 나무와 날 수만(언제 들어왔는지 보이는 잔디·다음 단계는 본인만). 비공개 계정은 부르는 쪽이 거른다."""
        today = today or date.today()
        counts = dict(self.con.execute("select substr(at, 1, 10), count(*) from views where user_id = ? group by 1", (uid,)).fetchall())
        if nick is None:
            counts.setdefault(today.isoformat(), 1)  # 지금 이 화면을 보고 있다
        n = self.con.execute("select days from users where id = ?", (uid,)).fetchone()[0] or len(counts)  # 누적 — 기록이 지워져도 줄지 않는다
        name, left = tree.stage(n)
        if nick is not None:
            return ('<section class="mt-space-xl mb-12 pb-space-xl border-b border-surface-container-high"><div class="flex items-center gap-2"><span class="w-2 h-2 shrink-0 rounded-full bg-primary"></span>'
                    f'<h2 class="text-[16px] font-bold text-on-surface">{e(nick)}의 나무</h2></div>'
                    f'<div class="mx-auto w-full max-w-[300px]">{tree.svg(n)}</div>'
                    f'<p class="text-center text-[16px] font-bold text-primary">{e(name)}</p>'
                    f'<p class="mt-0.5 text-center font-body-compact text-body-compact text-on-surface-variant">지금까지 {n}일 들어왔어요</p></section>')  # fmt: skip
        grass, came = tree.grass(counts, today)
        nxt = f" · {dict(tree.STAGES)[n + left]}까지 {left}일" if left else ""
        return ('<section class="mt-space-xl mb-12 pb-space-xl border-b border-surface-container-high"><div class="flex items-center gap-2"><span class="w-2 h-2 shrink-0 rounded-full bg-primary"></span>'
                '<h2 class="text-[16px] font-bold text-on-surface">내 나무</h2></div>'
                f'<div class="mx-auto w-full max-w-[300px]">{tree.svg(n)}</div>'
                f'<p class="text-center text-[16px] font-bold text-primary">{e(name)}</p>'
                f'<p class="mt-0.5 text-center font-body-compact text-body-compact text-on-surface-variant">지금까지 {n}일 들어왔어요{e(nxt)}</p>'
                f'<p class="mt-12 mb-2 text-center font-label-regular text-label-regular text-on-surface-variant">최근 석 달 · {came}일 들어왔어요</p>'
                f'{grass}</section>')  # fmt: skip

    def settings(self, uid: int, msg: str | None = None) -> str:
        email, created, mail_on, nick, bio, private = self.con.execute(
            "select email, created_at, mail_on, nickname, bio, private from users where id = ?", (uid,)).fetchone()  # fmt: skip
        (at,) = self.con.execute("select photo_at from users where id = ?", (uid,)).fetchone()
        (held,) = self.con.execute("select count(*) from holdings where user_id = ?", (uid,)).fetchone()
        joined = date.fromisoformat(created[:10])
        # 주간 안내 메일 켜기/끄기 — 누르면 바로 바뀐다 (답장 같은 절차 없이, 사용자 10/7)
        knob = "translate-x-5" if mail_on else "translate-x-0"
        track = "bg-primary" if mail_on else "bg-surface-container-highest"
        switch = (f'<form method="post" action="/me/mail" class="py-3.5 flex items-center justify-between"><span class="flex items-center gap-2 font-body-compact text-body-compact text-on-surface-variant">'
                  '<span class="material-symbols-outlined text-primary text-[18px]">mark_email_unread</span>주간 안내 메일</span>'
                  f'<button aria-label="주간 안내 메일 {"끄기" if mail_on else "켜기"}" aria-pressed="{"true" if mail_on else "false"}" type="submit" class="flex items-center gap-2">'
                  f'<span class="font-label-micro text-label-micro {"text-primary" if mail_on else "text-outline"} font-semibold">{"ON" if mail_on else "OFF"}</span>'
                  f'<span class="w-11 h-6 rounded-full p-0.5 {track} transition-colors"><span class="block w-5 h-5 rounded-full bg-surface-container-lowest shadow-sm transition-transform {knob}"></span></span></button></form>')  # fmt: skip
        lock = (f'<form method="post" action="/me/private" class="py-3.5 flex items-center justify-between gap-3"><span class="flex flex-col">'
                '<span class="flex items-center gap-2 font-body-compact text-body-compact text-on-surface-variant"><span class="material-symbols-outlined text-primary text-[18px]">lock</span>비공개 계정</span>'
                '<span class="font-label-micro text-label-micro text-outline">켜면 내가 수락한 사람만 나무와 리그램, 팔로워 목록을 봐요</span></span>'
                f'<button aria-label="비공개 계정 {"끄기" if private else "켜기"}" aria-pressed="{"true" if private else "false"}" type="submit" class="flex items-center gap-2 shrink-0">'
                f'<span class="font-label-micro text-label-micro {"text-primary" if private else "text-outline"} font-semibold">{"ON" if private else "OFF"}</span>'
                f'<span class="w-11 h-6 rounded-full p-0.5 {"bg-primary" if private else "bg-surface-container-highest"} transition-colors"><span class="block w-5 h-5 rounded-full bg-surface-container-lowest shadow-sm transition-transform {"translate-x-5" if private else "translate-x-0"}"></span></span></button></form>')  # fmt: skip

        def row(icon, label, value):
            return (f'<div class="py-3.5 flex items-center justify-between"><span class="flex items-center gap-2 font-body-compact text-body-compact text-on-surface-variant">'
                    f'<span class="material-symbols-outlined text-primary text-[18px]">{icon}</span>{label}</span>'
                    f'<span class="font-body-reading-strong text-body-compact text-on-surface">{value}</span></div>')  # fmt: skip

        def go(icon, label, href):
            return (f'<a href="{href}" class="py-3.5 flex items-center justify-between"><span class="flex items-center gap-2 font-body-compact text-body-compact text-on-surface-variant">'
                    f'<span class="material-symbols-outlined text-primary text-[18px]">{icon}</span>{label}</span>'
                    '<span class="material-symbols-outlined text-outline text-[20px]">chevron_right</span></a>')  # fmt: skip

        field = "w-full font-body-compact text-body-compact bg-surface-container-low rounded-lg px-4 py-3 focus:outline-none"
        photo = ('<div class="mt-space-lg flex items-center gap-space-md">'
                 '<label class="relative cursor-pointer" aria-label="프로필 사진 바꾸기">' + self.face(nick or email, "w-20 h-20", photo_url(uid, at))
                 + '<span class="absolute -bottom-0.5 -right-0.5 w-7 h-7 rounded-full bg-primary text-on-primary flex items-center justify-center border-2 border-surface">'
                 '<span class="material-symbols-outlined text-[16px]">photo_camera</span></span><input accept="image/*" class="hidden" id="photo-input" type="file"></label>'
                 '<div class="flex flex-col gap-1"><span class="font-label-regular text-label-regular text-on-surface font-semibold">프로필 사진</span>'
                 + ('<form method="post" action="/me/photo/delete"><button class="font-label-micro text-label-micro text-outline underline" type="submit">사진 지우기</button></form>' if at else "")
                 + '</div></div>'
                 # 고른 사진 → 동그라미 안에서 끌어 옮기고 크기를 맞춘 뒤(인스타그램처럼) 보이는 부분만 256px JPEG → /me/photo
                 '<div class="hidden fixed inset-0 z-[70] bg-on-background/80 flex-col items-center justify-center gap-4 px-margin" id="crop">'
                 '<p class="font-label-regular text-label-regular text-surface">끌어서 옮기고, 아래 막대로 크기를 맞춰요</p>'
                 '<div class="relative w-[280px] h-[280px] overflow-hidden rounded-xl bg-black touch-none select-none" id="stage">'
                 '<img alt="" class="absolute top-0 left-0 max-w-none origin-top-left pointer-events-none" id="crop-img">'
                 '<div class="absolute inset-0 rounded-full pointer-events-none" style="box-shadow:0 0 0 999px rgba(0,0,0,.55)"></div></div>'
                 '<input class="w-[280px] accent-primary" id="zoom" max="3" min="1" step="0.01" type="range" value="1" aria-label="사진 크기">'
                 '<div class="flex gap-3"><button class="px-5 py-2 rounded-lg border border-surface/60 text-surface font-label-regular text-label-regular" id="crop-cancel" type="button">취소</button>'
                 '<button class="px-5 py-2 rounded-lg bg-primary text-on-primary font-label-regular text-label-regular font-semibold" id="crop-ok" type="button">이대로 저장</button></div></div>'
                 "<script>(()=>{const S=280,box=document.getElementById('crop'),stage=document.getElementById('stage'),im=document.getElementById('crop-img'),zoom=document.getElementById('zoom');"
                 "let base=1,k=1,x=0,y=0,drag=null;"
                 "const clamp=()=>{const w=im.naturalWidth*base*k,h=im.naturalHeight*base*k;x=Math.min(0,Math.max(S-w,x));y=Math.min(0,Math.max(S-h,y));"
                 "im.style.transform=`translate(${x}px,${y}px) scale(${base*k})`;};"
                 "const open=()=>{box.classList.remove('hidden');box.classList.add('flex');},close=()=>{box.classList.add('hidden');box.classList.remove('flex');};"
                 "document.getElementById('photo-input').addEventListener('change',ev=>{const f=ev.target.files[0];if(!f)return;im.onload=()=>{"
                 "base=S/Math.min(im.naturalWidth,im.naturalHeight);k=1;zoom.value=1;x=(S-im.naturalWidth*base)/2;y=(S-im.naturalHeight*base)/2;clamp();open();};"
                 "im.src=URL.createObjectURL(f);});"
                 "stage.addEventListener('pointerdown',e=>{drag=[e.clientX-x,e.clientY-y];stage.setPointerCapture(e.pointerId);});"
                 "stage.addEventListener('pointermove',e=>{if(!drag)return;x=e.clientX-drag[0];y=e.clientY-drag[1];clamp();});"
                 "stage.addEventListener('pointerup',()=>drag=null);"
                 "zoom.addEventListener('input',()=>{const c=S/2,old=base*k;k=+zoom.value;const now=base*k;x=c-(c-x)*now/old;y=c-(c-y)*now/old;clamp();});"
                 "document.getElementById('crop-cancel').onclick=()=>{close();document.getElementById('photo-input').value='';};"
                 "document.getElementById('crop-ok').onclick=async()=>{const sc=base*k,c=document.createElement('canvas');c.width=c.height=256;"
                 "c.getContext('2d').drawImage(im,-x/sc,-y/sc,S/sc,S/sc,0,0,256,256);"
                 "try{const r=await fetch('/me/photo',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({img:c.toDataURL('image/jpeg',0.85)})});"
                 "const j=await r.json();location.href='/me/settings'+(j.msg?'?msg='+encodeURIComponent(j.msg):'');}"
                 "catch(err){location.href='/me/settings?msg='+encodeURIComponent('사진을 바꾸지 못했어요. 다시 해 주세요.');}};})();</script>")  # fmt: skip
        inner = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] lg:max-w-[760px] mx-auto pt-14 pb-24 lg:pt-20 lg:pb-16 bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-6">'
                 '<a class="pt-5 flex items-center gap-space-xs text-on-surface-variant hover:text-primary" href="/me"><span class="material-symbols-outlined text-[18px]">arrow_back</span>'
                 '<span class="font-label-regular text-label-regular font-medium">내 프로필</span></a>'
                 '<h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight mt-space-sm">설정</h1>'
                 f'<span class="font-body-compact text-body-compact text-on-surface-variant truncate">{e(email)}</span>'
                 + (f'<p class="mt-space-sm font-body-compact text-body-compact text-tertiary" role="alert">{e(msg)}</p>' if msg else "")
                 + photo + '<form method="post" action="/me/profile" class="mt-space-lg flex flex-col gap-space-sm">'
                 '<label class="font-label-regular text-label-regular text-on-surface" for="nick">닉네임</label>'
                 f'<input class="{field}" id="nick" name="nickname" maxlength="20" required value="{e(nick or "")}">'
                 '<label class="font-label-regular text-label-regular text-on-surface" for="bio">자기소개</label>'
                 f'<textarea class="{field}" id="bio" name="bio" maxlength="{BIO_MAX}" rows="2">{e(bio or "")}</textarea>'
                 '<button class="self-end px-4 py-2 rounded-lg bg-primary text-on-primary font-label-regular text-label-regular font-semibold" type="submit">저장</button></form>'
                 '<section class="mt-space-lg flex flex-col divide-y divide-surface-container-high/80 border-y border-surface-container-high">'
                 + go("bookmark", "내 저장 목록", "/me/saved") + go("favorite", "내 좋아요 목록", "/me/liked")
                 + row("event", "가입한 날", f"{joined.year}년 {joined.month}월 {joined.day}일")
                 + row("inventory_2", "담은 종목", f'<a class="text-primary" href="/">{held} / {MAX_STOCKS}개</a>')
                 + switch + lock + go("description", "이용 규칙", "/rules") + "</section>" + self.blocked_list(uid) +
                 '<button class="mt-space-xl w-full py-3 rounded-lg border border-outline-variant/60 text-on-surface-variant font-body-reading-strong text-body-compact hover:bg-surface-container-low transition-colors" '
                 'onclick="if(confirm(\'현재 계정에서 로그아웃할까요?\'))location.href=\'/logout\'" type="button">로그아웃</button>'
                 '<form method="post" action="/me/delete" onsubmit="return confirm(\'탈퇴하면 이메일과 담은 종목, 기록이 모두 지워지고 되돌릴 수 없어요. 탈퇴할까요?\')">'
                 '<button class="mt-space-sm w-full py-3 font-label-regular text-label-regular text-tertiary hover:underline" type="submit">탈퇴하기</button></form>'
                 '<p class="mt-space-lg flex justify-center gap-3 font-label-micro text-label-micro text-outline"><a class="underline" href="/privacy">개인정보 처리방침</a><span>·</span><a class="underline" href="/method">계산 방법</a></p>'
                 '</div></main>' + bottom_nav("me"))  # fmt: skip
        return page("설정", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    # ---- 팔로우 · 리그램 · 피드 (뉴닉 「뉴니커」처럼 — 좋아한 글을 내 팔로워에게) ----

    def counts(self, uid: int) -> tuple[int, int]:
        q = "select count(*) from follows where {} = ? and ok = 1"
        return (self.con.execute(q.format("followee_id"), (uid,)).fetchone()[0],
                self.con.execute(q.format("follower_id"), (uid,)).fetchone()[0])  # fmt: skip

    @staticmethod
    def face(name: str, size: str = "w-9 h-9", photo: str | None = None) -> str:
        inside = f'<img alt="" class="w-full h-full object-cover" src="{e(photo)}">' if photo else e((name or "?")[:1].upper())
        return (f'<span class="{size} shrink-0 overflow-hidden rounded-full bg-primary-fixed text-primary flex items-center justify-center font-label-regular text-label-regular font-semibold">'
                f'{inside}</span>')  # fmt: skip

    def follow_line(self, uid: int, see: bool = True) -> str:
        """「팔로워 N | 팔로잉 N」 — 비공개 계정을 남이 보면 숫자만(목록으로 가는 링크 없이)."""
        fer, fing = self.counts(uid)
        tag = (lambda tab: f'<a class="hover:underline" href="/f/{uid}?tab={tab}">') if see else (lambda tab: "<span>")
        end = "</a>" if see else "</span>"
        return (f'<p class="font-label-regular text-label-regular text-on-surface-variant">{tag("followers")}팔로워 <b class="text-on-surface">{fer:,}</b>{end}'
                f'<span class="mx-2 text-outline-variant">|</span>{tag("following")}팔로잉 <b class="text-on-surface">{fing:,}</b>{end}</p>')  # fmt: skip

    def follow_button(self, uid: int, other: int, back: str) -> str:
        """목록·알림 줄 오른쪽 — 이미 팔로우하면 「팔로잉」(회색, 누르면 취소), 아니면 「팔로우」(초록). 나 자신은 없음."""
        if other == uid:
            return ""
        label, on = self.follow_state(uid, other)
        cls = "bg-surface-container text-on-surface" if on else "bg-primary text-on-primary"
        return (f'<form method="post" action="/follow" class="shrink-0"><input type="hidden" name="u" value="{other}"><input type="hidden" name="back" value="{e(back)}">'
                f'<button type="submit" class="px-4 py-1.5 rounded-lg text-[13px] font-semibold {cls}">{label}</button></form>')  # fmt: skip

    def follow_state(self, uid: int, other: int) -> tuple[str, bool]:
        """단추 글자 — 「팔로잉」(수락됨) · 「요청됨」(비공개 계정에 보낸 요청, 누르면 취소) · 「팔로우」."""
        row = self.con.execute("select ok from follows where follower_id = ? and followee_id = ?", (uid, other)).fetchone()
        return ("팔로잉" if row[0] else "요청됨", True) if row else ("팔로우", False)

    def can_see(self, uid: int, other: int) -> bool:
        """비공개 계정의 리그램·팔로워 목록은 본인과 수락된 팔로워만."""
        row = self.con.execute("select private from users where id = ?", (other,)).fetchone()
        return uid == other or not (row and row[0]) or bool(self.con.execute(
            "select 1 from follows where follower_id = ? and followee_id = ? and ok = 1", (uid, other)).fetchone())

    def person_row(self, uid: int, other: int, nick: str, bio: str | None, pat: str | None, back: str, note: str = "") -> str:
        return (f'<div class="py-3 flex items-center gap-3"><a href="/u/{other}" class="flex items-center gap-3 min-w-0 flex-1">{self.face(nick, "w-12 h-12", photo_url(other, pat))}'
                f'<span class="flex flex-col min-w-0"><b class="text-[15px] text-on-surface truncate">{e(nick)}</b>'
                f'<span class="text-[13px] text-on-surface-variant truncate">{note or e(bio or "")}</span></span></a>{self.follow_button(uid, other, back)}</div>')  # fmt: skip

    def follow_page(self, uid: int, who: int, tab: str):
        """인스타그램처럼 — 위에 「팔로워 N명 | 팔로잉 N명」 탭, 아래에 사람 목록과 팔로우 단추 (사용자 10/10)."""
        row = self.con.execute("select nickname from users where id = ?", (who,)).fetchone()
        if not row:
            return "404 Not Found", [], self.simple("없음", "없는 사람이에요.")
        tab = tab if tab in ("followers", "following") else "followers"
        if not self.can_see(uid, who):
            return self.see(f"/u/{who}")
        fer, fing = self.counts(who)
        col, by = ("follower_id", "followee_id") if tab == "followers" else ("followee_id", "follower_id")
        people = self.con.execute(f"select u.id, u.nickname, u.bio, u.photo_at from follows f join users u on u.id = f.{col}"
                                  f" where f.{by} = ? and f.ok = 1 and u.nickname is not null order by f.at desc", (who,)).fetchall()  # fmt: skip
        back = f"/f/{who}?tab={tab}"
        tabs = "".join(f'<a href="/f/{who}?tab={k}" class="flex-1 text-center py-3 text-[15px] {"font-semibold text-on-surface border-b-2 border-on-surface" if k == tab else "text-on-surface-variant border-b border-surface-container-high"}">{label} {n:,}명</a>'
                       for k, label, n in (("followers", "팔로워", fer), ("following", "팔로잉", fing)))  # fmt: skip
        rows = "".join(self.person_row(uid, i, n, b, p, back) for i, n, b, p in people)
        none = f'<p class="py-10 text-center text-[14px] text-outline">{"아직 팔로워가 없어요." if tab == "followers" else "아직 팔로우한 사람이 없어요."}</p>'
        home = "/me" if who == uid else f"/u/{who}"
        inner = (top_bar(self.initial(uid)) + '<main class="w-full max-w-[480px] lg:max-w-[760px] mx-auto pt-14 pb-24 lg:pt-20 min-h-screen"><div class="px-margin">'
                 f'<div class="flex items-center gap-3 py-3"><a href="{home}" aria-label="뒤로" class="text-on-surface"><span class="material-symbols-outlined">arrow_back</span></a>'
                 f'<h1 class="text-[20px] font-semibold text-on-surface">{e(row[0] or "")}</h1></div>'
                 f'<nav class="flex">{tabs}</nav><div class="flex flex-col">{rows or none}</div></div></main>' + bottom_nav("me"))  # fmt: skip
        return "200 OK", [], page("팔로워" if tab == "followers" else "팔로잉", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    def fresh(self, uid: int, since: str) -> tuple[list, list]:
        """알림거리 (since 뒤, 최근 7일 안) — 팔로우한 사람의 새 리그램, 내가 담은 종목의 새 소식 (사용자 10/10).
        담은 종목은 남에게 알리지 않는다 — 본인 알림에만 쓴다."""
        since = max(since, (datetime.now() - timedelta(days=7)).isoformat())
        regs = self.con.execute("select r.at, u.id, u.nickname, u.photo_at, r.kind, r.ref, r.week from regrams r join users u on u.id = r.user_id"
                                " where r.user_id in (select followee_id from follows where follower_id = ? and ok = 1) and r.at > ?"
                                " order by r.at desc limit 30", (uid, since)).fetchall()  # fmt: skip
        arts = self.con.execute("select a.made_at, a.id, a.body, s.name, s.homepage from articles a join stocks s using(ticker)"
                                " where a.ticker in (select ticker from holdings where user_id = ?) and a.made_at > ?"
                                " order by a.made_at desc limit 30", (uid, since)).fetchall()  # fmt: skip
        return regs, arts

    def regram_target(self, kind: str, ref: str) -> tuple[str, str] | None:
        """리그램한 것의 (주소, 이름) — 알림 한 줄에 쓴다. 없어진 것이면 None."""
        if kind == "note":
            hit = self.con.execute("select name from stocks where ticker = ?", (ref,)).fetchone()
            return (f"/n/{ref}", f"{hit[0]} 노트") if hit else None
        if kind == "article":
            hit = self.con.execute("select body from articles where id = ?", (int(ref) if ref.isdigit() else -1,)).fetchone()
            return (f"/a/{ref}", json.loads(hit[0])["title"]) if hit else None
        a = learn.BY_SLUG.get(ref)
        return (f"/learn/{ref}", a["title"]) if a else None

    def notices(self, uid: int):
        """알림 — 팔로우 · 팔로우한 사람의 새 리그램 · 내 종목 새 소식, 최신 먼저. 이 화면을 열면 빨간 점이 사라진다."""
        seen = self.con.execute("select coalesce(notices_seen, '') from users where id = ?", (uid,)).fetchone()[0]
        rows = self.con.execute("select u.id, u.nickname, u.bio, u.photo_at, f.at from follows f join users u on u.id = f.follower_id"
                                " where f.followee_id = ? and f.ok = 1 and u.nickname is not null order by f.at desc limit 50", (uid,)).fetchall()  # fmt: skip
        asks = self.con.execute("select u.id, u.nickname, u.photo_at, f.at from follows f join users u on u.id = f.follower_id"
                                " where f.followee_id = ? and f.ok = 0 order by f.at desc", (uid,)).fetchall()  # fmt: skip
        regs, arts = self.fresh(uid, "")
        self.con.execute("update users set notices_seen = ? where id = ?", (datetime.now().isoformat(), uid))
        self.con.commit()
        new = lambda at: "bg-primary-fixed/30 -mx-margin px-margin" if at > seen else ""  # noqa: E731
        events = [(at, f'<div class="{new(at)}">' + self.person_row(uid, i, n, b, p, "/me/notices", f"회원님을 팔로우하기 시작했어요 · {ago(at)}") + "</div>")
                  for i, n, b, p, at in rows]  # fmt: skip
        for at, i, n, p, kind, ref, _ in regs:
            if (hit := self.regram_target(kind, ref)):
                events.append((at, f'<a href="{e(hit[0])}" class="py-3 flex items-center gap-3 {new(at)}">{self.face(n, "w-12 h-12", photo_url(i, p))}'
                                   f'<span class="flex flex-col min-w-0"><span class="text-[14px] text-on-surface"><b>{e(n)}</b>님이 리그램했어요</span>'
                                   f'<span class="text-[13px] text-on-surface-variant truncate">{e(hit[1])} · {ago(at)}</span></span></a>'))  # fmt: skip
        for at, aid, body, name, home in arts:
            events.append((at, f'<a href="/a/{aid}" class="py-3 flex items-center gap-3 {new(at)}">{logo(name, home, "w-12 h-12")}'
                               f'<span class="flex flex-col min-w-0"><span class="text-[14px] text-on-surface">내 종목 <b>{e(name)}</b> 새 소식</span>'
                               f'<span class="text-[13px] text-on-surface-variant truncate">{e(json.loads(body)["title"])} · {ago(at)}</span></span></a>'))  # fmt: skip
        items = "".join(h for _, h in sorted(events, key=lambda x: x[0], reverse=True))
        none = '<p class="py-10 text-center text-[14px] text-outline">아직 알림이 없어요. 누가 팔로우하거나, 팔로우한 사람이 리그램하거나, 내 종목에 새 소식이 나오면 여기에 알려 드려요.</p>'

        def answer(i, label, yes, cls):
            return (f'<form method="post" action="/follow/answer"><input type="hidden" name="u" value="{i}"><input type="hidden" name="yes" value="{yes}">'
                    f'<button type="submit" class="px-3 py-1.5 rounded-lg text-[13px] font-semibold {cls}">{label}</button></form>')  # fmt: skip
        items = "".join(
            f'<div class="py-3 flex items-center gap-3"><a href="/u/{i}" class="flex items-center gap-3 min-w-0 flex-1">{self.face(n, "w-12 h-12", photo_url(i, p))}'
            f'<span class="flex flex-col min-w-0"><b class="text-[15px] text-on-surface truncate">{e(n or "")}</b>'
            f'<span class="text-[13px] text-on-surface-variant truncate">팔로우를 요청했어요 · {ago(at)}</span></span></a>'
            + answer(i, "수락", 1, "bg-primary text-on-primary") + answer(i, "삭제", 0, "bg-surface-container text-on-surface") + "</div>"
            for i, n, p, at in asks) + items  # fmt: skip
        inner = (top_bar(self.initial(uid)) + '<main class="w-full max-w-[480px] lg:max-w-[760px] mx-auto pt-14 pb-24 lg:pt-20 min-h-screen"><div class="px-margin">'
                 '<h1 class="py-3 text-[20px] font-semibold text-on-surface">알림</h1>'
                 f'<div class="flex flex-col">{items or none}</div></div></main>' + bottom_nav("me"))  # fmt: skip
        return "200 OK", [], page("알림", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    def save_photo(self, uid: int, img: str):
        """프로필 사진 — JPEG 만, 작게(PHOTO_MAX). 브라우저가 이미 256px 정사각형으로 잘라 보낸다."""
        import base64
        import binascii

        def reply(msg="", code="200 OK"):
            return code, [("Content-Type", "application/json; charset=utf-8")], json.dumps({"msg": msg}, ensure_ascii=False)

        head = "data:image/jpeg;base64,"
        try:
            raw = base64.b64decode(img[len(head):], validate=True) if img.startswith(head) else b""
        except binascii.Error:
            raw = b""
        if not raw.startswith(b"\xff\xd8\xff") or len(raw) > PHOTO_MAX:
            return reply("사진을 바꾸지 못했어요. 다른 사진으로 해 주세요.", "400 Bad Request")
        self.con.execute("update users set photo = ?, photo_at = ? where id = ?", (raw, datetime.now().isoformat(timespec="seconds"), uid))
        self.con.commit()
        return reply()

    def nick_error(self, uid: int, nick: str) -> str:
        """닉네임 검사 — 문제가 없으면 빈 글. 겹침은 대소문자를 무시하고 본다(DB 유일 색인과 같게)."""
        if not NICK.fullmatch(nick):
            return "닉네임은 한글·영문·숫자·_ 2~20자로 정해 주세요."
        if notes.FORBIDDEN.search(nick) or BAD.search(nick):
            return "닉네임에 쓸 수 없는 말이 들어 있어요."
        if self.con.execute("select 1 from users where nickname = ? collate nocase and id != ?", (nick, uid)).fetchone():
            return f"「{nick}」은(는) 이미 누가 쓰고 있어요. 다른 닉네임으로 해 주세요."
        return ""

    def welcome_page(self, nick: str = "", error: str = "", agreed: bool = False) -> str:
        inner = ('<main class="flex flex-col relative w-full max-w-[480px] lg:max-w-[760px] mx-auto bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pt-16 pb-12">'
                 '<span class="font-display-editorial text-display-editorial text-primary tracking-tight">한장</span>'
                 '<h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight mt-space-md">닉네임을 정해 주세요</h1>'
                 '<p class="font-body-compact text-body-compact text-on-surface-variant mt-1">다른 사람에게는 이메일 대신 이 이름이 보여요. 한글·영문·숫자 2~20자, 다른 사람과 겹칠 수 없어요.</p>'
                 '<form method="post" action="/welcome" class="mt-space-lg flex flex-col gap-space-sm">'
                 f'<input autofocus class="w-full font-body-reading text-body-reading bg-surface-container-low rounded-lg px-4 py-3.5 focus:outline-none" maxlength="20" name="nickname" required value="{e(nick)}">'
                 # 이용 규칙 동의 — 닉네임·소개·사진이 남에게 보이기 전에 (앱 마켓이 사용자 콘텐츠가 있는 앱에 요구한다)
                 + '<label class="flex items-start gap-2 font-label-regular text-label-regular text-on-surface-variant"><input class="mt-0.5 accent-primary" name="rules" required type="checkbox" value="1"' + (" checked" if agreed else "") + '>'
                 '<span>[필수] <a class="text-primary underline" href="/rules" target="_blank">이용 규칙</a>에 동의해요 — 욕설·사칭·종목 추천·광고는 올리지 않아요</span></label>'
                 + (f'<p class="font-body-compact text-body-compact text-tertiary" role="alert">{e(error)}</p>' if error else "")
                 + '<button class="w-full py-3.5 bg-primary text-on-primary font-body-reading-strong text-body-reading-strong rounded-lg shadow-sm" type="submit">시작하기</button></form>'
                 '</div></main>')  # fmt: skip
        return page("닉네임", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    def welcome(self, uid: int, nick: str, agreed: bool = False):
        if err := self.nick_error(uid, nick):
            return "200 OK", [], self.welcome_page(nick, err, agreed)
        if not agreed:
            return "200 OK", [], self.welcome_page(nick, "이용 규칙에 동의해야 시작할 수 있어요.")
        try:
            self.con.execute("update users set nickname = ?, rules_at = ? where id = ?", (nick, datetime.now().isoformat(), uid))
            self.con.commit()
        except sqlite3.IntegrityError:  # 거의 같은 때 누가 먼저 가져간 경우
            return "200 OK", [], self.welcome_page(nick, f"「{nick}」은(는) 이미 누가 쓰고 있어요. 다른 닉네임으로 해 주세요.", agreed)
        return self.see("/")

    def save_profile(self, uid: int, nick: str, bio: str):
        if err := self.nick_error(uid, nick):  # 닉네임은 바꿀 수는 있어도 비울 수는 없다
            return self.see("/me/settings?msg=" + quote(err))
        if len(bio) > BIO_MAX or notes.FORBIDDEN.search(bio):
            return self.see("/me/settings?msg=" + quote("자기소개에 종목을 사라·팔라는 말이나 추천은 쓸 수 없어요."))
        if BAD.search(bio):
            return self.see("/me/settings?msg=" + quote("자기소개에 욕설·광고·연락처·바깥 링크는 쓸 수 없어요."))
        try:
            self.con.execute("update users set nickname = ?, bio = ? where id = ?", (nick, bio or None, uid))
            self.con.commit()
        except sqlite3.IntegrityError:
            return self.see("/me/settings?msg=" + quote(f"「{nick}」은(는) 이미 누가 쓰고 있어요."))
        return self.see("/me")  # 저장하면 바뀐 내 프로필로 (사용자 10/9)

    def regram_form(self, uid: int, kind: str, ref: str, week: str) -> str:
        """노트·읽기 팁 글 아래 — 리그램(한 줄 코멘트는 선택). 이미 했으면 취소 버튼."""
        done = self.con.execute("select 1 from regrams where user_id = ? and kind = ? and ref = ? and week = ?", (uid, kind, ref, week)).fetchone()
        (n,) = self.con.execute("select count(*) from regrams where kind = ? and ref = ? and week = ?", (kind, ref, week)).fetchone()
        undo = '<input type="hidden" name="undo" value="1">' if done else ""
        return (f'<form method="post" action="/regram" class="flex items-center gap-1.5"><input type="hidden" name="k" value="{e(kind)}"><input type="hidden" name="r" value="{e(ref)}"><input type="hidden" name="w" value="{e(week)}">{undo}'
                f'<button type="submit" aria-pressed="{"true" if done else "false"}" aria-label="리그램{" 취소" if done else ""} — 내 팔로워의 피드에 보여요" title="리그램 — 내 팔로워의 피드에 보여요" '
                f'class="w-10 h-10 rounded-full flex items-center justify-center border {"border-secondary/40 bg-secondary-container/60 text-secondary" if done else "border-outline-variant/60 text-outline"} transition-colors">'
                f'<span class="material-symbols-outlined text-[20px]">repeat</span></button>'
                f'<span class="font-label-regular text-label-regular text-on-surface-variant font-semibold">{n:,}</span></form>'
                + self.save_form(uid, kind, ref, week))  # fmt: skip

    def save_form(self, uid: int, kind: str, ref: str, week: str) -> str:
        """저장 — 나만 본다(숫자 없음). 설정 「내 저장 목록」에 모인다 (사용자 10/10)."""
        done = self.con.execute("select 1 from saves where user_id = ? and kind = ? and ref = ? and week = ?", (uid, kind, ref, week)).fetchone()
        undo = '<input type="hidden" name="undo" value="1">' if done else ""
        return (f'<form method="post" action="/save" class="ml-2 flex items-center"><input type="hidden" name="k" value="{e(kind)}"><input type="hidden" name="r" value="{e(ref)}"><input type="hidden" name="w" value="{e(week)}">{undo}'
                f'<button type="submit" aria-pressed="{"true" if done else "false"}" aria-label="저장{" 취소" if done else ""} — 나만 봐요" title="저장 — 내 저장 목록에 모여요" '
                f'class="w-10 h-10 rounded-full flex items-center justify-center border {"border-primary/40 bg-primary-fixed/60 text-primary" if done else "border-outline-variant/60 text-outline"} transition-colors">'
                f'<span class="material-symbols-outlined text-[20px]" style="{FILLED if done else ""}">bookmark</span></button></form>')  # fmt: skip

    def kept(self, uid: int, which: str) -> str:
        """설정 → 내 저장 목록 · 내 좋아요 목록 (나만 본다)."""
        title, src, none = (("내 저장 목록", "saves r", "아직 저장한 글이 없어요. 글 아래 책갈피 단추를 누르면 여기에 모여요.") if which == "saved" else
                            ("내 좋아요 목록", "(select user_id, 'note' kind, ticker ref, week, null comment, at from likes) r", "아직 좋아요를 누른 노트가 없어요."))  # fmt: skip
        body = self.regram_list("where r.user_id = ?", (uid,), title, mine=True, src=src)
        inner = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] lg:max-w-[760px] mx-auto pt-14 pb-24 lg:pt-20 lg:pb-16 bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-6">'
                 '<a class="pt-5 flex items-center gap-space-xs text-on-surface-variant hover:text-primary" href="/me/settings"><span class="material-symbols-outlined text-[18px]">arrow_back</span>'
                 '<span class="font-label-regular text-label-regular font-medium">설정</span></a>'
                 + (body or f'<h1 class="mt-space-lg font-headline-sm text-headline-sm text-on-surface">{title}</h1><p class="py-10 text-center text-[14px] text-outline">{none}</p>')
                 + "</div></main>" + bottom_nav("me"))  # fmt: skip
        return page(title, "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    def share_quote(self, uid: int, pg: str, text: str):
        """고른 글귀를 내 프로필에 — 그 글의 리그램에 글귀 한 줄을 붙인다(글 하나에 하나, 다시 하면 바뀐다) (사용자 10/10).
        글귀가 실제로 그 글 안에 있을 때만 — 인용인 척 「사세요」 같은 제 말을 올리지 못하게."""
        def reply(msg):
            return "200 OK", [("Content-Type", "application/json; charset=utf-8")], json.dumps({"msg": msg}, ensure_ascii=False)

        text = " ".join(text.split())
        m = HL_PAGE.fullmatch(pg)
        if not m or not QUOTE_MIN <= len(text) <= QUOTE_MAX or notes.FORBIDDEN.search(text):
            return reply(f"{QUOTE_MIN}~{QUOTE_MAX}자만 공유할 수 있어요")
        if not self.con.execute("select nickname from users where id = ?", (uid,)).fetchone()[0]:
            return reply("닉네임을 먼저 정해 주세요")
        kind, ref, week = {"n": "note", "a": "article"}.get(m[1], "learn"), pg.split("/", 2)[2], ""
        if kind == "note":
            (week,) = self.con.execute("select max(week) from notes where ticker = ?", (ref,)).fetchone()
            shown = self.note(uid, ref, False) if week else None
        elif kind == "article":
            shown = self.article(uid, int(ref)) if ref.isdigit() else None
        else:
            shown = self.learn(uid, ref) if ref in learn.BY_SLUG else None
        squash = lambda x: re.sub(r"\s+", "", x)  # noqa: E731 — 줄바꿈·문단 사이 빈칸은 견주지 않는다
        if not shown or not shown[0].startswith("200") or squash(text) not in squash(html.unescape(TAGS.sub("", shown[2]))):
            return reply("글에 있는 문장만 공유할 수 있어요")
        now = datetime.now().isoformat()
        self.con.execute("insert or ignore into regrams (user_id, kind, ref, week, at) values (?, ?, ?, ?, ?)", (uid, kind, ref, week, now))
        self.con.execute("update regrams set comment = ?, at = ? where user_id = ? and kind = ? and ref = ? and week = ?", (text, now, uid, kind, ref, week))
        self.con.commit()
        return reply("내 프로필에 올렸어요")

    def highlight(self, uid: int, method: str, path: str, form: dict, query: dict):
        """형광펜 — GET /hl?p=화면 → 칠한 곳들 · POST /hl 칠하기 · POST /hl/del 지우기. 모두 내 것만."""
        def reply(data):
            return "200 OK", [("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store")], json.dumps(data, ensure_ascii=False)

        if method == "GET":
            rows = self.con.execute("select id, s, e, text, color from highlights where user_id = ? and page = ? order by id", (uid, query.get("p", ""))).fetchall()
            return reply([{"id": i, "s": s, "e": e, "t": t, "c": c} for i, s, e, t, c in rows])
        if path == "/hl/del":
            self.con.execute("delete from highlights where id = ? and user_id = ?", (int(form["id"]) if form.get("id", "").isdigit() else -1, uid))
            self.con.commit()
            return reply({})
        pg, t, c = form.get("p", ""), form.get("t", ""), form.get("c", "")
        s, e2 = (int(form[k]) if form.get(k, "").isdigit() else -1 for k in ("s", "e"))
        (n,) = self.con.execute("select count(*) from highlights where user_id = ? and page = ?", (uid, pg)).fetchone()
        if not HL_PAGE.fullmatch(pg) or not 0 <= s < e2 or not t.strip() or len(t) > HL_MAX or c not in ("y", "g", "p", "b") or n >= HL_PER_PAGE:
            return reply({})
        cur = self.con.execute("insert into highlights (user_id, page, s, e, text, color, at) values (?, ?, ?, ?, ?, ?, ?)",
                               (uid, pg, s, e2, t, c, datetime.now().isoformat()))  # fmt: skip
        self.con.commit()
        return reply({"id": cur.lastrowid})

    def regram(self, uid: int, form: dict, table: str = "regrams"):
        kind, ref, week = form.get("k", ""), form.get("r", ""), form.get("w", "")
        back = {"note": f"/n/{quote(ref)}", "article": f"/a/{quote(ref)}"}.get(kind, f"/learn/{quote(ref)}")
        ok = (kind == "note" and self.con.execute("select 1 from notes where ticker = ? and week = ?", (ref, week)).fetchone()) or (
            kind == "learn" and ref in learn.BY_SLUG and week == "") or (
            kind == "article" and ref.isdigit() and week == "" and self.con.execute("select 1 from articles where id = ?", (int(ref),)).fetchone())
        if not ok:
            return self.see("/feed")
        if form.get("undo"):
            self.con.execute(f"delete from {table} where user_id = ? and kind = ? and ref = ? and week = ?", (uid, kind, ref, week))
            self.con.commit()
            return self.see(back)
        if table == "regrams" and not self.con.execute("select nickname from users where id = ?", (uid,)).fetchone()[0]:  # 저장은 나만 보니 닉네임이 없어도 된다
            return self.see("/me/settings?msg=" + quote("리그램하려면 닉네임을 먼저 정해 주세요. 팔로워에게 이 이름으로 보여요."))
        self.con.execute(f"insert or ignore into {table} (user_id, kind, ref, week, at) values (?, ?, ?, ?, ?)",
                         (uid, kind, ref, week, datetime.now().isoformat()))  # fmt: skip
        self.con.commit()
        return self.see(back)

    def regram_list(self, where: str, args: tuple, title: str, mine: bool = False, photos: "Photos | None" = None, src: str = "regrams r") -> str:
        """글 카드 목록 — 리그램(src 기본) · 저장(saves r) · 좋아요(likes 를 같은 모양으로 바꾼 것)."""
        photos = photos or Photos()
        rows = self.con.execute(
            f"select r.user_id, u.nickname, r.kind, r.ref, r.week, r.comment, r.at, u.photo_at from {src} join users u on u.id = r.user_id "
            + where + " order by r.at desc limit 50", args).fetchall()  # fmt: skip
        cards = []
        for who, nick, kind, ref, week, comment, at, pat in rows:
            d = at[:10].replace("-", ".")
            if kind == "note":
                hit = self.con.execute("select s.name, n.body, s.homepage from stocks s join notes n on n.ticker = s.ticker and n.week = ?"
                                       " where s.ticker = ?", (week, ref)).fetchone()  # fmt: skip
                if not hit:
                    continue
                card = lambda top, h=notes.mend(json.loads(hit[1])["headline"]), n=hit[0], home=hit[2], t=ref: note_card(t, n, home, h, d, top)
            elif kind == "article":
                hit = self.con.execute("select a.id, a.kind, a.body, a.date, s.name, s.induty_code from articles a join stocks s using(ticker) where a.id = ?",
                                       (int(ref) if ref.isdigit() else -1,)).fetchone()  # fmt: skip
                if not hit:
                    continue
                aid, k, body, adate, name, ind = hit
                b = json.loads(body)
                img = self.article_photo(aid, k, ind, name, photos)
                card = lambda top, b=b, img=img, name=name, aid=aid, adate=adate: row(f"/a/{aid}", img, b["title"], b["paragraphs"][0]["text"], name, adate.replace("-", "."), top)
            else:
                a = learn.BY_SLUG.get(ref)
                if not a:
                    continue
                mark = '<span class="w-7 h-7 rounded-full bg-primary-fixed text-primary flex items-center justify-center"><span class="material-symbols-outlined text-[16px]">menu_book</span></span>'
                card = lambda top, a=a, ref=ref, mark=mark: mini(f"/learn/{ref}", mark, a["title"], a["lead"].replace("**", ""), "읽기 팁", d, top)
            top = "" if mine else (f'<a href="/u/{who}" class="flex items-center gap-2">{self.face(nick, "w-6 h-6", photo_url(who, pat))}'
                                   f'<span class="font-label-regular text-label-regular text-on-surface-variant"><b class="text-on-surface font-semibold">{e(nick)}</b>님이 리그램</span></a>')  # fmt: skip
            if comment:  # 공유한 글귀 — 글에서 고른 문장 그대로 (share_quote 가 글 안에 있는지 확인한 것)
                top += (f'<blockquote class="border-l-4 border-primary pl-3 py-0.5 text-[16px] leading-[26px] text-on-surface font-medium">'
                        f'<a href="{e({"note": "/n/", "article": "/a/"}.get(kind, "/learn/") + ref)}">“{e(comment)}”</a></blockquote>')  # fmt: skip
            cards.append(card(top))
        if not cards:
            return ""
        body = "".join(cards)
        return (f'<section class="mt-space-lg"><h2 class="font-headline-sm text-headline-sm text-on-surface">{e(title)}</h2>'
                f'<div class="flex flex-col divide-y divide-surface-container-high/80">{body}</div></section>')  # fmt: skip

    def people(self, uid: int, q: str) -> str:
        if not q:
            return ""
        rows = self.con.execute("select id, nickname, bio, photo_at from users where nickname is not null and id != ? and nickname like ?"
                                " limit 40", (uid, f"%{q}%")).fetchall()  # fmt: skip
        gone = self.blocked(uid)  # 차단한·차단당한 사람은 찾기에도 안 나온다
        rows = [r for r in rows if r[0] not in gone][:20]
        items = "".join(f'<a href="/u/{i}" class="py-space-sm flex items-center gap-space-sm">{self.face(n, photo=photo_url(i, p))}<span class="flex flex-col min-w-0">'
                        f'<span class="font-label-regular text-label-regular text-on-surface font-semibold">{e(n)}</span>'
                        f'<span class="font-label-micro text-label-micro text-on-surface-variant truncate">{e(b or "")}</span></span></a>' for i, n, b, p in rows)  # fmt: skip
        none = '<p class="py-2 font-body-compact text-body-compact text-outline">그런 닉네임이 없어요.</p>'
        return f'<div class="mt-space-sm flex flex-col divide-y divide-surface-container-high/80">{items or none}</div>'

    def article_photo(self, aid: int, kind: str, ind: str | None, name: str, photos: "Photos | None" = None) -> str:
        """기사 사진 — 처음 고를 때 사건 종류에 맞는 주제(증자는 돈, 계약은 계약서…)로 고르고 저장한다.
        그 뒤로 피드와 기사 화면이 같은 사진을 쓴다 (사용자 10/9: 눌렀더니 사진이 바뀌었다)."""
        got = self.con.execute("select photo from articles where id = ?", (aid,)).fetchone()
        if got and got[0]:
            if photos:
                photos.used.add(got[0])
            return got[0]
        img = (photos or Photos()).pick(kind, ind, name)
        self.con.execute("update articles set photo = ? where id = ? and photo is null", (img, aid))
        self.con.commit()
        return self.con.execute("select photo from articles where id = ?", (aid,)).fetchone()[0] or img

    def latest(self, uid: int, photos: "Photos") -> str:
        """최근 소식 — 사건마다 쓴 기사. 담은 종목 먼저, 최신 먼저."""
        rows = self.con.execute(
            "select a.id, a.kind, a.date, a.body, s.name, s.induty_code, a.ticker in (select ticker from holdings where user_id = ?) mine"
            " from articles a join stocks s using(ticker) order by mine desc, a.date desc, a.id desc limit 30", (uid,)).fetchall()  # fmt: skip
        if not rows:
            return ""
        items = "".join(
            story(f"/a/{i}", self.article_photo(i, k, ind, name, photos),
                  (b := json.loads(body))["title"], b["paragraphs"][0]["text"], name + (" · 내 종목" if mine else ""), d.replace("-", "."))
            for i, k, d, body, name, ind, mine in rows)  # fmt: skip
        return (f'<section class="mt-space-lg"><h2 class="font-headline-sm text-headline-sm text-on-surface">최근 소식</h2>'
                f'<div class="flex flex-col lg:grid lg:grid-cols-2 lg:gap-x-14">{items}</div></section>')  # fmt: skip

    def article(self, uid: int, aid: int):
        row = self.con.execute("select a.ticker, a.kind, a.date, a.body, s.name, s.induty_code from articles a join stocks s using(ticker)"
                               " where a.id = ?", (aid,)).fetchone()  # fmt: skip
        if not row:
            return "404 Not Found", [], self.simple("없음", "없는 기사예요. <a class='text-primary underline' href='/feed'>피드</a>")
        t, kind, d, body, name, ind = row
        b = json.loads(body)
        img = self.article_photo(aid, kind, ind, name)

        def strong(text: str, marks: list[str]) -> str:
            """강조할 말(articles.emphasize 가 고른, 본문에 그대로 있는 말)만 읽기 팁처럼 진한 초록 굵은 글씨로. 겹치면 먼저 고른 것만."""
            spans: list[tuple[int, int]] = []
            for m in marks:
                i = text.find(m)
                if i >= 0 and all(i >= b or i + len(m) <= a for a, b in spans):
                    spans.append((i, i + len(m)))
            out, k = "", 0
            for a, b in sorted(spans):
                out += e(text[k:a]) + f'<strong class="font-semibold text-primary">{e(text[a:b])}</strong>'
                k = b
            return out + e(text[k:])

        def cite(p):  # 출처 번호 → 원문 바로 열기 (작은 회색 위첨자)
            return strong(p["text"], p.get("marks", [])) + "".join(f'<a class="{CITE}" href="{e(safe_url(b["links"].get(r, "#")))}" target="_blank" rel="noopener">[{e(r)}]</a>' for r in p["refs"])

        paras = "".join(f'<p class="text-[15px] leading-[27px] text-on-surface mb-4">{cite(p)}</p>' for p in b["paragraphs"])
        inner = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] lg:max-w-[760px] mx-auto pt-14 pb-24 lg:pt-20 lg:pb-16 bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-6">'
                 '<a class="pt-4 flex items-center gap-space-xs text-on-surface-variant hover:text-primary" href="/feed"><span class="material-symbols-outlined text-[18px]">arrow_back</span><span class="font-label-regular text-label-regular">피드</span></a>'
                 f'<h1 class="mt-space-sm text-[22px] leading-[30px] font-bold tracking-tight text-on-surface">{e(b["title"])}</h1>'
                 f'<p class="mt-1 text-[12px] text-outline">{e(name)} · {e(d.replace("-", "."))}</p>'
                 f'<img alt="" class="mt-space-md w-full aspect-[16/10] object-cover rounded-xl" src="{e(img)}">'
                 '<p class="mt-1 text-right text-[11px] text-outline">주제 사진 · Unsplash</p>'
                 f'<article class="mt-space-md">{paras}</article>'
                 + '<div class="mt-space-sm mb-space-sm flex justify-end">' + self.regram_form(uid, "article", str(aid), "") + "</div>"
                 f'<a class="mt-space-sm flex items-center justify-between rounded-xl border border-outline-variant/50 px-space-md py-3" href="/n/{e(t)}">'
                 f'<span class="flex items-center gap-2">{logo(name, self.con.execute("select homepage from stocks where ticker = ?", (t,)).fetchone()[0], "w-8 h-8")}'
                 f'<span class="text-[14px] font-semibold text-on-surface">{e(name)} 분석 보고서 보기</span></span><span class="material-symbols-outlined text-outline">chevron_right</span></a>'
                 '<p class="mt-space-md text-[11px] text-outline leading-relaxed">공시 원문·사업보고서·재무·회사 뉴스룸 요약문을 바탕으로 AI가 쓴 글이에요. 숫자는 코드가 원문과 대조했어요. 작은 번호를 누르면 원문이 열려요. 사라·팔아라는 뜻이 아니에요.</p>'
                 + "</div></main>" + bottom_nav("feed"))  # fmt: skip
        return "200 OK", [], page(b["title"], "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    def popular(self, photos: "Photos") -> str:
        """팔로우한 사람의 리그램이 없을 때 — 이번 주 노트를 많이 읽힌 순서로."""
        rows = self.con.execute(
            "select s.ticker, s.name, n.body, s.induty_code, n.made_at,"
            " (select count(*) from views v where v.page = 'note' and v.ticker = s.ticker and v.at >= n.week) c"
            " from notes n join stocks s using(ticker) where n.week = (select max(week) from notes) order by c desc, s.name limit 20").fetchall()  # fmt: skip
        cards = "".join(story(f"/n/{t}", photos.pick(None, ind, name), notes.mend(json.loads(b)["headline"]), gist(json.loads(b)), name, made[:10].replace("-", "."))
                        for t, name, b, ind, made, c in rows)  # fmt: skip
        return (f'<section class="mt-space-lg"><h2 class="font-headline-sm text-headline-sm text-on-surface">많이 읽은 노트</h2>'
                f'<div class="flex flex-col lg:grid lg:grid-cols-2 lg:gap-x-14">{cards}</div></section>')  # fmt: skip

    def suggest(self, uid: int) -> str:
        """추천 프로필 — 최근 2주에 활발한 사람(리그램 ×2 + 좋아요 + 팔로워) 순, 이미 팔로우했거나 요청한 사람은 빼고 (사용자 10/10).
        활발한 사람이 없어도 비우지 않는다 — 사람이 적은 처음엔 누구라도 보여야 팔로우가 시작된다.
        담은 종목으로는 고르지 않는다 — 공개하지 않은 보유 종목이 드러나므로."""
        since = (datetime.now() - timedelta(days=14)).isoformat()
        rows = self.con.execute(
            "select u.id, u.nickname, u.photo_at,"
            " (select count(*) from regrams r where r.user_id = u.id and r.at >= ?) rg,"
            " (select count(*) from likes l where l.user_id = u.id and l.at >= ?) lk,"
            " (select count(*) from follows f where f.followee_id = u.id and f.ok = 1) fer"
            " from users u where u.nickname is not null and u.id != ? and u.id not in (select followee_id from follows where follower_id = ?)",
            (since, since, uid, uid)).fetchall()  # fmt: skip
        gone = self.blocked(uid)
        rows = sorted((r for r in rows if r[0] not in gone), key=lambda r: (-(r[3] * 2 + r[4] + r[5]), r[1]))[:10]
        if not rows:
            return ""

        cards = "".join(
            f'<div class="shrink-0 w-[132px] flex flex-col items-center gap-1.5 text-center"><a href="/u/{i}" class="flex flex-col items-center gap-1.5 min-w-0 w-full">'
            f'{self.face(n, "w-16 h-16", photo_url(i, p))}<b class="text-[14px] text-on-surface truncate w-full">{e(n)}</b>'
            f'</a>{self.follow_button(uid, i, "/me")}</div>'
            for i, n, p, rg, lk, fer in rows)  # fmt: skip
        return (f'<section id="suggest" class="mt-space-lg"><div class="flex items-center justify-between"><h2 class="font-headline-sm text-headline-sm text-on-surface">추천 프로필</h2>'
                '<button type="button" aria-label="추천 프로필 닫기" class="p-1 text-outline hover:text-on-surface" onclick="try{sessionStorage.setItem(\'hideSuggest\',\'1\')}catch(e){}this.closest(\'section\').remove()">'
                '<span class="material-symbols-outlined text-[22px]">close</span></button></div>'
                f'<div class="mt-space-sm -mx-margin px-margin flex gap-4 overflow-x-auto pb-2">{cards}</div></section>'
                "<script>try{if(sessionStorage.getItem('hideSuggest'))document.getElementById('suggest').remove()}catch(e){}</script>")  # fmt: skip

    def tally(self, end: datetime) -> tuple[list, list]:
        """end 앞 7일 — 담은 종목 [(ticker, name, 담은 사람, 담은 사람)] · 읽은 노트 [(ticker, name, 읽은 사람, 조회수)], 많은 순."""
        a, b = (end - timedelta(days=7)).isoformat(), end.isoformat()
        held = self.con.execute("select s.ticker, s.name, count(*), count(*) from holdings h join stocks s using(ticker) where h.added_at >= ? and h.added_at < ?"
                                " group by s.ticker order by count(*) desc, s.name", (a, b)).fetchall()  # fmt: skip
        read = self.con.execute("select s.ticker, s.name, count(distinct v.user_id), count(*) from views v join stocks s using(ticker) where v.page = 'note' and v.at >= ? and v.at < ?"
                                " group by s.ticker order by count(distinct v.user_id) desc, count(*) desc, s.name", (a, b)).fetchall()  # fmt: skip
        return held, read

    def this_week(self) -> str:
        """이번 주 한장 — 몇 명인지는 적지 않고 오르내림만 (배민 순위처럼, 사용자 10/10). 정각마다 새로 센다.
        하루 전보다 담은 사람·조회수가 조금이라도 늘면 ▲, 줄면 ▼, 같으면 – (NEW 는 쓰지 않는다, 사용자 10/10).
        3명 이상일 때만 순위에 — 사람이 적을 때 누가 무엇을 담았는지 짐작되지 않게."""
        now = datetime.now().replace(minute=0, second=0, microsecond=0)
        cur, prev = self.tally(now), self.tally(now - timedelta(days=1))
        up = '<span class="text-[#E5534B] text-[12px]" aria-label="올랐어요">▲</span>'
        down = '<span class="text-[#3B7DDD] text-[12px]" aria-label="내렸어요">▼</span>'
        same = '<span class="text-outline-variant text-[12px]" aria-label="그대로">–</span>'

        def col(title, rows, before):
            rows = [r for r in rows if r[2] >= 3][:5]
            if not rows:
                return ""
            was = {t: v for t, _, _, v in before}
            mark = lambda t, v: up if v > was.get(t, 0) else down if v < was.get(t, 0) else same  # noqa: E731
            items = "".join(f'<a href="/n/{e(t)}" class="py-2.5 flex items-center gap-3"><b class="w-5 text-[16px] text-on-surface tabular-nums">{k + 1}</b>'
                            f'<span class="flex-1 text-[15px] text-on-surface truncate">{e(n)}</span>{mark(t, v)}</a>'
                            for k, (t, n, _, v) in enumerate(rows))  # fmt: skip
            return f'<div><h3 class="text-[13px] font-semibold text-outline">{title}</h3><div class="flex flex-col">{items}</div></div>'

        body = col("많이 담은 종목", cur[0], prev[0]) + col("많이 읽은 노트", cur[1], prev[1])
        when = f'{"오전" if now.hour < 12 else "오후"} {now.hour % 12 or 12}시 업데이트'
        return (f'<section class="mt-space-lg"><h2 class="font-headline-sm text-headline-sm text-on-surface">이번 주 한장</h2>'
                f'<div class="mt-space-sm"><p class="text-[13px] text-outline mb-2">{when}</p>'
                f'<div class="grid grid-cols-1 lg:grid-cols-2 gap-x-14 gap-y-4">{body}</div></div></section>') if body else ""

    def for_you(self, uid: int, today: date | None = None) -> str:
        """오늘의 내 종목 — 담은 종목에 생긴 일을 점수 큰 순으로 한 줄씩(맞춤 피드 1차, 사용자 10/11).
        재료: ① 최근 7일 큰 공시 ② 앞으로 14일 일정(실적 발표·주총·배당) ③ 큰손 움직임(기관 5% 지분 변화 30일 · 임원 거래 14일).
        점수 = 종류의 무게 − 날짜가 먼 만큼. 내 종목만 — 남의 글·추천이 아니라 사실만 모은다. 끝이 있는 피드(「오늘은 여기까지」)."""
        today = today or date.today()
        iso = today.isoformat()
        back = lambda n: (today - timedelta(days=n)).isoformat()  # noqa: E731
        mine = "join holdings h on h.ticker = s.ticker and h.user_id = ?"
        cards = []  # (점수, 아이콘, 색, 종목 이름, 홈페이지, 한 줄, 작은 글, 날짜 표시, 링크)

        def ago(d: str) -> str:
            n = (today - date.fromisoformat(d)).days
            return "오늘" if n <= 0 else "어제" if n == 1 else f"{n}일 전"

        for rno, d, title, code, imp, dr, t, name, home, aid in self.con.execute(
                "select d.rcept_no, d.date, d.title, d.code, d.importance, d.direction, s.ticker, s.name, s.homepage,"
                " (select a.id from articles a where a.ref = d.rcept_no)"
                f" from disclosures d join stocks s on s.ticker = d.ticker {mine}"
                " where d.date between ? and ? and d.importance >= 2 and d.code != 'OTHER' order by d.date desc", (uid, back(7), iso)):  # fmt: skip
            n = (today - date.fromisoformat(d)).days
            cards.append((100 - 10 * n + 5 * (imp or 0), "campaign", "text-primary", name, home, clean_title(title, code),
                          EVENT_EXPLAIN.get(code, ""), ago(d), f"/a/{aid}" if aid else f"/n/{t}"))
        for d, kind, what, t, name, home in self.con.execute(
                f"select e.date, e.kind, e.title, s.ticker, s.name, s.homepage from events e join stocks s on s.ticker = e.ticker {mine}"
                " where e.date between ? and ? order by e.date", (uid, iso, (today + timedelta(days=14)).isoformat())):  # fmt: skip
            n = (date.fromisoformat(d) - today).days
            dd = date.fromisoformat(d)
            cards.append((95 - 5 * n, "event_upcoming", "text-secondary", name, home, what,
                          f'{dd.month}월 {dd.day}일 ({"월화수목금토일"[dd.weekday()]})에 예정돼 있어요.', "오늘" if n == 0 else f"D-{n}", "/calendar"))
        for inst, rate, chg, d, t, name, home in self.con.execute(
                f"select b.inst, b.rate, b.rate_chg, b.date, s.ticker, s.name, s.homepage from big_holdings b join stocks s on s.ticker = b.stock_code {mine}"
                " where b.rate_chg is not null and b.rate_chg != 0 and b.date >= ? order by b.date desc", (uid, back(30))):  # fmt: skip
            if inst not in holders.BIG:
                continue
            n = (today - date.fromisoformat(d)).days
            who = holders.BIG[inst][0]
            cards.append((70 - 2 * n, "account_balance", "text-tertiary", name, home, f'{who}{notes.josa(who, "이")} 지분을 {"늘렸어요" if chg > 0 else "줄였어요"}',
                          f"지분 {rate:.2f}% ({chg:+.2f}%p) — 5% 넘게 가진 기관이 낸 보고예요.", ago(d), f"/learn/big/{inst}"))
        for t, name, home, cnt, net, last in self.con.execute(
                f"select s.ticker, s.name, s.homepage, count(*), sum(i.change), max(i.date) from insiders i join stocks s on s.ticker = i.ticker {mine}"
                " where i.kind = '임원' and i.date >= ? group by s.ticker", (uid, back(14))):  # fmt: skip
            n = (today - date.fromisoformat(last)).days
            side = "사들인 쪽이 많아요" if (net or 0) > 0 else "판 쪽이 많아요" if (net or 0) < 0 else "사고판 양이 비슷해요"
            cards.append((60 - 3 * n, "badge", "text-outline", name, home, f"임원 주식 거래 보고 {cnt}건", f"최근 2주 동안 {side}. 회사에서 받은 보상 주식도 들어 있을 수 있어요.", ago(last), f"/n/{t}"))
        cards.sort(key=lambda c: -c[0])
        items = "".join(
            f'<a href="{e(href)}" class="py-3.5 flex items-start gap-3">{logo(name, home, "w-9 h-9")}'
            f'<span class="min-w-0 flex-1 flex flex-col gap-0.5"><span class="flex items-center gap-1.5 text-[12px] text-outline">'
            f'<span class="material-symbols-outlined text-[15px] {tint}">{icon}</span><b class="font-medium text-on-surface-variant truncate">{e(name)}</b></span>'
            f'<span class="text-[15px] leading-[21px] font-semibold text-on-surface">{e(head)}</span>'
            f'<span class="text-[13px] leading-[19px] text-on-surface-variant line-clamp-2">{e(sub)}</span></span>'
            f'<span class="shrink-0 pt-0.5 text-[12px] text-outline tabular-nums">{e(when)}</span></a>'
            for _, icon, tint, name, home, head, sub, when, href in cards[:12])  # fmt: skip
        (has,) = self.con.execute("select count(*) from holdings where user_id = ?", (uid,)).fetchone()
        empty = ("아직 담은 종목이 없어요. 종목을 담으면 그 종목에 생긴 일을 여기에 모아 드려요." if not has
                 else "오늘은 내 종목에 새로 생긴 일이 없어요.")
        return ('<section class="mt-space-lg"><h2 class="font-headline-sm text-headline-sm text-on-surface">오늘의 내 종목</h2>'
                '<p class="mt-0.5 text-[12px] text-outline">내가 담은 종목에 생긴 일을 관련 큰 순으로 모았어요.</p>'
                + (f'<div class="flex flex-col divide-y divide-surface-container-high/70">{items}</div>'
                   '<p class="py-3 text-center text-[12px] text-outline">오늘은 여기까지예요. 사실만 모았어요 — 사고팔라는 뜻이 아니에요.</p>' if items
                   else f'<p class="py-6 text-center text-[13px] text-on-surface-variant">{empty}</p>') + "</section>")  # fmt: skip

    def feed(self, uid: int, q: str) -> str:
        mine = "where r.user_id in (select followee_id from follows where follower_id = ? and ok = 1) or r.user_id = ?"
        (n,) = self.con.execute("select count(*) from regrams r " + mine, (uid, uid)).fetchone()
        photos = Photos()
        news = self.latest(uid, photos)
        body = self.for_you(uid) + self.this_week() + news + (self.regram_list(mine, (uid, uid), "팔로우한 사람들의 리그램", photos=photos) if n else "") + ("" if news or n else self.popular(photos))
        inner = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] lg:max-w-[1200px] mx-auto pt-14 pb-24 lg:pt-20 lg:pb-16 bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-6">'
                 '<header class="pt-5"><h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight">피드</h1></header>'
                 + '<form method="get" action="/feed" class="mt-space-md flex items-center gap-space-sm bg-surface-container-low rounded-xl px-4 py-2.5"><span class="material-symbols-outlined text-outline text-[20px]">person_search</span>'
                 f'<input class="flex-1 bg-transparent font-body-compact text-body-compact focus:outline-none" name="q" value="{e(q)}" placeholder="닉네임으로 사람 찾기"></form>'
                 + self.people(uid, q) + body
                 + "</div></main>" + bottom_nav("feed"))  # fmt: skip
        return page("피드", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    def blocked(self, uid: int) -> set[int]:
        """내가 차단했거나 나를 차단한 사람 — 서로 보이지 않는다."""
        return {a if a != uid else b for a, b in self.con.execute("select user_id, blocked_id from blocks where user_id = ? or blocked_id = ?", (uid, uid))}

    def blocked_list(self, uid: int) -> str:
        """설정 화면 — 차단한 사람. 찾기에 안 나오니 푸는 길은 여기(이름을 누르면 「차단 풀기」가 있는 화면)."""
        rows = self.con.execute("select u.id, u.nickname from blocks b join users u on u.id = b.blocked_id where b.user_id = ? order by b.at desc", (uid,)).fetchall()
        if not rows:
            return ""
        return ('<section class="mt-space-lg"><h2 class="font-label-regular text-label-regular text-on-surface font-semibold">차단한 사람</h2><div class="mt-1 flex flex-col">'
                + "".join(f'<a class="py-2 font-body-compact text-body-compact text-primary underline" href="/u/{i}">{e(n or "(이름 없음)")}</a>' for i, n in rows) + "</div></section>")

    def block(self, uid: int, other: int):
        """차단(한 번 더 누르면 풀기) — 서로의 팔로우·요청을 지운다. 그래서 피드에도 저절로 안 나온다."""
        if not self.con.execute("delete from blocks where user_id = ? and blocked_id = ?", (uid, other)).rowcount:
            self.con.execute("insert into blocks values (?, ?, ?)", (uid, other, datetime.now().isoformat()))
            self.con.execute("delete from follows where (follower_id = ? and followee_id = ?) or (follower_id = ? and followee_id = ?)", (uid, other, other, uid))
        self.con.commit()
        return self.see(f"/u/{other}")

    def report_user(self, uid: int, other: int, why: str):
        """신고 — 적어 두고 운영자에게 바로 메일. 같은 사람을 여러 번 눌러도 처리 전에는 한 건. 처리는 `python -m hanjang.moderate`."""
        why = why if why in REPORT_WHY else "기타"
        if not self.con.execute("select 1 from reports where user_id = ? and target_id = ? and done_at is null", (uid, other)).fetchone():
            self.con.execute("insert into reports (user_id, target_id, why, at) values (?, ?, ?, ?)", (uid, other, why, datetime.now().isoformat()))
            self.con.commit()
            nick, bio, has_photo = self.con.execute("select nickname, bio, photo is not null from users where id = ?", (other,)).fetchone()
            if to := env().get("SMTP_USER"):
                with self.outside():
                    mail.send(to, f"[한장] 신고 — {why}", f"신고된 사람: #{other} {nick or '(닉네임 없음)'}\n자기소개: {bio or '(없음)'}\n프로필 사진: {'있음' if has_photo else '없음'}\n"
                              f"프로필: {mail.base_url()}/u/{other}\n신고한 사람: #{uid}\n\n24시간 안에 확인해요(이용 규칙). 서버에서:\n"
                              f"  프로필 지우기  python -m hanjang.moderate wipe {other}\n  계정 막기      python -m hanjang.moderate ban {other}\n  문제없음       python -m hanjang.moderate ok {other}")  # fmt: skip
        return "200 OK", [], self.simple("신고", f"신고를 받았어요. 운영자가 24시간 안에 확인해요. <a class='text-primary underline' href='/u/{other}'>돌아가기</a>")

    def user_page(self, uid: int, other: int):
        row = self.con.execute("select nickname, bio, photo_at from users where id = ? and nickname is not null", (other,)).fetchone()
        mine = self.con.execute("select 1 from blocks where user_id = ? and blocked_id = ?", (uid, other)).fetchone()
        if not row or (other in self.blocked(uid) and not mine):  # 닉네임이 없는 사람 · 나를 차단한 사람은 보이지 않는다
            return "404 Not Found", [], self.simple("없음", "없는 사람이에요. <a class='text-primary underline' href='/feed'>피드</a>")
        nick, bio, pat = row
        if mine:  # 내가 차단한 사람 — 이름과 풀기 단추만
            return "200 OK", [], self.simple(nick, f"<b>{e(nick)}</b> 님을 차단했어요. 서로의 프로필과 리그램이 보이지 않아요."
                                             f"<form method='post' action='/block' class='mt-4'><input type='hidden' name='u' value='{other}'>"
                                             "<button class='text-primary underline' type='submit'>차단 풀기</button></form>"
                                             "<a class='mt-4 inline-block text-primary underline' href='/feed'>피드로 돌아가기</a>")
        # 신고·차단 — 눈에 띄지 않게 접어 둔다 (앱 마켓의 사용자 콘텐츠 요구: 신고 · 차단 · 빠른 처리)
        more = ('<details class="mt-space-lg"><summary class="font-label-micro text-label-micro text-outline cursor-pointer">신고 · 차단</summary>'
                '<div class="mt-2 flex flex-col gap-3 rounded-xl border border-outline-variant/50 px-space-md py-3">'
                f'<form method="post" action="/report" class="flex flex-col gap-2"><input type="hidden" name="u" value="{other}">'
                '<span class="font-label-regular text-label-regular text-on-surface font-semibold">이 프로필 신고하기</span>'
                + "".join(f'<label class="flex items-center gap-2 font-body-compact text-body-compact text-on-surface-variant"><input class="accent-primary" name="why" required type="radio" value="{w}">{w}</label>' for w in REPORT_WHY)
                + '<button class="self-start font-label-regular text-label-regular text-tertiary underline" type="submit">신고 보내기</button></form>'
                f'<form method="post" action="/block" onsubmit="return confirm(\'차단하면 서로 팔로우가 풀리고, 서로의 프로필과 리그램이 보이지 않아요. 차단할까요?\')"><input type="hidden" name="u" value="{other}">'
                '<button class="font-label-regular text-label-regular text-tertiary underline" type="submit">이 사람 차단하기</button></form>'
                '<a class="font-label-micro text-label-micro text-outline underline" href="/rules">이용 규칙</a></div></details>')  # fmt: skip
        label, on = self.follow_state(uid, other)
        btn = "border border-outline-variant/60 text-on-surface-variant" if on else "bg-primary text-on-primary"
        shut = ('<div class="mt-space-xl py-10 flex flex-col items-center gap-2 border-t border-surface-container-high text-center">'
                '<span class="material-symbols-outlined text-outline text-[30px]">lock</span>'
                '<b class="font-body-reading-strong text-body-compact text-on-surface">비공개 계정이에요</b>'
                '<span class="font-body-compact text-body-compact text-on-surface-variant">팔로우 요청을 수락하면 나무와 리그램, 팔로워 목록을 볼 수 있어요.</span></div>')  # fmt: skip
        see = self.can_see(uid, other)
        inner = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] lg:max-w-[1200px] mx-auto pt-14 pb-24 lg:pt-20 lg:pb-16 bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-6">'
                 f'<header class="pt-5 flex items-center gap-space-md">{self.face(nick, "w-14 h-14", photo_url(other, pat))}<div class="flex flex-col min-w-0 flex-1">'
                 f'<div class="flex items-center gap-2 min-w-0"><h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight truncate">{e(nick)}</h1></div>{self.follow_line(other, see)}</div>'
                 f'<form method="post" action="/follow"><input type="hidden" name="u" value="{other}"><button class="px-4 py-2 rounded-lg font-label-regular text-label-regular font-semibold {btn}" type="submit">{label}</button></form></header>'
                 + (f'<p class="mt-space-md font-body-compact text-body-compact text-on-surface whitespace-pre-line">{e(bio)}</p>' if bio else "")
                 + ((self.my_tree(other, nick=nick) + self.regram_list("where r.user_id = ?", (other,), f"{nick}의 리그램", mine=True)) if see else shut)
                 + (more if other != uid else "")
                 + "</div></main>" + bottom_nav("feed"))  # fmt: skip
        return "200 OK", [], page(nick, "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    # ---- 큰손 포트폴리오 (읽기 팁 맨 아래) — 기관이 5% 넘게 가진 종목, 전체 상장사 ----

    # 기관 홈페이지 — 로고(Brandfetch)를 찾는 열쇠. 없으면 색 동그라미 (국민연금은 흰 로고라 뺌, 계열사는 그룹 로고가 또렷함)
    BIG_HOME = {"blackrock": "blackrock.com", "capital": "capitalgroup.com", "samsungam": "samsung.com",
                "miraeam": "miraeasset.com", "shinhanam": "shinhangroup.com", "kbam": "kbfg.com",
                "kitm": "kitmc.com", "align": "alignpartners.co.kr", "silchester": "silchester.com", "pzena": "pzena.com"}  # fmt: skip

    def big_list(self) -> str:
        counts = dict(self.con.execute("select inst, count(*) from big_holdings group by inst").fetchall())
        rows = [(k, v) for k, v in holders.BIG.items() if counts.get(k)]
        if not rows:
            return ""
        rows.sort(key=lambda kv: -counts[kv[0]])
        items = "".join(
            f'<a href="/learn/big/{k}" class="py-3.5 flex items-center gap-space-md">{logo(name, self.BIG_HOME.get(k), "w-10 h-10")}'
            f'<span class="flex flex-col min-w-0 flex-1"><span class="font-body-reading-strong text-body-compact text-on-surface">{e(name)}</span>'
            f'<span class="font-label-micro text-label-micro text-on-surface-variant truncate">{e(intro)}</span></span>'
            f'<span class="text-[12px] text-outline shrink-0">{counts[k]:,}종목</span></a>' for k, (name, _, intro) in rows)  # fmt: skip
        return ('<section class="mt-space-xl pt-space-md border-t border-surface-container-high"><h2 class="font-headline-md text-headline-md text-primary border-l-4 border-primary pl-2 leading-none">큰손 포트폴리오</h2>'
                '<p class="mt-2 font-body-compact text-body-compact text-on-surface-variant">국민연금·운용사 같은 기관이 5% 넘게 가진 회사들이에요. 공시로 알려진 것만 보여요.</p>'
                f'<div class="flex flex-col divide-y divide-surface-container-high/80">{items}</div></section>')  # fmt: skip

    def nps_portfolio(self, after_pie: str = "") -> str:
        """국민연금 주식 — 한국(국민연금 연간 공시 평가액)과 미국(같은 날 13F, 한국은행 환율로 원화)을 금액 큰 순 하나로. 파이도 그 비중."""
        rows = self.con.execute(
            "select p.market, p.name, p.ticker, p.won, s.name, s.homepage, exists(select 1 from notes n where n.ticker = p.ticker),"
            " coalesce(s.induty_code, (select b.induty_code from big_holdings b where b.stock_code = p.ticker limit 1)), s.sic"
            " from nps_port p left join stocks s on s.ticker = p.ticker order by p.won desc").fetchall()  # fmt: skip
        meta = self.con.execute("select asof, fx from nps_meta order by asof desc limit 1").fetchone()
        if not rows or not meta:
            return ""
        total = sum(r[3] for r in rows)
        n_kr = sum(r[0] == "KR" for r in rows)

        def label(r):
            mkt, name, _, _, kname, *_ = r
            return name if mkt == "KR" else issuer_name(name, kname)

        def line(i, r):
            mkt, name, t, won, _, home, has_note, kr, sic = r
            tag = ('<span class="ml-1.5 px-1.5 py-px rounded text-[10px] font-semibold align-middle '
                   + ("bg-surface-container-high text-on-surface-variant\">한국" if mkt == "KR" else "bg-secondary-container text-on-secondary-container\">미국") + "</span>")
            inner = (f'<span class="w-5 text-right text-[12px] text-outline tabular-nums">{i}</span>{logo(label(r), home, "w-9 h-9")}'
                     f'<span class="flex flex-col min-w-0 flex-1"><span class="flex items-baseline gap-1.5 min-w-0"><span class="text-[15px] font-semibold text-on-surface truncate">{e(label(r))}{tag}</span>'
                     f'{ind_tag(kr if mkt == "KR" else None, sic, name)}</span>'
                     f'<span class="text-[12px] text-on-surface-variant">비중 {won / total * 100:.1f}% · {e(sources.won_short(won))}</span></span>')  # fmt: skip
            return f'<a href="/n/{e(t)}" class="py-3 flex items-center gap-3">{inner}</a>' if has_note else f'<div class="py-3 flex items-center gap-3">{inner}</div>'

        return ('<section class="mt-space-xl pt-space-md border-t border-surface-container-high"><h2 class="font-headline-md text-headline-md text-on-surface">주식 포트폴리오 · 한국+미국</h2>'
                + pie([(label(r), r[3]) for r in rows]) + after_pie
                + '<div class="mt-space-sm flex flex-col divide-y divide-surface-container-high/70">' + "".join(line(i, r) for i, r in enumerate(rows[:TOP_LIST], 1)) + "</div>"
                + (f'<p class="pt-2 text-[12px] text-outline">외 {len(rows) - TOP_LIST:,}종목</p>' if len(rows) > TOP_LIST else "")
                + '<p class="mt-2 text-[11px] text-outline leading-relaxed">한국 주식은 국민연금이 공개한 종목별 평가액(공공데이터포털 「국민연금공단_국내주식 투자정보」), '
                + f'미국 주식은 같은 날 미국 증권거래위원회(SEC)에 낸 보유 신고(13F)예요. 달러는 그날 한국은행 환율(1달러 {meta[1]:,.1f}원)로 바꿨어요. '
                + f'한국 {n_kr:,}종목 · 미국 {len(rows) - n_kr:,}종목. 1년에 한 번 나오는 공시라 지금과 다를 수 있어요.</p></section>')  # fmt: skip

    def us_portfolio(self, key: str, after_pie: str = "") -> str:
        """기관의 미국 주식 — 13F 로 보유 전체가 공개된다(국내 5% 보고와 달리). 파이 + 큰 10종목."""
        rows = self.con.execute(
            "select g.issuer, g.ticker, g.value, g.weight, g.period, s.name, s.homepage, exists(select 1 from notes n where n.ticker = g.ticker),"
            " coalesce(nullif(g.sic, ''), s.sic)"
            " from guru_holdings g left join stocks s on s.ticker = g.ticker where g.guru = ? order by g.value desc", (key,)).fetchall()  # fmt: skip
        if not rows:
            return ""
        total = sum(r[2] for r in rows)

        def line(i, r):
            issuer, t, value, weight, _, kname, khome, has_note, sic = r
            label = issuer_name(issuer, kname)
            inner = (f'<span class="w-5 text-right text-[12px] text-outline tabular-nums">{i}</span>{logo(label, khome, "w-9 h-9")}'
                     f'<span class="flex flex-col min-w-0 flex-1"><span class="flex items-baseline gap-1.5 min-w-0"><span class="text-[15px] font-semibold text-on-surface truncate">{e(label)}</span>{ind_tag(sic=sic, issuer=issuer)}</span>'
                     f'<span class="text-[12px] text-on-surface-variant">비중 {weight:.1f}% · {e(notes.usd(value))}</span></span>')  # fmt: skip
            return f'<a href="/n/{e(t)}" class="py-3 flex items-center gap-3">{inner}</a>' if has_note else f'<div class="py-3 flex items-center gap-3">{inner}</div>'

        return ('<section class="mt-space-xl pt-space-md border-t border-surface-container-high"><h2 class="font-headline-md text-headline-md text-on-surface">미국 주식 포트폴리오</h2>'
                f'<p class="mt-1 text-[12px] text-outline">미국 주식 {len(rows):,}종목 · {e(notes.usd(total))} · {kdate(rows[0][4])} 기준</p>'
                + pie([(issuer_name(r[0], r[5]), r[2]) for r in rows]) + after_pie
                + '<div class="mt-space-sm flex flex-col divide-y divide-surface-container-high/70">' + "".join(line(i, r) for i, r in enumerate(rows[:TOP_LIST], 1)) + "</div>"
                + (f'<p class="pt-2 text-[12px] text-outline">외 {len(rows) - TOP_LIST:,}종목</p>' if len(rows) > TOP_LIST else "")
                + '<p class="mt-2 text-[11px] text-outline leading-relaxed">미국은 큰 투자자가 분기마다 미국 주식 보유 전체를 미국 증권거래위원회(SEC)에 신고해요(13F). '
                "분기가 끝나고 45일 안에 나와서 지금과 다를 수 있어요. 미국 밖 주식은 들어 있지 않아요.</p></section>")  # fmt: skip

    def owners(self, ticker: str) -> tuple:
        """(제목, 설명, [(이름, 링크, 홈페이지, 한 줄)]) — 미국은 13F 유명 투자자(비중 큰 순), 국내는 5% 넘게 가진 기관(지분 큰 순)."""
        got = self.con.execute("select guru, weight, period from guru_holdings where ticker = ? order by weight desc", (ticker,)).fetchall()
        if got:  # 유명 투자자가 먼저, 그다음 기관 — 블랙록처럼 모든 종목을 조금씩 가진 곳이 위를 덮지 않게
            rows = ([(gurus.GURUS[k][0], f"/learn/guru/{k}", guru_face(k, "w-9 h-9"), f"포트폴리오의 {w:.1f}% · {kdate(p)} 기준") for k, w, p in got if k in gurus.GURUS]
                    + [(holders.BIG[k][0], f"/learn/big/{k}", logo(holders.BIG[k][0], self.BIG_HOME.get(k), "w-9 h-9"), f"미국 주식의 {w:.1f}% · {kdate(p)} 기준")
                       for k, w, p in got if k in holders.BIG and k not in gurus.GURUS])  # fmt: skip
            return ("이 종목을 가진 유명 투자자·기관",
                    "미국 투자자가 분기마다 내는 보유 신고(SEC 13F)예요. 분기가 끝나고 45일 안에 나와서 지금과 다를 수 있어요. 따라 사고팔라는 뜻이 아니에요.", rows)
        kr = self.con.execute("select inst, rate, date from big_holdings where stock_code = ? order by rate desc", (ticker,)).fetchall()
        rows = [(holders.BIG[k][0], f"/learn/big/{k}", logo(holders.BIG[k][0], self.BIG_HOME.get(k), "w-9 h-9"), f"지분 {r:.2f}% · {kdate(d)} 보고")
                for k, r, d in kr if k in holders.BIG]  # fmt: skip
        return ("이 종목을 5% 넘게 가진 기관", "5% 넘게 가지면 내는 대량보유 보고(DART)로 알려진 것만이에요. 따라 사고팔라는 뜻이 아니에요.", rows)

    def guru_list(self) -> str:
        got = {k: n for k, n in self.con.execute("select guru, count(*) from guru_holdings group by guru")}
        keys = [k for k in gurus.GURUS if k in got]
        if not keys:
            return ""
        items = "".join(
            f'<a href="/learn/guru/{k}" class="py-3.5 flex items-center gap-space-md">{guru_face(k)}'
            f'<span class="flex flex-col min-w-0 flex-1"><span class="font-body-reading-strong text-body-compact text-on-surface">{e(gurus.GURUS[k][0])}</span>'
            f'<span class="font-label-micro text-label-micro text-on-surface-variant truncate">{e(gurus.GURUS[k][2])}</span></span>'
            f'<span class="text-[12px] text-outline shrink-0">{got[k]:,}종목</span></a>' for k in keys)  # fmt: skip
        return ('<section class="mt-space-xl pt-space-md border-t border-surface-container-high"><h2 class="font-headline-md text-headline-md text-primary border-l-4 border-primary pl-2 leading-none">미국 유명 투자자</h2>'
                '<p class="mt-2 font-body-compact text-body-compact text-on-surface-variant">워런 버핏·캐시 우드 같은 투자자가 분기마다 미국 증권거래위원회(SEC)에 낸 보유 종목이에요.</p>'
                f'<div class="flex flex-col divide-y divide-surface-container-high/80">{items}</div></section>')  # fmt: skip

    def guru(self, uid: int, key: str, wrap: str, end: str):
        if key not in gurus.GURUS:
            return "404 Not Found", [], self.simple("없음", "없는 투자자예요. <a class='text-primary underline' href='/learn'>읽기 팁</a>")
        name, cik, intro, home = gurus.GURUS[key]
        def build():
            rows = self.con.execute(
                "select g.issuer, g.ticker, g.value, g.weight, g.period, g.filed, g.accn, s.name, s.homepage,"
                " exists(select 1 from notes n where n.ticker = g.ticker), g.sic from guru_holdings g left join stocks s on s.ticker = g.ticker"
                " where g.guru = ? order by g.value desc", (key,)).fetchall()  # fmt: skip
            if not rows:
                return None
            period, filed, accn = rows[0][4], rows[0][5], rows[0][6]
            total = sum(r[2] for r in rows)
            sec_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn.replace('-', '')}/"
            top_pie = pie([(issuer_name(r[0], r[7]), r[2]) for r in rows])
            pie_ = bars([gurus.sector(r[10], r[0]) for r in rows], [r[2] for r in rows], "종목",
                        "가진 종목을 금액으로 큰 업종(SEC 산업분류)에 나눈 비율이에요. 업종을 못 찾은 회사는 기타에 넣었어요.")

            def row(i, r):
                issuer, t, value, weight, _, _, _, kname, khome, has_note, sic = r
                label = issuer_name(issuer, kname)
                inner = (f'<span class="w-5 text-right text-[12px] text-outline tabular-nums">{i}</span>{logo(label, khome, "w-9 h-9")}'
                         f'<span class="flex flex-col min-w-0 flex-1"><span class="flex items-baseline gap-1.5 min-w-0"><span class="text-[15px] font-semibold text-on-surface truncate">{e(label)}</span>{ind_tag(sic=sic, issuer=issuer)}</span>'
                         f'<span class="text-[12px] text-on-surface-variant">비중 {weight:.1f}% · {e(notes.usd(value))}</span></span>')  # fmt: skip
                if has_note:  # 우리 노트가 있는 종목만 누르면 노트로
                    return f'<a href="/n/{e(t)}" class="py-3 flex items-center gap-3">{inner}<span class="material-symbols-outlined text-outline text-[18px]">chevron_right</span></a>'
                return f'<div class="py-3 flex items-center gap-3">{inner}</div>'

            top = rows[:TOP_LIST]
            body = (f'<div class="flex items-center py-space-sm"><a class="flex items-center gap-space-xs text-on-surface-variant hover:text-primary" href="/learn"><span class="material-symbols-outlined text-[18px]">arrow_back</span><span class="font-label-regular text-label-regular font-medium">읽기 팁</span></a></div>'
                    f'<header class="flex items-center gap-space-md">{guru_face(key, "w-14 h-14")}<div class="flex flex-col"><h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight">{e(name)}</h1>'
                    f'<span class="text-[12px] text-outline">미국 주식 {len(rows):,}종목 · {e(notes.usd(total))} · {kdate(period)} 기준</span></div></header>'
                    f'<p class="mt-space-md font-body-compact text-body-compact text-on-surface">{e(intro)}</p>' + top_pie + pie_
                    + '<section class="mt-space-lg"><h2 class="font-headline-sm text-headline-sm text-on-surface">많이 가진 순서</h2><div class="flex flex-col divide-y divide-surface-container-high/70">'
                    + "".join(row(i, r) for i, r in enumerate(top, 1)) + "</div>"
                    + (f'<p class="pt-2 text-[12px] text-outline">외 {len(rows) - len(top):,}종목</p>' if len(rows) > len(top) else "") + "</section>"
                    + '<p class="mt-space-md text-[11px] text-outline leading-relaxed">미국은 운용 자산이 1억 달러가 넘는 투자자가 분기마다 미국 주식 보유를 신고해요(13F). '
                    + f'{kdate(period)} 기준, {kdate(filed)}에 낸 신고예요. 분기가 끝나고 45일 안에 나와서 지금은 다를 수 있고, 미국 밖 주식·현금·공매도는 들어 있지 않아요. '
                    + f'따라 사고팔라는 뜻이 아니에요. 자료: <a class="underline" href="{e(sec_url)}" target="_blank" rel="noopener">SEC 13F 원문</a>'
                    + (f' · 사진: <a class="underline" href="{e(PEOPLE[key][2])}" target="_blank" rel="noopener">{e(PEOPLE[key][0])}</a>, {e(PEOPLE[key][1])}, 위키미디어 공용'
                       if key in PEOPLE else "") + '</p>')  # fmt: skip
            return body

        body = self.cached(f"guru:{key}", build)
        if body is None:
            return "404 Not Found", [], self.simple("없음", "아직 받은 신고가 없어요. <a class='text-primary underline' href='/learn'>읽기 팁</a>")
        return "200 OK", [], page(name, "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", wrap + body + end)

    def big(self, uid: int, key: str, wrap: str, end: str):
        if key not in holders.BIG:
            return "404 Not Found", [], self.simple("없음", "없는 기관이에요. <a class='text-primary underline' href='/learn'>읽기 팁</a>")
        name, _, intro = holders.BIG[key]
        def build():
            (n_us,) = self.con.execute("select count(*) from guru_holdings where guru = ?", (key,)).fetchone()
            (n_all,) = self.con.execute("select count(*) from nps_port").fetchone() if key == "nps" else (0,)
            us_n = f" · 한국·미국 주식 {n_all:,}종목" if n_all else f" · 미국 주식 {n_us:,}종목" if n_us else ""
            rows = self.con.execute(
                "select b.stock_code, b.corp_name, b.rate, b.rate_chg, b.date, b.rcept_no, s.ticker is not null, s.homepage"
                " from big_holdings b left join stocks s on s.ticker = b.stock_code where b.inst = ? order by b.rate desc", (key,)).fetchall()  # fmt: skip
            inds = [x for (x,) in self.con.execute("select induty_code from big_holdings where inst = ?", (key,))]
            industry = bars([sector(x) for x in inds], [1] * len(inds), "곳", "한국에서 5% 넘게 가진 회사들을 큰 업종(통계청 산업분류)으로 나눠 센 비율이에요. 위 그림과 기준이 달라요.")
            # 파이 → 업종 → 많이 가진 순서. 「최근 늘리고 줄인 회사」·「지분이 큰 순서」는 뺐다(너무 자세하다, 사용자 10/10 — 5% 보고는 종목 노트 맨 밑에 남아 있다)
            port = self.nps_portfolio(industry) if key == "nps" else ""
            port = port or self.us_portfolio(key, industry)

            def row(i, r):  # 미국 신고가 없는 기관(신한·KB 등)만 — 5% 넘게 가진 회사가 이 페이지의 전부라 남긴다
                code, corp, rate, _, d, rno, ours, home = r
                href = f"/n/{code}" if ours else DART_VIEW.format(rno)
                return (f'<a href="{e(href)}" {"" if ours else "target=_blank rel=noopener"} class="py-3 flex items-center gap-3">'
                        f'<span class="w-5 text-right text-[12px] text-outline tabular-nums">{i}</span>{logo(corp, home, "w-9 h-9")}'
                        f'<span class="flex flex-col min-w-0 flex-1"><span class="text-[15px] font-semibold text-on-surface truncate">{e(corp)}</span>'
                        f'<span class="text-[12px] text-on-surface-variant">지분 {rate:.2f}%</span></span></a>')  # fmt: skip

            kr_only = ("" if port else industry
                       + '<section class="mt-space-lg"><h2 class="font-headline-sm text-headline-sm text-on-surface">5% 넘게 가진 회사</h2><div class="flex flex-col divide-y divide-surface-container-high/70">'
                       + "".join(row(i, r) for i, r in enumerate(rows, 1)) + "</div></section>"
                       + '<p class="mt-space-md text-[11px] text-outline leading-relaxed">한국엔 기관의 보유 종목 전체를 알리는 제도가 없어서, 5% 넘게 가진 회사만 보여요(대량보유 보고). '
                       "따라 사고팔라는 뜻이 아니에요. 자료: DART</p>")  # fmt: skip
            body = (f'<div class="flex items-center py-space-sm"><a class="flex items-center gap-space-xs text-on-surface-variant hover:text-primary" href="/learn"><span class="material-symbols-outlined text-[18px]">arrow_back</span><span class="font-label-regular text-label-regular font-medium">읽기 팁</span></a></div>'
                    f'<header class="flex items-center gap-space-md">{logo(name, self.BIG_HOME.get(key), "w-14 h-14")}<div class="flex flex-col"><h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight">{e(name)}</h1>'
                    f'<span class="text-[12px] text-outline">5% 넘게 가진 회사 {len(rows):,}곳{us_n}</span></div></header>'
                    f'<p class="mt-space-md font-body-compact text-body-compact text-on-surface">{e(intro)}</p>' + port + kr_only)  # fmt: skip
            return body

        body = self.cached(f"big:{key}", build)
        return "200 OK", [], page(name, "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", wrap + body + end)

    # ---- 공개 페이지: 개인정보 처리방침 · 계산 방법 (로그인 없이) ----

    def doc(self, path: str, uid: int | None) -> str:
        contact = env().get("PRIVACY_CONTACT", "")
        title, parts = {"/privacy": ("개인정보 처리방침", policy.privacy(contact)), "/method": ("계산 방법", policy.method()),
                        "/help/login": ("로그인 링크가 안 와요", policy.login_help(contact)), "/rules": ("이용 규칙", policy.rules(contact))}[path]  # fmt: skip
        body = "".join(
            f'<section class="mt-space-lg"><h2 class="font-headline-sm text-headline-sm text-primary mb-space-xs">{e(h)}</h2>'
            + "".join(f'<p class="font-body-compact text-body-compact text-on-surface leading-relaxed mb-space-sm">{self.marked(x)}</p>' for x in ps)
            + "</section>" for h, ps in parts)  # fmt: skip
        inner = ('<main class="flex flex-col relative w-full max-w-[480px] lg:max-w-[760px] mx-auto bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pt-space-lg pb-24">'
                 '<a class="flex items-center gap-space-xs text-on-surface-variant hover:text-primary" href="/"><span class="material-symbols-outlined text-[18px]">arrow_back</span>'
                 '<span class="font-label-regular text-label-regular font-medium">한장</span></a>'
                 f'<h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight mt-space-md">{e(title)}</h1>'
                 f'<p class="font-label-micro text-label-micro text-outline mt-1">마지막 고침 {policy.UPDATED}</p>{body}</div></main>'
                 + (bottom_nav("me") if uid else ""))  # fmt: skip
        return page(title, "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)

    # ---- 읽기 팁 (시안에 없는 화면 — 같은 디자인 말투로) ----

    @staticmethod
    def marked(text: str) -> str:
        """「**핵심 말**」 → 진한 초록 굵은 글씨. 나머지는 그대로 이스케이프."""
        return re.sub(r"\*\*(.+?)\*\*", r'<strong class="font-semibold text-primary">\1</strong>', e(text))

    def flow(self, paras: list[str]) -> str:
        """읽기 팁 본문 — 짧은 문단을 둘씩 묶어 한 덩어리로, 줄 간격은 노트보다 조금 촘촘하게.
        한두 문장짜리 문단이 하나씩 떨어져 보여 글이 끊겨 읽히던 것 (사용자 10/10)."""
        groups = [" ".join(paras[k:k + 2]) for k in range(0, len(paras), 2)]
        return "".join(f'<p class="font-body-reading text-body-reading text-on-surface leading-[1.8] mb-5">{self.marked(g)}</p>' for g in groups)

    @staticmethod
    def related(slug: str) -> str:
        """글 아래 「함께 읽으면 좋은 팁」 — 이어 읽을 글 세 편 (사용자 10/10)."""
        items = [learn.BY_SLUG[x] for x in learn.RELATED.get(slug, []) if x in learn.BY_SLUG]
        if not items:
            return ""
        return ('<section class="mt-space-xl pt-space-md border-t border-surface-container-high"><h2 class="font-headline-sm text-headline-sm text-on-surface mb-1">함께 읽으면 좋은 팁</h2>'
                '<div class="flex flex-col divide-y divide-surface-container-high/80">'
                + "".join(f'<a href="/learn/{e(x["slug"])}" class="py-3 flex items-center justify-between gap-space-sm group"><span class="flex flex-col min-w-0">'
                          f'<span class="text-[12px] text-primary font-semibold">{e(x["cat"])}</span>'
                          f'<span class="font-body-reading-strong text-body-reading-strong text-on-surface group-hover:underline">{e(x["title"])}</span></span>'
                          '<span class="material-symbols-outlined text-primary text-[18px]">chevron_right</span></a>' for x in items)
                + "</div></section>")  # fmt: skip

    def learn(self, uid: int, slug: str):
        wrap = (top_bar(self.initial(uid)) + '<main class="flex flex-col relative w-full max-w-[480px] lg:max-w-[760px] mx-auto pt-14 pb-24 lg:pt-20 lg:pb-16 bg-surface min-h-screen"><div class="flex flex-col w-full px-margin pb-6">')
        end = ('<p class="font-label-micro text-label-micro text-outline text-center py-space-lg">설명을 위한 글이에요. 특정 종목이나 상품을 추천하지 않아요.</p></div></main>'
               + bottom_nav("learn"))
        if slug.startswith("big/"):  # 큰손 포트폴리오 한 곳
            return self.big(uid, slug[4:], wrap, end)
        if slug.startswith("guru/"):  # 미국 유명 투자자 한 명
            return self.guru(uid, slug[5:], wrap, end)
        a = learn.BY_SLUG.get(slug)
        if slug == "long-short":  # 숫자를 DB 의 지수로 채운 글
            a = learn.long_short(self.con) or a
        if slug == "rates":  # 숫자를 DB 의 금리로 채운 글
            a = learn.rates(self.con) or a
        if slug and not a:
            return "404 Not Found", [], self.simple("없음", "없는 글이에요. <a class='text-primary underline' href='/learn'>읽기 팁</a>")
        if a:
            more_label, more_url = a["more"]
            face, credit = book_face(slug)
            inner = (wrap + '<div class="flex items-center py-space-sm"><a class="flex items-center gap-space-xs text-on-surface-variant hover:text-primary transition-colors" href="/learn"><span class="material-symbols-outlined text-[18px]">arrow_back</span>'
                     f'<span class="font-label-regular text-label-regular font-medium">읽기 팁</span></a><span class="ml-2 px-2 py-0.5 rounded-full bg-primary text-on-primary font-label-micro text-label-micro font-semibold">{e(a["cat"])}</span></div>'
                     f'<h1 class="font-display-editorial text-display-editorial text-on-surface font-semibold tracking-tight mb-space-sm">{e(a["title"])}</h1>'
                     + f'<aside class="my-space-xl lg:my-10 text-center">{RULE}<p class="py-space-lg px-space-md font-body-reading-strong font-bold text-[18px] leading-[30px] lg:text-[20px] lg:leading-[34px] text-primary">{self.marked(a["lead"])}</p>{RULE_FLIP}</aside>'
                     + '<div class="block">' + face + self.flow(a["body"][:1]) + '<div class="clear-both"></div></div>'
                     + figure(learn.FIGURE.get(slug))
                     + (index_chart(a["charts"]) + loss_bars(a["charts"]) if a.get("charts") else "")
                     + (rate_ladder(a["now"], a["month"]) + rate_chart(a["rates"]) if a.get("rates") else "")
                     + self.flow(a["body"][1:] + [x.replace("**", "") for x in learn.STORY.get(slug, [])])
                     + '<section class="mt-space-sm mb-space-lg rounded-xl bg-primary-fixed/40 border-l-4 border-primary px-space-md py-space-md flex flex-col gap-1.5"><span class="flex items-center gap-1 font-label-regular text-label-regular text-primary font-bold"><span class="material-symbols-outlined text-[18px]">lightbulb</span>기억할 것</span>'
                     + "".join(f'<p class="flex items-start gap-1.5 font-body-compact text-body-compact text-on-surface"><span class="material-symbols-outlined text-primary text-[16px] mt-0.5">check_circle</span><span>{self.marked(x)}</span></p>' for x in a["points"])
                     + f'</section><a class="inline-flex items-center gap-1 font-label-regular text-label-regular text-primary font-semibold hover:underline" href="{e(more_url)}" target="_blank" rel="noopener">더 알아보기: {e(more_label)}<span class="material-symbols-outlined text-[14px]">open_in_new</span></a>'
                     + self.related(slug) + credit
                     + '<div class="mt-space-lg flex justify-end">' + self.regram_form(uid, "learn", slug, "") + "</div>" + end)  # fmt: skip
            return "200 OK", [], page(a["title"], "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)
        groups = "".join(
            f'<section class="mt-space-xl pt-space-md border-t border-surface-container-high"><div class="flex items-center justify-between mb-space-sm"><h2 class="font-headline-md text-headline-md text-primary border-l-4 border-primary pl-2 leading-none">{e(c)}</h2></div>'
            f'<div class="flex flex-col divide-y divide-surface-container-high/80">'
            + "".join(f'<a href="/learn/{e(x["slug"])}" class="py-3.5 flex items-start justify-between gap-space-sm"><div class="flex flex-col gap-0.5"><span class="font-body-reading-strong text-body-reading-strong text-on-surface">{e(x["title"])}</span>'
                      f'<span class="font-body-compact text-body-compact text-on-surface-variant">{e(x["lead"].replace("**", ""))}</span></div><span class="material-symbols-outlined text-primary text-[18px] mt-1">chevron_right</span></a>'
                      for x in learn.ARTICLES if x["cat"] == c) + "</div></section>" for c in learn.CATS)  # fmt: skip
        inner = (wrap + '<header class="pt-5"><h1 class="font-headline-lg text-headline-lg text-on-surface tracking-tight">읽기 팁</h1>'
                 '<p class="font-body-compact text-body-compact text-on-surface-variant mt-1">주식을 처음 시작할 때 알아 두면 좋은 기초를 쉬운 말로 풀었어요.</p></header>' + self.cached("learn", lambda: groups + self.guru_list() + self.big_list()) + end)  # fmt: skip
        return "200 OK", [], page("읽기 팁", "bg-surface font-body-reading text-on-surface flex flex-col min-h-screen", inner)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # 윈도우 콘솔(cp949)이 「—」를 못 찍어 뒤에서 도는 첫 노트 쓰기가 멈췄다 (10/10)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    import threading
    from socketserver import ThreadingMixIn
    import wsgiref.simple_server
    from wsgiref.simple_server import WSGIServer, make_server

    wsgiref.simple_server.ServerHandler.server_software = "hanjang"  # 서버 종류·파이썬 판 번호를 응답 머리에 드러내지 않는다

    class Server(ThreadingMixIn, WSGIServer):
        """연결마다 스레드 — 브라우저가 미리 열어 둔 빈 연결 하나에 서버 전체가 멈추지 않게.
        요청 처리는 App 안의 잠금 하나로 차례대로(App.turn) — 메일·AI 를 기다리는 동안만 놓는다."""

        daemon_threads = True
        request_queue_size = 128  # 한꺼번에 몰린 연결을 받아 둘 줄 (기본 5 — 넘치면 연결을 끊는다)

    sys.stderr.reconfigure(encoding="utf-8")  # 윈도우 콘솔(cp949)에서 한글 로그가 깨지지 않게
    cfg = env()
    if len(cfg.get("SECRET", "")) < 32:  # 짧거나 없는 키로는 로그인 링크·쿠키를 위조당한다 — 켜지 않는다
        sys.exit("SECRET 이 없거나 짧아요(32자 이상). 만들기: python -c \"import secrets; print(secrets.token_hex(32))\"")
    db.connect().close()
    app = App(db.tune(sqlite3.connect(db.PATH, timeout=30, check_same_thread=False)), cfg["SECRET"])
    host, port = cfg.get("HOST", "127.0.0.1"), int(os.environ.get("PORT") or cfg.get("PORT", "8000"))  # 서버에선 127.0.0.1 그대로 두고 앞의 Caddy 가 https 를 맡는다
    print(f"한장 — http://{host}:{port}", file=sys.stderr)
    make_server(host, port, app, server_class=Server).serve_forever()
