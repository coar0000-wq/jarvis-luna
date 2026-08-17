@echo off
chcp 65001 >nul
cd /d C:\Users\Desktop\Claude\Projects\kms

echo 🔍 Git 이전 버전들 추출 중...

for /l %%i in (1,1,20) do (
    echo ✅ HEAD~%%i 확인 중...
    git show HEAD~%%i:index.html > temp_index_%%i.html 2>nul
    if exist temp_index_%%i.html (
        echo HEAD~%%i 추출됨 >> git_extraction_log.txt
    )
)

echo ✅ 완료!
dir temp_index_*.html
pause
