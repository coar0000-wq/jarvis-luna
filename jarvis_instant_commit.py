#!/usr/bin/env python3
import subprocess
import os

os.chdir(r"C:\Users\Desktop\Claude\Projects\kms")

print("\n" + "="*80)
print("🔥 JARVIS - 웹사이트 경로 수정 즉시 커밋 및 푸시")
print("="*80)

cmds = [
    ("git add index.html", "index.html 스테이징"),
    ('git commit -m "🔥 FIX: 웹사이트 경로 jarvis-agi → jarvis-luna (실시간 데이터 연동)"', "커밋"),
    ("git pull --rebase origin main", "Pull with rebase"),
    ("git push origin main", "GitHub 푸시"),
    ("git log --oneline -3", "최종 커밋 확인"),
]

for cmd, desc in cmds:
    print(f"\n✅ {desc}")
    print(f"   명령: {cmd}")
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=30)
        if result.stdout:
            for line in result.stdout.strip().split('\n')[:5]:
                print(f"   {line}")
        if result.returncode != 0 and result.stderr:
            print(f"   ⚠️  {result.stderr[:150]}")
    except Exception as e:
        print(f"   ❌ {e}")

print("\n" + "="*80)
print("✅ 완료! GitHub 푸시 성공")
print("="*80)
print("\n📊 다음:")
print("   1. CDN 갱신 대기 (1-5분)")
print("   2. https://coar0000-wq.github.io/jarvis-luna/ 새로고침")
print("\n" + "="*80 + "\n")
