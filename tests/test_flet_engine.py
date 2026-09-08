"""Flet motorunun Qt ile bir arada calismasini saglayan iki global ayar.

Ikisi de Flet'in ICINDEKI davranisa dokunuyor, yani bir Flet surumu
yukseltmesinde SESSIZCE bozulabilirler: program calismaya devam eder, hata
vermez, yalnizca eski dert geri gelir. Bu yuzden test edilmeleri gerekiyor
-- dogruladiklari sey "pencere acildi mi" degil, iki motorun bir arada
kalma sarti.

    signal yamasi         Flet ana thread'de olmadigi icin SIGINT
                          kaydedemiyor; yamasiz Flet pencereyi ACMADAN
                          dusuyor.
    otomatik guncelleme   Flet her olaydan sonra tum sayfayi yeniden
                          ciziyordu; log penceresi bu yuzden kapatma
                          dugmesine yanit vermez olmustu.

Ekran ya da `flet.exe` gerekmiyor: ikisi de surec genelinde birer bayrak.
"""

from __future__ import annotations

import asyncio
import threading

import flet as ft

from keypilot.fui.engine import FletEngine, _disable_auto_update, _install_signal_shim


def test_otomatik_guncelleme_kapaniyor():
    _disable_auto_update()
    assert ft.context.auto_update_enabled() is False


def test_kapali_bayrak_OLAY_baglamina_KOPYALANIYOR():
    """ASIL sart bu. Flet her olay isleyicisinden once `reset_auto_update`
    cagiriyor; bayrak oraya kopyalanmazsa kapatmis olmak ise yaramaz."""
    _disable_auto_update()
    ft.context.reset_auto_update()
    assert ft.context.auto_update_enabled() is False


def test_bayrak_FLET_THREADINE_ve_olay_gorevine_geciyor():
    """Gercek yerlesim: ayar ANA thread'de yapiliyor, olaylar Flet
    thread'indeki bir asyncio gorevinde kosuyor."""
    _disable_auto_update()
    goruldu: dict[str, bool] = {}

    def flet_thread() -> None:
        async def oturum() -> None:
            ft.context.reset_auto_update()  # flet/app.py on_session_created

            async def olay() -> bool:
                ft.context.reset_auto_update()  # base_control._trigger_event
                return ft.context.auto_update_enabled()

            goruldu["olay"] = await asyncio.create_task(olay())

        asyncio.run(oturum())

    thread = threading.Thread(target=flet_thread)
    thread.start()
    thread.join()
    assert goruldu["olay"] is False


def test_signal_yamasi_ARKA_threadde_patlamiyor():
    """Yamasiz hali `ValueError: signal only works in main thread` atiyor
    ve Flet daha pencereyi acmadan dusuyordu."""
    import signal

    _install_signal_shim()
    hata: list[BaseException] = []

    def arka() -> None:
        try:
            signal.signal(signal.SIGINT, signal.SIG_DFL)
        except BaseException as error:  # noqa: BLE001
            hata.append(error)

    thread = threading.Thread(target=arka)
    thread.start()
    thread.join()
    assert hata == []


def test_ask_qt_isi_ANA_threadde_kosturuyor(qapp):
    """`ask_qt` Flet thread'inden cagrilir ama is Qt'nin ana thread'inde
    kosmali: pano ve dosya kutusu oraya ait."""
    motor = FletEngine(lambda page: None)
    kosan: list[str] = []

    def is_() -> None:
        kosan.append(threading.current_thread().name)

    thread = threading.Thread(target=lambda: motor.ask_qt(is_), name="sahte-flet")
    thread.start()
    thread.join()

    # Kuyruga alinan sinyal ana thread olay dongusu donunce kosar.
    assert kosan == []
    qapp.processEvents()
    assert kosan == [threading.main_thread().name]
