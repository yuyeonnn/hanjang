"""앱 아이콘 다시 그리기 — 흰 종이를 줄인다(사용자 10/12: 깔았을 때 종이가 너무 크다). 4배로 그려 줄여서 가장자리를 매끈하게."""
import sys
from PIL import Image, ImageDraw

BG, PAPER, SHADOW, HEAD, LINE = (23, 73, 60), (252, 248, 251), (51, 99, 85), (41, 106, 74), (192, 200, 196)


def draw(size: int, paper_w: float) -> Image.Image:
    """paper_w: 종이 너비 ÷ 전체 너비."""
    S = size * 4
    im = Image.new("RGB", (S, S), BG)
    d = ImageDraw.Draw(im)
    w = S * paper_w
    h = w * 1.25
    x0, y0 = (S - w) / 2 - w * 0.03, (S - h) / 2 - w * 0.03
    r = w * 0.085
    off = w * 0.07
    d.rounded_rectangle((x0 + off, y0 + off, x0 + w + off, y0 + h + off), r, fill=SHADOW)
    d.rounded_rectangle((x0, y0, x0 + w, y0 + h), r, fill=PAPER)
    lx, th = x0 + w * 0.13, w * 0.055
    for k, (frac, col) in enumerate(((0.52, HEAD), (0.74, LINE), (0.68, LINE), (0.48, LINE), (0.63, LINE))):
        y = y0 + h * (0.18 + k * 0.15)
        d.rounded_rectangle((lx, y, lx + w * frac, y + th), th / 2, fill=col)
    return im.resize((size, size), Image.LANCZOS)


out = sys.argv[1] if len(sys.argv) > 1 else "hanjang/static"  # python deploy/icon.py — 그림을 바꾸면 pwa.py 의 ?v= 도 올린다
draw(512, 0.34).save(f"{out}/icon-maskable.png")   # 런처가 가장자리를 깎는다 — 종이를 가운데 작게 (전: 0.45)
draw(512, 0.42).save(f"{out}/icon-512.png")        # 전: 0.55
draw(192, 0.42).save(f"{out}/icon-192.png")
draw(180, 0.42).save(f"{out}/apple-touch-icon.png")
