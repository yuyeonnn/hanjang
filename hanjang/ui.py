"""화면 조각 — 공통 틀(page)·상단·하단 탭·칩·사진·카드 줄과 화면 상수. 모든 화면이 가져다 쓴다."""

import hashlib
import html
import json
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from hanjang import gurus, mail, notes, sources
from hanjang.pwa import PWA_TAGS
from hanjang.sources import industry_label


def FIRST(ticker: str) -> bool:  # 새 종목 바로 받기 — 테스트에서 바꿔 끼운다
    if not ticker[:1].isdigit() and not ticker.startswith("ETF"):  # 미국 티커(영문) — SEC 에서
        from hanjang import us
        return us.first(ticker)
    from hanjang import collect

    return collect.first(ticker)

MAX_STOCKS = 20  # PRD F2
COHORT = re.compile(r"[a-z0-9-]{1,20}")  # 시험 묶음 이름 — 초대 링크 /?c=trial-1 (python -m hanjang.trial 이 센다)
NICK = re.compile(r"[가-힣A-Za-z0-9_]{2,20}")  # 남에게 보이는 이름 — 이메일은 절대 보이지 않는다
BIO_MAX = 150
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
# 이 사이트의 스크립트·글꼴·그림만 — 남의 스크립트가 끼어들거나 폼이 밖으로 나가지 못하게. 화면에 인라인 스크립트가 많아 'unsafe-inline' 은 둔다
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data: blob: https://cdn.brandfetch.io; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'")
e = html.escape


# --- 시안 공통 머리 (Stitch 시안의 <head> 그대로) ---

HEAD = """<meta charset="utf-8"><meta content="width=device-width, initial-scale=1.0, viewport-fit=cover" name="viewport"><link href="https://fonts.googleapis.com" rel="preconnect"><link crossorigin="" href="https://fonts.gstatic.com" rel="preconnect"><link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&amp;family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,600;1,6..72,400&amp;display=swap" rel="preload" as="style" onload="this.onload=null;this.rel='stylesheet'"><noscript><link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&amp;family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,600;1,6..72,400&amp;display=swap" rel="stylesheet"></noscript>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@400,0..1&amp;display=block" rel="stylesheet"><style>@layer base{html,body{width:100vw;margin:0;padding:0;}body{overscroll-behavior:none;}.pb-safe{padding-bottom:env(safe-area-inset-bottom,0px);}.pt-safe{padding-top:env(safe-area-inset-top,0px);}main>:first-child{margin-top:0!important;}main>:last-child{margin-bottom:0!important;}}::-webkit-scrollbar{display:none;}body{word-break:keep-all;overflow-wrap:anywhere;}p,h1,h2,h3,li,span{text-wrap:pretty;}</style>"""


# 카카오톡·문자로 링크를 보낼 때 뜨는 미리보기 카드 — 어느 쪽을 보내도 같은 소개 (로그인 같은 화면 이름은 빼고)
SHARE_TITLE = "한장 — 한눈에 읽는 장"  # 이행시: 한눈에 읽는 / 장(場) — 종이 한 장이면서 주식 시장 (사용자 10/12)
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


SEEN = "<script>try{navigator.sendBeacon('/t?k=js')}catch(e){}</script>"  # 인사이트 — 스크립트가 실제로 돈 브라우저(사람)만 「들어온 사람」으로 센다


def page(title: str, body_attr: str, inner: str) -> str:
    return (f'<!DOCTYPE html><html lang="ko"><head>{HEAD}{CSS_TAG}{share_tags()}{PWA_TAGS}<title>{e(title)} · 한장</title></head>'
            f'<body class="{body_attr}">{inner}{STAY}{HL}{SEEN}</body></html>')  # fmt: skip


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
    key = sources.env().get("BRANDFETCH_CLIENT_ID", "")
    if not (key and homepage):
        return letter
    src = f"https://cdn.brandfetch.io/{quote(homepage)}/w/96/h/96/fallback/404?c={quote(key)}"
    return (f'<span class="{size} shrink-0 rounded-full overflow-hidden bg-surface-container-lowest border border-outline-variant/40 flex items-center justify-center">'
            f'<img alt="{e(name)} 로고" class="w-full h-full object-contain" loading="lazy" src="{e(src)}" '
            f'onerror="this.parentNode.outerHTML={e(json.dumps(letter))}"></span>')  # fmt: skip


DART_VIEW = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"


# 큰 업종 — 통계청 산업분류 코드 앞 두 자리로 묶는다 (도넛 조각을 열 개 안쪽으로)
SECTOR = [((10, 12), "식품·생활"), ((13, 19), "식품·생활"), ((20, 20), "화학·소재"), ((21, 21), "제약·바이오"),
          ((22, 23), "화학·소재"), ((24, 25), "철강·금속"), ((26, 27), "전자·반도체"), ((28, 29), "기계·전기"),
          ((30, 31), "자동차·운송장비"), ((32, 34), "식품·생활"), ((35, 36), "에너지"), ((41, 42), "건설"),
          ((45, 47), "유통"), ((49, 52), "운송·물류"), ((55, 56), "식품·생활"), ((58, 63), "IT·통신"),
          ((64, 66), "금융"), ((70, 70), "제약·바이오"), ((71, 71), "지주회사"), ((72, 73), "IT·통신")]  # fmt: skip


def sector(code: str | None) -> str | None:
    d = int(code[:2]) if code and code[:2].isdigit() else None
    return next((name for (lo, hi), name in SECTOR if d is not None and lo <= d <= hi), None)


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
