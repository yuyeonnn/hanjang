"""선 나무 그림(사용자가 고른 것, 10/14) → 화면용 그림과 앱 아이콘. `python deploy/tree_icon.py` (Pillow 필요 — 서버에서는 돌리지 않는다, 만든 파일을 커밋한다).
deploy/tree-source.png: 배경을 지운 원본(665×559). 선 굵기는 원본 그대로 둔다(사용자: 굵게 하지 말 것)."""
from PIL import Image

PAPER = (252, 248, 251)
src = Image.open("deploy/tree-source.png")


def fit(box: int) -> Image.Image:
    im = src.copy()
    im.thumbnail((box, box), Image.LANCZOS)
    return im


def icon(size: int, fill: float) -> Image.Image:
    """종이색 네모 한가운데에 나무 — fill: 나무가 차지하는 너비의 비율."""
    im, t = Image.new("RGBA", (size, size), PAPER + (255,)), fit(round(size * fill))
    im.alpha_composite(t, ((size - t.width) // 2, (size - t.height) // 2))
    return im.convert("RGB")


fit(420).save("hanjang/static/tree.png", optimize=True)  # 화면에서는 너비 210 — 두 배로 만들어 또렷하게
icon(512, 0.62).save("hanjang/static/icon-maskable.png", optimize=True)  # 런처가 가장자리를 깎는다 — 가운데 안쪽에
icon(512, 0.86).save("hanjang/static/icon-512.png", optimize=True)
icon(192, 0.86).save("hanjang/static/icon-192.png", optimize=True)
icon(180, 0.86).save("hanjang/static/apple-touch-icon.png", optimize=True)
