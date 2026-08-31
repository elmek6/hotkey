' cascade - sessiz baslatma (konsol penceresi acilmaz).
' Cift tiklayarak calistir. Windows ile birlikte acilmasi icin
' bu dosyanin kisayolunu  shell:startup  klasorune koy.
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = base
sh.Run """" & base & "\.venv\Scripts\pythonw.exe"" """ & base & "\main.py""", 0, False
