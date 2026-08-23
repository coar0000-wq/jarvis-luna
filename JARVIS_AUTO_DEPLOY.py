# -*- coding: utf-8 -*-
"""JARVIS AUTO DEPLOY - commit, push to origin/main, verify remote"""
import os, subprocess, json, datetime, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
MSG = os.environ.get("JARVIS_MSG", "JARVIS: update")
R = {"time": datetime.datetime.now().isoformat(), "steps": []}


def run(*args):
    p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    R["steps"].append({"cmd": " ".join(args), "rc": p.returncode,
                       "out": (p.stdout or "")[-600:], "err": (p.stderr or "")[-600:]})
    return p


run("git", "add", "-A")
run("git", "commit", "-m", MSG)
run("git", "fetch", "origin", "main")
run("git", "merge", "--no-edit", "origin/main")
push = run("git", "push", "origin", "HEAD:main")
run("git", "fetch", "origin", "main")

R["push_returncode"] = push.returncode
R["branch"] = run("git", "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
R["local_head"] = run("git", "rev-parse", "HEAD").stdout.strip()
R["remote_head"] = run("git", "rev-parse", "origin/main").stdout.strip()
R["status"] = run("git", "status", "--short", "-b").stdout[:600]

try:
    u = "https://raw.githubusercontent.com/coar0000-wq/jarvis-luna/%s/index.html" % R["local_head"]
    html = urllib.request.urlopen(u, timeout=30).read().decode("utf-8", "replace")
    R["remote_has_living_graph"] = "hero-visual" in html and "Living Knowledge Graph" in html
    R["remote_has_hero_bg"] = "hero-bg.jpg" in html
    R["remote_broken_glyphs"] = html.count("�")
except Exception as e:
    R["remote_check_error"] = str(e)

R["SUCCESS"] = (R.get("push_returncode") == 0
                and R.get("branch") == "main"
                and R.get("local_head") == R.get("remote_head")
                and R.get("remote_has_living_graph") is True)

with open(os.path.join(ROOT, "deploy_result.json"), "w", encoding="utf-8") as f:
    json.dump(R, f, ensure_ascii=False, indent=2)
print("SUCCESS" if R["SUCCESS"] else "FAILED")
