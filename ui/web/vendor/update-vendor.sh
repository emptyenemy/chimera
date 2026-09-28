#!/bin/sh
# Перекачивает иконки lucide и пересобирает спрайт vendor/lucide/icons.js.
# Единственное место, где фронт ходит наружу, — в рантайме всё локальное.
# Новая иконка — дописать имя в ICONS (как на lucide.dev) и запустить скрипт.
# Шрифты (Inter, JetBrains Mono) лежат в ../fonts, версии — в modules/upstream.py.
set -eu

LUCIDE=1.41.0

ICONS="activity arrow-down-to-line arrow-right arrow-up-right ban check chevron-down chevron-right
chevron-up chevrons-up-down circle-alert circle-check circle-dot circle-help circle-x clipboard-copy clock
copy cpu download ellipsis external-link eye eye-off file-text filter folder-open gamepad-2 gauge
git-branch globe hard-drive info key-round layout-dashboard link list list-checks loader-circle lock
network package pause pencil play plus power radar refresh-cw rotate-ccw save scan-search search
send server settings shield shield-check shield-off sliders-horizontal sparkles square terminal
trash-2 triangle-alert unlock upload wifi wifi-off x zap"

cd "$(dirname "$0")"
mkdir -p lucide/icons
rm -f lucide/icons/*.svg
for i in $ICONS; do
  curl -fsSL -o "lucide/icons/$i.svg" \
    "https://cdn.jsdelivr.net/npm/lucide-static@$LUCIDE/icons/$i.svg"
done

python build-icons.py
echo "OK: lucide@$LUCIDE"
