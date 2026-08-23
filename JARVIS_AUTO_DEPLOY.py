# -*- coding: utf-8 -*-
<<<<<<< HEAD
"""JARVIS AUTO DEPLOY - workflow cleanup + git push + verify"""
import os, subprocess, json, datetime, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
WF = os.path.join(ROOT, ".github", "workflows")
LOG = os.path.join(ROOT, "deploy_result.json")
=======
"""JARVIS AUTO DEPLOY - commit, push to origin/main, verify remote"""
import os, subprocess, json, datetime, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
MSG = os.environ.get("JARVIS_MSG") or "JARVIS: cumulative ledger for records/notes/links"
>>>>>>> origin/main
R = {"time": datetime.datetime.now().isoformat(), "steps": []}


def run(*args):
    p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    R["steps"].append({"cmd": " ".join(args), "rc": p.returncode,
<<<<<<< HEAD
                       "out": (p.stdout or "")[-1500:], "err": (p.stderr or "")[-1500:]})
    return p


# 1) disable duplicate workflows (.yml that already has a .yml.disabled twin)
disabled = []
for f in os.listdir(WF):
    if f.endswith(".yml") and os.path.exists(os.path.join(WF, f + ".disabled")):
        os.remove(os.path.join(WF, f))
        disabled.append(f)

# 2) disable jekyll pages build (it hijacks GitHub Pages deployment)
jk = os.path.join(WF, "jekyll-gh-pages.yml")
if os.path.exists(jk):
    tgt = jk + ".disabled"
    if os.path.exists(tgt):
        os.remove(jk)
    else:
        os.rename(jk, tgt)
    disabled.append("jekyll-gh-pages.yml")

# 3) .nojekyll so Pages serves raw files
nj = os.path.join(ROOT, ".nojekyll")
if not os.path.exists(nj):
    open(nj, "w").close()

R["disabled_workflows"] = sorted(set(disabled))

# 4) git commit + push
run("git", "config", "user.name", "JARVIS LUNA")
run("git", "config", "user.email", "coar0000@naver.com")
run("git", "add", "-A")
run("git", "commit", "-m",
    "JARVIS: hero section deploy + workflow cleanup + .nojekyll")
run("git", "fetch", "origin", "main")
run("git", "pull", "--rebase", "origin", "main")
push = run("git", "push", "origin", "HEAD:main")
R["push_returncode"] = push.returncode
R["local_head"] = run("git", "rev-parse", "HEAD").stdout.strip()
R["remote_head"] = run("git", "rev-parse", "origin/main").stdout.strip()

# 5) verify remote actually has the hero section
try:
    u = "https://raw.githubusercontent.com/coar0000-wq/jarvis-luna/main/index.html"
    html = urllib.request.urlopen(u, timeout=30).read().decode("utf-8", "replace")
    R["remote_has_hero_bg"] = "hero-bg.jpg" in html
    R["remote_title"] = html.split("<title>")[1].split("</title>")[0] if "<title>" in html else "?"
except Exception as e:
    R["remote_check_error"] = str(e)

R["SUCCESS"] = R.get("push_returncode") == 0 and R.get("local_head") == R.get("remote_head")

with open(LOG, "w", encoding="utf-8") as f:
=======
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
    R["remote_has_hero_bg"] = "hero-bg.jpg" in html
    R["remote_reads_runtime_json"] = "data/dashboard_runtime.json" in html
    R["remote_canvas_removed"] = "knowledge-graph" not in html
    R["remote_broken_glyphs"] = html.count("�")
except Exception as e:
    R["remote_check_error"] = str(e)

R["SUCCESS"] = (R.get("push_returncode") == 0
                and R.get("branch") == "main"
                and R.get("local_head") == R.get("remote_head")
                and R.get("remote_has_hero_bg") is True
                and R.get("remote_reads_runtime_json") is True
                and R.get("remote_broken_glyphs") == 0)

with open(os.path.join(ROOT, "deploy_result.json"), "w", encoding="utf-8") as f:
>>>>>>> origin/main
    json.dump(R, f, ensure_ascii=False, indent=2)
print("SUCCESS" if R["SUCCESS"] else "FAILED")
