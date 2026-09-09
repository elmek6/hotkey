## 1) Proje Ne kadar bitti

| Olcut | Durum |
|---|---|
| Pencere sayisi | 21 pencereden **12'si bagli**, 2'si yazildi-baglanmadi (ipucu, hafiza slotlari), **7'sine hic dokunulmadi** -- %57 bagli, %67 yazilmis |
| Qt'de kalan kod | **3.022 satir**: `snip.py` 1.340, `quick_panel.py` 562, `tray.py` 419, `array_filter.py` 313, `incognito_badge.py` 188, `key_capture.py` 112, `menu.py` 88 |
| Testler | 772 test geciyor; 7 panelin kendi birim testi var |
| **Asil hedef** (PySide6 bagimliligini kaldirmak) | **%0** |

Zorluk egrisi TERS: biten %57 isin kolay kismi, kalan 7 pencerenin
dordu "yazilacak" degil **KARAR bekliyor**. Yani "%67 bitti" yaniltici
bir sayi -- kalan is oransal olarak kucuk, zorluk olarak buyuk.

## 2) Flet'e gecmek dogru karar miydi?

**Bu program icin hayir.** Gerekce his degil, olcum:

| Kanit | Sayi |
|---|---|
| Ayni paneli yazmanin maliyeti | **1,66x kod** (2.870 -> 4.770 kod satiri, yorum ve docstring HARIC) |
| Ustune Qt'de karsiligi olmayan altyapi | `fui/engine.py` 117 kod satiri |
| **Qt koprusune muhtac panel** | 13 panelin **11'i** `ask_qt` cagiriyor |
| Win32'ye inmek zorunda kalan panel | 3 (`fui/tip.py`, `fui/clip_images.py`, `fui/engine.py`) |
| Surec maliyeti | Panel basina bir `flet.exe` -> 13 panel = **13 surec** |

Panel basina kod artisi (yorumlar cikarilmis, saf kod):

| Panel | Qt | Flet | Oran |
|---|---|---|---|
| `slot_edit` | 60 | 132 | 2,20 |
| `monitor` | 125 | 258 | 2,06 |
| `ocr_view` | 144 | 325 | 2,26 |
| `tip` | 105 | 336 | **3,20** |
| `settings_dialog` | 348 | 549 | 1,58 |
| **TOPLAM (14 panel)** | **2.870** | **4.770** | **1,66** |

En carpici satir sonuncusundan onceki: ipucu penceresi Qt'de 105 kod
satiri, Flet'te 336. Ucune bir de `probes/tip.py` (piksel sayan olcum
sondaji) ve `win32/window.py`ye eklenen yardimcilar biniyor.

**Asil bulgu:** panellerin %85'i, Flet'in yapamadigi bir is icin Qt'ye
geri donuyor. Pano, dosya kutusu, tus yakalama, tema, odak -- hepsi
Qt/Win32'de kaldi. Flet burada bir arayuz CATISI degil, Qt'nin ustune
giydirilmis bir CIZIM KATMANI oldu.

Sebep Flet'in kotu olmasi degil, **bu programin yanlis aday olmasi**:
KeyPilot bir Windows kabuk araci. Klavye hook'u, tepsi, ekran kirpma,
pencere yonetimi, DPI -- hepsi isletim sistemine yapisik. Flet'in asil
vaadi (tek kodla capraz platform, modern gorunum) burada KULLANILMIYOR,
cunku program zaten Windows'a civilenmis.

**Adil olan tarafi:** gecisin kendisi iyi tasarlandi. "Qt motor olarak
kalsin, geri donus `app.py`de bir satir olsun" kurali sayesinde bu
GERI ALINABILIR bir deney. Onceki tam-yeniden-yazim denemesi (`flet`
bransi, 164 dosya) copa gitmisti; bu gitmez. Ustelik ortaya cikan bilgi
(olcumler, kurallar, sondajlar) kalici.

## 3) Cozulen, dolanilan, cozulemeyen

| Konu | Durum |
|---|---|
| Saydam + cercevesiz pencere | **CALISIYOR** (olculdu: pencerenin yalnizca %30-39'u boyaniyor) |
| Odagi ALMAMA (ipucu, rozet) | **BEDAVA** -- Flet'in varsayilani zaten oyle |
| Odagi ALMA (pano gecmisi, hizli panel) | Flet **alamiyor**; Win32 koprusuyle cozuldu (`window.force_focus`) |
| Gorev cubugundan gizlenme | `skip_task_bar` **HIC ISLEMIYOR**; is Win32'ye dustu |
| Pencere boyunu icerige uydurma (`adjustSize`) | Yok; saydam zeminle **DOLANILDI** |
| Ilk acilis gecikmesi | On isitma ile **gizlendi** (0,60 sn -> 0,16 sn) ama panel basina bir surec bedeli var |
| **Baska uygulamaya surukle-birak** | **COZULEMEZ.** Flet'te yok; Win32 yolu denendi, `SetCapture` yuzunden calismiyor ve basarisizlik sekli "calismaz" degil **KILITLENIR** |
| **Tepsi ikonu** | **YOK.** Ayri kutuphane (`pystray`) ya da Qt'de kalmasi gerekir |
| **Tam ekran saydam bindirme** (`snip.py`) | **YOK.** Win32'ye inmek gerekir -- yani Flet'e tasinmis olmaz |
| **Ham tus kodu (VK)** | **YOK.** Klavye olayi Windows tus kodunu vermiyor; hook'tan beslenmesi gerekir |
| Degistirici tuslar (Ctrl/Shift + tik) | Tiklama olayinda **yok** -> coklu secim kaybedildi, yerine isaret kutusu |
| `devicePixelRatio` | Acikta **yok** -> "1:1 zoom" gercekten 1:1 degil |
| Tema izleme | Renkler denetim KURULURKEN giriyor -> canli tema degisimi 12 panelin elden gecirilmesi demek |

**Arada kalacaklar dort tane:** `snip.py`, `tray.py`, `menu.py` (zaten
Win32), `mem_slots.py`. En olasi bitis: **PySide6 hic kalkmaz, program
kalici olarak iki motorlu olur.**

## 4) Sayfalar arasi gecikmeler gececek mi? Flet hizli mi?

**Gecmez -- yapisal.** Ama gorunmez hale getirilebilir, kismen
getirildi de.

Ayrim su: Flutter'in CIZIMI hizli. Yavas olan **Python ile Flutter
arasindaki kopru**. Her `page.update()` denetim agacini serilestirip
BASKA BIR SURECE yolluyor. Olculenler:

| Ne | Sure |
|---|---|
| Hicbir sey degistirmeden `update()` (400 satir) | **25-30 ms** -- sadece taban |
| Ayni taban, ~200 satirda | 13 ms -> *taban SABIT DEGIL, agac boyutuyla orantili* |
| 545 satir, satir basina 7 denetim | 1,04 sn |
| 2000 satirlik listeyi bastan kurma | 2,28 sn |
| Yalnizca 2 yeni satir ekleme (400 satirlik listede) | 26-31 ms |
| Gercek yuk altinda ortalama cizim | 41 ms (en uzun tek cizim 198 ms) |
| Ilk acilis / isitilmis acilis | 1,0-3,5 sn -> **0,16 sn** |

Qt'de bunlarin hepsi surec ici C++ cagrisi, yani mikrosaniye. Flet'te
"hicbir sey yapmayan bir guncelleme" 25 ms tutuyor ve **cizim surerken
dongu baska hicbir seye cevap vermiyor** -- bildirilen "Show log
kapanmiyor" hatasi tam buydu.

Bugune kadar uc seyle bastirildi: cizilen satir siniri
(`log_view.RENDER_LIMIT = 500`), biriktirip-cizme (`monitor.DRAW_MS`),
ve **Flet'in ic bayragina mudahale** (otomatik guncellemeyi kapatma,
`engine._disable_auto_update`). Sonuncusu riskli: Flet surumu yukselince
SESSIZCE bozulabilir -- program calisir, yalnizca pencere yeniden
agirlasir. `tests/test_flet_engine.py` tam bu yuzden var.

Yani gecikmeler "proje bitince gececek" degil; **surekli yonetilecek bir
butce.**

## 5) Hangisi daha kolay yazilir / okunur / esnek

* **Yazim: Qt kisa.** Olculdu, 1,66x. Farkin bir kismi bu projenin agir
  belgeleme uslubu, ama asil kismi **Qt'nin bedava verdigini elle
  yazmak**: `adjustSize`, `QSplitter`, sutun siralama, cift tiklama, DPI
  cevrimi, coklu secim. Her biri Flet tarafinda ek kod ya da kayip.
* **Okunabilirlik: Flet onde.** Kod duz ve bildirimsel; Qt'nin ortuk
  sihri (sinyal/slot baglari, yerlesim sahipligi, `WA_*` bayraklari)
  yok. `fui/settings.py`yi okumak `ui/settings_dialog.py`yi okumaktan
  kolay. Bedeli **iki thread ve iki yon kurali**: yeni gelen once
  mimariyi okumak zorunda.
* **Esneklik: Qt acik ara onde** (Windows masaustunde). Pencere
  bayraklari, native diyaloglar, tepsi, `QPainter`, DPI, surukle-birak.

## 6) Flet gercekten Flutter widget'lari mi?

Kisa cevap: **Flet, Flutter'in widget KATALOGU; Flutter'in CATISI
degil.** Sabit bir Flutter uygulamasini Python'dan IPC ile uzaktan
kumanda ediyorsun.

Elde OLMAYAN sey widget'lar degil, altindaki mekanizma:

* `RenderObject` / kendi layout'unu yazmak
* **sliver'lar**, yani sanallastirilmis liste -- `RENDER_LIMIT`in sebebi
  tam bu: Flet'in listesi gorunmeyen satiri da ciziyor
* gesture arena ayrintilari (degistirici tuslar, isaretci olaylari)
* animasyon denetleyicileri, platform kanallari, hot reload

**Bir duzeltme:** `flet.canvas.Canvas` VAR (`Path`, `Arc`, `Points`,
`Shadow`, `Circle`, `Oval`...). Yani `QPainter` isi icin "karsiligi yok"
demek YANLIS olur -- rozet (`incognito_badge.py`, adim 18) plandaki gibi
`Container`/`Text` ile degil, gercekten Canvas ile cizilebilir. Buna
karsilik `snip.py` Canvas'la da cozulmez: orada dert cizim degil, **tam
ekran saydam bindirme + basili tus takibi**.

## 7) PySide6 en iyi aday mi? Alternatifleri ne?

**Python'da kalinacaksa, bu program icin evet.** Sebebi tek bir ozellik
degil, ozelliklerin BIR ARADA bulunmasi: rastgele pencere bayraklari
(cercevesiz + saydam + hep ustte + gorev cubugundan gizli), sistem
tepsisi, `QPainter` ile serbest cizim, native dosya kutulari, DPI
farkindaligi, es zamanli COKLU PENCERE ve Win32 hook thread'iyle sorunsuz
yasayan olgun bir olay dongusu. Bu listenin tamamini veren baska bir
Python kutuphanesi yok.

| Aday | Bu program icin |
|---|---|
| **PySide6 / PyQt6** (Qt) | Su anki secim. Tek basina hepsini veren aday. Bedeli: buyuk dagitim boyu, Qt'nin kendi soyutlamasi bazen Windows'la cekisiyor. PySide6 LGPL (ticari kullanimda PyQt6'nin GPL'inden rahat). |
| **wxPython** | Gercekten NATIVE Windows denetimleri, olgun. Ama API'si eski, saydam/cercevesiz pencere ve ozel cizim isleri Qt'ye gore hantal, toplulugu kucuk. Ikinci en iyi aday. |
| **pythonnet + WinForms/WPF/WinUI** | Windows entegrasyonu Qt'den bile IYI olabilir (tepsi, pencere, DPI, native diyalog dogrudan .NET API'si). Bedeli: capraz platform biter, interop karmasasi, Python ekosisteminde ince bir yol. Gercek bir alternatif ama BUYUK bir donus. |
| **Duz Win32** (`ctypes` / `pywin32`) | Proje bunu ZATEN yapiyor (`keypilot/win32/`, hook + menu + overlay). Cozulemeyen dort is icin gercek cevap da bu. Ama butun arayuzu boyle yazmak deli isi. |

**Sonuc:** Python'da kalinacaksa PySide6 dogru aday. Sorulacak asil soru
"Qt mi Flet mi" degil, **"bu program Python'da mi kalmali"**. Eger amac
en iyi Windows entegrasyonu ise C#/.NET (WPF/WinUI) ya da Rust bir tik
daha iyi sonuc verir; ama o zaman hook, makro, OCR, pano deposu -- yani
programin GERCEK degeri olan 10.000 satir -- yeniden yazilir. Bu bedele
degmez.

## 8) PySide mimarisi -- kisa tur

Qt'nin butun modeli **tek bir dongude** birlesiyor. Yedi parca:

### 1. `QApplication` ve olay dongusu

    app = QApplication(sys.argv)
    ...
    app.exec()          # ANA THREAD'i sonuna kadar tutar

`exec()` bir sonsuz dongu: Windows'un mesaj kuyrugundan olay ceker,
sahibine dagitir, kuyruk bosalinca uyur. **Butun arayuz bu thread'e
aittir** -- baska bir thread'den widget'a dokunmak tanimsiz davranistir.
Bu projedeki Flet'in ayri bir thread'e alinmasinin sebebi de bu: iki
kutuphane de ayni thread'i istiyor, ikisine birden verilemez.

### 2. Nesne agaci ve sahiplik

Her `QObject`in bir EBEVEYNI olabilir. Ebeveyn olunce cocuklari da
oluyor -- yani bellek yonetimi agac uzerinden. Pencere kapaninca yok
edilmesi (`WA_DeleteOnClose`) bu yuzden ucuz. Flet'te karsiligi yok:
orada panel BIR KEZ kurulup yasatiliyor (`flet-plan.md` "YASAYAN PANEL
kurali").

### 3. Sinyal / slot -- ve THREAD GECISI

    self.button.clicked.connect(self.on_click)

Gozlemci kalibi, ama asil onemli ozellik su: **alici baska bir
thread'deyse Qt cagriyi KENDILIGINDEN kuyruga alir** (queued
connection). `emit` cagiran thread'de hemen doner, is alicinin
thread'inde kosar.

Bu projede Flet -> Qt yonu tam bunun uzerine kurulu
(`fui/engine.py` `ask_qt`): pano, dosya kutusu, ayar yazma gibi isler
Flet thread'inden istenip ANA THREAD'de kosuyor.

### 4. Olaylar (`event`) ile sinyaller farkli seyler

Sinyal "bir sey oldu, haberin olsun"; olay ise Windows'tan gelen ham
girdi (`mousePressEvent`, `keyPressEvent`, `paintEvent`). Olaylar
YAKALANABILIR ve baskasi adina suzulebilir:

    def eventFilter(self, obj, event): ...

`ui/quick_panel.py` CapsLock panelinde tam bunu yapiyor -- baska bir
widget'in tuslarini araya girip okuyor. Flet'te bu KATMAN YOK; klavye
olayi yalnizca sayfa duzeyinde ve Windows tus kodunu vermiyor.

### 5. Pencere bayraklari ve oznitelikler

    setWindowFlag(Qt.FramelessWindowHint)
    setWindowFlag(Qt.WindowStaysOnTopHint)
    setAttribute(Qt.WA_ShowWithoutActivating)
    setAttribute(Qt.WA_TranslucentBackground)

Qt'nin Windows'a en yakin durdugu yer burasi: bu satirlarin her biri
dogrudan bir Win32 pencere stiline (`WS_EX_*`) ceviriliyor. Flet
gecisinde en cok kan kaybedilen yer de burasi oldu -- `skip_task_bar`
Flet'te calismadi ve is `win32/window.py`ye dustu.

### 6. Cizim: `QPainter`

    def paintEvent(self, event):
        p = QPainter(self)
        p.drawRoundedRect(...)

Widget kendi yuzeyini ciziyor. `ui/incognito_badge.py` ve `ui/snip.py`
tamamen bunun uzerine kurulu. Flet'teki karsiligi `flet.canvas.Canvas`
-- var ama surec disinda, yani her degisiklik IPC'den geciyor.

### 7. Yerlesim, model/gorunum, tema

* **Yerlesim** (`QVBoxLayout`, `QSplitter`): olcuyu widget'lar
  kendileri pazarliyor. `adjustSize` ve `QSplitter` bu sistemin
  meyvesi -- Flet'te ikisinin de karsiligi yok, geciste kaybedildi.
* **Model/gorunum** (`QAbstractItemModel`): veriyle gorunum ayri.
  Buyuk listeler icin ONEMLI, cunku gorunum yalnizca GORUNEN satiri
  ister. Flet'in listesi hepsini cizdigi icin `RENDER_LIMIT` kondu.
* **Tema:** `QPalette` + stylesheet (QSS, CSS'e benzer). Calisma aninda
  degistirilebilir; Flet'te renkler denetim kurulurken giriyor, o yuzden
  tema izleme kaybedildi.

### Bu projedeki yerlesim

    ana thread     app.exec()            Qt: tepsi, kalan PySide pencereleri
    hook thread    GetMessage            tuslar -- win32/hook.py
    flet thread    ft.run() + asyncio    keypilot/fui/engine.py

Ana thread'in "kutsal" olmamasinin sebebi klavye hook'unun KENDI mesaj
pompasi olmasi (`SetWindowsHookEx`, Qt dongusune bagli degil). Yani Qt
zaten tek dongu degildi; Flet ucuncu dongu olarak yanina kondu.