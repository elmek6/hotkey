"""Odak olcumunun HEDEF penceresi -- `probes/focus.py` bunu baslatir.

Ayri bir SUREC olmasi sart: Windows'un odak kurallari surec sinirinda
isliyor, ayni surecteki iki pencere birbirinden odagi serbestce aliyor.
Ilk olcumde Not Defteri kullanilmisti ama guvenilmez cikti (Windows 11'de
tek surec, sekmeli, aradan kapanabiliyor); burada pencere olcum bitene
kadar YERINDE duruyor.

Icinde bir yazi kutusu var: odak "pencerede" degil, YAZDIGIN yerde
olmali -- olculen sey tam olarak bu.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QVBoxLayout, QWidget

TITLE = "KeyPilot odak hedefi"


def main() -> int:
    app = QApplication(sys.argv)
    window = QWidget()
    window.setWindowTitle(TITLE)
    window.resize(360, 160)
    layout = QVBoxLayout(window)
    layout.addWidget(QLabel("odak olcumu -- burasi 'yazdigin uygulama'"))
    box = QLineEdit()
    box.setPlaceholderText("imlec burada olmali")
    layout.addWidget(box)
    window.show()
    box.setFocus()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
