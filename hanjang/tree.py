"""내 나무 — 들어온 날이 쌓일수록 자라는 나무 + 이번 달 잔디 (프로필, 사용자 10/11).

씨앗 → 새싹 → 어린 나무 → 자라는 나무 → 잎이 풍성한 나무 → 꽃이 핀 나무. 안 들어와도 시들지 않는다(벌 없음).
자라는 기준은 「들어온 날」뿐 — 주가·수익과 잇지 않는다. 그림은 코드가 그린 SVG(같은 날수면 늘 같은 나무).

    uv run python -m hanjang.tree   # 시안 보기 → data/tree-sample.html (자라는 단계)
"""

import calendar
import math
import random
from datetime import date
from html import escape as e

STAGES = ((0, "씨앗"), (1, "새싹"), (4, "어린 나무"), (15, "자라는 나무"), (40, "잎이 풍성한 나무"), (90, "꽃이 핀 나무"))
PINK, GOLD = "#f6c9d3", "#e0a23a"
LEVEL = ("#eae7ea", "#bceddc", "#86c5a4", "#3f7d5c", "#154539")  # 잔디 — 안 온 날 → 많이 본 날


def stage(n: int) -> tuple[str, int | None]:
    """(지금 단계 이름, 다음 단계까지 남은 날 — 마지막 단계면 None)."""
    name = [s for k, s in STAGES if n >= k][-1]
    nxt = next((k - n for k, _ in STAGES if k > n), None)
    return name, nxt


def _ground() -> str:
    grass = "".join(f'<path d="M{x} 262 q-2 -7 -5 -9 M{x} 262 q0 -9 1 -12 M{x} 262 q3 -6 6 -8" stroke="#6aa85e" stroke-width="1.5" fill="none" stroke-linecap="round"/>'
                    for x in (52, 92, 236, 272))  # fmt: skip
    return f'<ellipse cx="160" cy="266" rx="130" ry="12" fill="#e6dfd2"/><ellipse cx="166" cy="265" rx="62" ry="7" fill="#cdbfa6" opacity="0.7"/>{grass}'


def _sprout(n: int) -> str:
    if n == 0:  # 씨앗 — 흙 위에 살짝
        return '<ellipse cx="160" cy="259" rx="7" ry="5" fill="#6b4c33"/><path d="M157 256 q3 -3 6 0" stroke="#b99a6b" stroke-width="1.2" fill="none"/>'
    h = 14 + n * 7
    leaf = "M0 0 C{a} -3 {b} -13 0 -20 C-{b} -13 -{a} -3 0 0 Z".format(a=7 + n, b=8 + n)
    return (f'<path d="M160 262 q-3 -{h // 2} 0 -{h}" stroke="#5a9a4f" stroke-width="3" fill="none" stroke-linecap="round"/>'
            f'<g transform="translate(160 {262 - h}) rotate(-48)"><path d="{leaf}" fill="#5a9a4f"/><path d="M0 -2 L0 -17" stroke="#3d7346" stroke-width="1"/></g>'
            f'<g transform="translate(160 {262 - h}) rotate(42)"><path d="{leaf}" fill="#8cc271"/><path d="M0 -2 L0 -17" stroke="#5a9a4f" stroke-width="1"/></g>')  # fmt: skip


def _flower(x: float, y: float, r: float = 3.4) -> str:
    petals = "".join(f'<circle cx="{x + math.cos(a) * r:.1f}" cy="{y + math.sin(a) * r:.1f}" r="{r * 0.85:.1f}" fill="{PINK}"/>' for a in (i * math.tau / 5 - 1.57 for i in range(5)))
    return f'{petals}<circle cx="{x:.1f}" cy="{y:.1f}" r="{r * 0.55:.1f}" fill="{GOLD}"/>'


SHADES = ("#27523a", "#346b45", "#3f7f4c", "#559653", "#72ad5f", "#94c573", "#b9dc8e")  # 그늘 → 햇빛


def _leafy(n: int) -> str:
    """작은 잎이 빽빽하게 겹친 나무 — 왼쪽 위에서 빛을 받아 그쪽 잎이 밝다. 줄기는 뿌리 쪽이 벌어지고 위로 가늘어지며 가지가 수관 속으로 갈라진다 (사용자 10/11)."""
    rng = random.Random(7)
    s = min(1.0, n / 90) ** 0.6
    h, w = 34 + 86 * s, 5 + 13 * s  # 줄기 높이·밑동 굵기
    rx, ry = 18 + 92 * s, 16 + 64 * s  # 수관
    top = 262 - h
    cx, cy = 160, top - ry * 0.62
    tw = w * 0.42  # 줄기 위쪽 굵기
    trunk = (f'<path d="M{160 - w * 1.05:.1f} 263 C{160 - w * 0.55:.1f} 258 {160 - w * 0.5:.1f} {262 - h * 0.45:.1f} {160 - tw / 2:.1f} {top:.1f} L{160 + tw / 2:.1f} {top:.1f} '
             f'C{160 + w * 0.5:.1f} {262 - h * 0.45:.1f} {160 + w * 0.6:.1f} 258 {160 + w * 1.15:.1f} 263 Z" fill="url(#bark)"/>')  # fmt: skip
    for k in range(int(2 + 4 * s)):  # 나무껍질 결
        x0 = 160 + (k - 2) * w * 0.17
        trunk += f'<path d="M{x0:.1f} {258 - k % 2 * 6} q{1.5 - k % 3:.1f} -{h * 0.25:.1f} {0.6 * (k % 2):.1f} -{h * (0.45 + 0.08 * (k % 3)):.1f}" stroke="#4f3724" stroke-width="0.8" fill="none" opacity="0.45" stroke-linecap="round"/>'
    branches = ""
    if n >= 8:  # 가지 — 줄기 끝에서 갈라져 수관 속으로
        for i, (dx, dy, bw) in enumerate(((-0.62, 0.05, 0.5), (0.6, -0.02, 0.5), (-0.24, -0.5, 0.42), (0.26, -0.55, 0.4), (0.02, -0.2, 0.36))):
            if n < 8 + i * 9:
                continue
            ex, ey = cx + dx * rx * 0.8, cy + dy * ry * 0.8 + ry * 0.25
            branches += (f'<path d="M160 {top + 6:.1f} Q{160 + dx * rx * 0.25:.1f} {top - (top - ey) * 0.35:.1f} {ex:.1f} {ey:.1f}" stroke="#6b4c33" '
                         f'stroke-width="{max(1.6, tw * bw):.1f}" fill="none" stroke-linecap="round"/>')  # fmt: skip
    # 잎 — 뒤(어두운 잎)부터 그려 겹친다. 자리는 늘 같고(잎마다 정해진 자리), 날이 쌓이면 수관이 커지며 잎이 더해진다
    count = min(760, 16 + n * 10)
    scale = 0.7 + 0.42 * s
    groups: list[list[str]] = [[] for _ in SHADES]  # 밝기마다 한 묶음 — 어두운 묶음부터 그려 겹친다. 잎 모양은 <use> 로 한 번만 싣는다(그림이 가볍게)
    for _ in range(count):
        a, d = rng.uniform(0, math.tau), math.sqrt(rng.random())
        ux, uy = math.cos(a) * d, math.sin(a) * d
        uy = uy * 0.92 - 0.05 * (1 - abs(ux))  # 위가 조금 더 봉긋하게
        light = (-ux - uy) * 0.5 + 0.5 + rng.uniform(-0.28, 0.28)  # 왼쪽 위일수록 밝다
        groups[max(0, min(6, int(light * 7)))].append(
            f'<use href="#lf" transform="translate({cx + ux * rx:.0f} {cy + uy * ry:.0f})rotate({rng.randint(0, 179)})scale({scale * rng.uniform(0.8, 1.25):.2f})"/>')
    leaves = "".join(f'<g fill="{c}">{"".join(g)}</g>' for c, g in zip(SHADES, groups))
    under = "".join(f'<ellipse cx="{cx + dx * rx:.1f}" cy="{cy + dy * ry:.1f}" rx="{rx * 0.5:.1f}" ry="{ry * 0.48:.1f}" fill="#2b5a3c"/>'
                    for dx, dy in ((-0.3, 0.08), (0.3, 0.06), (0, -0.28), (0, 0.22)))  # 잎 사이 빈틈을 메우는 그늘  # fmt: skip
    extra = ""
    if n >= 90:  # 꽃
        for _ in range(min(16, 5 + (n - 90) // 4)):
            a, d = rng.uniform(0, math.tau), math.sqrt(rng.random()) * 0.85
            extra += _flower(cx + math.cos(a) * rx * d, cy + math.sin(a) * ry * d * 0.9, 3 + s)
    if n >= 30:  # 발밑 작은 꽃
        extra += _flower(80, 258, 2.6) + _flower(248, 259, 2.4)
    return trunk + branches + under + leaves + extra


def svg(n: int) -> str:
    """들어온 날 n → 나무 그림 한 장. 같은 n 이면 늘 같은 그림."""
    name, _ = stage(n)
    defs = '<defs><linearGradient id="bark" x1="0" x2="1" y1="0" y2="0"><stop offset="0" stop-color="#a07a52"/><stop offset="0.45" stop-color="#84603f"/><stop offset="1" stop-color="#5e4129"/></linearGradient><path id="lf" d="M0 -5.5C3 -3.6 3 3.2 0 5.5C-3 3.2 -3 -3.6 0 -5.5Z"/></defs>'
    return (f'<svg viewBox="0 0 320 280" width="100%" role="img" aria-label="내 나무 — {e(name)}" xmlns="http://www.w3.org/2000/svg">{defs}{_ground()}{_sprout(n) if n < 4 else _leafy(n)}</svg>')


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

    rows = ('<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px">'
            + "".join(f'<figure style="margin:0;background:#fff;border-radius:14px;padding:6px">{svg(n)}<figcaption style="font:12px sans-serif;text-align:center;color:#404945">{n}일 · {stage(n)[0]}</figcaption></figure>'
                      for n in (0, 2, 6, 12, 25, 45, 70, 110)) + "</div>")  # fmt: skip
    out = Path(__file__).parent.parent / "data" / "tree-sample.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(f'<!doctype html><meta charset="utf-8"><body style="background:#fcf8fb;margin:16px">{rows}</body>', encoding="utf-8")
    print(out)
