#!/bin/bash

# ========================================
# JARVIS LUNA GitHub 자동 푸시 스크립트
# ========================================

# 변수 설정
REPO_PATH="/c/Users/Desktop/Claude/Projects/kms"
COMMIT_MESSAGE="Complete: JSON.parse + array order + date format + background unified"
BRANCH="main"

echo "========================================"
echo "🚀 JARVIS LUNA GitHub 푸시 시작"
echo "========================================"
echo ""

# 디렉토리 이동
echo "📁 저장소 경로: $REPO_PATH"
cd "$REPO_PATH"

if [ ! -d ".git" ]; then
    echo "❌ Git 저장소가 아닙니다!"
    exit 1
fi

# Git 상태 확인
echo ""
echo "📊 Git 상태 확인 중..."
git status

# 모든 변경사항 스테이징
echo ""
echo "📝 변경사항 스테이징..."
git add .

# 커밋
echo ""
echo "💾 커밋 생성: $COMMIT_MESSAGE"
git commit -m "$COMMIT_MESSAGE"

if [ $? -eq 0 ]; then
    echo "✅ 커밋 성공"
else
    echo "⚠️ 커밋 실패 (변경사항 없음일 수 있음)"
fi

# 푸시
echo ""
echo "🚀 $BRANCH 브랜치로 푸시 중..."
git push origin "$BRANCH"

if [ $? -eq 0 ]; then
    echo "✅ 푸시 성공!"
    echo ""
    echo "📊 최종 상태:"
    git log --oneline -n 3
else
    echo "❌ 푸시 실패"
    echo ""
    echo "💡 해결 방법:"
    echo "  1. git pull --rebase origin $BRANCH"
    echo "  2. 충돌 해결"
    echo "  3. git push origin $BRANCH"
fi

echo ""
echo "========================================"
echo "✨ 완료!"
echo "========================================"
