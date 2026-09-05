"""Gelistirme ayarlari -- gunluk kullanimda KAPALI duran mekanizmalar.

Buradaki her sey "programin isini yapmasi" degil, "programi incelemek"
icin. Ayri bir dosyada durmalarinin sebebi tek: dagilmasinlar. Bir tanisi
mekanizma sinsice birikiyor -- bir nobetci, bir ayrinti log'u, bir sayac
-- ve hicbiri tek basina buyuk gorunmedigi icin kimse toplamini sormuyor.
Toplami burada, tek ekranda ve varsayilan olarak KAPALI.

    dev.enabled          ANA SALTER -- kapaliyken asagidakiler yok sayilir
    dev.hookWatchdogMs   hook nobetcisi: 0 = kapali, >0 = yoklama araligi
    log.fileInfo         log dosyasina INFO da yaz (tanimi logs.py'de)

ANA SALTER NASIL CALISIR: tek tek ayarlarin degerine BAKILMAZ, once
`enabled()` sorulur. Yani "gelistirme modunu kapat" tek hamlede hepsini
susturuyor ve kapatirken kimsenin ayrica hangi alt ayarin acik kaldigini
hatirlamasi gerekmiyor. Alt ayarlarin degeri korunuyor: modu tekrar
acinca birakildigi gibi geri geliyor.

YENI BIR GELISTIRME MEKANIZMASI EKLERKEN: ayari buraya koy, kodun icinde
`if dev.enabled() and ...` diye degil, buradaki kucuk yardimci
fonksiyonlardan biri uzerinden sor (`hook_watchdog_ms()` gibi). Salter
mantigi tek yerde kalsin.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from keypilot.settings import Category, setting

#: Komut satiri bayraklari ve ortam degiskeni -- TEK CALISMA icin zorlama.
#:
#: Neden var: gelistirme modu KULLANICININ ayari ve `settings.json`'a
#: yaziliyor. Bir deneme yapmak icin onu acip kapatmak kullanicinin
#: dosyasini kurcalamak demek -- bir de kapatmayi unutmak var. Bayrak
#: hicbir yere yazilmiyor, yalnizca O SURECI baglar.
#:
#: GRAMER -- bayragin VARLIGI acar, ayrinti anahtar=deger ile verilir:
#:
#:     --dev                     gelistirme modu acik
#:     --dev hook=300            acik + nobetci 300 ms
#:     --dev hook=0              acik ama nobetci kapali
#:     set KEYPILOT_DEV=hook=300  ayni anahtarlar, ortam degiskeniyle
#:                               (degiskenin VARLIGI zaten "acik" demek)
#:
#: KAPATMA BAYRAGI YOK: kapatmak icin bayragi yazmamak yeter. "acik/kapali/
#: on/off" gibi serbest metin de yok -- bir kelimeyi yanlis yazmak sessizce
#: yanlis moda dusururdu.
ENV_VAR = "KEYPILOT_DEV"
FLAG = "--dev"

#: Nobetci araliginin alt siniri. Daha sik yoklamanin anlami yok: olcut
#: zaten 3 saniyelik bir farka bakiyor (win32/hook.WATCHDOG_GAP_MS).
MIN_WATCHDOG_MS = 500
MAX_WATCHDOG_MS = 60_000

DEV_MODE = setting(
    "dev.enabled",
    "GELISTIRME MODU´´",
    default=False,
    category=Category.DEVELOPMENT,
    tags="gelistirme development hata ayiklama debug tani",
    desc=(
        "Bu bolumdeki butun gelistirme mekanizmalarinin ana salteri. Kapaliyken "
        "asagidaki ayarlarin degeri ne olursa olsun hicbiri calismaz -- program "
        "yalnizca kendi isini yapar. Acinca alt ayarlar birakildigi yerden "
        "devam eder."
    ),
)

HOOK_WATCHDOG_MS = setting(
    "dev.hookWatchdogMs",
    "Hook nobetcisi (ms, 0 = kapali)",
    default=0,
    category=Category.DEVELOPMENT,
    tags="hook nobetci watchdog tus calismiyor kurtarma",
    desc=(
        "Windows, dusuk seviye tus kancasini SESSIZCE zincirden cikarabiliyor "
        "(callback 300 ms'yi asarsa). O andan sonra program ayakta gorunur ama "
        "hicbir tus calismaz. Nobetci bunu dolayli olarak sezip kancayi yeniden "
        "kurar: 'sistem girdi gordu ama biz gormedik' der.\n\n"
        "0 = kapali. Acmak icin yoklama araligini ms olarak yaz (2000 iyi bir "
        "baslangic). DIKKAT: kapaliyken dusen bir kanca kendiliginden geri "
        "gelmez; tuslar sessizce olur ve programi yeniden baslatmak gerekir."
    ),
    validate=lambda value: (
        ""
        if value == 0 or MIN_WATCHDOG_MS <= value <= MAX_WATCHDOG_MS
        else f"0 (kapali) ya da {MIN_WATCHDOG_MS}-{MAX_WATCHDOG_MS} ms olmali"
    ),
)


@dataclass(frozen=True, slots=True)
class Override:
    """Bayragin/ortam degiskeninin soyledigi sey. `mode is None` = zorlama yok."""

    mode: bool | None = None
    hook_ms: int | None = None
    #: Anlasilmayan anahtarlar -- acilista log'a yaziliyor. Sessizce yutmak,
    #: "hook=300 yazdim ama nobetci calismadi"yi bes dakika arattirir.
    problems: tuple[str, ...] = ()
    #: Zorlamayi kim soyledi -- log satirinda gorunuyor.
    source: str = ""


def _options(tokens: list[str], source: str) -> Override:
    """`hook=300` gibi parcalari cozer. Deger tirnakli gelebilir (kabuk
    tirnagi yemediyse) -- kirpiliyor."""
    hook_ms: int | None = None
    problems: list[str] = []
    for token in tokens:
        key, sep, value = token.partition("=")
        key = key.strip().lower()
        value = value.strip().strip('"').strip("'")
        if not sep:
            problems.append(f"{token!r}: anahtar=deger bekleniyordu")
            continue
        if key == "hook":
            if not value.isdigit():
                problems.append(f"hook={value!r}: ms cinsinden sayi olmali")
                continue
            hook_ms = int(value)
        else:
            problems.append(f"{key!r}: bilinmeyen anahtar (hook)")
    return Override(mode=True, hook_ms=hook_ms, problems=tuple(problems), source=source)


def _from_argv() -> Override | None:
    """`--dev [anahtar=deger ...]` (yoksa bu kanalda zorlama yok).

    Bayragin ARDINDAN gelen anahtar=deger parcalari ona aittir; baska bir
    bayrak (`-` ile baslayan) gorulunce duruluyor. Boylece `--dev hook=300
    --supervised` dogru bolunuyor.
    """
    argv = sys.argv[1:]
    if FLAG not in argv:
        return None
    rest = argv[argv.index(FLAG) + 1 :]
    tokens: list[str] = []
    for token in rest:
        if token.startswith("-"):
            break
        tokens.append(token)
    return _options(tokens, FLAG)


def _from_env() -> Override | None:
    """Degiskenin VARLIGI "acik" demek; icerigi anahtar=deger parcalari."""
    raw = os.environ.get(ENV_VAR)
    if raw is None:
        return None
    return _options(raw.split(), ENV_VAR)


def _override() -> Override:
    """Komut satiri ortam degiskenini yener."""
    return _from_argv() or _from_env() or Override()


#: Surec basinda BIR KEZ okunuyor: sonradan degisen bir ortam degiskeni
#: programin ortasinda modu degistirmesin.
OVERRIDE = _override()


def argv_flags() -> list[str]:
    """Komut satirindaki `--dev ...` parcalarinin tamami ([] = yok).

    Yeniden baslatma cocuga AYNEN gecirsin diye var: gozetmen altinda
    bayrak zaten korunuyor (o kendi argumanlarini her seferinde veriyor),
    ama gozetmensiz yolda (VSCode F5) cocuk bayraksiz kalir ve "reload
    ettim, gelistirme modu kapandi" olurdu.
    """
    argv = sys.argv[1:]
    if FLAG not in argv:
        return []
    flags = [FLAG]
    for token in argv[argv.index(FLAG) + 1 :]:
        if token.startswith("-"):
            break
        flags.append(token)
    return flags


def problems() -> tuple[str, ...]:
    """Anlasilmayan bayrak parcalari -- acilista UYARI olarak yaziliyor.

    Yanlis yazilan bir anahtar etkisiz kaliyor (dogrusu bu: yazim hatasi
    modu sessizce cevirmemeli) ama SESSIZ kalmamali; "bayragi verdim,
    hicbir sey olmadi" en can sikici hata turu.
    """
    return OVERRIDE.problems


def override_note() -> str:
    """Zorlama varsa tek satirlik ozeti ("" = zorlama yok).

    Acilista log'a yaziliyor: mod ayar ekraninda KAPALI gorunurken acik
    olabiliyor ve bunun ekranda bir izi olmali (tepside mor halka, log'da
    bu satir).
    """
    if OVERRIDE.mode is None:
        return ""
    parts = [f"{OVERRIDE.source} -> acik"]
    if OVERRIDE.hook_ms is not None:
        parts.append(f"nobetci {OVERRIDE.hook_ms} ms")
    # Anlasilmayan parcalar BURADA DEGIL: onlar `problems()` uzerinden ayri
    # birer UYARI olarak yaziliyor (tepsi rozeti de yansin).
    return ", ".join(parts)


def _on_mode_change(_value, _old) -> None:
    """Ana salter degisti: degeri degismeyen ama gecerliligi degisen
    ayarlarin sahiplerine haber ver."""
    from keypilot import logs

    logs.refresh_dev_switches()


DEV_MODE.subscribe(_on_mode_change)


def enabled() -> bool:
    """Gelistirme modu acik mi -- alt ayarlarin hepsi buna bagli.

    Komut satiri/ortam zorlamasi AYARI YENER ve hicbir yere yazilmaz:
    o calisma bitince kullanicinin ayari oldugu gibi duruyor.
    """
    if OVERRIDE.mode is not None:
        return OVERRIDE.mode
    return bool(DEV_MODE.get())


def hook_watchdog_ms() -> int:
    """Nobetci yoklama araligi; 0 = nobetci calismasin.

    Ana salter kapaliyken alt ayarin degerine BAKILMIYOR: "gelistirme modu
    kapali ama nobetci nedense caliyor" diye bir hal olmasin.
    """
    if not enabled():
        return 0
    if OVERRIDE.hook_ms is not None:
        return OVERRIDE.hook_ms
    return int(HOOK_WATCHDOG_MS.get())


def file_info() -> bool:
    """Log dosyasina INFO da yazilsin mi (tanimi logs.FILE_INFO).

    Ayar logs.py'de duruyor -- oradaki `setup` ondan once kosuyor ve
    import dongusu olmasin. Salteri burada sorulmasinin sebebi tek yerde
    toplanmasi.
    """
    from keypilot.logs import FILE_INFO

    return enabled() and bool(FILE_INFO.get())
