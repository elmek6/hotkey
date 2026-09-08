"""Flet panellerinin ortak renkleri.

Qt tarafinda `keypilot/theme.py` var ama oradaki her sey QPalette /
stylesheet uzerine kurulu -- Flet'e verilecek bir sey yok. Renkler
Qt panellerinin stylesheet'lerinden aynen aliniyor: iki motor YAN YANA
kullanilacak ve kullanici hangisinin cizdigini fark etmemeli.

Tek istisna DANGER: Qt tarafi da sabit yaziyor (`theme.DANGER`), yani
oradaki degerle ayni tutulmasi yeterli.

TEMA IZLEME YOK. Qt surumu sistem temasina uyuyordu; buradaki paneller
koyu sabit. Ayar ekrani tasindiginda ele alinacak -- o zamana kadar
degistirilebilecek bir sey degil.
"""

from __future__ import annotations

#: Pencere zemini ve ana metin.
BG = "#0d1117"
FG = "#e6edf3"
#: Ikincil metin: aciklama, sayac, sistem satirlari.
MUTED = "#8b949e"
#: Giris kutusu zemini ve cercevesi.
FIELD_BG = "#161b22"
BORDER = "#30363d"
#: Catisan kisayol satirinin zemini (ui/key_map_view.py CONFLICT_BG).
CONFLICT_BG = "#5a1e22"
#: Tablo tek/cift satir ayrimi.
ALT_BG = "#11161d"
#: Kritik hata metni -- keypilot/theme.py DANGER ile ayni.
DANGER = "#f85149"
