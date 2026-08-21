#!/usr/bin/env python3
"""Collect real public knowledge sources and mirror them into an Obsidian graph.

No synthetic records are generated. Missing credentials/configuration are recorded
as not_configured instead of being replaced with fabricated data.
"""
from __future__ import annotations

import html
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "knowledge"
VAULT_DIR = Path(os.getenv("OBSIDIAN_VAULT_DIR", str(ROOT / "obsidian" / "JARVIS_LUNA")))
NOTE_DIR = VAULT_DIR / "Knowledge"
TIMEOUT = 30


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "JARVIS-RealKnowledgeSync/1.0"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read()


def text(value: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def collect_arxiv(max_results: int = 10) -> dict[str, Any]:
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode({
        "search_query": "cat:cs.AI OR cat:cs.LG",
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    try:
        root = ET.fromstring(fetch(url))
        ns = {"a": "http://www.w3.org/2005/Atom"}
        items = []
        for entry in root.findall("a:entry", ns):
            items.append({
                "title": text(entry.findtext("a:title", namespaces=ns)),
                "summary": text(entry.findtext("a:summary", namespaces=ns)),
                "published": text(entry.findtext("a:published", namespaces=ns)),
                "url": next((x.attrib.get("href") for x in entry.findall("a:link", ns) if x.attrib.get("rel") == "alternate"), ""),
                "authors": [text(a.findtext("a:name", namespaces=ns)) for a in entry.findall("a:author", ns)],
                "source": "arXiv API",
            })
        return {"status": "ok", "source": "arXiv API", "url": url, "items": items}
    except Exception as exc:
        return {"status": "error", "source": "arXiv API", "url": url, "items": [], "error": str(exc)}


def collect_youtube() -> dict[str, Any]:
    channel_ids = [x.strip() for x in os.getenv("YOUTUBE_CHANNEL_IDS", "").split(",") if x.strip()]
    if not channel_ids:
        return {"status": "not_configured", "source": "YouTube channel RSS", "items": [], "error": "YOUTUBE_CHANNEL_IDS is not configured"}
    items = []
    errors = []
    ns = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
    for channel_id in channel_ids:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={urllib.parse.quote(channel_id)}"
        try:
            root = ET.fromstring(fetch(url))
            for entry in root.findall("atom:entry", ns):
                items.append({
                    "title": text(entry.findtext("atom:title", namespaces=ns)),
                    "published": text(entry.findtext("atom:published", namespaces=ns)),
                    "updated": text(entry.findtext("atom:updated", namespaces=ns)),
                    "url": next((x.attrib.get("href") for x in entry.findall("atom:link", ns)), ""),
                    "channel_id": channel_id,
                    "source": "YouTube channel RSS",
                })
        except Exception as exc:
            errors.append({"channel_id": channel_id, "error": str(exc)})
    result = {"status": "ok" if items else "error", "source": "YouTube channel RSS", "items": items}
    if errors:
        result["errors"] = errors
    return result


def collect_google() -> dict[str, Any]:
    key, cx = os.getenv("GOOGLE_CSE_API_KEY"), os.getenv("GOOGLE_CSE_ID")
    queries = [x.strip() for x in os.getenv("KNOWLEDGE_QUERIES", "AI agents 2026,medical AI research 2026,Mixture of Experts latest").split(",") if x.strip()]
    if not (key and cx):
        return {"status": "not_configured", "source": "Google Programmable Search JSON API", "items": [], "queries": queries, "error": "GOOGLE_CSE_API_KEY and GOOGLE_CSE_ID are not configured"}
    items = []
    errors = []
    for query in queries:
        url = "https://www.googleapis.com/customsearch/v1?" + urllib.parse.urlencode({"key": key, "cx": cx, "q": query, "num": 10})
        try:
            payload = json.loads(fetch(url).decode("utf-8"))
            for item in payload.get("items", []):
                items.append({"query": query, "title": item.get("title", ""), "snippet": item.get("snippet", ""), "url": item.get("link", ""), "source": "Google Programmable Search"})
        except Exception as exc:
            errors.append({"query": query, "error": str(exc)})
    result = {"status": "ok" if items else "error", "source": "Google Programmable Search JSON API", "queries": queries, "items": items}
    if errors:
        result["errors"] = errors
    return result


def safe_name(value: str) -> str:
    value = re.sub(r"[^\w\-가-힣 ]+", "", value, flags=re.UNICODE).strip()
    return re.sub(r"\s+", "-", value)[:90] or "untitled"


def write_note(title: str, source: str, status: str, items: list[dict[str, Any]], links: list[str]) -> str:
    NOTE_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{safe_name(title)}.md"
    lines = ["---", f"title: {json.dumps(title, ensure_ascii=False)}", f"source: {json.dumps(source, ensure_ascii=False)}", f"status: {status}", f"collected_at: {datetime.now(timezone.utc).isoformat()}", "tags: [jarvis, real-data, knowledge]", "---", f"# {title}", "", f"> 상태: **{status}**", "", "## 연결된 지식", ""]
    lines.extend(f"- [[{link}]]" for link in links)
    lines.extend(["", "## 수집 항목", ""])
    if not items:
        lines.append("- 실제 데이터가 없거나 필요한 인증·설정이 없어 수집하지 않았습니다.")
    for item in items:
        item_title = text(str(item.get("title", "untitled")))
        url = item.get("url", "")
        lines.append(f"### {item_title}")
        if url:
            lines.append(f"- 원문: [{url}]({url})")
        for key in ("published", "updated", "query", "channel_id", "authors", "summary", "snippet"):
            value = item.get(key)
            if value:
                lines.append(f"- {key}: {text(', '.join(value) if isinstance(value, list) else str(value))}")
        lines.append("")
    (NOTE_DIR / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return filename[:-3]


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    collected = {"collected_at": datetime.now(timezone.utc).isoformat(), "sources": {"arxiv": collect_arxiv(), "youtube": collect_youtube(), "google": collect_google()}}
    (DATA_DIR / "real_sources.json").write_text(json.dumps(collected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    notes = {}
    notes["arxiv"] = write_note("JARVIS Real arXiv Papers", "arXiv API", collected["sources"]["arxiv"]["status"], collected["sources"]["arxiv"]["items"], ["JARVIS Real Knowledge Index"])
    notes["youtube"] = write_note("JARVIS Real YouTube", "YouTube channel RSS", collected["sources"]["youtube"]["status"], collected["sources"]["youtube"]["items"], ["JARVIS Real Knowledge Index"])
    notes["google"] = write_note("JARVIS Real Google Search", "Google Programmable Search JSON API", collected["sources"]["google"]["status"], collected["sources"]["google"]["items"], ["JARVIS Real Knowledge Index"])
    index = ["---", 'title: "JARVIS Real Knowledge Index"', "tags: [jarvis, knowledge-graph, real-data]", f"updated: {collected['collected_at']}", "---", "# JARVIS Real Knowledge Index", "", "> 이 인덱스는 실제 원문 API에서 수집된 항목만 연결합니다. 인증·설정이 없는 소스는 임의의 샘플 데이터로 대체하지 않습니다.", "", "## 소스", "", f"- [[{notes['arxiv']}]]", f"- [[{notes['youtube']}]]", f"- [[{notes['google']}]]", "", "## 데이터 원천", "", "- JSON 원본: `data/knowledge/real_sources.json`", "- Graph View: 이 문서와 연결된 세 개의 소스 노트를 기준으로 확인", ""]
    (NOTE_DIR / "JARVIS Real Knowledge Index.md").write_text("\n".join(index), encoding="utf-8")
    print(json.dumps({"data_file": str(DATA_DIR / "real_sources.json"), "notes_dir": str(NOTE_DIR), "statuses": {k: v["status"] for k, v in collected["sources"].items()}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
