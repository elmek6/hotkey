"""Incognito -- incognito.ahk portu.

UC KATMAN. Jump list kilidi tek basina yetmiyordu: tek bir indirme 5 ayri
depoya iz birakiyor, kilit bunun 1'ini kapsiyordu.

  1. ONLE   : `PolicyGuard` oturum boyunca Explorer'in izlemesini kapatir.
  2. DONDUR : jump list dosyalarini dislayici kilitle dondur (win32/filelock).
  3. GERI AL: yedek al, kapanista aynen geri yaz (tracestore).

KADEME. Depolarin maliyeti esit dagilmiyor ve hepsi ayni seyi korumuyor:

  * core (6 depo, VARSAYILAN ACIK) -- DOSYA ADI tasiyanlar. Actigin ya da
    kaydettigin bir dosyanin adi buraya duser.
  * deep (12 depo, VARSAYILAN KAPALI) -- klasor gezinme ve program calistirma
    izleri; dosya adi tutmazlar, maliyetin buyuk kismi burada.

ESLI DEPOLAR AYNI KADEMEDE OLMAK ZORUNDA (`COUPLED`). Ayirirsan
`RegDeltaStore` kardesi olmadan calisir ve SESSIZCE sizdirir; ayrinti
tracestore.RegDeltaStore'da.

QT YOK. Bu modul zamanlayici da acmaz, pencere de: `watch_tick()` disaridan
(app.py'deki QTimer) cagrilir, `enable()`/`disable()` sonucu veri olarak
doner ve ipucunu gosteren taraf UI'dir. Sebep AHK'de ayrilamayan seydi:
mantik test edilebilir kalsin.

BILEREK KAPSAM DISI (AHK tarafinda arastirildi, olculdu, elendi):
  * Thumbcache -- MODULUN EN BUYUK ACIGI. Onizlenen her gorselin kucuk resmi
    `thumbcache_*.db`de kaliyor ve DOSYA SILINSE BILE duruyor (~1,1 GB).
    Explorer acik tuttugu icin ne kilitlenebiliyor ne silinebiliyor.
  * Windows Timeline -- CDPUserSvc'de kilitli, politika HKLM.
  * Prefetch / SRUM / ShimCache / BAM / olay gunlukleri -- admin ister;
    bu modul bilincli HKCU-only.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from cascade import paths
from cascade.store import JsonStore
from cascade.tracestore import (
    CORE,
    DEEP,
    FileGlobStore,
    PolicyGuard,
    RegDeltaStore,
    RegStore,
    TraceStore,
)
from cascade.win32.filelock import ExclusiveLocks
from cascade.win32.shell import refresh_shell

log = logging.getLogger("cascade.incognito")

APPDATA = Path(os.environ.get("APPDATA", ""))
RECENT = APPDATA / "Microsoft" / "Windows" / "Recent"
VLC_INI = APPDATA / "vlc" / "vlc-qt-interface.ini"

# Kilitlenecek jump list klasorleri: (klasor, desen)
JUMPLIST_DIRS: tuple[tuple[Path, str], ...] = (
    (RECENT / "AutomaticDestinations", "*.automaticDestinations-ms"),
    (RECENT / "CustomDestinations", "*.customDestinations-ms"),
)

SESSION_MARK = "SESSION"
POLICY_FILE = "POLICY.tsv"

_E = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer"
_SH = r"HKCU\Software\Microsoft\Windows\Shell"  # Shellbags (NTUSER.DAT)
_SC = r"HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\Shell"


@dataclass(frozen=True, slots=True)
class EnableResult:
    locked: int  # dondurulan jump list dosyasi
    stores: int  # kapsamdaki depo
    deep: bool


@dataclass(frozen=True, slots=True)
class DisableResult:
    restored: int  # geri yuklenen depo
    skipped: int  # hic dokunulmadigi icin atlanan depo
    stores: int
    did_restore: bool  # kullanici geri yuklemeyi kapatmis olabilir


class IncognitoOptions(JsonStore):
    """`Files/incognito.json` -- su an tek ayar "derin izler"."""

    filename = "incognito.json"
    version = 1


class Incognito:
    """Oturum boyunca Windows'un dosya izlerini dondurur.

    Kullanim (app.py):
        inc = Incognito()
        inc.enable()                     # kisayoldan
        QTimer -> inc.watch_tick()       # 700 ms
        inc.disable()
    """

    WATCH_PERIOD_MS = 700  # yeni jump list dosyalarini yakalama sikligi

    # ESLI DEPOLAR -- birlikte geri yuklenmek ZORUNDA. Delta silmesi bos
    # NodeSlot birakiyor; slotun yeniden kullanilmamasi NodeSlots bitmap'ini
    # ICEREN BagMRU deposunun tam geri yuklenmesine bagli.
    COUPLED: tuple[tuple[str, ...], ...] = (("ShellBags_UsrClass", "ShellBagMRU_UsrClass"),)

    def __init__(self, ask_recover: Callable[[], bool] | None = None) -> None:
        self.active = False
        # enable()/disable() uzun surer ve arasinda Qt olayi islenebilir
        # (kisayola iki kez basmak, rozetten kapatmak). Bu bayrak ikinci
        # cagriyi no-op yapar; is yapan HER giris noktasi bakmak zorunda.
        self._busy = False

        self.locks = ExclusiveLocks()
        self.snap_dir = paths.FILES / "incognito_snapshot"
        self.session_start: float = 0.0
        self.restore_on_close = True
        self.cover_vlc = True  # VLC: kilit yerine "surekli bosalt"
        self.extra_targets: list[Path] = []
        self._ask_recover = ask_recover

        self._options = IncognitoOptions()
        self.deep_mode = bool(self._options.load().get("deep", False))

        # SIRA ONEMLI -- EN AGIR DEPO EN ONDE. Yeni depo eklerken olcup
        # agirligina gore yerlestir, sona ekleme.
        self.all_stores: list[TraceStore] = [
            # Shellbags cifti: BagMRU = gezinilen klasor sirasi (asil kanit,
            # tam yedek sart), Bags = yalniz gorunum ayari ama maliyetin
            # ~%90'iydi -> delta yoluna alindi.
            RegStore("ShellBagMRU_UsrClass", _SC + r"\BagMRU", DEEP),  # 2,75 MB
            RegStore("OpenSavePidlMRU", _E + r"\ComDlg32\OpenSavePidlMRU"),  # 1,70 MB
            RegStore("RecentDocs", _E + r"\RecentDocs"),  # 1,28 MB
            RegStore("UserAssist", _E + r"\UserAssist", DEEP),  # calisan programlar
            RegDeltaStore("ShellBags_UsrClass", _SC + r"\Bags", DEEP),  # ESLI
            # ComDlg32'nin DORDU birden kapsamda: ikisini birakmak kapiyi yari
            # kapatmak oluyordu.
            RegStore("LastVisitedPidlMRU", _E + r"\ComDlg32\LastVisitedPidlMRU"),
            RegStore("CIDSizeMRU", _E + r"\ComDlg32\CIDSizeMRU", DEEP),
            RegStore("FirstFolder", _E + r"\ComDlg32\FirstFolder", DEEP),
            RegStore("FeatureUsage", _E + r"\FeatureUsage", DEEP),
            RegStore("ShellBags", _SH + r"\Bags", DEEP),
            RegStore("ShellBagMRU", _SH + r"\BagMRU", DEEP),
            RegStore("WordWheelQuery", _E + r"\WordWheelQuery", DEEP),  # arama kutusu
            RegStore("TypedPaths", _E + r"\TypedPaths", DEEP),  # adres cubugu
            RegStore("RunMRU", _E + r"\RunMRU", DEEP),  # Win+R gecmisi
            RegStore("MUICache", _SC + r"\MuiCache", DEEP),
            FileGlobStore("RecentLnk", RECENT, "*.lnk"),
            FileGlobStore("JumpListAuto", *JUMPLIST_DIRS[0]),
            FileGlobStore("JumpListCustom", *JUMPLIST_DIRS[1]),
        ]
        self.stores: list[TraceStore] = self._select_stores()

        self.policy = PolicyGuard(
            [
                (_E + r"\Advanced", "Start_TrackDocs", 0),
                (_E + r"\Advanced", "Start_TrackProgs", 0),
                (
                    r"HKCU\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer",
                    "NoRecentDocsHistory",
                    1,
                ),
            ]
        )
        self._last_skipped = 0
        #: AppID -> ad tablosu; ilk sorulusta okunur (opsiyonel dosya).
        self._app_ids: dict[str, str] | None = None

    # ---- durum ----

    @property
    def locked_count(self) -> int:
        return len(self.locks)

    def locked_paths(self) -> list[Path]:
        return list(self.locks.paths())

    def get_name(self, app_id: str) -> str:
        """AHK `getName`: jump list AppID'sinin (hex) okunur adi.

        Tablo `Files/incognito_appids.json` icinde ve OPSIYONEL -- yoksa hex
        oldugu gibi gorunur. Windows bu esleme icin bir API vermiyor, liste
        elle buyuyor.
        """
        if self._app_ids is None:
            self._app_ids = self._load_app_ids()
        return self._app_ids.get(app_id.lower(), app_id)

    @staticmethod
    def _load_app_ids() -> dict[str, str]:
        path = paths.FILES / "incognito_appids.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(key).lower(): str(value) for key, value in data.items()}

    def name_for_file(self, path: Path) -> str:
        """AHK `nameForFile`: `<hex>.automaticDestinations-ms` -> uygulama adi."""
        return self.get_name(path.stem)

    def locked_names(self, limit: int = 300) -> list[str]:
        """AHK `getLockedNames`: dondurulmus jump list dosyalarinin adlari."""
        return [self.name_for_file(path) for path in self.locked_paths()[:limit]]

    # ---- kademe ----

    def _select_stores(self) -> list[TraceStore]:
        """Oturumda kapsanacak depolar. Sira korunur (en agir onde)."""
        if self.deep_mode:
            return list(self.all_stores)
        return [s for s in self.all_stores if s.tier == CORE]

    def set_deep_mode(self, on: bool) -> None:
        """Derin izleri ac/kapat. AKTIFKEN de cagrilabilir.

        Acarken yedek O AN alinir -- o ana kadar olusmus derin izler kapsam
        disi kalir, cunku yedek gecmise gidemez. Kapatirken o depolardaki
        oturum izleri KALIR ve yedekleri atilir.
        """
        if self._busy:
            return
        on = bool(on)
        if on == self.deep_mode:
            return
        self.deep_mode = on
        self._options.save({"deep": on})
        if not self.active:
            self.stores = self._select_stores()
            return

        before = {s.name for s in self.stores}
        following = self._select_stores()
        if on:
            added = [s for s in following if s.name not in before]
            self.stores = following
            self.snap_dir.mkdir(parents=True, exist_ok=True)
            for store in added:
                store.start_watch()
            for store in added:
                self._snapshot_one(store)
        else:
            dropped = [s for s in self.stores if s.tier == DEEP]
            self.stores = following
            for store in dropped:
                store.stop_watch()
                self._drop_snapshot(store)

    # ---- ac / kapa ----

    def toggle(self) -> EnableResult | DisableResult | None:
        return self.disable() if self.active else self.enable()

    def enable(self) -> EnableResult | None:
        if self.active or self._busy:
            return None
        self._busy = True
        try:
            self._recover_stale()  # onceki oturum cokmusse once onu coz
            self.active = True
            self.stores = self._select_stores()  # kademe her acilista okunur
            self.session_start = datetime.now().timestamp()
            self.snap_dir.mkdir(parents=True, exist_ok=True)

            self.policy.apply()  # 1) onle
            # Cokme kurtarmasi icin diske yaz: apply() durumu yalniz bellekte.
            self.policy.save_to(self.snap_dir / POLICY_FILE)

            self._snapshot_all()  # 3) yedekle -- KILITLEMEDEN ONCE
            self._lock_all_existing()  # 2) dondur
            self._clear_vlc_recents()
            return EnableResult(len(self.locks), len(self.stores), self.deep_mode)
        finally:
            self._busy = False

    def disable(self) -> DisableResult | None:
        if not self.active or self._busy:
            return None
        self._busy = True
        try:
            # Kilit ONCE acilmali: kilitli dosya okunamaz, geri yukleme
            # jump list paketini yazamaz.
            self.locks.unlock_all()
            restored = 0
            if self.restore_on_close:
                restored = self._restore_all()
                refresh_shell()
            else:
                for store in self.stores:
                    store.stop_watch()
                self._discard_snapshot()
            self.policy.revert()
            self.active = False
            return DisableResult(
                restored, self._last_skipped, len(self.stores), self.restore_on_close
            )
        finally:
            self._busy = False

    # ---- yedek ----

    def _snapshot_all(self) -> None:
        # SESSION = "acik bir oturumun yedegi duruyor"; cokme sonrasi
        # kurtarmayi bu tetikliyor. EN BASTA yazilmali -- sonda yazilirsa
        # yedegin ortasindaki bir cokme "yedek yok" gibi gorunur, POLICY.tsv
        # hic okunmaz ve Start_TrackDocs kapali takili kalir.
        self._clear_snap_payload()
        with contextlib.suppress(OSError):
            (self.snap_dir / SESSION_MARK).write_text(
                datetime.now().isoformat(timespec="seconds"), encoding="utf-8"
            )
        # Gozculer YEDEKTEN ONCE kurulur: yedek alinirken dusen bir iz
        # yedege karisirsa depo "degismis" sayilsin (bkz. reg.KeyWatcher).
        for store in self.stores:
            store.start_watch()
        for store in self.stores:
            self._snapshot_one(store)

    def _snapshot_one(self, store: TraceStore) -> None:
        try:
            store.snapshot(self.snap_dir)
        except Exception:
            log.exception("incognito yedek alinamadi: %s", store.name)

    def _restore_all(self) -> int:
        if not self.snap_dir.is_dir():
            return 0

        # 1) Soruyu SOR ve gozcuyu KAPAT. Kapatmak silmeden once olmali:
        #    silinecek anahtarin uzerinde acik KEY_NOTIFY handle'i kalmasin.
        changed: dict[str, bool] = {}
        for store in self.stores:
            changed[store.name] = store.has_changed()
            store.stop_watch()

        # 1b) ESLI DEPOLARI HIZALA. Gozcu her depoyu bagimsiz degerlendiriyor;
        #     ama delta silmesi ile kardesinin NodeSlots bitmap'i ayni anda
        #     eski haline donmezse bosalan slot yeniden kullanilir ve delta o
        #     bag'i kacirir. Biri degistiyse hepsi degismis sayilir.
        for group in self.COUPLED:
            if any(changed.get(name) for name in group):
                for name in group:
                    if name in changed:
                        changed[name] = True

        self._last_skipped = sum(1 for s in self.stores if not changed[s.name])

        restored = 0
        for store in self.stores:
            if not changed[store.name]:
                continue
            try:
                if store.restore(self.snap_dir):
                    restored += 1
            except Exception:
                log.exception("incognito geri yukleme basarisiz: %s", store.name)
        self._discard_snapshot()
        return restored

    def _discard_snapshot(self) -> None:
        shutil.rmtree(self.snap_dir, ignore_errors=True)

    def _clear_snap_payload(self) -> None:
        """Yedek klasorunu bosalt ama POLICY.tsv'YE DOKUNMA.

        enable() sirasi "policy.save_to -> yedek" oldugu icin duz silme az
        once yazilan POLICY.tsv'yi de siliyordu; cokme sonrasi revert_from
        dosyayi bulamiyor ve Start_TrackDocs kapali takili kaliyordu.
        """
        if not self.snap_dir.is_dir():
            return
        for path in self.snap_dir.iterdir():
            if path.name == POLICY_FILE:
                continue
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                with contextlib.suppress(OSError):
                    path.unlink()

    def _drop_snapshot(self, store: TraceStore) -> None:
        """Kapsam disina cikan deponun yedegini at (bkz. set_deep_mode)."""
        for path in store.snapshot_paths(self.snap_dir):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                with contextlib.suppress(OSError):
                    path.unlink()

    def _recover_stale(self) -> None:
        """Program cokmesi / zorla kapatma sonrasi kalan yedek.

        Politika geri alma kullanicinin kararindan BAGIMSIZ ve ONCE yapilir:
        "hayir" dese bile Start_TrackDocs kapali takili kalmasin.
        """
        if not (self.snap_dir / SESSION_MARK).exists():
            return
        PolicyGuard.revert_from(self.snap_dir / POLICY_FILE)
        # Soracak kimse yoksa geri yukle: kullanicinin gecmisini geri vermek
        # guvenli taraf, atmak geri donusu olmayan taraf.
        if self._ask_recover is None or self._ask_recover():
            log.info("onceki incognito oturumu duzgun kapanmamis, yedek geri yukleniyor")
            self._restore_all()
        else:
            self._discard_snapshot()

    # ---- kilit ----

    def _lock_all_existing(self) -> None:
        for directory, pattern in JUMPLIST_DIRS:
            if not directory.is_dir():
                continue
            for path in directory.glob(pattern):
                self.locks.lock(path)
        for target in self.extra_targets:
            if target.exists():
                self.locks.lock(target)

    def watch_tick(self) -> None:
        """Zamanlayicidan (WATCH_PERIOD_MS) cagrilir.

        Oturum SIRASINDA olusan yeni jump list dosyalarini kilitler, yeni
        `.lnk` izlerini siler. Asil guvence kapanistaki geri yukleme; bu tur
        "oturum sirasinda da gorunmesin" icin.
        """
        if not self.active:
            return
        for directory, pattern in JUMPLIST_DIRS:
            if not directory.is_dir():
                continue
            for path in directory.glob(pattern):
                if path not in self.locks:
                    self.locks.lock(path)
        for target in self.extra_targets:
            if target.exists() and target not in self.locks:
                self.locks.lock(target)
        self._clear_vlc_recents()
        self._clear_recent_lnk()

    def add_extra_target(self, path: Path | str) -> None:
        """Uygulama-ici gecmis dosyasi ekle. Kilitlemek uygulamayi bozabildigi
        icin liste varsayilan BOS."""
        target = Path(path)
        if target in self.extra_targets:
            return
        self.extra_targets.append(target)
        if self.active and target.exists():
            self.locks.lock(target)

    # ---- "son dosyalar" kisayollari ----

    def _clear_recent_lnk(self) -> None:
        """Yalniz OTURUMDA olusanlari siler; eski gecmis korunur.

        Bu klasor kilitlenmiyor: `Recent\\*.lnk`i kilitlemek Explorer'i
        bozuyor, o yuzden surekli silme yolu secildi.
        """
        if not RECENT.is_dir():
            return
        for path in RECENT.glob("*.lnk"):
            try:
                if path.stat().st_mtime < self.session_start:
                    continue
                path.unlink()
            except OSError:
                continue

    # ---- VLC ----

    def _clear_vlc_recents(self) -> None:
        """VLC son-medya listesini bosalt (kilitlemek VLC'yi bozuyor).

        Dosyanin tamamini yeniden yazan bir INI kutuphanesi kullanmiyoruz:
        VLC'nin kendi bicimini (yorum satirlari, sira) bozmadan yalniz
        ILGILI SATIRLARI bosaltmak, dosyayi bize ait olmayan bir bicime
        cevirmekten guvenli. Zaten doluysa yaziyoruz -- gereksiz disk
        yazimi da bir iz.
        """
        if not self.cover_vlc or not VLC_INI.is_file():
            return
        blanks = {
            "[RecentsMRL]": ("list", "times"),
            "[OpenDialog]": ("netMRL",),
        }
        try:
            text = VLC_INI.read_text(encoding="utf-8", errors="surrogateescape")
        except OSError:
            return

        out: list[str] = []
        section = ""
        dirty = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped
            elif section in blanks and "=" in stripped and not stripped.startswith("#"):
                name, _, value = stripped.partition("=")
                if name.strip() in blanks[section] and value.strip():
                    line = f"{name.strip()}="
                    dirty = True
            out.append(line)
        if not dirty:
            return
        try:
            VLC_INI.write_text("\n".join(out) + "\n", encoding="utf-8", errors="surrogateescape")
        except OSError:
            log.warning("VLC gecmisi temizlenemedi: %s", VLC_INI)

    # ---- denetim ----

    def audit(self) -> list[str]:
        """enable() anindaki sayimla simdikini karsilastirir.

        Taban YEDEKTEN turetiliyor (bkz. TraceStore.baseline_count), yani
        maliyet enable()'a degil bu cagriya yaziliyor -- kullanici
        "denetle"ye bastiginda zaten beklemeyi goze almis.
        """
        if not self.snap_dir.is_dir():
            return ["Yedek klasoru yok -- denetim yapilamiyor."]
        lines: list[str] = []
        for store in self.stores:
            try:
                line = store.audit_line(self.snap_dir)
            except Exception as exc:  # noqa: BLE001 -- denetim hicbir sey bozmasin
                line = f"{store.name}: denetlenemedi ({exc})"
            if line:
                lines.append(line)
        return lines

    # ---- tam temizlik ----

    def clean_now(self) -> int:
        """DIKKAT: geri donusu olmayan tek islem -- ESKI gecmisi de siler.

        Oncesinde `Files/incognito_backup_<zaman>/` altina kalici yedek alinir.
        KADEMEYE BAKMAZ (`all_stores`): kademe hiz icindi, "her seyi sil" acik
        bir kullanici eylemi.
        """
        was_active = self.active
        if was_active:
            self.locks.unlock_all()

        backup = paths.FILES / f"incognito_backup_{datetime.now():%Y%m%d_%H%M%S}"
        backup.mkdir(parents=True, exist_ok=True)
        removed = 0
        for store in self.all_stores:
            try:
                store.archive(backup)
                removed += store.purge()
            except Exception:
                log.exception("incognito temizlik basarisiz: %s", store.name)
        self._clear_vlc_recents()
        refresh_shell()

        if was_active:
            # Canli yedek YENILENMEZSE az once kalici silinen kayitlari hala
            # icerir ve disable() onlari geri yazip clean_now'u bosa cikarir.
            self._snapshot_all()
            self._lock_all_existing()  # Windows yeniden yaratirsa "bos" donsun
        return removed
