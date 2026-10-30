@echo off
rem 立即关闭显示器（不影响下载、后台任务）
powershell -NoProfile -WindowStyle Hidden -Command "Add-Type -Name M -Namespace W -MemberDefinition '[DllImport(\"user32.dll\")] public static extern int SendMessage(int hWnd, int hMsg, int wParam, int lParam);'; [void][W.M]::SendMessage(-1, 0x0112, 0xF170, 2)"