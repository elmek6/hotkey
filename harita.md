# cascade — AHK'den Python'a geçiş haritası

Kaynak: `C:\Users\0\Documents\AutoHotKey` — `AutoHotkey.ahk` + `Lib/` 30 modül,
**14.004 satır**. Ayrıca `test/` altında 4.400 satır deneme kodu (taşınmayacak).

Hedef: aynı davranış, CPython 3.13 + ctypes/Win32 + PySide6.

Bu dosya `sonuc.md` ve `python-gecis-yol-haritasi.md`'nin yerine geçer.
Onlardaki stack seçimi ve modül eşlemesi doğruydu; değişen şey **sıra** ve
**kaskadın nasıl yazılacağı**.

---

## Durum

| | |
|---|---|
| ✅ Faz -1 | risk sondajı — hook, SendInput, kombo, yutma, gecikme ölçüldü |
| 🔶 Faz 0 | gönderim katmanı: scancode + Unicode + fare var; Türkçe Q/F ve AltGr eksik |
| ✅ Faz 1 | kaskad durum makinesi — `core/cascade.py`, 18 birim testi |
| 🔶 Faz 2 | dispatcher: önek kombosu (`F13 & F14`, `^ & 1`) + modifier kombosu + yutma/geri gönderme var; `HotIf` bağlamı, süreç eşleşmesi ve JSON'dan okuma eksik |
| ✅ Faz 3 | iskelet: tek örnek kilidi, loglama, tepsi menüsü, reload/exit |

Çalışan program: `main.py` → tepsiye oturur, `Files/hotkeys.json` okur,
tepsi menüsünde **Durum / Kısayolları yeniden yükle / Yeniden başlat / Çıkış**.

Ölçülen değerler (bu makinede, 2026-08-28):

```
en uzun hook callback : 0.086 ms     Windows sınırı 300 ms  → ~3500x pay
sol/sağ modifier      : ayrı geliyor (VK 0xA0..0xA5)
tuş yutma             : çalışıyor (CapsLock artık toggle etmiyor)
fare düğmesi yutma    : çalışıyor (XButton2)
kendi SendInput'umuz  : dwExtraInfo=0x0CA5CADE ile geri beslemede tanınıyor
birim testi           : 61 test, hepsi geçiyor
```

---

## 1. Gerçek iş hacmi 14.000 satır değil

| Modül | Satır | Python'da karşılığı | Sonuç |
|---|---:|---|---|
| `OCR.ahk` | 1.819 | `winsdk` → `Windows.Media.Ocr` | **at**, ~60 satır |
| `screen_ocr.ahk` | 1.353 | aynı + `mss` | büyük kısmı at |
| `gdip_mini.ahk` | 444 | Pillow | **at**, 0 satır |
| `jsongo.v2.ahk` | 410 | `orjson` | **at**, 0 satır |
| `array_filter.ahk` | 387 | `QSortFilterProxyModel` + liste kavraması | büyük kısmı at |

Bunlar AHK'de kütüphane yokluğundan yazılmış ~4.400 satır. Gerçek port yüzeyi
**~8.000 satır**, yarısı GUI. Kalan ağır gerçek mantık üç modülde:
`incognito` (1.074), `clip_image_store` (879), `trace_store` (761).

Hotkey yüzeyi: ana scriptte 63 statik tanım, 31 dinamik `Hotkey()`, 30 `HotIf`
bağlamı. Bunlar tek tek koda değil, **veri tablosuna** dönüşecek.

---

## 2. Kaskad port edilmez, yeniden yazılır

Planın tek gerçek mimari kırılması burası.

AHK'de `singleHotCascade.handle()` şöyle çalışıyor:

```ahk
while (GetKeyState(key, "P")) {
    duration := A_TickCount - startTime
    ...
}
```

AHK hotkey thread'i **bloke olabilir**. Python'da LL hook callback'i bloke
olamaz — 300 ms'yi aşarsan Windows hook'u *sessizce* düşürür; program çalışıyor
görünür ama hiçbir tuş gelmez. Yani kaskad birebir çevrilemez:

- `cascade/core/` içinde **saf durum makinesi**. Zaman dışarıdan verilir.
  Win32 import'u yok, `sleep` yok, `GetKeyState` yok.
- Zamanlayıcı dışarıda: tüketici thread'de bir sonraki eşiğe kadar bekle,
  zaman aşımını durum makinesine besle. (Python 3.11'den beri Windows'ta
  `sleep`/`wait` yüksek çözünürlüklü zamanlayıcı kullanıyor, ~1 ms;
  `timeBeginPeriod` gerekmiyor.)
- Test edilebilir: *"220 ms basılı tutulunca orta basım tetiklenir"* artık bir
  pytest satırı. **AHK'de hiç yapılamayan şey buydu.**

### Yutma kararı ile eylemin ayrılması

Hook, keydown anında **hemen** yut/bırak cevabı vermek zorunda; ama basımın
kısa mı orta mı uzun mu olduğu o an belli değil. Çözüm, AHK'nin `KeyWait`
semantiğinin çevirisi:

1. Kaskad tablosundaki bir tuşsa → keydown **her zaman yutulur**.
2. Durum makinesi kararı verince, kısa basım çıktıysa orijinal tuş
   `SendInput` ile **yeniden enjekte edilir** (kendi imzamızla; hook onu atlar).
3. Orta/uzun çıktıysa eylem çalışır, enjeksiyon yok.

Portlarda "tuşum yendi" hissi tam burada doğar. Kabul kriteri: kaskad tuşuna
normal hızda basınca hiçbir fark hissedilmemeli (yeniden enjeksiyon < 5 ms).

---

## 3. Fazlar

Sıra, **"bunu her gün kullanabiliyorum"** noktasına en hızlı varacak şekilde
kuruldu. Önceki taslakta Faz 1 ayar dialoguydu — aylarca Qt yazıp programı hiç
kullanmamış olursun. Ayar dialogu en sona alındı; JSON dosyası aylarca yeter.

| # | İçerik | AHK karşılığı | Teslimat kriteri |
|---|---|---|---|
| **-1** ✅ | sondaj: hook + SendInput + kombo + gecikme | — | `probes/` çalışıyor |
| **0** 🔶 | gönderim katmanı: scancode, Unicode, AltGr, Türkçe Q/F | `key_builder`, `turkish_layout_addon` | AHK'nin `Send`/`SendText` davranışı birebir |
| **1** ✅ | kaskad durum makinesi | `key_handler_cascade`, `key_handler_hook` | `core/cascade.py` + 18 test, Win32'siz |
| **2** 🔶 | dispatcher: önek kombosu ✅, modifier kombosu ✅, JSON tablosu, `HotIf` bağlamı, süreç eşleşmesi | `key_handler_mouse`, `hot_vectors` | 63 statik hotkey tablodan okunuyor |
| **3** ✅ | iskelet: mutex, logging, tray, reload/exit | `AutoHotkey.ahk`, `script_state`, `error_handler` | `pythonw main.py` arka planda oturuyor |
| **4** | **ilk gerçek devir**: en sık kullandığın 5 kısayol | — | bir hafta günlük kullanım, geri dönüş yok |
| 5 | pano geçmişi (metin) + slotlar + kalıcılık | `clip_hist`, `clip_slot`, `memory_slots` | |
| 6 | GUI: geçmiş listesi, menüler, filtre | `menus`, `array_filter` | |
| 7 | görsel pano + sürükleme | `clip_image_*`, `gdip_mini`, `ole_drag_source` | |
| 8 | makro kaydedici/oynatıcı | `macro_recorder` | |
| 9 | ekran yakalama + OCR (`winsdk`) | `screen_ocr`, `OCR.ahk`, `magnifier` | |
| 10 | profiller, repository, incognito, trace | `app_shorts`, `repository`, `incognito`, `trace_store` | |
| 11 | ayar dialogu (pydantic → Qt), autostart, paketleme | `settings`, `settings_dialog` | |

**Faz 4 haritanın kalbi.** Oraya varmadan yazılan her satır spekülatif.

---

## 4. Paralel çalışma kuralı

AHK ve Python aynı anda açık olacak — ikisi de LL hook kuruyor, ikisi de her
tuşu görüyor. Zincirdeki sıra kurulum sırasına bağlı ve garanti edilemez.

**Kural: bir tuşun tek sahibi olur.** Python bir tuşu aldığında aynı gün AHK
tarafında o hotkey yorum satırına alınır. `Files/devir.md` diye tek liste
tutulur: `tuş | eski modül | yeni modül | devir tarihi`.

`Pause & Home` (reload) ve `Pause & End` (exit) en sona kadar AHK'de kalır —
Python tarafı çökerse geri dönüş yolun onlar.

AHK dosyalarına başka hiçbir şekilde dokunulmaz.

---

## 5. Bilinen tuzaklar

- **Debugger'ı hook callback'inin içinde durdurma.** `hook.py` → `_on_key` /
  `_on_mouse` içine breakpoint koyarsan tüm sistemin girdisi donar, 300 ms
  sonra Windows hook'u düşürür. Sondajları **Ctrl+F5** ile çalıştır.
  Breakpoint `core/` içine konur, orası hook thread'inde değil.
- **Yükseltilmiş pencereler.** Mevcut AHK scripti `#RequireAdmin`
  kullanmıyor, Python de kullanmayacak. Yönetici olarak açılmış pencerelerde
  (Görev Yöneticisi, regedit) ne hook görür ne SendInput geçer — davranış
  değişikliği değil, mevcut durumun aynısı.
- **`CFUNCTYPE` nesnesi ve DLL handle'ları** modül/örnek seviyesinde tutulmalı;
  yerel değişkende kalırsa GC toplar ve hook çağrısında proses çöker.
  `win32/structs.py` ve `HookThread` bunu zaten yapıyor.
- **Zaman granülaritesi.** AHK `A_TickCount` 15.6 ms adımlı, Python
  `perf_counter` ~100 ns. Kaskad eşikleri Python'da daha keskin hissedilecek;
  short/medium/long süreleri yeniden ayarlanmalı.
- **Hook callback'inden asla `SendInput` çağırma** — yeniden giriş ve
  kilitlenme. Gönderim yalnızca tüketici thread'de.
- **Önek tuşu yutulmak zorunda.** AHK önek tuşunu (`F13 & F14`'teki F13)
  hiç yutmaz, `~` ile de açıkça geçirilir. LL hook keydown anında cevap
  vermek zorunda olduğu için Python'da önek keydown'ı yutulur; tuş tek
  başına bırakılırsa orijinali `SendInput` ile geri gönderilir. `^` tuşunda
  bu görünür fark yaratmaz (ölü tuş zaten sonraki tuşu bekler), ama yazı
  tuşlarını önek yaparken akılda tutulmalı.
- **`^` tuşunun VK'si düzene bağlı.** Türkçe Q'da 0xDC, US'de Shift+6.
  Sabit yazma; `send.vk_for_char("^")` ile düzene sor.
- **Pano**: `AddClipboardFormatListener` + `WM_CLIPBOARDUPDATE`, polling yok.
- **Paketleme aylarca gerekmez.** `pythonw.exe main.py` kısayolu
  `shell:startup` içine → AHK ile aynı deneyim. Nuitka Faz 11'de.

---

## 6. Dizin yapısı

Flutter karşılıklarıyla:

```
pyproject.toml     ← pubspec.yaml        bağımlılıklar + araç ayarları
uv.lock            ← pubspec.lock        kilitlenmiş sürümler (git'e girer)
.venv/             ← .dart_tool/ + build/  indirilen paketler (git'e girmez)

cascade/           ← lib/                asıl kaynak
  core/            saf Python. Win32 import'u YASAK. Test edilebilir her şey burada.
  win32/           ctypes sarmalayıcıları. İşletim sistemine dokunan tek yer.
  ui/              PySide6 (Faz 6)
probes/            elle çalıştırılan donanım sondajları
tests/             ← test/               pytest
```

Çift tıklanabilir başlatıcılar: `baslat.cmd` (konsollu, hata görmek için),
`baslat.vbs` (sessiz — kısayolunu `shell:startup` içine koyunca Windows ile
birlikte açılır).

| Dosya | İş |
|---|---|
| `cascade/win32/consts.py` | Windows sabitleri, sadece sayı |
| `cascade/win32/structs.py` | `KBDLLHOOKSTRUCT`, `INPUT` + `user32` imzaları |
| `cascade/win32/hook.py` | LL hook, ayrı thread + kendi `GetMessage` döngüsü |
| `cascade/win32/send.py` | `SendInput` — scancode, Unicode, fare |
| `cascade/core/keynames.py` | VK ↔ isim (`0xA0` → `LShift`), AHK adlandırmasına yakın |
| `cascade/core/combo.py` | fiziksel tuş durumu, kombo metni, basım süresi |
| `cascade/core/builder.py` | `key_builder.ahk` portu: kaskad tanımı, `press_type` |
| `cascade/core/cascade.py` | kaskad durum makinesi (IDLE → HELD → MENU) |
| `cascade/core/hotkey.py` | AHK sözdizimi: önek kombosu (`F13 & F14`) + modifier kombosu (`^!k`) + kısayol tablosu |
| `cascade/core/mouse.py` | fare mesajı → tuş kodu (henüz bağlı değil, `F13 & WheelUp` için hazır) |
| `cascade/core/state.py` | `script_state.ahk` portu: Busy, ScriptInfo, MouseState |
| `cascade/actions.py` | eylem kimliği → gerçek iş (`send_text:`, `app.exit` …) |
| `cascade/ui/tray.py` | tepsi simgesi + menü, Duraklat/Devam (AHK `Suspend`) |
| `cascade/ui/tip.py` | AHK `ToolTip` karşılığı — zengin metin, emoji, renk, rozetli menü |
| `cascade/win32/instance.py` | `#SingleInstance Force` → adlandırılmış mutex, restart'ta bekleyerek devralır |
| `main.py` | her şeyi bağlayan giriş noktası |

---

## 7. Çalıştırma ve test

```
uv run python main.py            # ana program (tepsiye oturur)
uv run python -m probes.gui      # canlı izleyici (pencere)
uv run python -m probes.keys     # klavye kombo sondajı (konsol)
uv run python -m probes.mouse    # fare sondajı (konsol)
uv run python -m probes.raw      # ham olay dökümü (konsol)
uv run pytest -q                 # birim testleri
uv run ruff check .              # lint
```

VSCode'da **F5** → dört sondaj yapılandırması listelenir. Testler için sol
kenardaki erlen şişesi (Testing) sekmesi.

Test iki katmanlı:

1. **`pytest`, insansız.** Kombo mantığı, basım süresi, tuş isimleri —
   `core/` içinde saf Python, zaman dışarıdan verilir. Faz ilerledikçe
   kaskad, pano geçmişi, profil eşleşmesi de buraya girer.
2. **`probes/`, elle.** Gerçek klavye/fare gerektiren, otomatikleştirilemeyen
   kısım. `probes/gui.py` aynı zamanda Qt-loop + hook-thread mimarisinin
   provası: hook callback'i hiçbir Qt nesnesine dokunmaz, kuyruğa yazar,
   ana thread `QTimer` ile boşaltır.

---

## 8. Ortam

```
uv 0.12.7 · CPython 3.13.15 x64 · PySide6 6.11.2 · pywin32 312
comtypes · pillow · mss · psutil · orjson · pydantic · watchdog
dev: pytest · ruff · pyright
```

Faz geldikçe eklenecek: `winsdk` (Windows.Media.Ocr),
`rapidocr-onnxruntime` (çevrimdışı yedek), `opencv-python-headless`
(ImageSearch), `pywinauto`/`uiautomation`, `dxcam`.

3.14 değil 3.13: makinede 3.14.3 kurulu ama PySide6/pywin32 tekerlekleri orada
henüz yeni. Store sürümü de kullanılmıyor — COM/hook/registry sandbox'a takılır.

`keyboard`, `pynput`, `pyautogui` **kullanılmayacak**: kaskad, scancode ve
sol/sağ modifier ayrımı hiçbirinde tam yok. Hook ve SendInput doğrudan ctypes.

VSCode eklentileri: `ms-python.python` (debugpy + Pylance ile gelir),
`charliermarsh.ruff`.
