@echo off
setlocal
python -m pytest tests || exit /b 1
python -m compileall src tests || exit /b 1
