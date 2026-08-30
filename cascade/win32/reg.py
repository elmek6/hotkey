"""Registry islemleri -- trace_store.ahk `RegStore`in Win32 yarisi.

AHK tarafi reg.exe SUREC BASLATARAK calisiyordu: `reg.exe export` ile yedek,
`reg.exe import` ile geri yukleme. Sebep AHK'nin registry agacini bir bloka
alip geri yazacak bir yolunun olmamasiydi; bedeli agirdi (surec basina ~17 ms,
14 depo = 235 ms, ustune 5-8 sn zaman asimi bekleyisleri, yarim kalmis .reg
dosyasi riski ve "reg.exe patladi mi yoksa anahtar yok muydu?" belirsizligi).

Python'da o bedelin tamami yok: `winreg` agaci kendi surecimizde geziyor,
yedek dogrudan sozluk olarak elimize geliyor. AHK planindaki toplu cmd.exe
zinciri, beklemeyi kritik yoldan cikarma, .reg metnini satir sayarak taban
uretme -- hepsi O SORUNUN cozumuydu, burada karsiliksiz. Kalan tek Win32
ihtiyaci `RegNotifyChangeKeyValue` (agac degisti mi?) ve `RegDeleteTreeW`.

DEGERLER TIPIYLE korunur: RecentDocs REG_BINARY, TypedPaths REG_SZ. Tip
kaybolursa Explorer kaydi okuyamaz -- geri yukleme, silmekten beter olur.
JSON'a yazilabilsin diye ikili degerler base64'e cevrilir (`_encode`).
"""

from __future__ import annotations

import base64
import ctypes
import logging
import winreg
from ctypes import wintypes
from typing import Any

from cascade.win32.structs import kernel32

log = logging.getLogger("cascade.incognito.reg")

advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

# "HKCU\Software\..." -> kok handle. RegOpenKeyEx yol dizesini degil kok
# HANDLE'i + alt yolu ister; AHK'deki `_splitKey` ile ayni tablo.
_ROOTS: dict[str, int] = {
    "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
    "HKCU": winreg.HKEY_CURRENT_USER,
    "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
    "HKLM": winreg.HKEY_LOCAL_MACHINE,
    "HKEY_CLASSES_ROOT": winreg.HKEY_CLASSES_ROOT,
    "HKCR": winreg.HKEY_CLASSES_ROOT,
    "HKEY_USERS": winreg.HKEY_USERS,
    "HKU": winreg.HKEY_USERS,
    "HKEY_CURRENT_CONFIG": winreg.HKEY_CURRENT_CONFIG,
    "HKCC": winreg.HKEY_CURRENT_CONFIG,
}

KEY_NOTIFY = 0x0010
# NAME | ATTRIBUTES | LAST_SET | SECURITY -- AHK ile ayni dortlu.
REG_NOTIFY_FILTER = 0x1 | 0x2 | 0x4 | 0x8

advapi32.RegOpenKeyExW.argtypes = [
    wintypes.HKEY,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.HKEY),
]
advapi32.RegOpenKeyExW.restype = wintypes.LONG
advapi32.RegCloseKey.argtypes = [wintypes.HKEY]
advapi32.RegCloseKey.restype = wintypes.LONG
advapi32.RegNotifyChangeKeyValue.argtypes = [
    wintypes.HKEY,
    wintypes.BOOL,
    wintypes.DWORD,
    wintypes.HANDLE,
    wintypes.BOOL,
]
advapi32.RegNotifyChangeKeyValue.restype = wintypes.LONG
advapi32.RegDeleteTreeW.argtypes = [wintypes.HKEY, wintypes.LPCWSTR]
advapi32.RegDeleteTreeW.restype = wintypes.LONG

kernel32.CreateEventW.argtypes = [
    wintypes.LPVOID,
    wintypes.BOOL,
    wintypes.BOOL,
    wintypes.LPCWSTR,
]
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


def split_key(path: str) -> tuple[int, str] | None:
    """`"HKCU\\Software\\X"` -> `(HKEY_CURRENT_USER, "Software\\X")`."""
    head, sep, sub = path.partition("\\")
    if not sep:
        return None
    root = _ROOTS.get(head.upper())
    if root is None:
        return None
    return root, sub


def key_exists(path: str) -> bool:
    """Anahtar VAR MI?

    Bos anahtar ile olmayan anahtari ayirmak `.absent` sozlesmesi icin sart
    (bkz. tracestore.RegStore.snapshot): sayim ikisinde de 0 doner.
    """
    parts = split_key(path)
    if parts is None:
        return False
    try:
        with winreg.OpenKey(parts[0], parts[1], 0, winreg.KEY_READ):
            return True
    except OSError:
        return False


# ---- deger kodlama (JSON'a yazilabilsin diye) ----


def _encode(value: Any) -> Any:
    """`winreg.QueryValueEx` cikisini JSON'a yazilabilir hale getirir.

    REG_BINARY / REG_NONE `bytes` doner; orjson bytes yazamaz -> base64.
    Sozluk sarmalayicisi tipi belirsiz birakmiyor: cozerken str mi b64 mi
    diye tahmin etmek gerekmiyor.
    """
    if isinstance(value, bytes):
        return {"b64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (list, tuple)):  # REG_MULTI_SZ
        return list(value)
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, dict) and "b64" in value:
        return base64.b64decode(value["b64"])
    return value


# ---- yedek / geri yukleme ----


def dump_key(path: str) -> dict[str, Any] | None:
    """Anahtari ozyinelemeli okur. Anahtar yoksa None (AHK: `.absent`).

    Bicim: `{"values": [[ad, tip, deger], ...], "keys": {ad: {...}, ...}}`

    Okunamayan tek bir alt anahtar yedegin tamamini dusurmez; atlanir ve
    log'a yazilir. Boyle bir yedekle geri yukleme yapmak, o dali "oturumda
    dogmus" sanip silmek olurdu -- bu yuzden atlanan dal restore'da da
    DOKUNULMADAN birakilir (bkz. restore_key: eksik dal silinmez).
    """
    parts = split_key(path)
    if parts is None:
        return None
    try:
        handle = winreg.OpenKey(parts[0], parts[1], 0, winreg.KEY_READ)
    except OSError:
        return None
    with handle:
        return _dump_open(handle, path)


def _dump_open(handle: Any, path: str) -> dict[str, Any]:
    n_keys, n_values, _ = winreg.QueryInfoKey(handle)

    values: list[list[Any]] = []
    for index in range(n_values):
        try:
            name, data, kind = winreg.EnumValue(handle, index)
        except OSError:
            log.warning("registry degeri okunamadi: %s [%d]", path, index)
            continue
        values.append([name, kind, _encode(data)])

    keys: dict[str, Any] = {}
    for index in range(n_keys):
        try:
            name = winreg.EnumKey(handle, index)
        except OSError:
            log.warning("registry alt anahtari okunamadi: %s [%d]", path, index)
            continue
        try:
            with winreg.OpenKey(handle, name, 0, winreg.KEY_READ) as sub:
                keys[name] = _dump_open(sub, f"{path}\\{name}")
        except OSError:
            log.warning("registry alt anahtari acilamadi: %s\\%s", path, name)
    return {"values": values, "keys": keys}


def restore_key(path: str, dump: dict[str, Any]) -> bool:
    """Yedegi geri yazar. ONCE `delete_tree` cagrilmali.

    AHK'de bu zorunluluk reg.exe'nin MERGE yapmasindan geliyordu; burada da
    ayni: yalnizca yazmak oturumda EKLENEN kayitlari yerinde birakir.
    """
    parts = split_key(path)
    if parts is None:
        return False
    try:
        handle = winreg.CreateKeyEx(parts[0], parts[1], 0, winreg.KEY_WRITE)
    except OSError:
        log.exception("registry anahtari olusturulamadi: %s", path)
        return False
    with handle:
        _restore_open(handle, dump, path)
    return True


def _restore_open(handle: Any, dump: dict[str, Any], path: str) -> None:
    for entry in dump.get("values", ()):
        try:
            name, kind, data = entry
            winreg.SetValueEx(handle, name, 0, kind, _decode(data))
        except (OSError, ValueError, TypeError):
            log.warning("registry degeri geri yazilamadi: %s\\%s", path, entry[:1])
    for name, sub_dump in dump.get("keys", {}).items():
        try:
            with winreg.CreateKeyEx(handle, name, 0, winreg.KEY_WRITE) as sub:
                _restore_open(sub, sub_dump, f"{path}\\{name}")
        except OSError:
            log.warning("registry alt anahtari geri yazilamadi: %s\\%s", path, name)


def delete_tree(path: str) -> bool:
    """Anahtari alt agaciyla siler. Anahtar zaten yoksa False.

    `winreg.DeleteKey` yalnizca BOS anahtari siliyor; ozyinelemeli silmeyi
    Python'da elle yazmak yerine `RegDeleteTreeW` tek cagrida yapiyor.
    O fonksiyon anahtarin KENDISINI birakiyor -> ardindan DeleteKey.
    """
    parts = split_key(path)
    if parts is None:
        return False
    root, sub = parts
    if advapi32.RegDeleteTreeW(wintypes.HKEY(root), sub) != 0:
        return False
    try:
        winreg.DeleteKey(root, sub)
    except OSError:
        # Agac bosaltildi ama kok silinemedi (baska surecte acik olabilir).
        # Icerik gittigi icin sonuc pratikte ayni; yalanci False donmeyelim.
        log.debug("kok anahtar silinemedi, icerigi bosaltildi: %s", path)
    return True


# ---- sayim (denetim icin) ----


def count_dump(dump: dict[str, Any]) -> int:
    """Yedekteki kayit sayisi. `count_key` ile BIREBIR ayni seyi saymali.

    Sayilan: koke ait degerler + her derinlikteki alt anahtar ve degerleri.
    Kokun kendisi sayilmaz -- AHK'deki `Loop Reg key, "KVR"` de saymiyordu.
    """
    total = len(dump.get("values", ()))
    for sub in dump.get("keys", {}).values():
        total += 1 + count_dump(sub)
    return total


def count_key(path: str) -> int:
    """Canli anahtardaki kayit sayisi. Anahtar yoksa 0."""
    parts = split_key(path)
    if parts is None:
        return 0
    try:
        handle = winreg.OpenKey(parts[0], parts[1], 0, winreg.KEY_READ)
    except OSError:
        return 0
    with handle:
        return _count_open(handle)


def _count_open(handle: Any) -> int:
    n_keys, n_values, _ = winreg.QueryInfoKey(handle)
    total = n_values
    for index in range(n_keys):
        try:
            name = winreg.EnumKey(handle, index)
            with winreg.OpenKey(handle, name, 0, winreg.KEY_READ) as sub:
                total += 1 + _count_open(sub)
        except OSError:
            total += 1
    return total


# ---- sayisal alt anahtarlar (RegDeltaStore) ----


def numeric_subkeys(path: str) -> list[int]:
    """Yalniz tamamen rakamdan olusan alt anahtar adlari, sayi olarak."""
    parts = split_key(path)
    if parts is None:
        return []
    try:
        handle = winreg.OpenKey(parts[0], parts[1], 0, winreg.KEY_READ)
    except OSError:
        return []
    found: list[int] = []
    with handle:
        n_keys, _, _ = winreg.QueryInfoKey(handle)
        for index in range(n_keys):
            try:
                name = winreg.EnumKey(handle, index)
            except OSError:
                continue
            if name.isdigit():
                found.append(int(name))
    return found


def delete_subkeys_above(path: str, high_water: int) -> int:
    """`high_water`in USTUNDEKI sayisal alt anahtarlari siler.

    Numaralandirirken silmek guvensiz (enumerator kayar) -> once topla,
    sonra sil. AHK `_deleteAbove` ile ayni.
    """
    victims = [n for n in numeric_subkeys(path) if n > high_water]
    removed = 0
    for name in victims:
        if delete_tree(f"{path}\\{name}"):
            removed += 1
    return removed


# ---- tekil deger islemleri (PolicyGuard) ----


def read_dword(path: str, name: str) -> int | None:
    parts = split_key(path)
    if parts is None:
        return None
    try:
        with winreg.OpenKey(parts[0], parts[1], 0, winreg.KEY_READ) as handle:
            data, kind = winreg.QueryValueEx(handle, name)
    except OSError:
        return None
    if kind != winreg.REG_DWORD:
        return None
    return int(data)


def write_dword(path: str, name: str, data: int) -> bool:
    parts = split_key(path)
    if parts is None:
        return False
    try:
        with winreg.CreateKeyEx(parts[0], parts[1], 0, winreg.KEY_WRITE) as handle:
            winreg.SetValueEx(handle, name, 0, winreg.REG_DWORD, int(data))
        return True
    except OSError:
        log.warning("registry DWORD yazilamadi: %s\\%s", path, name)
        return False


def delete_value(path: str, name: str) -> bool:
    parts = split_key(path)
    if parts is None:
        return False
    try:
        with winreg.OpenKey(parts[0], parts[1], 0, winreg.KEY_SET_VALUE) as handle:
            winreg.DeleteValue(handle, name)
        return True
    except OSError:
        return False


# ---- degisiklik gozcusu ----


class KeyWatcher:
    """ "Bu agaca oturum boyunca hic dokunuldu mu?" sorusunu ucuza cevaplar.

    Cekirdegin alt-agac bildirimi (`RegNotifyChangeKeyValue`): `start()`
    anahtar basina bir event kurar (maliyet ~0), `has_changed()` 0 timeout'lu
    `WaitForSingleObject` ile sorar. Dokunulmamis depoda sil + geri yaz
    TAMAMEN atlanir; sonuc birebir ayni, disable() neredeyse bedava.

    TEK YONLU: yalniz is ATLAR, asla EKSILTMEZ. Gozcu kurulamazsa da,
    program yeniden baslarsa da `has_changed()` True doner ve tam yol isler
    -- atlamak POZITIF kanit ister.

    SIRALAMA SART: gozcu YEDEKTEN ONCE kurulur. Yedek alinirken dusen bir iz
    yedege karisirsa depo "degismis" sayilsin.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._key: int = 0
        self._event: int = 0

    def start(self) -> None:
        self.stop()
        parts = split_key(self.path)
        if parts is None:
            return
        handle = wintypes.HKEY()
        if (
            advapi32.RegOpenKeyExW(
                wintypes.HKEY(parts[0]), parts[1], 0, KEY_NOTIFY, ctypes.byref(handle)
            )
            != 0
        ):
            return  # anahtar yok -> gozcusuz; has_changed() True kalir
        event = kernel32.CreateEventW(None, True, False, None)
        if not event:
            advapi32.RegCloseKey(handle)
            return
        # bWatchSubtree=1, fAsynchronous=1 -> ayri thread gerekmez, cekirdek
        # biz mesgulken bile event'i sinyaller.
        if advapi32.RegNotifyChangeKeyValue(handle, True, REG_NOTIFY_FILTER, event, True) != 0:
            kernel32.CloseHandle(event)
            advapi32.RegCloseKey(handle)
            return
        self._key = handle.value or 0
        self._event = event

    def has_changed(self) -> bool:
        """Event bir kez sinyallenir ve oyle kalir; "en az bir degisiklik
        oldu mu?" bize yettigi icin yeniden kurmaya gerek yok."""
        if not self._event:
            return True  # kanit yok -> degismis say
        return kernel32.WaitForSingleObject(wintypes.HANDLE(self._event), 0) == 0

    def stop(self) -> None:
        """Silmeden ONCE cagrilmali: silinecek anahtarin uzerinde acik
        KEY_NOTIFY handle'i kalmasin."""
        if self._event:
            kernel32.CloseHandle(wintypes.HANDLE(self._event))
            self._event = 0
        if self._key:
            advapi32.RegCloseKey(wintypes.HKEY(self._key))
            self._key = 0
