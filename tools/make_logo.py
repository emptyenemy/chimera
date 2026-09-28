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
Пишет assets/logo/*.svg, assets/logo/chimera.ico, ui/web/img/logo.svg (favicon)
и ui/web/js/logo.js (знак в разметке интерфейса).
"""

import json

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw
from shapely import affinity
from shapely.geometry import LineString, MultiPolygon
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
LOGO_DIR = ROOT / "assets" / "logo"
WEB_LOGO = ROOT / "ui" / "web" / "img" / "logo.svg"
WEB_LOGO_JS = ROOT / "ui" / "web" / "js" / "logo.js"

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

# Иконка приложения: тёмная плашка с серым краем — на тёмной панели задач
# знак не теряется, на светлой плашка сама даёт контраст.
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 256)
PLATE_FILL = (10, 10, 10, 255)
PLATE_EDGE = (63, 63, 70, 255)
PLATE_RADIUS = 5.5
PLATE_EDGE_WIDTH = 0.5
GLYPH_ON_PLATE = 0.78  # насколько ужать знак на плашке
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

# Знак в интерфейсе — прямо в JS, как спрайт lucide (ui/web/vendor/build-icons.py):
# окно Qt открывает страницу через file://, и внешний svg (маской или <img>)
# зависит от доступа к локальным файлам, а inline-разметка рисуется всегда и сразу.
LOGO_JS = """// Сгенерировано tools/make_logo.py — править руками не нужно.
//
// <i data-logo></i> заменяется на inline-<svg> логотипа. Цвет — currentColor,
// размер — от родителя (width/height svg: 100%%).
(function () {
  var SVG = %s;
  function logo(root) {
    var list = (root || document).querySelectorAll("i[data-logo]");
    for (var i = 0; i < list.length; i++) {
      var tpl = document.createElement("template");
      tpl.innerHTML = SVG;
      var svg = tpl.content.firstChild;
      svg.setAttribute("class", "logo " + list[i].className);
      svg.setAttribute("aria-hidden", "true");
      list[i].replaceWith(svg);
    }
  }
  window.logo = logo;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { logo(); });
  } else {
    logo();
  }
})();
"""


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
    k = big / 24
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    edge = max(1, round(PLATE_EDGE_WIDTH * k))
    ImageDraw.Draw(img).rounded_rectangle(
        (0, 0, big - 1, big - 1), radius=PLATE_RADIUS * k,
        fill=PLATE_FILL, outline=PLATE_EDGE, width=edge,
    )
    img.paste(Image.new("RGBA", (big, big), GLYPH_COLOR), (0, 0), _mask(geom, big, GLYPH_ON_PLATE))
    return img.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    WEB_LOGO.parent.mkdir(parents=True, exist_ok=True)

    main_glyph = glyph("chimera")
    # LF на любой ОС: иначе на Windows write_text пишет \r\n и файлы расходятся с репозиторием
    lf = {"encoding": "utf-8", "newline": "\n"}
    (LOGO_DIR / "chimera.svg").write_text(svg(main_glyph), **lf)
    (LOGO_DIR / "chimera-simple.svg").write_text(svg(glyph("chimera-simple")), **lf)
    WEB_LOGO.write_text(svg(main_glyph, WEB_STYLE), **lf)
    WEB_LOGO_JS.write_text(LOGO_JS % json.dumps(svg(main_glyph).strip()), **lf)

    frames = [icon_frame(main_glyph, s) for s in ICO_SIZES]
    frames[-1].save(LOGO_DIR / "chimera.ico", format="ICO",
                    sizes=[(s, s) for s in ICO_SIZES], append_images=frames[:-1])
    print("готово:", ", ".join(str(p.relative_to(ROOT)) for p in (
        LOGO_DIR / "chimera.svg", LOGO_DIR / "chimera-simple.svg",
        LOGO_DIR / "chimera.ico", WEB_LOGO, WEB_LOGO_JS)))


if __name__ == "__main__":
    main()
