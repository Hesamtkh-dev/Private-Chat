@echo off
REM Change to the directory where this .bat file is located
cd /d "%~dp0"

REM Activate the virtual environment
call Scripts\activate

REM Run the Streamlit app
python main.py

pause
