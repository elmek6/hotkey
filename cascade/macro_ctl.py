"""Makro denetleyicisi -- kayit penceresi ile veri katmanini baglar.

AHK'de bu katman yoktu: kayit hook'un icinden, oynatma da ikinci bir
AutoHotkey surecinden yurutuluyordu. Bizde ikisi de tek surecte, bu yuzden
kimin hangi thread'de kostugu onemli:

    kayit    ANA THREAD -- olaylar `app._drain` icindeki `seen` kuyrugundan
             geliyor, hook callback'ine hic dokunulmuyor
    oynatma  AYRI THREAD -- `send.py` cagrilari sirasinda arayuz donmasin;
             Qt widget'ina bu thread'den DOKUNULMAZ, durum sinyalle
             bildirilir

Kendi enjekte ettigimiz girdi kayda GECMEZ (`hook` olaylari `injected` +
`ours` tasiyor), bu yuzden oynatirken kayit acik kalsa bile makro kendini
yeniden kaydetmez -- AHK'nin ayri surec baslatma gerekcesi burada yok.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from cascade import macro
from cascade.ui.macro_view import MacroView
from cascade.win32.hook import KeyEvent, MouseEvent

log = logging.getLogger("cascade.macro")


class MacroController(QObject):
    #: oynatma bitti (ayri thread'den) -- arayuz ANA thread'de tazelensin
    finished = Signal(int)

    def __init__(self, *, tip: Callable[[str, int], None] | None = None) -> None:
        super().__init__()
        self._tip = tip or (lambda _text, _ms: None)
        self.recorder = macro.Recorder()
        self._slot = 1
        #: Kaydedilmemis kayit var mi (kaydedici kendini durdurmus olabilir)
        self._pending = False
        self.view = MacroView()
        self.view.record_requested.connect(self.start_record)
        self.view.stop_requested.connect(self.stop)
        self.view.play_requested.connect(self.play)
        self.finished.connect(self._on_finished)

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        #: Pencere kaydi ayari acikken one cikan pencereyi yoklar
        #: (AHK: SetTimer(logWindow, 100)).
        self._window_timer = QTimer(self)
        self._window_timer.timeout.connect(self._poll_window)

    def register(self, runner) -> None:
        runner.register("macro.recorder", lambda _: self.show())
        # TODO: makro slotlarina KISAYOL. Su an makro yalniz pencereden
        # calisiyor; uc slotun tusu olmali ve bu tuslar keymap.py'ye SABIT
        # yazilmamali -- kayit defterinden gecmeli:
        #
        #     runner.register("macro.play", lambda arg: self.play(int(arg)))
        #     for slot in (1, 2, 3):
        #         table.claim(f"macro:{slot}", spec, f"macro.play:{slot}",
        #                     f"makro {slot}")
        #
        # Boylece makro tuslari da kisayol haritasinda gorunur, alan ve
        # profil kisayollariyla ayni catisma kontrolunden gecer ve
        # kullanici tusu KeyCapture ile degistirebilir (bkz. app.py
        # `bind_profile_keys` -- ayni kalip). Tusun nerede secilecegi
        # kararlasmadi: makro penceresinde slot basina bir KeyCapture en
        # dogru yer gibi duruyor.

    def show(self) -> None:
        self.view.open()

    # ---- kayit ----

    def start_record(self, slot: int, record_type: str) -> None:
        self._slot = slot
        self.recorder.start(record_type)
        self._pending = True
        if macro.RECORD_WINDOW.get():
            self._window_timer.start(100)
        self.view.set_state(True, False, f"Kayitta -- rec{slot}.jsonl (Esc: durdur)")
        self._tip("⏺️ Kayit basladi", 1200)

    def stop(self, slot: int = 0, name: str = "") -> None:
        """Kaydi bitirir ve diske yazar; oynatma varsa onu da keser.

        Iki isi tek dugmenin yapmasi kasitli: kullanicinin "dur" dedigi an
        neyin surdugunu bilmesi gerekmiyor (AHK'de de `stop()` boyleydi).
        """
        self._stop.set()
        self._window_timer.stop()
        # `recording` bayragina DEGIL `_pending`e bakiyoruz: kaydedici Esc
        # ya da olay sinirinda kendini durdurmus olabilir, o kayit da
        # diske yazilmali.
        if not self._pending:
            self.view.set_state(False, self._playing(), "")
            return
        self._pending = False
        self.recorder.stop()
        path = self.recorder.save(slot or self._slot, name)
        if path is None:
            self.view.set_state(False, False, "Bos kayit -- dosya yazilmadi")
            return
        self.view.set_state(False, False, f"{len(self.recorder.events)} olay -> {path.name}")

    def feed(self, event) -> None:
        """`app._drain` her hook olayinda cagirir. Ne kayit ne oynatma
        varken bedava: ilk iki satirda donuyor."""
        if isinstance(event, KeyEvent) and event.vk == macro.VK_ESCAPE and self._playing():
            # Panik tusu. Oynatma sirasinda klavye kullanicinin elinden
            # cikiyor; Esc'i BASILIRKEN degil kaydedici gormeden once
            # yakaliyoruz ki uzun bir makronun ortasinda da is gorsun.
            self._stop.set()
            self._tip("⏹️ Oynatma kesildi", 1200)
            return
        if not self.recorder.recording:
            return
        if isinstance(event, KeyEvent):
            self.recorder.feed_key(event)
            if not self.recorder.recording:
                # Esc ya da sinir: kaydedici kendini durdurdu, yaziya dok.
                self.stop(self._slot, self.view.name.text())
        elif isinstance(event, MouseEvent):
            self.recorder.feed_mouse(event)

    def _poll_window(self) -> None:
        from cascade.win32 import window

        hwnd = window.foreground_window()
        self.recorder.feed_window(window.window_class(hwnd), window.window_title(hwnd))

    # ---- oynatma ----

    def _playing(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def play(self, slot: int, repeat: int = 1) -> None:
        if self._playing():
            return
        name, events = macro.read(macro.slot_path(slot))
        if not events:
            self.view.set_state(False, False, f"Kayit bos: rec{slot}.jsonl")
            return
        self._stop.clear()
        self.view.set_state(False, True, f"Oynatiliyor -- {name or f'rec{slot}.jsonl'}")

        def run() -> None:
            player = macro.Player(stop=self._stop.is_set)
            try:
                done = player.play(events, repeat)
            except Exception:
                log.exception("makro oynatilamadi (slot %s)", slot)
                done = 0
            self.finished.emit(done)

        self._thread = threading.Thread(target=run, name="macro-play", daemon=True)
        self._thread.start()

    def _on_finished(self, done: int) -> None:
        self.view.set_state(False, False, f"Bitti -- {done} olay")

    def shutdown(self) -> None:
        """Cikista: oynatma yarida kalsa bile surec beklemeden kapansin."""
        self._stop.set()
        self._window_timer.stop()
