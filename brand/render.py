"""Render every logo file uzbridge ships from the one master mark (n-mark.svg).

    uv run python brand/render.py

Uses headless Chrome for the SVG, so every size comes from the same vector.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
MARK = (HERE / "n-mark.svg").read_text()
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
INK = "#1B2230"
FONT = "https://fonts.googleapis.com/css2?family=Onest:wght@600&display=swap"


def sized(px: int | str) -> str:
    """The master mark at a given size (px, or "100%")."""
    return MARK.replace('width="512" height="512"', f'width="{px}" height="{px}"')


def shot(html: str, w: int, h: int, out: Path, transparent: bool = False) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "p.html"
        page.write_text(
            f'<html><head><link href="{FONT}" rel="stylesheet"></head>'
            f'<body style="margin:0;width:{w}px;height:{h}px;overflow:hidden">{html}</body></html>'
        )
        args = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size={w},{h}"]
        if transparent:
            args.append("--default-background-color=00000000")
        args += ["--virtual-time-budget=3000", f"--screenshot={out}", page.as_uri()]
        subprocess.run(args, check=True, capture_output=True)


def centred(w: int, h: int, inner: str, bg: str) -> str:
    return (
        f'<div style="width:{w}px;height:{h}px;background:{bg};display:flex;align-items:center;'
        f'justify-content:center">{inner}</div>'
    )


def mark_only(w: int, h: int | None = None, pad: float = 0.0, bg: str = "transparent") -> str:
    h = h or w
    return centred(w, h, sized(round(min(w, h) * (1 - 2 * pad))), bg)


def lockup(w: int, h: int, bg: str = "#ffffff", scale: float = 0.42) -> str:
    """Mark + the "uzbridge" wordmark, centred."""
    m = round(h * scale)
    word = (
        f'<span style="font-family:Onest,sans-serif;font-weight:600;font-size:{round(m * 0.5)}px;'
        f'letter-spacing:-0.02em;color:{INK};margin-left:{round(m * 0.18)}px">uzbridge</span>'
    )
    return centred(w, h, sized(m) + word, bg)


def main() -> None:
    pub = ROOT / "frontend" / "public"
    # Dashboard: vector mark for the UI + favicon, PNGs for touch icons.
    (pub / "brand").mkdir(exist_ok=True)
    shutil.copy(HERE / "n-mark.svg", pub / "brand" / "n-mark.svg")
    shutil.copy(HERE / "n-mark.svg", pub / "favicon.svg")
    shot(mark_only(180, pad=0.1, bg="#ffffff"), 180, 180, pub / "apple-touch-icon.png")
    shot(mark_only(32), 32, 32, pub / "favicon-32.png", transparent=True)
    # The icon amoCRM shows for the button-made integration.
    shot(lockup(400, 272), 400, 272, pub / "amocrm-logo.png")

    # Django admin (Jazzmin): sidebar / login logo and tab icon.
    static = ROOT / "backend" / "static" / "brand"
    static.mkdir(parents=True, exist_ok=True)
    shutil.copy(HERE / "n-mark.svg", static / "n-mark.svg")
    shot(mark_only(128), 128, 128, static / "n-mark-128.png", transparent=True)

    # amoCRM widget: every size its structure docs ask for.
    img = ROOT / "widget" / "src" / "images"
    shot(lockup(400, 272), 400, 272, img / "logo_main.png")
    shot(lockup(240, 84, scale=0.5), 240, 84, img / "logo_medium.png")
    shot(lockup(174, 109), 174, 109, img / "logo_dp.png")
    shot(mark_only(130, 100, pad=0.11, bg="#ffffff"), 130, 100, img / "logo.png")  # too narrow for the wordmark
    shot(mark_only(108, pad=0.12, bg="#ffffff"), 108, 108, img / "logo_small.png")
    shot(mark_only(84, pad=0.12, bg="#ffffff"), 84, 84, img / "logo_min.png")
    for lang in ("ru", "en"):
        shot(lockup(1000, 680, "#F4F8FB", 0.34), 1000, 680, img / f"tour_1_{lang}.png")

    # Odoo addon icon (apps list and the payment provider image).
    icon = ROOT / "odoo_addons" / "uzbridge" / "static" / "description" / "icon.png"
    shot(mark_only(256, pad=0.12, bg="#ffffff"), 256, 256, icon)
    print("rendered")


if __name__ == "__main__":
    main()
