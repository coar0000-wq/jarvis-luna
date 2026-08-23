# -*- coding: utf-8 -*-
"""읽기 전용 진단. 저장소 상태를 확인만 하고 아무것도 바꾸지 않는다."""
import json, subprocess, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = {}


def run(*a):
    p = subprocess.run(a, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return (p.stdout or p.stderr or "").strip()


out["branch"] = run("git", "rev-parse", "--abbrev-ref", "HEAD")
out["head"] = run("git", "rev-parse", "HEAD")
out["origin_main"] = run("git", "rev-parse", "origin/main")
out["log_head"] = run("git", "log", "--oneline", "-8").splitlines()
out["log_origin"] = run("git", "log", "--oneline", "-8", "origin/main").splitlines()
out["reflog"] = run("git", "reflog", "-18").splitlines()
out["status"] = run("git", "status", "--short", "-b").splitlines()[:25]
out["rebase_in_progress"] = os.path.isdir(os.path.join(ROOT, ".git", "rebase-merge")) or \
                            os.path.isdir(os.path.join(ROOT, ".git", "rebase-apply"))
out["stash"] = run("git", "stash", "list").splitlines()
out["ahead_behind"] = run("git", "rev-list", "--left-right", "--count", "HEAD...origin/main")

# 최신 작업물이 원격에 있는지 표식으로 확인
for probe, path in [("corpus_accumulates", "prepare_real_training_corpus.py"),
                    ("workflow_retry", ".github/workflows/JARVIS-Deep-Analysis.yml"),
                    ("liquid_glass", "index.html")]:
    txt = run("git", "show", "origin/main:" + path)
    out[probe + "_on_origin"] = any(k in txt for k in
                                    ["load_existing", "push rejected, rebasing", "Liquid Glass"])

with open(os.path.join(ROOT, "diagnose.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("written")
