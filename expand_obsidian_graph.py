#!/usr/bin/env python3
"""Expand the Obsidian knowledge graph from real collected records only."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "knowledge" / "real_sources.json"
CORPUS = ROOT / "data" / "knowledge" / "training_corpus.jsonl"
KNOWLEDGE = ROOT / "obsidian" / "JARVIS_LUNA" / "Knowledge"
SLUG_RE = re.compile(r"[^\w가-힣 -]+", re.UNICODE)
TOKEN_RE = re.compile(r"[\w가-힣]{3,}", re.UNICODE)
STOP = {"the", "and", "for", "with", "from", "that", "this", "using", "based", "into", "about", "their", "your", "our", "are", "was", "have", "has"}


def slug(text: str, fallback: str = "Node") -> str:
    clean = SLUG_RE.sub("", text).strip().replace(" ", "-")
    return clean[:70] or fallback


def wiki(name: str) -> str:
    # Obsidian resolves wikilinks by filename, not by the rendered H1 title.
    target = name if name == "JARVIS Real Knowledge Index" else slug(name)
    return f"[[{target}]]"


def load_records() -> list[dict]:
    rows: list[dict] = []
    if CORPUS.exists():
        for line in CORPUS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    if rows:
        return rows
    if not RAW.exists():
        raise SystemExit(f"Missing real source file: {RAW}")
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    for source_name, source in raw.get("sources", {}).items():
        for item in source.get("items", []):
            rows.append({
                "title": item.get("title", "Untitled"),
                "text": item.get("summary", ""),
                "url": item.get("url", ""),
                "source": item.get("source", source_name),
                "source_key": source_name,
            })
    return rows


def topic_names(row: dict) -> list[str]:
    blob = (row.get("title", "") + " " + row.get("text", "")).lower()
    candidates = [
        ("Shopify Commerce", ("shopify", "ecommerce", "commerce", "product")),
        ("AI Image Generation", ("image", "vision", "diffusion", "text-to-image", "generative")),
        ("Machine Learning Research", ("learning", "model", "neural", "training", "reinforcement")),
        ("AI Agents", ("agent", "agentic", "workflow", "tool use")),
        ("Model Routing and MoE", ("routing", "mixture-of-experts", "moe", "expert")),
    ]
    topics = [name for name, terms in candidates if any(term in blob for term in terms)]
    return topics or ["AI Research"]


def source_name(row: dict) -> str:
    source = str(row.get("source", "Unknown"))
    if "arxiv" in source.lower():
        return "Source · arXiv"
    if "youtube" in source.lower():
        return "Source · YouTube"
    if "google" in source.lower() or "rss" in source.lower():
        return "Source · Google Search"
    return "Source · " + slug(source, "Unknown")


def write_note(path: Path, title: str, tags: list[str], links: list[str], body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    unique_links = list(dict.fromkeys(links))
    frontmatter = "---\n" + f'title: "{title.replace(chr(34), chr(39))}"\n' + "type: knowledge-graph\n" + "status: generated-from-real-data\n" + f"updated_at: {datetime.now(timezone.utc).isoformat()}\n" + "tags: [{', '.join(tags)}]\n" + "---\n\n"
    link_block = "\n## Connected nodes\n\n" + " ".join(wiki(link) for link in unique_links) + "\n" if unique_links else ""
    path.write_text(frontmatter + f"# {title}\n\n" + body.strip() + "\n" + link_block, encoding="utf-8")


def main() -> int:
    rows = load_records()
    if not rows:
        raise SystemExit("No real records found; refusing to generate graph nodes.")
    KNOWLEDGE.mkdir(parents=True, exist_ok=True)
    source_records: dict[str, list[dict]] = defaultdict(list)
    topic_records: dict[str, list[dict]] = defaultdict(list)
    record_nodes: list[str] = []
    for i, row in enumerate(rows, 1):
        title = str(row.get("title", "Untitled")).strip()
        record = f"Record {i:03d} · {slug(title, f'Record-{i:03d}') }"
        record_nodes.append(record)
        src = source_name(row)
        source_records[src].append({"node": record, "row": row})
        for topic in topic_names(row):
            topic_records[topic].append({"node": record, "row": row})
        url = row.get("url", "")
        domain = urlparse(url).netloc or "unknown"
        body = f"> 실제 수집 레코드입니다. 원문: [{domain}]({url})\n\n**제목:** {title}\n\n{row.get('text', '').strip()}\n\n**출처:** {src}"
        write_note(KNOWLEDGE / "Records" / f"{slug(record)}.md", record, ["record", "real-data"], [src, *topic_names(row), "JARVIS Real Knowledge Index"], body)

    source_links: list[str] = []
    for src, items in sorted(source_records.items()):
        source_links.append(src)
        links = [item["node"] for item in items] + sorted({topic for item in items for topic in topic_names(item["row"])}) + ["JARVIS Real Knowledge Index"]
        body = f"실제 수집 레코드 **{len(items)}건**이 이 소스에 연결되어 있습니다.\n\n" + "\n".join(f"- {wiki(item['node'])}" for item in items)
        write_note(KNOWLEDGE / "Sources" / f"{slug(src)}.md", src, ["source", "real-data"], links, body)

    topic_links: list[str] = []
    for topic, items in sorted(topic_records.items()):
        topic_links.append(topic)
        links = [item["node"] for item in items] + sorted({source_name(item["row"]) for item in items}) + ["JARVIS Real Knowledge Index"]
        body = f"실제 수집 레코드 **{len(items)}건**이 이 주제에 연결되어 있습니다.\n\n" + "\n".join(f"- {wiki(item['node'])}" for item in items)
        write_note(KNOWLEDGE / "Topics" / f"{slug(topic)}.md", topic, ["topic", "real-data"], links, body)

    index_links = source_links + topic_links + record_nodes
    body = (
        "이 인덱스는 실제 수집 코퍼스에서 자동 생성되었습니다. Graph View에서 소스·주제·개별 레코드의 3단계 연결을 제공합니다.\n\n"
        f"- 실제 레코드: **{len(rows)}건**\n"
        f"- 소스 노드: **{len(source_links)}개**\n"
        f"- 주제 노드: **{len(topic_links)}개**\n\n"
        "### Source nodes\n\n" + "\n".join(f"- {wiki(link)}" for link in source_links) + "\n\n"
        "### Topic nodes\n\n" + "\n".join(f"- {wiki(link)}" for link in topic_links)
    )
    write_note(KNOWLEDGE / "JARVIS Real Knowledge Index.md", "JARVIS Real Knowledge Index", ["index", "real-data", "graph"], index_links, body)
    print(json.dumps({"records": len(rows), "source_nodes": len(source_links), "topic_nodes": len(topic_links), "output": str(KNOWLEDGE)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
