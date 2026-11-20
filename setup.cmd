@echo off
setlocal
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0tools\setup.ps1"
if errorlevel 1 (
  echo.
  echo N3 Recompiled setup failed. Review the message above or .tools\setup-state\last-setup.jsonl.
  pause
)
