@echo off
rem Lives in windows\ but operates on the repo root.
cd /d "%~dp0.."
call venv\Scripts\activate
python main.py
