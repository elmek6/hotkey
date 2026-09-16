"""Jest overlay gorunurlugu -- yon kilidi ve P/S asamasi."""

from keypilot.ui.gesture_overlay import GestureOverlay


def test_kayitsiz_yon_gizli(qapp):
    overlay = GestureOverlay()
    overlay.begin("", {"U": "Zoom+", "D": "Zoom-"})
    assert overlay._tiles["U"].isVisible()
    assert overlay._tiles["D"].isVisible()
    assert not overlay._tiles["L"].isVisible()
    assert not overlay._tiles["R"].isVisible()
    overlay.close()


def test_p_ilk_anda_yanmaz_s_buyur(qapp):
    overlay = GestureOverlay()
    overlay.begin("", {"L": "Del"})
    assert overlay._tiles["P"].isVisible()
    assert overlay._tiles["S"].isVisible()
    assert overlay._tiles["P"].styleSheet().find(GestureOverlay.ACTIVE_BG) < 0
    overlay.update_state("P", "")
    assert overlay._tiles["P"].styleSheet().find(GestureOverlay.ACTIVE_BG) >= 0
    overlay.update_state("S", "")
    assert not overlay._tiles["P"].isVisible()
    assert overlay._tiles["S"].isVisible()
    assert overlay._s_span
    overlay.close()


def test_jest_baslayinca_s_soener_karsi_eksen_gizlenir(qapp):
    overlay = GestureOverlay()
    overlay.begin("", {"U": "Zoom+", "D": "Zoom-", "L": "Vol -", "R": "Vol +"})
    overlay.update_state("S", "")
    overlay.update_state("", "L", counts={"L": "+1"})
    assert not overlay._tiles["S"].isVisible()
    assert not overlay._tiles["P"].isVisible()
    assert overlay._tiles["L"].isVisible()
    assert overlay._tiles["R"].isVisible()
    assert not overlay._tiles["U"].isVisible()
    assert not overlay._tiles["D"].isVisible()
    overlay.close()


def test_sifir_sure_tus_birakilana_kadar_kalir(qapp):
    """ACTIVE_SECONDS=0: zamanlayici baslamaz, hide gelene kadar acik kalir."""
    overlay = GestureOverlay()
    assert GestureOverlay.ACTIVE_SECONDS == 0
    overlay.begin("", {"L": "Del"})
    assert overlay.isVisible()
    assert not overlay._timeout.isActive()
    overlay.close()
