"""
jarvis_deep_analysis.py - FULL FILE 전체 덮어쓰기용
CLAUDE.md: gosi + 다이소 + 웹채널 -> Gemini url_context + Deep Analysis -> Pages 배포
1번, 2번, 3번 수정본 포함 전체 실행 + push + 보고 (Rule 3)
"""
import json, datetime, subprocess
from pathlib import Path
ROOT = Path(__file__).parent

def run(cmd, timeout=180):
    print(f"\n$ {cmd}")
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        print(r.stdout[-2000:])
        if r.stderr:
            print(f"STDERR: {r.stderr[-1000:]}")
        return r.returncode == 0, r.stdout + r.stderr
    except Exception as e:
        print(f"❌ 실패: {e}")
        return False, str(e)

def main():
    print("🚀 JARVIS 심층분석 시작")
    steps = []
    for f in ["gosi_collector.py", "product_discovery.py", "inci_converter.py", "generate_dashboard_runtime.py"]:
        print(f"{'✅' if (ROOT / f).exists() else '❌'} {f}")

    print("\n=== 1단계: gosi.json 수집 ===")
    ok, _ = run("python gosi_collector.py")
    steps.append(("gosi", ok))

    print("\n=== 2단계: Product Discovery 수집 ===")
    ok, _ = run("python product_discovery.py")
    steps.append(("product", ok))

    print("\n=== 3단계: INCI S 7 -> EN 7 ===")
    ok, _ = run("python inci_converter.py")
    steps.append(("inci", ok))

    print("\n=== 4단계: Shopify ===")
    ok, _ = run("python shopify_uploader.py")
    steps.append(("shopify", ok))

    print("\n=== 5단계: Dashboard Runtime v3.0 ===")
    ok, _ = run("python generate_dashboard_runtime.py")
    steps.append(("runtime", ok))

    print("\n=== 6단계: Push (CLAUDE.md Rule 3) ===")
    for cmd in ["git status", "git diff --stat", "git add -A", f'git commit -m "feat: JARVIS Deep Analysis {datetime.datetime.utcnow().strftime("%Y-%m-%d")} - auto"', "git push origin main", "git log -1 --oneline"]:
        run(cmd, timeout=60)

    print("\n📋 최종 보고")
    print("Actions: https://github.com/coar0000-wq/jarvis-luna/actions")
    print("Pages: https://coar0000-wq.github.io/jarvis-luna/")
    for name, ok in steps:
        print(f"{'✅' if ok else '❌'} {name}")

if __name__ == "__main__":
    main()
