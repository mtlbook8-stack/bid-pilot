#requires -Version 5.1
# Build a Linux-compatible function deployment zip with forward-slash entry
# names. PowerShell's Compress-Archive and .NET's ZipFile.CreateFromDirectory
# on Windows both bake backslashes into entry names, which Linux unzip treats
# as literal filename characters — making subdirectories disappear at runtime.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$StageDir,
    [Parameter(Mandatory = $true)][string]$ZipPath
)

$ErrorActionPreference = 'Stop'
Add-Type -Assembly System.IO.Compression
Add-Type -Assembly System.IO.Compression.FileSystem

if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }

$stageItem = Get-Item -LiteralPath $StageDir
$stageFull = $stageItem.FullName.TrimEnd('\','/')
$fs = [System.IO.File]::Open($ZipPath, [System.IO.FileMode]::Create)
try {
    $zip = [System.IO.Compression.ZipArchive]::new($fs, [System.IO.Compression.ZipArchiveMode]::Create)
    try {
        Get-ChildItem -LiteralPath $stageFull -Recurse -File | ForEach-Object {
            # Use the canonicalized stage path's length against each file's
            # FullName (which is already canonical) to compute the relative
            # entry path. Mixing short (ABERHA~1) and long path forms here
            # produced entries like "c-pkg/..." in earlier attempts.
            $full = $_.FullName
            if (-not $full.StartsWith($stageFull, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "Unexpected path outside stage: $full"
            }
            $rel = $full.Substring($stageFull.Length).TrimStart('\','/') -replace '\\','/'
            $entry = $zip.CreateEntry($rel, [System.IO.Compression.CompressionLevel]::Optimal)
            $es = $entry.Open()
            try {
                $bytes = [System.IO.File]::ReadAllBytes($_.FullName)
                $es.Write($bytes, 0, $bytes.Length)
            } finally { $es.Dispose() }
        }
    } finally { $zip.Dispose() }
} finally { $fs.Dispose() }

Write-Host "Zip created: $ZipPath"
