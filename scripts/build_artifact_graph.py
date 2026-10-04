#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
JARVIS 산출물 의존 그래프 · 재생성 순서 가드
=============================================

왜 만들었나
-----------
2026-09-15 다이소 실수집 #33 이 59분 수집하고 발행 직전에 죽었다.

    FAIL 마케팅 카드 S등급 6 vs 소싱 점수 S 8
    FAIL 게이트 대상 6건 vs S등급 8건. 게이트가 점수보다 먼저 돌았다

점수는 이번 실행이 다시 계산했는데, 그 점수에서 파생되는
market_team.json / listing_gate.json 을 아무도 다시 만들지 않았다.
대시보드는 그 낡은 두 파일로 팀 카드를 썼고, audit 이 막았다.

audit 은 "숫자가 안 맞는다"를 사후에 잡는다.
그때는 이미 59분이 지난 뒤다.

이 파일은 "재생성 순서가 빠졌다"를 사전에 잡는다.
코드를 읽어서 잡으므로 수집을 한 번도 돌리지 않아도 된다.

무엇을 하나
-----------
1. scripts/**/*.py 를 AST 로 읽어 각 스크립트가 읽고 쓰는
   data/**/*.json 을 뽑는다.  (소비자 / 생산자)
2. .github/workflows/*.yml 과 발행 액션에서 각 워크플로가
   실제로 실행하는 스크립트를 뽑는다.
3. 발행하는 워크플로가 상위 산출물을 갱신하면서 그 파생본을
   다시 만들지 않으면 위반으로 본다.

쓰는 법
-------
    python scripts/build_artifact_graph.py            # 그래프 요약 출력
    python scripts/build_artifact_graph.py --check    # 위반 있으면 exit 1
    python scripts/build_artifact_graph.py --json     # 그래프를 JSON 으로
    python scripts/build_artifact_graph.py --mermaid # Mermaid 다이어그램을 stdout 으로
    python scripts/build_artifact_graph.py --write    # data/artifact_graph.json 저장

짐작하지 않는 것
----------------
- 추출하지 못한 스크립트는 조용히 넘기지 않고 unresolved 에 남긴다.
- 발행 관문이 실제로 읽는 파일만 위반으로 올린다.
  전체 스크립트를 다 걸면 경고가 수백 개 나와서 아무도 안 본다.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
WORKFLOWS = ROOT / ".github" / "workflows"
PUBLISH_ACTION = ROOT / ".github" / "actions" / "publish" / "action.yml"

# 발행 관문이 돌리는 것들.
# publish 액션 안에서 audit 이 이 둘의 산출물을 대조한다.
AUDIT_SCRIPT = "scripts/audit_team_reports.py"

# data 디렉터리를 가리키는 흔한 변수 이름.
# ROOT / "data" 형태는 아래에서 따로 푼다.
_DATA_BASES = {"D", "DATA", "DATA_DIR", "DATADIR"}

# 읽기로 보는 호출 이름
_READ_FUNCS = {
    "load", "load_json", "read_json", "loadj", "rj", "_load", "_read_json",
}

# 쓰기로 보는 호출 이름
_WRITE_FUNCS = {"save_json", "write_json", "dump_json", "wj", "_save_json"}


# ──────────────────────────────────────────────────────────────
# 1. 파이썬 스크립트에서 읽기/쓰기 경로 뽑기
# ──────────────────────────────────────────────────────────────


class PathResolver(ast.NodeVisitor):
    """AST 안의 경로 표현식을 data/ 기준 상대경로 문자열로 푼다."""

    def __init__(self) -> None:
        # 변수 이름 -> data 기준 경로
        self.vars: dict[str, str] = {}
        # data 디렉터리로 쓰이는 변수 이름
        self.bases: set[str] = set(_DATA_BASES)

    # -- 경로 해석 ---------------------------------------------

    def segments(self, node: ast.AST) -> list[str] | None:
        """a / "b" / "c.json" 같은 표현식을 ["b", "c.json"] 으로."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]

        if isinstance(node, ast.Name):
            if node.id in self.bases:
                return ["<data>"]
            known = self.vars.get(node.id)
            if known:
                return ["<data>"] + known.split("/")
            # ROOT 는 저장소 루트다. data 를 붙여야 의미가 생긴다.
            if node.id in {"ROOT", "BASE", "REPO"}:
                return ["<root>"]
            return None

        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left = self.segments(node.left)
            right = self.segments(node.right)
            if left is None or right is None:
                return None
            return left + right

        if isinstance(node, ast.Call):
            # Path("data/x.json")
            fn = node.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if name == "Path" and node.args:
                return self.segments(node.args[0])

        return None

    def resolve(self, node: ast.AST) -> str | None:
        """경로 표현식을 'data/...json' 으로. data 밖이면 None."""
        segs = self.segments(node)
        if not segs:
            return None

        # 평탄화: 각 조각이 'a/b' 일 수 있다
        flat: list[str] = []
        for s in segs:
            flat.extend(x for x in s.split("/") if x)

        if not flat or not flat[-1].endswith(".json"):
            return None

        if flat[0] == "<data>":
            rest = flat[1:]
        elif flat[0] == "<root>":
            rest = flat[1:]
            if not rest or rest[0] != "data":
                return None
            rest = rest[1:]
        elif flat[0] == "data":
            rest = flat[1:]
        else:
            return None

        if not rest:
            return None
        return "data/" + "/".join(rest)


class ArtifactVisitor(ast.NodeVisitor):
    """한 스크립트가 읽는 파일과 쓰는 파일을 모은다."""

    def __init__(self) -> None:
        self.r = PathResolver()
        self.reads: set[str] = set()
        self.writes: set[str] = set()

    # -- 변수 바인딩 -------------------------------------------

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue

            # DATA = ROOT / "data"  처럼 data 디렉터리 자체를 잡는다
            segs = self.r.segments(node.value)
            if segs:
                flat: list[str] = []
                for s in segs:
                    flat.extend(x for x in s.split("/") if x)
                if flat and flat[0] == "<root>" and flat[1:] == ["data"]:
                    self.r.bases.add(target.id)
                    continue
                if flat == ["<data>"]:
                    self.r.bases.add(target.id)
                    continue

            path = self.r.resolve(node.value)
            if path:
                self.r.vars[target.id] = path[len("data/"):]

        self.generic_visit(node)

    # -- 사용처 -------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        fn = node.func

        # X.write_text(...) / X.read_text(...)
        if isinstance(fn, ast.Attribute):
            target = self.r.resolve(fn.value)
            if target:
                if fn.attr in {"write_text", "write_bytes"}:
                    self.writes.add(target)
                elif fn.attr in {"read_text", "read_bytes"}:
                    self.reads.add(target)

        name = getattr(fn, "id", None)
        attr = getattr(fn, "attr", None)

        # open(P, "w") / open(P)
        if name == "open" and node.args:
            target = self.r.resolve(node.args[0])
            if target:
                mode = ""
                if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                    mode = str(node.args[1].value)
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                        mode = str(kw.value.value)
                if any(ch in mode for ch in ("w", "a", "x")):
                    self.writes.add(target)
                else:
                    self.reads.add(target)

        # load(P) / load_json(P) / save_json(P, ...) 같은 헬퍼
        if name in _READ_FUNCS and node.args:
            target = self.r.resolve(node.args[0])
            if target:
                self.reads.add(target)

        if name in _WRITE_FUNCS and node.args:
            for arg in node.args[:2]:
                target = self.r.resolve(arg)
                if target:
                    self.writes.add(target)
                    break

        # json.load(...) / json.loads(P.read_text()) 는 위 read_text 가 잡는다
        if attr in {"load", "loads"} and node.args:
            target = self.r.resolve(node.args[0])
            if target:
                self.reads.add(target)

        self.generic_visit(node)


def scan_script(path: Path) -> dict[str, list[str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except (OSError, SyntaxError):
        return {"reads": [], "writes": [], "error": ["parse_failed"]}

    v = ArtifactVisitor()
    v.visit(tree)

    # 같은 파일을 읽고 쓰는 경우(제자리 갱신)는 쓰기로 본다
    reads = sorted(v.reads - v.writes)
    writes = sorted(v.writes)
    return {"reads": reads, "writes": writes, "error": []}


def scan_all_scripts() -> dict[str, dict[str, list[str]]]:
    out: dict[str, dict[str, list[str]]] = {}
    for p in sorted(SCRIPTS.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        rel = p.relative_to(ROOT).as_posix()
        info = scan_script(p)
        if info["reads"] or info["writes"]:
            out[rel] = info
    return out


# ──────────────────────────────────────────────────────────────
# 2. 워크플로가 실제로 돌리는 스크립트
# ──────────────────────────────────────────────────────────────

_SCRIPT_RE = re.compile(r"(scripts/[A-Za-z0-9_./-]+\.py)")
_PUBLISH_RE = re.compile(r"uses:\s*\./\.github/actions/publish")
_REGEN_RE = re.compile(r"regenerate-dashboard:\s*'?\"?(\w+)")
_AUDIT_RE = re.compile(r"audit:\s*'?\"?(\w+)")
_INPUT_DEFAULT_RE = re.compile(
    r"^\s{2}(\S+):\s*$\n(?:^\s{4}.*$\n)*?^\s{4}default:\s*'?\"?(\w+)",
    re.M,
)


def publish_action_defaults(text: str) -> dict[str, str]:
    """publish 액션의 inputs 기본값을 읽는다.

    regenerate-dashboard 와 audit 은 기본값이 둘 다 'true' 다.
    워크플로가 아무것도 적지 않으면 그대로 켜진다.
    이걸 짐작으로 false 로 보면 검사 범위를 2개로 착각한다.
    실제로는 발행하는 워크플로 12개 전부가 관문 대상이다.
    """
    out: dict[str, str] = {}
    for name, default in _INPUT_DEFAULT_RE.findall(text):
        out[name] = default
    return out


def scripts_in_text(text: str) -> list[str]:
    seen: list[str] = []
    for m in _SCRIPT_RE.finditer(text):
        s = m.group(1)
        if s not in seen:
            seen.append(s)
    return seen


_PUBLISH_WRAPPER = "scripts/publish_transaction.py"
_RUNTIME_CHAIN = [["scripts/health_check_v2.py"],["scripts/generate_dashboard_runtime.py"],["scripts/run_jarvis_agents.py","--force"],["scripts/run_jarvis_operations.py"],["scripts/build_team_improvement.py"]]
_COMMERCE_CHAIN = [["scripts/build_product_master.py"],["scripts/daiso/score_shopify_demand.py"],["scripts/build_product_master.py","--inject-s"],["scripts/pricing_model.py"],["scripts/check_legal_products.py"],["scripts/build_legal_full.py"],["scripts/build_listing_gate.py"],["scripts/build_product_master.py","--inject-s"],["scripts/build_shopify_shortlist.py"],["scripts/build_mocra_readiness.py"],["scripts/build_listing_gate.py"],["scripts/build_market_team.py"],["scripts/export_shopify_operational.py"],["scripts/build_shopify_action_queue.py"],["scripts/discover_channels.py"]]

def _ast_matches(node, expression):
    return ast.dump(node) == ast.dump(ast.parse(expression, mode="eval").body)


def publish_wrapper_contract(action_text):
    """Recognize only the actual audited CLI and verify declaration execution.

    An unknown or changed wrapper cannot invent graph producer coverage. The
    mandatory final gate and candidate separation are checked, not assumed.
    """
    wrapper = ROOT / _PUBLISH_WRAPPER
    policy_file = ROOT / "config/publish_policy.json"
    if not wrapper.exists() and not policy_file.exists():
        if _PUBLISH_WRAPPER in scripts_in_text(action_text):
            raise ValueError("publish graph contract: wrapper missing")
        return None
    if not wrapper.exists() or not policy_file.exists():
        raise ValueError("publish graph contract: wrapper/policy missing")
    import yaml
    action = yaml.safe_load(action_text) or {}
    invocations = []
    for step in (action.get("runs") or {}).get("steps") or []:
        calls = re.findall(r"(?m)^\s*python(?:3)?(?:\s+-[A-Za-z]+)*\s+scripts/publish_transaction\.py([^\n]*)", step.get("run", ""))
        if calls and (step.get("if") or any("||" in tail for tail in calls)):
            raise ValueError("publish graph contract: invocation conditional/masked")
        invocations.extend(calls)
    if len(invocations) != 1:
        raise ValueError("publish graph contract: action does not invoke wrapper once")
    policy = json.loads(policy_file.read_text(encoding="utf-8"))
    if policy.get("runtime_commands") != _RUNTIME_CHAIN or policy.get("commerce_commands") != _COMMERCE_CHAIN:
        raise ValueError("publish graph contract: required ordered producer chain changed")
    for key in ("commerce_inputs", "derived_paths", "candidate_protected"):
        if not isinstance(policy.get(key), list) or not policy[key]:
            raise ValueError(f"publish graph contract: missing {key}")
    for command in _RUNTIME_CHAIN + _COMMERCE_CHAIN + [["scripts/check_release_quality.py"], ["scripts/build_daiso_candidate_comparison.py"]]:
        if not (ROOT / command[0]).is_file():
            raise ValueError(f"publish graph contract: producer/checker missing {command[0]}")
    tree = ast.parse(wrapper.read_text(encoding="utf-8-sig"))
    cls = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Transaction"), None)
    methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)} if cls else {}
    if not {"__init__", "command", "candidate_only", "regenerate_and_validate", "run", "stage", "push"} <= methods.keys():
        raise ValueError("publish graph contract: required functions absent")
    main = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    if not main or not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "run"
                           and isinstance(n.func.value, ast.Call) and isinstance(n.func.value.func, ast.Name)
                           and n.func.value.func.id == "Transaction" for n in ast.walk(main)):
        raise ValueError("publish graph contract: CLI cannot reach Transaction.run")
    if not any(isinstance(n, ast.If) and _ast_matches(n.test, "__name__ == '__main__'")
               and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "main" for c in ast.walk(n))
               for n in tree.body):
        raise ValueError("publish graph contract: executable main guard absent")
    if not any(isinstance(n, ast.Constant) and n.value == "config/publish_policy.json" for n in ast.walk(methods["__init__"])):
        raise ValueError("publish graph contract: policy loader absent")
    command = methods["command"]
    if not any(isinstance(n, ast.If) and _ast_matches(n.test, "p.returncode")
               and any(isinstance(c, ast.Raise) for c in n.body) for n in command.body):
        raise ValueError("publish graph contract: command failure propagation absent")
    for key in ("TYPESAFE_ENABLED", "GEMINI_FALLBACK_ENABLED", "TYPESAFE_ALLOW_PAID"):
        if not any(isinstance(n, ast.keyword) and n.arg == key and _ast_matches(n.value, "'0'") for n in ast.walk(command)):
            raise ValueError("publish graph contract: offline model disable absent")
    regen = methods["regenerate_and_validate"]
    if not any(isinstance(n, ast.Assign) and _ast_matches(n.value, "self.candidate_only()") for n in regen.body):
        raise ValueError("publish graph contract: candidate separation absent")
    commerce = next((n for n in regen.body if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == "commerce" for t in n.targets)), None)
    if not commerce or not _ast_matches(commerce.value,
            "not candidate and any(path_allowed(n, self.policy['commerce_inputs'] + commerce_outputs) for n in relevant)"):
        raise ValueError("publish graph contract: conditional commerce protection changed")
    dispatch_lines = []
    for test, key in (("commerce", "commerce_commands"), ("relevant or self.regenerate_dashboard", "runtime_commands")):
        guard = next((n for n in regen.body if isinstance(n, ast.If) and _ast_matches(n.test, test)), None)
        if not guard or len(guard.body) != 1 or not isinstance(guard.body[0], ast.For):
            raise ValueError("publish graph contract: required conditional dispatch absent")
        loop = guard.body[0]
        if (not _ast_matches(loop.iter, f"self.policy['{key}']") or len(loop.body) != 1
                or not isinstance(loop.body[0], ast.Expr) or not _ast_matches(loop.body[0].value, "self.command(work, args)")):
            raise ValueError("publish graph contract: declared ordered chain not executed")
        dispatch_lines.append(guard.lineno)
    quality = next((n for n in regen.body if isinstance(n, ast.For) and isinstance(n.target, ast.Name) and n.target.id == "phase"
                    and _ast_matches(n.iter, "('candidate', 'final')")), None)
    gate = quality.body[0].value if quality and len(quality.body) == 1 and isinstance(quality.body[0], ast.Expr) else None
    gate_args = gate.args[1] if isinstance(gate, ast.Call) and len(gate.args) == 2 else None
    if isinstance(gate_args, ast.BinOp) and isinstance(gate_args.op, ast.Add) and _ast_matches(gate_args.right, "extra"):
        gate_args = gate_args.left
    if (not isinstance(gate, ast.Call) or not _ast_matches(gate.func, "self.command")
            or not isinstance(gate_args, ast.List) or len(gate_args.elts) < 3
            or not _ast_matches(gate_args.elts[0], "'scripts/check_release_quality.py'")
            or not _ast_matches(gate_args.elts[1], "'--phase'") or not _ast_matches(gate_args.elts[2], "phase")):
        raise ValueError("publish graph contract: mandatory candidate/final release gate absent")
    expected_gate = "['scripts/check_release_quality.py', '--phase', phase, '--root', str(work), '--baseline', str(baseline), '--report', str(report_dir/f'{phase}.json'), *extra]"
    if (not _ast_matches(gate.args[0], "work") or not _ast_matches(gate_args, expected_gate)
            or not dispatch_lines[0] < dispatch_lines[1] < quality.lineno):
        raise ValueError("publish graph contract: final merged-root gate or execution order changed")
    calls = [(n.lineno, n.func.attr) for n in ast.walk(methods["run"]) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id == "self"]
    order = [min((line for line, name in calls if name == method), default=0)
             for method in ("regenerate_and_validate", "stage", "push")]
    if not 0 < order[0] < order[1] < order[2]:
        raise ValueError("publish graph contract: validation must precede stage/push")
    return policy


def _graph_path_allowed(name, paths):
    return any(name == p.rstrip("/") or name.startswith(p.rstrip("/") + "/") for p in paths)


def _transaction_profiles(text, policy, scripts):
    import shlex
    import yaml
    doc = yaml.safe_load(text) or {}
    profiles = []
    produced = {w for script in scripts_in_text(text) for w in (scripts.get(script) or {}).get("writes", [])}
    prefixes = ("data/daiso_real/candidate_", "data/daiso_real/collection_status.json", "data/daiso_real/crawl_state.json",
                "data/agents/", "data/knowledge/cumulative_history.json")
    commerce_outputs = ["data/daiso_real/shopify_demand_score.json", "data/product_master.json", "data/pricing_model.json",
                        "data/listing_gate.json", "data/legal_products.json", "data/legal_full.json", "data/market_team.json",
                        "data/shopify_exports/", "data/shopify_action_queue.json", "data/shopify_shortlist.json"]
    for job in (doc.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            if step.get("uses") != "./.github/actions/publish":
                continue
            params = step.get("with") or {}
            paths = shlex.split(str(params.get("paths") or ""))
            if not paths or any("${{" in p for p in paths):
                raise ValueError("publish graph contract: explicit publication paths required")
            sources = [p for p in paths if not _graph_path_allowed(p, policy["derived_paths"])]
            candidate = bool(sources) and all(p.startswith(prefixes) for p in sources)
            triggers = sorted(n for n in produced if _graph_path_allowed(n, paths)
                              and _graph_path_allowed(n, policy["commerce_inputs"] + commerce_outputs))
            commerce = bool(triggers) and not candidate
            commands = list(policy["commerce_commands"]) if commerce else []
            if candidate and _graph_path_allowed("data/daiso_real/candidate_pool.json", paths):
                commands += [["scripts/build_daiso_candidate_comparison.py"]]
            commands += policy["runtime_commands"]
            commands += [["scripts/check_release_quality.py", "--phase", p] for p in ("candidate", "final")]
            if str(params.get("audit", "true")).lower() == "true":
                commands.append([AUDIT_SCRIPT])
            profiles.append({"step": step.get("name"), "condition": step.get("if"), "paths": paths,
                             "candidate_only": candidate, "commerce_regeneration": commerce,
                             "commerce_triggers": triggers, "commands": commands,
                             "runtime_condition": "nonempty source delta or requested regeneration; no-change skips publication"})
    return profiles


def scan_workflows(scripts: dict | None = None) -> dict[str, dict]:
    publish_text = ""
    if PUBLISH_ACTION.exists():
        publish_text = PUBLISH_ACTION.read_text(encoding="utf-8-sig")
    publish_scripts = scripts_in_text(publish_text)
    contract = publish_wrapper_contract(publish_text)
    if contract and scripts is None:
        scripts = scan_all_scripts()
    defaults = publish_action_defaults(publish_text)

    out: dict[str, dict] = {}
    for p in sorted(WORKFLOWS.glob("*.y*ml")):
        text = p.read_text(encoding="utf-8-sig")
        rel = p.relative_to(ROOT).as_posix()
        publishes = bool(_PUBLISH_RE.search(text))

        def flag(rx: re.Pattern, key: str, body: str = text) -> bool:
            m = rx.search(body)
            if m:
                return m.group(1).lower() == "true"
            return defaults.get(key, "false").lower() == "true"

        regen = publishes and flag(_REGEN_RE, "regenerate-dashboard")
        audit = publishes and flag(_AUDIT_RE, "audit")

        runs = scripts_in_text(text)
        # 발행 액션이 돌리는 스크립트도 이 워크플로가 돌리는 것이다.
        # regenerate-dashboard: true 일 때만 그 안의 재생성이 돈다.
        effective = list(runs)
        profiles = _transaction_profiles(text, contract, scripts or {}) if contract and publishes else []
        if profiles:
            for profile in profiles:
                for command in profile["commands"]:
                    if command[0] not in effective:
                        effective.append(command[0])
        elif regen:
            for s in publish_scripts:
                if s not in effective:
                    effective.append(s)

        out[rel] = {
            "publishes": publishes,
            "regenerates_dashboard": regen,
            "runs_audit": audit,
            "mandatory_release_gate": bool(profiles),
            "publish_profiles": profiles,
            "runs": runs,
            "effective": effective,
        }
    return out


# ──────────────────────────────────────────────────────────────
# 3. 순서 위반 찾기
# ──────────────────────────────────────────────────────────────


def build_graph() -> dict:
    scripts = scan_all_scripts()
    workflows = scan_workflows(scripts)

    # 생산자 맵: 산출물 -> 그것을 쓰는 스크립트들
    producers: dict[str, list[str]] = {}
    for s, info in scripts.items():
        for w in info["writes"]:
            producers.setdefault(w, []).append(s)

    # 발행 관문이 읽는 산출물
    audit_info = scripts.get(AUDIT_SCRIPT) or {"reads": []}
    audited = set(audit_info["reads"])

    # 발행 액션이 마지막에 다시 만드는 산출물은 종착점이다.
    #
    # dashboard_runtime.json 이 그렇다. 다른 것을 다 만든 뒤
    # 맨 끝에 한 번 더 생성된다. 그러니 "이걸 갱신했으니
    # 아래가 낡았다" 는 성립하지 않는다.
    #
    # 이걸 빼지 않으면 discover_channels.py 같이 통계용으로
    # 대시보드를 읽는 수집기가 전부 오탐으로 잡힌다.
    # 실제로 21건 중 20건이 그것이었다.
    terminal: set[str] = set()
    publish_text = PUBLISH_ACTION.read_text(encoding="utf-8-sig") if PUBLISH_ACTION.exists() else ""
    contract = publish_wrapper_contract(publish_text)
    terminal_scripts = ([args[0] for args in contract["runtime_commands"]] if contract
                        else scripts_in_text(publish_text))
    # Conditional commerce chains are not global terminals: their stale edges
    # must remain visible in unrelated and candidate-only publications.
    for s in terminal_scripts:
        info = scripts.get(s)
        if info:
            terminal.update(info["writes"])

    # audit 이 직접 읽지는 않지만 같이 써지는 형제 산출물까지 리거로 본다.
    #
    # score_shopify_demand.py 는 한 번에 세 개를 쓴다.
    #   shopify_demand_score.json        (audit 이 직접 읽음)
    #   shopify_s_recommendations.json   (audit 은 안 읽음)
    #   shopify_s_rejected.json
    #
    # #33 의 두 번째 FAIL 은 listing_gate 가 낡아서 난 것인데,
    # listing_gate 의 입력은 recommendations \ucabd이다.
    # 그걸 빼면 같은 사고의 절반을 못 잡는다.
    # 같은 스크립트가 한 번에 쓰는 파일은 같이 움직인다.
    coupled = set(audited)
    for s, info in scripts.items():
        if set(info["writes"]) & audited:
            coupled.update(info["writes"])

    violations: list[dict] = []

    for wf, meta in workflows.items():
        if not meta["runs_audit"] and not meta.get("mandatory_release_gate"):
            continue

        ran = set(meta["effective"])

        # 이 워크플로가 이번 실행에서 새로 쓰는 산출물
        produced: set[str] = set()
        for s in meta["effective"]:
            info = scripts.get(s)
            if info:
                produced.update(info["writes"])

        # 관문이 읽는 파일 중, 이 워크플로가 갱신한 것에서 파생되는데
        # 정작 그 파생 스크립트를 안 돌린 경우를 찾는다
        # audit 은 자기가 읽는 두 파일을 서로 대조해서 FAIL 을 낸다.
        #   U = 이번에 갱신된 상위 산출물
        #   Y = U 에서 파생되는 아래 산출물
        # 둘 다 audit 의 시야에 있어야 숫자가 맞붙어진다.
        # 한쪽만 읽으면 대조할 상대가 없으니 막힐 일도 없다.
        # 종착 산출물은 발행 직전에 어차피 다시 만든다.
        # 낡을 수가 없으니 후보에서 뺀다.
        for y in sorted(audited - terminal):
            for prod in producers.get(y, []):
                if prod in ran:
                    continue
                upstream = sorted(
                    (set(scripts[prod]["reads"]) & produced & coupled)
                    - terminal
                )
                if not upstream:
                    continue
                violations.append({
                    "workflow": wf,
                    "stale_artifact": y,
                    "producer_not_run": prod,
                    "upstream_updated": upstream,
                })

    return {
        "scripts": scripts,
        "workflows": workflows,
        "producers": producers,
        "audited": sorted(audited),
        "coupled": sorted(coupled),
        "terminal": sorted(terminal),
        "violations": violations,
    }


# ──────────────────────────────────────────────────────────────
# 4. 출력
# ──────────────────────────────────────────────────────────────


def render_mermaid(g: dict) -> str:
    """정본 그래프만 읽어 결정적 Mermaid 텍스트를 만든다. 파일/네트워크 쓰기 없음."""
    def node_id(kind: str, name: str) -> str:
        digest = hashlib.sha256(f"{kind}:{name}".encode("utf-8")).hexdigest()[:16]
        return f"n_{kind}_{digest}"

    def label(name: str) -> str:
        # Mermaid의 따옴표/대괄호/HTML/간선 구문을 라벨 밖으로 새지 않게 한다.
        entities = {"&": "#38;", '"': "#34;", "'": "#39;", "[": "#91;",
                    "]": "#93;", "<": "#60;", ">": "#62;", "`": "#96;",
                    "|": "#124;", "\\": "#92;"}
        return "".join(entities.get(ch, " " if ch in "\r\n" else ch)
                       for ch in name)

    nodes: set[tuple[str, str]] = set()
    edges: set[tuple[tuple[str, str], tuple[str, str], str]] = set()
    for workflow, meta in g["workflows"].items():
        w = ("workflow", workflow)
        nodes.add(w)
        for script in meta["effective"]:
            s = ("script", script)
            nodes.add(s)
            edges.add((w, s, "execute"))
    for script, info in g["scripts"].items():
        s = ("script", script)
        nodes.add(s)
        for artifact in info["writes"]:
            a = ("artifact", artifact)
            nodes.add(a)
            edges.add((s, a, "write"))
        for artifact in info["reads"]:
            a = ("artifact", artifact)
            nodes.add(a)
            edges.add((a, s, "read"))
    stale: set[tuple[str, str]] = set()
    for violation in g["violations"]:
        w = ("workflow", violation["workflow"])
        a = ("artifact", violation["stale_artifact"])
        nodes.update((w, a))
        stale.add(a)
        edges.add((w, a, "stale"))

    lines = ["flowchart LR",
             "  classDef workflow fill:#e7f0ff,stroke:#3265aa;",
             "  classDef script fill:#e5f6ee,stroke:#36765b;",
             "  classDef artifact fill:#fff4df,stroke:#956c20;",
             "  classDef stale fill:#ffe8e8,stroke:#c12d2d,stroke-width:2px;"]
    for kind, name in sorted(nodes):
        ident = node_id(kind, name)
        lines.append(f'  {ident}["{label(name)}"]')
        lines.append(f"  class {ident} {'stale' if (kind, name) in stale else kind};")
    symbols = {"execute": "==>", "write": "-->", "read": "-->",
               "stale": "-.->|stale|"}
    for source, target, relation in sorted(edges):
        lines.append(f"  {node_id(*source)} {symbols[relation]} {node_id(*target)}")
    return "\n".join(lines) + "\n"


def print_summary(g: dict) -> None:
    print("=" * 56)
    print("JARVIS 산출물 의존 그래프")
    print("=" * 56)
    print(f"스크립트 {len(g['scripts'])}개 · 산출물 {len(g['producers'])}개 "
          f"· 워크플로 {len(g['workflows'])}개")
    print(f"audit 이 대조하는 산출물 {len(g['audited'])}개")
    print()

    gated = [w for w, m in g["workflows"].items() if m["runs_audit"]]
    print(f"발행 시 audit 관문을 거치는 워크플로 {len(gated)}개")
    for w in gated:
        m = g["workflows"][w]
        tag = " · 대시보드 재생성" if m["regenerates_dashboard"] else ""
        print(f"  - {Path(w).name}{tag} · 스크립트 {len(m['effective'])}개")
    print()


def print_violations(g: dict) -> int:
    v = g["violations"]
    if not v:
        print("OK  재생성 순서 위반 없음")
        return 0

    print(f"위반 {len(v)}건")
    print()
    for x in v:
        print(f"  FAIL {Path(x['workflow']).name}")
        print(f"       갱신함   : {', '.join(x['upstream_updated'])}")
        print(f"       안 돌림  : {x['producer_not_run']}")
        print(f"       낡는 파일: {x['stale_artifact']}")
        print("       -> 발행 audit 이 이 불일치로 막는다.")
        print()

    print("::error::산출물 재생성 순서가 빠졌다.")
    print("::error::상위 산출물을 갱신하는 워크플로는")
    print("::error::그 파생본을 만드는 스크립트도 같이 돌려야 한다.")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="위반이 있으면 exit 1")
    ap.add_argument("--json", action="store_true",
                    help="그래프를 JSON 으로 출력")
    ap.add_argument("--mermaid", action="store_true",
                    help="정본 그래프를 Mermaid 로 stdout 에만 출력")
    ap.add_argument("--write", action="store_true",
                    help="data/artifact_graph.json 으로 저장")
    args = ap.parse_args()

    g = build_graph()

    if args.json:
        print(json.dumps(g, ensure_ascii=False, indent=2))
        return 0

    if args.mermaid:
        sys.stdout.write(render_mermaid(g))
        return 0

    if args.write:
        out = ROOT / "data" / "artifact_graph.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(g, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"저장: {out.relative_to(ROOT)}")

    print_summary(g)
    rc = print_violations(g)

    return rc if args.check else 0


if __name__ == "__main__":
    sys.exit(main())
