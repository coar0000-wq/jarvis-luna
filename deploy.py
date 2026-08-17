#!/usr/bin/env python3
"""
JARVIS LUNA - GitHub Pages Auto Deploy
자동으로 로컬 파일을 GitHub에 푸시
"""

import subprocess
import os
from datetime import datetime

def run_command(cmd, cwd=None):
    """Git 명령 실행"""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd or "C:\\Users\\Desktop\\Claude\\Projects\\kms",
            capture_output=True,
            text=True,
            encoding='utf-8'
        )
        return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        return False, "", str(e)

def main():
    repo_path = "C:\\Users\\Desktop\\Claude\\Projects\\kms"

    print("=" * 60)
    print("JARVIS LUNA - GitHub Pages Auto Deploy")
    print("=" * 60)
    print()

    # 1. Git status 확인
    print("1️⃣  Checking repository status...")
    success, stdout, stderr = run_command("git status", repo_path)
    if not success:
        print(f"❌ Error: {stderr}")
        return False
    print("✅ Repository status OK")
    print()

    # 2. Add files
    print("2️⃣  Adding files to staging...")
    commands_to_add = [
        "git add index.html",
        "git add dashboard.html",
        "git add data/",
        "git add .gitignore",
    ]

    for cmd in commands_to_add:
        success, stdout, stderr = run_command(cmd, repo_path)
        if success:
            print(f"  ✅ {cmd}")
        else:
            print(f"  ⚠️  {cmd}")
    print()

    # 3. Commit
    print("3️⃣  Creating commit...")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    commit_message = f"🚀 JARVIS LUNA - Deploy to GitHub Pages ({timestamp})"
    commit_cmd = f'git commit -m "{commit_message}"'

    success, stdout, stderr = run_command(commit_cmd, repo_path)
    if success:
        print(f"✅ Commit created")
        print(f"   Message: {commit_message}")
    else:
        print(f"⚠️  Commit: {stderr}")
    print()

    # 3.5 Pull from GitHub (sync)
    print("3️⃣️.5️⃣  Syncing with GitHub...")
    pull_cmd = "git pull origin main"
    success, stdout, stderr = run_command(pull_cmd, repo_path)
    if success:
        print("✅ Pulled latest changes from GitHub")
    else:
        print(f"⚠️  Pull: {stderr[:100]}")
    print()

    # 4. Push to GitHub
    print("4️⃣  Pushing to GitHub...")
    push_cmd = "git push origin main"
    success, stdout, stderr = run_command(push_cmd, repo_path)

    if success:
        print("✅ Push successful!")
        print()
        print("=" * 60)
        print("🎉 Deployment Complete!")
        print("=" * 60)
        print()
        print("📊 Status:")
        print("  ✅ Files added to staging")
        print("  ✅ Changes committed")
        print("  ✅ Pushed to GitHub (main branch)")
        print()
        print("🌐 Website URL:")
        print("  https://coar0000-wq.github.io/jarvis-luna/")
        print()
        print("⏳ Next steps:")
        print("  1. GitHub Pages build in progress (5-10 minutes)")
        print("  2. Visit the URL above to see the site")
        print("  3. Check https://github.com/coar0000-wq/jarvis-luna/actions for build status")
        print()
        return True
    else:
        print(f"❌ Push failed: {stderr}")
        print()
        print("⚠️  Troubleshooting:")
        print("  - Check network connection")
        print("  - Verify GitHub credentials")
        print("  - Check repository permissions")
        print()
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
