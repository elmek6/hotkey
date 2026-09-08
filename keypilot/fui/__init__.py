"""Flet arayuzu -- PySide6'dan ADIM ADIM gecisin yasadigi yer.

`keypilot/ui/` hala ayakta ve program hala Qt ile kosuyor. Buraya
tasinan her panel Qt tarafinda BIR satir degistiriyor: eski widget'in
yerine buradaki esdegeri konuyor. Ikisi ayni anda calisir.

Tasinan paneller:

    fui/key_map.py     Kisayol haritasi     <- ui/key_map_view.py

Neden burasi ayri bir paket: `ui/` icindeki her modul PySide6 ithal
ediyor ve o dosyalari kirletmeden yan yana durmalari gerekiyor. Panel
tasinip oturunca eskisi silinir, dosya adi `ui/`ye geri tasinmaz --
sonunda `ui/` bosalip yok olur.
"""
