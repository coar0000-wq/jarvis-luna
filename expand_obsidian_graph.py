#!/usr/bin/env python3
"""Expand the Obsidian knowledge graph from real collected records only."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
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


# 파일 이름 상한. 리눅스는 파일명 255 바이트가 한계다. 한글은 UTF-8 로
# 한 자 3 바이트라 글자 수로 재면 넘길 수 있다. 바이트로도 잰다.
NAME_MAX_BYTES = 180


def slug(text: str, fallback: str = "Node") -> str:
    # NFC 로 맞춘다. 같은 글자가 조합형(NFD)과 완성형(NFC) 두 가지로 올 수
    # 있는데, 파일 이름과 링크가 서로 다른 형태면 눈으로는 같아 보여도
    # 못 찾는다. é 와 한글이 특히 그렇다.
    text = unicodedata.normalize("NFC", text)
    clean = SLUG_RE.sub("", text).strip().replace(" ", "-")[:70]
    while len(clean.encode("utf-8")) > NAME_MAX_BYTES and clean:
        clean = clean[:-1]
    return clean or fallback


# 해시 -> 처음 정한 이름. 회차가 바뀌어도 같은 이름을 쓰게 한다.
# 볼트 밖에 둔다. 노트가 아니라 장부라서 그래프에 끼면 안 된다.
LEDGER = Path(__file__).resolve().parent / "data" / "obsidian_record_names.json"
_LEDGER: dict[str, str] | None = None
_LEDGER_DIRTY: list[int] = []


def name_ledger() -> dict[str, str]:
    global _LEDGER
    if _LEDGER is None:
        try:
            _LEDGER = json.loads(LEDGER.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _LEDGER = {}
        if not isinstance(_LEDGER, dict):
            _LEDGER = {}
    return _LEDGER


def save_ledger() -> None:
    if not _LEDGER_DIRTY:
        return
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(
        json.dumps(name_ledger(), indent=0, ensure_ascii=False,
                   sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"이름 장부 {len(name_ledger()):,}건 저장 "
          f"(이번에 새로 정한 것 {len(_LEDGER_DIRTY):,}건)")


def seed_ledger_from_disk(folder: Path) -> int:
    """이미 디스크에 있는 노트 이름을 장부에 먼저 넣는다.

    장부가 없던 시절에 만들어진 노트가 대부분이다. 그것들을 먼저
    등록해야 오늘부터 이름이 바뀌지 않는다. 같은 해시가 여러 개면
    먼저 만난 것을 쓴다. 어느 쪽이든 하나로 고정되는 것이 중요하다.
    """
    led = name_ledger()
    added = 0
    for p in sorted(folder.rglob("Record-*.md")):
        m = re.match(r"Record-([0-9a-f]{10})--", p.stem)
        if not m:
            continue
        h = m.group(1)
        if h in led:
            continue
        # 파일 이름은 이미 slug 를 거친 형태다. 그대로 뒤에 붙이면
        # 다시 slug 를 통과해도 같은 파일 이름이 나온다.
        led[h] = f"Record {h} · " + p.stem[len(f"Record-{h}--"):]
        added += 1
    if added:
        _LEDGER_DIRTY.append(added)
    return added


def record_key(row: dict) -> str:
    """자료 하나를 가리키는 고정 이름.

    전에는 이랬다.
        record = f"Record {i:03d} · {slug(title)}"
    i 는 말뭉치 안의 순번이다. 말뭉치는 회차마다 늘어난다. 그러면 같은
    글이 회차마다 다른 번호를 받고, 파일 이름에 번호가 들어가니 회차마다
    새 파일이 하나 더 생긴다.

    실제로 같은 기사 하나가 볼트에 다섯 벌 있었다.
        Record-1199--J-beauty-pushes-overseas-as-Curél-and-Ci-Flavors-scale-gl.md
        Record-1205--...  Record-1216--...  Record-1221--...  Record-1224--...
    그런데 인덱스(Source--Google-Search.md)는 Record-1230 을 가리켰다.
    디스크에 없는 번호다. 그래서 끊어진 링크가 된다. 다섯 벌은 아무도
    안 가리키는 고아로 남는다. 회차마다 이 일이 되풀이된다.

    노트가 3만에서 7만 6천으로 분 것도 이것 때문이다. 새 자료가 그만큼
    들어온 게 아니라 같은 자료를 계속 다시 쓴 것이다.

    그래서 순번을 쓰지 않고 원문 URL 로 이름을 정한다. URL 이 없으면
    제목으로 정한다. 같은 글은 회차가 바뀌어도 같은 파일이라 안 끊어진다.

    앞 10자리 해시를 붙이는 것은 제목이 같은 다른 글을 가르기 위해서다.
    쌓인 고아는 scripts/clean_record_duplicates.py 가 따로 치운다.
    """
    url = str(row.get("url") or "").strip()
    title = unicodedata.normalize("NFC", str(row.get("title") or "Untitled").strip())
    h = hashlib.sha256((url or title).encode("utf-8")).hexdigest()[:10]
    name = f"Record {h} · {slug(title, 'Record')}"

    # 한 번 정한 이름은 계속 그 이름을 쓴다 (2026-09-13)
    #
    # 해시는 URL 로 정해지니 회차가 바뀌어도 같다. 그런데 제목은 바뀐다.
    # 정확히는 제목의 대소문자가 바뀐다. 수집기마다 출처 이름을 다르게
    # 적기 때문이다. 그래서 같은 해시에 이런 짝이 생겼다.
    #
    #   Record-018fb3abd4--Many-Shot-Jailbreaking.md
    #   Record-018fb3abd4--Many-shot-jailbreaking.md
    #   Record-056ae43ebf--...---TechRa.md
    #   Record-056ae43ebf--...---techra.md
    #
    # 30쌍 60개를 실측했다. 전부 같은 해시에 대소문자만 다르다.
    #
    # 윈도우는 이 둘을 같은 파일로 본다. 그래서 저장소에는 두 경로가
    # 등록되는데 디스크에는 하나뿐이다. 그러면 한쪽은 영원히 '수정됨'
    # 으로 남는다. 작업 폴더가 절대 깨끗해지지 않고 rebase 가 막힌다.
    # 오늘 푸시할 때 실제로 그것 때문에 막혀서 배관 명령으로 우회했다.
    #
    # 회차 안에서만 걸러서는 안 막힌다. 다음 회차는 기억이 없기 때문이다.
    # 그래서 해시별로 처음 정한 이름을 파일에 적어 두고 계속 그것을 쓴다.
    # 이름을 바꾸지 않으므로 이미 걸린 링크도 안 끊어진다.
    fixed = name_ledger().get(h)
    if fixed:
        return fixed
    name_ledger()[h] = name
    _LEDGER_DIRTY.append(1)
    return name


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
        ("투자은행·금융", ("investment bank", "equity", "bond", "credit", "portfolio",
                     "asset management", "macro outlook", "interest rate", "hedge",
                     "투자은행", "금융", "채권", "금리")),
        ("반도체·하드웨어", ("semiconductor", "wafer", "foundry", "lithography", "hbm",
                      "dram", "nand", "gpu", "chipset", "euv", "packaging",
                      "반도체", "웨이퍼", "파운드리")),
    ]

    topics = [name for name, terms in candidates if any(term in blob for term in terms)]

    # 수집기가 분야를 직접 적어 보낸 경우(기관 수집분) 그 값을 신뢰한다.
    # 제목만으로 추측하는 것보다 정확하고, 추측이 아니라 수집 시점의 사실이다.
    explicit = {
        "투자은행": "투자은행·금융",
        "반도체": "반도체·하드웨어",
        "AI연구소": "AI 에이전트",
        "데이터분석": "데이터·분석",
    }.get(str(row.get("category", "")).strip())
    if explicit and explicit not in topics:
        topics.append(explicit)
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
    # 장부가 비어 있으면 이미 있는 노트 이름부터 등록한다.
    # 그래야 오늘 이후로 같은 자료의 이름이 안 바뀐다.
    seeded = seed_ledger_from_disk(KNOWLEDGE)
    if seeded:
        print(f"기존 노트 {seeded:,}건의 이름을 장부에 등록했다")
    source_records: dict[str, list[dict]] = defaultdict(list)
    topic_records: dict[str, list[dict]] = defaultdict(list)
    org_records: dict[str, list[dict]] = defaultdict(list)
    record_nodes: list[str] = []
    seen_names: dict[str, str] = {}
    for row in rows:
        title = unicodedata.normalize("NFC", str(row.get("title", "Untitled")).strip())
        record = record_key(row)
        # 잘라낸 이름이 우연히 겹치면 뒤엣것이 앞엣것을 덮는다. 겹치면
        # 건너뛴다. 같은 자료면 어차피 같은 파일이라 잃는 것이 없다.
        #
        # 대소문자를 무시하고 본다. 윈도우는 ASML 과 Asml 을 같은 파일로
        # 본다. 저장소에는 둘 다 등록되고 체크아웃하면 하나가 다른 하나를
        # 덮는다. 그러면 작업 폴더가 영구히 dirty 가 되고 rebase 가 안 된다.
        # 실제로 그렇게 돼서 72개 파일이 되돌려도 계속 수정됨으로 남았다.
        fname = slug(record)
        key = fname.casefold()
        if key in seen_names and seen_names[key] != record:
            continue
        seen_names[key] = record
        record_nodes.append(record)
        src = source_name(row)
        source_records[src].append({"node": record, "row": row})
        for topic in topic_names(row):
            topic_records[topic].append({"node": record, "row": row})
        org = str(row.get("org", "")).strip()
        if org:
            org_records[f"기관 · {org}"].append({"node": record, "row": row})
        url = row.get("url", "")
        domain = urlparse(url).netloc or "unknown"
        body = f"> 실제 수집 레코드입니다. 원문: [{domain}]({url})\n\n**제목:** {title}\n\n{row.get('text', '').strip()}\n\n**출처:** {src}"
        org_link = [f"기관 · {org}"] if org else []
        write_note(KNOWLEDGE / "Records" / f"{slug(record)}.md", record, ["record", "real-data"], [src, *topic_names(row), *org_link, "JARVIS Real Knowledge Index"], body)

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

    org_links: list[str] = []
    for org_node, items in sorted(org_records.items()):
        org_links.append(org_node)
        links = ([item["node"] for item in items]
                 + sorted({t for item in items for t in topic_names(item["row"])})
                 + ["JARVIS Real Knowledge Index"])
        kinds: dict[str, int] = {}
        for item in items:
            k = str(item["row"].get("kind") or "기타")
            kinds[k] = kinds.get(k, 0) + 1
        breakdown = ", ".join(f"{k} {v}건" for k, v in sorted(kinds.items()))
        body = (f"실제 수집 레코드 **{len(items)}건**이 이 기관에 연결되어 있습니다. ({breakdown})\n\n"
                + "\n".join(f"- {wiki(item['node'])}" for item in items))
        write_note(KNOWLEDGE / "Orgs" / f"{slug(org_node)}.md", org_node,
                   ["org", "real-data"], links, body)

    index_links = source_links + topic_links + org_links + record_nodes
    body = (
        "이 인덱스는 실제 수집 코퍼스에서 자동 생성되었습니다. Graph View에서 소스·주제·개별 레코드의 3단계 연결을 제공합니다.\n\n"
        f"- 실제 레코드: **{len(rows)}건**\n"
        f"- 소스 노드: **{len(source_links)}개**\n"
        f"- 주제 노드: **{len(topic_links)}개**\n\n"
        "### Source nodes\n\n" + "\n".join(f"- {wiki(link)}" for link in source_links) + "\n\n"
        "### Topic nodes\n\n" + "\n".join(f"- {wiki(link)}" for link in topic_links)
    )
    write_note(KNOWLEDGE / "JARVIS Real Knowledge Index.md", "JARVIS Real Knowledge Index", ["index", "real-data", "graph"], index_links, body)
    save_ledger()
    print(json.dumps({"records": len(rows), "source_nodes": len(source_links), "topic_nodes": len(topic_links), "output": str(KNOWLEDGE)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
