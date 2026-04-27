@echo off
cd /d "%~dp0"
start /b python src/bot.py > bot.log 2>&1
echo Bot started in background. Check bot.log for output.
pause