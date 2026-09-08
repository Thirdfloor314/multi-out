# Install Multi-Out for the current user. No admin rights needed.
$ErrorActionPreference = "Stop"

$src = Split-Path -Parent $MyInvocation.MyCommand.Path
$script = Join-Path $src "multiout.py"

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { throw "Python 3 not found on PATH. Install it from python.org first." }
$pyw = Join-Path (Split-Path $py.Source) "pythonw.exe"
if (-not (Test-Path $pyw)) { $pyw = $py.Source }

Write-Host "Installing dependencies..."
& $py.Source -m pip install --user --upgrade comtypes pycaw PyQt6 PyAudioWPatch

Write-Host "Checking this machine..."
& $py.Source $script --selftest

# Start Menu shortcut for the window
$startMenu = [Environment]::GetFolderPath("Programs")
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut((Join-Path $startMenu "Multi-Out.lnk"))
$lnk.TargetPath = $pyw
$lnk.Arguments  = "`"$script`""
$lnk.WorkingDirectory = $src
$lnk.Description = "Play audio on several outputs at once"
$lnk.Save()

# Scheduled task so auto-switch runs at logon, windowless
$action  = New-ScheduledTaskAction -Execute $pyw -Argument "`"$script`" --daemon"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$set     = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
             -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName "Multi-Out auto-switch" -Action $action `
    -Trigger $trigger -Settings $set -Force | Out-Null
Start-ScheduledTask -TaskName "Multi-Out auto-switch"

Write-Host ""
Write-Host "Installed. 'Multi-Out' is in your Start Menu."
Write-Host "Auto-switch runs at logon as the task 'Multi-Out auto-switch'."
