# PySide6 -> Flet gecis plani

> **DURUM** (bu dosya her adimda guncelleniyor)
>
> Branch `flet2`. Tasinan: **5 panel** + bir ortaklastirma
> (`ask_qt`, `f56ff95`) -- kisayol haritasi (`7cbca8c`),
> duraklatma kutusu (`8775927`), slot duzenleme (`609573b`), log
> penceresi (`45f525e`), QR penceresi (`eff1be8`). Kalan 16 pencere hala
> PySide6'da ve program iki motorla CALISIYOR.
>
> **Asama 1'de geriye tek panel kaldi: `monitor.py`.**
>
> Yeni panel yazacak olana: once **Mimari** bolumunu, sonra **SIRADAKI
> ADIM** bolumunu oku. Kodda ornek: `keypilot/fui/key_map.py` (salt
> okunur), `keypilot/fui/pause.py` (dugmeli),
> `keypilot/fui/slot_edit.py` (kullanicidan METIN alan, yasayan panel) ve
> `keypilot/fui/log_view.py` (en buyugu: iki sekme, zamanlayici, Qt'ye is
> yaptirma, cizim sinirlama) ve `keypilot/fui/qr.py` (calisma aninda
> dogan/olen denetimler, resim).
>
> Denemek icin: `uv run python -m probes.flet` (bkz. **Nasil denenir**).

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

**Bir panelin uc parcasi.** Ucunun de ayni oldugu kalip:

| Parca | Nerede koser | Ornek |
|---|---|---|
| Qt'nin gordugu yuz | ana thread | `show_rows`, `show_paused`, `show_slot`, `shutdown` |
| Cizim ve olaylar | flet thread | `_build`, `_show_now`, `_hide_now`, `_on_key` |
| Cikan yol | sinyal, ana thread'e duser | `closed`, `resume`, `saved` |

Ilk cagri sayfayi bulamazsa (`engine.page is None`) thread baslatilir ve
BEKLENMEZ; `_build` bekleyen veriyle kendini cizer. Bekleseydi ana
thread 3.5 saniye donar, tepsi ve tus kuyrugu takilirdi.

---

## Asama 1 -- kolay: standart pencere, az cikti

| # | Panel | Satir | Durum | Not |
|---|---|---|---|---|
| 1 | `key_map_view.py` | 176 | **BITTI** | Salt okunur tablo. Tek cikti: `closed`. |
| 2 | `pause.py` | 99 | **BITTI** | 4 dugme, 4 sinyal. `WindowStaysOnTopHint` -> `always_on_top`. |
| 3 | `slot_edit.py` | 92 | **BITTI** | Form: ad + eski deger + yeni deger. Ilk kez ICERI veri alan ve DISKE yazan panel; ilk YASAYAN panel (bkz. asagidaki not). |
| 4 | `qr_view.py` | 341 | **BITTI** | Canli QR + sablona gore degisen alanlar. Planda 4a/4b diye bolunmustu, TEK adimda bitti (bkz. asagidaki not). |
| 5 | `log_view.py` | 421 | **BITTI** | Salt okunur liste + detay. Iki sekme, yoklama zamanlayicisi, Qt'ye is yaptirma. #4'ten ONCE yapildi (bkz. adim 3 sonu). |
| 6 | `monitor.py` | 183 | sirada | Canli akan olay listesi. IIk kez "surekli guncelleme" testi. Asama 1'in SON paneli. |

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

## Nasil denenir

### 1) Deneme penceresi -- gercek programa dokunmadan

    uv run python -m probes.flet

Bu kucuk bir DENEME PROGRAMI (projede `probes/` klasoru zaten bunun icin
var, `probes/gui.py` gibi). Gercek KeyPilot'u BASLATMAZ: tuslari
devralmaz, tepsiye yerlesmez, calisan KeyPilot'u kapatmaz. Sadece
tasinan pencereleri sahte veriyle acar.

On dugmesi var: kisayol haritasi, duraklatma kutusu, duraklatma +
kritik hata metni, uc slot durumu (dolu slot, bos slot, sifre slotu), log
penceresi ve uc QR girisi (duz metin, link, hazir wifi dizgisi). Log ve
QR pencereleri GERCEK dosyalari okuyor (`Files/log.txt`, `slots.json`) --
sahte veri yok; "Log temizle" gercekten siliyor, QR'in grup secimi
gercekten ayara yaziliyor. Pencerede bakilacak iki sey:

* **Alt satirdaki sayac** -- her saniye artmali. DURURSA program tarafi
  Flet yuzunden takilmis demektir, yani mimari kirik.
* **Ortadaki doküm** -- panellerden gelen her olay buraya yaziliyor.
  Satirlarda `MainThread` yazmali.

Deneme penceresini kapatinca Flet pencereleri de kapanir. Kapanmazsa
gorev cubugunda `flet.exe` kalir (Gorev Yoneticisi'nden kapatilabilir).

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
   suresince normal, bkz. asagidaki temizlik listesi.
9. **Pencere boyu.** Metin/Link sablonunda kisa, Wifi'de daha uzun bir
   pencere acilmali (alan sayisina gore). Altta bos serit KALMAMALI.
10. **Esc / X** kapatir; tekrar acinca aninda gelmeli ve icerik YENI
    panodakine gore kurulmali.

---

## SIRADAKI ADIM (adim 6): olay izleyici -- ASAMA 1'IN SONU

Dosya: `keypilot/ui/monitor.py` (183 satir) -> `keypilot/fui/monitor.py`

**Neden bu:** Asama 1'de kalan tek panel. Satir sayisi kucuk ama
**gecisin en riskli panellerinden biri** -- simdiye kadarki hicbir panel
SANIYEDE ONLARCA KEZ guncellenmiyordu.

**ASIL ENGEL: her olayda cizim YAPILAMAZ.** Qt surumunde `add()` her
klavye/fare olayinda cagriliyor ve tabloya bir satir ekliyor
(`app.py` `_drain`, satir ~1540). `QTableWidget` bunu tek satir ekleyerek
hallediyordu. Flet'te ayni sey `page.update()` demek ve adim 4'te olculdu:
guncelleme suresi denetim sayisiyla dogru orantili, ustelik cizim bitene
kadar dongu BASKA HICBIR SEYE yanit vermiyor. Hizli yazan birinde bu
saniyede 20+ tam cizim eder -- pencere kilitlenir.

**Cozum yonu (yazacak olana):** olaylari Qt tarafinda BIRIKTIR, ciziMI
zamanlayiciya bagla.

    add(event, swallowed)   ->  listeye ekle, CIZME (ana thread)
    QTimer ~100 ms          ->  degistiyse tek `_draw` (Flet thread)

Boylece cizim sayisi saniyede en fazla 10'a iner ve `_drain`in isi
listeye bir demet eklemekten ibaret kalir. `fui/log_view.py`deki
`POLL_MS` zamanlayicisi ayni kalibin ornegi.

**Oteki dort mesele:**

1. **`isVisible()` karsiligi.** `app.py` `_drain` her turda
   `self.monitor.isVisible()` diye soruyor ve pencere kapaliyken hic
   beslemiyor (maliyet sifir). Flet panelinde bu soru FLET thread'ine
   sorulamaz -- her tus icin thread'ler arasi gidip donmek olur. Panel
   gorunurlugunu Qt tarafinda bir bayrakta tutmali (`_hide`/`_show_now`
   ikisini de guncelleyecek).
2. **Sag tik menusu.** Qt'de `QMenu` ile hucre/satir/tumu kopyalama var.
   Flet'te baglam menusu YOK; adim 4'te ayni sorun dugmelerle cozuldu
   (alt siradaki dugmeler zaten ayni kopyalama secenekleri -- Qt surumu
   de ikisini birden sunuyordu, yani menuyu dusurmek kayip degil).
3. **Cift tiklama** satiri kopyaliyordu; Flet'te cift dokunma olayi yok.
   Yine dugme (adim 4'te de boyle yapildi).
4. **Panoya yazma** `_on_qt` ile Qt tarafinda -- kalip hazir.

**Olcu:** Qt `resize(660, 460)`. Yukseklik oldugu gibi kopyalanmamali,
bkz. **PENCERE OLCUSU kurali**.

**On kosul BITTI:** `ask_qt` motora tasindi (`f56ff95`), yani monitor
kalibi kopyalamayacak -- dogrudan `self._engine.ask_qt(...)` cagiracak.

**Ikinci on kosul da bitti:** otomatik guncelleme kapatildi (bkz.
**OTOMATIK GUNCELLEME KAPALI**). Monitor'un akan listesi log
penceresiyle ayni tuzaga dusecekti; artik yalniz `_draw` ciziyor.
Kaydirma konumu tutulacaksa `on_scroll` ARTIK BEDAVA.

---

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
      `ui/slot_edit.py`, `ui/log_view.py`, `ui/qr_view.py`.
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
- [ ] **`fui/qr.py`deki `QFileDialog`** -- "Kaydet PNG" dosya kutusu hala
      Qt'nin. Gecis suresince BILEREK boyle (`_on_qt` ile bir satir);
      Qt gidince yerine `ft.FilePicker` yazilmali ve o bir SERVIS:
      sayfaya eklenip sonucu geri cagriyla alinmali. Onceki `flet`
      bransinda `cascade/fui/shell.py` ornegi var.
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
- [ ] **Flet'in ic bayragina mudahale** (`fui/engine.py`
      `_disable_auto_update`). `signal.signal` yamasi gibi SUREC genelinde
      ve Flet'in ICINDEKI bir davranisa dayaniyor: bayrak modul duzeyinde
      paylasilan bir `ContextVar` varsayilaninda tutuluyor ve
      `reset_auto_update` onu ustten kopyaliyor. Flet surumu yukselince
      SESSIZCE bozulabilir -- program calisir, yalnizca pencere yeniden
      agirlasir. `tests/test_flet_engine.py` tam bu yuzden var; surum
      yukseltmesinde ONCE o testlere bakilmali. Flet resmi bir
      "auto-update kapali" ayari sunarsa oraya gecilmeli.

- [ ] **`fui/theme.py` sabit koyu palet.** Qt surumu sistem temasini
      izliyordu (`theme.py`: Windows 10'da `AppsUseLightTheme`). Ayar
      ekrani tasinirken (Asama 2, #13) tema izleme geri gelmeli.
- [ ] **`pyproject.toml`den `pyside6`** -- yalnizca Asama 3 bittikten
      sonra. `flet-desktop` ACIKCA eklendi cunku Flet onu ilk
      calistirmada kendi kendine pip'liyor; kilitli projede istenmez.
- [ ] **Testler.** `tests/` icinde Qt pencerelerini kuran testler var;
      panel tasindikca Flet karsiliklari yazilmali. Motorun iki global
      ayari artik test ediliyor (`tests/test_flet_engine.py`: signal
      yamasi, otomatik guncelleme, `ask_qt`); tasinan BES PANELIN kendi
      birim testi hala YOK -- dogrulama elle yapildi. En kolay baslangic
      saf fonksiyonlar (Flet gerekmiyor, ekran gerekmiyor):
      `fui/slot_edit.py` `old_value()` (maskeleme, bosluk ezme, kirpma),
      `fui/qr.py` `masked()` / `slot_rows()` / `window_height()`,
      `fui/log_view.py` `line_text()` / `source_chars()` /
      `detail_height()`. Bunlar tam da elle dogrulanmasi en sikici olan
      kurallar.
- [ ] **`slots_ctl._editing`** -- duzenlenen slotu tutan alan. Ayni anda
      tek kutu acik oldugu icin dogru; Flet coklu pencereye gecerse
      (yukaridaki `FletEngine` karari) bu varsayim duser.
- [ ] **QR'da her tus vurusunda tam cizim.** `_refresh` alan degisiminde
      kareyi yeniden uretip `page.update()` cagiriyor. Su an sorun DEGIL
      (pencerede az denetim var, segno 1 ms altinda, PNG birkac kilobayt)
      ama log penceresindeki gecikmeli cizim kalibi (`FILTER_MS`) burada
      YOK. Alanlar cogalirsa ilk bakilacak yer.
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
      penceresi kendi varsayilan yerine geliyor. Cozum fiziksel/mantiksal
      piksel cevrimi istiyor (bu makine %135 olcekli, iki monitor) --
      `win32/screen.py` `monitors()` hazir, `page.window.left/top` var.
      Cok monitorlu kullanimda rahatsiz ederse oncelige alinmali.
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
- [ ] **Slot kutusunun olcusu sabit** (480x330). Qt `adjustSize` ile
      380-520 piksel arasinda kendini ayarliyordu; cok uzun "eski" degeri
      artik kutuyu buyutmuyor, 160 karakterde zaten kirpiliyor.
