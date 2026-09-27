' ============================================================
'  Project Radar launcher (double-click on Desktop shortcut)
'  1. If the radar server is not running, start it silently
'     with pythonw; the app then opens its own native window
'     (pywebview) and a taskbar-tray icon.
'  2. If the server is already running (window was closed to
'     tray), just wake the window up via /api/show.
'  This file must stay pure ASCII: it derives its own folder
'  from WScript.ScriptFullName, so no Chinese literals here.
' ============================================================
Option Explicit

Dim shell, fso, baseDir, script, pyExe, pywExe, port, url
Dim http, started, i

port = 8618
url = "http://127.0.0.1:" & port & "/"

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' --- locate program folder (this .vbs lives inside it) ---
script = WScript.ScriptFullName
baseDir = fso.GetParentFolderName(script)

' --- locate python / pythonw (D:\Programs\Python311 preferred) ---
pyExe = "D:\Programs\Python311\python.exe"
pywExe = "D:\Programs\Python311\pythonw.exe"
If Not fso.FileExists(pywExe) Then
    pywExe = baseDir & "\pythonw.exe"
End If
If Not fso.FileExists(pyExe) Then
    pyExe = "python.exe"
End If
If Not fso.FileExists(pywExe) Then
    pywExe = pyExe
End If

' --- if server already answers, wake the window and exit ---
Function ServerUp()
    On Error Resume Next
    Set http = CreateObject("MSXML2.XMLHTTP")
    http.open "GET", url & "api/status", False
    http.send
    If Err.Number <> 0 Then
        Err.Clear
        ServerUp = False
    Else
        ServerUp = (http.status = 200)
    End If
    On Error Goto 0
End Function

If ServerUp() Then
    ' bring the existing window back from the tray
    On Error Resume Next
    Set http = CreateObject("MSXML2.XMLHTTP")
    http.open "GET", url & "api/show", False
    http.send
    On Error Goto 0
    WScript.Quit 0
End If

' --- cold start: run the app (its own window appears) ---
shell.Run """" & pywExe & """ """ & baseDir & "\project_radar.py""", 0, False

' wait up to 15 seconds for the HTTP service to come up
started = False
For i = 1 To 60
    WScript.Sleep 250
    If ServerUp() Then
        started = True
        Exit For
    End If
Next
If Not started Then
    MsgBox "Project Radar did not start within 15s." & vbCrLf & _
           "Check log: " & baseDir & "\radar.log", 16, "Project Radar"
    WScript.Quit 1
End If
