"""Генератор логотипа CHIMERA: SVG для интерфейса и ICO для exe из одной геометрии.

Знак — трискелион: три одинаковых завитка из общего центра, повёрнутые на 120°.
Рисуется линиями, но в файлы уходит уже контуром (заливка с дырами, без stroke):
так логотип одинаково выглядит в любом рендерере, масштабируется вместе с
толщиной линий и красится одним fill/currentColor. Внутренний просвет двойной
линии — настоящая дыра, а не линия цветом фона, поэтому знак ложится на любую
подложку.

Варианты:
  chimera        — основной: двойная (контурная) линия;
  chimera-simple — одинарная линия, запасной, пока нигде не используется.

Запуск: python tools/make_logo.py (нужны shapely и pillow из requirements-dev.txt).
Пишет assets/logo/*.svg, assets/logo/chimera.ico, frontend/public/logo.svg (favicon)
и frontend/src/assets/logo-path.ts (знак в разметке интерфейса).
"""

import json

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw
from shapely import affinity
from shapely.geometry import LineString, MultiPolygon
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
LOGO_DIR = ROOT / "assets" / "logo"
WEB_LOGO = ROOT / "frontend" / "public" / "logo.svg"
WEB_LOGO_JS = ROOT / "frontend" / "src" / "assets" / "logo-path.ts"

CENTER = (12.0, 12.0)  # холст 24×24, как у иконок lucide
LIVE = 11.0            # полуразмер живой области: 1 единица отступа до края холста

# Рукав — три кубических сегмента: из центра вверх, дугой вправо и завитком внутрь.
ARM = [
    ((12, 12), (12, 7.5), (14.5, 4.6), (17.4, 5.2)),
    ((17.4, 5.2), (19.8, 5.7), (20.2, 8.9), (18.1, 9.6)),
    ((18.1, 9.6), (16.7, 10.1), (15.7, 8.8), (16.6, 7.9)),
]

# Толщины (в единицах холста): одинарная линия — 2, как у lucide; двойная —
# внешний контур 3.6 с просветом 1.4 посередине.
SIMPLE_WIDTH = 2.0
OUTER_WIDTH = 3.6
INNER_WIDTH = 1.4

# Прозрачная иконка приложения: только знак, без подложки.
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 256)
GLYPH_COLOR = (250, 250, 250, 255)
SUPERSAMPLE = 16


def _cubic(p0, p1, p2, p3, steps=48):
    pts = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        pts.append((
            u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
            u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
        ))
    return pts


def _arms() -> list[LineString]:
    pts = []
    for seg in ARM:
        pts.extend(_cubic(*seg)[(1 if pts else 0):])
    arm = LineString(pts)
    return [affinity.rotate(arm, a, origin=CENTER) for a in (0, 120, 240)]


def _stroke(lines, width):
    return unary_union([ln.buffer(width / 2, quad_segs=16, cap_style="round", join_style="round")
                        for ln in lines])


def _fit(geom):
    """Ужимает знак в живую область 22×22 вокруг центра, если он из неё вылез."""
    minx, miny, maxx, maxy = geom.bounds
    reach = max(CENTER[0] - minx, maxx - CENTER[0], CENTER[1] - miny, maxy - CENTER[1])
    return affinity.scale(geom, LIVE / reach, LIVE / reach, origin=CENTER) if reach > LIVE else geom


def glyph(variant: str):
    arms = _arms()
    if variant == "chimera":
        shape = _stroke(arms, OUTER_WIDTH).difference(_stroke(arms, INNER_WIDTH))
    elif variant == "chimera-simple":
        shape = _stroke(arms, SIMPLE_WIDTH)
    else:
        raise ValueError(variant)
    return _fit(shape.simplify(0.004))


def _polygons(geom):
    return list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]


def _ring_d(ring) -> str:
    coords = list(ring.coords)[:-1]
    head = f"M{coords[0][0]:.2f} {coords[0][1]:.2f}"
    return head + "".join(f"L{x:.2f} {y:.2f}" for x, y in coords[1:]) + "Z"


def path_d(geom) -> str:
    return "".join(_ring_d(r) for p in _polygons(geom) for r in (p.exterior, *p.interiors))


def svg(geom, style: str = "") -> str:
    fill = "" if style else ' fill="currentColor"'
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        f"{style}<path{fill} fill-rule=\"evenodd\" d=\"{path_d(geom)}\"/></svg>\n"
    )


# Для вкладки браузера и маски в сайдбаре: цвет под тему системы. Маске цвет не
# важен (берётся только прозрачность), а favicon так читается на любой вкладке.
WEB_STYLE = ("<style>path{fill:#0a0a0a}"
             "@media (prefers-color-scheme:dark){path{fill:#fafafa}}</style>")

def _mask(geom, size: int, scale: float) -> Image.Image:
    """Маска знака size×size: каждый полигон — заливка минус его дыры, всё вместе — max."""
    k = size / 24
    out = Image.new("L", (size, size), 0)

    def px(coords):
        return [((x - CENTER[0]) * scale * k + size / 2, (y - CENTER[1]) * scale * k + size / 2)
                for x, y in coords]

    for p in _polygons(geom):
        m = Image.new("L", (size, size), 0)
        d = ImageDraw.Draw(m)
        d.polygon(px(p.exterior.coords), fill=255)
        for hole in p.interiors:
            d.polygon(px(hole.coords), fill=0)
        out = ImageChops.lighter(out, m)
    return out


def icon_frame(geom, size: int) -> Image.Image:
    big = size * SUPERSAMPLE
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (big, big), GLYPH_COLOR), (0, 0), _mask(geom, big, 1.0))
    return img.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    WEB_LOGO.parent.mkdir(parents=True, exist_ok=True)

    main_glyph = glyph("chimera")
    def save(path, text):
        data = path.read_bytes() if path.exists() else b"\r\n"
        newline = "\r\n" if b"\r\n" in data else "\n"
        path.write_bytes(text.replace("\n", newline).encode("utf-8"))
    save(LOGO_DIR / "chimera.svg", svg(main_glyph))
    save(LOGO_DIR / "chimera-simple.svg", svg(glyph("chimera-simple")))
    save(WEB_LOGO, svg(main_glyph, WEB_STYLE))
    save(WEB_LOGO_JS, "export const LOGO_PATH = " + json.dumps(path_d(main_glyph)) + "\n")

    frames = [icon_frame(main_glyph, s) for s in ICO_SIZES]
    frames[-1].save(LOGO_DIR / "chimera.ico", format="ICO",
                    sizes=[(s, s) for s in ICO_SIZES], append_images=frames[:-1])
    print("готово:", ", ".join(str(p.relative_to(ROOT)) for p in (
        LOGO_DIR / "chimera.svg", LOGO_DIR / "chimera-simple.svg",
        LOGO_DIR / "chimera.ico", WEB_LOGO, WEB_LOGO_JS)))


if __name__ == "__main__":
    main()
