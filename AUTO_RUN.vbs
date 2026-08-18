' VBScript - Phase 26 MoE Auto Push Execution
' 더블클릭하면 자동으로 Python 스크립트 실행
' Author: JARVIS
' Date: 2026-08-18

' ============================================================================
' Configuration
' ============================================================================

Dim shell, fso, repo_path, cmd, result, objShell, objExec

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

repo_path = "C:\Users\Desktop\Claude\Projects\kms"
cmd = "cd /d " & repo_path & " && python auto_push_final.py"

' ============================================================================
' Main Execution
' ============================================================================

' Check if repository exists
If Not fso.FolderExists(repo_path) Then
    MsgBox "❌ ERROR: Repository path not found!" & vbCrLf & vbCrLf & _
           "Expected: " & repo_path, vbExclamation, "Path Error"
    WScript.Quit 1
End If

' Check if Python script exists
If Not fso.FileExists(repo_path & "\auto_push_final.py") Then
    MsgBox "❌ ERROR: auto_push_final.py not found!" & vbCrLf & vbCrLf & _
           "Expected: " & repo_path & "\auto_push_final.py", vbExclamation, "Script Error"
    WScript.Quit 1
End If

' Display notification
MsgBox "🚀 Phase 26 MoE Auto Push Started!" & vbCrLf & vbCrLf & _
       "📋 Task: GitHub Push + Test Execution" & vbCrLf & vbCrLf & _
       "⏱️  Estimated time: 1-2 minutes" & vbCrLf & vbCrLf & _
       "A new window will open with detailed output.", _
       vbInformation, "Phase 26 MoE Auto Execution"

' Execute command in new CMD window (visible)
On Error Resume Next
shell.Run "cmd /k " & cmd, 1, False
On Error GoTo 0

' Display completion message after delay
WScript.Sleep 2000

MsgBox "✅ Auto Execution Started!" & vbCrLf & vbCrLf & _
       "📊 A command window opened with detailed output." & vbCrLf & vbCrLf & _
       "📈 After execution completes:" & vbCrLf & _
       "   1. Check GitHub: https://github.com/coar0000/kms/commits/main" & vbCrLf & _
       "   2. Wait 1-2 minutes for GitHub Pages update" & vbCrLf & _
       "   3. Verify all tests passed (10/10)" & vbCrLf & vbCrLf & _
       "💡 The command window will remain open for you to review the output.", _
       vbInformation, "Execution Complete"
