#!/usr/bin/env python3
"""Build evidence-only frontmatter relation hubs for the JARVIS_LUNA vault.

Dry-run and evidence-only are defaults. Only exact, unique topic/source/org/team
frontmatter declarations produce links. Source hashes, field/value and resolved
targets are persisted in Navigation/_local/typed-relations.json, locally excluded
from git before apply. No title/tag inference or folder/cluster/root bridges.
Orphans and disconnected components are legitimate. --legacy-inference explicitly
restores the previous overlay. --prune-generated backs up and removes only owned
stale generated files in Navigation; private pages also require --include-private
and verified git exclusion. Original/unknown notes remain unchanged. Symlinks are
refused. Standard library only.
"""
from __future__ import annotations

import argparse
import collections
import dataclasses
import hashlib
import json
import math
import os
import posixpath
import re
import subprocess
import sys
import time
import unicodedata
import urllib.parse
from pathlib import Path
from typing import Iterable

GENERATOR = "connect_obsidian_orphans"
GENERATOR_VERSION = 2
LEDGER_DIR = "_local"
LEDGER_NAME = "typed-relations.json"
MARKER = f"generated_by: {GENERATOR}"
ROOT_NAME = "JARVIS Orphan Navigation Hub"
PRIVATE_ROOT_NAME = "JARVIS Private Orphan Navigation Hub"
PRIVATE_DIR = "_private"
DEFAULT_NAV_DIR = "Navigation"
DEFAULT_PRIVATE_PREFIXES = ("Personal",)
DEFAULT_MAX_LINKS = 500

TIER_DIRECT = "direct-metadata"
TIER_TAG = "inferred-tag"
TIER_TITLE = "inferred-title"
TIER_NAV = "navigation-only"
TIER_ORDER = (TIER_DIRECT, TIER_TAG, TIER_TITLE, TIER_NAV)

TIER_TEXT = {
    TIER_DIRECT: (
        "직접 연결 (메타데이터 선언)",
        "각 노트 자신의 frontmatter 값이 아래 대상 노트 이름과 정확히 일치합니다. "
        "내용을 읽고 내린 판단이 아니라 노트가 스스로 선언한 값입니다.",
    ),
    TIER_TAG: (
        "추정 연결 (공유 태그)",
        "frontmatter 에 같은 태그가 선언되어 있다는 사실만 사용했습니다. "
        "내용상 관련성은 보증하지 않습니다.",
    ),
    TIER_TITLE: (
        "추정 연결 (제목 속 이름 포함)",
        "노트 제목에 대상 노트의 이름이 포함되어 있어 추정했습니다. "
        "확신이 낮으니 사람이 검토하세요. 근거로 인용하지 마세요.",
    ),
    TIER_NAV: (
        "탐색 전용 (주제 관계 없음)",
        "같은 폴더에 있다는 사실 외에 알려진 관계가 없습니다. "
        "이 허브는 파일에 도달할 수 있게만 하며 주제적 관련성을 주장하지 않습니다.",
    ),
}

# frontmatter field -> (family, entity folder, filename prefix stripped before matching)
DIRECT_FIELDS = {
    "topics": ("topic", "Knowledge/Topics", ""),
    "topic": ("topic", "Knowledge/Topics", ""),
    "org": ("org", "Knowledge/Orgs", "기관--"),
    "source": ("source", "Knowledge/Sources", "Source--"),
    "team": ("team", "Knowledge/Teams", "팀 · "),
}
FAMILY_LABEL = {
    "topic": "Topic",
    "org": "Org",
    "source": "Source",
    "team": "Team",
    "tag": "Tag",
    "title": "Title",
    "folder": "Folder",
    "cluster": "Cluster",
}
TITLE_TARGET_FOLDERS = (
    "Concepts",
    "Phases",
    "Knowledge/Topics",
    "Knowledge/Orgs",
    "Knowledge/Teams",
    "Knowledge/Sources",
)
GENERIC_TAGS = {
    "record", "real-data", "knowledge-graph", "generated", "note", "notes", "todo",
    "navigation", "orphan-connector",
}
TITLE_MAX_GROUP = 60   # title-mention targets hitting more orphans than this are too generic
TITLE_STOPLIST = {"미분류", "index", "readme", "untitled", "template", "templates"}
TRUE_VALUES = {"true", "yes", "y", "1", "on"}

# --------------------------------------------------------------------------- fs helpers


def _long(path: Path | str) -> str:
    """Windows long-path safe string."""
    p = os.path.abspath(str(path))
    if os.name == "nt" and not p.startswith("\\\\?\\"):
        if p.startswith("\\\\"):
            return "\\\\?\\UNC\\" + p[2:]
        return "\\\\?\\" + p
    return p


def read_text(path: Path | str) -> str:
    with open(_long(path), "rb") as fh:
        raw = fh.read()
    return raw.decode("utf-8-sig", errors="replace")


def nkey(s: str) -> str:
    """Case/Unicode-normalised comparison key (Obsidian links are case-insensitive)."""
    return unicodedata.normalize("NFC", s).casefold()


def fuzzy_key(s: str) -> str:
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFC", s).casefold())


def tokens(s: str) -> list[str]:
    return re.findall(r"[^\W_]+", unicodedata.normalize("NFC", s).casefold())


# --------------------------------------------------------------------------- parsing

_FM_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
_FENCE_RE = re.compile(
    r"(?ms)^[ \t]*(```|~~~).*?^[ \t]*\1[ \t]*$|^[ \t]*(?:```|~~~).*\Z"
)
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
_WIKI_RE = re.compile(r"(!?)\[\[([^\[\]\n]+?)\]\]")
_MDLINK_RE = re.compile(
    r"(!?)\[(?:[^\[\]\n]|\\.)*\]\((<[^<>\n]+>|[^()\s]*(?:\([^()\s]*\)[^()\s]*)*)(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'))?\)"
)
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")


def _unquote_scalar(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def _parse_value(v: str):
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1]
        items = []
        for m in re.finditer(r'\s*(?:"([^"]*)"|\'([^\']*)\'|([^,]+))', inner):
            item = next(g for g in m.groups() if g is not None).strip()
            if item:
                items.append(item)
        return items
    return _unquote_scalar(v)


def parse_frontmatter(text: str) -> tuple[dict, str, str]:
    """Return (fields, raw frontmatter text, body)."""
    if text.startswith("\ufeff"):
        text = text[1:]
    m = _FM_RE.match(text)
    if not m:
        return {}, "", text
    fm: dict = {}
    cur = None
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s*-\s+(.*)$", line)
        if item and cur is not None and (line.startswith((" ", "\t", "-"))):
            if not isinstance(fm.get(cur), list):
                fm[cur] = [fm[cur]] if fm.get(cur) else []
            fm[cur].append(_unquote_scalar(item.group(1)))
            continue
        kv = re.match(r"^([^\s:#][^:]*):\s*(.*)$", line)
        if kv and not line.startswith((" ", "\t")):
            cur = kv.group(1).strip()
            val = kv.group(2).strip()
            fm[cur] = _parse_value(val) if val else []
    return fm, m.group(1), text[m.end():]


def as_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v if str(x).strip()]
    return [str(v)] if str(v).strip() else []


def strip_code(body: str) -> str:
    return _INLINE_CODE_RE.sub("", _FENCE_RE.sub("", body))


@dataclasses.dataclass(frozen=True)
class RawLink:
    target: str      # target path/name with alias/heading removed (not yet resolved)
    md_style: bool   # True for [text](dest) links
    embed: bool


def _cut_fragment(t: str) -> str:
    return re.split(r"[#^]", t, maxsplit=1)[0]


def extract_links(text: str) -> list[RawLink]:
    """All wikilinks, embeds and Markdown links outside code, incl. frontmatter."""
    fm, fm_raw, body = parse_frontmatter(text)
    scan = fm_raw + "\n" + strip_code(body)
    links: list[RawLink] = []
    for m in _WIKI_RE.finditer(scan):
        inner = re.split(r"\\?\|", m.group(2), maxsplit=1)[0].rstrip("\\")
        links.append(RawLink(_cut_fragment(inner).strip(), False, bool(m.group(1))))
    for m in _MDLINK_RE.finditer(scan):
        dest = m.group(2).strip()
        if dest.startswith("<") and dest.endswith(">"):
            dest = dest[1:-1]
        if not dest or dest.startswith("#") or dest.startswith("//") or _SCHEME_RE.match(dest):
            continue
        dest = dest.split("#", 1)[0].split("?", 1)[0]  # cut before unquoting (%23 stays a name char)
        links.append(RawLink(urllib.parse.unquote(dest).strip(), True, bool(m.group(1))))
    return links


def canvas_links(text: str) -> list[RawLink]:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    out = []
    for node in data.get("nodes", []) if isinstance(data, dict) else []:
        f = node.get("file") if isinstance(node, dict) else None
        if isinstance(f, str) and f:
            out.append(RawLink(_cut_fragment(f).strip(), True, False))
    return out


# --------------------------------------------------------------------------- vault model


@dataclasses.dataclass
class Node:
    rel: str                     # vault-relative POSIX path (as on disk)
    is_note: bool                # markdown or canvas (can contain links)
    generated: bool = False
    private: bool = False
    title: str = ""
    fm: dict = dataclasses.field(default_factory=dict)
    links: list = dataclasses.field(default_factory=list)
    sha256: str = ""

    @property
    def ext(self) -> str:
        return posixpath.splitext(self.rel)[1].lower()

    @property
    def stem(self) -> str:
        base = posixpath.basename(self.rel)
        return base[:-3] if base.lower().endswith(".md") else base

    @property
    def folder(self) -> str:
        return posixpath.dirname(self.rel)


def link_target_str(rel: str) -> str:
    return rel[:-3] if rel.lower().endswith(".md") else rel


class Resolver:
    """Obsidian-like link resolution: case-insensitive, path suffix, name only."""

    def __init__(self, rels: Iterable[str]):
        self.by_full: dict[str, list[str]] = collections.defaultdict(list)
        self.by_name: dict[str, list[str]] = collections.defaultdict(list)
        for rel in rels:
            low = nkey(rel)
            self.by_full[low].append(rel)
            base = posixpath.basename(low)
            self.by_name[base].append(rel)
            if low.endswith(".md"):
                self.by_full[low[:-3]].append(rel)
                self.by_name[base[:-3]].append(rel)
        self.ambiguous = 0

    def resolve(self, src_rel: str, link: RawLink) -> str | None:
        """Return target rel, ``""`` for a same-note link, or None if unresolved."""
        t = link.target.replace("\\", "/") if link.md_style else link.target
        t = t.strip()
        if not t:
            return ""
        absolute = t.startswith("/")
        t = t.lstrip("/")
        key = nkey(t)
        cands: list[str] = []
        if link.md_style and not absolute:
            joined = posixpath.normpath(posixpath.join(posixpath.dirname(src_rel), t))
            if not joined.startswith(".."):
                cands = self.by_full.get(nkey(joined), [])
        if not cands and (absolute or "/" in key):
            cands = self.by_full.get(key, [])
        if not cands and "/" in key:
            base = posixpath.basename(key)
            cands = [
                r for r in self.by_name.get(base, [])
                if nkey(r).endswith("/" + key) or nkey(link_target_str(r)).endswith("/" + key)
            ]
        elif not cands:
            cands = self.by_name.get(key, [])
        cands = sorted(set(cands))
        if not cands:
            return None
        if len(cands) > 1:
            self.ambiguous += 1
            src_dir = posixpath.dirname(src_rel)
            same = [c for c in cands if posixpath.dirname(c) == src_dir]
            pool = same or cands
            return min(pool, key=lambda c: (c.count("/"), nkey(c)))
        return cands[0]


def scan_vault(vault: Path, nav_dir: str, private_prefixes: tuple[str, ...]) -> tuple[list[Node], dict]:
    stats = {"decode_errors": 0}
    nodes: list[Node] = []
    prefixes = tuple(nkey(p.strip("/")) for p in private_prefixes)
    nav_low = nkey(nav_dir)
    for dirpath, dirnames, filenames in os.walk(_long(vault)):
        for entry in dirnames + filenames:
            if not entry.startswith(".") and Path(os.path.join(dirpath, entry)).is_symlink():
                raise ValueError("symlinks are refused")
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for fn in sorted(filenames):
            if fn.startswith("."):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, _long(vault)).replace(os.sep, "/")
            if rel == f"{nav_dir}/{LEDGER_DIR}/{LEDGER_NAME}":
                continue  # local audit data is not an Obsidian graph node
            ext = posixpath.splitext(fn)[1].lower()
            node = Node(rel=rel, is_note=ext in (".md", ".canvas"))
            first = nkey(rel.split("/", 1)[0])
            node.private = first in prefixes if "/" in rel else False
            if node.is_note:
                with open(full, "rb") as fh:
                    raw = fh.read()
                node.sha256 = hashlib.sha256(raw).hexdigest()
                try:
                    text = raw.decode("utf-8-sig")
                except UnicodeDecodeError:
                    stats["decode_errors"] += 1
                    text = raw.decode("utf-8-sig", errors="replace")
                in_nav = nkey(rel).startswith(nav_low + "/")
                if ext == ".md":
                    fm, fm_raw, _ = parse_frontmatter(text)
                    if in_nav and fm.get("generated_by") == GENERATOR:
                        node.generated = True
                    node.fm = fm
                    node.title = str(fm.get("title") or "").strip() if not isinstance(fm.get("title"), list) else ""
                    fl = {k: v for k, v in fm.items()}
                    if any(str(fl.get(k, "")).strip().lower() in TRUE_VALUES for k in ("private", "personal")):
                        node.private = True
                    if str(fl.get("publish", "")).strip().lower() == "false":
                        node.private = True
                    if any(nkey(t).lstrip("#") in ("private", "personal") for t in as_list(fm.get("tags"))):
                        node.private = True
                    node.links = extract_links(text)
                else:
                    node.links = canvas_links(text)
            nodes.append(node)
    return nodes, stats


def build_edges(nodes: list[Node], include_generated: bool) -> tuple[dict, dict, dict]:
    """Return (degree map, info) over active nodes; edges are undirected for degree."""
    active = [n for n in nodes if include_generated or not n.generated]
    resolver = Resolver(n.rel for n in active)
    degree = {n.rel: 0 for n in active}
    seen: set[tuple[str, str]] = set()
    unresolved = 0
    total_links = 0
    for n in active:
        for lk in n.links:
            total_links += 1
            tgt = resolver.resolve(n.rel, lk)
            if tgt is None:
                unresolved += 1
                continue
            if tgt == "" or tgt == n.rel:
                continue
            pair = (n.rel, tgt)
            if pair in seen:
                continue
            seen.add(pair)
            degree[n.rel] += 1
            degree[tgt] += 1
    parent = {r: r for r in degree}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in seen:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    comp = {r: find(r) for r in degree}
    sizes = collections.Counter(comp.values())
    largest = max(sizes.values()) if sizes else 0
    info = {
        "components": len(sizes),
        "largest_component": largest,
        "nodes_outside_largest_component": len(degree) - largest,
        "link_occurrences": total_links,
        "unique_edges": len(seen),
        "unresolved_links": unresolved,
        "ambiguous_links": resolver.ambiguous,
    }
    return degree, info, comp


def parse_graph_filters(vault: Path) -> dict:
    out = {"exists": False, "exclude_prefixes": [], "search": "", "showOrphans": None,
           "showAttachments": None, "hideUnresolved": None, "showTags": None}
    gp = vault / ".obsidian" / "graph.json"
    if not gp.is_file():
        return out
    try:
        data = json.loads(read_text(gp))
    except ValueError:
        return out
    out["exists"] = True
    out["search"] = str(data.get("search", ""))
    for k in ("showOrphans", "showAttachments", "hideUnresolved", "showTags"):
        out[k] = data.get(k)
    for tok in out["search"].split():
        if tok.startswith("-path:"):
            out["exclude_prefixes"].append(tok[len("-path:"):].strip('"').strip("/"))
    return out


def under_any(rel: str, prefixes: list[str]) -> bool:
    low = nkey(rel)
    return any(low.startswith(nkey(p) + "/") for p in prefixes if p)


# --------------------------------------------------------------------------- planning


@dataclasses.dataclass
class Group:
    tier: str
    family: str
    name: str                 # human name (entity / tag / folder)
    private: bool
    basis: str                # which metadata was used
    targets: list = dataclasses.field(default_factory=list)   # existing notes the hub points at
    members: list = dataclasses.field(default_factory=list)   # orphan rels
    file_stem: str = ""
    why: str = ""             # overrides the generic tier explanation when set


def _safe_name(s: str, limit: int = 90) -> str:
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r'[\\/:*?"<>|#^\[\]\r\n\t]+', "-", s).strip(" .-")
    return (s[:limit]).strip(" .-") or "untitled"


def clean_tags(fm: dict) -> list[str]:
    out = []
    for t in as_list(fm.get("tags")) + as_list(fm.get("tag")):
        t = t.strip().lstrip("#").strip()
        if not t or re.search(r"[{}()'\"$,]", t) or " " in t:
            continue
        if nkey(t) in GENERIC_TAGS:
            continue
        out.append(t)
    return sorted(set(out), key=nkey)


def _title_of(n: Node) -> str:
    return n.title or n.stem


def build_entity_index(nodes: list[Node]) -> dict:
    """family -> fuzzy key -> [entity rel]. Entities are existing non-private notes."""
    idx: dict[str, dict[str, list[str]]] = collections.defaultdict(lambda: collections.defaultdict(list))
    folders = {(fam, nkey(folder), prefix) for fam, folder, prefix in DIRECT_FIELDS.values()}
    for n in nodes:
        if n.generated or n.private or n.ext != ".md":
            continue
        for fam, folder, prefix in folders:
            if nkey(n.folder) == folder:
                stem = n.stem
                if prefix and nkey(stem).startswith(nkey(prefix)):
                    stem = stem[len(prefix):]
                idx[fam][fuzzy_key(stem)].append(n.rel)
    return idx


def build_title_targets(nodes: list[Node]) -> tuple[dict, list[Node]]:
    """token-first index of (tokens, node) for title-mention inference."""
    folders = tuple(nkey(f) for f in TITLE_TARGET_FOLDERS)
    idx: dict[str, list] = collections.defaultdict(list)
    pool = []
    for n in nodes:
        if n.generated or n.ext != ".md" or nkey(n.folder) not in folders:
            continue
        name = re.sub(r"^(Source--|기관--|팀\s*·\s*|Source\s*·\s*)", "", n.stem)
        toks = tokens(name)
        joined = "".join(toks)
        if not toks or joined in {fuzzy_key(s) for s in TITLE_STOPLIST}:
            continue
        ascii_only = joined.isascii()
        if len(joined) < (6 if ascii_only else 3):
            continue
        idx[toks[0]].append((tuple(toks), n))
        pool.append(n)
    return idx, pool


def find_title_match(orphan: Node, title_idx: dict) -> Node | None:
    toks = tokens(_title_of(orphan)) + ["\0"] + tokens(orphan.stem)
    best = None
    best_score = (0, 0)
    for i, tk in enumerate(toks):
        for tt, target in title_idx.get(tk, ()):
            if target.rel == orphan.rel:
                continue
            if target.private and not orphan.private:
                continue
            if tuple(toks[i:i + len(tt)]) == tt:
                score = (len(tt), sum(len(x) for x in tt))
                if score > best_score or (score == best_score and best is not None and target.rel < best.rel):
                    best, best_score = target, score
    return best


def classify(orphans: list[Node], nodes: list[Node]) -> list[Group]:
    entity_idx = build_entity_index(nodes)
    title_idx, _ = build_title_targets(nodes)
    notes_by_stem: dict[str, list[Node]] = collections.defaultdict(list)
    for n in nodes:
        if not n.generated and n.ext == ".md":
            notes_by_stem[fuzzy_key(n.stem)].append(n)

    groups: dict[tuple, Group] = {}

    def add(tier, family, name, private, basis, member, targets=()):
        key = (tier, family, nkey(name), private)
        g = groups.get(key)
        if g is None:
            g = groups[key] = Group(tier, family, name, private, basis, list(targets))
        g.members.append(member)

    remaining: list[Node] = []
    for o in orphans:
        placed = False
        if o.is_note and o.ext == ".md":
            hits: list[tuple[str, str, str, str]] = []   # family, entity rel, entity name, field
            for field in ("topics", "topic"):
                for val in as_list(o.fm.get(field)):
                    ents = entity_idx["topic"].get(fuzzy_key(val), [])
                    if len(ents) == 1:
                        hits.append(("topic", ents[0], posixpath.basename(link_target_str(ents[0])), field))
            if not hits:
                for field in ("org", "source"):
                    fam = DIRECT_FIELDS[field][0]
                    for val in as_list(o.fm.get(field)):
                        ents = entity_idx[fam].get(fuzzy_key(val), [])
                        if len(ents) == 1:
                            hits.append((fam, ents[0], posixpath.basename(link_target_str(ents[0])), field))
            for fam, ent, ent_name, field in hits:
                add(TIER_DIRECT, fam, ent_name, o.private, f"frontmatter `{field}`", o.rel, [ent])
                placed = True
        if not placed:
            remaining.append(o)

    # tag tier: shared declared tags among the still-unplaced orphans
    tag_members: dict[tuple[str, bool], list[Node]] = collections.defaultdict(list)
    node_tags: dict[str, list[str]] = {}
    for o in remaining:
        if o.ext != ".md":
            continue
        tags = clean_tags(o.fm)
        node_tags[o.rel] = tags
        for t in tags:
            tag_members[(nkey(t), o.private)].append(o)
    still: list[Node] = []
    for o in remaining:
        choices = [(len(tag_members[(nkey(t), o.private)]), nkey(t), t) for t in node_tags.get(o.rel, [])
                   if len(tag_members[(nkey(t), o.private)]) >= 2]
        if choices:
            _, _, tag = min(choices)
            add(TIER_TAG, "tag", tag, o.private, "frontmatter `tags`", o.rel)
        else:
            still.append(o)

    # title tier
    last: list[Node] = []
    title_hits: dict[str, list[tuple[Node, Node]]] = collections.defaultdict(list)
    for o in still:
        target = None
        if o.is_note and o.ext == ".md":
            target = find_title_match(o, title_idx)
        elif not o.is_note or o.ext == ".canvas":
            cands = [c for c in notes_by_stem.get(fuzzy_key(posixpath.splitext(o.stem)[0]), [])
                     if c.rel != o.rel and (o.private or not c.private)]
            if len(cands) == 1:
                target = cands[0]
        if target is not None:
            title_hits[target.rel].append((o, target))
        else:
            last.append(o)
    # a name that matches very many orphans is too generic to say anything: fall back to folder
    for trel, pairs in sorted(title_hits.items()):
        if len(pairs) > TITLE_MAX_GROUP:
            last.extend(o for o, _ in pairs)
            continue
        for o, target in pairs:
            add(TIER_TITLE, "title", posixpath.basename(link_target_str(target.rel)), o.private,
                "note title / file name", o.rel, [target.rel])

    for o in last:
        folder = o.folder or "(vault root)"
        add(TIER_NAV, "folder", folder, o.private, "folder location only", o.rel)

    out = sorted(groups.values(), key=lambda g: (g.private, TIER_ORDER.index(g.tier), g.family, nkey(g.name)))
    used: set[str] = set()
    for g in out:
        raw = f"{FAMILY_LABEL[g.family]} · {g.name.replace('/', ' › ')}"
        stem = _safe_name(raw)
        if stem != raw or nkey(stem) in used:
            stem = f"{_safe_name(raw, 80)}-{hashlib.sha1((g.tier + g.family + g.name).encode('utf-8')).hexdigest()[:6]}"
        used.add(nkey(stem))
        g.file_stem = stem
        g.members = sorted(set(g.members), key=nkey)
    return out


# --------------------------------------------------------------------------- rendering


def make_link(rel: str, label: str | None = None) -> str:
    """Link that resolves to exactly `rel` (always path-qualified)."""
    target = link_target_str(rel)
    label = (label if label is not None else posixpath.basename(target)).replace("[", "(").replace("]", ")")
    label = re.sub(r"[|\r\n]+", " ", label).strip() or "link"
    odd = (re.search(r"[\[\]#^|\r\n\\]", target) is not None
           or any(seg != seg.strip() or seg.endswith(".") for seg in target.split("/")))
    if not odd:
        return f"[[{target}|{label}]]"
    return f"[{label}]({urllib.parse.quote(rel, safe='/')})"


def yaml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def frontmatter(title: str, extra: dict) -> str:
    lines = ["---", f"title: {yaml_str(title)}", "type: navigation-hub", MARKER,
             f"generator_version: {GENERATOR_VERSION}"]
    for k, v in extra.items():
        if isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        elif isinstance(v, int):
            lines.append(f"{k}: {v}")
        else:
            lines.append(f"{k}: {yaml_str(str(v))}")
    lines.append("---")
    return "\n".join(lines)


DISCLAIMER = ("> 자동 생성된 탐색용 노트입니다 (`scripts/connect_obsidian_orphans.py`). "
              "원본 노트는 수정하지 않았고, 이 링크는 증거나 출처 관계가 아닙니다.")


def render_member(rel: str, nodes_by_rel: dict[str, Node]) -> str:
    n = nodes_by_rel[rel]
    suffix = "" if n.is_note else " (attachment)"
    label = n.stem
    return f"- {make_link(rel, label)}{suffix}"


@dataclasses.dataclass
class PlannedFile:
    rel: str            # vault-relative path of the generated file
    content: str
    private: bool
    role: str           # root | group | bucket | retired


def plan_files(groups: list[Group], nodes: list[Node], nav_dir: str, max_links: int,
               existing_generated: dict[str, bool]) -> list[PlannedFile]:
    nodes_by_rel = {n.rel: n for n in nodes}
    files: dict[str, PlannedFile] = {}

    def path_for(private: bool, folder: str, stem: str) -> str:
        parts = [nav_dir] + ([PRIVATE_DIR] if private else []) + ([folder] if folder else []) + [stem + ".md"]
        return "/".join(parts)

    roots = {p: path_for(p, "", PRIVATE_ROOT_NAME if p else ROOT_NAME) for p in (False, True)}
    group_pages: dict[bool, list[tuple[Group, str]]] = {False: [], True: []}

    for g in groups:
        folder = {TIER_DIRECT: "Direct", TIER_TAG: "Inferred", TIER_TITLE: "Inferred", TIER_NAV: "Folders"}[g.tier]
        page = path_for(g.private, folder, g.file_stem)
        label, why = TIER_TEXT[g.tier]
        why = g.why or why
        extra = {"relation_tier": g.tier, "relation_basis": g.basis, "private": g.private,
                 "member_count": len(g.members)}
        head = [frontmatter(f"{FAMILY_LABEL[g.family]} · {g.name}", extra), "",
                f"# {FAMILY_LABEL[g.family]} · {g.name}", "", DISCLAIMER, "",
                f"- 연결 성격: **{label}**", f"- 설명: {why}", f"- 근거: {g.basis}",
                f"- 상위: {make_link(roots[g.private], 'Orphan Navigation Hub')}"]
        for t in g.targets:
            head.append(f"- 대상 노트: {make_link(t)}")
        if g.private:
            head.append("- 공개 금지: 이 노트는 개인 영역을 포함하므로 git 에서 제외되어야 합니다.")
        head.append("")
        if len(g.members) <= max_links:
            body = [f"## 구성원 ({len(g.members)})", ""] + [render_member(r, nodes_by_rel) for r in g.members]
            files[page] = PlannedFile(page, "\n".join(head + body) + "\n", g.private, "group")
        else:
            nb = max(2, math.ceil(len(g.members) / (max_links * 0.8)))
            buckets: dict[int, list[str]] = collections.defaultdict(list)
            for r in g.members:
                buckets[int(hashlib.sha1(nkey(r).encode("utf-8")).hexdigest()[:8], 16) % nb].append(r)
            body = [f"## 구성원 페이지 ({len(g.members)}개 노트 / {nb} 페이지)", ""]
            for b in range(nb):
                bpage = path_for(g.private, "Buckets", f"{g.file_stem} · p{b + 1:03d}")
                body.append(f"- {make_link(bpage, f'p{b + 1:03d}')} ({len(buckets[b])})")
                bh = [frontmatter(f"{FAMILY_LABEL[g.family]} · {g.name} · p{b + 1:03d}",
                                  {**extra, "member_count": len(buckets[b])}), "",
                      f"# {FAMILY_LABEL[g.family]} · {g.name} · p{b + 1:03d}", "", DISCLAIMER, "",
                      f"- 연결 성격: **{label}**", f"- 상위: {make_link(page, g.file_stem)}", "",
                      f"## 구성원 ({len(buckets[b])})", ""]
                bh += [render_member(r, nodes_by_rel) for r in sorted(buckets[b], key=nkey)]
                files[bpage] = PlannedFile(bpage, "\n".join(bh) + "\n", g.private, "bucket")
            files[page] = PlannedFile(page, "\n".join(head + body) + "\n", g.private, "group")
        group_pages[g.private].append((g, page))

    for private in (False, True):
        has_existing = any(p == private for p in existing_generated.values())
        if not group_pages[private] and not has_existing:
            continue
        title = "JARVIS 비공개 고아 노트 탐색 허브" if private else "JARVIS 고아 노트 탐색 허브"
        lines = [frontmatter(title, {"relation_tier": "navigation", "private": private}), "", f"# {title}", "",
                 DISCLAIMER, ""]
        if private:
            lines += ["> 개인 영역 노트용 허브입니다. 이 폴더는 git 에서 제외(비공개)되어야 합니다.", "",
                      f"- 공개 허브: {make_link(roots[False], 'Orphan Navigation Hub')}", ""]
        else:
            top = sorted(n.rel for n in nodes if "/" not in n.rel and n.ext == ".md" and not n.generated and not n.private)
            lines += ["## 기존 진입점", ""] + [f"- {make_link(r)}" for r in top] + [""]
        by_tier: dict[str, list[tuple[Group, str]]] = collections.defaultdict(list)
        for g, page in group_pages[private]:
            by_tier[g.tier].append((g, page))
        for tier in TIER_ORDER:
            if not by_tier[tier]:
                continue
            label, why = TIER_TEXT[tier]
            total = sum(len(g.members) for g, _ in by_tier[tier])
            lines += [f"## {label} · {total}", "", why, ""]
            for g, page in by_tier[tier]:
                lines.append(f"- {make_link(page, f'{FAMILY_LABEL[g.family]} · {g.name}')} ({len(g.members)})")
            lines.append("")
        files[roots[private]] = PlannedFile(roots[private], "\n".join(lines).rstrip() + "\n", private, "root")


    # existing generated files that are no longer planned become retired stubs (never deleted)
    for rel, private in sorted(existing_generated.items()):
        if rel in files:
            continue
        if roots[private] not in files:
            continue
        stub = [frontmatter(posixpath.basename(rel)[:-3] + " (retired)", {"relation_tier": "navigation",
                "private": private, "retired": True}), "",
                "# retired navigation page", "", DISCLAIMER, "",
                "이 페이지는 더 이상 쓰이지 않습니다 (구성원이 없거나 이름이 바뀜). 삭제하지 않고 남겨 두었습니다.", "",
                f"- 상위: {make_link(roots[private], 'Orphan Navigation Hub')}"]
        files[rel] = PlannedFile(rel, "\n".join(stub) + "\n", private, "retired")
    return sorted(files.values(), key=lambda f: f.rel)


# --------------------------------------------------------------------------- git helpers


def git(args: list[str], cwd: Path) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None


def git_root(vault: Path) -> Path | None:
    r = git(["rev-parse", "--show-toplevel"], vault)
    if r and r.returncode == 0 and r.stdout.strip():
        return Path(r.stdout.strip())
    return None


def git_ignored(root: Path, path_abs: Path) -> bool:
    r = git(["check-ignore", "-q", "--no-index", str(path_abs)], root)
    return bool(r and r.returncode == 0)


def add_local_exclude(root: Path, pattern: str) -> bool:
    r = git(["rev-parse", "--git-path", "info/exclude"], root)
    if not r or r.returncode != 0:
        return False
    p = Path(r.stdout.strip())
    if not p.is_absolute():
        p = root / p
    refuse_symlinks(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    cur = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
    if pattern in cur.splitlines():
        return True
    with open(p, "a", encoding="utf-8", newline="\n") as fh:
        if cur and not cur.endswith("\n"):
            fh.write("\n")
        fh.write("# connect_obsidian_orphans: private navigation hubs must never be published\n" + pattern + "\n")
    return True


# --------------------------------------------------------------------------- main logic


def analyse_legacy(vault: Path, nav_dir: str, private_prefixes: tuple[str, ...], max_links: int,
            include_private: bool, private_safe: bool) -> dict:
    """Read-only analysis and plan. Returns a dict with summary + internals."""
    nodes, scan_stats = scan_vault(vault, nav_dir, private_prefixes)
    baseline = [n for n in nodes if not n.generated]
    degree, info, _ = build_edges(baseline, include_generated=False)
    graph = parse_graph_filters(vault)
    orphans = [n for n in baseline if degree.get(n.rel, 0) == 0]
    orphans.sort(key=lambda n: nkey(n.rel))
    existing_generated = {n.rel: n.rel.startswith(f"{nav_dir}/{PRIVATE_DIR}/")
                          for n in nodes if n.generated}
    groups = classify(orphans, baseline)
    non_generated_paths = {nkey(n.rel) for n in baseline}
    orphan_by_rel = {n.rel: n for n in orphans}
    baseline_by_rel = {n.rel: n for n in baseline}

    def plan_pass(grps: list[Group]) -> dict:
        files = plan_files(grps, baseline, nav_dir, max_links, existing_generated)
        # collision check: never overwrite a file that exists and is not ours
        collisions = [f.rel for f in files if nkey(f.rel) in non_generated_paths]
        write_files = [f for f in files if f.rel not in collisions
                       and (include_private and private_safe or not f.private)]
        skipped_private = [f for f in files if f.private and f not in write_files and f.rel not in collisions]
        # projected graph: re-parse generated content with the same extractor
        proj_nodes = list(baseline)
        for f in write_files:
            proj_nodes.append(Node(rel=f.rel, is_note=True, generated=False, private=f.private,
                                   links=extract_links(f.content)))
        pdeg, pinfo, pcomp = build_edges(proj_nodes, include_generated=True)
        return {"files": files, "collisions": collisions, "write_files": write_files,
                "skipped_private": skipped_private, "pdeg": pdeg, "pinfo": pinfo, "pcomp": pcomp}

    first = plan_pass(groups)
    # Bridge pass: already-linked clusters that stay cut off from the main graph get ONE navigation-only
    # link to a representative member, so the whole vault ends up in a single connected component.
    sizes = collections.Counter(first["pcomp"].values())
    main_root = max(sizes, key=lambda r: (sizes[r], r)) if sizes else None
    clusters: dict[str, list[str]] = collections.defaultdict(list)
    for rel, root in first["pcomp"].items():
        if root != main_root and rel in baseline_by_rel:
            clusters[root].append(rel)
    bridges = {False: [], True: []}
    for members in clusters.values():
        members.sort(key=lambda r: (baseline_by_rel[r].private, nkey(r)))
        rep = members[0]
        bridges[baseline_by_rel[rep].private].append(rep)
    bridge_count = sum(len(v) for v in bridges.values())
    if bridge_count:
        for private, reps in bridges.items():
            if reps:
                groups.append(Group(
                    TIER_NAV, "cluster", "Disconnected clusters", private,
                    "graph structure only (one representative per cluster)", [], sorted(set(reps), key=nkey),
                    "Disconnected clusters",
                    "이미 서로 링크되어 있으나 주 그래프와 떨어진 노트 묶음입니다. 묶음마다 대표 노트 하나만 "
                    "연결했으며, 주제 관계를 주장하지 않습니다."))
        groups.sort(key=lambda g: (g.private, TIER_ORDER.index(g.tier), g.family, nkey(g.name)))
        first = plan_pass(groups)
    files, collisions = first["files"], first["collisions"]
    write_files, skipped_private = first["write_files"], first["skipped_private"]
    pdeg, pinfo = first["pdeg"], first["pinfo"]
    projected_orphans = [r for r in orphan_by_rel if pdeg.get(r, 0) == 0]
    generated_orphans = [f.rel for f in write_files if pdeg.get(f.rel, 0) == 0]

    def counts(sel: Iterable[Node]) -> dict:
        sel = list(sel)
        return {"total": len(sel), "notes": sum(1 for n in sel if n.is_note),
                "attachments": sum(1 for n in sel if not n.is_note),
                "private": sum(1 for n in sel if n.private)}

    visible = [n for n in orphans if not under_any(n.rel, graph["exclude_prefixes"])]
    by_top = collections.Counter((n.rel.split("/", 1)[0] if "/" in n.rel else "(vault root)") for n in orphans)
    tier_nodes: dict[str, set] = collections.defaultdict(set)
    tier_private: dict[str, set] = collections.defaultdict(set)
    for g in (g for g in groups if g.family != "cluster"):
        tier_nodes[g.tier].update(g.members)
        if g.private:
            tier_private[g.tier].update(g.members)
    primary = {t: len(tier_nodes[t]) for t in TIER_ORDER}
    # a node placed by direct tier is not double counted for other tiers
    summary = {
        "vault": str(vault),
        "nodes": {"total": len(baseline), "markdown_notes": sum(1 for n in baseline if n.ext == ".md"),
                  "canvas": sum(1 for n in baseline if n.ext == ".canvas"),
                  "attachments_non_note": sum(1 for n in baseline if not n.is_note),
                  "existing_generated_hubs_excluded": len(nodes) - len(baseline),
                  "private_nodes": sum(1 for n in baseline if n.private),
                  "decode_errors": scan_stats["decode_errors"]},
        "links": info,
        "orphans_baseline": {**counts(orphans), "by_top_folder": dict(by_top.most_common()),
                             "graph_visible_total": len(visible),
                             "hidden_by_graph_filter": len(orphans) - len(visible),
                             "graph_filter_exclusions": graph["exclude_prefixes"]},
        "graph_json": {k: graph[k] for k in ("exists", "search", "showOrphans", "showAttachments",
                                             "hideUnresolved", "showTags")},
        "tiers_primary_nodes": primary,
        "tiers_private_nodes": {t: len(tier_private[t]) for t in TIER_ORDER},
        "cluster_bridges": bridge_count,
        "groups": {"total": len(groups), "private": sum(1 for g in groups if g.private),
                   "by_tier": dict(collections.Counter(g.tier for g in groups))},
        "files": {"planned_total": len(files), "to_write": len(write_files),
                  "private_planned": sum(1 for f in files if f.private),
                  "private_skipped": len(skipped_private),
                  "by_role": dict(collections.Counter(f.role for f in write_files)),
                  "collisions_refused": len(collisions)},
        "projected": {"orphans_remaining": len(projected_orphans),
                      "orphans_remaining_private": sum(1 for r in projected_orphans if orphan_by_rel[r].private),
                      "generated_hubs_unreachable": len(generated_orphans),
                      "attachment_orphans_remaining": sum(1 for r in projected_orphans if not orphan_by_rel[r].is_note),
                      "unresolved_links_after": pinfo["unresolved_links"],
                      "components": pinfo["components"],
                      "largest_component": pinfo["largest_component"],
                      "nodes_outside_largest_component": pinfo["nodes_outside_largest_component"]},
    }
    return {"summary": summary, "files": files, "write_files": write_files, "nodes": nodes,
            "orphans": orphans, "groups": groups, "collisions": collisions}


def refuse_symlinks(p: Path) -> None:
    for part in (p, *p.parents):
        if part.is_symlink():
            raise ValueError("symlinks are refused")


def owned_file(p: Path) -> bool:
    refuse_symlinks(p)
    if not p.is_file():
        return False
    if p.suffix.lower() == ".md":
        fm, _, _ = parse_frontmatter(read_text(p))
        return fm.get("generated_by") == GENERATOR
    if p.suffix.lower() == ".json":
        try:
            obj = json.loads(read_text(p))
            return isinstance(obj, dict) and obj.get("generated_by") == GENERATOR
        except ValueError:
            return False
    return False


def declared_relations(nodes: list[Node]) -> tuple[list[dict], int]:
    """Exact, unique declared names or full vault paths only; never fuzzy/title inference."""
    baseline = [n for n in nodes if not n.generated and n.ext == ".md"]
    index = collections.defaultdict(lambda: collections.defaultdict(set))
    for n in baseline:
        for family, folder, prefix in set(DIRECT_FIELDS.values()):
            if n.folder != folder:
                continue
            for name in (n.rel, link_target_str(n.rel), n.stem,
                         n.stem[len(prefix):] if prefix and n.stem.startswith(prefix) else n.stem):
                index[family][unicodedata.normalize("NFC", name)].add(n.rel)
    by_rel = {n.rel: n for n in baseline}
    records, unresolved = [], 0
    for n in baseline:
        for field, (family, _, _) in DIRECT_FIELDS.items():
            for value in as_list(n.fm.get(field)):
                key = value
                if key.startswith("[[") and key.endswith("]]"):
                    key = key[2:-2]  # no alias/fragment guesses
                targets = index[family].get(unicodedata.normalize("NFC", key), set())
                if len(targets) != 1 or n.rel in targets:
                    unresolved += 1
                    continue
                target = next(iter(targets))
                record = {"type": "declared-" + family, "source_path": n.rel,
                          "source_sha256": n.sha256, "field": field, "value": value,
                          "resolved_target": target, "target_sha256": by_rel[target].sha256,
                          "private": n.private or by_rel[target].private}
                record["id"] = hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
                records.append(record)
    records = list({r["id"]: r for r in records}.values())
    return sorted(records, key=lambda r: (r["source_path"], r["field"], r["value"])), unresolved


def analyse(vault: Path, nav_dir: str, private_prefixes: tuple[str, ...], max_links: int,
            include_private: bool, private_safe: bool, legacy_inference: bool = False,
            prune_generated: bool = False) -> dict:
    if legacy_inference:
        result = analyse_legacy(vault, nav_dir, private_prefixes, max_links, include_private, private_safe)
        result["summary"]["relation_mode"] = "legacy-inference"
        if prune_generated:
            result["write_files"] = [f for f in result["write_files"] if f.role != "retired"]
        result["prune_files"] = stale_owned(vault, nav_dir, result["nodes"], result["write_files"],
                                           include_private and private_safe) if prune_generated else []
        return result
    nodes, stats = scan_vault(vault, nav_dir, private_prefixes)
    baseline = [n for n in nodes if not n.generated]
    degree, info, _ = build_edges(baseline, False)
    orphans = [n for n in baseline if not degree[n.rel]]
    records, unresolved = declared_relations(baseline)
    allowed = [r for r in records if not r["private"] or include_private and private_safe]
    grouped = collections.defaultdict(list)
    for r in allowed:
        grouped[(r["private"], r["type"], r["resolved_target"])].append(r)
    files, memberships, groups = [], [], []
    for (private, relation_type, target), relations in sorted(grouped.items()):
        family = relation_type[len("declared-"):]
        digest = hashlib.sha256((relation_type + target).encode("utf-8")).hexdigest()[:16]
        group = Group(TIER_DIRECT, family, posixpath.basename(link_target_str(target)), private,
                      "exact frontmatter declaration; see local typed ledger", [target],
                      sorted({r["source_path"] for r in relations}), digest)
        groups.append(group)
        # Ordered fixed-size pages: no artificial catalog/root/folder/cluster bridges.
        for start in range(0, len(relations), max_links):
            chunk = relations[start:start + max_links]
            rel = f"{nav_dir}/" + (f"{PRIVATE_DIR}/" if private else "") + f"Direct/{family}-{digest}-p{start // max_links + 1:04d}.md"
            lines = [frontmatter("Declared " + family + " relations", {"relation_tier": TIER_DIRECT,
                      "private": private, "relation_mode": "evidence-only"}), "",
                     "# Declared frontmatter relations", "",
                     "Only exact declarations are represented. No relationship between members is inferred.",
                     "Folder location, tags and title similarity are not evidence.", "",
                     "- Declared target: " + make_link(target), ""]
            for r in chunk:
                lines.append("- " + make_link(r["source_path"]) + " | field/value: " +
                             json.dumps({r["field"]: r["value"]}, ensure_ascii=False) + " | evidence: " + r["id"])
            content = "\n".join(lines) + "\n"
            files.append(PlannedFile(rel, content, private, "group"))
            for member in sorted({target, *(r["source_path"] for r in chunk)}):
                memberships.append({"type": "evidence-hub-membership", "source_path": rel,
                                    "source_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                                    "resolved_target": member, "semantic_relation": False,
                                    "evidence_ids": [r["id"] for r in chunk if member in (r["source_path"], r["resolved_target"])]})
    ledger = {"generated_by": GENERATOR, "generator_version": GENERATOR_VERSION,
              "schema": "typed-relation-ledger/v1", "local_only": True, "private": True,
              "relation_mode": "evidence-only", "relations": allowed, "memberships": memberships}
    ledger_rel = f"{nav_dir}/{LEDGER_DIR}/{LEDGER_NAME}"
    files.append(PlannedFile(ledger_rel, json.dumps(ledger, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                             True, "ledger"))
    collisions = [f.rel for f in files if (vault / f.rel).exists() and not owned_file(vault / f.rel)]
    write_files = [f for f in files if f.rel not in collisions]
    stale = stale_owned(vault, nav_dir, nodes, write_files, include_private and private_safe)
    all_stale = stale_owned(vault, nav_dir, nodes, write_files, True)
    retained = [n for n in nodes if n.generated and n.rel not in {f.rel for f in write_files}
                and n.rel not in ({f.rel for f in stale} if prune_generated else set())]
    projected = baseline + retained + [Node(f.rel, True, links=extract_links(f.content))
                                       for f in write_files if f.role != "ledger"]
    pdeg, pinfo, _ = build_edges(projected, True)
    left = [n for n in baseline if not pdeg[n.rel]]
    covered = {r["source_path"] for r in allowed}
    summary = {"vault": str(vault), "relation_mode": "evidence-only",
               "nodes": {"total": len(baseline), "existing_generated_hubs_excluded": sum(n.generated for n in nodes),
                         "private_nodes": sum(n.private for n in baseline), "decode_errors": stats["decode_errors"]},
               "links": info, "orphans_baseline": {"total": len(orphans), "private": sum(n.private for n in orphans),
                                                  "attachments": sum(not n.is_note for n in orphans)},
               "cluster_bridges": 0, "tiers_primary_nodes": {t: len(covered) if t == TIER_DIRECT else 0 for t in TIER_ORDER},
               "groups": {"total": len(groups), "private": sum(g.private for g in groups)},
               "files": {"planned_total": len(files), "to_write": len(write_files), "collisions_refused": len(collisions),
                         "private_skipped": len(records) - len(allowed),
                         "stale_generated": len(all_stale), "stale_private_not_authorized": len(all_stale) - len(stale),
                         "would_prune": len(stale) if prune_generated else 0},
               "brain_operational_coverage": {"resolved_declared_relations": len(records), "ledger_relations": len(allowed),
                                              "sources_with_evidence": len(covered), "unresolved_declarations": unresolved,
                                              "private_relations_skipped": len(records) - len(allowed),
                                              "no_evidence_nodes": len(baseline) - len({r["source_path"] for r in records}),
                                              "meaning": "Coverage of declared evidence, not a claim that the whole Brain is complete."},
               "projected": {"orphans_remaining": len(left), "orphans_remaining_private": sum(n.private for n in left),
                             "attachment_orphans_remaining": sum(not n.is_note for n in left),
                             "components": pinfo["components"], "largest_component": pinfo["largest_component"],
                             "nodes_outside_largest_component": pinfo["nodes_outside_largest_component"],
                             "unresolved_links_after": pinfo["unresolved_links"]}}
    return {"summary": summary, "nodes": nodes, "orphans": orphans, "groups": groups, "files": files,
            "write_files": write_files, "collisions": collisions, "prune_files": stale if prune_generated else []}


def stale_owned(vault: Path, nav_dir: str, nodes: list[Node], files: list[PlannedFile], private_safe: bool) -> list[PlannedFile]:
    planned = {f.rel for f in files}
    result = []
    for n in nodes:
        if n.generated and n.rel not in planned and (not n.private or private_safe):
            p = vault / n.rel
            if n.rel.startswith(nav_dir + "/") and owned_file(p):
                result.append(PlannedFile(n.rel, read_text(p), n.private, "prune"))
    ledger = f"{nav_dir}/{LEDGER_DIR}/{LEDGER_NAME}"
    if ledger not in planned and owned_file(vault / ledger):
        result.append(PlannedFile(ledger, read_text(vault / ledger), True, "prune"))
    return result


def diff_against_disk(vault: Path, write_files: list[PlannedFile]) -> dict:
    create, update, same = [], [], []
    for f in write_files:
        p = vault / f.rel
        refuse_symlinks(p)
        if p.exists() and not owned_file(p):
            raise ValueError("refusing to overwrite unowned file")
        if not p.exists():
            create.append(f)
        elif read_text(p).replace("\r\n", "\n") == f.content:
            same.append(f)
        else:
            update.append(f)
    return {"create": create, "update": update, "unchanged": same}


def write_atomic(path: Path, content: str) -> None:
    refuse_symlinks(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-" + GENERATOR)
    refuse_symlinks(tmp)
    with open(_long(tmp), "x", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    os.replace(_long(tmp), _long(path))


def apply_plan(vault: Path, diff: dict, backup_dir: Path) -> dict:
    refuse_symlinks(backup_dir)
    if backup_dir.resolve().is_relative_to(vault.resolve()):
        raise ValueError("backups must be outside the vault")
    prune = diff.get("prune", [])
    affected = diff["update"] + prune
    # Preflight every mutation before writes. Recheck ownership immediately before deletion.
    for f in diff["create"] + affected:
        p = vault / f.rel
        refuse_symlinks(p)
        if f in diff["create"]:
            if p.exists():
                raise ValueError("new path appeared since planning")
        elif not owned_file(p):
            raise ValueError("refusing to mutate unowned file")
        if f in prune and read_text(p) != f.content:
            raise ValueError("stale file changed since planning")
    backup_dir.mkdir(parents=True, exist_ok=False)
    snapshots = {}
    for f in affected:
        raw = (vault / f.rel).read_bytes()
        snapshots[f.rel] = raw
        dst = backup_dir / "files" / f.rel
        refuse_symlinks(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(raw)
    manifest = {"generator": GENERATOR, "version": GENERATOR_VERSION,
                "created_files": [f.rel for f in diff["create"]],
                "updated_files": [f.rel for f in diff["update"]],
                "pruned_files": [f.rel for f in prune], "unchanged_count": len(diff["unchanged"]),
                "backups": len(affected), "backup_sha256": {r: hashlib.sha256(b).hexdigest() for r, b in snapshots.items()},
                "note": "Rollback: restore ./files for updated/pruned entries; remove only manifest-created entries."}
    write_atomic(backup_dir / "apply_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    for f in diff["create"] + diff["update"]:
        p = vault / f.rel
        if f.rel in snapshots and (not owned_file(p) or p.read_bytes() != snapshots[f.rel]):
            raise ValueError("generated file changed after backup")
        write_atomic(p, f.content)
    for f in prune:
        p = vault / f.rel
        if not owned_file(p) or p.read_bytes() != snapshots[f.rel]:
            raise ValueError("stale file changed after backup; refusing deletion")
        p.unlink()
    return {"backups": len(affected), "created": len(diff["create"]), "updated": len(diff["update"]),
            "pruned": len(prune)}


GRAPH_PLAN = [
    "NOT applied. Proposed manual changes to .obsidian/graph.json:",
    "1. Keep showOrphans=true, showAttachments=true, hideUnresolved=true (all unreferenced attachments now get hub links).",
    "2. search: append ' -path:Navigation/Buckets -path:Navigation/_private/Buckets' to the existing "
    "'-path:Knowledge/Records' (large bucket pages and the 84k generated records stay out of the rendered graph, "
    "but remain linked and clickable from group hubs/backlinks).",
    "3. colorGroups: add {\"query\": \"path:Navigation\", \"color\": {\"a\": 1, \"rgb\": 1752220}} so hubs are visually distinct "
    "from content nodes (Personal group colour is unchanged).",
    "4. Optional: add one manual line '[[Navigation/JARVIS Orphan Navigation Hub]]' to 'JARVIS Graph Hub.md'; this script "
    "never edits existing notes, and the generator organize_obsidian_graph.py rewrites that hub anyway.",
    "5. Do not rely on the Knowledge/* folders for overlay files: organize_obsidian_graph.py regenerates them every run.",
]


def _main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent
    default_vault = here.parent / "obsidian" / "JARVIS_LUNA"
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--vault", type=Path, default=default_vault)
    ap.add_argument("--nav-dir", default=DEFAULT_NAV_DIR, help="folder (inside the vault) for generated hubs")
    ap.add_argument("--private-prefix", action="append", dest="private_prefixes",
                    help="top-level vault folder treated as personal (repeatable; default: Personal)")
    ap.add_argument("--max-links-per-page", type=int, default=DEFAULT_MAX_LINKS)
    ap.add_argument("--apply", action="store_true", help="write hubs (default is a dry-run)")
    ap.add_argument("--legacy-inference", action="store_true", help="opt into old inferred/folder/cluster connections")
    ap.add_argument("--prune-generated", action="store_true", help="backup and remove only owned generated files absent from the new plan")
    ap.add_argument("--include-private", action="store_true",
                    help="also write private hubs (only if git ignores them)")
    ap.add_argument("--git-exclude-private", action="store_true",
                    help="add local-only .git/info/exclude entry for the private hub folder")
    ap.add_argument("--verify", action="store_true",
                    help="read-only: count orphans of the vault INCLUDING already generated hubs")
    ap.add_argument("--backup-root", type=Path, default=None)
    ap.add_argument("--report", type=Path, default=None, help="write JSON summary here (outside the vault)")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    refuse_symlinks(args.vault.absolute())
    vault = args.vault.resolve()
    if not vault.is_dir():
        print(f"error: vault not found: {vault}", file=sys.stderr)
        return 2
    if args.nav_dir.startswith(("/", "\\")):
        raise ValueError("nav-dir must be relative")
    nav_dir = args.nav_dir.strip("/")
    prefixes = tuple(args.private_prefixes or DEFAULT_PRIVATE_PREFIXES)
    if (not nav_dir or "\\" in nav_dir or ":" in nav_dir or any(x in ("", ".", "..") or x.startswith(".") for x in nav_dir.split("/"))
            or Path(nav_dir).is_absolute() or nav_dir.split("/")[0] in prefixes):
        raise ValueError("nav-dir must be a safe relative non-private folder")
    if args.max_links_per_page < 1:
        raise ValueError("max-links-per-page must be positive")
    refuse_symlinks(vault / nav_dir)
    if args.report:
        refuse_symlinks(args.report.absolute())
        if args.report.resolve().is_relative_to(vault):
            raise ValueError("reports must be outside the vault")

    root = git_root(vault)
    priv_abs = vault / nav_dir / PRIVATE_DIR
    priv_pattern = None
    if root is not None:
        try:
            priv_pattern = "/" + priv_abs.relative_to(root).as_posix() + "/"
        except ValueError:
            priv_pattern = None
    ignored_now = bool(root and git_ignored(root, priv_abs / "x.md"))
    private_safe = ignored_now or (args.git_exclude_private and root is not None and priv_pattern is not None)
    if root is not None:
        private_tracked = git(["ls-files", "--", str(priv_abs)], root)
        private_safe = private_safe and bool(private_tracked and not private_tracked.returncode and not private_tracked.stdout.strip())

    if args.verify:
        nodes, _ = scan_vault(vault, nav_dir, prefixes)
        deg, info, _ = build_edges(nodes, include_generated=True)
        left = [n for n in nodes if not deg.get(n.rel, 0)]
        out = {"mode": "verify", "relation_mode": "legacy-inference" if args.legacy_inference else "evidence-only",
               "nodes": len(nodes), "generated_hubs": sum(n.generated for n in nodes), "links": info,
               "orphans_remaining": len(left), "orphans_remaining_private": sum(n.private for n in left),
               "orphans_remaining_attachments": sum(not n.is_note for n in left)}
        if args.legacy_inference:
            print(json.dumps(out, ensure_ascii=False, indent=1))
            return 0 if not left else 1
        expected = analyse(vault, nav_dir, prefixes, args.max_links_per_page, args.include_private, private_safe)
        delta = diff_against_disk(vault, expected["write_files"])
        ledger_path = vault / nav_dir / LEDGER_DIR / LEDGER_NAME
        ledger_ignored = root is None or git_ignored(root, ledger_path)
        if root is not None:
            tracked = git(["ls-files", "--", str(ledger_path)], root)
            ledger_ignored = ledger_ignored and bool(tracked and not tracked.returncode and not tracked.stdout.strip())
        coverage = expected["summary"]["brain_operational_coverage"]
        coverage.update({"missing_generated_files": len(delta["create"]), "stale_or_changed_generated_files": len(delta["update"]),
                         "unplanned_owned_generated_files": expected["summary"]["files"]["stale_generated"],
                         "ledger_local_only_safe": ledger_ignored, "collisions": len(expected["collisions"])})
        out["brain_operational_coverage"] = coverage
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 1 if delta["create"] or delta["update"] or expected["collisions"] or coverage["unplanned_owned_generated_files"] or not ledger_ignored else 0

    res = analyse(vault, nav_dir, prefixes, args.max_links_per_page, args.include_private, private_safe,
                  legacy_inference=args.legacy_inference, prune_generated=args.prune_generated)
    s = res["summary"]
    diff = diff_against_disk(vault, res["write_files"])
    diff["prune"] = res["prune_files"]
    s["files"].update({"would_create": len(diff["create"]), "would_update": len(diff["update"]),
                       "unchanged": len(diff["unchanged"])})
    s["mode"] = "apply" if args.apply else "dry-run"
    s["private_hubs_git_ignored_now"] = ignored_now
    s["graph_settings_plan"] = GRAPH_PLAN if args.legacy_inference else ["No graph.json changes. Orphans and separate components are legitimate without declared evidence."]
    flags = []
    if args.legacy_inference:
        flags.append("--legacy-inference")
    if args.prune_generated:
        flags.append("--prune-generated")
    if args.include_private:
        flags.append("--include-private")
    if args.git_exclude_private:
        flags.append("--git-exclude-private")
    s["suggested_apply_command"] = subprocess.list2cmdline(
        ["python", "scripts/connect_obsidian_orphans.py", "--vault", str(vault), "--nav-dir", nav_dir, "--apply", *flags])

    if res["collisions"]:
        print(f"error: {len(res['collisions'])} planned hub path(s) collide with non-generated files; refusing those",
              file=sys.stderr)
    if args.include_private and not private_safe:
        print("warning: private hubs NOT written: the private folder is not git-ignored "
              "(re-run with --git-exclude-private)", file=sys.stderr)

    if args.apply:
        if args.include_private and args.git_exclude_private and priv_pattern and not ignored_now:
            add_local_exclude(root, priv_pattern)
            if not git_ignored(root, priv_abs / "x.md"):
                print("error: could not make the private folder git-ignored; aborting before any write", file=sys.stderr)
                return 2
        if res["collisions"]:
            print("error: collisions detected; aborting all writes and pruning", file=sys.stderr)
            print(json.dumps(s, ensure_ascii=False, indent=1))
            return 2
        local_abs = vault / nav_dir / LEDGER_DIR
        if root is not None:
            local_pattern = "/" + local_abs.relative_to(root).as_posix() + "/"
            if not git_ignored(root, local_abs / LEDGER_NAME):
                if not add_local_exclude(root, local_pattern) or not git_ignored(root, local_abs / LEDGER_NAME):
                    raise ValueError("cannot enforce local-only ledger git exclusion")
            tracked = git(["ls-files", "--", str(local_abs)], root)
            if not tracked or tracked.returncode or tracked.stdout.strip():
                raise ValueError("local ledger is tracked or tracking safety cannot be verified")
        backup_root = args.backup_root or (vault.parent / "automation" / "logs" / GENERATOR)
        refuse_symlinks(backup_root)
        if backup_root.resolve().is_relative_to(vault):
            raise ValueError("backups must be outside the vault")
        if root is not None and backup_root.resolve().is_relative_to(root.resolve()):
            backup_pattern = "/" + backup_root.resolve().relative_to(root.resolve()).as_posix() + "/"
            if not add_local_exclude(root, backup_pattern) or not git_ignored(root, backup_root / "x.json"):
                raise ValueError("cannot enforce local-only backup git exclusion")
            tracked = git(["ls-files", "--", str(backup_root)], root)
            if not tracked or tracked.returncode or tracked.stdout.strip():
                raise ValueError("backup folder is tracked or tracking safety cannot be verified")
        backup_dir = backup_root / (time.strftime("%Y%m%d-%H%M%S") + "-" + str(time.time_ns()))
        s["applied"] = apply_plan(vault, diff, backup_dir)
        s["backup_dir"] = str(backup_dir)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(s, fh, ensure_ascii=False, indent=1)
    print(json.dumps(s, ensure_ascii=False, indent=1))
    return 2 if res["collisions"] else 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except (OSError, ValueError) as exc:
        print("error: unsafe path, ownership, or local-only storage condition; " + type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
