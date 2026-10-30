@echo off
rem 双击运行：会弹 UAC，以管理员身份执行 open-lan.ps1（放行 8787 并打印手机访问地址）
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-NoExit','-File','%~dp0open-lan.ps1'"
