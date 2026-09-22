COMMODITY NEWS DESK - WINDOWS EXE

1. Copy this entire folder to your Windows PC.
2. Double-click build_exe.bat.
3. The script installs the Python packages and builds:

   dist\CommodityNewsDesk.exe

4. After the build finishes, double-click:

   dist\CommodityNewsDesk.exe

The EXE starts the Flask server and opens the dashboard automatically at:
http://127.0.0.1:5000

IMPORTANT:
- The EXE still needs internet access because the dashboard reads public RSS feeds.
- Windows Defender/SmartScreen may show a warning for an unsigned locally-built EXE. This is normal for an EXE that has not been code-signed.
- If you change app.py, config.py, templates, CSS, or JavaScript later, run build_exe.bat again.
