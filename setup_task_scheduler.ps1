$TaskName = "JARVIS-CumulativeProductsUpdate"
$ScriptDir = "C:\Users\Desktop\Claude\Projects\kms"
$ScriptPath = Join-Path $ScriptDir "update_cumulative_products.py"
$PythonPath = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if (-not $PythonPath) { $PythonPath = "C:\Python311\python.exe" }
try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    $Action = New-ScheduledTaskAction -Execute $PythonPath -Argument ""$ScriptPath"" -WorkingDir $ScriptDir
    $Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 10)
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -User "NT AUTHORITY\SYSTEM" -RunLevel Highest -Force
    Write-Host "작업 스케줄러 등록 성공: $TaskName (10분 주기)" -ForegroundColor Green
} catch {
    Write-Host "에러 발생: $_" -ForegroundColor Red
}
