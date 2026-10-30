@echo off
rem 双击运行：会弹 UAC，以管理员身份执行 fix-hotspot.ps1
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-NoExit','-File','%~dp0fix-hotspot.ps1'"
