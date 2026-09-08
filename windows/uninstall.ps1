# Remove Multi-Out for the current user.
$ErrorActionPreference = "SilentlyContinue"
Unregister-ScheduledTask -TaskName "Multi-Out auto-switch" -Confirm:$false
Remove-Item (Join-Path ([Environment]::GetFolderPath("Programs")) "Multi-Out.lnk")
Get-Process pythonw -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*multiout.py*" } | Stop-Process -Force
Write-Host "Removed. Your state file is kept at $env:LOCALAPPDATA\multiout\state.json"
