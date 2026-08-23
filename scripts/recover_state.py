# -*- coding: utf-8 -*-
"""중단된 리베이스를 정리하고 로컬을 원격과 합친다.

진단 결과
  - origin/main(f7c3c39)에 오늘 작업이 모두 들어 있다.
  - 로컬은 리베이스가 중간에 멈춰 작업 트리가 옛 상태로 남아 있다.
  - 로컬 커밋 2cbd809(Obsidian 볼트 편집)는 원격에 없으므로 보존해야 한다.

그래서 reset --hard 가 아니라 abort 후 merge 를 쓴다. 어느 쪽도 버리지 않는다.
"""
import json, os, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = {"steps": []}


def run(*a):
    p = subprocess.run(a, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    R["steps"].append({"cmd": " ".join(a), "rc": p.returncode,
                       "out": (p.stdout or "")[-400:], "err": (p.stderr or "")[-400:]})
    return p


in_rebase = (os.path.isdir(os.path.join(ROOT, ".git", "rebase-merge")) or
             os.path.isdir(os.path.join(ROOT, ".git", "rebase-apply")))
R["rebase_was_in_progress"] = in_rebase
if in_rebase:
    run("git", "rebase", "--abort")

run("git", "fetch", "origin", "main")
run("git", "merge", "--no-edit", "origin/main")
push = run("git", "push", "origin", "HEAD:main")
run("git", "fetch", "origin", "main")

R["push_rc"] = push.returncode
R["head"] = run("git", "rev-parse", "HEAD").stdout.strip()
R["origin_main"] = run("git", "rev-parse", "origin/main").stdout.strip()
R["status"] = run("git", "status", "--short", "-b").stdout[:600]
R["rebase_still_in_progress"] = (os.path.isdir(os.path.join(ROOT, ".git", "rebase-merge")) or
                                 os.path.isdir(os.path.join(ROOT, ".git", "rebase-apply")))

# 오늘 작업이 실제로 작업 트리에 있는지 파일로 직접 확인
def has(path, needle):
    p = os.path.join(ROOT, path)
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return needle in f.read()
    except OSError:
        return False

R["checks"] = {
    "corpus_accumulates": has("prepare_real_training_corpus.py", "load_existing"),
    "workflow_push_retry": has(".github/workflows/JARVIS-Deep-Analysis.yml", "push rejected, rebasing"),
    "liquid_glass": has("index.html", "Liquid Glass"),
    "live_right_aligned": has("index.html", "로고와 같은 크기로 헤더 오른쪽"),
    "daiso_workflow": os.path.exists(os.path.join(ROOT, ".github/workflows/daiso-real-collection.yml")),
    "daiso_collector": os.path.exists(os.path.join(ROOT, "scripts/daiso/collect_daiso.py")),
    "archive_exists": os.path.exists(os.path.join(ROOT, "archive/daiso_placeholder/README.md")),
    "fake_collector_gone": not os.path.exists(os.path.join(ROOT, "amazon_product_discovery.py")),
    "vault_obsidian_cfg": os.path.exists(os.path.join(ROOT, "obsidian/JARVIS_LUNA/.obsidian/graph.json")),
    "vault_sync_script": os.path.exists(os.path.join(ROOT, "automation/vault_sync.py")),
}
R["SUCCESS"] = (R["push_rc"] == 0 and R["head"] == R["origin_main"]
                and not R["rebase_still_in_progress"]
                and all(R["checks"].values()))

with open(os.path.join(ROOT, "diagnose.json"), "w", encoding="utf-8") as f:
    json.dump(R, f, ensure_ascii=False, indent=2)
print("SUCCESS" if R["SUCCESS"] else "CHECK diagnose.json")
