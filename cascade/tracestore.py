"""Windows iz depolari -- trace_store.ahk portu (incognito.py'nin altyapisi).

Bir dosyanin izi tek yerde durmuyor: ayni indirme `Recent\\*.lnk`te,
RecentDocs'ta, ComDlg32 MRU'larinda ve jump list'te kayit birakiyor.

CEKIRDEK FIKIR degismedi: acilirken yedek al, kapanirken aynen geri yaz.
Oturumda ne olustuysa yok olur, ONCEKI gecmis hic bozulmaz.

AHK'den AYNEN TASINAN kurallar (hepsi acidan ogrenilmis):

  * Registry hive'i kilitlenemez -> yedek/geri yukleme sart.
  * Geri yuklemeden ONCE anahtari silmek ZORUNLU; yalnizca ustune yazmak
    oturumda eklenenleri yerinde birakir.
  * Jump list dosyalari aktifken kilitli: yedek KILITLEMEDEN ONCE, geri
    yukleme KILIT ACILDIKTAN SONRA.
  * `.absent` sozlesmesi: "anahtar hic yoktu" ile "yedek alinamadi" AYRI
    durumlar. Karistirmak, yillardir duran DOLU bir anahtari "oturumda
    dogmus" sanip komple silmek demek -- AHK'de bir kez oldu.
  * `FileGlobStore` yedegi KLASOR DEGIL TEK DOSYA: maliyet veri hacminden
    degil DOSYA ADEDINDEN geliyor (156 dosya yaratmak 229 ms, tek paket
    51 ms). Bicim AHK ile birebir ("AHKGLOB1").

AHK'den TASINMAYAN sey: reg.exe'yi toplu cmd.exe'de zincirleme, 5-8 sn'lik
surec bekleme siniri, .reg metnini satir sayarak taban uretme. Hepsi
"AHK registry agacini kendi basina okuyamiyor" sorununun cozumuydu;
`winreg` ile o sorun yok (bkz. win32/reg.py).
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import struct
import time
from pathlib import Path

import orjson

from cascade.store import _write_atomic
from cascade.win32 import reg

log = logging.getLogger("cascade.incognito.store")

CORE = "core"
DEEP = "deep"


def _ahk_mtime(seconds: float) -> int:
    """POSIX zamani -> AHK'nin YYYYMMDDHHMISS tamsayisi (yerel saat).

    Paket bicimi AHK ile ayni kalsin diye ayni gosterim; karsilastirma da
    bu cozunurlukte yapiliyor (saniye), iki taraf ayni sonucu versin.
    """
    return int(time.strftime("%Y%m%d%H%M%S", time.localtime(seconds)))


def _from_ahk_mtime(stamp: int) -> float:
    return time.mktime(time.strptime(str(stamp), "%Y%m%d%H%M%S"))


class TraceStore:
    """Soyut taban.

    `tier`: "core" = DOSYA ADI tasiyan izler (varsayilan acik),
            "deep" = klasor gezinme + program calistirma izleri.
    Secim incognito.Incognito._select_stores() icinde.
    """

    def __init__(self, name: str, tier: str = CORE) -> None:
        self.name = name
        self.tier = tier

    # ---- alt siniflarin dolduracagi ----

    def count(self) -> int:
        """Su anda kac kayit var (denetim icin)."""
        return 0

    def snapshot(self, root: Path) -> bool:
        raise NotImplementedError

    def restore(self, root: Path) -> bool:
        raise NotImplementedError

    def purge(self) -> int:
        """Tamamen sil, silinen sayisini dondur."""
        return 0

    def archive(self, root: Path) -> bool:
        """clean_now()un aldigi KALICI yedek. Tek farkli depo FileGlobStore:
        oturum yedegi tek pakete, kalici yedek duz klasor kopyasina gider."""
        return self.snapshot(root)

    def snapshot_paths(self, root: Path) -> list[Path]:
        """Bu deponun yedek dosyalari. Kapsam disina cikan depo temizlenirken
        kullanilir; her depo KENDI dosyalarini bildirsin ki yeni bir depo tipi
        eklenince yedek sizdirmasin (AHK'de bu bir uzanti listesiydi)."""
        return []

    def baseline_count(self, root: Path) -> int:
        """Taban sayimi YEDEKTEN turetilir -- yedek tanim geregi enable()
        aninin kopyasi. Donus -1 = turetilemedi, depo denetimde atlanir."""
        return -1

    def audit_line(self, root: Path) -> str:
        base = self.baseline_count(root)
        if base < 0:
            return ""
        now = self.count()
        diff = now - base
        if not diff:
            return ""
        return f"{self.name}: {'+' if diff > 0 else ''}{diff}   ({base} -> {now})"

    # ---- degisiklik gozcusu ----
    # Gozcusuz varsayilan -> has_changed() HEP True. Atlamak POZITIF kanit ister.

    def start_watch(self) -> None:
        return None

    def has_changed(self) -> bool:
        return True

    def stop_watch(self) -> None:
        return None


class RegStore(TraceStore):
    """Tek bir registry anahtari; tam yedek + tam geri yukleme."""

    def __init__(self, name: str, key: str, tier: str = CORE) -> None:
        super().__init__(name, tier)
        self.key = key
        self._watcher = reg.KeyWatcher(key)

    # yedek dosyalari
    def _file(self, root: Path) -> Path:
        return root / f"{self.name}.json"

    def _absent(self, root: Path) -> Path:
        """ "Anahtar enable() aninda hic yoktu" isareti.

        Olmadan geri yukleme, "hic yedek alinamadi" (dokunma) ile "anahtar
        yoktu" (sil) durumlarini ayiramiyor; RunMRU/TypedPaths ilk kez
        olustugunda kalici kaliyordu."""
        return root / f"{self.name}.absent"

    def snapshot_paths(self, root: Path) -> list[Path]:
        return [self._file(root), self._absent(root)]

    def count(self) -> int:
        return reg.count_key(self.key)

    def snapshot(self, root: Path) -> bool:
        for path in self.snapshot_paths(root):
            path.unlink(missing_ok=True)
        dump = reg.dump_key(self.key)
        if dump is None:
            # IKI AYRI DURUM, karistirmak VERI KAYBI demek:
            #  (a) anahtar gercekten yoktu -> ".absent" koy
            #  (b) okuma patladi -> isaret KOYMA; koyarsak geri yukleme,
            #      duran DOLU bir anahtari "oturumda dogmus" sanip siler.
            if not reg.key_exists(self.key):
                self._absent(root).write_bytes(b"1")
                return True
            log.warning("%s: anahtar var ama okunamadi, yedek alinmadi", self.name)
            return False
        return _write_atomic(self._file(root), orjson.dumps(dump))

    def restore(self, root: Path) -> bool:
        if self._absent(root).exists():
            # enable() aninda anahtar yoktu -> oturumda olustuysa komple sil.
            reg.delete_tree(self.key)
            return True
        path = self._file(root)
        if not path.exists():
            return False  # hic yedek alinamamis -- DOKUNMA
        try:
            dump = orjson.loads(path.read_bytes())
        except (OSError, orjson.JSONDecodeError):
            log.exception("%s: yedek okunamadi, geri yukleme atlandi", self.name)
            return False
        if not isinstance(dump, dict):
            return False
        # Once komple sil: yalnizca ustune yazmak oturumda eklenenleri birakir.
        reg.delete_tree(self.key)
        return reg.restore_key(self.key, dump)

    def baseline_count(self, root: Path) -> int:
        if self._absent(root).exists():
            return 0
        path = self._file(root)
        if not path.exists():
            return -1
        try:
            dump = orjson.loads(path.read_bytes())
        except (OSError, orjson.JSONDecodeError):
            return -1
        if not isinstance(dump, dict):
            return -1
        return reg.count_dump(dump)

    def purge(self) -> int:
        n = self.count()
        if not n:
            return 0
        return n if reg.delete_tree(self.key) else 0

    def start_watch(self) -> None:
        self._watcher.start()

    def has_changed(self) -> bool:
        return self._watcher.has_changed()

    def stop_watch(self) -> None:
        self._watcher.stop()


class RegDeltaStore(RegStore):
    """Registry anahtari -- DELTA ("yalniz oturumda eklenenleri sil").

    Tam yedek yerine yalniz en yuksek sayisal alt anahtar numarasini
    (high-water mark) not eder, geri yuklemede sadece onun USTUNDEKILERI siler.

    NEDEN: ShellBags_UsrClass 8,2 MB / 47k kayit; bir oturumda eklenen ise
    birkac alt anahtar. Tam geri yukleme ayrica 8.882 anahtarin
    LastWriteTime'ini "simdi"ye cekip yillara yayilmis gecmisi tek bir
    pencereye sikistiriyordu -- kendisi bir iz.

    NEDEN DOGRU: Bags alt anahtarlari tam sayi ve tahsis SIRALI (olcum
    1..2427, bosluk yok) -- yeni klasor hep max+1 aliyor.

    DIKKAT -- TEK BASINA DOGRU DEGIL: silme bos NodeSlot birakiyor, Windows
    onu yeniden kullanirsa yeni bag hwm'in ALTINDA dogar ve delta kacirir.
    Engelleyen sey kardes BagMRU deposunun TAM geri yuklenmesi
    (incognito.Incognito.COUPLED). O listeyi bozarsan bu depo SESSIZCE sizdirir.
    """

    def _file(self, root: Path) -> Path:
        return root / f"{self.name}.hwm"

    def _max_child(self) -> int:
        """En yuksek SAYISAL alt anahtar. Anahtar bossa 0 -- o durumda
        oturumda olusan her sey (1, 2, ...) silinir, dogru davranis."""
        children = reg.numeric_subkeys(self.key)
        return max(children) if children else 0

    def _read_hwm(self, root: Path) -> int:
        try:
            return int(self._file(root).read_text("ascii").strip())
        except (OSError, ValueError):
            return -1

    def snapshot(self, root: Path) -> bool:
        for path in self.snapshot_paths(root):
            path.unlink(missing_ok=True)
        if not reg.key_exists(self.key):
            # Oturumda olustuysa komple silinsin -- RegStore ile ayni sozlesme.
            self._absent(root).write_bytes(b"1")
            return True
        return _write_atomic(self._file(root), str(self._max_child()).encode("ascii"))

    def restore(self, root: Path) -> bool:
        if self._absent(root).exists():
            reg.delete_tree(self.key)
            return True
        if not self._file(root).exists():
            return False  # yedek alinamamis -- DOKUNMA
        hwm = self._read_hwm(root)
        if hwm < 0:
            # Bozuk isaret: yanlis hwm = ESKI kayitlari silmek. Dokunma.
            return False
        reg.delete_subkeys_above(self.key, hwm)
        return True

    # hwm bir sayim degil -> kayit diffi uretilemez; denetim satirini
    # kendisi hesaplar.
    def baseline_count(self, root: Path) -> int:
        return -1

    def audit_line(self, root: Path) -> str:
        if self._absent(root).exists():
            return f"{self.name}: anahtar oturum basinda yoktu -- kapanista silinecek"
        if not self._file(root).exists():
            return ""
        hwm = self._read_hwm(root)
        if hwm < 0:
            return ""
        top = self._max_child()
        if top <= hwm:
            return ""
        return f"{self.name}: +{top - hwm} yeni kayit   ({hwm} -> {top})"


class FileGlobStore(TraceStore):
    """Klasor + dosya deseni (`Recent\\*.lnk`, jump list klasorleri).

    Yedek TEK DOSYA (".pack"). BICIM (kucuk-endian, AHK ile birebir):

        "AHKGLOB1"          8 bayt imza
        u32                 kayit sayisi
        kayit x N:
          u32 adUzunluk     (UTF-8 bayt)
          ad                UTF-8, NUL yok
          u32 veriUzunluk
          i64 sonYazma      (YYYYMMDDHHMISS; 0 = veri yok, dokunma)
          veri              ham bayt
    """

    SIGNATURE = b"AHKGLOB1"
    _HEADER = struct.Struct("<8sI")
    _ENTRY = struct.Struct("<I")
    _SIZES = struct.Struct("<Iq")

    def __init__(self, name: str, directory: Path, pattern: str, tier: str = CORE) -> None:
        super().__init__(name, tier)
        self.dir = Path(directory)
        self.pattern = pattern

    def _pack(self, root: Path) -> Path:
        return root / f"{self.name}.pack"

    def _bak(self, root: Path) -> Path:
        return root / self.name  # yalniz archive() (clean_now) kullanir

    def snapshot_paths(self, root: Path) -> list[Path]:
        return [self._pack(root), self._bak(root)]

    def _files(self) -> list[Path]:
        if not self.dir.is_dir():
            return []
        return [p for p in self.dir.glob(self.pattern) if p.is_file()]

    def count(self) -> int:
        return len(self._files())

    def snapshot(self, root: Path) -> bool:
        """Paket HER durumda yazilir (klasor yok olsa bile): bos paket geri
        yuklemeye "enable() aninda burada hicbir sey yoktu" bilgisini tasir.
        Atlanirsa oturumda ILK KEZ yaratilan klasordeki iz kalici kalir."""
        chunks: list[bytes] = []
        written = 0
        for path in self._files():
            entry = self._pack_one(path)
            if entry is None:
                continue
            chunks.append(entry)
            written += 1
        blob = self._HEADER.pack(self.SIGNATURE, written) + b"".join(chunks)
        return _write_atomic(self._pack(root), blob)

    def _pack_one(self, path: Path) -> bytes | None:
        """OKUNAMAYAN DOSYA (baska surec kilitlemis olabilir) yine de ADIYLA
        pakete girer, ama mtime=0 ile: adi olmazsa geri yukleme onu "oturumda
        dogmus" sanip SILER, verisi olursa yanlis icerik yazar."""
        try:
            data = path.read_bytes()
            stamp = _ahk_mtime(path.stat().st_mtime)
        except OSError:
            data, stamp = b"", 0
        name = path.name.encode("utf-8")
        return self._ENTRY.pack(len(name)) + name + self._SIZES.pack(len(data), stamp) + data

    def _unpack(self, root: Path) -> dict[str, tuple[str, bytes, int]] | None:
        """Paketi oku -> {ad_kucuk: (gercek_ad, veri, mtime)}.

        Anahtar buyuk/kucuk harf duyarsiz (NTFS oyle davraniyor, AHK'de de
        Map.CaseSense "Off" idi) ama GERCEK ad da tasinir: geri yazarken
        kucultulmus adi kullanmak dosyayi yeniden adlandirmak olurdu.
        None = yedek YOK/BOZUK; bos sozluk = BOS yedek, ikisi ayri anlam.
        """
        path = self._pack(root)
        if not path.exists():
            return None
        try:
            raw = path.read_bytes()
        except OSError:
            return None
        if len(raw) < self._HEADER.size:
            return None
        signature, expected = self._HEADER.unpack_from(raw, 0)
        if signature != self.SIGNATURE:
            return None
        out: dict[str, tuple[str, bytes, int]] = {}
        offset = self._HEADER.size
        try:
            for _ in range(expected):
                (name_len,) = self._ENTRY.unpack_from(raw, offset)
                offset += self._ENTRY.size
                name = raw[offset : offset + name_len].decode("utf-8")
                offset += name_len
                size, stamp = self._SIZES.unpack_from(raw, offset)
                offset += self._SIZES.size
                out[name.casefold()] = (name, raw[offset : offset + size], stamp)
                offset += size
        except (struct.error, UnicodeDecodeError):
            log.warning("%s: paket bozuk, geri yukleme atlanacak", self.name)
            return None  # bozuk paket -> "yedek yok" say, DOKUNMA
        return out

    def restore(self, root: Path) -> bool:
        """Iki asama: (1) oturumda DOGAN dosyalari sil, (2) oturumda
        DEGISENLERI yedekten geri yaz. Ikisi birlikte klasoru enable()
        anindaki haline dondurur."""
        backup = self._unpack(root)
        if backup is None:
            return False  # yedek yok / bozuk -- dokunma
        if not self.dir.is_dir():
            return True  # klasor hala yok -> yapacak bir sey kalmadi
        live: dict[str, tuple[int, int]] = {}
        for path in self._files():
            key = path.name.casefold()
            if key not in backup:
                with contextlib.suppress(OSError):
                    path.unlink()  # oturumda DOGDU -> sil
                continue
            try:
                info = path.stat()
            except OSError:
                continue
            live[key] = (info.st_size, _ahk_mtime(info.st_mtime))

        for key, (name, data, stamp) in backup.items():
            # mtime=0 -> yedek alinirken okunamamisti; icerigini bilmiyoruz,
            # dokunmak veriyi bozmak olur.
            if not stamp:
                continue
            # Birebir aynisa yazma -- disable()i sifira yakin tutan kontrol.
            if live.get(key) == (len(data), stamp):
                continue
            target = self.dir / name
            with contextlib.suppress(OSError, ValueError):
                target.write_bytes(data)
                # Damgayi da geri koy -- "simdi" kalmasi basli basina iz.
                when = _from_ahk_mtime(stamp)
                os.utime(target, (when, when))
        return True

    def baseline_count(self, root: Path) -> int:
        """Taban = baslktaki u32; paketi acmaya gerek yok."""
        path = self._pack(root)
        if not path.exists():
            return -1
        try:
            with path.open("rb") as handle:
                head = handle.read(self._HEADER.size)
        except OSError:
            return -1
        if len(head) < self._HEADER.size:
            return -1
        signature, count = self._HEADER.unpack(head)
        return count if signature == self.SIGNATURE else -1

    def archive(self, root: Path) -> bool:
        """clean_now()un KALICI yedegi: elle karistirilabilsin diye duz
        klasor kopyasi (pakete gerek yok, hiz burada onemli degil)."""
        target = self._bak(root)
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        for path in self._files():
            with contextlib.suppress(OSError):
                shutil.copy2(path, target / path.name)
        return True

    def purge(self) -> int:
        removed = 0
        for path in self._files():
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        return removed


class PolicyGuard:
    """Politika korumasi -- onleme katmani (trace_store.ahk `PolicyGuard`).

    Explorer son-dokuman listesini BELLEKTE tutup geri yazabildigi icin
    yalnizca "sonradan temizlemek" yetmiyor: izleme oturum boyunca
    KAYNAGINDA kapatilmali. Snapshot/restore'u guvenilir kilan parca bu.
    Hepsi HKCU -> yonetici hakki gerekmez.

    NOT: `ClearRecentDocsOnExit` bilincli olarak DISARIDA. Oturum kapanisinda
    ESKI gecmisi de siler; "onceki gecmis korunsun" karariyla celisir.
    """

    def __init__(self, items: list[tuple[str, str, int]]) -> None:
        self.items = items  # (anahtar, deger adi, yazilacak DWORD)
        self.saved: list[tuple[str, str, int | None]] = []
        self.applied = False

    def apply(self) -> None:
        if self.applied:
            return
        self.saved = []
        for key, value, data in self.items:
            self.saved.append((key, value, reg.read_dword(key, value)))
            reg.write_dword(key, value, data)
        self.applied = True

    def revert(self) -> None:
        if not self.applied:
            return
        for key, value, old in self.saved:
            self._revert_one(key, value, old)
        self.saved = []
        self.applied = False

    # ---- cokme kurtarma ----
    # apply() durumu yalniz bellekte; program cokerse revert() no-op kalir ve
    # politikalar KALICI takili kalirdi (Explorer'in "Son kullanilanlar"i bir
    # daha donmezdi). Bu ikili eski degerleri diske yazip surecten bagimsiz
    # geri yukluyor. Bicim revert_from'un okuduguyla ayni olmak ZORUNDA.

    def save_to(self, path: Path) -> None:
        lines = [
            f"{key}\t{value}\t{'0' if old is None else '1'}\t{'' if old is None else old}"
            for key, value, old in self.saved
        ]
        with contextlib.suppress(OSError):
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    @staticmethod
    def revert_from(path: Path) -> None:
        if not path.exists():
            return
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            log.exception("PolicyGuard.revert_from: %s okunamadi", path.name)
            text = ""
        for line in text.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            key, value, had = parts[0], parts[1], parts[2] == "1"
            old: int | None = None
            if had and len(parts) >= 4:
                with contextlib.suppress(ValueError):
                    old = int(parts[3])
            PolicyGuard._revert_one(key, value, old)
        with contextlib.suppress(OSError):
            path.unlink()

    @staticmethod
    def _revert_one(key: str, value: str, old: int | None) -> None:
        if old is None:
            reg.delete_value(key, value)
        else:
            reg.write_dword(key, value, old)
