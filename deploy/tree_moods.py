"""선 나무 그림의 여러 버전 — 잎 떨어짐·바람·달밤·해·비. `python deploy/tree_moods.py` → hanjang/static/tree-*.webp (Pillow 필요, 만든 파일을 커밋한다).
더한 잎·달·해·비는 나무와 같은 색·같은 굵기의 선. 캔버스(860×600)는 나무(665)보다 넓다 — 달·해·날리는 잎이 잘리지 않게."""
import math
import random
from PIL import Image, ImageDraw

INK, PAPER = (125, 143, 136), (252, 248, 251)
K = 2  # 두 배로 그려 줄여서 선을 매끈하게
src = Image.open("deploy/tree-source.png")
W, H = 860, 600
OX, OY = (W - src.width) // 2, H - src.height - 12
LW = 2.6  # 원본 그림의 선 굵기쯤


def canvas():
    return Image.new("RGBA", (W * K, H * K), (0, 0, 0, 0))


def base(bend=0.0):
    """나무를 놓는다. bend: 위로 갈수록 오른쪽으로 휘는 정도(px) — 땅은 그대로."""
    im = canvas()
    big = src.resize((src.width * K, src.height * K), Image.LANCZOS)
    if not bend:
        im.alpha_composite(big, (OX * K, OY * K)); return im
    gy = big.height - 30 * K  # 땅 줄 위부터 휜다
    for y in range(big.height):
        t = max(0.0, (gy - y) / gy)
        im.alpha_composite(big.crop((0, y, big.width, y + 1)), (OX * K + round(bend * K * t ** 1.6), OY * K + y))
    return im


def bez(p0, p1, p2, p3, n=24):
    return [tuple((1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * b + 3 * (1 - t) * t * t * c + t ** 3 * d for a, b, c, d in zip(p0, p1, p2, p3)) for t in (i / n for i in range(n + 1))]


def stroke(d, pts, w=LW):
    d.line([(x * K, y * K) for x, y in pts], fill=INK + (255,), width=round(w * K), joint="curve")


def leaf(d, x, y, deg, s=3.4):
    """잎 한 장 — 나무의 잎과 같은 모양(윤곽 + 가운데 잎맥)."""
    a = math.radians(deg); c, sn = math.cos(a), math.sin(a)
    tr = lambda px, py: (x + (px * c - py * sn) * s, y + (px * sn + py * c) * s)
    stroke(d, [tr(*p) for p in bez((0, 0), (3.6, -2.6), (3.8, -8.6), (0, -12.5)) + bez((0, -12.5), (-3.8, -8.6), (-3.6, -2.6), (0, 0))], LW * 0.85)
    stroke(d, [tr(0, -1.5), tr(0, -9.5)], LW * 0.85)


def fall():
    im = base(); d = ImageDraw.Draw(im)
    for x, y, r in ((690, 250, 70), (735, 345, 130), (650, 420, 95), (705, 520, 160), (175, 430, -110), (610, 572, 84), (240, 574, -80)):
        leaf(d, x, y, r)
    return im


def wind():
    im = base(90); d = ImageDraw.Draw(im); rng = random.Random(4)
    for x, y in ((735, 150), (790, 235), (760, 330), (815, 400), (700, 440)):
        leaf(d, x, y, rng.uniform(60, 120))
    for x, y, ln in ((40, 170, 110), (20, 260, 80), (70, 330, 120), (700, 505, 90)):  # 바람 줄
        stroke(d, bez((x, y), (x + ln * 0.3, y - 10), (x + ln * 0.7, y + 10), (x + ln, y)), LW * 0.8)
    return im


def moon():
    im = base(); d = ImageDraw.Draw(im)
    cx, cy, r, dd, r2, tilt = 60, 95, 40, 22, 34, -35
    x0 = (dd * dd + r * r - r2 * r2) / (2 * dd); y0 = math.sqrt(r * r - x0 * x0)
    th, ph = math.degrees(math.atan2(y0, x0)), math.degrees(math.atan2(y0, x0 - dd))
    rot = lambda px, py: (cx + px * math.cos(math.radians(tilt)) - py * math.sin(math.radians(tilt)), cy + px * math.sin(math.radians(tilt)) + py * math.cos(math.radians(tilt)))
    arc = lambda ox, rr, a0: [rot(ox + rr * math.cos(math.radians(a0 + (360 - 2 * a0) * k / 40)), rr * math.sin(math.radians(a0 + (360 - 2 * a0) * k / 40))) for k in range(41)]
    stroke(d, arc(0, r, th) + arc(dd, r2, ph)[::-1])  # 초승달 — 바깥 둥근 줄과 안쪽 둥근 줄
    for x, y, q in ((150, 40, 8), (20, 190, 6), (800, 70, 7), (835, 190, 5), (720, 20, 5)):  # 별 — 짧은 십자
        stroke(d, [(x - q, y), (x + q, y)], LW * 0.8); stroke(d, [(x, y - q), (x, y + q)], LW * 0.8)
    return im


def sun():
    im = base(); d = ImageDraw.Draw(im); cx, cy, r = 795, 70, 30
    stroke(d, [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))) for a in range(0, 361, 6)])
    for a in range(0, 360, 45):
        c, s = math.cos(math.radians(a)), math.sin(math.radians(a))
        stroke(d, [(cx + c * (r + 12), cy + s * (r + 12)), (cx + c * (r + 26), cy + s * (r + 26))])
    return im


def rain():
    im = base(); d = ImageDraw.Draw(im); rng = random.Random(9)
    for x, y in ((80, 60), (190, 30), (300, 50), (430, 24), (560, 48), (690, 70), (790, 40), (60, 240), (800, 250), (120, 400), (740, 420), (30, 520), (820, 540), (700, 180), (150, 150)):
        ln = rng.uniform(16, 24); stroke(d, [(x, y), (x - ln * 0.3, y + ln)], LW * 0.8)
    return im


if __name__ == "__main__":
    for name, fn in (("fall", fall), ("wind", wind), ("moon", moon), ("sun", sun), ("rain", rain)):
        fn().resize((W * 2 // 3, H * 2 // 3), Image.LANCZOS).save(f"hanjang/static/tree-{name}.webp", quality=82, method=6)
