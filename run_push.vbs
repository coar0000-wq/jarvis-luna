' JARVIS LUNA GitHub 자동 푸시 (VBScript)
' 이 파일을 더블클릭하면 자동으로 푸시 실행

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

' 작업 디렉토리
strPath = "C:\Users\Desktop\Claude\Projects\kms"

' 배치 파일 경로
strBatchFile = strPath & "\push-to-github.bat"

' 배치 파일 존재 확인
If objFSO.FileExists(strBatchFile) Then
    ' 배치 파일 실행
    objShell.Run """" & strBatchFile & """", 1, False
Else
    MsgBox "푸시 스크립트를 찾을 수 없습니다: " & strBatchFile, vbCritical, "오류"
End If
