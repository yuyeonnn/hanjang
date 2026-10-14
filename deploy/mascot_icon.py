"""앱 아이콘 = 마스코트(네잎클로버를 든 강아지, 사용자가 Stitch 로 만듦 10/14). `python deploy/mascot_icon.py deploy/mascot-clover-source.png hanjang/static` — 그림을 바꾸면 pwa.py 의 ?v= 도 올린다.
지금 원본은 화면 캡처에서 자른 것(394×476)이라, 큰 원본 파일을 받으면 deploy/mascot-clover-source.png 만 바꿔 다시 돌린다. mascot-clover.png(배경 지운 것)는 hanjang/static/mascot/clover.png 로 옮겨 쓴다."""
import sys
from collections import deque

import numpy as np
from PIL import Image, ImageFilter

src, out_dir = sys.argv[1], sys.argv[2]
im = Image.open(src).convert("RGB")
a = np.asarray(im).astype(int)
h, w, _ = a.shape
br = a.sum(axis=2) / 3
bgish = (br > 229) & (br < 243) & (abs(a[:, :, 0] - a[:, :, 2]) < 6)  # 회색 종이 배경(237±5)만 — 흰 몸(250+)·옅은 그림자·분홍·선은 아님
mask = np.zeros((h, w), bool)
dq = deque((y, x) for y in range(h) for x in range(w) if (y in (0, h - 1) or x in (0, w - 1)) and bgish[y, x])
for y, x in dq:
    mask[y, x] = True
while dq:
    y, x = dq.popleft()
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        yy, xx = y + dy, x + dx
        if 0 <= yy < h and 0 <= xx < w and not mask[yy, xx] and bgish[yy, xx]:
            mask[yy, xx] = True
            dq.append((yy, xx))
fg = Image.fromarray((~mask * 255).astype("uint8"))
fg = fg.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.MinFilter(7))   # 선이 끊긴 틈으로 샌 자리를 메운다
alpha = fg.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
rgba = im.convert("RGBA")
rgba.putalpha(alpha)
rgba.save(f"{out_dir}/mascot-clover.png")
BG = (225, 240, 232, 255)  # 옅은 초록 — 흰 강아지와 검은 선이 다 보인다


def icon(size: int, frac: float) -> Image.Image:
    S = size * 2
    out = Image.new("RGBA", (S, S), BG)
    th = int(S * frac)
    tw = int(th * w / h)
    out.alpha_composite(rgba.resize((tw, th), Image.LANCZOS), ((S - tw) // 2, (S - th) // 2 + int(S * 0.01)))
    return out.resize((size, size), Image.LANCZOS).convert("RGB")


icon(512, 0.58).save(f"{out_dir}/icon-maskable.png")  # 런처가 가장자리를 깎는다 — 가운데 60% 안에
icon(512, 0.74).save(f"{out_dir}/icon-512.png")
icon(192, 0.74).save(f"{out_dir}/icon-192.png")
icon(180, 0.74).save(f"{out_dir}/apple-touch-icon.png")
print("ok", rgba.size)
