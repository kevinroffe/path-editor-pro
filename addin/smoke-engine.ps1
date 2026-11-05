# Smoke test for the packaged engine: starts qbiq-engine.exe, then checks the page, the key, a real Revit level upload and
# the level elevation in the Enscape XML. Run it on every rebuilt engine (a PyInstaller bundle can silently miss a module).
#   .\smoke-engine.ps1 -EngineDir <folder holding qbiq-engine.exe>
# Copy the bundle to a short path first (for example C:\Users\Public\q): very long paths break DLL loading.
param(
    [Parameter(Mandatory = $true)][string]$EngineDir,
    [int]$Port = 5560
)
$ErrorActionPreference = 'Stop'
$fixture = Join-Path $PSScriptRoot '..\backend\tests\fixtures\revit_level.json'
$exe = Join-Path $EngineDir 'qbiq-engine.exe'
$failures = @()
function Check($name, $ok) { if ($ok) { Write-Host "ok    $name" } else { Write-Host "FAIL  $name"; $script:failures += $name } }

$p = Start-Process -FilePath $exe -ArgumentList '--port', $Port, '--key', 'test' -PassThru -WindowStyle Hidden
try {
    $base = "http://127.0.0.1:$Port"
    $up = $false
    for ($i = 0; $i -lt 60 -and -not $up; $i++) {
        Start-Sleep -Seconds 1
        if ($p.HasExited) { break }
        try { $up = (Invoke-WebRequest "$base/" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch { }
    }
    Check 'engine starts and serves the page' $up
    if ($up) {
        $h = @{ 'X-Qbiq-Key' = 'test' }
        $code = try { (Invoke-WebRequest "$base/api/demo" -UseBasicParsing).StatusCode } catch { $_.Exception.Response.StatusCode.value__ }
        Check 'API without the key is refused (403)' ($code -eq 403)
        Check 'API with the key works' ((Invoke-WebRequest "$base/api/demo" -Headers $h -UseBasicParsing).StatusCode -eq 200)

        $body = [Text.Encoding]::UTF8.GetBytes((Get-Content $fixture -Raw -Encoding UTF8))
        $r = Invoke-RestMethod "$base/api/upload-revit" -Method Post -Headers $h -ContentType 'application/json; charset=utf-8' -Body $body
        Check 'Revit level loads as source revit with a plan' ($r.source -eq 'revit' -and $null -ne $r.plan)
        $route = Invoke-RestMethod "$base/api/autopath" -Method Post -Headers $h -ContentType 'application/json' -Body '{"start":[5,-20],"end":[55,-20]}'
        Check 'Auto-path returns a route' ($route.waypoints.Count -ge 2)
        $xml = (Invoke-WebRequest "$base/api/export/xml" -Method Post -Headers $h -ContentType 'application/json' -UseBasicParsing `
            -Body '{"waypoints":[[10,-20,0,"",null],[50,-20,0,"",null]],"cuts":[],"settings":{"duration":10,"units_to_metres":0.3048,"elevation_m":3.9624}}').Content
        Check 'XML eye height includes the level elevation (5.53)' ($xml -match 'y="5\.5324')
    }
    else {
        Write-Host ("engine did not start" + $(if ($p.HasExited) { " (exited with code $($p.ExitCode))" } else { '' }))
    }
}
finally {
    if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force }
}
if ($failures.Count) { Write-Host "`n$($failures.Count) check(s) failed."; exit 1 }
Write-Host "`nAll checks passed."
