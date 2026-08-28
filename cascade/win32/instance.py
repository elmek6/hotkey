"""DEVRE DISI -- tek ornek kilidi. Istenmedi, kendiliginden eklenmisti.

AHK'deki `#SingleInstance Force` karsiligiydi: adlandirilmis mutex ile
ikinci ornegin acilmasini engellerdi.

Kullanmak icin: asagiyi yorumdan cikar, main.py'nin sonundaki
main_with_lock() ornegine bak.
"""

#
# from __future__ import annotations
#
# import ctypes
# from ctypes import wintypes
#
# from cascade.win32.structs import kernel32
#
# ERROR_ALREADY_EXISTS = 183
#
# kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
# kernel32.CreateMutexW.restype = wintypes.HANDLE
# kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
# kernel32.CloseHandle.restype = wintypes.BOOL
# kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
# kernel32.ReleaseMutex.restype = wintypes.BOOL
#
#
# class SingleInstance:
#     """`with` ya da elle release ile kullanilir.
#
#     acquired False ise bu makinede zaten bir cascade calisiyor demektir.
#     """
#
#     def __init__(self, name: str = "cascade") -> None:
#         self.name = f"Local\\{name}-single-instance"
#         self._handle = kernel32.CreateMutexW(None, True, self.name)
#         last_error = ctypes.get_last_error()
#         self.acquired = bool(self._handle) and last_error != ERROR_ALREADY_EXISTS
#         if self._handle and not self.acquired:
#             kernel32.CloseHandle(self._handle)
#             self._handle = None
#
#     def release(self) -> None:
#         if self._handle:
#             kernel32.ReleaseMutex(self._handle)
#             kernel32.CloseHandle(self._handle)
#             self._handle = None
#             self.acquired = False
#
#     def __enter__(self) -> SingleInstance:
#         return self
#
#     def __exit__(self, *_) -> None:
#         self.release()
