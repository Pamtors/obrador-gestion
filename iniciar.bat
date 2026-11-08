@echo off
cd /d "%~dp0"

call venv\Scripts\activate.bat

start "" http://localhost:8000

uvicorn app.main:app --reload

pause
