#!/usr/bin/env python3
"""Run evaluation and mirror the static site into GitHub Pages /docs."""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
subprocess.run([sys.executable, str(ROOT / "src" / "evaluate.py")], cwd=ROOT, check=True)
(ROOT / "docs").mkdir(exist_ok=True)
for name in ("index.html", "styles.css", "app.js", "results.json"):
    source = ROOT / "web" / name
    target = ROOT / "docs" / name
    shutil.copyfile(source, target)
    if source.read_bytes() != target.read_bytes():
        raise SystemExit(f"sync verification failed: {name}")
print("OK: evaluation rerun; web and docs are byte-identical")
