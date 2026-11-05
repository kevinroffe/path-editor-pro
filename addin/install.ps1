# Installs the Qbiq Path Tool add-in for the current Windows user (no admin rights needed).
#   .\install.ps1                 install or update for Revit 2024
#   .\install.ps1 -Uninstall      remove it
# Close Revit first: add-ins are read when Revit starts.
param(
    [string]$RevitVersion = '2024',
    [switch]$Uninstall,
    [switch]$Force      # install even though Revit is running (it will not see the add-in until restarted)
)
$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$addins = Join-Path $env:APPDATA "Autodesk\Revit\Addins\$RevitVersion"
$dest = Join-Path $addins 'QbiqPathTool'
$manifest = Join-Path $addins 'QbiqPathTool.addin'

if ($Uninstall) {
    Remove-Item $manifest -ErrorAction SilentlyContinue
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    Write-Host 'Qbiq Path Tool removed.'
    return
}

if ((Get-Process Revit -ErrorAction SilentlyContinue) -and -not $Force) {
    Write-Warning 'Revit is running. Close it, run this again, then start Revit (or use -Force to install now and restart Revit later).'
    return
}

New-Item -ItemType Directory -Force $dest | Out-Null
Copy-Item (Join-Path $here 'addin\*') $dest -Recurse -Force
if (Test-Path (Join-Path $dest 'engine')) { Remove-Item (Join-Path $dest 'engine') -Recurse -Force }
Copy-Item (Join-Path $here 'engine') (Join-Path $dest 'engine') -Recurse -Force

# The manifest must hold the full path of the add-in DLL.
$text = Get-Content (Join-Path $dest 'QbiqPathTool.addin') -Raw
$text.Replace('__ASSEMBLY__', (Join-Path $dest 'Qbiq.PathTool.Addin.dll')) | Set-Content -Encoding UTF8 $manifest
Remove-Item (Join-Path $dest 'QbiqPathTool.addin')

Write-Host "Installed to $dest"
Write-Host 'Start Revit 2024: the "Path Tool" tab appears in the ribbon.'
