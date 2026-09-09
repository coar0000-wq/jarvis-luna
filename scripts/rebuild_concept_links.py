#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""없는 노트를 가리키는 대괄호를 정리한다.

무엇이 문제였나
  볼트 노트 59,121개 중 미해결 위키링크가 11,948개다. 그런데 그게
  고르게 퍼져 있지 않았다. 전부 Personal 폴더의 노트 87개에서 나온다.
  Knowledge 폴더 58,000여 개에서는 한 건도 안 나온다.

  그 87개 중 50개가 *_Graph.md 다. 영상을 보고 정리한 노트인데,
  불릿 라벨을 전부 대괄호로 감쌌다.

      ### Key Characteristics
      - [[Autonomy]]: Works independently
      - [[Perception]]: Understands environment
      ### Agent vs. Chatbot
      [[Differences]]:
      - [[Agent]]: Takes actions, persistent memory
      - [[Chatbot]]: Responds to queries only

  [[Differences]] 는 개념이 아니다. 그 문단의 소제목이다.
  서로 다른 대상 7,811종 중 6,563종은 딱 한 노트에서만 불린다.
  한 번 불리고 가리키는 노트도 없는 링크는 링크가 아니다.
  그래프뷰에는 아무 데도 안 닿는 흐린 점 7,811개가 뜬다.

무엇을 하나
  전부 이으면 없는 노트 7,811개를 만들어야 한다. 전부 지우면 진짜
  개념까지 사라진다. 그래서 조건을 둔다. 조건은 아래 세 가지를
  모두 만족해야 하고, 판단 결과는 전건 파일에 남긴다.

    1. 서로 다른 노트 3개 이상에서 불린다
       한 문서 안에서 스무 번 불리는 것은 그 문서의 소제목이다.
    2. 제외어 목록에 없다
       Key Takeaways, Best Practices 처럼 문서 뼈대에 붙는 말이다.
       35개 노트에 Key Takeaways 절이 있다는 뜻일 뿐 개념이 아니다.
    3. 두 낱말 이상이거나, 약어이거나, 낱말 안에 대문자가 있다
       Medical Imaging·Active Learning·Bounding Box 는 남고
       Scalability·Consistency·Monitoring 은 빠진다.
       YOLO·SEO·ROI 는 약어라 남고 PyTorch·OpenCV 는 안쪽 대문자로 남는다.

  통과하면 Concepts/ 에 개념 노트를 만들고 그 개념을 부르는 노트를
  역링크로 적는다. 못 통과하면 [[X]] 를 **X** 로 되돌린다.
  글자는 그대로 남고 그래프에서 유령 점만 사라진다.

  Phase-N-... 은 따로 본다. 36종을 11개 노트가 부르는데 계획된 허브가
  안 만들어진 것이다. 이것은 구조 층이라 허브 노트를 만든다.

되돌리기
  --apply 를 주지 않으면 아무것도 안 고치고 보고서만 쓴다.
  먼저 그렇게 돌려 data/obsidian_concept_rules.json 을 보고 판단한다.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "data" / "obsidian_concept_rules.json"

WIKILINK = re.compile(r"\[\[([^\]|#]+)((?:#[^\]|]+)?)(\|[^\]]+)?\]\]")
PHASE = re.compile(r"^Phase-\d+-")

MIN_NOTES = 3

# 문서 뼈대에 붙는 말. 35개 노트에 "Key Takeaways" 절이 있다는 것은
# 그 노트들이 서로 이어져야 한다는 뜻이 아니다. 같은 서식을 썼을 뿐이다.
구조어 = {
    "key takeaways", "takeaways", "summary", "overview", "introduction",
    "conclusion", "conclusions", "use case", "use cases", "example",
    "examples", "case study", "case studies", "best practices",
    "next steps", "steps", "benefits", "features", "advanced features",
    "advantages", "disadvantages", "pros", "cons", "differences",
    "comparison", "requirements", "goal", "goals", "tips", "notes",
    "results", "result", "challenges", "solution", "solutions",
    "definition", "concept", "structure", "process", "method", "methods",
    "approach", "techniques", "types", "tools", "resources", "references",
    "guidelines", "templates", "applications", "practical applications",
    "practical application", "industry applications", "key characteristics",
    "key strengths", "timeline", "documentation", "real examples",
    "youtube resources", "learning path", "capabilities", "impact",
    "input", "output", "parameters", "configuration", "links", "video",
}

# 일반 품질·상태를 가리키는 말. 두 낱말이어서 3번 조건은 통과하지만
# 어느 문서에나 붙는다. 이어봐야 서로 관계없는 문서가 묶인다.
속성어 = {
    "cost efficiency", "cost effective", "cost optimization",
    "cost reduction", "high accuracy", "high performance", "low latency",
    "large scale", "full control", "long-term", "short-term", "real-time",
    "data-driven", "mobile friendly", "open source", "regular updates",
    "continuous improvement", "quality control", "quality assurance",
    "quality metrics", "quality improvement", "quality assessment",
    "quality management", "quality checks", "quality content",
    "content quality", "user satisfaction", "user experience",
    "performance metrics", "performance optimization", "problem solving",
    "decision making", "progress tracking", "monitor progress",
    "monitor performance", "error handling", "team management",
    "project management", "workflow management", "thought leadership",
}

# 안쪽 대문자가 없는 제품·도구 이름. 3번 조건으로는 못 걸러서 따로 적는다.
도구명 = {
    "labelbox", "roboflow", "snorkel", "yolo", "hugging face",
    "pascal voc", "coco", "onnx", "keras", "colab", "streamlit",
}

ACRONYM = re.compile(r"^[A-Z0-9][A-Z0-9\-]{1,6}$")
INNER_CAPS = re.compile(r"^[A-Z][a-z]+[A-Z]")


def looks_like_concept(target: str) -> tuple[bool, str]:
    """조건 2·3 을 본다. 왜 그렇게 판단했는지 사유도 같이 돌려준다."""
    low = target.casefold().strip()
    if low in 구조어:
        return False, "문서 뼈대에 붙는 말"
    if low in 속성어:
        return False, "어느 문서에나 붙는 일반 속성어"
    if low in 도구명:
        return True, "제품·도구 이름"
    words = target.split()
    if len(words) >= 2:
        return True, f"{len(words)}낱말 구"
    if ACRONYM.match(target):
        return True, "약어"
    if INNER_CAPS.search(target):
        return True, "낱말 안에 대문자 (제품명)"
    if not target.isascii():
        return True, "한글·비영문 고유 표현"
    return False, "영어 한 낱말 일반어"


def scan(vault: Path) -> tuple[dict, set]:
    """볼트를 한 번 훑어 미해결 대상과 그것을 부르는 노트를 모은다."""
    notes = sorted(vault.rglob("*.md"))
    stems = {n.stem.casefold() for n in notes}
    callers: dict[str, set] = collections.defaultdict(set)
    for n in notes:
        try:
            text = n.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in WIKILINK.finditer(text):
            t = m.group(1).strip().replace("\\", "/").split("/")[-1]
            if t.lower().endswith(".md"):
                t = t[:-3]
            if t.casefold() not in stems:
                callers[t].add(n.relative_to(vault).as_posix())
    return callers, stems


def decide(callers: dict) -> dict:
    """대상마다 승격·강등·Phase허브 중 무엇인지 정한다."""
    out = {}
    for target, srcs in callers.items():
        if PHASE.match(target):
            out[target] = {"판정": "phase허브", "사유": "계획된 구조 허브",
                           "노트수": len(srcs), "부른노트": sorted(srcs)}
            continue
        ok, why = looks_like_concept(target)
        if len(srcs) < MIN_NOTES:
            out[target] = {"판정": "평문", "노트수": len(srcs),
                           "사유": f"노트 {len(srcs)}개에서만 불림 (기준 {MIN_NOTES})",
                           "부른노트": sorted(srcs)}
        elif not ok:
            out[target] = {"판정": "평문", "노트수": len(srcs), "사유": why,
                           "부른노트": sorted(srcs)}
        else:
            out[target] = {"판정": "개념", "노트수": len(srcs), "사유": why,
                           "부른노트": sorted(srcs)}
    return out


def concept_note(target: str, info: dict) -> str:
    srcs = "\n".join(f"- [[{Path(s).stem}]]" for s in info["부른노트"])
    return (f"# {target}\n\n"
            f"> 노트 {info['노트수']}개가 이 개념을 부른다. "
            f"판단 근거: {info['사유']}.\n"
            f"> scripts/rebuild_concept_links.py 가 만들었다. "
            f"내용은 사람이 채운다.\n\n"
            f"## 이 개념을 부르는 노트\n\n{srcs}\n")


def phase_note(target: str, info: dict) -> str:
    srcs = "\n".join(f"- [[{Path(s).stem}]]" for s in info["부른노트"])
    return (f"# {target}\n\n"
            f"> 계획에는 있었으나 만들어지지 않은 허브였다. "
            f"노트 {info['노트수']}개가 여기를 가리킨다.\n"
            f"> scripts/rebuild_concept_links.py 가 자리만 만들었다. "
            f"내용은 사람이 채운다.\n\n"
            f"## 이 단계를 가리키는 노트\n\n{srcs}\n")


def rewrite(vault: Path, demote: set) -> tuple[int, int]:
    """평문으로 내릴 대상만 [[X]] -> **X** 로 바꾼다."""
    files, links = 0, 0
    for n in sorted(vault.rglob("*.md")):
        try:
            text = n.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "[[" not in text:
            continue
        hit = [0]

        def sub(m):
            t = m.group(1).strip().replace("\\", "/").split("/")[-1]
            if t.lower().endswith(".md"):
                t = t[:-3]
            if t not in demote:
                return m.group(0)
            hit[0] += 1
            # 별칭이 있으면 사람이 읽으라고 쓴 말이니 그것을 남긴다.
            shown = (m.group(3) or "")[1:].strip() or m.group(1).strip()
            return f"**{shown}**"

        new = WIKILINK.sub(sub, text)
        if hit[0]:
            n.write_text(new, encoding="utf-8")
            files += 1
            links += hit[0]
    return files, links


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=str(ROOT / "obsidian" / "JARVIS_LUNA"),
                    type=Path)
    ap.add_argument("--apply", action="store_true",
                    help="실제로 고친다. 안 주면 보고서만 쓴다.")
    ap.add_argument("--min-notes", type=int, default=MIN_NOTES)
    args = ap.parse_args()

    globals()["MIN_NOTES"] = args.min_notes

    if not args.vault.exists():
        print(f"볼트가 없다: {args.vault}")
        return 2

    callers, stems = scan(args.vault)
    total = sum(len(s) for s in callers.values())
    verdict = decide(callers)

    개념 = {t: v for t, v in verdict.items() if v["판정"] == "개념"}
    평문 = {t: v for t, v in verdict.items() if v["판정"] == "평문"}
    phase = {t: v for t, v in verdict.items() if v["판정"] == "phase허브"}

    print(f"볼트 노트 {len(stems):,}개 · 미해결 대상 {len(callers):,}종")
    print(f"  개념 노트로  {len(개념):5,}종")
    print(f"  평문으로     {len(평문):5,}종")
    print(f"  Phase 허브   {len(phase):5,}종")

    made = []
    if args.apply:
        cdir = args.vault / "Concepts"
        pdir = args.vault / "Phases"
        for name, info, d, fn in (
                [(t, v, cdir, concept_note) for t, v in 개념.items()]
                + [(t, v, pdir, phase_note) for t, v in phase.items()]):
            d.mkdir(parents=True, exist_ok=True)
            safe = re.sub(r'[\\/:*?"<>|]', "-", name)
            f = d / f"{safe}.md"
            if not f.exists():
                f.write_text(fn(name, info), encoding="utf-8")
                made.append(f.relative_to(args.vault).as_posix())
        files, links = rewrite(args.vault, set(평문))
        print(f"  만든 노트 {len(made):,}개 · 고친 노트 {files:,}개 · "
              f"평문으로 바꾼 링크 {links:,}개")
    else:
        files = links = 0
        print("  (--apply 없이 돌아 아무것도 고치지 않았다)")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        "생성": datetime.now(timezone.utc).isoformat(),
        "만든이": "scripts/rebuild_concept_links.py",
        "규칙": [
            f"서로 다른 노트 {MIN_NOTES}개 이상에서 불릴 것",
            "문서 뼈대·일반 속성어 목록에 없을 것",
            "두 낱말 이상이거나 약어이거나 낱말 안에 대문자가 있을 것",
        ],
        "볼트_노트수": len(stems),
        "미해결_링크수": total,
        "미해결_대상수": len(callers),
        "개념노트": len(개념),
        "평문전환": len(평문),
        "phase허브": len(phase),
        "적용함": bool(args.apply),
        "만든_노트": made,
        "고친_노트수": files,
        "평문으로_바꾼_링크수": links,
        "판정": {t: {k: v for k, v in d.items() if k != "부른노트"}
               for t, d in sorted(verdict.items())},
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  보고서 -> {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
