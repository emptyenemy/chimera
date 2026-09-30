$ErrorActionPreference = 'Stop'

$runtimePresent = python -c "from ui.webview_runtime import installed; print('installed' if installed() else 'missing')"
Write-Host "WebView2 Runtime: $runtimePresent"
if ($runtimePresent -eq 'installed') { exit 0 }

$webviewSetupPath = Join-Path $env:RUNNER_TEMP 'MicrosoftEdgeWebview2Setup.exe'
Invoke-WebRequest -Uri 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $webviewSetupPath
$webviewSignature = Get-AuthenticodeSignature -LiteralPath $webviewSetupPath
if ($webviewSignature.Status -ne 'Valid' -or $webviewSignature.SignerCertificate.Subject -notmatch 'Microsoft Corporation') {
    throw 'WebView2 installer signature is invalid'
}
$webviewInstaller = Start-Process -FilePath $webviewSetupPath -ArgumentList '/silent', '/install' -WindowStyle Hidden -Wait -PassThru
Write-Host "WebView2 installer exit code: $($webviewInstaller.ExitCode)"
python -c "from ui.webview_runtime import installed; assert installed(), 'WebView2 Runtime was not installed'"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
