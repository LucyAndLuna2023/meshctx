$ErrorActionPreference = 'Stop'
$uri = 'http://192.168.3.45:8889/meshctx-setup.exe'
$outFile = 'C:\MeshCtxGUITest\s_v380.exe'

Write-Output "=== DOWNLOAD ==="
Invoke-WebRequest -Uri $uri -OutFile $outFile -UseBasicParsing
Write-Output "Download OK: $((Get-Item $outFile).Length) bytes"

$targetDir = 'C:\MeshCtxTest'
if (Test-Path $targetDir) { Remove-Item -Recurse -Force $targetDir }

Write-Output "=== INSTALL ==="
$proc = Start-Process -FilePath $outFile -ArgumentList '/S','/D=C:\MeshCtxTest' -Wait -NoNewWindow -PassThru
Write-Output "Install exit: $($proc.ExitCode)"
Start-Sleep -Seconds 3

Write-Output "=== VERIFY ==="
if (Test-Path $targetDir) {
    Get-ChildItem $targetDir -Recurse | ForEach-Object { "$($_.FullName) ($($_.Length) bytes)" }
} else {
    Write-Output "DIR NOT FOUND: $targetDir"
    # Check default
    $defaultPath = "${env:ProgramFiles}\MeshCtx"
    if (Test-Path $defaultPath) {
        Write-Output "Found at default: $defaultPath"
        Get-ChildItem $defaultPath -Recurse | ForEach-Object { "$($_.FullName) ($($_.Length) bytes)" }
    }
}
