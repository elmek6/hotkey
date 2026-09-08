"""Log dosyasinin bicimi, ayristirilmasi ve log penceresi.

Eskiden hatalar `QMessageBox` icinde 15 tam traceback olarak gosteriliyordu:
kutu icerige gore buyuyup ekrani asiyor, kapatma dugmesi disarida
kaliyordu. Yerine kronolojik liste geldi; traceback ait oldugu satirin
ALTINDA acilip kapaniyor (sabit alt panel degil).

DOSYA BICIMI (kullanicinin karari):

    @2026-09-07 16:12:46 🔵 MainThread   keypilot: KeyPilot basladi
    @2026-09-07 16:13:01 🟡 MainThread   keypilot.app: cift tiklama yutuldu
    !Traceback (most recent call last):
      ValueError: ornek

Her kayit `@` ile, detay blogunun ilk satiri `!` ile baslar. Detayin geri
kalanina dokunulmaz. Seviye ADI degil renkli simge yazilir.
"""

from __future__ import annotations

import logging

from keypilot import logs

BICIM = f"{logs.MARK_RECORD}%(asctime)s %(icon)s %(threadName)-14s %(name)s: %(message)s"

#: Bicimden ONCE yazilmis dosya: `@` yok, seviye kelimeyle, traceback duz.
ESKI = (
    "2026-09-04 13:19:40 INFO    MainThread     cascade: cascade basladi\n"
    "2026-09-07 16:08:20 ERROR   keypilot-mag   keypilot.magnifier: buyutec baslatilamadi\n"
    "Traceback (most recent call last):\n"
    '  File "magnifier.py", line 213, in _ensure_running\n'
    "OSError: [WinError 740] elevation\n"
)

YENI = (
    "@2026-09-07 16:12:46 🔵 MainThread     keypilot: KeyPilot basladi\n"
    "@2026-09-07 16:12:50 🔵 MainThread     keypilot: ayrinti\n"
    "@2026-09-07 16:13:01 🟡 MainThread     keypilot.app: cift tiklama yutuldu\n"
    "!Traceback (most recent call last):\n"
    "  ValueError: ornek\n"
)


# ---- ayristirma ----


def test_ESKI_bicim_de_okunur():
    """Bicim degisti diye gecmis log okunamaz olmamali."""
    rows = logs.parse_log_text(ESKI)
    assert len(rows) == 2
    assert rows[0].message == "cascade basladi"
    assert rows[0].level == "INFO"
    assert rows[1].source == "keypilot.magnifier"
    assert rows[1].thread == "keypilot-mag"


def test_traceback_kayda_DETAY_olarak_baglanir():
    """Asil dert buydu: ozet ile detay ayni metne yapisikti."""
    rows = logs.parse_log_text(ESKI)
    assert rows[1].message == "buyutec baslatilamadi"
    assert "WinError 740" in rows[1].detail
    assert "WinError 740" not in rows[1].message


def test_yeni_bicim_okunur_simge_ADA_cevrilir():
    rows = logs.parse_log_text(YENI)
    assert [row.level for row in rows] == ["INFO", "INFO", "WARNING"]
    assert rows[2].when == "2026-09-07 16:13:01"
    assert rows[2].icon == "🟡"
    assert rows[2].detail.splitlines() == [
        "Traceback (most recent call last):",
        "  ValueError: ornek",
    ]  # yalniz `!` soyuluyor, girinti oldugu gibi kaliyor


def test_DETAY_isareti_blogun_BASINDA():
    """`!` detayin ilk satirinda: "burada blok basliyor" pesin belli olsun."""
    rows = logs.parse_log_text(YENI)
    assert len(rows) == 3
    assert rows[2].detail  # `!` satiri detay tasiyor
    assert not rows[0].detail
    assert not rows[2].detail.startswith(logs.MARK_DETAIL)  # isaret soyulmus


def test_dosyanin_ORTASINDAN_baslayan_detay_atilmaz():
    """Rotasyon dosyayi traceback'in ortasindan kesebiliyor."""
    rows = logs.parse_log_text("  File 'x.py', line 1\nValueError: kirik\n")
    assert len(rows) == 1
    assert "ValueError: kirik" in rows[0].detail


def test_bos_dosya_bos_liste():
    assert logs.parse_log_text("") == ()


def test_okunamayan_dosya_patlamaz(tmp_path):
    assert logs.read_log(tmp_path / "yok.txt") == ()


def test_limit_son_kayitlari_verir(tmp_path):
    path = tmp_path / "log.txt"
    path.write_text(YENI, encoding="utf-8")
    rows = logs.read_log(path, limit=1)
    assert len(rows) == 1
    assert rows[0].level == "WARNING"


def test_clear_log_dosyayi_bosaltir_SILMEZ(tmp_path):
    """Handler dosya tutamacini elinde tutuyor; silmek onu kor birakirdi."""
    path = tmp_path / "log.txt"
    path.write_text(YENI, encoding="utf-8")
    assert logs.clear_log(path) is True
    assert path.exists()
    assert path.read_text(encoding="utf-8") == ""


# ---- yazan taraf ----


def _bicimle(record: logging.LogRecord) -> str:
    return logs.MarkFormatter(BICIM, datefmt="%Y-%m-%d %H:%M:%S").format(record)


def _kayit(level: int, message: str) -> logging.LogRecord:
    return logging.LogRecord("keypilot", level, __file__, 1, message, None, None)


def test_HER_kayit_isaretle_baslar():
    """Isaret yalniz hatalarda degil: "isaretle basliyorsa yeni kayit"."""
    for level in (logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL):
        assert _bicimle(_kayit(level, "satir")).startswith(logs.MARK_RECORD)


def test_seviye_ADI_yerine_renkli_simge_yazilir():
    assert " 🔵 " in _bicimle(_kayit(logging.INFO, "duz"))
    assert " 🟡 " in _bicimle(_kayit(logging.WARNING, "dikkat"))
    assert " 🔴 " in _bicimle(_kayit(logging.ERROR, "patladi"))
    assert " 💥 " in _bicimle(_kayit(logging.CRITICAL, "coktu"))
    assert "INFO" not in _bicimle(_kayit(logging.INFO, "duz"))


def test_tek_satirlik_kayit_DUZ_isaret_alir():
    """`!` yalnizca detayi olan kayda ait."""
    assert _bicimle(_kayit(logging.INFO, "duz")).startswith(logs.MARK_RECORD)


def _hatali_kayit() -> logging.LogRecord:
    import sys

    try:
        raise ValueError("ornek")
    except ValueError:
        return logging.LogRecord(
            "keypilot", logging.ERROR, __file__, 1, "patladi", None, sys.exc_info()
        )


def test_DETAY_blogunun_ilk_satiri_unlemle_baslar():
    lines = _bicimle(_hatali_kayit()).splitlines()
    assert lines[0].startswith(logs.MARK_RECORD)  # kayit satiri
    assert lines[1].startswith(logs.MARK_DETAIL)  # detay blogu basliyor
    # traceback'in KENDI girintisine dokunulmuyor
    assert lines[2].startswith("  File ")


def test_yazdigimizi_geri_okuyabiliyoruz():
    """Bicim ile ayristirici ayni dosyada, ayni anda bozulmasinlar."""
    rows = logs.parse_log_text(_bicimle(_hatali_kayit()))
    assert len(rows) == 1
    assert rows[0].level == "ERROR"
    assert rows[0].message == "patladi"
    assert "ValueError: ornek" in rows[0].detail


def test_panoya_kopyalanan_metin_dosya_bicimiyle_ayni():
    kaynak = logs.parse_log_text(YENI)[2]
    geri = logs.parse_log_text(kaynak.text)
    assert len(geri) == 1
    assert geri[0].message == kaynak.message
    assert geri[0].detail == kaynak.detail
    assert geri[0].level == kaynak.level


# ---- pencere ----


def _pencere(tmp_path, monkeypatch):
    from keypilot import paths
    from keypilot.ui.log_view import LogView

    path = tmp_path / "log.txt"
    path.write_text(YENI, encoding="utf-8")
    monkeypatch.setattr(paths, "LOG", path)
    view = LogView()
    view.reload(force=True)
    return view


def test_pencere_listeler_ve_suzer(qapp, tmp_path, monkeypatch):
    view = _pencere(tmp_path, monkeypatch)
    try:
        assert view.table.rowCount() == 3

        view.only_errors.setChecked(True)
        assert view.table.rowCount() == 1  # yalniz WARNING+

        view.only_errors.setChecked(False)
        # Filtre GECIKMELI ciziyor (yazarken 2000 satir kurulmasin diye);
        # testte zamanlayiciyi beklemek yerine cizimi dogrudan tetikliyoruz.
        view.filter.setText("cift tiklama")
        view._render()
        assert view.table.rowCount() == 1

        view.filter.setText("bulunamayacak-bir-sey")
        view._render()
        assert view.table.rowCount() == 0
    finally:
        view.close()


def test_seviye_sutununda_dosyadaki_simge_var(qapp, tmp_path, monkeypatch):
    view = _pencere(tmp_path, monkeypatch)
    try:
        assert view.table.item(0, 2).text() == "🔵"
        assert view.table.item(2, 2).text() == "🟡"
    finally:
        view.close()


def test_detay_SATIRIN_ALTINDA_acilir(qapp, tmp_path, monkeypatch):
    """Traceback listenin icinde degil, ait oldugu satirin altinda."""
    view = _pencere(tmp_path, monkeypatch)
    try:
        # listedeki hucre tek satir kaliyor
        assert "\n" not in view.table.item(2, view.MESSAGE_COLUMN).text()
        assert view.table.rowCount() == 3  # kapaliyken ek satir yok

        view._on_cell_clicked(2, view.MESSAGE_COLUMN)
        assert view.table.rowCount() == 4  # kayit + acilan kutu
        box = view.table.cellWidget(3, 0)
        assert "ValueError: ornek" in box.toPlainText()
        # basligi/mesaji TEKRAR ETMIYOR: ustunde zaten duruyor
        assert "cift tiklama yutuldu" not in box.toPlainText()

        view._on_cell_clicked(2, view.MESSAGE_COLUMN)  # ikinci tik kapatir
        assert view.table.rowCount() == 3
        assert view.table.cellWidget(3, 0) is None
    finally:
        view.close()


def test_DETAYSIZ_satir_tiklaninca_ACILMAZ(qapp, tmp_path, monkeypatch):
    """Detay yoksa acilacak bir sey de yok: satir yerinde kalir."""
    view = _pencere(tmp_path, monkeypatch)
    try:
        view._on_cell_clicked(0, view.MESSAGE_COLUMN)
        assert view.table.rowCount() == 3
    finally:
        view.close()


def test_SATIRIN_HER_YERI_acar(qapp, tmp_path, monkeypatch):
    """Ayri bir ok sutunu YOK; tiklama icin isabet sarti da olmamali."""
    view = _pencere(tmp_path, monkeypatch)
    try:
        view._on_cell_clicked(2, 0)  # tarih sutunu
        assert view.table.rowCount() == 4
    finally:
        view.close()


def test_acik_detay_YENIDEN_OKUYUNCA_acik_kalir(qapp, tmp_path, monkeypatch):
    """Dosya 1.5 sn'de bir tazeleniyor; acilan kutu her seferinde kapanmamali."""
    view = _pencere(tmp_path, monkeypatch)
    try:
        view._on_cell_clicked(2, view.MESSAGE_COLUMN)
        view.reload(force=True)  # kayitlar YENI nesneler olarak geliyor
        assert view.table.rowCount() == 4
        assert view.table.cellWidget(3, 0) is not None
    finally:
        view.close()


def test_satir_kopyalama_acik_kutuya_kaymaz(qapp, tmp_path, monkeypatch):
    """Araya giren detay satiri liste ile kayit eslesmesini bozmamali."""
    view = _pencere(tmp_path, monkeypatch)
    try:
        view._on_cell_clicked(2, view.MESSAGE_COLUMN)
        view.table.selectRow(3)  # acilan kutunun satiri: kayit degil
        assert view._selected() is None
        view.table.selectRow(2)
        assert view._selected().message == "cift tiklama yutuldu"
    finally:
        view.close()


def test_detayli_satir_MESAJIN_SONUNDA_isaret_ve_ayri_zemin_alir(qapp, tmp_path, monkeypatch):
    """"Devami var mi" listeye bakinca anlasilmali -- ayri sutun olmadan."""
    from keypilot.ui import log_view as module

    view = _pencere(tmp_path, monkeypatch)
    try:
        detayli = view.table.item(2, view.MESSAGE_COLUMN)
        assert detayli.text().endswith(module.DETAIL_MARK)
        assert detayli.background().color() == view.detail_bg()
        # detaysiz satirda ne isaret ne ayri zemin var
        duz = view.table.item(0, view.MESSAGE_COLUMN)
        assert not duz.text().endswith(module.DETAIL_MARK)
        assert duz.background().color() != view.detail_bg()
    finally:
        view.close()


def test_ARA_BICIMLERDEKI_isaret_seviyeyi_kaydirmaz():
    """Gelistirme sirasinda zaman damgasi ile seviye arasinda tek
    karakterlik isaret duran bicimler oldu; o satirlarda seviye bir kayip
    `!` seviye adi sanilyordu."""
    ara = "@2026-09-07 16:47:16 ! INFO    MainThread     keypilot: kapaniyor\n"
    row = logs.parse_log_text(ara)[0]
    assert row.level == "INFO"
    assert row.thread == "MainThread"
    assert row.source == "keypilot"


def test_ESKI_bitis_isaretli_bicim_de_okunur():
    """Kisa omurlu ara bicimde `!` blogun SONUNA konuyordu."""
    eski = (
        "@2026-09-07 16:13:01 WARNING MainThread     keypilot.app: patladi\n"
        " ValueError: ornek\n"
        "!\n"
        "@2026-09-07 16:13:02 INFO    MainThread     keypilot: devam\n"
    )
    rows = logs.parse_log_text(eski)
    assert len(rows) == 2  # yalniz duran `!` kayit acmiyor
    assert rows[0].detail.strip() == "ValueError: ornek"
    assert rows[1].message == "devam"


def test_istatistikler_AYRI_SEKMEDE_liste_olarak(qapp, tmp_path, monkeypatch):
    view = _pencere(tmp_path, monkeypatch)
    try:
        assert [view.tabs.tabText(i) for i in range(view.tabs.count())] == ["Log", "Durum"]
        view.set_stats([("hook: dusen olay", "0"), ("pano kaydi", "2500")])
        assert view.stats.rowCount() == 2
        assert view.stats.item(1, 0).text() == "pano kaydi"
        assert view.stats.item(1, 1).text() == "2500"
        # log listesinin alt seridinde artik yoklar
        assert "pano" not in view.status.text()
    finally:
        view.close()
