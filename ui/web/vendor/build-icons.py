"""Собирает скачанные SVG иконок lucide в один vendor/lucide/icons.js.

Спрайт кладётся прямо в JS, а не в отдельный .svg: внешний <use href="файл.svg#id">
браузер тянет отдельным запросом и до его конца рисует пустоту, а обычный <script>
успевает выполниться до первой отрисовки — иконки появляются сразу и офлайн.

Запускается из update-vendor.sh, руками вызывать не нужно.
"""
import io
import json
import re
import sys
from pathlib import Path

SRC = Path(__file__).parent / "lucide" / "icons"
OUT = Path(__file__).parent / "lucide" / "icons.js"

HEADER = """// Сгенерировано build-icons.py из lucide-static — править руками не нужно,
// набор иконок задан в update-vendor.sh.
//
// Спрайт вставляется в начало <body>, а <i data-icon="wallet"> заменяется на
// <svg class="icon"><use href="#i-wallet"></svg>. Размер и цвет иконка берёт от
// родителя (width:1em, stroke:currentColor), см. .icon в css/base.css.
"""

RUNTIME = """(function () {
  var SPRITE = %s;

  function mount() {
    if (document.getElementById("lucide-sprite")) return;
    var host = document.createElement("div");
    host.id = "lucide-sprite";
    host.hidden = true;
    host.innerHTML = SPRITE;
    document.body.insertBefore(host, document.body.firstChild);
  }

  // Заменяет <i data-icon="..."> на настоящий <svg>. Повторный вызов безопасен:
  // отрисованная иконка тегом <i> уже не является и второй раз не находится.
  function icons(root) {
    mount();
    var list = (root || document).querySelectorAll("i[data-icon]");
    for (var i = 0; i < list.length; i++) {
      var node = list[i];
      var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      var use = document.createElementNS("http://www.w3.org/2000/svg", "use");
      use.setAttribute("href", "#i-" + node.dataset.icon);
      svg.setAttribute("class", "icon " + node.className);
      svg.setAttribute("aria-hidden", "true");
      svg.appendChild(use);
      node.replaceWith(svg);
    }
  }

  window.icons = icons;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { icons(); });
  } else {
    icons();
  }
})();
"""


def main():
    symbols = []
    for path in sorted(SRC.glob("*.svg")):
        # Из файла lucide берём только содержимое <svg>: обводку и размер задаёт CSS.
        body = re.sub(r"(?s)\A.*?<svg[^>]*>|</svg>\s*\Z", "", path.read_text(encoding="utf-8"))
        body = re.sub(r"\s+", " ", body).strip()
        symbols.append('<symbol id="i-%s" viewBox="0 0 24 24">%s</symbol>' % (path.stem, body))

    if not symbols:
        sys.exit("нет ни одного svg в %s — сначала скачайте иконки" % SRC)

    sprite = '<svg xmlns="http://www.w3.org/2000/svg">%s</svg>' % "".join(symbols)
    # newline="\n" — файл уходит в репозиторий, переводы строк везде одинаковые.
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(HEADER + RUNTIME % json.dumps(sprite, ensure_ascii=False))

    print("icons.js: %d иконок, %.1f КБ" % (len(symbols), OUT.stat().st_size / 1024))


if __name__ == "__main__":
    main()
