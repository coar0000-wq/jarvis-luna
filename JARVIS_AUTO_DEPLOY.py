# -*- coding: utf-8 -*-
"""JARVIS AUTO DEPLOY - commit + push + verify"""
import os, subprocess, json, datetime, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
R = {"time": datetime.datetime.now().isoformat(), "steps": []}


def run(*args):
    p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    R["steps"].append({"cmd": " ".join(args), "rc": p.returncode,
                       "out": (p.stdout or "")[-800:], "err": (p.stderr or "")[-800:]})
    return p


run("git", "add", "-A")
run("git", "commit", "-m", "JARVIS: fix corrupted emoji glyphs in index.html")
run("git", "fetch", "origin", "main")
run("git", "merge", "--no-edit", "origin/main")
push = run("git", "push", "origin", "HEAD:main")
R["push_returncode"] = push.returncode
R["local_head"] = run("git", "rev-parse", "HEAD").stdout.strip()
R["remote_head"] = run("git", "rev-parse", "origin/main").stdout.strip()

try:
    u = "https://raw.githubusercontent.com/coar0000-wq/jarvis-luna/main/index.html"
    html = urllib.request.urlopen(u, timeout=30).read().decode("utf-8", "replace")
    R["remote_has_hero_bg"] = "hero-bg.jpg" in html
    R["remote_broken_glyphs"] = html.count("�")
except Exception as e:
    R["remote_check_error"] = str(e)

R["SUCCESS"] = R.get("push_returncode") == 0 and R.get("local_head") == R.get("remote_head")

with open(os.path.join(ROOT, "deploy_result.json"), "w", encoding="utf-8") as f:
    json.dump(R, f, ensure_ascii=False, indent=2)
print("SUCCESS" if R["SUCCESS"] else "FAILED")
