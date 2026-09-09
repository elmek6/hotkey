# PySide6 -> Flet gecis plani

> **DURUM** -- branch `flet2`
>
> | | |
> |---|---|
> | Flet'te ve BAGLI | 12 panel |
> | Yazildi, BAGLANMADI | 2 panel -- ipucu (`fui/tip.py`), hafiza slotlari (`fui/mem_slots.py`) |
> | Hala PySide6'da | 9 pencere |
> | Sirada | **adim 17: ipucunu `app.py`ye bagla** |
>
> Program IKI MOTORLA calisiyor: ara durak, sorun degil.
>
> **BU DOSYA IKIYE AYRILDI.** Once YAPILACAK is gelir (siradaki adim,
> kalan pencereler, acik kararlar, temizlik listesi), sonra DEGISMEYEN
> BILGI (mimari, panel yazma kurallari, sondajlar). Dosyanin SONUNDA
> `=== BITENLER ===` ayracinin altinda ne bittiginin kaydi duruyor --
> oraya "bu is nasil cozulmustu" diye bakilir, IS LISTESI olarak degil.
>
> Yeni panel yazacak olana: once **Mimari**, sonra **Panel yazarken
> bilinecekler**, sonra **SIRADAKI ADIM**.
>
> Denemek icin: `uv run python -m probes.flet` (bkz. **Nasil denenir**).

**Yontem: panel panel, kolaydan zora. Program her adimdan sonra CALISIR
durumda.** Qt motor olarak kaliyor; tasinan panel `keypilot/fui/` altina
gidiyor, Qt karsiligi silinmiyor -- geri donmek `app.py`'de bir satir.

Onceki deneme (`flet` brans'i, `cascade` paketi) tam yeniden yazimdi:
164 dosya, 18 pencere tek bir Flet penceresine sikistirildi ve odak,
saydamlik, es zamanli pencere kaybedildi. O yol BIRAKILDI.

---

# YAPILACAK

## SIRADAKI ADIM (adim 17): ipucunu BAGLA

Panel yazildi, 29 birim testi geciyor ve EKRANDAN olculdu -- saydamlik,
olcu, pencere bayraklari, acilis suresi (arsivde **ADIM 16**). Kalan tek
is onu programa takmak.

**1. Once GOZLE bak:** `uv run python -m probes.flet`, bes ipucu
dugmesi. Olculemeyen tek sey metnin okunakliligi.

**2. `app.py`de UC SATIR:**

    self.tip = TipPanel()        # satir ~190, `Tip()` yerine
    self.tip.warm()              # acilista -- ISITILMADAN kullanilmamali
    self.tip.shutdown()          # `on_exit` icinde

    -> ISITMA ISTEGE BAGLI DEGIL. Isitilmayan panelde ilk ipucu GEC
       gorunur (olculdu: isitilmis 0.16 sn, isitilmamis 0.60 sn; soguk
       makinede `flet.exe` 1-3.5 sn, ipucunun kendi suresi 900-2500 ms
       -- yani hic gorunmeyebilir) VE ilk ipucu GOREV CUBUGUNDA cikar.
       Ikisi de olculdu.

**3. Bagladiktan sonra GERCEK PROGRAMDA dogrula.** Ipucu programin KIRK
yerinden cagriliyor (hata bildirimi dahil), yani bu panelin yanlisi oteki
on ikisinden daha cok yeri etkiler.

## SONRAKI ADIMLAR

**Adim 18 -- `incognito_badge.py` (188 satir).** Ipucuyla ayni kalip:
cercevesiz + saydam + hep ustte + gorev cubugundan gizli. Ipucunun
cozdukleri HAZIR (saydamlik, `set_tool_window`, imlec yanina yerlestirme),
yani bu adim KUCUK olmali. Tek farki `QPainter` cizimi: rozet elle
cizilmis bir sekil, Flet'te `Container`/`Text` ile yeniden kurulacak.

**Adim 19-20 -- `array_filter.py` (313) ve `quick_panel.py` (562).** Ikisi
de odagi ALMAK zorunda (arama kutusuna yaziliyor). `win32/window.py`
`force_focus()` tam bunun icin yazildi ve olculdu ama HENUZ HIC
KULLANILMADI -- ilk gercek musterisi bu iki panel. Panel basina "odak
ister / istemez" bir bayrak gerekecek: ayni yardimci ipucu ve rozet icin
ZARARLI.

    -> Bu iki panel `key_capture.py` (#16) sorusunu da acacak: hizli
       panel tus okuyor, ham tus yakalama Flet'te YOK. Cozum muhtemelen
       "hook'tan besle".

## Kalan pencereler -- Asama 3

Bunlar "biraz ugrasinca olur" degil; her biri icin bir KARAR gerekiyor.

| # | Panel | Satir | Engel | Secenek |
|---|---|---|---|---|
| 10 | `mem_slots.py` | 454 | Satiri BASKA BIR UYGULAMAYA surukleyip birakma (`QDrag`) | **Flet'te karsiligi YOK** ve Win32'ye inmek de yetmiyor -- olculdu, arsivde **ADIM 10 -- YARIM KALDI**. Ya sürükleme kaybedilir (panel hazir: `fui/mem_slots.py`), ya pencere Qt'de kalir. |
| 14 | `array_filter.py` | 313 | **OLCULDU, engel TERSINE CIKTI:** bu pencere odagi ALMAK zorunda (arama kutusuna yaziliyor, `activateWindow` + `setFocus`), Flet penceresi ise odagi ALAMIYOR | Odak KOPRUSU YAZILDI (adim 15): `win32/window.py` `force_focus()` -- gosterdikten sonra Qt tarafindan cagrilacak |
| 15 | `quick_panel.py` | 562 | Ayni: CapsLock paneli de kutuya yaziyor (`eventFilter`) | Ayni kopru |
| 16 | `key_capture.py` | 112 | Ham tus yakalama: `ui_open` ile hook susturulup tuslar Qt olayi olarak okunuyor | Flet klavye olayi sayfa duzeyinde ve Windows tus kodlarini vermiyor. Hook'tan beslemek gerekir. |
| 17 | `incognito_badge.py` | 188 | `QPainter` ile cizilen, hep ustte duran rozet | **Odak sorunu OLCULDU ve YOK:** Flet penceresi gosterilince odak calmiyor. Kalan is cerceve/saydamlik (`frameless`, `always_on_top`, `skip_task_bar` Flet'te var) ve ON ISITMA (adim 15, hazir) |
| 18 | `tip.py` | 173 | `FramelessWindowHint` + `WA_ShowWithoutActivating` | **YAZILDI ve OLCULDU (adim 16) -> `fui/tip.py`**, baglanmadi. Odak bedava cikti (adim 14); gercek engel `adjustSize` idi -- saydam zeminle cozuldu, olculdu |
| 19 | `menu.py` | 88 | Win32 `TrackPopupMenu` (zaten Qt degil) | Flet'e tasimak anlamsiz; oldugu gibi kalabilir. |
| 20 | `tray.py` | 419 | `QSystemTrayIcon` -- Flet'te tepsi YOK | Onceki brans `pystray` eklemisti. Ayri bir karar. |
| 21 | `snip.py` | 1347 | Tam ekran saydam bindirme + `QPainter` cizimi + basili tus takibi | **Flet'te karsiligi YOK.** Win32 katmanina inmeli (onceki brans `win32/overlay.py` yazmisti). En son, belki hic. |

**Sonuc:** Asama 3 asilmadan PySide6 bagimliligi KALKMAZ. Asama 1 ve 2
BITTI (13 panel yazildi, 12'si bagli); kalan dokuz pencerenin dordu
yazilmayi degil KARAR bekliyor.

## Acik kararlar

Bunlar "yapilacak is" degil, VERILECEK KARAR. Gerekceler arsivde.

| Ne | Durum | Ayrinti |
|---|---|---|
| `mem_slots.py` -- surukleme kaybedilsin mi? | Panel HAZIR ama baglanmadi. Surukleme Flet'te YOK, Win32 yolu OLCULDU ve calismiyor. Kabul edilirse baglanir, edilmezse `fui/mem_slots.py` SILINIR -- ucuncu hali yok. | arsiv: **ADIM 10** |
| Tema -- acik palet gelsin mi? | Flet panelleri KOYU SABIT. Ayarin kendisi calisiyor, Flet tarafi izlemiyor; on iki panelin elden gecirilmesi demek. | **Karara baglanacaklar** |
| Panel basina bir `flet.exe` | Su an DOGRU secim (Flet'te surec basina tek pencere) ama 13 panel 13 surec. Tek kabuk mu, coklu pencere mi? | **Karara baglanacaklar** |
| `tray.py`, `menu.py`, `snip.py` | Ucu de Flet'e HIC tasinmayabilir. Odak sorunundan bagimsiz, ayri kararlar. | **Kalan pencereler** tablosu |

## Tam geciste SILINECEK / DUZELTILECEK

Gecis boyunca bilerek eklenen gecici seyler. Her biri "tam gecis"te
temizlenmeli; sirasi onemsiz ama listenin tamami bitmeden gecis bitmis
sayilmaz.

### Silinecek dosyalar

- [ ] `keypilot/ui/` paketinin tamami -- her panel tasindikca ilgili dosya.
      Son iki yardimci (`place.py` pencere ortalama, `preview.py` metin
      kisaltma) Flet'te karsiliklari yazilinca gidecek. `place.py` uzun
      sure kalacak: 8 Qt penceresi daha kullaniyor.
- [ ] **Artik kimsenin kullanmadigi Qt panelleri.** Yontem geregi
      silinmiyorlar (geri donus tek satir), ama import edilmedikleri icin
      sessizce curuyorlar -- taniyan yok, test eden yok:
      `ui/key_map_view.py` (`owner_label` disinda), `ui/pause.py`,
      `ui/slot_edit.py`, `ui/log_view.py`, `ui/qr_view.py`,
      `ui/monitor.py`, `ui/macro_view.py`, `ui/ocr_view.py`,
      `ui/repository_view.py`, `ui/profiles_view.py`,
      `ui/clip_images.py`, `ui/settings_dialog.py`. Bunlarin TESTLERI
      hala kosuyor (`tests/test_repository_view.py`,
      `tests/test_profiles_view.py`, `tests/test_settings_dialog.py`) --
      dosya silinirken o testler de gidecek; Flet karsiliklari ayri
      dosyada (`tests/test_fui_repository.py`,
      `tests/test_fui_profiles.py`, `tests/test_fui_clip_images.py`,
      `tests/test_fui_settings.py`).
      **`ui/key_capture.py` ISTISNA:** `ui/profiles_view.py` silinse de
      KALIYOR, cunku Flet paneli onu kullanmaya devam ediyor
      (`fui/profiles.py` `_capture_key`).
- [ ] `keypilot/theme.py` -- QPalette/stylesheet uzerine kurulu, Flet'e
      verecek bir seyi yok. Yerine `keypilot/fui/theme.py`.
- [ ] **`keypilot/fui/mem_slots.py` -- BAGLANMAMIS panel.** Adim 10 karara
      baglanmadigi icin duruyor (bkz. **ADIM 10 -- YARIM KALDI**).
      Surukleme kaybi kabul edilirse baglanir; edilmezse bu dosya
      silinir. Ucuncu bir hali YOK: import edilmeyen panel curur.
- [ ] `keypilot/fui/__pycache__/` ve `keypilot/fui/panels/__pycache__/` --
      eski `flet` brans'indan kalma `.pyc` artiklari, kaynaklari yok.
      Zararsiz (Python kaynaksiz `.pyc` yuklemez) ama kafa karistiriyor.

### Silinecek kod parcalari

- [ ] **`signal.signal` yamasi** (`fui/engine.py` `_signal_main_only`,
      `_install_signal_shim`). Flet ana thread'i alamadigi icin var:
      `ft.run()` SIGINT/SIGTERM kaydediyor ve CPython bunu yalnizca ana
      thread'de kabul ediyor. Tam geciste `ft.run()` ana thread'e gecer
      ve yama GEREKSIZ kalir -- global bir yama oldugu icin ilk silinecek
      seylerden.
- [ ] **`QObject` / `Signal` mirasi** her `fui/*.py` panelinde. Yalnizca
      Flet->Qt gecisi icin var. Qt gidince duz geri cagriya (callback)
      donusecek.
- [ ] **Ters bagimliliklar** -- Flet paneli hala bir `ui/` dosyasindan
      saf metin yardimcisi aliyor. Qt dosyasi silinirken yardimci Flet
      tarafina tasinacak:
      `fui/key_map.py` -> `ui/key_map_view.py` (`owner_label` +
      `OWNER_LABELS`), `fui/slot_edit.py` ve `fui/qr.py` -> `ui/preview.py`
      (`shorten`).
- [ ] **`MASK_CHAR` iki yerde:** `ui/qr_view.py` ve `fui/qr.py`. Ayni
      karakter, ayni is; Qt dosyasi silinince tek kalir.
- [x] ~~`_on_qt` sinyali `fui/engine.py`ye TASINMALI~~ -- **YAPILDI**
      (`f56ff95`). `FletEngine.ask_qt(job)`; iki panelden kalkti.
      Motorun `QObject` olmasinin TEK sebebi bu sinyal, yani Qt gidince
      hem `ask_qt` hem miras birlikte silinecek.
- [ ] **`fui/profiles.py`deki `_capture_key`** -- kisayol yakalama kutusu
      hala Qt'nin (`ui/key_capture.py` + kucuk bir `QDialog`). Gecici
      DEGIL bir tercih: `ft.KeyboardEvent` Windows sanal tus kodunu (VK)
      vermiyor ve programin geri kalani VK ile konusuyor. Asama 3 #16
      (`key_capture.py`) cozulene kadar boyle kalacak; cozum muhtemelen
      "hook'tan besle" olacak ve o zaman bu kopru de gidecek.
- [ ] **`QFileDialog` iki panelde:** `fui/qr.py` ("Kaydet PNG") ve
      `fui/clip_images.py` ("PNG Kaydet"). Gecis suresince BILEREK boyle
      (`ask_qt` ile bir satir); Qt gidince yerine `ft.FilePicker`
      yazilmali ve o bir SERVIS: sayfaya eklenip sonucu geri cagriyla
      alinmali. Onceki `flet` bransinda `cascade/fui/shell.py` ornegi
      var. Ayni panelde `QGuiApplication.clipboard()` da var -- pano
      Flet'te YOK, o Qt gidince `win32/clipboard.py` uzerinden
      cozulecek.
- [ ] **`main.py`** `QApplication` kurulumu, `app.setQuitOnLastWindowClosed`,
      `logs.install_qt_handler()` -- hepsi `ft.run()` ile degisecek.
- [ ] **Panel basina `shutdown()` cagrilari** (`app.py` `on_exit`). Su an
      her Flet paneli kendi `flet.exe`sini kapatmak zorunda; tek kabuga
      gecilirse tek cagri kalir.
- [ ] **`probes/focus.py` + `probes/focus_target.py`** -- adim 14'un
      olcumu. Karar verildi (arsiv: **ADIM 14**), yani sondajin isi bitti;
      yalnizca "acaba yeni Flet surumunde degisti mi" sorusu icin
      duruyor. Icindeki `force_focus` adim 15'te kalici yere TASINDI
      (`win32/window.py`); sondaj artik onu cagiriyor, kopya kalmadi.
- [ ] **`probes/tip.py`** -- adim 16'nin olcumu (saydamlik, pencere
      bayraklari, acilis suresi). Isi bitti; yalnizca "acaba yeni Flet
      surumunde degisti mi" sorusu icin duruyor. Ozellikle
      `skip_task_bar` bir gun duzelirse `fui/tip.py`deki Win32
      yamasi (`_hide_from_taskbar`) gereksizlesir -- once bu sondaj
      kosulmali.
- [ ] **`probes/flet.py`** -- "hangi panel Flet'te" sorusunun cevabi
      oldugu surece ise yariyor. Her sey Flet'e gecince anlamsizlasir;
      icindeki sahte veriler `probes/gui.py` gibi bir sondaja tasinabilir.

### Karara baglanacaklar

- [ ] **Panel basina bir `FletEngine`** -- yani panel basina bir
      `flet.exe`. Su an DOGRU secim: Flet'te surec basina tek pencere var
      ve Qt'nin coklu pencere davranisi boylece korunuyor. Ama 13 panel
      13 surec demek. Tam geciste ya coklu pencere destegi kullanilir ya
      da onceki bransin "panel yigini" modeline donulur (o model es
      zamanli pencereyi kaybediyordu).
- [ ] **Flet'in ic bayragina mudahale** (`fui/engine.py`
      `_disable_auto_update`). `signal.signal` yamasi gibi SUREC genelinde
      ve Flet'in ICINDEKI bir davranisa dayaniyor: bayrak modul duzeyinde
      paylasilan bir `ContextVar` varsayilaninda tutuluyor ve
      `reset_auto_update` onu ustten kopyaliyor. Flet surumu yukselince
      SESSIZCE bozulabilir -- program calisir, yalnizca pencere yeniden
      agirlasir. `tests/test_flet_engine.py` tam bu yuzden var; surum
      yukseltmesinde ONCE o testlere bakilmali. Flet resmi bir
      "auto-update kapali" ayari sunarsa oraya gecilmeli.

- [ ] **`fui/theme.py` sabit koyu palet -- ADIM 13'TE KARARA BAGLANDI:
      simdilik OYLE KALIYOR.** Qt surumu sistem temasini izliyordu
      (`theme.py`: `AppsUseLightTheme`) ve plan "ayar ekrani tasinirken
      geri gelsin" diyordu. Ayar ekrani tasindi, tema izleme GELMEDI.
      Sebep uc tane: (1) renkler denetime KURULURKEN giriyor (`_build`
      panel omrunde BIR KEZ kosuyor, pencere kapaninca yok edilmiyor
      GIZLENIYOR), yani canli tema degisimi her panelin denetim agacini
      yeniden kurmak demek; (2) panel basina ayri bir `flet.exe` var,
      yani is on iki surecte birden yapilacak; (3) panellerin bir kismi
      kendi sabit rengini tasiyor (`fui/clip_images.py` `PREVIEW_BG`,
      `fui/monitor.py` satir renkleri, `fui/mem_slots.py` baslik
      renkleri) -- acik palet bunlarin uzerinde okunmaz.
      **Yapilacak is:** `fui/theme.py`ye acik palet + `resolve()`
      cagrisi, panellerdeki sabit renklerin temaya baglanmasi, panellerin
      tema degisiminde yeniden kurulmasi. On iki panelin hepsinin gozle
      dogrulanmasini istiyor; tek kabuga gecilirse (asagidaki
      `FletEngine` karari) is TEK panele iner, o yuzden SIRASI ondan
      sonra. Ayar ekrani bu durumu kullaniciya yaziyor
      (`fui/settings.py` `THEME_NOTE`) -- is bitince kaldirilacak yer
      orasi.
- [ ] **`pyproject.toml`den `pyside6`** -- yalnizca Asama 3 bittikten
      sonra. `flet-desktop` ACIKCA eklendi cunku Flet onu ilk
      calistirmada kendi kendine pip'liyor; kilitli projede istenmez.
- [ ] **Testler.** `tests/` icinde Qt pencerelerini kuran testler var;
      panel tasindikca Flet karsiliklari yazilmali. Motorun iki global
      ayari artik test ediliyor (`tests/test_flet_engine.py`: signal
      yamasi, otomatik guncelleme, `ask_qt`) ve adim 9'da ILK panel
      testi yazildi (`tests/test_fui_repository.py`: Flet
      calistirilmadan panelin Qt tarafi suruluyor -- suzgec, kaydetme,
      silme). Ayni kalip adim 11 (`tests/test_fui_profiles.py`, 26 test),
      adim 12 (`tests/test_fui_clip_images.py`, 38 test) ve adim 13'te
      (`tests/test_fui_settings.py`, 42 test) izlendi. Kalan SEKIZ
      panelin birim testi hala YOK -- dogrulama elle yapildi. En kolay baslangic saf fonksiyonlar (Flet gerekmiyor,
      ekran gerekmiyor):
      `fui/slot_edit.py` `old_value()` (maskeleme, bosluk ezme, kirpma),
      `fui/qr.py` `masked()` / `slot_rows()` / `window_height()`,
      `fui/log_view.py` `line_text()` / `source_chars()` /
      `detail_height()`, `fui/monitor.py` `row_text()` / `header_text()`
      (sutun hizasi -- gozle dogrulanmasi en sikici olan sey). Bunlar tam
      da elle dogrulanmasi en sikici olan kurallar.
- [ ] **`slots_ctl._editing`** -- duzenlenen slotu tutan alan. Ayni anda
      tek kutu acik oldugu icin dogru; Flet coklu pencereye gecerse
      (yukaridaki `FletEngine` karari) bu varsayim duser.
- [ ] **QR'da her tus vurusunda tam cizim.** `_refresh` alan degisiminde
      kareyi yeniden uretip `page.update()` cagiriyor. Su an sorun DEGIL
      (pencerede az denetim var, segno 1 ms altinda, PNG birkac kilobayt)
      ama log penceresindeki gecikmeli cizim kalibi (`FILTER_MS`) burada
      YOK. Alanlar cogalirsa ilk bakilacak yer.
- [ ] **Pano gorselleri listesinde SINIR YOK** (`fui/clip_images.py`).
      Her tazelemede butun satirlar yeniden kuruluyor ve her satirda bir
      64x64 PNG var; depo 500 kayde kadar cikabiliyor (`MAX_SLOTS`).
      PNG'ler onbellekte (slot+id) yani yeniden KODLANMIYOR, ama tam
      cizimde hepsi Flutter tarafina yeniden gidiyor. Gercek depoda
      (yuzlerce gorsel) acilis yavaslarsa ilk bakilacak yer burasi;
      cozum kalibi hazir: `fui/log_view.py` `RENDER_LIMIT`.
- [ ] **Ayar ekraninda her tus vurusunda TAM cizim** (`fui/settings.py`
      `_on_search`). Qt surumu de her harfte suzuyordu ve 26 kartta
      olculebilir bir gecikme yok. Ayar sayisi buyurse ya da kartlar
      agirlasirsa `fui/log_view.py`nin gecikmeli suzgeci (`FILTER_MS`)
      buraya da gelmeli.
- [ ] **`RENDER_LIMIT = 500`** (`fui/log_view.py`). Cizim maliyeti satir
      sayisiyla dogru orantili oldugu icin kondu. Flet'in ileride
      gercekten sanallastiran (yalniz gorunen satiri cizen) bir liste
      denetimi gelirse sinir KALKMALI -- Qt surumunde boyle bir sinir
      yoktu.

### Geri alinan / kaybedilen davranislar

- [ ] **Kisayol haritasinda sutun basligi tiklamasi** (Qt:
      `setSortingEnabled`). Flet surumunde siralama sabit: catisanlar
      ustte. Istenirse `DataColumn.on_sort` ile geri gelir.
- [ ] **Ilk acilis 1-3.5 sn.** Her panelin kendi `flet.exe`si var, yani
      bu bedel PANEL BASINA bir kez odeniyor. Tek kabuga gecilirse bir kez.
- [ ] **Slot kutusu imlecin ekraninda acilmiyor.** Qt surumu
      `ui/place.py` ile calisilan monitorun ortasina aciyordu; Flet
      penceresi kendi varsayilan yerine geliyor.
      **ARTIK UCUZ (adim 16):** fiziksel/mantiksal piksel cevrimi YAZILDI
      ve olculdu -- `win32/screen.py` `dpi_scale_at()` + `work_area_at()`,
      kullanim ornegi `fui/tip.py` `place()`. Bu makinenin UC monitorunde
      de olcek 1.104; plandaki eski "%135, iki monitor" notu YANLISTI.
      On bir panelin hepsinde ayni kayip var ve hepsi ayni kalipla
      cozulur.
- [ ] **Log penceresinde cift tiklama.** Qt'de satiri panoya
      kopyaliyordu; Flet `Container`inda cift dokunma olayi yok. Ayni is
      "Satiri kopyala" dugmesinde -- once satira tiklanip secilmesi
      gerekiyor.
- [ ] **Log penceresinde ayni anda en fazla 500 satir** (`RENDER_LIMIT`,
      yukarida). Suzgec TUM 2000 kayitta ariyor, yalniz cizim sinirli.
- [ ] **Log sutunlarinin genisligi icerige gore ayarlanmiyor.** Qt
      `resizeColumnsToContents` kullaniyordu; burada `sev` disindaki
      sutunlar tek bir sabit genislikli yaziya dolguyla diziliyor
      (`line_text`), `kaynak` sutunu 12-26 karakter arasinda veriye gore.
- [ ] **QR penceresi imlecin ekraninda acilmiyor** -- slot kutusuyla ayni
      sebep (`ui/place.py` karsiligi yok). Tek duzeltme ikisini birden
      cozer.
- [ ] **QR penceresi Qt surumunden UZUN.** Genislik birebir (640), boy
      Wifi sablonunda 605 yerine 729. Sebep Flet'in Material denetimleri
      (bkz. **PENCERE OLCUSU kurali**); daha da daraltmak okunakliktan
      goturur. Tema/olcu isi adim 13'te (`settings_dialog.py`) topluca
      ele alinabilir.
- [ ] **OCR panelinde metin DUZENLENEMIYOR.** Qt'de sonuc bir
      `QPlainTextEdit`ti: kopyalamadan once elle duzeltilebiliyordu.
      Flet'te `TextField` satiri SARIYOR ve kolonlu/tablo dizilimi
      okunmaz hale geliyor; hizalamayi korumak icin secilebilir ama
      duzenlenemez bir metin (`no_wrap`, iki eksende kaydirma) secildi.
      Duzenleme gerekirse Kopyala ile disari alinip orada yapiliyor.

- [ ] **OCR panelinde `QSizeGrip` yok.** Sag alttaki boyut tutamagi
      dustu; Flet penceresi kenarlarindan zaten boyutlandiriliyor.

- [ ] **Makro ekraninda "Hazir" zamanlayicisi dustu.** Qt'de 200 ms'lik
      bir `QTimer` bosta durum yazisini "Hazir"a cekiyordu; simdi durum
      yalnizca DEGISTIGINDE yaziliyor. Gorunen fark yok (bosta zaten
      "Hazir" yaziyor), kazanc saniyede bes bedava cizimin gitmesi.

- [ ] **Makro ekrani imlecin ekranina ORTALANMIYOR.** Qt `place.py`
      kullaniyordu; Flet penceresi kendi varsayilan yerinde aciliyor --
      oteki alti panelle ayni kayip, ayni sebep.

- [ ] **Olay izleyicide HUCRE kopyalama.** Qt'de sag tik menusunde
      "Hucreyi kopyala" vardi; Flet'te baglam menusu yok. Menudeki oteki
      iki secenek (satir, tumu) zaten dugme olarak duruyordu.

- [ ] **Olay izleyicide cift tiklama.** Satiri panoya kopyaliyordu; ayni
      is "Satiri kopyala" dugmesinde, once satira tiklanmasi gerekiyor.
      Log penceresiyle ayni kayip, ayni sebep.

- [ ] **Olay izleyicide satirlar 0.15 sn gecikmeyle giriyor** (`DRAW_MS`).
      Qt her olayda tabloya yaziyordu. Gecikme goz icin farkedilmez ama
      "tusa bastim, satir hemen ciksin" beklentisi varsa buradan.

- [ ] **Olay izleyici Qt surumunden GENIS** (820x520, Qt 660x460). Alt
      siradaki alti denetim Flet'in Material olculeriyle 660'a sigmiyor
      (bkz. **PENCERE OLCUSU kurali**).

- [ ] **Profil yoneticisinde sutun genisligi degistirilemiyor.** Qt'de
      `QSplitter` vardi (fareyle surukleniyordu); Flet'te sutunlar sabit
      ve Qt'nin acilis olculeri korundu (330/250/gerisi). Depo penceresi
      (`fui/repository.py`) ile ayni kayip, ayni sebep.

- [ ] **Profil yoneticisi imlecin ekraninda acilmiyor.** Qt `place.py`
      kullaniyordu; oteki dokuz panelle ayni kayip, ayni sebep. Not:
      kisayol YAKALAMA kutusu Qt oldugu icin O hala imlecin ekraninda
      aciliyor -- iki pencere iki ayri yerde acilabilir.

- [ ] **Pano gorsellerinde Ctrl/Shift ile COKLU SECIM dustu.** Yerine
      her satirda bir ISARET KUTUSU var. Sebep Flet'te: tiklama olayi
      degistirici tuslari TASIMIYOR (`ft.TapEvent`de ctrl/shift alani
      yok; `ft.KeyboardEvent`te var ama o yalnizca tusa BASILINCA geliyor
      ve birakma haberi gelmedigi icin durum takip edilemiyor).
      `ft.KeyboardListener` (on_key_down/on_key_up) bir gun bu isi
      gorebilir -- odak sorunu cozulurse. Islev kaybi YOK: coklu secimin
      tek kullanicisi toplu silmeydi.

- [ ] **Pano gorsellerinde 1:1 GERCEKTEN 1:1 degil.** Qt cizimi
      `devicePixelRatio`ya bolerek bir goruntu pikselini bir EKRAN
      pikseline oturtuyordu; Flet'te cizim Flutter'in mantiksal
      pikselinde ve olcegi veren bir alan YOK. %150 olcekli ekranda
      "1:1" gorsel bir tik buyuk cikar. Bu makine %135 olcekli, yani
      gozle gorulur.

- [ ] **Pano gorsellerinde sutun genisligi degistirilemiyor.** Qt'de
      `QSplitter` vardi ve liste kolonlarin GERCEK genisligine
      cekiliyordu (`_fit_list_width`); Flet'te liste sabit (430, Qt'nin
      acilis olcusu). Depo ve profil pencereleriyle ayni kayip, ayni
      sebep.

- [ ] **Pano gorselleri imlecin ekraninda acilmiyor.** Qt
      `center_on_cursor_screen` kullaniyordu; oteki on panelle ayni
      kayip, ayni sebep (`ui/place.py` karsiligi yok).

- [ ] **Silme onayi acikken yoklama DURMUYOR.** Qt onay kutusu acilirken
      zamanlayiciyi durduruyordu (liste altta degismesin). Flet'te kutu
      Flet dongusunde, yoklama Qt thread'inde -- durdurmak iki thread'i
      elle esitlemek demek. Zararsiz: isaretler SLOT ile tasiniyor, yani
      liste tazelense de silinecek kayitlar ayni kalir.

- [ ] **Ayar ekraninda deger MENUSU yerine acilir kutu.** Qt deger
      dugmesine basinca `QMenu` aciyordu: secilide TIK, varsayilan
      KALIN. Flet'te `ft.Dropdown`; varsayilan yine kalin duruyor, tik
      isaretini Dropdown kendi koyuyor. Tek fark menunun dugmenin
      ALTINDA degil kutunun icinde acilmasi.

- [ ] **Ayar ekrani sistem temasini izlemiyor** -- yukaridaki tema
      karari. Ayar ekraninin KENDISI artik Flet oldugu icin "temayi
      degistirdim, bu pencere degismedi" goruntusu en cok burada goze
      carpiyor; panel bunu alt satirda yaziyor.

- [ ] **Ayar ekrani imlecin ekraninda acilmiyor.** Qt
      `center_on_cursor_screen` kullaniyordu; oteki on bir panelle ayni
      kayip, ayni sebep.

- [ ] **Slot kutusunun olcusu sabit** (480x330). Qt `adjustSize` ile
      380-520 piksel arasinda kendini ayarliyordu; cok uzun "eski" degeri
      artik kutuyu buyutmuyor, 160 karakterde zaten kirpiliyor.

---

# DEGISMEYEN BILGI

Buradan asagisi is listesi DEGIL: mimari, panel yazarken bilinmesi
gerekenler, sondajlarin nasil calistirildigi.

## Mimari

    ana thread     app.exec()            Qt: tepsi, kalan PySide pencereleri
    hook thread    GetMessage            tuslar -- win32/hook.py, ZATEN ayriydi
    flet thread    ft.run() + asyncio    keypilot/fui/engine.py

Ana thread'in "kutsal" olmamasinin sebebi klavye hook'unun kendi mesaj
pompasinin olmasi (`SetWindowsHookEx`, Qt dongusune bagli degil).

**Iki yon, iki kural:**

| Yon | Yol | Neden |
|---|---|---|
| Qt -> Flet | `FletEngine.call()` | Dogrudan `page.update()` SESSIZCE olu: baska thread'den cagrilinca is kuyruga girer, dongu uyanmaz, ekranda hicbir sey olmaz, log'a tek satir dusmez. |
| Flet -> Qt | QObject sinyali | `dispatcher.ui_open` yazmak `reset()` zincirini calistiriyor; durum makineleri kilitsiz, Qt ana thread'inde kosmalilar. Alicisi ana thread'de olan sinyali Qt kendiliginden kuyruga alir. |

**Panel tasima kurali:** Qt widget'inin ARAYUZUNU aynen koru
(`show_rows` + `closed` gibi). `app.py`'de degisen tek sey hangi sinifin
kuruldugu olsun. Boylece geri donus de tek satir.

**Olculen degerler:** ilk acilis 1.0-3.5 sn (`flet.exe` ayaga kalkiyor;
sistem isindikca alt sinira yaklasiyor), sonraki acilislar 0.0-0.1 sn
(pencere kapanmiyor, gizleniyor). Panel acan cagri ana thread'i
bloklamiyor (0.001-0.01 sn'de donuyor).

**Cizim maliyeti** (adim 4'te olculdu, log penceresi): `page.update()`
suresi denetim sayisiyla dogru orantili ve cizim bitene kadar Flet
dongusu BASKA HICBIR SEYE yanit vermiyor -- Esc de, dugme de, kaydirma
da bekliyor.

| Ne | Sure |
|---|---|
| 545 satir, satir basina 7 denetim | 1.04 sn |
| ayni liste, satir basina 4 denetim | 0.40 sn |
| 2000 satir, 4 denetim | 2.28 sn |
| 2000 kayit, en yeni 500'u cizilerek | 0.42 sn |
| `scroll_to` (istemciye gidip donen cagri) | 0.3-0.4 sn |

Cikan uc kural: **satir basina denetim sayisini kis** (sabit genislikli
yazi tipinde sutunlar dolguyla tek `Text`e sigar), **cizilen satiri
sinirla**, ve **istemciye gidip donen cagrilardan kacin** (sona kaydirmak
icin `scroll_to` yerine `auto_scroll` ozelligi -- ayni `update()` icinde
gidiyor).

**OTOMATIK GUNCELLEME KAPALI (adim 5.5, bildirilen hatanin sebebi; `8e8f4ea`).**
Flet 0.86 her olay isleyicisinden sonra `session.after_event` calistiriyor
ve isleyici KENDI `update()`ini cagirmadiysa "otomatik guncelleme"
yapiyor: en yakin IZOLE ataya kadar yukari yuruyup onu guncelliyor.
Flet'te izole isaretli tek denetim `Page`, yani bu HER OLAYDAN SONRA TUM
SAYFA demek.

Yukaridaki cizim maliyetiyle birleşince sonuc su: log listesi
`auto_scroll` ile kaydiginda `on_scroll` saniyede onlarca kez geliyor,
isleyicisi yalnizca kaydirma konumunu not ediyor (`update()` cagirmiyor),
ve her biri 500 satirlik TAM bir cizim baslatiyor. Cizim surerken dongu
baska hicbir seye bakmadigi icin isler birikiyor ve **pencere kapatma
dugmesine yanit vermiyor** -- bildirilen "Show log kapanmiyor" hatasi
buydu. Ayni sessiz maliyet suzgecin `FILTER_MS` gecikmesini de bosa
cikariyordu: her harfte zaten tam cizim oluyordu.

`fui/engine.py` `_disable_auto_update()` bunu SUREC genelinde kapatiyor
(`start()` icinde, bir kez). Kapatmak guvenli, cunku bu paketteki her
isleyici cizimini acikca yapiyor: `page.update()` cagiriyor, isi `call()`
ile kuyruga birakiyor, ya da gorunen bir sey degistirmiyor. Kutular
(`show_dialog` / `pop_dialog`) kendi denetimlerini guncelliyor.

**Yeni panel yazacak olana kural:** denetim degistirdiysen cizimi KENDIN
iste. Flet artik arkandan toplamiyor.

**ARTIMLI CIZIM (adim 6'da olculdu).** Yukaridaki tablo "listeyi bastan
kur" varsayimiyla cikmisti: her cizimde satirlar icin YENI denetim
nesneleri uretiliyor. Denetim nesneleri YASATILIRSA maliyet coguyor.
400 satirlik liste, satir basina iki denetim:

| Ne | Sure |
|---|---|
| BOS listeye 400 satir koy (ilk dolum) | 118 ms |
| listeyi bastan kur (400 satir zaten varken) | 145-162 ms |
| yalnizca 2 yeni satir ekle | 26-31 ms |
| 20 yeni satir ekle | 31 ms |
| hicbir sey degistirmeden `update()` | 25-30 ms |
| tek satirin zemin rengi | 25 ms |

Uc ders. Birincisi **bastan kurmak bes kat pahali** -- akan bir listede
`listing.controls.append(...)` kullanilmali, `listing.controls = [...]`
degil. Ikincisi **bir `page.update()`in bir TABANI var**: Flet agaci
degisiklik olmasa bile bastan yuruyor, yani CIZIM SAYISI da kisilmali.
`fui/monitor.py` ikisini de yapiyor (bkz. `DRAW_MS`).

Ucuncusu: **o taban SABIT DEGIL, agac boyutuyla orantili.** Ayni panelde
olculdu -- 400 satirda 25-30 ms, ~200 satirda 13 ms. Yani listenin tavani
(`MAX_ROWS`) yalnizca bellek degil CIZIM HIZI ayaridir; bir panel agir
geliyorsa ilk bakilacak kol bu.

Gercek yuk altinda olculdu (`probes/flet.py`deki akisin ayni, saniyede
240 olay -- hizli yazan birinin ~12 kati): cizim ortalamasi **41 ms**,
150 ms'lik pencerenin dortte biri; en uzun tek cizim 198 ms ve o, akis
surerken yapilan BASTAN KURMA. Insan hizinda (~20 olay/sn) taban degere,
25-30 ms'ye iniyor.

> **OLCUM NASIL YAPILDI.** Tek kullanimlik bir betik: Flet penceresi
> acar, `page.update()` cagrilarini `perf_counter` ile sarar, sayilari
> yazip kapanir. Projede TUTULMADI (`probes/` altina girmedi) -- burada
> duran sayilar sonucu. Bir sonraki agir panelde (ornegin
> `settings_dialog.py`) yeniden gerekirse ayni kalip: bos bir sayfa, bir
> `ListView`, ayni islemin uc-bes turu ve turlar arasinda
> `await asyncio.sleep(0.15)` (dongunun mesajlari bosaltmasi icin --
> bunsuz olcum takiliyor).

> **BILINEN SINIR:** `_flush` her turda kosulsuz cizim istiyor. Bir cizim
> `DRAW_MS`i SUREKLI asarsa istekler birikir. Olculen degerlerde bu
> olmuyor (yalniz bastan kurma 150 ms'i asiyor ve o tekrarlanmiyor);
> olursa cozum bir "cizim surerken yenisini isteme" bayragi.

**Bir panelin uc parcasi.** Ucunun de ayni oldugu kalip:

| Parca | Nerede koser | Ornek |
|---|---|---|
| Qt'nin gordugu yuz | ana thread | `show_rows`, `show_paused`, `show_slot`, `shutdown` |
| Cizim ve olaylar | flet thread | `_build`, `_show_now`, `_hide_now`, `_on_key` |
| Cikan yol | sinyal, ana thread'e duser | `closed`, `resume`, `saved` |

Ilk cagri sayfayi bulamazsa (`engine.page is None`) thread baslatilir ve
BEKLENMEZ; `_build` bekleyen veriyle kendini cizer. Bekleseydi ana
thread 3.5 saniye donar, tepsi ve tus kuyrugu takilirdi.

## Panel yazarken bilinecekler

Her biri BIR ADIMDA ogrenildi ve bedeli odendi; hepsi hala gecerli.

**YASAYAN PANEL kurali (adim 3'te ogrenildi).** Qt'de "her acilista yeni
pencere kur, kapaninca yok et" ucuzdu (`WA_DeleteOnClose`). Flet'te ayni
kalip her acilisa `flet.exe`nin yeniden ayaga kalkmasini, yani saniyeleri
ekliyor. Bu yuzden Flet paneli BIR KEZ kurulur, yasar ve veriyle
tazelenir. Sonucu iki yerde gorunuyor:

* **Panelin arayuzu degisir.** Kurucuya verilen veri bir `show_*`
  metoduna tasinir: `SlotEditDialog(index, ...)` -> `show_slot(index, ...)`.
* **Cagiran taraf hedefi kendi tutar.** Sinyal artik "hangi nesne
  kapandi" demiyor; `slots_ctl.py` duzenlenen slotu `_editing` icinde
  not ediyor ve `saved(ad, icerik)` gelince oraya yaziyor. Ayni anda tek
  kutu acik oldugu icin tek deger yetiyor.

Bu, plandaki "app.py'de tek satir degissin" kuralinin ilk istisnasi:
kurulum/yikim kaliba gomulu oldugu icin cagiran dosya da degisiyor.

**QT'YE IS YAPTIRMA kurali (adim 4'te ogrenildi, adim 5.5'te ortaklandi).**
Panelin dugmesi bazen Flet'in yapamayacagi bir sey istiyor: panoya yazmak
(`QApplication.clipboard`), dosya okumak, bir Qt kutusu acmak. Bunlar Flet
dongusunde kosmamali -- `FletEngine.call()`in TERS yonu gerekiyor. Yol
motorda:

    self._engine.ask_qt(self._copy_selected)

Alicisi ana thread'de kurulmus bir nesne (`FletEngine` artik `QObject`)
oldugu icin Qt sinyali kendiliginden kuyruga aliyor: `emit` Flet
thread'inde hemen doner, is ana thread'in sirasi gelince kosar.

> Adim 4'te `fui/log_view.py` icinde `_on_qt` diye dogdu, adim 5'te
> `fui/qr.py`ye birebir kopyalandi. Plandaki "ikinci panel de isterse
> ortak yere tasinsin" kurali oradaydi; ucuncu kullanici (monitor)
> gelmeden once tasindi -- kendi commit'inde, `f56ff95`.

Ayni adimda cikan cizim kurallari **Olculen degerler** bolumunde.

**PENCERE OLCUSU kurali (adim 5'te ogrenildi).** Flet'in Material
denetimleri Qt'nin widget'larindan KALIN: bir giris kutusu en dar haliyle
~36 piksel, Qt'de ~24. Pencere olcusu Qt'ninkinden kopyalanirsa icerik
sigmiyor, "yeterince buyuk" bir sayi verilirse altta bos serit kaliyor.
Uc pratik kural:

* **Genislik Qt'den kopyalanabilir**, yukseklik KOPYALANAMAZ. QR
  penceresi: genislik 640 (Qt ile birebir), yukseklik Qt'nin 605'i yerine
  729 (Wifi sablonu).
* **Tek satirlik kutulara `height` VER.** Verilmezse Material varsayilani
  ~48 piksel ve pencere gozle gorulur uzuyor.
* **Cok satirli `TextField`e `height` VERME.** Kutu yerini ayirtiyor ama
  TEK SATIR cizip altini bos birakiyor; yukseklik `min_lines`/`max_lines`
  ile verilmeli (olculdu, `fui/qr.py` `RAW_LINES`).

Olcmenin yolu: Qt surumunu acip `widget.size()` yazdirmak (istemci alani
-- Flet'in `window.height`i baslik cubugunu DA sayiyor, ~31 piksel fark),
sonra Flet penceresini acip ekran goruntusu almak. `probes/flet.py` ile
ikisi de programa dokunmadan acilabiliyor.

**PLANIN BOLMESI DAGILABILIR (adim 5).** Bu adim planda 4a/4b diye ikiye
bolunmustu; gerekcesi "PNG kaydetme `ft.FilePicker` ister, o da servis
olarak kurulmali" idi. Adim 4'un `_on_qt` kalibi o gerekceyi cop etti:
dosya kutusu da pano da ZATEN Qt tarafinda kosmali, yani ikisi de birer
satir oldu ve pencere tek adimda bitti. **Ders:** bir sonraki adimin
tahmini, bir onceki adimin ogrettikleriyle yeniden bakilmadan
uygulanmamali.

**CANLI PANEL kurali (adim 6'da ogrenildi).** Bir panel saniyede
onlarca kez guncelleniyorsa iki sey birden gerekiyor:

* **Biriktir, sonra ciz.** Veriyi alan yol (burada `add`, ana thread)
  CIZMEZ; yalnizca listeye yazar. Cizimi bir `QTimer` yapar. Boylece
  cizim sayisi olay sayisindan bagimsizlasir.
* **Denetimleri yasat.** Cizim yeni satirlari EKLER, listeyi bastan
  kurmaz (bkz. **ARTIMLI CIZIM**). Bastan kurma yalnizca sira degisince
  ya da liste temizlenince.

Ucuncu bir sey daha cikti: **"pencere acik mi" sorusu ANA THREAD'de
cevaplanmali.** `app.py` `_drain` her olayda bunu soruyor ve Qt'de
`isVisible()` idi; Flet penceresinin durumu Flet thread'inde ve her tus
icin thread'ler arasi gidip donmek olmaz. `fui/monitor.py` duz bir
`visible` bayragi tutuyor, `show_monitor` kaldiriyor, `_hide`/`close`
indiriyor.

**Kodda ornek panel.** Yeni panel yazan en yakin kalibi buradan alsin:
`fui/key_map.py` (salt okunur), `fui/pause.py` (dugmeli),
`fui/slot_edit.py` (kullanicidan METIN alan, yasayan panel),
`fui/log_view.py` (iki sekme, zamanlayici, Qt'ye is yaptirma, cizim
sinirlama), `fui/qr.py` (calisma aninda dogan/olen denetimler, resim),
`fui/monitor.py` (CANLI akan liste -- artimli cizim), `fui/macro.py`
(DISARIDAN gelen durumu yazan ilk panel), `fui/ocr.py` (HEP USTTE duran
pencere + gizle/geri getir), `fui/repository.py` (UC SUTUNLU form),
`fui/profiles.py` (IKI KADEMELI liste + Flet'in yapamadigi isi Qt'ye
yaptiran kalici kopru), `fui/clip_images.py` (DISKTEN gelen resim listesi
+ `ft.InteractiveViewer`), `fui/settings.py` (ayarin TIPINE gore dogan
denetim) ve `fui/tip.py` (cercevesiz + SAYDAM + hep ustte + imlecin
yaninda -- Asama 3 kalibi).

## Nasil denenir

### 1) Deneme penceresi -- gercek programa dokunmadan

    uv run python -m probes.flet

Bu kucuk bir DENEME PROGRAMI (projede `probes/` klasoru zaten bunun icin
var, `probes/gui.py` gibi). Gercek KeyPilot'u BASLATMAZ: tuslari
devralmaz, tepsiye yerlesmez, calisan KeyPilot'u kapatmaz. Sadece
tasinan pencereleri sahte veriyle acar.

Yirmi dort dugmesi var: kisayol haritasi, duraklatma kutusu, duraklatma +
kritik hata metni, uc slot durumu (dolu slot, bos slot, sifre slotu), log
penceresi, olay izleyici, ayar ekrani, pano gorselleri (iki dugme) ve uc
QR girisi (duz metin, link, hazir wifi dizgisi). Log ve QR pencereleri GERCEK dosyalari okuyor
(`Files/log.txt`, `slots.json`) -- sahte veri yok; "Log temizle"
gercekten siliyor, QR'in grup secimi gercekten ayara yaziliyor (ama
ayar dosyasi GECICI -- asagida). Olay
izleyici SAHTE bir akisla besleniyor: saniyede ~40 olay, yani hizli yazan
birinin iki kati (tuslara dokunulmuyor). Makro ekrani GERCEK slot
dosyalarini (`Files/rec*.jsonl`) okuyor ve ad kutusu gercekten diske
yaziyor; kayit/oynatma YAPILMIYOR -- onlari `macro_ctl.py` yapiyor,
sondaj yalnizca gelen sinyali dokume yazip durumu elle geri besliyor
(oynatma iki saniye sonra "Bitti" oluyor). Kod parcasi deposu GERCEK
`repository.md`nin GECICI BIR KOPYASI uzerinde calisiyor
(`%TEMP%/keypilot-sondaj-repository.md`): gorunum gercek veriyle
sinaniyor ama "Kaydet"/"Sil" kullanicinin dosyasina dokunmuyor. Pano
gorselleri GECICI bir depoda SAHTE uc resimle aciliyor
(`%TEMP%/keypilot-sondaj-gorseller`); gercek `clipimg.dat` kopyalanmiyor
cunku 500 MB'a kadar cikabiliyor ve "Sil" gercekten siliyor. Ucuncu
ornek onizleme kutusundan BUYUK: "1:1 / sigdir" ve kaydirma ancak
oyle sinaniyor. Ikinci dugme ("YENI resim ekle") depoya yeni bir gorsel
yaziyor -- acik pencere listeyi 900 ms icinde KENDILIGINDEN
tazelemeli.

Ayar ekrani GERCEK ayar defteri uzerinde calisiyor ama dosya GECICI:
sondaj acilirken `paths.SETTINGS` bir kopyaya cevriliyor
(`%TEMP%/keypilot-sondaj-settings.json`, bkz. `use_probe_settings`).
Yani "Tumu varsayilana" gercekten calisir, kullanicinin
`Files/settings.json`ina DOKUNMAZ -- ve sondaj ayri bir surec oldugu
icin calisan KeyPilot da etkilenmez. Ayni sebeple QR panelinin grup
secimi de artik gercek ayara degil bu kopyaya yaziliyor. Pencerede
bakilacak iki sey:

* **Alt satirdaki sayac** -- her saniye artmali. DURURSA program tarafi
  Flet yuzunden takilmis demektir, yani mimari kirik.
* **Ortadaki doküm** -- panellerden gelen her olay buraya yaziliyor.
  Satirlarda `MainThread` yazmali.

Deneme penceresini kapatinca Flet pencereleri de kapanir. Kapanmazsa
gorev cubugunda `flet.exe` kalir (Gorev Yoneticisi'nden kapatilabilir).

**Ipucu (adim 16) -- BES DUGME, en onemli sinav.** Panel `app.py`ye
BAGLANMADI: gordugun sey yalnizca sondajda kosuyor, gercek programin
ipuclari hala Qt'nin. Sondaj ipucunu ON ISITMA ile aciyor, yani ILK
dugme de aninda gorunmeli (isitma calismiyorsa 1-3.5 saniye beklersin --
o zaman haber ver). Bakilacaklar:

1. **Kutu IMLECIN sag altinda mi?** Fareyi ekranin ortasina getir, bas.
   Sonra fareyi sag alt koseye goturup tekrar bas: kutu ekran disina
   TASMAMALI, ice cekilmeli. Ikinci monitorde de dene -- konum hesabi
   fiziksel/mantiksal piksel cevrimi yapiyor ve orasi negatif
   koordinatta.
2. **Cerceve gitti mi?** Baslik cubugu, kenarlik ve kapatma dugmesi
   OLMAMALI; yalnizca yuvarlak koseli koyu kutu.
3. **SAYDAMLIK -- bu adimin en kritik sinavi.** Kutunun DISINDA kalan yer
   saydam olmali. Kutunun etrafinda koyu bir DIKDORTGEN gorunuyorsa
   saydamlik tutmamis demektir: haber ver, o zaman pencere olcusu
   metinden hesaplanacak (`window_size` comert degil TAM olacak).
4. **ODAK GITMIYOR mu?** Bir yere yazarken (Not Defteri) ipucu dugmesine
   bas -- yazdigin yerden odak GITMEMELI. Adim 14'te olculdu, burada
   dogrulaniyor.
5. **Gorev cubugunda gorunmuyor mu?** Ipucu acikken gorev cubuguna bak:
   `KeyPilot ipucu` diye bir pencere OLMAMALI (`skip_task_bar`).
6. **Metin dogru mu?** "HTML" dugmesi: **KeyPilot** kalin, `version` ve
   `build` SOLUK gri, uc satir. "Duz metin" dugmesinde HTML
   yorumlanmamali.
7. **Olcu.** Metin KIRPILIYORSA ya da kutu gereksiz genisse `CHAR_PX`
   tahmini tutmamis demektir -- haber ver, hangi metinde oldugunu soyle.
8. **Resimli ipucu.** Solda 64x64 kucuk resim, saginda iki satir metin.
   Resim gorunmuyorsa haber ver.
9. **Menu.** Rozetler (1/2/3) sabit genislikli ve kendi zeminli; ikinci
   satirdaki `x4` SOLUK olmali. Baslik MAVI.
10. **Kendi kendine kapaniyor mu?** Sureler 2-4 saniye. "KAPAT" dugmesi
    hemen kapatmali; kapattiktan sonra suresi dolan bir sayac pencereyi
    ikinci kez KAPATMAYA CALISMAMALI (goze carpan bir sey olmaz, ama
    log'a hata dusmemeli).

### 1b) Odak sondaji -- Asama 3'un olcumu

    uv run python -m probes.focus

Ayri bir sondaj: panel DENEMEZ, odak olcer (bkz. **ADIM 14 -- ODAK
OLCUMU**). Kendi hedef penceresini aciyor
(`probes/focus_target.py`), Flet penceresini sekiz ayri yoldan
gosteriyor ve her seferinde odagin nerede oldugunu 20 ms'de bir
orneklyor. ~2 dakika surer, sonuc konsola tablo olarak dusuyor.

**Olcum sirasinda makineye DOKUNMA.** Odak calan baska bir uygulama
(IDE, calisan bir Flutter ornegi) olcumu kirletiyor; sondaj bunu
farkedip tekrar deniyor ama her seferinde kurtaramiyor -- satirda
"OLCULEMEDI" yaziyorsa o senaryo yeniden calistirilmali.

### 1c) Ipucu sondaji -- adim 16'nin olcumu

    uv run python -m probes.tip

Panel DENEMEZ, ipucu penceresini OLCER. Ekrani ipucu kapaliyken yakalar,
gosterir, tekrar yakalar ve degisen pikselleri sayar -- saydamligin
calisip calismadigi ancak boyle anlasiliyor. Ayrica pencere bayraklarini
dokuyor (hangi Flet ayari GERCEKTEN isledi) ve isitilmis/isitilmamis
acilis suresini olcer. ~1 dakika surer.

Makineye dokunmak GEREKMIYOR (odak sondajindan farki bu: burada odak
degil piksel okunuyor), ama ekran gorunur olmali -- kilitli ekranda ya da
uzak masaustu kapaliyken olcum anlamsiz.

Sonuc tablosu ve cikan kararlar: arsivde **ADIM 16 -- IPUCU**.

**Sondaj UC panel aciyor** (ana panel + iki acilis olcumu) ve her biri
ayri bir `flet.exe`. Kapanis GARANTI ALTINDA: `main()` ne olursa olsun
(istisna, Ctrl+C) hepsini kapatiyor -- yoksa yarida kesilen bir tur gorev
cubugunda uc sahipsiz pencere birakiyordu, bir kez oyle oldu ve dokuz
artik toplandi. Motorun kendisi saglam (olculdu: `engine.stop()` 0.33
sn'de thread'i olduruyor ve `flet.exe` gidiyor); eksik olan cagrinin
GARANTISIYDI. Yeni bir sondaj yazan ayni kalibi izlesin: paneli
`new_panel()` ile kur, `finally: close_all()`.

### 2) Gercek program

`hotkey.vbs`e cift tikla -- normal calistirma yolu.

**Kisayol haritasi:**

1. `´` tusuna bas (Backspace'in solundaki tus). Bir menu acilir.
2. Menude **k** harfine bas -- "Kisayol haritasi".
3. Tablo acilmali (ilk acilista ~3-4 saniye bekleyebilir, sonrakiler
   aninda).
4. Pencereyi kapat (Esc ya da X).
5. **EN ONEMLI ADIM:** simdi F13'e bas. Menu acilmali. Acilmiyorsa
   pencere kapaninca kisayollar geri gelmemis demektir -- bu bir hata,
   haber ver.

**Duraklatma kutusu** (iki yoldan biri):

* `´` tusu -> **p** harfi, ya da
* **Pause** tusunu BASILI TUT, ya da
* Tepsi simgesine sag tikla -> "Pause menu..."

Dort dugmeyi de dene:

* **Devam et** -- kutu kapanir, tuslar geri gelir.
* **Yeniden baslat** -- program kendini yeniler.
* **Kaydetmeden yeniden baslat** -- ayni, ama pano dosyasina yazmaz.
* **Cikis** -- program kapanir. Kapandiktan sonra Gorev Yoneticisi'nde
  `flet.exe` KALMAMALI.

X ile ya da Esc ile kapatmak "Devam et" ile ayni sey demek.

**Slot duzenleme kutusu:**

1. **F14** tusuna KISA bas (basili tutma -- o secim araci). Menu acilir.
2. Menude **Edit ^** alt menusune gir, bir slot numarasi sec.
3. Kutu acilmali: uc satir (ad / eski / yeni) ve altta Kaydet + Iptal.
   Imlec **ad** kutusunda olmali.
4. Bakilacaklar:
   * **eski** satiri slotun SIMDIKI icerigini gosteriyor mu? Slot bossa
     `(bos)` yazmali.
   * **yeni** kutusu PANODAKIYLE mi acildi? (Once bir seyler kopyala,
     sonra menuyu ac.) Pano bossa slotun kendi icerigi gelir.
   * Bir seyler yaz, **Kaydet**. Sag altta "💾 ad" ipucu cikmali ve
     degisiklik slotta durmali (ayni menuden tekrar acip bak).
   * **Iptal**, **Esc** ve **X** hicbir sey kaydetmemeli.
   * **ad** kutusundayken **Enter** Kaydet demek.
5. Kutuyu kapat, sonra **BASKA bir slot** ac. Bu sefer aninda acilmali
   (pencere yasiyor) ve icindekiler YENI slota ait olmali -- eski slotun
   metni kalirsa bu bir hata, haber ver.
6. **Sifre slotu (10).** Eski deger `••••••••` gorunmeli, acik metin
   ASLA yazmamali; pano bossa **yeni** kutusu BOS acilmali.

**Log penceresi** (iki yoldan biri):

* `´` tusu -> menude **2** ("Show stats"), ya da
* Tepsi simgesine sag tikla -> **Show log...**

Pencere 980x620 acilmali, liste EN ALTTA (en yeni kayit gorunur)
baslamali. Bakilacaklar:

1. **Sutunlar hizali mi?** `tarih | saat | sev | kaynak | mesaj`. Yazi
   tipi sabit genislikte (Consolas); sutunlarin kaymamasi gerekiyor.
2. **Renkler.** Hata/kritik satirlar KIRMIZI yazili; detayi olan satirlar
   koyu sari zeminli ve mesajlarinin sonunda `▾` var.
3. **Detay ac/kapa.** `▾` isaretli bir satira tikla -- traceback hemen
   ALTINDA acilmali, ikinci tik kapatmali. Acip kapatinca listenin
   bakilan yeri KACMAMALI.
4. **Suzgec.** Kutuya bir sey yaz (ornek: `flet`), liste daralmali. Yazma
   bitiminden ~0.15 sn sonra ciziliyor, yani her harfte beklemiyor.
5. **Yalniz hata/uyari** kutusu: yalnizca kirmizi/sari kayitlar kalmali.
6. **Alt satir.** `N / M kayit · K hata-uyari · <dosya yolu>`. Cok kayit
   varsa basinda `son 500 gosteriliyor` yazar -- bu normal (bkz.
   `RENDER_LIMIT`).
7. **Dort dugme.** *Yenile* listeyi tazeler; *Satiri kopyala* SECILI
   satiri panoya alir (once bir satira tikla); *Dosyayi ac* Notepad
   acar; *Log temizle* ONAY sorar ve Evet dersen dosyayi bosaltir.
8. **Durum sekmesi.** Ustteki "Durum" sekmesinde hook sayaclari olmali.
9. **Esc / X** pencereyi kapatir. Kapattiktan sonra tekrar ac: aninda
   acilmali.

**Olay izleyici** (iki yoldan biri):

* `´` tusu -> menude **4**, ya da
* Tepsi simgesine sag tikla -> **Event monitor...**

Pencere 820x520 acilmali ve TUSLARA BASTIKCA satir eklenmeli. Qt
surumunden farkli olarak satirlar aninda degil, en fazla 0.15 saniye
gecikmeyle giriyor -- akan liste goze aynidir, sebebi planda
(**CANLI PANEL kurali**). Bakilacaklar:

1. **Sutunlar hizali mi?** `t | tus | vk | sc | yon | durum`. Yazi tipi
   sabit genislikte; `Media_Play_Pause` gibi uzun bir ad (medya tusu)
   sutunu kaydirmamali.
2. **Yutulan olaylar KIRMIZI.** `F13`e bas: menuyu acan tus yutuluyor,
   satiri kirmizi olmali.
3. **Fare dugmeleri de listede.** Farenin yan tuslarina bas; `sc`
   sutununda tarama kodu yerine imlecin konumu (`1920,1080`) yazar.
4. **Akis hizli mi?** Bir sure hizli yaz. Liste akarken pencere
   TAKILMAMALI: kaydirma, dugmeler ve X aninda cevap vermeli.
5. **Duraklat.** Isaretle: liste yazmayi birakir ama kisayollar
   CALISMAYA DEVAM eder (F13 menuyu hala acmali). Isareti kaldirinca
   yeniden akar -- duraklatma sirasindaki olaylar KAYIP, Qt surumunde de
   oyleydi.
6. **Yeni ustte.** Isaretle: yeni olaylar en uste duser ve liste
   kaymaz. Isaretsizken liste hep sona kayar.
7. **Satiri kopyala.** ONCE bir satira tikla (zemini mavi olur), sonra
   dugmeye bas. Bir yere yapistir: o satir gelmeli.
8. **Tumunu kopyala.** En fazla 400 satir gelir -- listenin tavani bu,
   Qt surumundeki sayinin ayni.
9. **Temizle.** Liste ve alt satirdaki `olay N / yutulan M` sayaclari
   sifirlanmali; `t` sutunu bir sonraki olayda sifirdan baslamali.
10. **Esc / X** kapatir. Kapaliyken maliyet SIFIR olmali: kapattiktan
    sonra program gozle gorulur sekilde hafiflemeli (kapaliyken olaylar
    panele hic gitmiyor). Tekrar acinca aninda gelmeli ve liste BOS
    baslamali degil -- kapatmadan onceki olaylar durur.

**QR penceresi** (iki yoldan biri):

* **F14** tusuna KISA bas -> menude **QR kod**, ya da
* CapsLock'u basili tut (hizli panel) -> bir oge sec -> **Alt+q**.

Pencere PANODAKIYLE aciliyor, yani once bir sey kopyalamak isi kolaylastirir.
Bakilacaklar:

1. **Sablon tahmini.** `https://` ile baslayan bir metin kopyalayip ac:
   ustteki **Link** dugmesi secili gelmeli. Duz metinde **Metin**,
   `WIFI:...` ile baslayan bir dizgide **Wifi**.
2. **Canli kare.** Alandaki metni degistir -- kare HER TUSTA yenilenmeli,
   beklemesiz. Sag altta `ver3 · 41 bayt` gibi bir sayac var; icerik
   buyudukce surum artar, 20'yi gecince `⚠ cok yogun` yazar.
3. **Kare okunuyor mu?** Telefonun kamerasini tut. Okumazsa **ham icerik**
   kutusuna bak: hata bicimde mi veride mi orada gorunur.
4. **Wifi sablonu.** **Wifi**'ye gec: SSID, Parola, Guvenlik ve "gizli ag"
   alanlari gelmeli. Parola NOKTALARLA basliyor; kutunun sagindaki GOZ
   simgesine basinca gorunur olmali. Ham icerik kutusunda parola yine
   `••••` -- acik yazmamali.
5. **Sablon degistirince alanlar sifirlanir**, bu bilerek boyle: eski
   sablonun metnini yeni alanlara tasimak yaniltici olurdu.
6. **Slot listesi.** Ust kutudan grup sec, altta o grubun DOLU slotlari
   listelenir (sifre slotu YOK). Bir satira tikla -- icerigi alanlara
   dolmali ve sablon yeniden tahmin edilmeli. Grup secimi ayara yaziliyor:
   pencereyi kapatip acinca ayni grup secili gelmeli.
7. **Panoya kopyala.** Bir yere yapistir (ornek: Paint) -- kare
   gelmeli.
8. **Kaydet PNG.** Dosya kutusu acilir. **DIKKAT:** bu kutu hala Qt'nin
   (`QFileDialog`), yani Flet penceresinden farkli gorunuyor -- gecis
   suresince normal, bkz. **Tam geciste SILINECEK / DUZELTILECEK**.
9. **Pencere boyu.** Metin/Link sablonunda kisa, Wifi'de daha uzun bir
   pencere acilmali (alan sayisina gore). Altta bos serit KALMAMALI.
10. **Esc / X** kapatir; tekrar acinca aninda gelmeli ve icerik YENI
    panodakine gore kurulmali.

**Makro kayit ekrani:**

* `´` tusu -> menude makro kaydediciyi acan secenek.

Pencere 520x400 acilmali: ustte slot listesi + kayit turu, altinda ad
kutusu, uc dugme (Kaydet / Durdur / Oynat), iki onay kutusu, durum
satiri ve altta "Not defterinde ac" + "Kapat". Bakilacaklar:

1. **Slot listesi dolu mu?** `rec1.jsonl  -  ad` bicimi; slot
   degistirince **ad kutusu** o slotun adiyla degismeli.
2. **Ad kutusu diske yaziyor mu?** Bir ad yaz, baska bir yere tikla
   (odak kaybi) ya da Enter'a bas; pencereyi kapatip acinca ad DURMALI.
   Dosyasi olmayan slotta ad tutulmaz -- Qt surumunde de oyleydi.
3. **Kaydet.** Basinca dugme "⏺️ Kayitta" olmali, durum satirinda
   `Kayitta -- rec1.jsonl (Esc: durdur)` yazmali; slot ve tur kutulari
   ile Oynat dugmesi KAPANMALI. Birkac tusa bas.
4. **Durdur** (ya da ayni dugmeye tekrar basmak, ya da **Esc**). Durum
   satirinda `N olay -> rec1.jsonl` yazmali ve dosya gercekten
   olusmali ("Not defterinde ac" ile bak).
5. **Oynat.** Kaydedilen tuslar gonderilmeli; oynarken Kaydet/Oynat
   kapali, durum `Oynatiliyor -- ...`. Bitince `Bitti -- N olay`.
   Ortada **Esc** oynatmayi kesmeli.
6. **Iki onay kutusu.** Ayarin KENDISI degisiyor: isaretleyip ayar
   ekranindan bak, ayni degeri gostermeli.
7. **Bos slot oynatilmaz:** `Kayit bos: recN.jsonl` yazmali.
8. **Esc / X / Kapat** pencereyi gizler ve suren kaydi DURDURUR (Qt
   surumu de oyleydi). Tekrar acinca aninda gelmeli.

**OCR sonuc paneli:**

* **F14** tusuna BASILI TUT, bir alan sec -> OCR+ eylemi (menude
  gelismis OCR).

Pencere 860x560 acilmali ve HEP USTTE durmali. Bakilacaklar:

1. **Hep ustte mi?** Baska bir pencereye tikla -- OCR paneli ustte
   KALMALI (duraklatma kutusunda calisiyordu, burada pencere uzun sure
   acik kaliyor). Kalmiyorsa haber ver.
2. **Secim cercevesi.** Panel acikken cerceveyi kenarindan cek: alan
   yeniden okunmali ve panel kendini tazelemeli. Bu sirada panel
   EKRANDAN KAYBOLUP geri gelmeli (kirpimin icine girmesin) -- gecikme
   gozle gorulur ama metin yeni alanin metni olmali.
3. **Bicim.** "Duz metin" / "Kolonlu" / "Tablo (ayracli)" arasinda gec.
   Tabloda hucreler ayracla ayrilmali; ayrac kutusu YALNIZ tabloda
   acik, otekilerde pasif. "Duz metin"de kolon esigi de pasif.
4. **Ayrac kutusuna elle yaz** (ornek: `	` ya da `;`) -- metin aninda
   yeniden dizilmeli. Kutu duzenlenebilir: listeden secmek de elle
   yazmak da is gormeli.
5. **Kolon esigi.** "Otomatik" disinda bir deger sec (ornek `80px`) --
   kolon bolme degismeli.
6. **Olcek.** Degistirince alt satirda "okunuyor..." yazip yeniden OCR
   yapmali (ekran TEKRAR CEKILMEZ, elimizdeki kirpim okunur).
7. **Yenile.** Ekran tekrar cekilir: altta duran sayfayi kaydir, sonra
   Yenile'ye bas -- yeni icerik gelmeli.
8. **Metin kutusu.** Kolonlu/tablo biciminde sutunlar HIZALI olmali
   (sabit genislikli yazi tipi, satir SARILMIYOR); uzun satirda alttan
   yatay kaydirma cikmali. Metin SECILEBILIR ama duzenlenemez -- Qt
   surumunde duzenlenebiliyordu, kaybin sebebi asagidaki listede.
9. **Kopyala.** Bir yere yapistir; metin pano gecmisine de dusmeli.
10. **Esc / X / Kapat** pencereyi gizler VE secim cercevesini de kapatir
    (`closed` -> `snip.end_session`). Cerceve ekranda kalirsa bu bir
    hata, haber ver.

**Kod parcasi deposu:**

* `´` menusunden **Repository** (ya da tepsi menusu > 📚 Repository).

Pencere 1020x620 acilmali; solda kategoriler ve etiketler, ortada
sonuclar, sagda alanlar. Bakilacaklar:

1. **Acilista diskten okuma.** Depoyu Notepad'de degistirip pencereyi
   ac -- yeni hal gelmeli (pencere yasiyor, veriyi HER acilista
   tazeliyor). Acikken degistirdiysen **Diskten tazele**.
2. **Arama** her tus vurusunda suzmeli: baslik, kategori ve GOVDE
   iciyle eslesiyor, etiketle DEGIL.
3. **Kategori tek secim**; secili satira tekrar tiklamak suzgeci
   kaldirmali (Qt'deki `ToggleList` davranisi).
4. **Etiketler coklu.** Secilen etiketlerin HEPSINI tasiyanlar kaliyor.
   Ustteki `(tumu)` satiri secimi bosaltir; bir etiket secilince
   `(tumu)` kendiliginden kalkmali. Etiket listesi arama + kategori
   sonucundan geliyor: listede duran hicbir etiket sonucu SIFIRA
   dusurmemeli.
5. **Secim -> alanlar.** Sonuclardan bir kayda tikla; sagdaki alanlar
   dolmali, UUID satiri kaydin kimligini yazmali.
6. **Kaydet.** Basligi degistir, Kaydet -- ortadaki liste ANINDA
   guncellenmeli ve dosyada AYNI uuid uzerine yazilmali (yeni kayit
   ACILMAMALI). Bosluk: baslik bos birakilirsa "Baslik zorunlu."
   kutusu cikmali.
7. **Yeni.** Alanlar bosalir, UUID `(yeni)` olur; Kaydet'e basinca
   listeye yeni bir kayit dusmeli. Yeni kategori/etiket yazdiysan
   soldaki listelerde gorunmeli.
8. **Sil** onay ister; Evet dendiginde kayit hem listeden hem dosyadan
   gitmeli.
9. **Esc / X / Kapat** pencereyi gizler. Tekrar acinca aninda gelmeli.

**Profil yoneticisi:**

* `´` menusunden **Profiller** (ya da F13 menusunde "Profil duzenle
  (...)"), ya da tepsi menusu.

Pencere 1000x660 acilmali; solda profiller, ortada secili profilin
aksiyonlari, sagda secili aksiyonun alanlari. Bakilacaklar:

1. **Acilista diskten okuma** ve ILK profilin secili gelmesi. F13
   menusunden "Profil duzenle (<ad>)" ile acildiysa O profil secili
   gelmeli.
2. **Profil secimi** ortadaki listeyi kurmali ve SAG SUTUNU BOSALTMALI
   -- oteki profilin aksiyonu sagda asili kalirsa bu bir hata.
3. **Eslesme kurali** (sol altta) sinif/baslik alanlarini duz Turkce
   anlatmali; ikisi de bosken UYARI yazmali. Kural SECIMDE ve
   KAYDETTE tazeleniyor, yazarken degil (Qt'de de oyleydi).
4. **KISAYOL -- bu adimin en onemli sinavi.** Sagdaki "Kisayol"
   dugmesine bas: **Qt tarafinda** kucuk bir pencere acilmali ve
   "tusa bas..." demeli. Bir tus kombosuna bas (ornegin Ctrl+Shift+K)
   -- pencere kapanmali ve dugmede o kombo yazmali. Bakilacaklar:
   * Kucuk pencere ONDE aciliyor mu? Flet penceresi baska bir SUREC
     (`flet.exe`) ve odak onda; kutu arkada kalir ya da tus almazsa
     HABER VER -- o zaman yakalamayi hook'tan beslemek gerekecek
     (Asama 3 #16).
   * **Esc** yakalamayi iptal etmeli (eski deger kalir),
     **Backspace/Delete** kisayolu SILMELI.
   * Tek basina Ctrl/Shift/Alt yakalamayi BITIRMEMELI.
   * Kisayolu atadiktan sonra **Kaydet**; sonra o tusa bas -- aksiyon
     calismali (kayit defterine tutturuluyor, `keys_changed`).
5. **Aksiyon Kaydet/Yeni/Sil** ve **▲/▼ tasima**. Sira F13 menusundeki
   siradir: tasidiktan sonra menuyu acip bak.
6. **Tus dizileri** kutusunun altindaki ipucu her satiri "kisayol" ya
   da "duz metin" diye ayirmali (`^+t` kisayol, `merhaba` metin).
7. **Zorunlu alanlar:** profil adi bos -> "Profil adi zorunlu.",
   aksiyon adi bos -> "Aksiyon adi zorunlu.", profil secilmeden
   aksiyon kaydetmek -> "Once profil sec ya da kaydet."
8. **Silme** onay ister; Evet dendiginde hem listeden hem
   `profiles.json`dan gitmeli.
9. **Esc / X / Kapat** pencereyi gizler. Tekrar acinca aninda gelmeli.

**Pano gorselleri:**

* `´` menusunden **Pano gorselleri...**, ya da **F14** menusunde
  **Clipboard images**.

Once BIR EKRAN GORUNTUSU KOPYALA (PrintScreen ya da Win+Shift+S), yoksa
depo bos olabilir. Pencere 1080x640 acilmali; solda 64x64 kucuk resimli
liste, sagda secili kaydin onizlemesi. Bakilacaklar:

1. **Kucuk resimler geliyor mu?** Her satirda resim + iki metin sutunu:
   solda "son kullanim" ve `WxH · KB`, sagda "ilk kayit" ve kac kez
   kopyalandigi. Resim gorunmuyorsa haber ver (thumb diskten HAM okunup
   PNG'ye ceviriliyor, bu adimin yeni isi).
2. **Secim ve onizleme.** Bir satira tikla: sag taraf o gorseli
   gostermeli, alt satirda `WxH px · KB · #id · ilk: tarih` yazmali.
3. **CANLI LISTE -- en onemli sinav.** Pencere ACIKKEN baska bir sey
   kopyala (yeni bir ekran goruntusu). En gec bir saniye icinde yeni
   kayit listenin BASINA dusmeli ve **bakilan kayit degismemeli**
   (secim slot ile tasiniyor).
4. **Zoom ve kaydirma.** Onizlemenin uzerinde fare tekerlegini cevir --
   buyuyup kucumeli; basili tutup surukleyince kaymali. Buyuk bir
   goruntude **1:1 / sigdir** dugmesi gercek piksel olcusu ile
   sigdirilmis gorunum arasinda gidip gelmeli. Kucuk bir gorselde dugme
   is yapmaz (zaten sigiyor, 1:1'de duruyor).
5. **Cift tik = panoya al.** Bir satira cift tikla; sag altta
   "📋 goruntu panoda WxH" ipucu cikmali ve bir yere yapistirinca o
   gorsel gelmeli. Kayit listenin basina gecmeli (son kullanim
   tazeleniyor).
6. **Panoya Al** dugmesi ayni isi SECILI satir icin yapiyor.
7. **Isaret kutulari.** Qt surumunde Ctrl/Shift + tik ile coklu secim
   vardi; Flet'te satirin solundaki KUTU isaretleniyor. Iki kayit
   isaretle ve **Sil**'e bas: "N gorsel silinecek" onayi cikmali. Hicbir
   sey isaretli degilse Sil SECILI kaydi onaysiz siler (Qt'de de
   oyleydi). **Delete** tusu da ayni is.
8. **Liste bosalirsa pencere kapanmali** (Qt surumunun ayni davranisi).
9. **PNG Kaydet** dosya kutusu acmali (kutu Qt'nin, Flet penceresinin
   ARKASINDA kalirsa haber ver) ve secilen yere yazmali; sag altta
   "💾 kaydedildi: ..." ipucu cikmali.
10. **Paint+pano** gorseli Paint'te acmali (`Files/paint/clip-<slot>.png`).
    Acilmazsa panelde "Gorsel Paint'te acilamadi." kutusu cikar.
11. **En alttaki sayac:** `N gorsel · X MB · K kopyalama`. Silince ve
    kopyalayinca guncellenmeli.
12. **Esc / X / Kapat** pencereyi gizler; kapaliyken yoklama DURUR
    (pencere kapaliyken maliyet sifir). Tekrar acinca aninda gelmeli ve
    liste guncel olmali.

**Ayar ekrani:**

* `´` menusunden **⚙️ Ayarlar...** (ya da F14 menusu > System > Ayarlar).

Pencere 860x560 acilmali; ustte arama, solda kategoriler, sagda kartlar,
altta durum + iki dugme. Bakilacaklar:

1. **Kartlar.** Her kartta ad, ortada bilgi (aralik: `1-9`, `0-500 ms`),
   sagda DEGER ve altta aciklama. Deger sutunu butun kartlarda AYNI
   hizada olmali.
2. **Acik/kapali ve secenek** kartlarinda deger bir acilir kutu. Ac:
   VARSAYILAN secenek KALIN yazili olmali. Degistir -- deger kalin olur
   (degismis ayar isareti) ve alt satirdaki "N degismis" sayaci artar.
3. **Sayi kartlari.** Kutu VARSAYILANDA BOS duruyor, saginda `↺` ve
   silik varsayilan var. Bir sayi yaz + Enter: deger yerine yazilir,
   kalinlasir. `↺` varsayilana dondurur ve kutu yine bosalir. Kutuyu
   ELLE BOSALTMAK da varsayilana donmek demek.
4. **Gecersiz deger.** Araligin disinda bir sayi yaz (ornek `mouse`
   gecikmesine 999) ve Enter: **yazdigin kutuda KALIR**, ortadaki bilgi
   KIRMIZI yanar ve ayar DEGISMEZ. Sonra gecerli bir deger yaz --
   kirmizi kalkmali.
5. **Kategori suzgeci** (sol sutun): tiklayinca yalniz o kategori
   gorunur ve kart aralarindaki kategori BASLIKLARI kalkar. Ayracin
   ALTINDA GELISTIRME, en altta **Tümü** olmali.
6. **Arama** her tus vurusunda suzuyor; ad, anahtar, aciklama, etiket ve
   secenekler icinde ariyor. Arama yazinca kategori suzgeci
   KENDILIGINDEN kalkmali (secim "Tümü"ye doner).
7. **Tema.** "Tema" ayarini Koyu/Acik yap: **Qt pencereleri** (tepsi
   menusu, ipucu, hafiza slotlari, ayar ekraninin KENDISI degil) rengini
   degistirmeli. Flet panelleri KOYU KALIR -- alt satirda bunu soyleyen
   bir uyari cikmali. Bu bilerek boyle (bkz. **Karara baglanacaklar**).
8. **↺ Tumu varsayilana** ONAY sorar; Evet dendiginde butun kartlar
   varsayilana doner ve sayac sifirlanir.
9. **📝 settings.json** once diske yazip Notepad'de acar. Dosyada YALNIZ
   varsayilandan farkli ayarlar durmali.
10. **Kapanista kaydetme.** Bir ayar degistir, pencereyi kapat (Esc / X /
    Kapat), sonra programi yeniden baslat (`´` > p > Yeniden baslat):
    ayar YERINDE kalmali.
11. **Ayarin ETKISI.** Degistirdigin ayar gercekten calismali (ornek:
    ipucu suresi, fare gecikmesi). Panel degeri yazmakla kalmiyor,
    aboneleri de tetikliyor -- calismazsa haber ver, bu adimin en onemli
    sinavi o.

---
---

# === BITENLER ===

**Buradan asagisi IS DEGIL, KAYIT.** Biten adimlarin ne getirdigi ve
hangi engelin nasil asildigi burada duruyor. Bir soruna carpildiginda
"bu daha once cozulmus muydu" diye BURAYA bakilir; yapilacak is
yukaridaki **YAPILACAK** bolumunde.

## Hangi adim ne getirdi

| Adim | Ne | Commit |
|---|---|---|
| 1 | kisayol haritasi | `7cbca8c` |
| 2 | duraklatma kutusu | `8775927` |
| 3 | slot duzenleme -- ilk YASAYAN panel | `609573b` |
| 4 | log penceresi -- Qt'ye is yaptirma dogdu | `45f525e` |
| 5 | QR penceresi -- planda 4a/4b idi, tek adimda bitti | `eff1be8` |
| 5.5 | `ask_qt` ortaklastirildi | `f56ff95` |
| 6 | olay izleyici -- ilk CANLI panel | `e4b4606` |
| 7 | makro kayit ekrani | `fda9923` |
| 8 | OCR sonuc paneli | `09dcb7a` |
| 9 | kod parcasi deposu -- ilk PANEL TESTI (19) | `885d832` |
| 10 | hafiza slotlari -- YARIM KALDI | `1ebcb8d` |
| 11 | profil yoneticisi -- ilk kalici Qt koprusu (26 test) | `8fbd4ab` |
| 12 | pano gorselleri -- ilk RESIM LISTESI (38 test) | `0103f83` |
| 13 | ayar ekrani -- en buyuk form, ASAMA 2 BITTI (42 test) | `c00f95c` |
| 14 | odak olcumu -- kod degil OLCUM | `7a0ba3c` |
| 15 | on isitma + odak koprusu (9 test) | `6f59b07` |
| 16 | ipucu -- ilk Asama 3 paneli, yazildi (29 test) | -- |

Uc sey her adimda tekrarlandi ve ise yaradi:

* **Once olc, sonra yaz.** Adim 10'da tersi yapildi (panel yazildi, sonra
  baglanamadi) ve dosya oylece duruyor. Adim 14 ve 16 olcumle basladi;
  16'da olcum panel yazildiktan SONRA da yapildi ve UC SESSIZ HATA buldu.
* **Panelin arayuzu korunur** (`show_rows` + `closed`), boylece geri donus
  `app.py`de tek satir.
* **Panelin kendi birim testi olur:** Flet calistirilmadan panelin QT
  TARAFI surulur. Adim 9'da basladi, adim 16'da 29 teste cikti.

## Asama 1 -- kolay: standart pencere, az cikti

| # | Panel | Satir | Durum | Not |
|---|---|---|---|---|
| 1 | `key_map_view.py` | 176 | **BITTI** | Salt okunur tablo. Tek cikti: `closed`. |
| 2 | `pause.py` | 99 | **BITTI** | 4 dugme, 4 sinyal. `WindowStaysOnTopHint` -> `always_on_top`. |
| 3 | `slot_edit.py` | 92 | **BITTI** | Form: ad + eski deger + yeni deger. Ilk kez ICERI veri alan ve DISKE yazan panel; ilk YASAYAN panel (bkz. **Panel yazarken bilinecekler**). |
| 4 | `qr_view.py` | 341 | **BITTI** | Canli QR + sablona gore degisen alanlar. Planda 4a/4b diye bolunmustu, TEK adimda bitti (bkz. **Panel yazarken bilinecekler**). |
| 5 | `log_view.py` | 421 | **BITTI** | Salt okunur liste + detay. Iki sekme, yoklama zamanlayicisi, Qt'ye is yaptirma. #4'ten ONCE yapildi (bkz. adim 3 sonu). |
| 6 | `monitor.py` | 183 | **BITTI** | Canli akan olay listesi. Ilk "surekli guncelleme" paneli: cizim artimli ve zamanlayiciya bagli (bkz. **Panel yazarken bilinecekler**). |

## Asama 2 -- orta: durum yazan formlar

| # | Panel | Satir | Not |
|---|---|---|---|
| 7 | `macro_view.py` | 213 | Kayit ekrani. **BITTI** -> `fui/macro.py` |
| 8 | `ocr_view.py` | 229 | `WindowStaysOnTopHint`. Sonuc paneli. **BITTI** -> `fui/ocr.py` |
| 9 | `repository_view.py` | 404 | Kod parcasi deposu. **BITTI** -> `fui/repository.py` |
| 10 | `mem_slots.py` | 454 | **YARIM KALDI -> Asama 3'e tasindi** (satiri disari surukleme). Bkz. arsivin sonundaki **ADIM 10**. |
| 11 | `profiles_view.py` | 468 | Profil yoneticisi. **BITTI** -> `fui/profiles.py` |
| 12 | `clip_images.py` | 486 | Pano gorselleri. **BITTI** -> `fui/clip_images.py` |
| 13 | `settings_dialog.py` | 605 | En buyuk form. **BITTI** -> `fui/settings.py`. Tema karari: **Karara baglanacaklar**. |

## ADIM 14 -- ODAK OLCUMU (yapildi, kod yazilmadi)

Sondaj: `probes/focus.py` (hedef pencere `probes/focus_target.py`).
Calistir: `uv run python -m probes.focus`. Her senaryo, hedef pencere
odaktayken Flet penceresini gosterip iki saniye boyunca 20 ms'de bir
`GetForegroundWindow` orneklyor.

**Olcum KIRLENEBILIYOR.** Makinede odak calan baska bir uygulama varsa
(calisan bir Flutter ornegi, IDE) senaryo bosa gidiyor; sondaj bunu
farkedip temiz olcum alana kadar alti kez deniyor ve alamazsa
"OLCULEMEDI" yaziyor. Ilk iki calistirmada tam bu oldu -- yanlis veriyle
karar verilmedi. Ilk hedef Not Defteri idi, o da guvenilmez cikti
(Windows 11'de tek surec, sekmeli, aradan kapaniyor); hedef artik kendi
actigimiz kucuk bir Qt penceresi.

| # | Senaryo | Sonuc |
|---|---|---|
| A | `window.visible = True` + `to_front()` (panellerin BUGUN yaptigi) | odak hedefte KALDI (3 temiz olcum) |
| B | yalniz `window.visible = True` | odak hedefte KALDI (3) |
| C | `window.focused = False` | odak hedefte KALDI (2) |
| D | `WS_EX_NOACTIVATE` + `ShowWindow(SW_SHOWNOACTIVATE)` | odak hedefte KALDI (2) -- yani gerekmiyor bile |
| E | A'dan sonra odagi hedefe GERI verme | odak GERI GELDI (2) |
| G | `window.focused = True` + `to_front()` | odak yine hedefte -- **Flet penceresi odagi ISTEYEREK DE ALAMIYOR** |
| H | odagi BIZIM surecimizden Flet penceresine ZORLAMA | **odak Flet penceresine VERILEBILDI** (`AttachThreadInput` + `SetForegroundWindow`) |
| F | ILK ACILIS -- `flet.exe` sifirdan ayaga kalkarken | **KARARSIZ:** bir olcumde 2.12 sn sonra odagi CALDI, bir olcumde calmadi, bir olcumde kirlendi |

**Neden boyle:** Windows odak calmayi surec duzeyinde kisitliyor --
`SetForegroundWindow` yalnizca "son girdiyi alan" surece izin veriyor.
`flet.exe` AYRI bir surec ve kullanicinin son tusu bize (ya da hedef
uygulamaya) gitti, yani Flet kendi penceresini one getiremiyor. Bizim
surecimiz getirebiliyor -- H senaryosu bunu gosteriyor.

**Kararlar (dort pencere, iki grup):**

1. **Odak ALMAMASI gerekenler -- `tip.py` (#18), `incognito_badge.py`
   (#17):** engel YOK. Qt'de bunun icin `WA_ShowWithoutActivating`
   gerekiyordu, Flet'te varsayilan davranis zaten bu. Kalan is cercevesiz
   ve hep ustte cizim (`frameless`, `always_on_top`, `skip_task_bar`
   Flet'te var) ve ILK ACILIS gecikmesi.
2. **Odak ALMASI gerekenler -- `array_filter.py` (#14),
   `quick_panel.py` (#15):** planin tahmini TERSINE cikti. Bu iki
   pencere odagi kaybetmemeli DEGIL, odagi ALMALI: ikisinde de kutuya
   yaziliyor (`search.setFocus()`, `eventFilter`). Flet kendi basina
   alamiyor; odak Qt tarafindan verilecek -- `ask_qt`in yeni bir
   kullanimi.

**Ilk acilis kararsizligi ikisini de ilgilendiriyor:** panel ilk kez
acilirken `flet.exe` ayaga kalkiyor (1-3.5 sn) ve o anda odak GIDEBILIYOR.
Cozum panelleri ONCEDEN, gizli olarak ayaga kaldirmak (on isitma) --
sonraki adim.

## ADIM 15 -- ON ISITMA + ODAK KOPRUSU (bitti)

**Iki yardimci, panel tasima YOK.** Adim 14'un olcumu iki eksik
birakmisti; ikisi de dort pencerenin ORTAK ihtiyaci, o yuzden panelden
once yazildilar -- yoksa her panelde tekrar cozulurlerdi.

### 1) On isitma -- `FletEngine.warm()`

Panelin ilk acilisi `flet.exe`yi ayaga kaldiriyor: 1.0-3.5 saniye VE
olculen odak kararsizligi (F senaryosu -- bir olcumde yeni surec 2.12 sn
sonra odagi caldi). `warm()` bu bedeli PROGRAM BOSTAYKEN odetiyor:
thread baslar, `_build` kosar, pencere GORUNMEZ.

Motorda uc parca:

| Ne | Is |
|---|---|
| `warm()` | `start()`in ta kendisi, tek farki bayrak (`_warming`) |
| `show_on_build(job)` | `_build`in SON SATIRI. Isitmada gostermez. |
| `start()` | bayragi DUSURUR -- isitirken gelen gercek acilis kazanir |

On uc panelin hepsi `_build` sonunda artik `self._engine.call(self._show_now)`
degil `self._engine.show_on_build(self._show_now)` cagiriyor. Isitilmis
panel sonradan normal acildiginda `engine.page` zaten dolu, yani panelin
`show_*` metodu dogrudan `call()` yoluna giriyor -- kacan bir sey yok.

    -> HANGI PANEL ISITILACAK, HENUZ SECILMEDI. Her panelin kendi
       `flet.exe`si var: hepsini isitmak 12 surec demek. Yalniz odaga
       duyarli / sik acilan paneller isitilmali (ipucu, hizli panel) ve
       secim OLCULEREK yapilmali -- bellek ve acilis suresi. Su an
       `warm()`i kimse cagirmiyor.

### 2) Odak koprusu -- `win32/window.py` `force_focus()`

`probes/focus.py`deki `force_focus` kalici yere tasindi:
`AttachThreadInput` + `SetForegroundWindow` + `BringWindowToTop`, ve
sonucu `GetForegroundWindow` ile DOGRULUYOR (`SetForegroundWindow` izin
verilmeyince `True` donup pencereyi gorev cubugunda yanip soner
birakabiliyor -- tek olcut odagin nerede oldugu). Sondaj artik kendi
kopyasini degil bunu cagiriyor.

**Ayni dans zaten iki yerdeydi:** `win32/menu.py` `force_foreground`
menu ve `ui/snip.py` icin bunu yapiyordu. Flet penceresi UCUNCU
kullanici oldu, yani govde ortak yere alindi
(`window.force_foreground`); menudeki ad delege olarak KALDI cunku
`ui/snip.py` onu cagiriyor.

    -> Bu cagri QT'NIN ANA THREAD'inde kosuyor. Ilk atis tuttuysa hic
       beklemiyor; tutmazsa deneme basina `FOCUS_SETTLE` (0.25 sn)
       bekliyor, yani en kotu durumda tepsi ve tus kuyrugu o kadar
       duruyor. Ana thread'de cagiranlar `tries`/`settle`i kismali.

    -> `array_filter` ve `quick_panel` icin SART, ipucu ve rozet icin
       ZARARLI (onlar odak ALMAMALI ve Flet'in varsayilani zaten oyle).
       Yani panel basina "odak ister/istemez" bir bayrak gerekecek --
       o bayrak panelle birlikte, adim 16+'da.

### Testler

`tests/test_flet_engine.py`ye dort test (isitma pencereyi gostermiyor,
normal acilis gosteriyor, isitirken gelen `start()` isitmayi iptal
ediyor, isitilmis panel sonra normal aciliyor) ve yeni
`tests/test_window_focus.py` (5 test: dogrulama, bosuna beklememe,
kucultulmus pencereyi geri acma). Ikisi de ekran ya da `flet.exe`
ISTEMIYOR -- Win32 cagrilari yamaniyor; odagin gercekten degistigi
`probes/focus.py`nin isi.

## ADIM 16 -- IPUCU (yazildi, BAGLANMADI)

Dosya: `keypilot/fui/tip.py`. Qt karsiligi `keypilot/ui/tip.py` (173
satir). **ILK ASAMA 3 PANELI.**

### Engel tahmin edildiginden BASKA cikti

Plan bu pencereyi "odak" yuzunden Asama 3'e koymustu. Adim 14 odagi
olcup gecti (Flet zaten calmiyor). Panel yazilirken gercek engel ortaya
cikti ve o plana HIC girmemisti:

| Ne | Qt | Flet |
|---|---|---|
| odak calmama | `WA_ShowWithoutActivating` | **varsayilan** (adim 14) |
| cercevesiz | `FramelessWindowHint` | `frameless` + `title_bar_hidden` |
| gorev cubugunda yok | `Qt.ToolTip` | `skip_task_bar` |
| **icerige gore boy** | **`adjustSize()`** | **KARSILIGI YOK** |

Ipucu bir satirdan on satira kadar degisiyor (`show_menu` pano
gecmisinde dokuz satir). Sabit olcu verilseydi ya metin kirpilirdi ya
altta bos serit kalirdi.

**COZUM SAYDAMLIK.** Pencereye COMERT bir olcu veriliyor ve zemini
saydam birakiliyor (`window.bgcolor` + `page.bgcolor` TRANSPARENT);
gorunen kutu pencerenin kendisi degil, icindeki `Container`. Container
Flet'in kendi yerlesimiyle iceriginin boyuna oturuyor -- yani
"adjustSize" isini Flutter yapiyor, artan yer saydam kaliyor.
`window_size` yine de icerikle buyuyor: sabit buyuk bir pencere ekranin
kenarinda yerlestirme hesabini bozardi.

### HTML korundu -- cagiran kirk yer degismedi

`show_html` ipucunun ANA arayuzu: `app.py`, `clip_ctl.py` ve
`fui/mem_slots.py` toplam kirk yerde HTML govdesi uretiyor. Plandaki
panel tasima kurali geregi imza korundu ve HTML burada `ft.TextSpan`lara
CEVRILIYOR (`parse`). Kullanilan dagarcik ONCE TARANDI, kucuk cikti:
kalin, satir sonu, renkli span (tek renk: `#8b949e`), kacis dizileri.
`<i>` yalnizca ornek metinlerde. **Bilinmeyen etiket atiliyor, metni
kaliyor** -- ipucu bir metin kutusu, tanimadigi bir etiket yuzunden BOS
gorunmesi en kotu sonuc olurdu.

`show_menu` HTML'den GECMIYOR: Qt bir tablo uretiyordu, Flet'te tablo
yok ve gerek de yok -- satirlar dogrudan denetim (rozet bir
`Container`).

### Imlecin yaninda -- ILK KEZ konum hesabi

Oteki on iki panelin hepsinde "imlecin ekraninda acilmiyor" diye bir
kayip yazili (bkz. **Geri alinan / kaybedilen davranislar**). Ipucunda bu kabul edilemez:
ekranin ortasinda acilan bir ipucu ipucu degildir.

Cevrim gerekiyor cunku iki taraf ayri birimde konusuyor: bu paketteki
her sey FIZIKSEL pikselde (`GetCursorPos`, `virtual_rect`, `monitors`),
Flutter -- yani `window.left/top` -- MANTIKSAL pikselde. Iki yeni
yardimci `win32/screen.py`de: `dpi_scale_at(x, y)` ve `work_area_at`.

    -> OLCULDU: bu makinenin UC monitorunde de olcek 1.104 (106 DPI).
       Plandaki "%135" notu artik GECERLI DEGIL; cevrim yapilmasaydi
       pencere yuzlerce piksel sapardi.

Bu yardimci hazir olduguna gore oteki panellerin "imlecin ekraninda
acilmiyor" kaybi da artik ucuz: `place()` kalibi oradan alinabilir.

### ON ISITMANIN ILK MUSTERISI

Ipucu programin HER YERINDEN aciliyor ve suresi 900-2500 ms. Isitilmasa
ILK ipucu `flet.exe` ayaga kalkana kadar (1.0-3.5 sn) gorunmezdi -- yani
hic gorunmemis sayilirdi. `TipPanel.warm()` adim 15'in `FletEngine.warm`
yolunu cagiriyor; sondaj bunu yapiyor.

### Testler -- ve BIR DERS

`tests/test_fui_tip.py`, 29 test, Flet de ekran da gerekmiyor: `parse`
(dagarcik + bozuk HTML), `window_size` (icerikle buyume, tavan, resim) ve
`place` (cevrim, kenara cekme, negatif koordinatli ikinci monitor --
olcek testte BILEREK 1.25 yamaniyor ki cevrimin gercekten yapildigi
gorulsun).

**DENETIM AGACI TESTI (yeni kalip, bir hatadan dogdu).** Ilk surumde
`ft.border.all` ve `ft.padding.symmetric` yaziliydi; dogrusu
`ft.Border.all` ve `ft.Padding.symmetric`. Saf fonksiyonlarin 21 testi
GECIYORDU ama panel ekranda acilirken Flet
`module ... has no attribute` diye dusuyordu -- yani yanlis Flet API'si
ancak GERCEK PENCEREDE gorunuyordu.

Cozum ucuz: `_build` ve `_content` SAHTE bir sayfayla (`SahteSayfa`,
duz bir nesne) cagriliyor. Denetimler gercekten kuruluyor, Flet
calistirilmiyor, ekran gerekmiyor -- yanlis bir ad ya da imza artik
testte patliyor. **Yeni panel yazacak olana: bu kalibi kullan.** On uc
panelin hicbirinde bu test yok; ayni hata onlarda da olabilir (tarandi,
`ft.<kucuk harf>.<...>` bicimli baska cagri KALMADI, ama tarama yalnizca
bu hata bicimini yakalar).

### EKRANDAN OLCULDU (`probes/tip.py`) -- UC SESSIZ HATA

Panel yazildi, testleri geciyordu ve ekranda YANLIS calisiyordu. Adim
14'un dersi burada tersinden dogrulandi: **Flet ayarlarinin ISLEYIP
ISLEMEDIGI ancak gercek pencerede gorunuyor.**

Sondaj GOZE degil PIKSELE bakiyor: ekrani ipucu kapaliyken yakalar,
ipucunu gosterir, tekrar yakalar ve pencerenin dikdortgeninde DEGISEN
pikselleri sayar. Saydamsa yalnizca kutunun yeri degisir.

| Ne olculdu | Sonuc |
|---|---|
| **SAYDAMLIK** | **CALISIYOR** -- pencerenin yalnizca %30-39'u boyaniyor, gerisi bir onceki kareyle BAYT BAYT ayni |
| `always_on_top` | CALISIYOR (WS_EX_TOPMOST kondu) |
| `frameless` | CALISIYOR gorunuyor: WS_THICKFRAME kalkti, WS_CAPTION uslupta kaliyor ama CIZILMIYOR (ustteki serit boyanmiyor) |
| **`skip_task_bar`** | **ISLEMIYOR** -- ne WS_EX_TOOLWINDOW var ne sahip, yani gorev cubugunda dugme CIKIYOR |
| **`movable = False`** | **GIZLEMEYI BOZUYOR** -- ipucu bir daha kapanmiyor |
| **on isitma** | pencereyi ACIKCA gizlemiyordu: `flet.exe` kendi bos penceresini aciyor |
| olcu tahmini (`CHAR_PX`) | KIRPILMA YOK; tahmin ~%15 COMERT (saydamlik yuttugu icin gorunmuyor) |
| acilis suresi | isitilmis **0.15 sn**, isitilmamis **0.62 sn** (makine sicakken; soguk acilis 1-3.5 sn) |

**Uc hata da SESSIZDI:** program calisiyor, hata vermiyor, log'a bir sey
dusmuyor -- yalnizca pencere yanlis davraniyor. Ucu de duzeltildi:

1. **`movable = False` KALDIRILDI.** Kaybedilen bir sey yok: pencere
   cercevesiz, suruklenecek baslik cubugu zaten yok. Bayrak bayrak
   bolerek bulundu (sekiz ayri pencere acildi, teker teker denendi).
2. **Gorev cubugu isi WIN32'YE DUSTU** -- `win32/window.py`
   `set_tool_window()`. Qt surumu bunu `Qt.ToolTip` bayragiyla bedavaya
   yapiyordu. ZAMANLAMA onemli: Windows bu bayragi ancak pencere
   GIZLIYKEN gorev cubuguna yansitiyor, o yuzden her gosterimden ONCE
   deneniyor (ipucular arasinda pencere zaten gizli). `find_window`a
   `visible_only=False` eklendi -- isitilan pencere gizli oldugu icin
   eski hali onu bulamiyordu.
3. **ON ISITMA PENCEREYI GIZLIYOR** (`fui/engine.py` `_hide_for_warm`).
   Adim 15'te "gostermemek icin hicbir sey yapma" yetiyor sanilmisti;
   yetmiyor -- `ft.run()` calisir calismaz ekranda varsayilan olculu bos
   bir pencere var. Ustelik `_build`de yazilanlar (baslik, cercevesizlik)
   bir `update()` gelmeden istemciye HIC gitmiyordu, yani isitilan
   pencerenin basligi bile yoktu ve tutamagi bulunamiyordu. Gizleme
   MOTORA kondu: isitilan her panelin ayni ihtiyaci var.

Ikisinin de REGRESYON TESTI var (`test_movable_AYARLANMIYOR`,
`test_gorev_cubugundan_gizleme_BIR_KEZ`): sessiz hatalar sessizce geri
gelmesin.

### BAGLANMADI -- neden ve sirasi

`app.py`de `Tip()` -> `TipPanel()` tek satir, ama bu panel oteki on
ikiden farkli: KIRK cagirani var ve biri HATA BILDIRIMI. Yanlis
calisirsa program sessizlesmez, HATALAR GORUNMEZ olur.

Olcum yapildi ve pencerenin davranisi artik biliniyor; kalan tek sey
GOZLE bakilmasi gereken sey: **metnin okunakliligi.** Sondaj pikselin
degistigini gorur, YAZININ dogru dizildigini goremez -- kalin/soluk
ayrimi, emoji, rozet hizasi ve satir araligi goz isi.

Bakilacaklar **Nasil denenir** > ipucu dugmelerinde.

---

## ADIM 10 -- YARIM KALDI (hafiza slotlari penceresi)

Dosya: `keypilot/ui/mem_slots.py` (454 satir). **Panel yazildi
(`keypilot/fui/mem_slots.py`) ama BAGLANMADI**: `app.py` hala Qt
surumunu kuruyor, program bu adimdan once neyse o. Sebep tek bir
davranis: **satiri baska bir uygulamaya surukleyip birakma.**

### Planin tahmini yanlis cikti

Bu adimin gerekcesi "diske yazan `SlotStore`u slot kutusu ve QR ile
PAYLASIYOR, `ask_qt` en siki burada uygulanacak" idi. Dosyaya bakinca
oyle olmadigi gorundu: bu pencerenin bloklari BELLEKTE yasiyor,
`slots.json` ile ILGISI YOK (`ui/mem_slots.py` dosya basi bunu zaten
yaziyor -- "isim benzerligi yuzunden karistiriliyordu"). Paylasilan
durum da yok, disk de. **Adim 5'in dersi bir kez daha dogrulandi:** bir
sonraki adimin tahmini, dosyaya bakilmadan uygulanmamali.

Gercek engel bambaska bir yerdeydi.

### Engel: OS'e surukleyip birakma

Qt surumunde `DragTable` var (AHK `OleDragSource`): tabloda kisaltilmis
onizleme yazar, satiri Notepad'e surukleyince blogun TAM icerigi duser.
Kullanici bunu pencerenin ana islevlerinden sayiyor.

* `ft.Draggable` / `ft.DragTarget` yalnizca UYGULAMANIN ICINDE tasiyor;
  isletim sistemine birakma diye bir sey yok.
* Onceki `flet` bransina bakildi: **orada da cozulmemis.** mem_slots o
  bransta Flet'e hic tasinmamis, PySide penceresi olarak kalmis --
  kalan `cascade/ui/__pycache__/mem_slots.cpython-313.pyc` icinde hala
  `DragTable`, `QDrag`, `startDrag` geciyor.

### Win32 yolu DENENDI ve OLCULDU -- calismiyor

Windows'ta surukleme `ole32.dll` `DoDragDrop` ile yapiliyor ve projede
zaten kurulu olan `pywin32` bunu aciyor. Borunun tamami ucuz cikti:
`pythoncom.DoDragDrop` var, `IDropSource` icin gecit var
(`win32com.server.util.wrap`), ve `IDataObject` yazmaya bile gerek yok
-- `pythoncom.OleGetClipboard()` panodaki icerigi hazir bir
`IDataObject` olarak veriyor (bu pencere zaten pano yoneticisi, panoya
yazmak normal).

Tek kullanimlik betikle olculdu (projede TUTULMADI): `DoDragDrop`
cagrildi, modal donguye girdi ve **`QueryContinueDrag`i HIC cagirmadi**;
sentetik Esc de kirmadi, 40 saniyede timeout ile oldurulmesi gerekti.

Sebep belgelerde yaziyor: `DoDragDrop`un dongusu fare mesajlarini
CAGIRAN THREAD'IN kuyrugundan okuyor ve bunun icin fareyi yakalamasi
gerekiyor; `SetCapture` ise BASKA BIR SURECE giden fare girdisini
yakalayamiyor. Flet her paneli ayri bir surecte aciyor (`flet.exe`),
yani tusa basilan pencere onun, sürüklemeyi baslatacak kod bizim
surecimizde. Notepad'de calismasinin sebebi de bu: orada ikisi ayni
surec.

**Ayni duvar `QDrag` icin de gecerli** -- Qt de iceride ayni
`DoDragDrop`u cagiriyor. Yani "Qt koprusu" ile "DLL yolu" ayni sey;
Qt'nin silinmesi bu konuda bir sey kaybettirmiyor.

**Basarisizlik sekli "calismaz" degil, KILITLENIR.** Gercek programda o
cagri Qt ana thread'inde kosardi: tepsi, ipucu ve zamanlayicilar kalici
olarak donardi. Bu yuzden panele HIC konmadi.

### Yapilabilecekler (sirasiyla ucu de bir KARAR)

1. **Surukleme kaybedilir, panel baglanir.** `fui/mem_slots.py` hazir ve
   bekliyor; `app.py`de degisecek uc satir: import, `MemSlotsPanel()`
   kurulumu, `isVisible()` -> `visible` (bir de kapanista `shutdown()`
   listesi). Yerine cift tiklama duruyor: blok -> panoya kopyalar,
   gecmis -> dogrudan yapistirir.
2. **`AttachThreadInput` ile flet.exe'nin girdi kuyruguna baglanmak.**
   `SetCapture` sinirini kaldirmasi beklenir. DENENMEDI: bagli
   thread'lerden biri takilirsa kullanicinin fare/klavye girdisi donuyor
   -- bir "guzel olurdu" ozelligi icin fazla riskli bulundu.
3. **Flet'in istemcisini degistirmek.** Isi gercekten Flutter tarafinda
   `super_drag_and_drop` cozer; bu, `flet-desktop`in yerine ozel
   derlenmis bir Flutter istemcisi demek. Bu projenin olcusunu asiyor.

Karar 1'e donerse `fui/mem_slots.py` baglanir; donmezse **o dosya
SILINECEK** (bkz. **Tam geciste SILINECEK / DUZELTILECEK**). Su an tuttugu tek
sey: yazilmis, okunmus, ama kimsenin import etmedigi bir panel.

### Yazilan panelde ne var (karar 1 secilirse hazir)

* Iki liste (10 blok + en cok 10 gecmis kaydi), satir basina TEK yazi --
  sabit genislikli yazi tipinde "F01" sutunu dolguyla ayni satirda
  (`row_text`).
* **Cift tiklama Flet'te BULUNDU:** `ft.GestureDetector` `on_double_tap`.
  Log ve olay izleyicide "Flet'te cift tiklama yok" diye yazilmisti --
  dogrusu `Container`da yok, `GestureDetector`da var. Bedeli tek
  tiklamanin ~300 ms gec islenmesi (Flutter iki olayi ancak boyle
  ayiriyor). O iki panelde de istenirse ayni yolla geri gelir.
* `visible` bayragi (`app.py` `memslots_paste_enter` Qt'de `isVisible()`
  soruyordu), `always_on_top`, baslik seridine tiklayinca listeyi ters
  cevirme, F1..F10 kutusunun kapanista birakilmasi.
* Kutular (`F1-F10`, `veri tekrari`, `orta tus`) Flet'te ama degerleri
  duz `bool` alanlarda: `on_clip` ve `smart_paste` bunlari ANA
  THREAD'den okuyor (`fui/monitor.py` kalibi).
