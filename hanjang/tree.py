"""내 나무 — 들어온 날이 쌓일수록 자라는 나무 + 이번 달 잔디 (프로필, 사용자 10/11).

씨앗 → 새싹 → 어린 나무 → 자라는 나무 → 잎이 풍성한 나무 → 꽃이 핀 나무. 안 들어와도 시들지 않는다(벌 없음).
자라는 기준은 「들어온 날」뿐 — 주가·수익과 잇지 않는다. 그림은 코드가 그린 SVG(같은 날수면 늘 같은 나무).

    uv run python -m hanjang.tree   # 시안 보기 → data/tree-sample.html (세 모양 × 자라는 단계)
"""

import calendar
import math
import random
from datetime import date
from html import escape as e

STAGES = ((0, "씨앗"), (1, "새싹"), (4, "어린 나무"), (15, "자라는 나무"), (40, "잎이 풍성한 나무"), (90, "꽃이 핀 나무"))
GREENS = ("#2e6e4e", "#3f8f63", "#63b07d", "#9fd6a8", "#d3efd2")  # 그늘 → 빛
TRUNK, TRUNK_DARK, PINK, PINK_DARK, GOLD = "#8a6a48", "#6f5338", "#f6c9d3", "#e79fb0", "#e0a23a"
LEVEL = ("#eae7ea", "#bceddc", "#86c5a4", "#3f7d5c", "#154539")  # 잔디 — 안 온 날 → 많이 본 날


def stage(n: int) -> tuple[str, int | None]:
    """(지금 단계 이름, 다음 단계까지 남은 날 — 마지막 단계면 None)."""
    name = [s for k, s in STAGES if n >= k][-1]
    nxt = next((k - n for k, _ in STAGES if k > n), None)
    return name, nxt


def _ground(style: str) -> str:
    grass = "".join(f'<path d="M{x} 232 q-2 -7 -5 -9 M{x} 232 q0 -9 1 -12 M{x} 232 q3 -6 6 -8" stroke="{GREENS[2]}" stroke-width="1.6" fill="none" stroke-linecap="round"/>'
                    for x in (58, 96, 232, 266))  # fmt: skip
    return (f'<ellipse cx="160" cy="236" rx="128" ry="13" fill="#e3efe5"/><ellipse cx="160" cy="233" rx="46" ry="7" fill="#d5c3a5"/>{grass}')


def _sprout(n: int) -> str:
    if n == 0:  # 씨앗 — 흙 위에 살짝
        return f'<ellipse cx="160" cy="229" rx="7" ry="5" fill="{TRUNK_DARK}"/><path d="M157 226 q3 -3 6 0" stroke="#b99a6b" stroke-width="1.2" fill="none"/>'
    h = 14 + n * 7
    leaf = "M0 0 C{a} -3 {b} -13 0 -20 C-{b} -13 -{a} -3 0 0 Z".format(a=7 + n, b=8 + n)
    return (f'<path d="M160 232 q-3 -{h // 2} 0 -{h}" stroke="{GREENS[2]}" stroke-width="3" fill="none" stroke-linecap="round"/>'
            f'<g transform="translate(160 {232 - h}) rotate(-48)"><path d="{leaf}" fill="{GREENS[2]}"/><path d="M0 -2 L0 -17" stroke="{GREENS[1]}" stroke-width="1"/></g>'
            f'<g transform="translate(160 {232 - h}) rotate(42)"><path d="{leaf}" fill="{GREENS[3]}"/><path d="M0 -2 L0 -17" stroke="{GREENS[2]}" stroke-width="1"/></g>')  # fmt: skip


def _flower(x: float, y: float, r: float = 3.4) -> str:
    petals = "".join(f'<circle cx="{x + math.cos(a) * r:.1f}" cy="{y + math.sin(a) * r:.1f}" r="{r * 0.85:.1f}" fill="{PINK}"/>' for a in (i * math.tau / 5 - 1.57 for i in range(5)))
    return f'{petals}<circle cx="{x:.1f}" cy="{y:.1f}" r="{r * 0.55:.1f}" fill="{GOLD}"/>'


def _fluffy(n: int, outline: bool) -> str:
    """동글동글한 수관 — 어두운 덩어리 위에 밝은 덩어리를 왼쪽 위로 조금씩 밀어 겹쳐 빛을 받은 느낌. outline=True 면 스티커처럼 진한 테두리."""
    rng = random.Random(7)
    s = min(1.0, n / 90) ** 0.6
    h, w = 22 + 82 * s, 5 + 12 * s
    rx, ry = 16 + 86 * s, 14 + 60 * s
    top = 232 - h
    cx, cy = 160, top - ry * 0.55
    trunk = (f'<path d="M{160 - w / 2:.1f} 232 C{160 - w / 3:.1f} {232 - h / 2:.1f} {160 - w / 4:.1f} {top + 10:.1f} {160 - w / 5:.1f} {top - 4:.1f} L{160 + w / 5:.1f} {top - 4:.1f} '
             f'C{160 + w / 4:.1f} {top + 10:.1f} {160 + w / 3:.1f} {232 - h / 2:.1f} {160 + w / 2 + 2:.1f} 232 Z" fill="{TRUNK}"/>'
             f'<path d="M{160 + w / 8:.1f} 230 C{160 + w / 6:.1f} {232 - h / 2:.1f} {160 + w / 8:.1f} {top + 12:.1f} {160 + w / 10:.1f} {top:.1f}" stroke="{TRUNK_DARK}" stroke-width="{max(1, w / 5):.1f}" fill="none" stroke-linecap="round" opacity="0.7"/>')  # fmt: skip
    if n >= 15:  # 가지 — 수관 속으로 사라진다
        for dx, dy in ((-0.5, 0.25), (0.52, 0.2)):
            trunk += (f'<path d="M160 {top + h * 0.3:.1f} Q{160 + dx * rx * 0.5:.1f} {cy + dy * ry + 22:.1f} {160 + dx * rx:.1f} {cy + dy * ry:.1f}" '
                      f'stroke="{TRUNK}" stroke-width="{max(2, w * 0.3):.1f}" fill="none" stroke-linecap="round"/>')  # fmt: skip
    k = 6 + int(9 * s)
    ring = [(cx + math.cos(a) * rx * 0.72, cy + math.sin(a) * ry * 0.72, rx * (0.34 + rng.random() * 0.1)) for a in (i * math.tau / k + rng.random() * 0.25 for i in range(k))]
    ring.append((cx, cy, rx * 0.6))
    blobs = ""
    if outline:
        blobs += "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r + 3:.1f}" fill="#1f4a3d"/>' for x, y, r in ring)
    for i, (dx, dy, scale, col) in enumerate(((0, 0, 1.0, GREENS[0]), (-0.05, -0.07, 0.86, GREENS[1]), (-0.11, -0.15, 0.68, GREENS[2]))):
        blobs += "".join(f'<circle cx="{x + dx * rx:.1f}" cy="{y + dy * ry:.1f}" r="{r * scale:.1f}" fill="{col}"/>' for x, y, r in ring)
    # 빛 받은 작은 덩어리 — 왼쪽 위에 몇 개
    for _ in range(3 + int(5 * s)):
        a, d = rng.uniform(2.6, 4.6), rng.uniform(0.25, 0.75)
        blobs += f'<circle cx="{cx + math.cos(a) * rx * d - rx * 0.1:.1f}" cy="{cy + math.sin(a) * ry * d - ry * 0.12:.1f}" r="{rx * rng.uniform(0.08, 0.14):.1f}" fill="{GREENS[3]}" opacity="0.9"/>'
    extra = ""
    if n >= 90:  # 꽃
        for _ in range(min(14, 4 + (n - 90) // 4)):
            a, d = rng.uniform(0, math.tau), math.sqrt(rng.random()) * 0.82
            extra += _flower(cx + math.cos(a) * rx * d, cy + math.sin(a) * ry * d, 3.2 + s)
    if n >= 30:  # 발밑 작은 꽃
        extra += _flower(84, 228, 2.6) + _flower(244, 229, 2.4)
    return trunk + blobs + extra


def _botanical(n: int) -> str:
    """가지가 갈라지고 끝마다 잎사귀 — 식물 도감 그림처럼. 자랄수록 가지가 한 번씩 더 갈라진다."""
    rng = random.Random(11)
    s = min(1.0, n / 90) ** 0.6
    depth = 2 + int(3.99 * s)
    leaf = "M0 0 C5 -3 6 -11 0 -17 C-6 -11 -5 -3 0 0 Z"
    out, leaves, tips = [], [], []

    def grow(x, y, ang, length, width, d):
        x2, y2 = x + math.cos(ang) * length, y + math.sin(ang) * length
        mx, my = (x + x2) / 2 + math.cos(ang + 1.57) * length * 0.12, (y + y2) / 2 + math.sin(ang + 1.57) * length * 0.12
        out.append(f'<path d="M{x:.1f} {y:.1f} Q{mx:.1f} {my:.1f} {x2:.1f} {y2:.1f}" stroke="{TRUNK if d > 1 else TRUNK_DARK}" stroke-width="{width:.1f}" fill="none" stroke-linecap="round"/>')
        if d == 0:
            tips.append((x2, y2))
            for _ in range(3 + int(3 * s)):
                lx, ly = x2 + rng.uniform(-9, 9), y2 + rng.uniform(-9, 7)
                leaves.append(f'<g transform="translate({lx:.1f} {ly:.1f}) rotate({rng.randint(-150, 150)}) scale({rng.uniform(0.75, 1.15) * (0.75 + 0.45 * s):.2f})">'
                              f'<path d="{leaf}" fill="{rng.choice(GREENS[1:4])}"/><path d="M0 -2 L0 -14" stroke="{GREENS[0]}" stroke-width="0.7" opacity="0.6"/></g>')  # fmt: skip
            return
        spread = 0.42 + rng.uniform(-0.06, 0.1)
        grow(x2, y2, ang - spread, length * 0.74, width * 0.66, d - 1)
        grow(x2, y2, ang + spread * rng.uniform(0.8, 1.1), length * 0.72, width * 0.66, d - 1)
        if d >= 3 and rng.random() < 0.6:
            grow(x2, y2, ang + rng.uniform(-0.12, 0.12), length * 0.6, width * 0.55, d - 2)

    grow(160, 232, -1.57, 26 + 44 * s, 4 + 9 * s, depth)
    extra = "".join(_flower(x + rng.uniform(-6, 6), y + rng.uniform(-8, 2), 3) for x, y in tips[: min(len(tips), 3 + (n - 90) // 4)]) if n >= 90 else ""
    return "".join(out) + "".join(leaves) + extra + (_flower(84, 228, 2.6) + _flower(244, 229, 2.4) if n >= 30 else "")


STYLES = {"fluffy": "동글동글", "sticker": "테두리 스티커", "botanical": "잎사귀"}


def svg(n: int, style: str = "fluffy") -> str:
    """들어온 날 n → 나무 그림 한 장. 같은 n 이면 늘 같은 그림."""
    name, _ = stage(n)
    body = _sprout(n) if n < 4 else _botanical(n) if style == "botanical" else _fluffy(n, style == "sticker")
    return (f'<svg viewBox="0 0 320 250" width="100%" role="img" aria-label="내 나무 — {e(name)}" xmlns="http://www.w3.org/2000/svg">{_ground(style)}{body}</svg>')


def month(counts: dict[str, int], today: date) -> str:
    """이번 달 잔디 — 일요일부터 일곱 칸씩. 그날 본 화면 수에 따라 네 단계 초록. 아직 오지 않은 날은 점선 칸."""
    cells = "".join(f'<span style="font-size:11px;color:#68706c;text-align:center">{d}</span>' for d in "일월화수목금토")
    for week in calendar.Calendar(firstweekday=6).monthdatescalendar(today.year, today.month):
        for d in week:
            if d.month != today.month:
                cells += "<span></span>"
                continue
            c = counts.get(d.isoformat(), 0)
            lv = 0 if c == 0 else 1 if c <= 2 else 2 if c <= 5 else 3 if c <= 10 else 4
            look = (f"background:{LEVEL[lv]}" if d <= today else "border:1px dashed #c0c8c4") + (";outline:2px solid #154539;outline-offset:1px" if d == today else "")
            cells += f'<span title="{d.month}월 {d.day}일" style="aspect-ratio:1;border-radius:5px;{look}"></span>'
    legend = "".join(f'<span style="width:11px;height:11px;border-radius:3px;background:{c};display:inline-block"></span>' for c in LEVEL)
    return (f'<div style="display:grid;grid-template-columns:repeat(7,1fr);gap:5px;max-width:260px;margin:0 auto">{cells}</div>'
            f'<p style="margin:8px auto 0;max-width:260px;display:flex;align-items:center;justify-content:flex-end;gap:4px;font-size:11px;color:#68706c">적게 {legend} 많이</p>')  # fmt: skip


if __name__ == "__main__":
    from pathlib import Path

    rows = "".join(
        f'<h2 style="font:600 15px sans-serif;margin:18px 0 4px">{label}</h2><div style="display:grid;grid-template-columns:repeat(6,1fr);gap:8px">'
        + "".join(f'<figure style="margin:0;background:#fff;border-radius:14px;padding:6px">{svg(n, key)}<figcaption style="font:12px sans-serif;text-align:center;color:#404945">{n}일 · {stage(n)[0]}</figcaption></figure>'
                  for n in (0, 2, 8, 25, 60, 110)) + "</div>"
        for key, label in STYLES.items())  # fmt: skip
    out = Path(__file__).parent.parent / "data" / "tree-sample.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(f'<!doctype html><meta charset="utf-8"><body style="background:#fcf8fb;margin:16px">{rows}</body>', encoding="utf-8")
    print(out)
