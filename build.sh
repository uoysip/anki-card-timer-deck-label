#!/usr/bin/env bash
# Packages addon/ into card_timer_deck_label.ankiaddon (install via Tools > Add-ons > Install from file)
set -euo pipefail
cd "$(dirname "$0")/addon"
rm -rf __pycache__
rm -f ../card_timer_deck_label.ankiaddon
zip -q -X ../card_timer_deck_label.ankiaddon __init__.py settings.py config.json manifest.json
# the license lives at the repo root; -j stores it at the top of the package
zip -q -X -j ../card_timer_deck_label.ankiaddon ../LICENSE
echo "Built $(cd .. && pwd)/card_timer_deck_label.ankiaddon"
