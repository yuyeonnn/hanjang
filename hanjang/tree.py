"""내 나무 — 들어온 날이 쌓일수록 자라는 나무 + 이번 달 잔디 (프로필, 사용자 10/11).

씨앗 → 새싹 → 어린 나무 → 자라는 나무 → 잎이 풍성한 나무 → 꽃이 핀 나무. 안 들어와도 시들지 않는다(벌 없음).
자라는 기준은 「들어온 날」뿐 — 주가·수익과 잇지 않는다. 그림은 코드가 그린 SVG(같은 날수면 늘 같은 나무).

    uv run python -m hanjang.tree   # 시안 보기 → data/tree-sample.html (자라는 단계)
"""

import math
from datetime import date, timedelta
from html import escape as e

STAGES = ((0, "씨앗"), (1, "새싹"), (4, "어린 나무"), (15, "자라는 나무"), (40, "잎이 풍성한 나무"), (90, "꽃이 핀 나무"))
LEVEL = ("#eae7ea", "#bceddc", "#86c5a4", "#3f7d5c", "#154539")  # 잔디 — 안 온 날 → 많이 본 날


def stage(n: int) -> tuple[str, int | None]:
    """(지금 단계 이름, 다음 단계까지 남은 날 — 마지막 단계면 None)."""
    name = [s for k, s in STAGES if n >= k][-1]
    nxt = next((k - n for k, _ in STAGES if k > n), None)
    return name, nxt


GREENS = ("#2f5d50", "#3f7d5c", "#5c9a72", "#86b98f", "#a9d1ae")


def _spots() -> tuple[list, list]:
    """잎 360장·꽃 14송이의 정해진 자리 — 사용자가 고른 시안(10/11 데모)과 똑같은 난수로. 날이 쌓이면 앞에서부터 차례로 달린다."""
    seed = 7

    def rnd() -> float:
        nonlocal seed
        seed = (seed * 1664525 + 1013904223) % 4294967296
        return seed / 4294967296

    leaves = []
    for _ in range(360):
        a, r = rnd() * math.tau, math.sqrt(rnd())
        leaves.append((math.cos(a) * r, math.sin(a) * r, GREENS[int(rnd() * len(GREENS))], int(rnd() * 180), 0.8 + rnd() * 0.6))
    flowers = []
    for _ in range(14):
        a, r = rnd() * math.tau, math.sqrt(rnd()) * 0.9
        flowers.append((math.cos(a) * r, math.sin(a) * r))
    return leaves, flowers


LEAVES, FLOWERS = _spots()


def svg(n: int) -> str:
    """들어온 날 n → 나무 그림 한 장(같은 n 이면 늘 같은 그림). 하루에 잎 세 장, 120일이면 360장. 90일부터 꽃."""
    name, _ = stage(n)
    gx, gy = 160, 270
    out = [f'<ellipse cx="{gx}" cy="{gy + 6}" rx="120" ry="10" fill="#b99a6b" opacity="0.35"/><ellipse cx="{gx}" cy="{gy + 2}" rx="34" ry="7" fill="#8a6a48"/>']
    if n == 0:
        out.append(f'<ellipse cx="{gx}" cy="{gy - 3}" rx="6" ry="4" fill="#6b4a2f"/>')
    else:
        h, tw = min(150, 14 + n * 1.5), min(16, 2 + n * 0.14)
        ty = gy - h
        out.append(f'<path d="M{gx - tw / 2:.1f} {gy} Q{gx - tw / 3:.1f} {gy - h / 2:.1f} {gx - 1} {ty:.1f} L{gx + 1} {ty:.1f} Q{gx + tw / 3:.1f} {gy - h / 2:.1f} {gx + tw / 2:.1f} {gy} Z" fill="#7a5a3c"/>')
        rx, ry = min(118, 8 + n * 1.1), min(92, 7 + n * 0.85)
        cy = ty - ry * 0.45
        if n >= 12:  # 가지 — 열흘쯤마다 하나씩
            for i, (bx, by) in enumerate(((-0.55, 0.15), (0.55, 0.05), (-0.3, -0.4), (0.32, -0.45))):
                if n >= 12 + i * 10:
                    out.append(f'<path d="M{gx} {ty + h * 0.28:.1f} Q{gx + bx * rx * 0.5:.1f} {cy + by * ry + 18:.1f} {gx + bx * rx:.1f} {cy + by * ry:.1f}" '
                               f'fill="none" stroke="#7a5a3c" stroke-width="{max(1.5, tw * 0.3):.1f}" stroke-linecap="round"/>')  # fmt: skip
        ls = min(9, 4 + n * 0.06)
        for ux, uy, c, rot, s in LEAVES[: min(360, n * 3)]:
            x, y = gx + ux * rx, cy + uy * ry
            out.append(f'<ellipse cx="{x:.1f}" cy="{y:.1f}" rx="{ls * s:.1f}" ry="{ls * s * 0.55:.1f}" fill="{c}" transform="rotate({rot} {x:.1f} {y:.1f})"/>')
        if n >= 90:  # 꽃 — 분홍 꽃잎 다섯 장에 노란 가운데
            for ux, uy in FLOWERS[: min(len(FLOWERS), int((n - 90) / 1.5) + 2)]:
                x, y = gx + ux * rx, cy + uy * ry
                out.append("".join(f'<circle cx="{x + math.cos(p * math.tau / 5) * 3.2:.1f}" cy="{y + math.sin(p * math.tau / 5) * 3.2:.1f}" r="2.6" fill="#f4c6cf"/>' for p in range(5))
                           + f'<circle cx="{x:.1f}" cy="{y:.1f}" r="1.8" fill="#e0a23a"/>')  # fmt: skip
    return f'<svg viewBox="0 -18 320 310" width="100%" role="img" aria-label="내 나무 — {e(name)}" xmlns="http://www.w3.org/2000/svg">{"".join(out)}</svg>'


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
    return (f'<div style="display:grid;grid-auto-flow:column;grid-template-rows:14px repeat(7,18px);grid-auto-columns:max-content;gap:4px;width:max-content;max-width:100%">{cells}</div>'
            f'<p style="margin:8px 0 0;display:flex;align-items:center;gap:4px;font-size:11px;color:#68706c">적게 {legend} 많이</p>'), came  # fmt: skip


if __name__ == "__main__":
    from pathlib import Path

    rows = ('<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px">'
            + "".join(f'<figure style="margin:0;background:#fff;border-radius:14px;padding:6px">{svg(n)}<figcaption style="font:12px sans-serif;text-align:center;color:#404945">{n}일 · {stage(n)[0]}</figcaption></figure>'
                      for n in (0, 2, 6, 12, 25, 45, 70, 110)) + "</div>")  # fmt: skip
    out = Path(__file__).parent.parent / "data" / "tree-sample.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(f'<!doctype html><meta charset="utf-8"><body style="background:#fcf8fb;margin:16px">{rows}</body>', encoding="utf-8")
    print(out)
