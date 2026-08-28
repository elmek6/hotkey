@echo off
rem cascade - HATA AYIKLAMA. Konsol acik kalir, hatalari burada gorursun.
rem Bu pencereyi kapatirsan cascade de kapanir. Normal kullanim icin baslat.vbs.
cd /d "%~dp0"
echo Hata ayiklama modu. Bu pencereyi kapatirsan cascade de kapanir.
echo.
".venv\Scripts\python.exe" main.py
echo.
echo cascade kapandi. Kapatmak icin bir tusa bas.
pause >nul
