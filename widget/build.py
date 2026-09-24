"""Build the amoCRM widget archive.

    python build.py https://api.uzbridge.uz

Writes dist/uzbridge-widget.zip with the files at the archive root (amoCRM
rejects archives with a parent folder) and the API base baked into script.js.
Logos are drawn here so the archive always has every size amoCRM requires.
"""

import io
import json
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "src"
DIST = HERE / "dist"

# name -> (width, height), from amoCRM's widget structure docs.
LOGOS = {
    "logo_main.png": (400, 272),
    "logo_small.png": (108, 108),
    "logo.png": (130, 100),
    "logo_medium.png": (240, 84),
    "logo_min.png": (84, 84),
    "logo_dp.png": (174, 109),
}
ACCENT = (18, 135, 127)


def draw_logo(size: tuple[int, int]) -> bytes:
    from PIL import Image, ImageDraw

    w, h = size
    img = Image.new("RGBA", size, (255, 255, 255, 0))
    d = ImageDraw.Draw(img)
    side = min(w, h) * 0.8
    x0, y0 = (w - side) / 2, (h - side) / 2
    d.rounded_rectangle([x0, y0, x0 + side, y0 + side], radius=side * 0.27, fill=ACCENT)
    lw = max(2, int(side * 0.09))
    # A bridge: arch plus three piers.
    d.arc(
        [x0 + side * 0.2, y0 + side * 0.38, x0 + side * 0.8, y0 + side * 0.98],
        start=180, end=360, fill="white", width=lw,
    )
    for fx, top in ((0.3, 0.64), (0.7, 0.64), (0.5, 0.5)):
        d.line([x0 + side * fx, y0 + side * top, x0 + side * fx, y0 + side * 0.8], fill="white", width=lw)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def main():
    if len(sys.argv) != 2 or not sys.argv[1].startswith("https://"):
        sys.exit("usage: python build.py https://api.your-domain")
    api_base = sys.argv[1].rstrip("/")
    json.loads((SRC / "manifest.json").read_text())  # fail early on a broken manifest

    DIST.mkdir(exist_ok=True)
    out = DIST / "uzbridge-widget.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", (SRC / "manifest.json").read_text())
        z.writestr("script.js", (SRC / "script.js").read_text().replace("__API_BASE__", api_base))
        for f in sorted((SRC / "i18n").glob("*.json")):
            json.loads(f.read_text())
            z.writestr(f"i18n/{f.name}", f.read_text())
        for name, size in LOGOS.items():
            custom = SRC / "images" / name
            z.writestr(f"images/{name}", custom.read_bytes() if custom.exists() else draw_logo(size))
    print(f"{out} ({out.stat().st_size // 1024} KB) → API {api_base}")


if __name__ == "__main__":
    main()
