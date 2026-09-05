' KeyPilot - sessiz baslatma (konsol penceresi acilmaz).
' Cift tiklayarak calistir. Windows ile birlikte acilmasi icin
' bu dosyanin kisayolunu  shell:startup  klasorune koy.
'
' Bu dosya bir GOZETMEN: uygulamayi baslatir ve BEKLER. Onceden hicbir
' kontrol yapilmaz -- acilis gecikmesi yok, is yalnizca gercekten hata
' olunca yapilir.
'
' CIKIS KODLARI (main.py ile ayni liste). Sifirdan farkli her kod cokme
' SAYILMAZ, cunku ikisi normal yasam dongusunun parcasi:
'
'     0                normal cikis
'     2 ALREADY        bu oturumda zaten bir KeyPilot var
'     3 RESTART        "beni yeniden calistir" (Pause+Home / tepsi menusu)
'     digeri           gercek cokme
'
' Ikisini de eskiden cokme sayiyorduk ve zarari buyuktu: cift tiklayip
' ikinci ornegi acmak "2" dondurur, gozetmen bunu cokme sanip `uv sync`
' calistirir ve BIR KEZ DAHA denerdi -- o ikinci deneme calisan ornegi
' devralip oldururdu. "Bazen dogru calismiyor"un buyuk kismi buydu.
'
' TEK BEKCI. Yeniden baslatmayi 3 kodu ile BIZ yapiyoruz (RunUntilDone):
' uygulama cikar, ayni bekci onu tekrar calistirir. Eskiden uygulama
' yerine YENI bir `wscript hotkey.vbs` aciyordu ve bir sure iki bekci
' birden yasiyordu -- ikisi de ayni konsol gunlugunu yazmak isteyince cmd
' "dosya kullanimda" deyip cocugu HIC baslatmiyordu ("reload deyince
' program kapanip gitti"). Tek program calistiriyoruz; basinda tek bekci
' olmali. Uygulamaya bunu `--supervised` ile soyluyoruz (bkz. RunApp);
' bayragi gormezse (VSCode F5) cocugu eskisi gibi kendisi aciyor.
'
' KENDI KENDINI TAMIR, sirasiyla:
'
'     .venv yok            -> `uv sync` denenir, sonra tekrar bakilir
'     hizli cokme          -> `uv sync` (yeni surum yeni paket istiyordur)
'                             + BIR kez daha calistirilir
'     uzun calisip cokme   -> paket sorunu degildir: sync YAPILMAZ,
'                             program yalnizca bir kez geri getirilir
'
' HATA AYIKLAMA DA BURADA. Ayri bir .cmd yok: cokme kutusundan "Evet"
' denince ayni komut GORUNUR konsolda yeniden calisir. Sebebi, ayri
' dosyanin kanitla bulusmamasiydi -- kullanici konsolu actiginda hata
' coktan gecmis oluyordu.
'
' Programin kalici gunlugu TEK dosya: Files\log.txt (keypilot/logs.py).
' Buradaki son-konsol.log ikinci bir gunluk DEGIL: CALISAN surecin konsol
' ciktisi, cikista siliniyor. Cokme aninda kopyasi
' Files\hata-<tarih-saat>.log olarak SAKLANIR (son KEEP_CRASH tanesi);
' silinip gitmesi cokmeyi sonradan incelemeyi imkansiz kiliyordu.
'
' Gunluk dosyasinin adi CAKISABILIYOR: yeniden baslatmada eski gozetmen
' hala son-konsol.log'u acik tutarken yenisi ayni dosyaya yazmak ister,
' cmd "dosya kullanimda" deyip HIC baslamazdi -- "reload deyince program
' kapanip gitti"nin bir ayagi buydu. Artik bos bir ad seciliyor.
'
' Bu betikte HICBIR yerde islenmemis hata kalmamali: gozetmen kendi
' cokerse geriye uygulamayi baslatacak kimse kalmiyor. Dosya islemleri
' bu yuzden On Error Resume Next ile sarili.
Option Explicit

Const KEEP_CRASH = 5      ' saklanan cokme gunlugu sayisi
Const FAST_CRASH = 25     ' bu surenin altinda olen surec "hemen coktu"
Const EXIT_ALREADY = 2
Const EXIT_RESTART = 3
Const SUPERVISED = "--supervised"   ' uygulamaya "bekci kapida" demek
' Yeniden baslatma dongu freni: bu surenin altinda pes pese bu kadar
' yeniden baslatma insan eli degildir, dongudur.
Const RESTART_FLOOD = 5
Const MAX_RESTARTS = 4

Dim sh, fso, base, q, py, logf, extra, i, rc, saved, lastRun
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

base = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = base
q    = Chr(34)
' python.exe (pythonw degil): konsolu GIZLI acilir ama stderr'i vardir,
' hata metni ancak boyle log dosyasina dusuyor.
py   = base & "\.venv\Scripts\python.exe"

' Uygulamanin kendi "yeniden baslat"i bizi RESTART_FLAG ile cagiriyor;
' ne gelirse main.py'ye aynen aktariliyor.
extra = ""
For i = 0 To WScript.Arguments.Count - 1
    extra = extra & " " & q & WScript.Arguments(i) & q
Next

On Error Resume Next
If Not fso.FolderExists(base & "\Files") Then fso.CreateFolder base & "\Files"
On Error GoTo 0

' --- sanal ortam: yoksa once KENDIMIZ kurmayi deneriz -------------------
If Not fso.FileExists(py) Then
    If Not Sync() Then
        MsgBox "Sanal ortam yok ve `uv sync` calistirilamadi." & vbCrLf & vbCrLf & _
               base & "\.venv" & vbCrLf & vbCrLf & _
               "uv kurulu mu? Kurmak icin bu klasorde:" & vbCrLf & "    uv sync", _
               vbCritical, "KeyPilot baslatilamadi"
        WScript.Quit 1
    End If
    If Not fso.FileExists(py) Then
        MsgBox "`uv sync` calisti ama sanal ortam yine yok:" & vbCrLf & _
               base & "\.venv", vbCritical, "KeyPilot baslatilamadi"
        WScript.Quit 1
    End If
End If

logf = PickLog()

' --- calistir; gerekirse BIR kez tamir edip tekrar dene ------------------
rc = RunUntilDone()
If Not CleanExit(rc) Then
    ' Hemen olduyse en sik sebep yeni surumun istedigi yeni bir paket.
    ' Saatlerce calisip coktuyse paketle ilgisi yok; sync bosuna beklerdi.
    If lastRun < FAST_CRASH Then Sync()
    rc = RunUntilDone()
End If

If CleanExit(rc) Then
    Discard logf   ' konsol kopyasi ortada kalmasin
Else
    ' Kanit ONCE saklanir, sonra sorulur: kutuya bakarken baslatilan yeni
    ' bir ornek son-konsol.log'un uzerine yaziyor.
    saved = KeepCrashLog()
    Discard logf
    If MsgBox("KeyPilot hata ile kapandi (cikis kodu " & rc & "):" & vbCrLf & vbCrLf & _
              Tail(saved) & vbCrLf & _
              "Hata gunlugu: " & saved & vbCrLf & vbCrLf & _
              "Konsolda (gorunur pencerede) yeniden baslatilsin mi?" & vbCrLf & _
              "Hayir dersen gunluk Not Defteri'nde acilir.", _
              vbCritical + vbYesNo, "KeyPilot") = vbYes Then
        RunConsole()
    ElseIf saved <> "" Then
        On Error Resume Next
        sh.Run "notepad.exe " & q & saved & q, 1, False
        On Error GoTo 0
    End If
    WScript.Quit rc
End If

' --- yardimcilar ---------------------------------------------------------

' Cokme SAYILMAYAN cikislar. Bkz. dosya basindaki liste.
' EXIT_RESTART buraya normalde HIC gelmez (RunUntilDone onu yiyor); dongu
' freni devreye girerse diye listede duruyor.
Function CleanExit(code)
    CleanExit = (code = 0) Or (code = EXIT_ALREADY) Or (code = EXIT_RESTART)
End Function

' Uygulamayi calistirir ve "beni yeniden calistir" (EXIT_RESTART) dedikce
' TEKRAR calistirir. Donus: yeniden baslatma OLMAYAN ilk cikis kodu.
' Yan etki: `lastRun` son calismanin suresini (saniye) tutar.
'
' Yeniden baslatmanin butun isi bu dongu. Yeni bir bekci acilmiyor, yeni
' bir wscript acilmiyor; ayni pencere, ayni gunluk dosyasi, ayni bekci.
Function RunUntilDone()
    Dim code, floods, t0
    floods = 0
    Do
        t0 = Timer
        code = RunApp()
        lastRun = Elapsed(t0)
        If code <> EXIT_RESTART Then
            RunUntilDone = code
            Exit Function
        End If
        ' Fren: yeniden baslatma insanin bastigi bir tustur, saniyede bir
        ' olmaz. Ust uste hizli gelirse ortada dongu vardir -- programi
        ' sonsuza kadar diriltip makineyi mesgul etmeyelim.
        If lastRun < RESTART_FLOOD Then
            floods = floods + 1
        Else
            floods = 0
        End If
    Loop While floods <= MAX_RESTARTS
    MsgBox "KeyPilot ust uste " & (MAX_RESTARTS + 1) & " kez aninda kendini " & _
           "yeniden baslatti; dongu kirildi." & vbCrLf & vbCrLf & _
           "Gunluk: " & base & "\Files\log.txt", vbExclamation, "KeyPilot"
    RunUntilDone = 0
End Function

' Gecen sure (saniye). Timer gece yarisi sifirlanir; eksi cikarsa gunu ekle.
Function Elapsed(t0)
    Elapsed = Timer - t0
    If Elapsed < 0 Then Elapsed = Elapsed + 86400
End Function

' Bagimliliklari tazeler. Donus: komut calisti ve basarili oldu mu.
' `uv` PATH'te olmayabilir -- o zaman False doner ve cagiran karar verir.
Function Sync()
    Dim code
    Sync = False
    On Error Resume Next
    code = sh.Run("cmd /c uv sync", 0, True)
    If Err.Number = 0 Then Sync = (code = 0)
    Err.Clear
    On Error GoTo 0
End Function

' YAZILABILIR bir konsol gunlugu adi secer.
'
' Yeniden baslatmada iki gozetmen bir an ayni anda yasiyor: eskisinin cmd'si
' son-konsol.log'u hala acik tutuyorken yenisinin `2>` yonlendirmesi ayni
' dosyayi ister ve "dosya baska bir surec tarafindan kullaniliyor" der --
' cocuk HIC baslamaz. Bos bir ad secmek bunu bitiriyor.
Function PickLog()
    Dim path, i2, probe
    On Error Resume Next
    For i2 = 0 To 4
        If i2 = 0 Then
            path = base & "\Files\son-konsol.log"
        Else
            path = base & "\Files\son-konsol-" & (i2 + 1) & ".log"
        End If
        Err.Clear
        Set probe = fso.OpenTextFile(path, 2, True)  ' yazmak icin ac = kilit testi
        If Err.Number = 0 Then
            probe.Close
            PickLog = path
            On Error GoTo 0
            Exit Function
        End If
    Next
    Err.Clear
    On Error GoTo 0
    PickLog = base & "\Files\son-konsol.log"
End Function

' Dosyayi siler; silinemezse SESSIZCE gecer (baskasi tutuyor olabilir).
Sub Discard(path)
    On Error Resume Next
    If path <> "" Then
        If fso.FileExists(path) Then fso.DeleteFile path, True
    End If
    Err.Clear
    On Error GoTo 0
End Sub

' Uygulamayi GORUNUR konsolda calistirir; pencere kapanana kadar durur.
' Eski hata-ayikla.cmd'nin isi -- artik kanitin yaninda duruyor.
Sub RunConsole()
    On Error Resume Next
    sh.Run "cmd /k " & q & "echo Hata ayiklama modu. Bu pencereyi kapatirsan " & _
           "KeyPilot de kapanir. & echo. & " & q & py & q & " " & _
           q & base & "\main.py" & q & extra & q, 1, False
    Err.Clear
    On Error GoTo 0
End Sub

' Cokme aninda konsol ciktisini tarihli bir kopyaya alir ve eskileri budar.
' Donus: kopyanin tam yolu ("" = yazacak bir sey yoktu).
Function KeepCrashLog()
    Dim stamp, target, folder, file, olds, names, i3, j, tmp
    KeepCrashLog = ""
    On Error Resume Next
    If Not fso.FileExists(logf) Then
        On Error GoTo 0
        Exit Function
    End If
    stamp = Year(Now) & Pad(Month(Now)) & Pad(Day(Now)) & "-" & _
            Pad(Hour(Now)) & Pad(Minute(Now)) & Pad(Second(Now))
    target = base & "\Files\hata-" & stamp & ".log"
    Err.Clear
    fso.CopyFile logf, target, True
    If Err.Number <> 0 Then
        Err.Clear
        On Error GoTo 0
        Exit Function
    End If
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
    If olds = "" Then
        On Error GoTo 0
        Exit Function
    End If
    names = Split(Left(olds, Len(olds) - 1), vbLf)
    If UBound(names) < KEEP_CRASH Then
        On Error GoTo 0
        Exit Function
    End If
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
    Err.Clear
    On Error GoTo 0
End Function

Function Pad(n)
    Pad = Right("0" & n, 2)
End Function

' Uygulamayi penceresiz calistirir ve KAPANANA KADAR bekler.
' stderr log dosyasina yazilir. Donus: cikis kodu.
Function RunApp()
    Dim c
    ' SUPERVISED bayragi YALNIZCA burada: uygulama "bekci kapida" bilgisini
    ' buradan aliyor ve yeniden baslatmayi bize birakiyor. RunConsole'da
    ' YOK -- orada `cmd /k` bizi beklemiyor, uygulama cocugunu kendisi
    ' acmali, yoksa hata ayiklarken "yeniden baslat" cikis olurdu.
    c = "cmd /c " & q & q & py & q & " " & q & base & "\main.py" & q & extra & _
        " " & q & SUPERVISED & q & " 2> " & q & logf & q & q
    On Error Resume Next
    Err.Clear
    RunApp = sh.Run(c, 0, True)
    If Err.Number <> 0 Then RunApp = 1
    Err.Clear
    On Error GoTo 0
End Function

' Log dosyasinin son satirlarini dondurur (traceback tam gorunsun diye 40).
Function Tail(path)
    Dim t, all, lines, n, i2, out
    Tail = "(hata metni bos -- uygulama mesaj vermeden kapandi)"
    If path = "" Then Exit Function
    On Error Resume Next
    If Not fso.FileExists(path) Then
        On Error GoTo 0
        Exit Function
    End If
    Set t = fso.OpenTextFile(path, 1)
    If Err.Number <> 0 Then
        Err.Clear
        On Error GoTo 0
        Exit Function
    End If
    all = t.ReadAll
    t.Close
    Err.Clear
    On Error GoTo 0
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
