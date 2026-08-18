# 관리자 권한 확인 및 상승
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "관리자 권한이 필요합니다. 관리자 권한으로 재시작합니다..." -ForegroundColor Yellow
    Start-Process powershell.exe -ArgumentList "-ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
    exit
}

# 작업 스케줄러 등록 스크립트 (10분마다 Python 스크립트 실행)
try {
    $TaskName = "JARVIS-CumulativeProductsUpdate"
    $PythonScriptPath = "C:\Users\Desktop\Claude\Projects\kms\update_cumulative_products.py"
    $WorkingDirectory = "C:\Users\Desktop\Claude\Projects\kms"

    # 기존 등록된 동일 이름의 작업이 있다면 삭제
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

    # 작업 동작 설정 (Python 스크립트 실행)
    $Action = New-ScheduledTaskAction -Execute "python.exe" -Argument "`"$PythonScriptPath`"" -WorkingDirectory $WorkingDirectory

    # 작업 트리거 설정 (10분마다 반복, 지금 시작)
    $Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Days 365)

    # 작업 설정 (최고 권한으로 실행)
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 0) -StartWhenAvailable

    # 작업 스케줄러에 등록
    Register-ScheduledTask -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -RunLevel Highest `
        -Description "매 10분마다 cumulative_products.json 업데이트 (공식: 117 + 현재시간×4 + 날짜×2)" `
        -Force

    Write-Host "✅ 작업 스케줄러 등록이 완료되었습니다: $TaskName" -ForegroundColor Green
    Write-Host "   작업명: $TaskName"
    Write-Host "   반복: 10분마다"
    Write-Host "   Python 스크립트: $PythonScriptPath"
    Write-Host "   작업 디렉토리: $WorkingDirectory"
    Write-Host "   권한: Highest (관리자)"
    Write-Host ""
    Write-Host "🚀 수동으로 작업을 실행하려면:"
    Write-Host "   Start-ScheduledTask -TaskName '$TaskName'"
}
catch {
    Write-Host "❌ 에러 발생: $_" -ForegroundColor Red
}

Pause
