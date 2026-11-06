"""내 나무 — 들어온 날이 쌓일수록 자라는 나무 + 이번 달 잔디 (프로필, 사용자 10/11).

씨앗 → 새싹 → 어린 나무 → 자라는 나무 → 잎이 풍성한 나무 → 꽃이 핀 나무 → 분홍빛이 드는 나무(150일이면 다 자란다). 안 들어와도 시들지 않는다(벌 없음).
자라는 기준은 「들어온 날」뿐 — 주가·수익과 잇지 않는다. 그림은 코드가 그린 SVG(같은 날수면 늘 같은 나무).

    uv run python -m hanjang.tree   # 시안 보기 → data/tree-sample.html (자라는 단계)
"""

import math
import time
import random
from datetime import date, timedelta
from html import escape as e

STAGES = ((0, "씨앗"), (1, "새싹"), (4, "어린 나무"), (15, "자라는 나무"), (40, "잎이 풍성한 나무"), (90, "꽃이 핀 나무"), (150, "분홍빛이 드는 나무"))
LEVEL = ("#ebebeb", "#bceddc", "#86c5a4", "#3f7d5c", "#154539")  # 잔디 — 안 온 날 → 많이 본 날


def stage(n: int) -> tuple[str, int | None]:
    """(지금 단계 이름, 다음 단계까지 남은 날 — 마지막 단계면 None)."""
    name = [s for k, s in STAGES if n >= k][-1]
    nxt = next((k - n for k, _ in STAGES if k > n), None)
    return name, nxt


GREENS = ("#44705a", "#5a8a66", "#78a57a", "#a9cb92", "#cde2b4")  # 그늘진 잎 → 햇빛 받은 잎
BARK = "#7d5a3f"
PINKS = ("#dc94a8", "#e6a8b8", "#eebbc8", "#f5cfd8", "#fae1e7")  # 110일 뒤 잎이 하나씩 물드는 분홍 — 초록과 같은 다섯 단계


# 수관 — 큰 덩이 하나에 작은 잎 덩이 여덟이 둘레로 겹친 모양(가운데 x·y, 반지름). 테두리가 뭉게뭉게해 공이 아니라 나무처럼 보이고,
# 아랫단이 가장 넓다. 왼쪽·오른쪽은 거의 같되 똑같지는 않게
PUFFS = ((0, 0, 0.8), (0, -0.62, 0.4), (-0.5, -0.4, 0.42), (0.52, -0.38, 0.43), (-0.88, 0.1, 0.36), (0.86, 0.12, 0.38), (-0.56, 0.42, 0.38), (0.54, 0.44, 0.37), (0, 0.42, 0.4))


def _spots() -> tuple[list, list]:
    """잎 뭉치 190곳·꽃 20송이의 정해진 자리 — 날이 쌓이면 앞에서부터 차례로 달린다. (자리 x·y, 초록 단계, 돌린 각, 크기, 잎 수)
    새 자리는 후보 열둘 가운데 이미 난 잎에서 가장 먼 곳 — 몇 장이 달렸든 수관이 고르게 찬다(한쪽이 비지 않게, 사용자 10/13)."""
    rng = random.Random(7)
    leaves = []
    for _ in range(190):
        best, far = None, -1.0
        for _ in range(12):
            px, py, pr = rng.choices(PUFFS, [q[2] ** 2 for q in PUFFS])[0]
            a, r = rng.uniform(0, math.tau), math.sqrt(rng.random()) * pr
            x, y = px + math.cos(a) * r, py + math.sin(a) * r
            d = min(((x - p[0]) ** 2 + (y - p[1]) ** 2 for p in leaves), default=9.0)
            if d > far:
                best, far = (x, y), d
        leaves.append((*best, rng.choices(range(5), (4, 5, 4, 4, 3))[0], rng.randrange(360), rng.uniform(0.85, 1.2), rng.choice((3, 3, 4))))
    flowers = []
    for _ in range(20):
        px, py, pr = rng.choices(PUFFS, [q[2] ** 2 for q in PUFFS])[0]
        a, r = rng.uniform(0, math.tau), math.sqrt(rng.random()) * pr * 0.85
        flowers.append((px + math.cos(a) * r, py + math.sin(a) * r))
    return leaves, flowers


LEAVES, FLOWERS = _spots()


def _clover(k: int) -> str:
    """하트 모양 둥근 잎 k 장이 한 점에서 벌어진 잎 뭉치. 크기 1 짜리 path."""
    d = ""
    for i in range(k):
        c, v = math.cos(math.tau * i / k), math.sin(math.tau * i / k)
        q = [f"{x * c - y * v:.2f} {x * v + y * c:.2f}" for x, y in ((-0.9, -0.5), (-0.6, -1.3), (0, -0.95), (0.6, -1.3), (0.9, -0.5))]
        d += f"M0 0C{q[0]} {q[1]} {q[2]}C{q[3]} {q[4]} 0 0Z"
    return d


CLOVER = {3: _clover(3), 4: _clover(4)}


def _limbs(x: float, y: float, ang: float, length: float, d: int, w: float, key: str, tips: list) -> str:
    """둘로 갈라지며 뻗는 가지 — 갈라질수록 가늘고 짧다. 휘는 정도는 가지 자리(key)마다 정해져 있어, 나무가 자라도 먼저 난 가지 모양은 그대로다. 가지 끝 자리는 tips 에 담는다(거기 잎이 달린다)."""
    rng = random.Random(key)
    x2, y2 = x + math.cos(ang) * length, y + math.sin(ang) * length
    bend = rng.uniform(-0.08, 0.08)
    mx, my = (x + x2) / 2 + math.cos(ang + 1.57) * length * bend, (y + y2) / 2 + math.sin(ang + 1.57) * length * bend
    out = f'<path d="M{x:.1f} {y:.1f}Q{mx:.1f} {my:.1f} {x2:.1f} {y2:.1f}" stroke-width="{max(1.2, w):.1f}"/>'
    if d:
        sp = 0.5 + rng.uniform(-0.03, 0.05)
        out += _limbs(x2, y2, ang - sp, length * 0.74, d - 1, w * 0.66, key + "l", tips) + _limbs(x2, y2, ang + sp, length * 0.74, d - 1, w * 0.66, key + "r", tips)
    else:
        tips.append((x2, y2))
    return out


def svg(n: int) -> str:
    """들어온 날 n → 나무 그림 한 장(같은 n 이면 늘 같은 그림). 잎 뭉치가 하루에 두 곳쯤 늘어 110일이면 다 찬다. 90일부터 분홍 꽃, 110일 뒤로는 꽃이 늘고 잎도 몇 장씩 분홍으로 물들어 150일에 다 자란 모습이 된다(열매·새는 뺐다, 사용자 10/13)."""
    name, _ = stage(n)
    gx, gy = 160, 270
    out = [f'<ellipse cx="{gx}" cy="{gy + 6}" rx="120" ry="10" fill="#dfe9cf" opacity="0.7"/>']
    # 발밑 — 잔디가 나무 둘레에서부터 번져 한 달쯤이면 땅을 다 덮는다. 그 위에 작은 꽃(보름쯤부터)
    cover = min(1.0, (n + 3) / 30) if n else 0
    if cover:
        rx = 40 + 80 * cover
        out.append(f'<ellipse cx="{gx}" cy="{gy + 6}" rx="{rx:.0f}" ry="{6 + 4 * cover:.1f}" fill="#b5d49a"/>')
        rng, blades = random.Random(3), []
        for _ in range(int(170 * cover)):
            ux = rng.uniform(-1, 1)
            x, y = gx + ux * rx, gy + 6 + (6 + 4 * cover) * math.sqrt(1 - ux * ux) * rng.uniform(-0.9, 1)
            lean, tall = rng.uniform(-3, 3), rng.uniform(5, 10)
            blades.append((y, f'<path d="M{x:.1f} {y:.1f} q{lean / 2:.1f} -{tall / 2:.1f} {lean:.1f} -{tall:.1f}" stroke="{rng.choice(("#6fa172", "#8fbb7c", "#a3cc8c", "#7fae7a"))}"/>'))
        out.append('<g fill="none" stroke-width="1.5" stroke-linecap="round">' + "".join(b for _, b in sorted(blades)) + "</g>")
    if n == 0:  # 흙 둔덕은 씨앗일 때만 — 싹이 난 뒤엔 잔디 위에 바로 선다
        out.append(f'<ellipse cx="{gx}" cy="{gy + 2}" rx="34" ry="7" fill="#8a6a48"/>')
    for i, x in enumerate((92, 232, 60, 262, 120, 204)[: min(6, n // 15)]):
        y, c = 262 + (i % 2) * 2, ("#f4c6cf", "#f6dc8a", "#ffffff")[i % 3]
        out.append(f'<path d="M{x} {y + 12} q-1 -6 0 -11" stroke="{GREENS[2]}" stroke-width="1.4" fill="none" stroke-linecap="round"/>'
                   + "".join(f'<circle cx="{x + math.cos(p * math.tau / 5) * 2.8:.1f}" cy="{y + math.sin(p * math.tau / 5) * 2.8:.1f}" r="2.3" fill="{c}" stroke="#e3d6c2" stroke-width="0.3"/>' for p in range(5))
                   + f'<circle cx="{x}" cy="{y}" r="1.6" fill="#e0a23a"/>')  # fmt: skip
    if n == 0:
        out.append(f'<ellipse cx="{gx}" cy="{gy - 3}" rx="6" ry="4" fill="#6b4a2f"/>')
    else:
        h, tw = min(150, 14 + n * 1.5), min(15, 2 + n * 0.13)
        ty = gy - h
        rx, ry = min(132, 8 + n * 1.22), min(90, 7 + n * 0.83)  # 옆으로 넓은 수관
        cy = ty - ry * 0.3
        fy = min(gy - h * 0.3, cy + ry * 1.12)  # 줄기가 가지로 갈라지는 높이 — 수관 바로 밑이라 갈라진 가지가 보인다
        out.append(f'<path d="M{gx - tw * 0.8:.1f} {gy} Q{gx - tw * 0.36:.1f} {gy - 10} {gx - tw * 0.33:.1f} {gy - h * 0.3:.1f} L{gx - tw * 0.22:.1f} {fy:.1f} L{gx + tw * 0.22:.1f} {fy:.1f} '
                   f'L{gx + tw * 0.33:.1f} {gy - h * 0.3:.1f} Q{gx + tw * 0.36:.1f} {gy - 10} {gx + tw * 0.8:.1f} {gy} Z" fill="{BARK}"/>')  # fmt: skip
        depth = 0 if n < 4 else 1 if n < 10 else 2 if n < 20 else 3 if n < 40 else 4  # 가지는 자라면서 한 번씩 더 갈라진다
        tips: list = []
        fan = ((0, 1.05), (-0.41, 1.0), (0.41, 1.0), (-0.8, 0.68), (0.8, 0.68))[: 1 if n < 4 else 3 if n < 25 else 5]  # 굵은 가지가 부채꼴로 (벌어진 각, 길이)
        limbs = "".join(_limbs(gx + a * tw * 0.2, fy + 2, -math.pi / 2 + a, ry * 0.6 * ln, max(0, depth - 1), tw * (0.42 - abs(a) * 0.1), f"t{i}", tips) for i, (a, ln) in enumerate(fan))
        out.append(f'<g fill="none" stroke="{BARK}" stroke-linecap="round">{limbs}</g>')
        ls = min(8.6, 4.6 + n * 0.04)
        for i, (x, y) in enumerate(tips):  # 가지 끝마다 잎 — 잎 없이 삐져나온 가지가 없게
            out.append(f'<path d="{CLOVER[3 + i % 2]}" fill="{GREENS[i % 3]}" transform="translate({x:.1f} {y:.1f}) rotate({i * 47 % 360}) scale({ls:.1f})"/>')
        pink = min(0.2, max(0, n - 110) / 200)  # 110일 뒤 — 잎이 하나씩 분홍으로 물든다. 150일에 다섯에 하나, 거기서 멈춘다(더 분홍이면 과하다, 사용자 10/13)
        for i, (ux, uy, shade, rot, sc, k) in sorted(enumerate(LEAVES[: min(len(LEAVES), 2 + int(n * 1.75))]), key=lambda v: v[1][2]):  # 그늘진 잎부터 그려 밝은 잎이 위에 온다
            out.append(f'<path d="{CLOVER[k]}" fill="{(PINKS if i * 37 % len(LEAVES) < pink * len(LEAVES) else GREENS)[shade]}" transform="translate({gx + ux * rx:.1f} {cy + uy * ry:.1f}) rotate({rot}) scale({ls * sc:.1f})"/>')
        for i, (ux, uy, rot) in enumerate(((-1.2, -0.2, 40), (1.18, -0.55, -30), (1.2, 0.4, 110), (-1.1, 0.7, 150), (0.1, -1.14, 10))[: max(0, (n - 25) // 15)]):  # 바람에 날리는 잎 몇 장
            out.append(f'<path d="M0 0Q4.5 -5.5 0 -12Q-4.5 -5.5 0 0Z" fill="{GREENS[2 + i % 3]}" transform="translate({gx + ux * rx:.1f} {cy + uy * ry:.1f}) rotate({rot})"/>')
        if n >= 90:  # 꽃 — 분홍 꽃잎 다섯 장에 노란 가운데
            for ux, uy in FLOWERS[: min(14, int((n - 90) / 1.5) + 2) + min(6, max(0, n - 110) // 6)]:  # 110일까지 14송이, 그 뒤 엿새에 한 송이씩 150일의 20송이까지
                x, y = gx + ux * rx, cy + uy * ry
                out.append("".join(f'<circle cx="{x + math.cos(p * math.tau / 5) * 3.2:.1f}" cy="{y + math.sin(p * math.tau / 5) * 3.2:.1f}" r="2.6" fill="#f4c6cf" stroke="#e39fb1" stroke-width="0.4"/>' for p in range(5))
                           + f'<circle cx="{x:.1f}" cy="{y:.1f}" r="1.8" fill="#e0a23a"/>')  # fmt: skip
    return f'<svg viewBox="-12 -30 344 324" width="100%" role="img" aria-label="내 나무 — {e(name)}" xmlns="http://www.w3.org/2000/svg">{"".join(out)}</svg>'


WEEKS = 13  # 잔디 — 최근 석 달쯤. 한 달은 초순에 두 줄뿐이라 허전하고, 여섯 달(26주)은 휴대폰 너비를 넘는다 (10/11)


def grass(counts: dict[str, int], today: date) -> tuple[str, int]:
    """최근 13주 잔디(깃허브 모양) — 요일이 왼쪽에 세로로(일~토), 한 주가 세로 한 줄, 위에 달 이름. 이번 주는 오늘까지만 그린다.
    그날 본 화면 수에 따라 네 단계 초록. (그림, 그 기간에 들어온 날 수)"""
    start = today - timedelta(days=(today.weekday() + 1) % 7 + 7 * (WEEKS - 1))  # 13주 전 일요일
    cells = '<span></span>' + "".join(f'<span style="font-size:11px;line-height:18px;color:#68706c;padding-right:4px">{d if d in "월수금" else ""}</span>' for d in "일월화수목금토")
    came, d = 0, start
    while d <= today:
        if d.weekday() == 6:  # 줄 맨 위 — 이 주에 1일이 들어 있으면 달 이름
            week = [d + timedelta(days=i) for i in range(7)]
            first = next((x for x in week if x.day == 1), None)
            cells += f'<span style="font-size:11px;line-height:14px;color:#68706c;white-space:nowrap;width:18px;overflow:visible">{f"{first.month}월" if first else ""}</span>'
        c = counts.get(d.isoformat(), 0)
        came += c > 0
        lv = 0 if c == 0 else 1 if c <= 2 else 2 if c <= 5 else 3 if c <= 10 else 4
        look = f"background:{LEVEL[lv]}" + (";outline:2px solid #154539;outline-offset:1px" if d == today else "")
        cells += f'<span title="{d.month}월 {d.day}일" style="width:18px;height:18px;border-radius:4px;{look}"></span>'
        d += timedelta(days=1)
    legend = "".join(f'<span style="width:11px;height:11px;border-radius:3px;background:{c};display:inline-block"></span>' for c in LEVEL)
    return (f'<div style="display:grid;grid-auto-flow:column;grid-template-rows:14px repeat(7,18px);grid-auto-columns:max-content;gap:4px;width:max-content;max-width:100%;margin:0 auto">{cells}</div>'
            f'<p style="margin:8px 0 0;display:flex;align-items:center;justify-content:center;gap:4px;font-size:11px;color:#68706c">적게 {legend} 많이</p>'), came  # fmt: skip


def line(mood: str = "calm", width: int = 210) -> str:
    """가는 선으로 그린 나무 한 그루 — 사용자가 고른 그림과 그 버전들(10/14 · 만들기: deploy/tree_icon.py, deploy/tree_moods.py).
    mood: "wait"(바람 — 살랑 흔들린다) · "oops"(잎이 떨어진다 — 오류) · "rain"(비 — 끊김) · "sun"·"moon"(낮·밤) · 그 밖에는 나무만.
    width: 나무의 너비. 버전 그림은 달·해·날리는 잎 자리만큼 캔버스가 넓어서(860 가운데 나무 665) 그만큼 넓게 놓는다 — 어느 버전이든 나무 크기가 같다."""
    kind = MOODS.get(mood)
    src, w, h = (f"tree-{kind}.webp", width * 860 // 665, width * 600 // 665) if kind else ("tree.png", width, width * 559 // 665)
    sway = "transform-origin:50% 100%;animation:hj-sway 3s ease-in-out infinite" if mood == "wait" else ""
    return (('<style>@keyframes hj-sway{0%,100%{transform:rotate(-1.6deg)}50%{transform:rotate(1.6deg)}}</style>' if sway else "")
            + f'<img src="/static/{src}?v=1" width="{w}" height="{h}" alt="나무" style="max-width:100%;height:auto;{sway}">')


def perch(mood: str = "calm", width: int = 92) -> str:
    """두 줄 띠(실선+점선) 바로 위에 세우는 나무 — 띠가 땅이 된다.
    flex 줄(align-items:flex-end)의 오른쪽 끝에 넣고, 그 줄 바로 아래에 띠가 오게 한다. 그림 아래 여백만큼 살짝 내려 띠에 닿게."""
    return f'<span style="flex:none;display:flex;margin-bottom:-{2 if mood in MOODS else 1}px">{line(mood, width)}</span>'


MOODS = {"wait": "wind", "oops": "fall", "rain": "rain", "sun": "sun", "moon": "moon"}


def sky() -> str:
    """지금 한국 시각이 낮이면 "sun", 밤이면 "moon" — 홈 맨 아래 나무."""
    return "sun" if 6 <= (time.gmtime().tm_hour + 9) % 24 < 18 else "moon"
