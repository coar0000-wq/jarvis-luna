@echo off
cd /d C:\Users\Desktop\Claude\Projects\kms

echo Step 1: Fetch remote...
git fetch origin

echo Step 2: Reset to remote...
git reset --hard origin/main

echo Step 3: Add changes...
git add jarvis_luna_complete.py requirements.txt .github/workflows/jarvis-luna-deploy.yml

echo Step 4: Commit...
git commit -m "JARVIS LUNA Groq Edition"

echo Step 5: Force push...
git push -f origin main

echo COMPLETE!
echo Add GROQ_API_KEY to GitHub Secrets
pause
