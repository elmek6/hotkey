' cascade - sessiz baslatma (konsol penceresi acilmaz).
' Cift tiklayarak calistir. Windows ile birlikte acilmasi icin
' bu dosyanin kisayolunu  shell:startup  klasorune koy.
'
' Bu dosya bir GOZETMEN: uygulamayi baslatir ve BEKLER. Normal cikista
' (kod 0, "Cikis" ya da "Yeniden baslat") sessizce biter. Uygulama HATA ile
' dolerse -- tipik olarak git pull sonrasi eksik paket -- "uv sync" ile
' bagimliliklar tazelenip BIR KEZ daha denenir; yine olmazsa hata metni
' pencerede gosterilir. Onceden hicbir kontrol yapilmaz: acilis gecikmesi
' yok, is yalnizca gercekten hata olunca yapilir.
'
' Programin kalici gunlugu TEK dosya: Files\log.txt (cascade/logs.py).
' Buradaki son-konsol.log ikinci bir gunluk DEGIL: konsol ciktisinin son
' calismaya ait kopyasi, temiz cikista siliniyor -- yalnizca cokmeden
' sonra, sebebi okunabilsin diye duruyor.
Option Explicit

Dim sh, fso, base, q, py, logf, extra, i, rc
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

base = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = base
q    = Chr(34)
' python.exe (pythonw degil): konsolu GIZLI acilir ama stderr'i vardir,
' hata metni ancak boyle log dosyasina dusuyor.
py   = base & "\.venv\Scripts\python.exe"
logf = base & "\Files\son-konsol.log"

' Uygulamanin kendi "yeniden baslat"i bizi RESTART_FLAG ile cagiriyor;
' ne gelirse main.py'ye aynen aktariliyor.
extra = ""
For i = 0 To WScript.Arguments.Count - 1
    extra = extra & " " & q & WScript.Arguments(i) & q
Next

If Not fso.FileExists(py) Then
    MsgBox "Sanal ortam bulunamadi:" & vbCrLf & base & "\.venv" & vbCrLf & vbCrLf & _
           "Kurmak icin bu klasorde su komutu calistir:" & vbCrLf & "    uv sync", _
           vbCritical, "cascade baslatilamadi"
    WScript.Quit 1
End If
If Not fso.FolderExists(base & "\Files") Then fso.CreateFolder base & "\Files"

rc = RunApp()

If rc <> 0 Then
    ' Hatayla dondu. En sik sebep: yeni surum yeni bir paket istiyor.
    ' Bagimliliklari tazele ve BIR kez daha dene.
    sh.Run "cmd /c uv sync", 0, True
    rc = RunApp()
End If

If rc = 0 Then
    ' Temiz kapanis: konsol kopyasi ortada kalmasin.
    If fso.FileExists(logf) Then fso.DeleteFile logf, True
Else
    MsgBox "cascade hata ile kapandi (cikis kodu " & rc & "):" & vbCrLf & vbCrLf & _
           Tail(logf) & vbCrLf & _
           "Konsol ciktisi: " & logf & vbCrLf & _
           "Konsolda calistirmak icin: hata-ayikla.cmd", _
           vbCritical, "cascade"
    WScript.Quit rc
End If

' --- yardimcilar ---------------------------------------------------------

' Uygulamayi penceresiz calistirir ve KAPANANA KADAR bekler.
' stderr log dosyasina yazilir. Donus: cikis kodu.
Function RunApp()
    Dim c
    c = "cmd /c " & q & q & py & q & " " & q & base & "\main.py" & q & extra & _
        " 2> " & q & logf & q & q
    RunApp = sh.Run(c, 0, True)
End Function

' Log dosyasinin son satirlarini dondurur (mesaj kutusu sismesin diye).
Function Tail(path)
    Dim t, all, lines, n, i2, out
    Tail = "(hata metni bos -- uygulama mesaj vermeden kapandi)"
    If Not fso.FileExists(path) Then Exit Function
    Set t = fso.OpenTextFile(path, 1)
    all = t.ReadAll
    t.Close
    If Trim(all) = "" Then Exit Function
    lines = Split(Replace(all, vbCrLf, vbLf), vbLf)
    n = UBound(lines)
    i2 = n - 12
    If i2 < 0 Then i2 = 0
    out = ""
    For i2 = i2 To n
        out = out & lines(i2) & vbCrLf
    Next
    Tail = out
End Function
