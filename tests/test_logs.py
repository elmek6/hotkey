"""Hata deposu -- error_handler.ahk'nin lastFullError / getRecentErrors'u."""

import logging

from keypilot import logs
from keypilot.logs import ErrorStore, recent_text


def test_uyari_ve_ustu_toplanir():
    store = ErrorStore()
    logger = logging.getLogger("test.keypilot.store")
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    logger.addHandler(store)
    try:
        logger.info("bu girmez")
        logger.warning("dikkat")
        logger.error("patladi")
    finally:
        logger.removeHandler(store)

    assert len(store) == 2
    assert store.last.text == "patladi"
    assert store.last.level == "ERROR"


def test_exception_izi_metne_girer():
    store = ErrorStore()
    logger = logging.getLogger("test.keypilot.exc")
    logger.propagate = False
    logger.addHandler(store)
    try:
        raise ValueError("ornek")
    except ValueError:
        logger.exception("eylem hatasi")
    finally:
        logger.removeHandler(store)

    assert "ValueError: ornek" in store.last.text


def test_limit_asilinca_eskiler_duser():
    store = ErrorStore(limit=3)
    for index in range(5):
        store.add("ERROR", f"hata {index}")
    assert len(store) == 3
    assert store.last.text == "hata 4"


def test_bos_depo_none_doner():
    assert ErrorStore().last is None


def test_recent_text_bos_durumda_da_calisir():
    """Menu her zaman bir sey gostermeli, bos liste patlamamali."""
    assert isinstance(recent_text(5), str)


def test_lifecycle_satiri_FILE_INFO_kapaliyken_de_dosyaya_gecer():
    """Kapanis nedeni log'da kalmali.

    FILE_INFO kapaliyken dosyaya yalnizca WARNING+ dusuyordu; "kapaniyor /
    yeniden baslatiliyor" satirlarinin hepsi INFO. Program kapandiktan sonra
    NEDEN kapandigi hicbir yerde yazmiyordu.
    """
    logs._file_info = False
    duz = logging.LogRecord("keypilot", logging.INFO, __file__, 1, "duz", None, None)
    assert not logs._file_filter(duz)

    isaretli = logging.LogRecord(
        "keypilot", logging.INFO, __file__, 1, "kapaniyor", None, None
    )
    setattr(isaretli, logs.ALWAYS, True)
    assert logs._file_filter(isaretli)


def test_FILE_INFO_acikken_her_INFO_gecer():
    logs._file_info = True
    try:
        duz = logging.LogRecord("keypilot", logging.INFO, __file__, 1, "duz", None, None)
        assert logs._file_filter(duz)
    finally:
        logs._file_info = False
