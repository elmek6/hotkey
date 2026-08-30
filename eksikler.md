# AHK → Python: eksik aktarılan özellikler

Karşılaştırma tarihi: 2026-08-30. Bilinçli atlananlar listede YOK:
türkçe klavye, görsel pano (clip_image_*), OCR modülleri*, incognito,
repository, app_shorts, macro_recorder.
(*OCR: F14 seçim aracına "Basit/Gelişmiş OCR" olarak geri geldi.)

Durum işaretleri: ⬜ yapılmadı · 🔶 kısmen / eylem hazır ama tuşsuz · ✅ sonradan eklendi

## Tuş / kaskad tarafı

| # | Özellik | AHK kaynağı | Durum |
|---|---|---|---|
| 1 | `cascadeTab` — Tab: kısa=Tab, basılı tut=slot menüsü, rakam=slot yükle | key_handler_cascade.ahk | ⬜ |
| 2 | `cascadeCaps` — CapsLock toggle + rakamla geçmiş yapıştır | key_handler_cascade.ahk | ⬜ |
| 3 | `Caret & rakam` AHK'de SLOT yüklüyordu; Python'da geçmişi yapıştırıyor (bilinçli sapma diye notlu ama slot yükleme yolu yoktu) | cascadeCaret | 🔶 F13 kombolarıyla slot yolu açıldı |
| 4 | MButton kaskadı: kısa=smartPaste (memslots), orta=smartPaste+Shift+Enter, MButton&F14=geçmiş arama, MButton&F15..F20=smart paste 6..1 | key_handler_mouse.ahk handleMButton | 🔶 `memslots.paste` eylemi hazır, tuşsuz |
| 5 | `~MButton & WheelUp/Down` → Ctrl +/- zoom | AutoHotkey.ahk | ⬜ |
| 6 | RButton & F13/F14 → büyüteç zoom | handleRButton | ⬜ (RButton & Wheel ses var) |
| 7 | F13 & F15..F20 → pano geçmişi 6..1; F14 & F15..F20 → slot 6..1 | handleF13/handleF14 | ✅ F13 & F15..F20 → slot 6..1 eklendi (F14 seçim tuşu oldu) |
| 8 | Çift basım (pressType 4): enum var, makine hiç üretmiyor; AHK'de F13/F14 çift basımı arama pencereleri açıyordu | key_handler_mouse.ahk | ⬜ |
| 9 | F14/F17/F18 jestleri: F14 jestle ok tuşları; F17/F18 yatay jestle Delete/Backspace/geri al (yalnız F13 jesti port edildi) | EM.gesture satırları | ⬜ |
| 10 | Görsel basılı-tutma göstergesi (renkli etiket, EM.visual/ShowIndicator) — bizde yalnız bip | key_builder.ahk | ⬜ |
| 11 | Çift tık dedektörü: 70 ms altı çift tık sayacı + bip (arızalı fare tespiti) | AutoHotkey.ahk #HotIf bloğu | ⬜ |
| 12 | Hızlı tekerlek kısıtlaması (`shouldProcessWheel` — hızlı çevirmede her ikinci olay) | script_state.ahk MouseState | ⬜ |
| 13 | Memslots açıkken `Insert` → smartPaste (eylem hazır, tuş bağlı değil) | AutoHotkey.ahk #HotIf isMemSlots | 🔶 |

## Pano / slot tarafı

| # | Özellik | AHK kaynağı | Durum |
|---|---|---|---|
| 14 | Slot menüleri: hızlı slot menüsü, slot arama, "slota kaydet" menüsü, grup ekle/sil, yan grup seçimi | clip_slot.ahk + menus.ahk | ⬜ (dosya biçimi bozulmadan korunuyor) |
| 15 | `bigclips.bin` — 1 MB üstü kopyalar ayrı dosyaya; bizde hiç alınmıyor | clip_hist.ahk | ⬜ |
| 16 | Bellek içi geçmiş sınırı: AHK 1000, Python 50 (diskte ikisi de 2500) | clip_hist.ahk | ⬜ fark |

## Sistem tarafı

| # | Özellik | AHK kaynağı | Durum |
|---|---|---|---|
| 17 | Tuş sayacı / istatistik (KeyCounts, loadStats/saveStats, stats penceresi) | key_counter.ahk, script_state.ahk | ⬜ |
| 18 | Hep-üstte yönetimi (📌 pencere sabitleme, çıkışta hepsini bırakma) | script_state WindowModule + menus.ahk | ⬜ |
| 19 | Work/home profili: bilgisayar adına göre yapılandırma; work'te Outlook'u küçültülmüş başlatma | AutoHotkey.ahk LoadSettings | ⬜ (app_shorts kapsamında mı? karar senin) |
| 20 | `Pause & Delete` — tüm AHK süreçlerini öldürüp çık | AutoHotkey.ahk | ⬜ |
| 21 | Ufak statik kısayollar: `#a/#s/#d/#w` fare hareketi, `#q/#e` tık, `#y` Enter, NumpadIns/Del/Clear → J/L/K + Alt+Tab, `^<` VSCode satır sil, `!v` yavaş yapıştırma, AppsKey&a | AutoHotkey.ahk | ⬜ (deneme tuşlarını sen söyledikçe ekleniyor) |
| 22 | Ayarlar sistemi (settings.ahk + settings_dialog + SettingAction kayıtları) | settings*.ahk | ⬜ Faz 11'de planlı |

Not: `~RButton Up` → Esc mantığı eksik DEĞİL; Python'da farklı ve daha temiz
çözüldü (sağ tık yutulup sürüklemede gerçek basım enjekte ediliyor).
