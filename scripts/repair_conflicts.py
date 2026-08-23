# -*- coding: utf-8 -*-
"""충돌 표식이 커밋된 파일을 정확한 원본으로 되돌린다.

앞선 복구 스크립트가 충돌 난 병합을 `git add -A` 로 그대로 커밋해 버려
index.html 등에 <<<<<<< 표식이 들어갔다. 파일별로 올바른 출처를 지정해
체크아웃하고, 표식이 하나도 남지 않은 것을 확인한 뒤에만 푸시한다.

  index.html, 배포 스크립트  -> e3b12dc (마지막으로 화면 확인까지 끝낸 커밋)
  data/*.json               -> f7c3c39 (파이프라인 봇이 만든 최신 산출물)
"""
import json, os, re, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = {"steps": [], "restored": {}}

SOURCES = {
    "e3b12dc": ["index.html", "JARVIS_AUTO_DEPLOY.py", "JARVIS_AUTO_DEPLOY.bat"],
    "f7c3c39": ["data/scheduler_log.json", "data/phase_26_progress.json",
                "data/google_search_results/google_search_results.json",
                "data/dropshipping_analysis/youtube_dropshipping_analysis.json"],
}
MARKER = re.compile(r"^(<{7} |={7}$|>{7} )", re.M)


def run(*a):
    p = subprocess.run(a, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    R["steps"].append({"cmd": " ".join(a), "rc": p.returncode,
                       "out": (p.stdout or "")[-250:], "err": (p.stderr or "")[-250:]})
    return p


for commit, paths in SOURCES.items():
    for rel in paths:
        rc = run("git", "checkout", commit, "--", rel).returncode
        R["restored"][rel] = {"from": commit, "rc": rc}

# 저장소 전체에서 표식이 남았는지 확인
remaining = []
for base, dirs, names in os.walk(ROOT):
    dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "node_modules", "archive")]
    for n in names:
        if not n.endswith((".html", ".py", ".json", ".yml", ".md", ".css", ".js", ".bat", ".ps1")):
            continue
        p = os.path.join(base, n)
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                if MARKER.search(f.read()):
                    remaining.append(os.path.relpath(p, ROOT).replace("\\", "/"))
        except OSError:
            pass
R["markers_remaining"] = remaining

if not remaining:
    run("git", "add", "-A")
    run("git", "commit", "-m", "JARVIS: repair files that captured merge conflict markers")
    push = run("git", "push", "origin", "HEAD:main")
    R["push_rc"] = push.returncode
else:
    R["push_rc"] = None

run("git", "fetch", "origin", "main")
R["head"] = run("git", "rev-parse", "HEAD").stdout.strip()
R["origin_main"] = run("git", "rev-parse", "origin/main").stdout.strip()


def has(path, needle):
    try:
        with open(os.path.join(ROOT, path), encoding="utf-8", errors="replace") as f:
            return needle in f.read()
    except OSError:
        return False


R["checks"] = {
    "no_markers": not remaining,
    "liquid_glass": has("index.html", "Liquid Glass"),
    "live_right": has("index.html", "로고와 같은 크기로 헤더 오른쪽"),
    "md_family": has("index.html", "MD family"),
    "data_detail": has("index.html", "renderDataDetail"),
    "corpus_accumulates": has("prepare_real_training_corpus.py", "load_existing"),
    "workflow_retry": has(".github/workflows/JARVIS-Deep-Analysis.yml", "push rejected, rebasing"),
    "vault_cfg": os.path.exists(os.path.join(ROOT, "obsidian/JARVIS_LUNA/.obsidian/graph.json")),
    "synced": R["head"] == R["origin_main"],
}
R["SUCCESS"] = all(R["checks"].values()) and R.get("push_rc") == 0

with open(os.path.join(ROOT, "recover_report.json"), "w", encoding="utf-8") as f:
    json.dump(R, f, ensure_ascii=False, indent=2)
print("SUCCESS" if R["SUCCESS"] else "CHECK recover_report.json")
