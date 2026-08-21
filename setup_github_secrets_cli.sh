#!/bin/bash
# GitHub Secrets 자동 설정 (GitHub CLI 사용)

echo "🔐 GitHub Secrets 자동 설정 시작..."
echo "=================================="

# GitHub CLI 확인
if ! command -v gh &> /dev/null; then
    echo "❌ GitHub CLI가 설치되지 않았습니다."
    echo "📥 설치: https://cli.github.com"
    exit 1
fi

# 인증 확인
echo "🔍 GitHub 인증 확인 중..."
if ! gh auth status &> /dev/null; then
    echo "❌ GitHub에 로그인하지 않았습니다."
    echo "🔐 다음 명령어로 로그인하세요:"
    echo "   gh auth login"
    exit 1
fi

echo "✅ GitHub 인증 확인 완료"

# Repository 설정
REPO="coar0000/kms"

echo ""
echo "🔧 Secrets 설정 중..."
echo "Repository: $REPO"

# SENDER_EMAIL 설정
echo ""
echo "1️⃣ SENDER_EMAIL 추가 중..."
echo "coar1004@naver.com" | gh secret set SENDER_EMAIL --repo $REPO --body-from -

if [ $? -eq 0 ]; then
    echo "✅ SENDER_EMAIL 설정 완료"
else
    echo "❌ SENDER_EMAIL 설정 실패"
    exit 1
fi

# EMAIL_PASSWORD 설정
echo ""
echo "2️⃣ EMAIL_PASSWORD 추가 중..."
echo "EHgus123!" | gh secret set EMAIL_PASSWORD --repo $REPO --body-from -

if [ $? -eq 0 ]; then
    echo "✅ EMAIL_PASSWORD 설정 완료"
else
    echo "❌ EMAIL_PASSWORD 설정 실패"
    exit 1
fi

# 확인
echo ""
echo "📋 설정된 Secrets 확인 중..."
gh secret list --repo $REPO

echo ""
echo "=================================="
echo "🎉 GitHub Secrets 설정 완료!"
echo "=================================="
echo ""
echo "✅ 설정 완료:"
echo "   - SENDER_EMAIL: coar1004@naver.com"
echo "   - EMAIL_PASSWORD: [설정됨]"
echo ""
echo "🚀 자동화 시작:"
echo "   - 5일마다 자동 실행"
echo "   - 다음 발송: 2026-08-22"
echo ""
