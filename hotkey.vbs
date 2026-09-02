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
' HATA AYIKLAMA DA BURADA. Ayri bir .cmd yok: cokme kutusundan "Evet"
' denince ayni komut GORUNUR konsolda yeniden calisir. Sebebi, ayri
' dosyanin kanitla bulusmamasiydi -- kullanici konsolu actiginda hata
' coktan gecmis oluyordu.
'
' Programin kalici gunlugu TEK dosya: Files\log.txt (cascade/logs.py).
' Buradaki son-konsol.log ikinci bir gunluk DEGIL: CALISAN surecin konsol
' ciktisi, temiz cikista siliniyor. Cokme aninda kopyasi
' Files\hata-<tarih-saat>.log olarak SAKLANIR (son KEEP_CRASH tanesi):
' silinip gitmesi, cokmeyi sonradan incelemeyi imkansiz kiliyordu --
' sonraki temiz calisma kanitin uzerine yaziyordu.
Option Explicit

Const KEEP_CRASH = 5   ' saklanan cokme gunlugu sayisi

Dim sh, fso, base, q, py, logf, extra, i, rc, saved
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
    ' Kanit ONCE saklanir, sonra sorulur: kutuya bakarken baslatilan yeni
    ' bir ornek son-konsol.log'un uzerine yaziyor.
    saved = KeepCrashLog()
    If MsgBox("cascade hata ile kapandi (cikis kodu " & rc & "):" & vbCrLf & vbCrLf & _
              Tail(saved) & vbCrLf & _
              "Hata gunlugu: " & saved & vbCrLf & vbCrLf & _
              "Konsolda (gorunur pencerede) yeniden baslatilsin mi?" & vbCrLf & _
              "Hayir dersen gunluk Not Defteri'nde acilir.", _
              vbCritical + vbYesNo, "cascade") = vbYes Then
        RunConsole()
    ElseIf saved <> "" Then
        sh.Run "notepad.exe " & q & saved & q, 1, False
    End If
    WScript.Quit rc
End If

' --- yardimcilar ---------------------------------------------------------

' Uygulamayi GORUNUR konsolda calistirir; pencere kapanana kadar durur.
' Eski hata-ayikla.cmd'nin isi -- artik kanitin yaninda duruyor.
Sub RunConsole()
    sh.Run "cmd /k " & q & "echo Hata ayiklama modu. Bu pencereyi kapatirsan " & _
           "cascade de kapanir. & echo. & " & q & py & q & " " & _
           q & base & "\main.py" & q & extra & q, 1, False
End Sub

' Cokme aninda konsol ciktisini tarihli bir kopyaya alir ve eskileri budar.
' Donus: kopyanin tam yolu ("" = yazacak bir sey yoktu).
Function KeepCrashLog()
    Dim stamp, target, folder, file, olds, names, i3, j, tmp
    KeepCrashLog = ""
    If Not fso.FileExists(logf) Then Exit Function
    stamp = Year(Now) & Pad(Month(Now)) & Pad(Day(Now)) & "-" & _
            Pad(Hour(Now)) & Pad(Minute(Now)) & Pad(Second(Now))
    target = base & "\Files\hata-" & stamp & ".log"
    fso.CopyFile logf, target, True
    KeepCrashLog = target

    ' Budama: adlar tarih damgali oldugu icin alfabetik sira = zaman sirasi.
    Set folder = fso.GetFolder(base & "\Files")
    olds = ""
    For Each file In folder.Files
        If LCase(Left(file.Name, 5)) = "hata-" And _
           LCase(Right(file.Name, 4)) = ".log" Then
            olds = olds & file.Name & vbLf
        End If
    Next
    ' Trim() vbLf'i KIRPMAZ: son ayracin ardindaki bos eleman silinecek
    ' dosya adi sanilip DeleteFile'i klasorun kendisine gonderiyordu.
    If olds = "" Then Exit Function
    names = Split(Left(olds, Len(olds) - 1), vbLf)
    If UBound(names) < KEEP_CRASH Then Exit Function
    For i3 = 0 To UBound(names) - 1
        For j = 0 To UBound(names) - 1 - i3
            If names(j) > names(j + 1) Then
                tmp = names(j) : names(j) = names(j + 1) : names(j + 1) = tmp
            End If
        Next
    Next
    For i3 = 0 To UBound(names) - KEEP_CRASH
        fso.DeleteFile base & "\Files\" & names(i3), True
    Next
End Function

Function Pad(n)
    Pad = Right("0" & n, 2)
End Function

' Uygulamayi penceresiz calistirir ve KAPANANA KADAR bekler.
' stderr log dosyasina yazilir. Donus: cikis kodu.
Function RunApp()
    Dim c
    c = "cmd /c " & q & q & py & q & " " & q & base & "\main.py" & q & extra & _
        " 2> " & q & logf & q & q
    RunApp = sh.Run(c, 0, True)
End Function

' Log dosyasinin son satirlarini dondurur (traceback tam gorunsun diye 40).
Function Tail(path)
    Dim t, all, lines, n, i2, out
    Tail = "(hata metni bos -- uygulama mesaj vermeden kapandi)"
    If path = "" Then Exit Function
    If Not fso.FileExists(path) Then Exit Function
    Set t = fso.OpenTextFile(path, 1)
    all = t.ReadAll
    t.Close
    If Trim(all) = "" Then Exit Function
    lines = Split(Replace(all, vbCrLf, vbLf), vbLf)
    n = UBound(lines)
    i2 = n - 40
    If i2 < 0 Then i2 = 0
    out = ""
    For i2 = i2 To n
        out = out & lines(i2) & vbCrLf
    Next
    Tail = out
End Function
