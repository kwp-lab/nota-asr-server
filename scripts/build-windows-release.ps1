[CmdletBinding()]
param(
    [ValidateSet("Release")]
    [string]$Configuration = "Release",

    [Alias("UnsignedDevelopmentBuild")]
    [switch]$UnsignedRelease
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$DistRoot = Join-Path $RepoRoot "dist"
$worktreeState = @(git -C $RepoRoot status --porcelain)
if ($worktreeState.Count -ne 0) {
    throw "Formal Windows releases require a clean Git worktree."
}

$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Create the locked development environment before building: uv sync --extra cpu --extra dev"
}
$version = (& $python -c "import nota_asr_server; print(nota_asr_server.__version__)").Trim()
$managerVersion = (& cargo metadata --manifest-path (Join-Path $RepoRoot "Cargo.toml") --locked --no-deps --format-version 1 |
    ConvertFrom-Json).packages.Where({ $_.name -eq "nota-asr-manager" }).version
if ($managerVersion -ne $version) {
    throw "Manager version $managerVersion does not match Server version $version."
}
$changelog = Get-Content -LiteralPath (Join-Path $RepoRoot "CHANGELOG.md") -Raw
$firstRelease = [regex]::Match(
    $changelog,
    '(?m)^## \[(?<version>[^]]+)\] - (?<date>\d{4}-\d{2}-\d{2})$'
)
if (-not $firstRelease.Success -or $firstRelease.Groups['version'].Value -ne $version) {
    throw "The first dated CHANGELOG.md section must be version $version."
}
$unreleased = [regex]::Match(
    $changelog,
    '(?ms)^## \[Unreleased\]\s*(?<body>.*?)(?=^## \[)'
)
if (-not $unreleased.Success -or -not [string]::IsNullOrWhiteSpace($unreleased.Groups['body'].Value)) {
    throw "Move all release notes out of [Unreleased] before building a formal release."
}

$hasStoreCertificate = -not [string]::IsNullOrWhiteSpace($env:NOTA_SIGN_CERT_SHA1)
$hasPfxCertificate = -not [string]::IsNullOrWhiteSpace($env:NOTA_SIGN_PFX_PATH)
if (-not $UnsignedRelease -and -not ($hasStoreCertificate -or $hasPfxCertificate)) {
    throw "No code-signing certificate is configured. Configure NOTA_SIGN_CERT_SHA1 or NOTA_SIGN_PFX_PATH, or explicitly pass -UnsignedRelease for a public unsigned portable package."
}

function Get-SignTool {
    if ($env:NOTA_SIGNTOOL) {
        return (Get-Item -LiteralPath $env:NOTA_SIGNTOOL).FullName
    }
    $command = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $kits = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    $candidate = Get-ChildItem -LiteralPath $kits -Filter signtool.exe -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match '\\x64\\signtool\.exe$' } |
        Sort-Object FullName -Descending |
        Select-Object -First 1
    if (-not $candidate) { throw "Windows SDK signtool.exe was not found." }
    return $candidate.FullName
}

function Invoke-CodeSign([string]$Path) {
    if ($UnsignedRelease) { return }
    $signTool = Get-SignTool
    $timestampUrl = if ($env:NOTA_SIGN_TIMESTAMP_URL) { $env:NOTA_SIGN_TIMESTAMP_URL } else { "http://timestamp.digicert.com" }
    $arguments = @("sign", "/fd", "SHA256", "/tr", $timestampUrl, "/td", "SHA256")
    if ($hasStoreCertificate) {
        $arguments += @("/sha1", $env:NOTA_SIGN_CERT_SHA1)
    } else {
        $arguments += @("/f", $env:NOTA_SIGN_PFX_PATH)
        if ($env:NOTA_SIGN_PFX_PASSWORD) { $arguments += @("/p", $env:NOTA_SIGN_PFX_PASSWORD) }
    }
    $arguments += $Path
    & $signTool @arguments
    if ($LASTEXITCODE -ne 0) { throw "Code signing failed for $Path" }
    & $signTool verify /pa /v $Path
    if ($LASTEXITCODE -ne 0) { throw "Signature verification failed for $Path" }
}

New-Item -ItemType Directory -Path $DistRoot -Force | Out-Null
$workRoot = Join-Path $DistRoot (".wr-" + [guid]::NewGuid().ToString("N").Substring(0, 12))
$packageName = "Nota-ASR-Runtime-$version-Windows-x64-CPU"
$archiveRoot = Join-Path $workRoot "a"
$runtimeRoot = Join-Path $archiveRoot $packageName
$metadataPath = Join-Path $workRoot "cargo-metadata.json"
$zipName = "$packageName.zip"
$zipPath = Join-Path $DistRoot $zipName
$stagedZipPath = Join-Path $workRoot $zipName
$shaPath = "$zipPath.sha256"
$manifestPath = Join-Path $DistRoot "$packageName.manifest.json"
if (Test-Path -LiteralPath $zipPath) {
    throw "Release artifact already exists: $zipPath"
}
if (Test-Path -LiteralPath $shaPath) {
    throw "Release checksum already exists: $shaPath"
}
if (Test-Path -LiteralPath $manifestPath) {
    throw "Release manifest already exists: $manifestPath"
}

try {
    New-Item -ItemType Directory -Path $workRoot -Force | Out-Null
    & (Join-Path $RepoRoot "scripts\build-windows-runtime.ps1") -OutputDirectory $runtimeRoot -PreloadModel sensevoice
    if ($LASTEXITCODE -ne 0) { throw "Runtime build failed." }

    & cargo build --manifest-path (Join-Path $RepoRoot "Cargo.toml") --workspace --release --locked
    if ($LASTEXITCODE -ne 0) { throw "Manager build failed." }
    $manager = Join-Path $RepoRoot "target\release\NotaASRManager.exe"
    Invoke-CodeSign $manager
    Copy-Item -LiteralPath $manager -Destination (Join-Path $runtimeRoot "NotaASRManager.exe")

    cargo metadata --manifest-path (Join-Path $RepoRoot "Cargo.toml") --locked --format-version 1 |
        Set-Content -LiteralPath $metadataPath -Encoding utf8NoBOM
    & (Join-Path $runtimeRoot "runtime\python\python.exe") `
        (Join-Path $RepoRoot "scripts\generate_manager_license_artifacts.py") `
        --metadata $metadataPath `
        --cargo-lock (Join-Path $RepoRoot "Cargo.lock") `
        --output-dir (Join-Path $runtimeRoot "legal")
    if ($LASTEXITCODE -ne 0) { throw "Manager compliance generation failed." }

    $signToolVersion = "not-used"
    if (-not $UnsignedRelease) {
        $signToolVersion = (Get-Item -LiteralPath (Get-SignTool)).VersionInfo.FileVersion
    }

    $runtimeManifestPath = Join-Path $runtimeRoot "runtime-manifest.json"
    $runtimeManifest = Get-Content -LiteralPath $runtimeManifestPath -Raw | ConvertFrom-Json -AsHashtable
    $runtimeManifest.manager_version = $managerVersion
    $runtimeManifest.distribution = "portable-zip"
    $runtimeManifest.component_sizes.manager = (Get-Item -LiteralPath (Join-Path $runtimeRoot "NotaASRManager.exe")).Length
    $runtimeManifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runtimeManifestPath -Encoding utf8NoBOM

    $previousOffline = $env:HF_HUB_OFFLINE
    $env:HF_HUB_OFFLINE = "1"
    try {
        & (Join-Path $runtimeRoot "runtime\python\python.exe") -m nota_asr_server.cli doctor `
            --config (Join-Path $runtimeRoot "config\server.toml") --output json
        if ($LASTEXITCODE -notin @(0, 5)) { throw "Offline Runtime self-check failed." }
    } finally {
        $env:HF_HUB_OFFLINE = $previousOffline
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $archiveRoot,
        $stagedZipPath,
        [System.IO.Compression.CompressionLevel]::Optimal,
        $false
    )

    $zipItem = Get-Item -LiteralPath $stagedZipPath
    $sha256 = (Get-FileHash -LiteralPath $stagedZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $stagedShaPath = Join-Path $workRoot "$zipName.sha256"
    $stagedManifestPath = Join-Path $workRoot "$packageName.manifest.json"
    Set-Content -LiteralPath $stagedShaPath -Value "$sha256  $zipName" -Encoding ascii
    $releaseManifest = [ordered]@{
        schema_version = 1
        product = "nota-asr-server"
        version = $version
        artifact = $zipName
        artifact_format = "portable-zip"
        platform = "windows-x64"
        runtime = "cpu-online"
        manager_signed = -not [bool]$UnsignedRelease
        signature_policy = if ($UnsignedRelease) { "unsigned-public" } else { "authenticode" }
        sha256 = $sha256
        bytes = [long]$zipItem.Length
        git_commit = (git -C $RepoRoot rev-parse HEAD).Trim()
        built_at_utc = [DateTime]::UtcNow.ToString("o")
        build_tools = [ordered]@{
            powershell_version = $PSVersionTable.PSVersion.ToString()
            signtool_version = $signToolVersion
        }
    }
    $releaseManifest | ConvertTo-Json -Depth 6 |
        Set-Content -LiteralPath $stagedManifestPath -Encoding utf8NoBOM
    Move-Item -LiteralPath $stagedZipPath -Destination $zipPath
    Move-Item -LiteralPath $stagedShaPath -Destination $shaPath
    Move-Item -LiteralPath $stagedManifestPath -Destination $manifestPath
    Write-Output "Portable Windows release created at $zipPath"
}
finally {
    if (Test-Path -LiteralPath $workRoot) {
        Remove-Item -LiteralPath $workRoot -Recurse -Force
    }
}
