"""Generate SuperCapture app icon (assets/icons/app.ico)."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


def _lerp(a: int, b: int, t: float) -> int:
    return int(round(a + (b - a) * t))


def _blend(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return (
        _lerp(c1[0], c2[0], t),
        _lerp(c1[1], c2[1], t),
        _lerp(c1[2], c2[2], t),
    )


def _draw_diagonal_gradient(
    image: Image.Image,
    rect: tuple[int, int, int, int],
    c1: tuple[int, int, int],
    c2: tuple[int, int, int],
) -> None:
    x0, y0, x1, y1 = rect
    w = max(1, x1 - x0)
    h = max(1, y1 - y0)
    grad = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = grad.load()
    denom = float(max(1, w + h - 2))
    for y in range(h):
        for x in range(w):
            t = (x + y) / denom
            r, g, b = _blend(c1, c2, t)
            px[x, y] = (r, g, b, 255)
    image.alpha_composite(grad, (x0, y0))


def _rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def _draw_star(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color: tuple[int, int, int, int]) -> None:
    draw.polygon(
        [
            (cx, cy - r),
            (cx + r * 0.35, cy - r * 0.35),
            (cx + r, cy),
            (cx + r * 0.35, cy + r * 0.35),
            (cx, cy + r),
            (cx - r * 0.35, cy + r * 0.35),
            (cx - r, cy),
            (cx - r * 0.35, cy - r * 0.35),
        ],
        fill=color,
    )


def create_icon(size: int) -> Image.Image:
    # Draw on a larger canvas for cleaner anti-aliasing at small icon sizes.
    scale = 4
    s = size * scale
    canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # Background: rounded square with gradient.
    radius = int(s * 0.23)
    bg = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    _draw_diagonal_gradient(bg, (0, 0, s, s), (19, 55, 116), (20, 162, 170))
    bg_mask = _rounded_mask(s, radius)
    canvas.alpha_composite(Image.composite(bg, Image.new("RGBA", (s, s), (0, 0, 0, 0)), bg_mask))

    # Soft inner glow for a polished app-like look.
    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    inset = int(s * 0.08)
    gdraw.rounded_rectangle(
        (inset, inset, s - inset, s - inset),
        radius=int(s * 0.18),
        fill=(255, 255, 255, 28),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=int(s * 0.03)))
    canvas.alpha_composite(glow)

    # Camera body.
    cam_w = int(s * 0.64)
    cam_h = int(s * 0.46)
    cam_x0 = (s - cam_w) // 2
    cam_y0 = int(s * 0.31)
    cam_x1 = cam_x0 + cam_w
    cam_y1 = cam_y0 + cam_h
    cam_r = int(s * 0.11)
    draw.rounded_rectangle((cam_x0, cam_y0, cam_x1, cam_y1), radius=cam_r, fill=(244, 249, 255, 255))

    # Camera top bump.
    bump_w = int(cam_w * 0.42)
    bump_h = int(cam_h * 0.22)
    bump_x0 = cam_x0 + int(cam_w * 0.08)
    bump_y0 = cam_y0 - int(bump_h * 0.52)
    bump_x1 = bump_x0 + bump_w
    bump_y1 = bump_y0 + bump_h
    draw.rounded_rectangle((bump_x0, bump_y0, bump_x1, bump_y1), radius=int(s * 0.06), fill=(244, 249, 255, 255))

    # Lens and ring.
    lc = (s // 2, cam_y0 + int(cam_h * 0.52))
    lr_outer = int(s * 0.145)
    lr_inner = int(s * 0.103)
    draw.ellipse(
        (lc[0] - lr_outer, lc[1] - lr_outer, lc[0] + lr_outer, lc[1] + lr_outer),
        fill=(53, 83, 129, 255),
    )

    lens = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    _draw_diagonal_gradient(
        lens,
        (lc[0] - lr_inner, lc[1] - lr_inner, lc[0] + lr_inner, lc[1] + lr_inner),
        (86, 224, 255),
        (49, 105, 255),
    )
    lens_mask = Image.new("L", (s, s), 0)
    lmd = ImageDraw.Draw(lens_mask)
    lmd.ellipse((lc[0] - lr_inner, lc[1] - lr_inner, lc[0] + lr_inner, lc[1] + lr_inner), fill=255)
    canvas.alpha_composite(Image.composite(lens, Image.new("RGBA", (s, s), (0, 0, 0, 0)), lens_mask))

    # Lens highlight.
    hi_r = int(s * 0.04)
    hi_x = lc[0] - int(lr_inner * 0.35)
    hi_y = lc[1] - int(lr_inner * 0.35)
    draw.ellipse((hi_x - hi_r, hi_y - hi_r, hi_x + hi_r, hi_y + hi_r), fill=(255, 255, 255, 210))

    # Cute face detail.
    eye_r = max(2, int(s * 0.012))
    eye_y = cam_y0 + int(cam_h * 0.30)
    eye_dx = int(cam_w * 0.22)
    draw.ellipse((lc[0] - eye_dx - eye_r, eye_y - eye_r, lc[0] - eye_dx + eye_r, eye_y + eye_r), fill=(58, 82, 115, 255))
    draw.ellipse((lc[0] + eye_dx - eye_r, eye_y - eye_r, lc[0] + eye_dx + eye_r, eye_y + eye_r), fill=(58, 82, 115, 255))
    smile_w = int(cam_w * 0.22)
    smile_h = int(cam_h * 0.10)
    smile_y = cam_y1 - int(cam_h * 0.18)
    draw.arc(
        (lc[0] - smile_w // 2, smile_y - smile_h // 2, lc[0] + smile_w // 2, smile_y + smile_h // 2),
        start=15,
        end=165,
        fill=(58, 82, 115, 255),
        width=max(2, int(s * 0.012)),
    )

    # Small sparkle accent.
    _draw_star(
        draw,
        cx=float(cam_x1 - int(cam_w * 0.10)),
        cy=float(cam_y0 + int(cam_h * 0.16)),
        r=float(int(s * 0.055)),
        color=(255, 240, 143, 230),
    )

    # Subtle border.
    draw.rounded_rectangle(
        (1, 1, s - 2, s - 2),
        radius=radius,
        outline=(255, 255, 255, 58),
        width=max(2, int(s * 0.014)),
    )

    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    out_dir = Path(__file__).resolve().parent.parent / "assets" / "icons"
    out_dir.mkdir(parents=True, exist_ok=True)

    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [create_icon(s) for s in sizes]

    ico_path = out_dir / "app.ico"
    images[-1].save(
        str(ico_path),
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[:-1],
    )
    print(f"Icon saved: {ico_path}")


if __name__ == "__main__":
    main()
