name: Root Collector

on:
  schedule:
    - cron: "*/30 * * * *"
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: root-collector
  cancel-in-progress: false

jobs:
  collect:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install packages
        run: |
          python -m pip install --upgrade pip
          pip install requests beautifulsoup4 lxml pandas

      - name: Create data folders
        run: |
          mkdir -p data
          mkdir -p data/daiso_real

      - name: Guard GOSI (Restore)
        run: |
          if [ ! -f data/daiso_real/daiso_gosi.json ]; then
            echo "{}" > data/daiso_real/daiso_gosi.json
            echo "Created empty daiso_gosi.json"
          fi

          python -u scripts/guard_gosi.py --restore

      - name: Run GOSI Collector
        run: |
          python -u scripts/gosi_collector.py

      - name: Verify JSON
        run: |
          python - <<'PY'
          import json
          from pathlib import Path

          p = Path("data/daiso_real/daiso_gosi.json")

          if not p.exists():
              raise SystemExit("daiso_gosi.json missing")

          with open(p, "r", encoding="utf-8") as f:
              json.load(f)

          print("JSON OK")
          PY

      - name: Commit & Push
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

          git add data/daiso_real/daiso_gosi.json

          git diff --cached --quiet || git commit -m "auto: update cosmetic gosi"

          git push
