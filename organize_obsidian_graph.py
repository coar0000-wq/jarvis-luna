#!/usr/bin/env python3
"""Clean generated graph folders and rebuild one connected Obsidian graph."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from expand_obsidian_graph import slug

ROOT = Path(__file__).resolve().parent
VAULT = ROOT / "obsidian" / "JARVIS_LUNA"
KNOWLEDGE = VAULT / "Knowledge"
GENERATED = (KNOWLEDGE / "Records", KNOWLEDGE / "Sources", KNOWLEDGE / "Topics")
HUB = VAULT / "JARVIS Graph Hub.md"
DASHBOARD = VAULT / "JARVIS Dashboard Sync.md"


def remove_generated_only() -> None:
    for path in GENERATED:
        if path.exists():
            shutil.rmtree(path)


def write_hub() -> None:
    """Write only links whose target notes exist in the current generated vault."""
    candidates = [
        "JARVIS Real Knowledge Index",
        "JARVIS Dashboard Sync",
        "Source · arXiv",
        "Source · YouTube",
        "Source · Google Search",
        "Shopify Commerce",
        "AI Image Generation",
        "AI Research",
        "Machine Learning Research",
        "AI Agents",
        "Model Routing and MoE",
    ]
    existing_stems = {path.stem for path in VAULT.rglob("*.md") if path != HUB}
    links = [name for name in candidates if slug(name) in existing_stems or name in existing_stems]
    body = [
        "---",
        "title: JARVIS Graph Hub",
        "type: graph-hub",
        "status: generated",
        "---",
        "",
        "# JARVIS Graph Hub",
        "",
        "이 노트는 JARVIS_LUNA 전체 지식 그래프의 진입점입니다. 실제 수집 지식, 출처, 주제, 개별 레코드와 대시보드를 한 곳에서 연결합니다.",
        "",
        "## Knowledge graph",
        "",
    ]
    body.extend(
        f"- [[{name if name in {'JARVIS Real Knowledge Index', 'JARVIS Dashboard Sync'} else slug(name)}]]"
        for name in links
    )
    body.extend([
        "",
        "## Graph rules",
        "",
        "새로운 실제 수집 레코드는 Source·Topic·Record 노드에 연결되어야 합니다. 생성된 노트는 원문 URL과 수집 출처를 포함해야 하며, 임의 샘플은 그래프에 넣지 않습니다.",
    ])
    HUB.write_text("\n".join(body) + "\n", encoding="utf-8")


def connect_dashboard() -> None:
    if not DASHBOARD.exists():
        return
    text = DASHBOARD.read_text(encoding="utf-8")
    marker = "\n## Graph navigation\n"
    section = marker + "\n- [[JARVIS Graph Hub]]\n- [[JARVIS Real Knowledge Index]]\n"
    if marker not in text:
        DASHBOARD.write_text(text.rstrip() + section, encoding="utf-8")


def main() -> int:
    KNOWLEDGE.mkdir(parents=True, exist_ok=True)
    remove_generated_only()
    result = subprocess.run([sys.executable, str(ROOT / "expand_obsidian_graph.py")], cwd=ROOT, check=False)
    if result.returncode:
        return result.returncode
    write_hub()
    connect_dashboard()
    print(f"organized vault: {VAULT}")
    print("removed and regenerated: Records, Sources, Topics")
    print(f"hub: {HUB}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
