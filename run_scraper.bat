@echo off
cd /d "%~dp0"
echo Starting scraper at %date% %time% >> scraper_log.txt
".venv\Scripts\python.exe" "static-site\scripts\scraper.py" >> scraper_log.txt 2>&1
echo Finished scraper at %date% %time% >> scraper_log.txt
