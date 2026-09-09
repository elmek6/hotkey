"""Beni oldurebilecek bir job'in icinde miyim? -- "program neden izsiz kayboldu"
sorusunun tek dogrudan olcumu.

Windows'ta bir surec bir JOB nesnesine bagli olabilir. Job'in
KILL_ON_JOB_CLOSE bayragi acikken job kapanir kapanmaz icindeki HER surec
TerminateProcess ile olur: `on_exit` kosmaz, konsol denetleyicisi kosmaz,
sinyal gelmez, gozetmen de ayni anda oldugu icin cokme kutusu bile
cikmaz. Geriye tek satir kalmaz -- 08.09'da yasanan tam olarak buydu
(bkz. Files/log.txt: 13:53'te acilis, sonra hicbir sey).

VS Code'un entegre terminali ve F5 (debugpy) cocuklarini boyle bir job'a
koyuyor. Pencere kapaninca job kapanir ve terminalden baslatilmis KeyPilot
-- arada wscript ve cmd olsa bile, job MIRAS ALINIR -- birlikte olur.

Job UYELIGI disaridan sorulabiliyor (IsProcessInJob) ama BAYRAKLAR
sorulamiyor: QueryInformationJobObject bir job tutamaci ister ve baskasinin
job'ini acmanin yolu yok. Bu yuzden olcum sureci KENDISI yapmali; sonda da
bunun icin var. Nerede calistirdiysan onun cevabini verir:

    VS Code entegre terminalinde  -> KeyPilot'u oradan baslatmak guvenli mi
    F5 / dogrudan pencerede       -> ayni soru, o yol icin

Calistir:  uv run python -m probes.job
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from keypilot.win32.structs import kernel32

#: QueryInformationJobObject bilgi sinifi: JobObjectExtendedLimitInformation.
JOB_EXTENDED_LIMIT = 9

#: LimitFlags bitleri -- yalnizca "kim beni oldurur" sorusuna bakanlar.
FLAGS = {
    0x00002000: ("KILL_ON_JOB_CLOSE", "job kapaninda OLDURULURUM"),
    0x00000800: ("BREAKAWAY_OK", "cocuk job'dan cikabilir (bayrakla)"),
    0x00001000: ("SILENT_BREAKAWAY_OK", "cocuk job'a HIC girmez"),
    0x00000400: ("DIE_ON_UNHANDLED_EXCEPTION", "yakalanmamis hatada susarak olurum"),
}


class IoCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_ulonglong)
        for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
        )
    ]


class BasicLimit(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class ExtendedLimit(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", BasicLimit),
        ("IoInfo", IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def in_job() -> bool:
    """Bu surec herhangi bir job'a bagli mi. (Win11'de bagli olmak TEK
    BASINA kotu haber degil: kap, Defender ve kabuklar da job kullaniyor.)"""
    flag = wintypes.BOOL()
    kernel32.IsProcessInJob(kernel32.GetCurrentProcess(), None, ctypes.byref(flag))
    return bool(flag.value)


def limit_flags() -> int | None:
    """Icinde bulundugum job'in LimitFlags'i. None = okunamadi."""
    info = ExtendedLimit()
    written = wintypes.DWORD()
    ok = kernel32.QueryInformationJobObject(
        None, JOB_EXTENDED_LIMIT, ctypes.byref(info), ctypes.sizeof(info),
        ctypes.byref(written),
    )
    if not ok:
        return None
    return int(info.BasicLimitInformation.LimitFlags)


def main() -> int:
    print(f"pid {os.getpid()}")
    if not in_job():
        print("job icinde DEGILIM -- buradan baslatilan KeyPilot, beni "
              "baslatan pencere kapaninca olmez.")
        return 0

    flags = limit_flags()
    if flags is None:
        print(f"job icindeyim ama bayraklar okunamadi (hata "
              f"{ctypes.get_last_error()})")
        return 1

    print(f"job icindeyim, LimitFlags = 0x{flags:08x}")
    for bit, (name, what) in FLAGS.items():
        mark = "ACIK " if flags & bit else "kapali"
        print(f"  {mark}  {name:<28} {what}")

    kill = bool(flags & 0x00002000)
    silent = bool(flags & 0x00001000)
    print()
    if kill and not silent:
        print("SONUC: KeyPilot'u BURADAN baslatma. Bu pencere kapandigi an "
              "wscript, cmd ve python birlikte oldurulur; log'a tek satir "
              "dusmez.")
    elif kill and silent:
        print("SONUC: job oldurucu ama cocuklar job'a girmiyor (SILENT_"
              "BREAKAWAY) -- buradan baslatilan KeyPilot kurtulur.")
    else:
        print("SONUC: job kapanisi oldurmuyor; buradan baslatmak guvenli.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
