# ?쨼 JARVIS ?먮룞??諛고룷 ?ㅽ겕由쏀듃

Write-Host "?? JARVIS ?먮룞???쒖뒪??諛고룷 ?쒖옉..." -ForegroundColor Cyan

# Git 而ㅻ컠
Write-Host "`n?뱷 Git 而ㅻ컠 以?.." -ForegroundColor Yellow
git add -A
git commit -m "?쨼 JARVIS ?ㅼ젣 ?먮룞???쒖뒪??(GitHub Actions 留?10遺?" -q

if ($LASTEXITCODE -eq 0) {
    Write-Host "??而ㅻ컠 ?꾨즺" -ForegroundColor Green
} else {
    Write-Host "?좑툘 而ㅻ컠 ?ㅽ뙣 (蹂寃쎌궗???놁쓬 媛??" -ForegroundColor Yellow
}

# Git ?몄떆
Write-Host "`n?뱾 GitHub濡??몄떆 以?.." -ForegroundColor Yellow
git push origin main -q

if ($LASTEXITCODE -eq 0) {
    Write-Host "???몄떆 ?꾨즺" -ForegroundColor Green
} else {
    Write-Host "???몄떆 ?ㅽ뙣" -ForegroundColor Red
    exit 1
}

# 諛고룷 ?뺣낫 ?쒖떆
Write-Host "`n" -ForegroundColor Cyan
Write-Host "?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?? -ForegroundColor Cyan
Write-Host "??JARVIS ?먮룞???쒖뒪??諛고룷 ?꾨즺!" -ForegroundColor Green
Write-Host "?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?? -ForegroundColor Cyan

Write-Host "`n?뱤 ?먮룞???쒖뒪???뺣낫:" -ForegroundColor Cyan
Write-Host "  ???ㅽ뻾 鍮덈룄: 留?10遺꾨쭏?? -ForegroundColor White
Write-Host "  ???뚰겕?뚮줈?? .github/workflows/jarvis_automation.yml" -ForegroundColor White
Write-Host "  ???ㅽ겕由쏀듃: scripts/jarvis_automation_real.py" -ForegroundColor White
Write-Host "  ???곗씠?? data/jarvis_work_detailed_log.json" -ForegroundColor White

Write-Host "`n?뵕 GitHub Actions ?뺤씤:" -ForegroundColor Cyan
Write-Host "  https://github.com/coar0000-wq/jarvis-luna/actions" -ForegroundColor Cyan

Write-Host "`n?뱢 ??쒕낫??" -ForegroundColor Cyan
Write-Host "  https://coar0000-wq.github.io/jarvis-luna/" -ForegroundColor Cyan

Write-Host "`n???ㅼ쓬 ?먮룞 ?ㅽ뻾:" -ForegroundColor Yellow
$nextRun = [Math]::Ceiling((Get-Date).Minute / 10) * 10
if ($nextRun -eq 60) { $nextRun = 0 }
Write-Host "  ??$($nextRun)遺??대궡" -ForegroundColor Yellow

Write-Host "`n???쒖뒪?쒖씠 ?뺤긽 ?묐룞?섍퀬 ?덉뒿?덈떎!" -ForegroundColor Green


