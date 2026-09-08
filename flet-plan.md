# PySide6 -> Flet gecis plani

**Yontem: panel panel, kolaydan zora. Program her adimdan sonra CALISIR
durumda.** Qt motor olarak kaliyor; tasinan panel `keypilot/fui/` altina
gidiyor, Qt karsiligi silinmiyor -- geri donmek `app.py`'de bir satir.

Onceki deneme (`flet` brans'i, `cascade` paketi) tam yeniden yazimdi:
164 dosya, 18 pencere tek bir Flet penceresine sikistirildi ve odak,
saydamlik, es zamanli pencere kaybedildi. O yol BIRAKILDI.

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

**Olculen degerler:** ilk acilis ~3.5 sn (`flet.exe` ayaga kalkiyor),
sonraki acilislar 0.0 sn (pencere kapanmiyor, gizleniyor). Panel acan
cagri ana thread'i bloklamiyor (0.001 sn'de donuyor).

---

## Asama 1 -- kolay: standart pencere, az cikti

| # | Panel | Satir | Durum | Not |
|---|---|---|---|---|
| 1 | `key_map_view.py` | 176 | **BITTI** | Salt okunur tablo. Tek cikti: `closed`. |
| 2 | `pause.py` | 99 | **BITTI** | 4 dugme, 4 sinyal. `WindowStaysOnTopHint` -> `always_on_top`. |
| 3 | `slot_edit.py` | 92 | sirada | Form: ad + eski deger + yeni deger. Sifre slotunda maskeleme. |
| 4 | `qr_view.py` | 341 | bekliyor | Uretilen QR'i gosteriyor. Goruntu Flet'e `base64` ile verilebilir. |
| 5 | `log_view.py` | 421 | bekliyor | Salt okunur liste + detay. Buyuk ama duz. |
| 6 | `monitor.py` | 183 | bekliyor | Canli akan olay listesi. IIk kez "surekli guncelleme" testi. |

## Asama 2 -- orta: durum yazan formlar

| # | Panel | Satir | Not |
|---|---|---|---|
| 7 | `macro_view.py` | 213 | Kayit ekrani. |
| 8 | `ocr_view.py` | 229 | `WindowStaysOnTopHint`. Sonuc paneli. |
| 9 | `repository_view.py` | 404 | Kod parcasi deposu. |
| 10 | `mem_slots.py` | 454 | `WindowStaysOnTopHint`. |
| 11 | `profiles_view.py` | 468 | Profil yoneticisi. |
| 12 | `clip_images.py` | 486 | `QPainter` -- kucuk resim cizimi. Flet'te `ft.Image` ile. |
| 13 | `settings_dialog.py` | 605 | En buyuk form. Tema secimi burada; `fui/theme.py`nin sabit koyu paleti burada ele alinacak. |

## Asama 3 -- zor: Flet'te KARSILIGI OLMAYAN pencere davranislari

Bunlar "biraz ugrasinca olur" degil; her biri icin bir KARAR gerekiyor.

| # | Panel | Satir | Engel | Secenek |
|---|---|---|---|---|
| 14 | `array_filter.py` | 313 | Odak calmamali (pano gecmisi acilirken hedef uygulama odagi kaybetmemeli) | Flet penceresi acilinca odak alir. Ya davranis kabul edilir ya panel Qt'de kalir. |
| 15 | `quick_panel.py` | 562 | Ayni odak sorunu (CapsLock paneli) | Ayni. |
| 16 | `key_capture.py` | 112 | Ham tus yakalama: `ui_open` ile hook susturulup tuslar Qt olayi olarak okunuyor | Flet klavye olayi sayfa duzeyinde ve Windows tus kodlarini vermiyor. Hook'tan beslemek gerekir. |
| 17 | `incognito_badge.py` | 188 | `QPainter` ile cizilen, hep ustte duran rozet | Flet penceresi cerceveli; cerceve gizlense de odak/saydamlik sorunu surer. |
| 18 | `tip.py` | 173 | `FramelessWindowHint` + `WA_ShowWithoutActivating` | **Flet'te karsiligi YOK.** Ipucu odak calarsa yazdiginiz yerden odak gider. Muhtemelen Qt'de KALIR ya da Win32 katmanina iner. |
| 19 | `menu.py` | 88 | Win32 `TrackPopupMenu` (zaten Qt degil) | Flet'e tasimak anlamsiz; oldugu gibi kalabilir. |
| 20 | `tray.py` | 419 | `QSystemTrayIcon` -- Flet'te tepsi YOK | Onceki brans `pystray` eklemisti. Ayri bir karar. |
| 21 | `snip.py` | 1347 | Tam ekran saydam bindirme + `QPainter` cizimi + basili tus takibi | **Flet'te karsiligi YOK.** Win32 katmanina inmeli (onceki brans `win32/overlay.py` yazmisti). En son, belki hic. |

**Sonuc:** Asama 3 asilmadan PySide6 bagimliligi KALKMAZ. Asama 1 ve 2
tamamlandiginda 13 panel Flet'te, 8 pencere Qt'de olur ve program iki
motorla calismaya devam eder. Bu sorun degil, ARA DURAK.

---

## Tasinan panelleri DENEME

Gercek programi calistirmadan:

    uv run python -m probes.flet            iki panel birden
    uv run python -m probes.flet pause      yalniz duraklatma
    uv run python -m probes.flet keymap     yalniz kisayol haritasi

Sondaj yalnizca bir `QApplication` kuruyor: hook YOK, tepsi YOK, tuslara
dokunulmuyor, calisan KeyPilot devralinmiyor. Pencerede iki sey izlenir:

* **Alt satirdaki sayac.** Durursa Qt ana dongusu Flet yuzunden
  bloklanmis demektir -- gecisin en temel varsayimi cokmus olur.
* **Dokumdeki "alici thread".** `MainThread` yazmali: panel sinyali kendi
  thread'inden gonderiyor, Qt kuyruga alip ana thread'de teslim etmeli.

Sondaj penceresi kapatilinca `shutdown()` cagriliyor -- gercek programda
bunu `app.py` `on_exit` yapiyor. Yapilmazsa `flet.exe` gorev cubugunda
sahipsiz kaliyor.

---

## Tam geciste SILINECEK / DUZELTILECEK

Gecis boyunca bilerek eklenen gecici seyler. Her biri "tam gecis"te
temizlenmeli; sirasi onemsiz ama listenin tamami bitmeden gecis bitmis
sayilmaz.

### Silinecek dosyalar

- [ ] `keypilot/ui/` paketinin tamami -- her panel tasindikca ilgili dosya.
      Son iki yardimci (`place.py` pencere ortalama, `preview.py` metin
      kisaltma) Flet'te karsiliklari yazilinca gidecek.
- [ ] `keypilot/theme.py` -- QPalette/stylesheet uzerine kurulu, Flet'e
      verecek bir seyi yok. Yerine `keypilot/fui/theme.py`.
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
- [ ] **Ters bagimlilik:** `fui/key_map.py` -> `ui/key_map_view.py`
      (`owner_label`). Qt dosyasi silinirken `owner_label` + `OWNER_LABELS`
      `fui/key_map.py`ye tasinacak.
- [ ] **`main.py`** `QApplication` kurulumu, `app.setQuitOnLastWindowClosed`,
      `logs.install_qt_handler()` -- hepsi `ft.run()` ile degisecek.
- [ ] **Panel basina `shutdown()` cagrilari** (`app.py` `on_exit`). Su an
      her Flet paneli kendi `flet.exe`sini kapatmak zorunda; tek kabuga
      gecilirse tek cagri kalir.
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
- [ ] **`fui/theme.py` sabit koyu palet.** Qt surumu sistem temasini
      izliyordu (`theme.py`: Windows 10'da `AppsUseLightTheme`). Ayar
      ekrani tasinirken (Asama 2, #13) tema izleme geri gelmeli.
- [ ] **`pyproject.toml`den `pyside6`** -- yalnizca Asama 3 bittikten
      sonra. `flet-desktop` ACIKCA eklendi cunku Flet onu ilk
      calistirmada kendi kendine pip'liyor; kilitli projede istenmez.
- [ ] **Testler.** `tests/` icinde Qt pencerelerini kuran testler var;
      panel tasindikca Flet karsiliklari yazilmali. Su an tasinan iki
      panelin BIRIM TESTI YOK -- dogrulama elle yapildi.

### Geri alinan / kaybedilen davranislar

- [ ] **Kisayol haritasinda sutun basligi tiklamasi** (Qt:
      `setSortingEnabled`). Flet surumunde siralama sabit: catisanlar
      ustte. Istenirse `DataColumn.on_sort` ile geri gelir.
- [ ] **Ilk acilis ~3.5 sn.** Her panelin kendi `flet.exe`si var, yani bu
      bedel PANEL BASINA bir kez odeniyor. Tek kabuga gecilirse bir kez.
