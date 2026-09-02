# cascade — AHK'den Python'a geçiş

Kaynak: AHK projesinin kopyası `_AutoHotKey/` içinde — `AutoHotkey.ahk` +
`Lib/` 30 modül, **~14.000 satır**.

Hedef: aynı davranış, CPython 3.13 + ctypes/Win32 + PySide6.

Her kod degisikliginden sonra kücük bir degisiklik ise minor versiyon yükseltmesi
Her kod sonrasi reload veya restart yapilmali

Flutter karşılıklarıyla:
```
pyproject.toml     ← pubspec.yaml        bağımlılıklar + araç ayarları
uv.lock            ← pubspec.lock        kilitlenmiş sürümler (git'e girer)
.venv/             ← .dart_tool/ + build/  indirilen paketler (git'e girmez)

cascade/           ← lib/                asıl kaynak
  keymap.py        SCRIPT katmanı: tuş tabloları, menüler ← AutoHotkey.ahk
  dispatch.py      tuşların çalışma mantığı: yutma/önek/jest ← key_handler_*.ahk
  app.py           kurulum + yaşam döngüsü + pano/slot/büyüteç bağlantıları
  core/            saf Python. Win32 import'u YASAK. Test edilebilir her şey burada.
  win32/           ctypes sarmalayıcıları. İşletim sistemine dokunan tek yer.
  ui/              PySide6 pencereleri
probes/            elle çalıştırılan donanım sondajları
tests/             ← test/               pytest
```

Kural: donanımla (hook, SendInput, pano, registry) konuşan TEK yer
`win32/`; olay akışının tek kapısı `dispatch.py`. Diğer modüller tuşa
doğrudan dokunmaz, `keymap.py` tablolarıyla kayıt olur.

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
| `cascade/core/state.py` | `script_state.ahk` portu: ClipboardState (Busy port edilmedi, gerekçe dosya başında) |
| `cascade/core/prefix.py` | önek tuşu durum makinesi (`A & B::` yazımının arkası) |
| `cascade/core/gesture.py` | eksen kilitli jest sayacı (`hot_vectors.ahk`in gereken kadarı) |
| `cascade/core/clip_history.py` | pano geçmişi listesi (`clip_hist.ahk` bellek tarafı) |
| `cascade/store.py` | disk: `clipboards.bin` + `slots.json` — AHK ile aynı biçim |
| `cascade/actions.py` | eylem kimliği → gerçek iş (`send_text:`, `app.exit` …) |
| `cascade/keymap.py` | tuş tabloları + menü içerikleri (script/soft code) |
| `cascade/dispatch.py` | yut/bırak kararları, olay akışının tek kapısı |
| `cascade/app.py` | kurulum, pano/slot/büyüteç bağlantıları, reload/exit |
| `cascade/ui/tray.py` | tepsi simgesi + menü, Duraklat/Devam (AHK `Suspend`) |
| `cascade/ui/tip.py` | AHK `ToolTip` karşılığı — zengin metin, emoji, renk, rozetli menü |
| `cascade/ui/array_filter.py` | filtreli liste penceresi (`array_filter.ahk`) |
| `cascade/ui/mem_slots.py` | hafıza slotları penceresi (`memory_slots.ahk`) |
| `cascade/ui/menu.py` | imleç yanında açılır menü (`menus.ahk`in Qt hali) |
| `cascade/ui/clipboard.py` | pano dinleyicisi (gecikmeli + tazelik kontrollü) |
| `cascade/win32/magnifier.py` | Windows büyüteci (`magnifier.ahk`) |
| `cascade/ui/snip.py` | F14 ekran alanı seçimi: tutamaçlı çerçeve + işlem çubuğu |
| `cascade/win32/ocr.py` | Windows OCR motoru (`OCR.ahk`in pywinrt ile ~100 satırı) |
| `cascade/core/ocr_layout.py` | OCR çıktısının dizilmesi: kolon/tablo (saf, test edilebilir) |
| `cascade/ui/ocr_view.py` | Gelişmiş OCR paneli: dil, biçim, ayraç, ölçek, kolon eşiği |
| `cascade/win32/window.py` | Hep-üstte pencere yönetimi (`WindowModule` + `menuAlwaysOnTop`) |
| `cascade/win32/screen.py` | Tüm monitörleri tek BitBlt ile fiziksel pikselde yakalama |
| `cascade/imgstore.py` | Görsel pano deposu (`clip_image_store.ahk`, biçim birebir) |
| `cascade/ui/clip_images.py` | Görsel geçmişi penceresi (`clip_image_dialog.ahk`) |
| `cascade/win32/instance.py` | `#SingleInstance Force` → adlandırılmış mutex, restart'ta bekleyerek devralır |
| `main.py` | yalnız giriş noktası: kilit + Qt + Cascade kurulumu |

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

VSCode eklentileri: `ms-python.python` (debugpy + Pylance ile gelir),
`charliermarsh.ruff`.
