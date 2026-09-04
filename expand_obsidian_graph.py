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
    """수집 자료를 주제로 분류한다.

    2026-09-04 확장. 이전에는 주제가 5개뿐이라 18,174개 중 11,346개가
    기본값 "AI Research" 로 떨어져 그래프에서 한 덩어리로 뭉쳤다.
    실제 제목 4,000개를 표본 조사해 빈출 주제를 뽑았다.
      beauty 1367 · shopify 1286 · ecommerce 533 · tiktok 427
      korean 398 · makeup 380 · skincare 318 · business 238

    분류는 제목과 본문의 키워드 근거로만 한다. 추측하지 않는다.
    아무 키워드도 안 걸리면 "미분류" 로 둔다. 억지로 AI Research 에
    몰아넣지 않는다. 미분류가 쌓이면 그것 자체가 분류를 늘리라는 신호다.
    """
    blob = (row.get("title", "") + " " + row.get("text", "")).lower()

    candidates = [
        # 사업 영역
        ("경영·전략", ("business", "strategy", "revenue", "profit", "pricing",
                    "margin", "startup", "founder", "경영", "전략", "매출", "수익")),
        ("마케팅·광고", ("marketing", "advertis", "campaign", "seo", "influencer",
                     "viral", "brand awareness", "conversion", "마케팅", "광고")),
        ("이커머스·Shopify", ("shopify", "ecommerce", "e-commerce", "commerce",
                          "dropship", "storefront", "checkout", "이커머스", "쇼피파이")),
        ("뷰티·스킨케어", ("beauty", "skincare", "skin care", "cosmetic", "makeup",
                      "serum", "sunscreen", "toner", "k-beauty", "뷰티", "화장품", "스킨케어")),
        ("소셜·콘텐츠", ("tiktok", "youtube", "instagram", "shorts", "creator",
                     "content", "video", "소셜", "콘텐츠")),
        ("물류·통관", ("shipping", "logistics", "customs", "tariff", "duty",
                    "fulfillment", "물류", "통관", "관세", "배송")),
        ("법률·규제", ("regulat", "compliance", "fda", "mocra", "legal", "law",
                    "gdpr", "privacy policy", "license", "법률", "규제", "컴플라이언스")),

        # 기술 영역
        ("AI 에이전트", ("agent", "agentic", "tool use", "workflow", "orchestrat",
                     "에이전트")),
        ("LLM·언어모델", ("llm", "language model", "gpt", "claude", "transformer",
                      "prompt", "rag", "언어모델")),
        ("모델 라우팅·MoE", ("routing", "mixture-of-experts", "moe", "expert",
                        "라우팅")),
        ("머신러닝 연구", ("neural", "training", "reinforcement", "benchmark",
                     "fine-tun", "dataset", "머신러닝", "학습")),
        ("컴퓨터 비전", ("vision", "image", "diffusion", "segmentation", "text-to-image",
                    "visual", "비전", "이미지")),
        ("로보틱스", ("robot", "manipulation", "embodied", "autonomous vehicle",
                  "drone", "로봇", "자율주행")),
        ("음성·오디오", ("speech", "audio", "voice", "asr", "tts", "음성", "오디오")),
        ("보안·프라이버시", ("security", "attack", "adversarial", "jailbreak",
                      "prompt injection", "vulnerab", "보안")),
        ("인프라·클라우드", ("aws", "cloud", "kubernetes", "serverless", "infra",
                      "deployment", "인프라", "클라우드")),
        ("데이터·분석", ("analytics", "data pipeline", "labeling", "annotation",
                    "big data", "데이터", "분석")),
        ("의료·바이오", ("medical", "clinical", "health", "patient", "bio",
                    "diagnos", "의료", "임상")),
        ("과학·수학", ("physics", "chemistry", "math", "theorem", "quantum",
                   "plasma", "수학", "물리")),
    ]

    topics = [name for name, terms in candidates if any(term in blob for term in terms)]
    return topics or ["미분류"]


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
    frontmatter = "---\n" + f'title: "{title.replace(chr(34), chr(39))}"\n' + "type: knowledge-graph\n" + "status: generated-from-real-data\n" + f"updated_at: {datetime.now(timezone.utc).isoformat()}\n" + f"tags: [{', '.join(tags)}]\n" + "---\n\n"
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
