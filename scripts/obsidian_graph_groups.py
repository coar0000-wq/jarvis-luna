"""옵시디언 그래프뷰 색 그룹을 정의하고, 색이 안 칠해지는 노트를 실측한다.

왜 만들었나 (2026-10-17)
  그래프뷰에 흰 점이 많다는 지적. 세어 보니 원인은 셋이었다.
    1. path:Personal 회색(#757575) 108개, path:Personal/Claude 회색청(#90a4ae) 142개.
       어두운 배경에서는 둘 다 흰 점으로 보인다. 사실상 '분류 안 됨' 이었다.
    2. Knowledge 바로 아래 인덱스 노트 5개는 어느 그룹에도 안 걸렸다 (진짜 흰 점).
    3. Concepts 257개가 한 색이라 다른 그룹(3~37개)과 크기가 안 맞았다.
  graph.json 을 손으로 고치면 다음 사람이 같은 자리를 다시 판다. 그래서 그룹을
  여기 한 곳에 적고, 볼트 전체를 옵시디언 검색 규칙대로 평가해 '어느 그룹에도
  안 걸린 노트 수' 와 '그룹별 노드 수' 를 남긴다. 0 이 아니면 --check 가 실패한다.

평가 규칙 (옵시디언 검색의 부분집합, 대소문자 무시)
  path:X   경로에 X 포함      file:X  파일 이름에 X 포함
  "X" / X  파일 이름 또는 본문에 X 포함
  공백 = AND,  OR,  ( ),  -부정
  색은 위에서부터 처음 맞는 그룹 하나만 칠해진다 (옵시디언과 같다).

사용
  python scripts/obsidian_graph_groups.py            # 측정만 (쓰지 않음)
  python scripts/obsidian_graph_groups.py --write    # graph.json 갱신
  python scripts/obsidian_graph_groups.py --check    # 흰 점이 있으면 exit 1
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VAULT = ROOT / "obsidian" / "JARVIS_LUNA"
GRAPH = VAULT / ".obsidian" / "graph.json"

# 그래프에서 빼는 것. 84k 자동 기록과 템플릿은 그리지 않는다.
SEARCH = "-path:Knowledge/Records -path:Personal/templates -path:.trash"

BEAUTY = ('"다이소" OR "화장품" OR "뷰티" OR "K-Beauty" OR "kbeauty" OR "올리브영" '
          'OR "Etsy" OR "스킨케어" OR "메이크업" OR "선크림" OR "전성분"')


def f(*names: str) -> str:
    return "(" + " OR ".join(f'file:"{n}"' for n in names) + ")"


# Personal 주제 묶음. 개념(Concepts) 노트도 이 묶음으로 나눈다.
# (이름, 파일 이름 패턴, 개인 노트 색, 개념 노트 색)
FAMILIES: list[tuple[str, tuple[str, ...], int, int]] = [
    ("데이터 라벨링", ("Annotation", "Labeling", "Label_Studio", "Labelbox", "Encord", "Augmentation",
                     "Roboflow"), 0xFFAB40, 0xE65100),
    ("비전 AI", ("Image", "Vision", "Detection", "Segmentation", "Face", "Localization"), 0xEEFF41, 0x9E9D24),
    ("AI 에이전트·스킬", ("Agent", "Skills", "MCP", "OpenClaw", "Plugin", "AI Models", "AI_Hub", "Voice_AI",
                       "Hermes"), 0xE040FB, 0x8E24AA),
    ("마케팅·SEO", ("SEO", "AEO", "Marketing", "Google", "Pinterest", "Content", "Market", "Canva",
                  "Color_Palette"), 0xFF6E40, 0xBF360C),
    ("클라우드·인프라", ("AWS", "NVIDIA", "Physical_AI"), 0x40C4FF, 0x0277BD),
]

# (이름, 쿼리, 색) — 순서가 곧 우선순위다.
# 색은 이웃 그룹끼리 색상과 밝기가 둘 다 갈리게 골랐다. 회색 계열과 파스텔
# (밝기 높고 채도 낮은 색)은 쓰지 않는다. 어두운 배경에서 흰 점과 구분이 안
# 됐던 것이 이번 문제의 절반이다. 그래서 low_contrast() 로 검사한다.
HEAD: list[tuple[str, str, int]] = [
    ("허브", 'file:"JARVIS Graph Hub" OR file:"JARVIS Brain" OR file:"JARVIS Dashboard Sync" '
            'OR file:README OR tag:#hub', 0xFFD54F),
    ("팀", "path:Brain/Teams OR path:Knowledge/Teams", 0xB388FF),
    ("데스크", "path:Brain/Desks", 0x26C6DA),
    ("상품·스토어", 'path:Brain/Products OR file:"Shopify Store"', 0x66BB6A),
    ("지식 주제", "path:Knowledge/Topics", 0x42A5F5),
    ("지식 기관", "path:Knowledge/Orgs", 0xFFA726),
    ("지식 출처·인덱스", "path:Knowledge", 0xFF7043),
    ("단계·브리핑", "path:Phases OR path:Briefings", 0xB5651D),
    ("화장품·다이소", f"path:Personal ({BEAUTY})", 0xFF4081),
    ("HNSD 연구", "path:Personal/Claude file:HNSD", 0x00BFA5),
    ("JARVIS 진화 로드맵", "path:Personal/Claude " + f("Level", "선언", "진화", "우주", "로드맵"), 0x7C4DFF),
    ("JARVIS 실행 기록", "path:Personal/Claude " + f("Phase", "Week", "Day", "진행", "완료", "Month", "20260",
                                                  "계획", "일정"), 0x536DFE),
    ("JARVIS 기술·영상 학습", "path:Personal/Claude " + f("YouTube", "youtube", "자동습득", "기술", "분석",
                                                     "Skills", "SKILL", "MCP", "프롬프트"), 0x18FFFF),
    ("Claude 프로젝트 기타", "path:Personal/Claude", 0x64FFDA),
]
TAIL_PERSONAL: list[tuple[str, str, int]] = [
    ("옵시디언·시스템 문서", "path:Personal " + f("Obsidian", "README", "JARVIS", "TEMPLATE", "Template",
                                               "METADATA", "GIT", "Notion", "Knowledge Base", "create a link",
                                               "Key Components", "Specific Use"), 0xB2FF59),
    ("학습 자료", "path:Personal " + f("Watchlist", "Academic", "Statistics", "Patent"), 0xC6A700),
    ("개인 기타", "path:Personal", 0xAD1457),
]


def low_contrast(rgb: int) -> bool:
    """흰 점처럼 보이는 색: 채도가 낮거나(회색) 너무 밝은 파스텔."""
    r, g, b = (rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255
    hi, lo = max(r, g, b), min(r, g, b)
    sat = 0 if hi == 0 else (hi - lo) / hi
    return sat < 0.35 or lo > 200


def personal_family_members(notes: list[dict]) -> dict[str, list[str]]:
    """개인 주제 노트를 묶음별로 나눈다. 앞의 그룹(화장품·시스템)에 먼저 걸린 것은 뺀다."""
    pre = [parse(q) for _, q, _ in HEAD]
    fams = [(name, parse("path:Personal " + f(*pats))) for name, pats, _, _ in FAMILIES]
    out: dict[str, list[str]] = {name: [] for name, *_ in FAMILIES}
    for n in notes:
        if not n["path"].startswith("personal/") or any(match(e, n) for e in pre):
            continue
        for name, e in fams:
            if match(e, n):
                out[name].append(Path(n["rel"]).stem)
                break
    return out


def build_groups(notes: list[dict]) -> list[tuple[str, str, int]]:
    """개념 노트는 '이 개념을 부르는 노트' 가 어느 묶음인지로 색을 정한다.

    전에는 Concepts 257개가 한 색이었다. 본문 키워드로 나누면 "Image_" 가
    라벨링 플랫폼 노트 이름(Encord_Image_Training...)에도 걸려 161개가 한 묶음이
    됐다. 부르는 노트의 실제 이름 목록으로 나누면 50~60개 단위로 갈린다.
    여러 묶음이 함께 부르는 개념은 적은 쪽(비전·에이전트·클라우드)을 먼저 준다.
    """
    members = personal_family_members(notes)
    groups = list(HEAD)
    for name, pats, color, _ in FAMILIES:
        groups.append((name, "path:Personal " + f(*pats), color))
    groups.extend(TAIL_PERSONAL)

    def refs(fam: str) -> str:
        names = members.get(fam) or []
        return "(" + " OR ".join(f'"{n}"' for n in names) + ")" if names else ""

    order = ["비전 AI", "AI 에이전트·스킬", "클라우드·인프라"]
    colors = {name: cc for name, _, _, cc in FAMILIES}
    for fam in order:
        r = refs(fam)
        if r:
            groups.append((f"개념 · {fam}", f"path:Concepts {r}", colors[fam]))
    lab, mkt = refs("데이터 라벨링"), refs("마케팅·SEO")
    if lab and mkt:
        groups.append(("개념 · 라벨링×마케팅 교차", f"path:Concepts {lab} {mkt}", 0x00897B))
    if mkt:
        groups.append(("개념 · 마케팅·SEO", f"path:Concepts {mkt}", colors["마케팅·SEO"]))
    if lab:
        groups.append(("개념 · 데이터 라벨링", f"path:Concepts {lab}", colors["데이터 라벨링"]))
    groups.append(("개념 · 기타", "path:Concepts", 0x43A047))
    return groups


# ---------------------------------------------------------------- 검색 평가기
TOKEN = re.compile(r'\s*(\(|\)|-(?=\S)|"[^"]*"|[^\s()"]+:"[^"]*"|[^\s()]+)')


def tokenize(q: str) -> list[str]:
    out, pos = [], 0
    q = q.strip()
    while pos < len(q):
        m = TOKEN.match(q, pos)
        if not m:
            raise ValueError(f"쿼리 해석 실패: {q[pos:]!r}")
        out.append(m.group(1))
        pos = m.end()
    return out


def parse(q: str):
    toks = tokenize(q)
    i = 0

    def peek():
        return toks[i] if i < len(toks) else None

    def or_expr():
        nonlocal i
        parts = [and_expr()]
        while peek() == "OR":
            i += 1
            parts.append(and_expr())
        return ("or", parts) if len(parts) > 1 else parts[0]

    def and_expr():
        parts = []
        while peek() not in (None, ")", "OR"):
            parts.append(unary())
        if not parts:
            raise ValueError(f"빈 항: {q!r}")
        return ("and", parts) if len(parts) > 1 else parts[0]

    def unary():
        nonlocal i
        t = peek()
        if t == "-":
            i += 1
            return ("not", unary())
        if t == "(":
            i += 1
            e = or_expr()
            if peek() != ")":
                raise ValueError(f"괄호 짝 안 맞음: {q!r}")
            i += 1
            return e
        i += 1
        if ":" in t and not t.startswith('"'):
            k, v = t.split(":", 1)
            return (k.lower(), v.strip('"').lower())
        return ("text", t.strip('"').lower())

    e = or_expr()
    if i != len(toks):
        raise ValueError(f"남은 토큰: {toks[i:]}")
    return e


def match(e, note: dict) -> bool:
    kind = e[0]
    if kind == "or":
        return any(match(x, note) for x in e[1])
    if kind == "and":
        return all(match(x, note) for x in e[1])
    if kind == "not":
        return not match(e[1], note)
    v = e[1]
    if kind == "path":
        return v in note["path"]
    if kind == "file":
        return v in note["name"]
    if kind == "tag":
        return v.lstrip("#") in note["tags"]
    if kind == "text":
        return v in note["name"] or v in note["text"]
    raise ValueError(f"지원 안 하는 연산자: {kind}")


def load_notes(vault: Path) -> list[dict]:
    notes = []
    for root, dirs, files in os.walk(vault):
        dirs[:] = [d for d in dirs if d not in (".obsidian", ".trash", ".git")]
        for fn in files:
            if not fn.endswith(".md"):
                continue
            p = Path(root) / fn
            rel = p.relative_to(vault).as_posix()
            text = p.read_text(encoding="utf-8", errors="ignore")
            notes.append({
                "path": rel.lower(),
                "rel": rel,
                "name": fn[:-3].lower(),
                "text": text.lower(),
                "tags": {t.lower() for t in re.findall(r"(?:^|\s)#([\w/가-힣-]+)", text)},
            })
    return notes


def measure(vault: Path = VAULT, groups=None, search: str = SEARCH) -> dict:
    flt = parse(search)
    notes = [n for n in load_notes(vault) if match(flt, n)]
    groups = groups if groups is not None else build_groups(notes)
    compiled = [(name, parse(q)) for name, q, _ in groups]
    counts = {name: 0 for name, _, _ in groups}
    white = []
    shown = 0
    for n in notes:
        if not match(flt, n):
            continue
        shown += 1
        for name, e in compiled:
            if match(e, n):
                counts[name] += 1
                break
        else:
            white.append(n["rel"])
    empty = [k for k, v in counts.items() if v == 0]
    pale = [name for name, _, c in groups if low_contrast(c)]
    return {"shown": shown, "white": len(white), "white_notes": sorted(white)[:50],
            "groups": counts, "empty_groups": empty,
            "largest_group": max(counts.values()) if counts else 0, "group_defs": groups, "pale_groups": pale}


def write_graph(groups, path: Path = GRAPH) -> None:
    g = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    g["search"] = SEARCH
    g["colorGroups"] = [{"query": q, "color": {"a": 1, "rgb": c}} for _, q, c in groups]
    path.write_text(json.dumps(g, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    r = measure()
    print(f"그래프 노트 {r['shown']}개 · 흰 점 {r['white']}개 · 그룹 {len(r['group_defs'])}개 · 최대 그룹 {r['largest_group']}개")
    for name, n in r["groups"].items():
        print(f"  {n:4d}  {name}")
    for w in r["white_notes"]:
        print(f"  [흰 점] {w}")
    if a.write:
        write_graph(r["group_defs"])
        print(f"graph.json 갱신: {GRAPH.relative_to(ROOT)}")
    if a.check and (r["white"] or r["empty_groups"] or r["pale_groups"]):
        print(f"::error::흰 점 {r['white']}개, 빈 그룹 {r['empty_groups']}, 흐린 색 {r['pale_groups']}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
