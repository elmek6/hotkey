# AHK → Python: eksik aktarılan özellikler

Karşılaştırma tarihi: 2026-08-30. Bilinçli atlananlar listede YOK:
incognito, repository, macro_recorder. (`app_shorts` ve **türkçe klavye**
sonradan taşındı — aşağıda ✅.)

Sonradan geri alınanlar: **OCR** (F14 seçim aracında "OCR / OCR+") ve
**görsel pano** (`clip_image_*` → `imgstore.py` + `ui/clip_images.py`,
dosya biçimi AHK ile birebir).

Durum işaretleri: ⬜ yapılmadı · 🔶 kısmen / eylem hazır ama tuşsuz · ✅ sonradan eklendi

## Tuş / kaskad tarafı

| # | Özellik | AHK kaynağı | Durum |
|---|---|---|---|
| 1 | `cascadeTab` — Tab: kısa=Tab, basılı tut=slot menüsü, rakam=slot yükle | key_handler_cascade.ahk | ✅ (modifierli basımda önek devre dışı: Alt+Tab bozulmasın) |
| 2 | `cascadeCaps` — CapsLock toggle + rakamla geçmiş yapıştır | key_handler_cascade.ahk | ✅ |
| 3 | `Caret & rakam` AHK'de SLOT yüklüyordu; Python'da geçmişi yapıştırıyor (bilinçli sapma diye notlu ama slot yükleme yolu yoktu) | cascadeCaret | 🔶 F13 kombolarıyla slot yolu açıldı |
| 4 | MButton kaskadı: kısa=smartPaste (memslots), orta=smartPaste+Shift+Enter, MButton&F14=geçmiş arama, MButton&F15..F20=smart paste 6..1 | key_handler_mouse.ahk handleMButton | 🔶 `memslots.paste` eylemi hazır, tuşsuz |
| 4b | F14 kısa basım AHK'de `showF14menu` (tam menü: makro, mem clip, sistem, özel tuşlar, slot kolonları) idi; bizde slot hızlı menüsü | menus.ahk showF14menu | 🔶 slot menüsü ✅, menünün diğer blokları F13 menüsünde |
| 5 | `~MButton & WheelUp/Down` → Ctrl +/- zoom | AutoHotkey.ahk | ⬜ |
| 6 | RButton & F13/F14 → büyüteç zoom | handleRButton | ⬜ (RButton & Wheel ses var) |
| 7 | F13 & F15..F20 → pano geçmişi 6..1; F14 & F15..F20 → slot 6..1 | handleF13/handleF14 | ✅ F13 & F15..F20 → slot 6..1 eklendi (F14 seçim tuşu oldu) |
| 8 | Çift basım (pressType 4): enum var, makine hiç üretmiyor; AHK'de F13/F14 çift basımı arama pencereleri açıyordu | key_handler_mouse.ahk | ⬜ |
| 9 | F14/F17/F18 jestleri: F14 jestle ok tuşları; F17/F18 yatay jestle Delete/Backspace/geri al (yalnız F13 jesti port edildi) | EM.gesture satırları | ⬜ |
| 10 | Görsel basılı-tutma göstergesi (renkli etiket, EM.visual/ShowIndicator) — bizde yalnız bip | key_builder.ahk | ⬜ |
| 11 | Çift tık dedektörü: 70 ms altı çift tık sayacı + bip (arızalı fare tespiti) | AutoHotkey.ahk #HotIf bloğu | ✅ `dispatch.DOUBLE_CLICK_MS`; ikinci basım VE bırakması yutulur |
| 12 | Hızlı tekerlek kısıtlaması (`shouldProcessWheel` — hızlı çevirmede her ikinci olay) | script_state.ahk MouseState | ⬜ |
| 13 | Memslots açıkken `Insert` → smartPaste (eylem hazır, tuş bağlı değil) | AutoHotkey.ahk #HotIf isMemSlots | 🔶 |
| 13b | ✅ **Türkçe klavye eklentisi (ScrollLock)**: kısa basım TR aç/kapa, ≥600 ms dizilim 1↔2; dizilim 1 = c/s/i/g uzun basınca ç/ş/ı/ğ (harfi gönder, 400 ms sonra hâlâ basılıysa BackSpace + Türkçe harf), dizilim 2 = doğrudan remap (ü→ğ, ö→ş, ä→ı, `,`→ö, `.`→ç, y↔z…) | turkish_layout_addon.ahk | ✅ `core/turkish.py` + dispatch aşaması; demo kaskadı kaldırıldı |
| 13c | ✅ Klavyeyle fare: `#a/#s/#d/#w` 10px, `#q/#e` sol/sağ tık, `#y` Enter | AutoHotkey.ahk | ✅ |
| 13d | ✅ `DialogPauseGui` — Pause basılı tut: duraklat + pencere (devam / kaydetmeden yeniden başlat / yeniden başlat / çıkış) | menus.ahk | ✅ `ui/pause.py` |

## Pano / slot tarafı

| # | Özellik | AHK kaynağı | Durum |
|---|---|---|---|
| 14 | Slot menüleri: hızlı slot menüsü ✅ (F14 kısa basım), slot arama ⬜, "slota kaydet" menüsü ⬜, grup ekle/sil ⬜, yan grup seçimi ⬜ | clip_slot.ahk + menus.ahk | 🔶 (dosya biçimi bozulmadan korunuyor) |
| 15 | `bigclips.bin` — 1 MB üstü kopyalar ayrı dosyaya; bizde hiç alınmıyor | clip_hist.ahk | ⬜ |
| 15b | Görsel pano: yakalama, 500 slotlu indeks, 500 MB dairesel log, dedupe, thumb, önizleme penceresi | clip_image_store + clip_image_dialog | ✅ biçim birebir |
| 16 | Bellek içi geçmiş sınırı: AHK 1000, Python 50 (diskte ikisi de 2500) | clip_hist.ahk | ⬜ fark |

## Sistem tarafı

| # | Özellik | AHK kaynağı | Durum |
|---|---|---|---|
| 17 | Tuş sayacı / istatistik (KeyCounts, loadStats/saveStats, stats penceresi) | key_counter.ahk, script_state.ahk | ⬜ |
| 18 | Hep-üstte yönetimi (📌 pencere sabitleme, çıkışta hepsini bırakma) | script_state WindowModule + menus.ahk | ✅ `win32/window.py`, F13 menüsünde |
| 19 | Work/home profili: bilgisayar adına göre yapılandırma; work'te Outlook'u küçültülmüş başlatma | AutoHotkey.ahk LoadSettings | ⬜ (app_shorts kapsamında mı? karar senin) |
| 20 | `Pause & Delete` — tüm AHK süreçlerini öldürüp çık | AutoHotkey.ahk | ⬜ |
| 21 | Ufak statik kısayollar: `#a/#s/#d/#w` fare hareketi, `#q/#e` tık, `#y` Enter, NumpadIns/Del/Clear → J/L/K + Alt+Tab, `^<` VSCode satır sil, `!v` yavaş yapıştırma, AppsKey&a | AutoHotkey.ahk | ⬜ (deneme tuşlarını sen söyledikçe ekleniyor) |
| 22 | Ayarlar sistemi (settings.ahk + settings_dialog + SettingAction kayıtları) | settings*.ahk | ⬜ Faz 11'de planlı |

Not: `~RButton Up` → Esc mantığı eksik DEĞİL; Python'da farklı ve daha temiz
çözüldü (sağ tık yutulup sürüklemede gerçek basım enjekte ediliyor).

## OCR (F14 seçim aracı içinde) — AHK screen_ocr.ahk'den taşınanlar

| Özellik | Durum |
|---|---|
| Alan seçimi, 8 tutamaç, ortadan taşıma, Esc iptal | ✅ |
| Ayar fazında örtünün kalkması + tıklamaların altına geçmesi (maske) | ✅ |
| Alan değişince ekranın temiz haliyle yeniden yakalanması (SETTLE_MS) | ✅ |
| Biçim: düz metin / kolonlu / tablo (ayraçlı) | ✅ |
| Ayraç: hazır liste + elle yazma, `\t` `\n` `\s` kaçışları | ✅ |
| Ölçek (1-4x), yeniden OCR (ekran tekrar çekilmeden) | ✅ |
| Kolon eşiği (otomatik / elle px) | ✅ |
| Panelin yeniden boyutlandırılabilmesi | ✅ |
| Dil ve gri tonlama kutuları | ⛔ **kaldırıldı** — AHK'nin sarmalayıcısı zorunlu tutuyordu, `Windows.Media.Ocr` tutmuyor; dil kullanıcı profilinden seçiliyor, gri tonlama sabit uygulanıyor |
| Kelime kelime seçilebilen overlay (AHK'nin 1300 satırının çoğu buydu) | ⬜ |
| `readWindow` — aktif pencerenin tamamını OCR'la (seçimsiz) | ⬜ |
| Panel konumunun seçimin yanına (sağ/sol hangisi genişse) yerleşmesi | ⬜ |

## Görsel pano (clip images) — AHK clip_image_*.ahk'den taşınanlar

| Özellik | Durum |
|---|---|
| `clipimg.idx` / `clipimg.dat` biçimi (v2, 32 B header + 500×16448 B slot) | ✅ birebir |
| Dairesel 500 MB log, 8 bayt hizalama, pad kayıtları, tail'dan yeme | ✅ |
| Yazma sırası: blob → slot → header (çökme güvenliği) | ✅ |
| CRC32 ile dedupe (sayaç artar, blob'a dokunulmaz) | ✅ |
| 64×64 ham BGRA thumb, oran korunur + ortalanır | ✅ |
| Bozuk header/ring ve sürüm değişiminde yedekleyip sıfırlama | ✅ |
| Liste: son kullanım / boyut / KB / × / ilk kayıt + thumb ikonu | ✅ |
| Önizleme: sığıyorsa 1:1, sığmıyorsa sığdır; tekerlekle zoom, sürükleyerek kaydırma | ✅ |
| Panoya al (çift tık), sil (çoklu seçim + onay), PNG kaydet, 1:1/sığdır | ✅ |
| Canlı liste (depo `rev` yoklaması, seçim slot ile korunur) | ✅ |
| Panodaki görselin kendiliğinden depoya düşmesi | ✅ |
| F14 seçim aracında "🖼️ Görsellere ekle" | ✅ |
| `_isNearTail` / `_relocate` — sık kullanılanı ring başına taşıma (LRU) | ⬜ ring %80 dolmadan tetiklenmiyordu |
| Listeden dışarı sürükleyip bırakma (`ole_drag_source.ahk`) | ⬜ |
| Hash'in ham DIB yerine RGBA'dan alınması → dedupe AHK ile ortak çalışmaz | ⚠️ biçim uyumlu, dedupe sürümler arası değil |
