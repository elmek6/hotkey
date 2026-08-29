"""Hata deposu -- error_handler.ahk'nin lastFullError / getRecentErrors'u."""

import logging

from cascade.logs import ErrorStore, recent_text


def test_uyari_ve_ustu_toplanir():
    store = ErrorStore()
    logger = logging.getLogger("test.cascade.store")
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
    logger = logging.getLogger("test.cascade.exc")
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
