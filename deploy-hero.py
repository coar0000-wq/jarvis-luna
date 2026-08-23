#!/usr/bin/env python3
import os
import shutil
import subprocess
import sys

# Configuration
project_path = r"C:\Users\Desktop\Claude\Projects\kms\jarvis-luna"
source_image = r"C:\Users\Desktop\Claude\Projects\kms\images\111.jpg"
dest_image = os.path.join(project_path, "hero-bg.jpg")

print("\n" + "=" * 50)
print("JARVIS-LUNA Hero Section Deploy")
print("=" * 50 + "\n")

try:
    # Step 1: Copy image
    print("Step 1: Copy hero background image...")
    shutil.copy2(source_image, dest_image)
    print(f"✓ Image copied: hero-bg.jpg\n")

    # Step 2: Change to project directory
    print("Step 2: Change to project directory...")
    os.chdir(project_path)
    print(f"✓ Working directory: {project_path}\n")

    # Step 3: Git status
    print("Step 3: Check git status...")
    result = subprocess.run(["git", "status"], capture_output=True, text=True)
    print(result.stdout + "\n")

    # Step 4: Git add
    print("Step 4: Stage files...")
    subprocess.run(["git", "add", "index.html", "hero-bg.jpg"], check=True)
    print("✓ Files staged for commit\n")

    # Step 5: Git commit
    print("Step 5: Commit changes...")
    subprocess.run(["git", "commit", "-m", "Update hero section: wine cellar background + white text + new styling"], check=True)
    print("✓ Changes committed\n")

    # Step 6: Git push
    print("Step 6: Push to GitHub...")
    subprocess.run(["git", "push", "origin", "main"], check=True)
    print("✓ GitHub push completed\n")

    # Step 7: Verify
    print("Step 7: Final verification...")
    result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
    commit_hash = result.stdout.strip()

    result = subprocess.run(["git", "log", "-1", "--format=%B"], capture_output=True, text=True)
    commit_message = result.stdout.strip()

    print(f"✓ Commit hash: {commit_hash}")
    print(f"  Message: {commit_message}\n")

    print("=" * 50)
    print("Deploy Complete! ✓")
    print("=" * 50)
    print("Website: https://coar0000-wq.github.io/jarvis-luna/")
    print("Expected update time: 5-10 minutes")
    print("\n")

except Exception as e:
    print(f"\n❌ Error: {e}\n")
    sys.exit(1)
