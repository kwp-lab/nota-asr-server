[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,

    [ValidateSet("sensevoice", "paraformer", "fun-asr-nano")]
    [string]$PreloadModel = "sensevoice"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$PythonVersion = "3.12.12"
$UvVersion = "0.9.2"
$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path

if (-not $IsWindows) {
    throw "Windows Runtime builds must run on Windows."
}
if ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne "X64") {
    throw "Windows Runtime builds require an x64 build host."
}

$uv = Get-Command uv -ErrorAction Stop
$actualUvVersion = (& $uv.Source --version).Trim()
if ($actualUvVersion -notmatch "^uv $([regex]::Escape($UvVersion))(?: |$)") {
    throw "Expected uv $UvVersion, found $actualUvVersion."
}

$outputPath = if ([System.IO.Path]::IsPathFullyQualified($OutputDirectory)) {
    [System.IO.Path]::GetFullPath($OutputDirectory)
} else {
    [System.IO.Path]::GetFullPath($OutputDirectory, (Get-Location).Path)
}
if (Test-Path -LiteralPath $outputPath) {
    throw "Output directory already exists: $outputPath"
}
$outputParent = Split-Path -Parent $outputPath
New-Item -ItemType Directory -Path $outputParent -Force | Out-Null
# Keep the private staging name short. Windows dependencies can have deeply
# nested site-packages paths, so repeating the human-readable output name and a
# full GUID here can exceed legacy MAX_PATH limits during wheel installation.
$staging = Join-Path $outputParent (".nr-" + [guid]::NewGuid().ToString("N").Substring(0, 12))
$buildRoot = Join-Path $staging ".build"
$managedPythonRoot = Join-Path $buildRoot "python-install"
$runtimeRoot = Join-Path $staging "runtime"
$runtimePythonRoot = Join-Path $runtimeRoot "python"
$requirements = Join-Path $buildRoot "requirements-windows-cpu.txt"
$wheelRoot = Join-Path $buildRoot "wheel"

New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null

try {
    & $uv.Source python install $PythonVersion --install-dir $managedPythonRoot --managed-python --no-bin --no-config
    if ($LASTEXITCODE -ne 0) { throw "uv failed to install managed Python." }

    $managedPython = Get-ChildItem -LiteralPath $managedPythonRoot -Filter "python.exe" -File -Recurse |
        Where-Object { $_.Directory.Name -like "cpython-*" } |
        Select-Object -First 1
    if (-not $managedPython) {
        throw "Managed Python $PythonVersion was not found in the staging directory."
    }
    New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
    Move-Item -LiteralPath $managedPython.Directory.FullName -Destination $runtimePythonRoot
    $runtimePython = Join-Path $runtimePythonRoot "python.exe"

    & $uv.Source export --project $RepoRoot --frozen --no-dev --extra cpu --no-emit-project --format requirements.txt --output-file $requirements --quiet
    if ($LASTEXITCODE -ne 0) { throw "uv failed to export frozen CPU requirements." }

    New-Item -ItemType Directory -Path $wheelRoot -Force | Out-Null
    & $uv.Source build --project $RepoRoot --wheel --out-dir $wheelRoot
    if ($LASTEXITCODE -ne 0) { throw "uv failed to build the Nota Server wheel." }
    $serverWheels = @(Get-ChildItem -LiteralPath $wheelRoot -Filter "nota_asr_server-*.whl")
    if ($serverWheels.Count -ne 1) {
        throw "Expected one Nota Server wheel, found $($serverWheels.Count)."
    }
    $serverWheel = $serverWheels[0]

    & $uv.Source pip sync --python $runtimePython --system --break-system-packages --require-hashes --link-mode copy --index "https://download.pytorch.org/whl/cpu" --index-strategy unsafe-best-match $requirements
    if ($LASTEXITCODE -ne 0) { throw "uv failed to install frozen CPU dependencies." }
    & $uv.Source pip install --python $runtimePython --system --break-system-packages --link-mode copy --index "https://download.pytorch.org/whl/cpu" --index-strategy unsafe-best-match $serverWheel.FullName
    if ($LASTEXITCODE -ne 0) { throw "uv failed to install the Nota Server wheel." }

    # The target computer never compiles Python or PyTorch extensions. Header
    # files and import/static libraries are build-time inputs; native runtime
    # loading uses the packaged .pyd and .dll files instead.
    [long]$removedCompilationBytes = 0
    $compilationFiles = @(
        Get-ChildItem -LiteralPath $runtimePythonRoot -File -Recurse |
            Where-Object { $_.Extension -in @(".h", ".hpp", ".lib") }
    )
    foreach ($file in $compilationFiles) {
        $removedCompilationBytes += $file.Length
        Remove-Item -LiteralPath $file.FullName -Force
    }

    foreach ($directory in @("config", "resources", "models", "data", "logs", "legal")) {
        New-Item -ItemType Directory -Path (Join-Path $staging $directory) -Force | Out-Null
    }
    Copy-Item -LiteralPath (Join-Path $RepoRoot "deploy\windows\nota-asr.cmd") -Destination $staging
    Copy-Item -LiteralPath (Join-Path $RepoRoot "deploy\windows\start-server.cmd") -Destination $staging
    $configTemplate = Get-Content -LiteralPath (Join-Path $RepoRoot "deploy\windows\server.toml") -Raw
    $config = $configTemplate.Replace("{{PRELOAD_MODEL}}", $PreloadModel)
    Set-Content -LiteralPath (Join-Path $staging "config\server.toml") -Value $config -Encoding utf8NoBOM
    Set-Content -LiteralPath (Join-Path $staging "resources\server.example.toml") -Value $config -Encoding utf8NoBOM
    Copy-Item -LiteralPath (Join-Path $RepoRoot "src\nota_asr_server\model_catalog.json") -Destination (Join-Path $staging "resources\models.json")
    Copy-Item -LiteralPath (Join-Path $RepoRoot "LICENSE") -Destination (Join-Path $staging "legal\LICENSE")
    Copy-Item -LiteralPath (Join-Path $RepoRoot "NOTICE") -Destination (Join-Path $staging "legal\NOTICE")
    Copy-Item -LiteralPath (Join-Path $RepoRoot "MODEL_LICENSES.md") -Destination (Join-Path $staging "legal\MODEL_LICENSES.md")
    Copy-Item -LiteralPath (Join-Path $runtimePythonRoot "LICENSE.txt") -Destination (Join-Path $staging "legal\PYTHON_LICENSE.txt")

    & $runtimePython (Join-Path $RepoRoot "scripts\generate_license_artifacts.py") --python $runtimePython --output-dir (Join-Path $staging "legal")
    if ($LASTEXITCODE -ne 0) { throw "Windows Runtime license generation failed." }

    $serverVersion = (& $runtimePython -c "import nota_asr_server; print(nota_asr_server.__version__)").Trim()
    $componentNotice = @"
# Windows Runtime components

- Nota ASR Server: MIT; version $serverVersion.
- CPython ${PythonVersion}: Python Software Foundation License; supplied by Astral python-build-standalone through uv $UvVersion.
- Python packages: see THIRD_PARTY_LICENSES.md, THIRD_PARTY_NOTICES.txt, and bom.cyclonedx.json in this directory.
- Runtime model weights are downloaded separately and are governed by MODEL_LICENSES.md.
"@
    Set-Content -LiteralPath (Join-Path $staging "legal\RUNTIME_COMPONENTS.md") -Value $componentNotice -Encoding utf8NoBOM

    & $runtimePython -m nota_asr_server.cli config validate --config (Join-Path $staging "config\server.toml")
    if ($LASTEXITCODE -ne 0) { throw "Generated configuration failed validation." }
    & $runtimePython -c "import torch, torchaudio, nota_asr_server; assert '+cpu' in torch.__version__; print(torch.__version__, torchaudio.__version__, nota_asr_server.__version__)"
    if ($LASTEXITCODE -ne 0) { throw "Runtime import self-test failed." }
    $torchVersion = (& $runtimePython -c "import torch; print(torch.__version__)").Trim()
    $torchaudioVersion = (& $runtimePython -c "import torchaudio; print(torchaudio.__version__)").Trim()

    # Validation imports create a small lazy cache. Publish source-only Python
    # files; a target installation may cache only the modules it actually uses.
    [long]$removedBytecodeBytes = 0
    $bytecodeFiles = @(
        Get-ChildItem -LiteralPath $runtimePythonRoot -Filter "*.pyc" -File -Recurse
    )
    foreach ($file in $bytecodeFiles) {
        $removedBytecodeBytes += $file.Length
        Remove-Item -LiteralPath $file.FullName -Force
    }
    Get-ChildItem -LiteralPath $runtimePythonRoot -Directory -Recurse |
        Where-Object { $_.Name -eq "__pycache__" } |
        Sort-Object { $_.FullName.Length } -Descending |
        ForEach-Object {
            if (-not @(Get-ChildItem -LiteralPath $_.FullName -Force).Count) {
                Remove-Item -LiteralPath $_.FullName -Force
            }
        }

    Remove-Item -LiteralPath $buildRoot -Recurse -Force

    $commit = (git -C $RepoRoot rev-parse HEAD).Trim()
    $dirty = [bool](git -C $RepoRoot status --porcelain)
    $sizes = [ordered]@{}
    foreach ($directory in @("runtime", "config", "resources", "models", "data", "logs", "legal")) {
        $path = Join-Path $staging $directory
        [long]$totalBytes = 0
        Get-ChildItem -LiteralPath $path -File -Recurse | ForEach-Object { $totalBytes += $_.Length }
        $sizes[$directory] = $totalBytes
    }
    $manifest = [ordered]@{
        schema_version = 1
        product = "nota-asr-server"
        server_version = $serverVersion
        python_version = $PythonVersion
        uv_version = $UvVersion
        torch_version = $torchVersion
        torchaudio_version = $torchaudioVersion
        platform = "windows-x64"
        runtime = "cpu-online"
        preload_model = $PreloadModel
        git_commit = $commit
        git_dirty = $dirty
        built_at_utc = [DateTime]::UtcNow.ToString("o")
        pruning = [ordered]@{
            compile_bytecode = $false
            removed_compilation_files = $compilationFiles.Count
            removed_compilation_bytes = $removedCompilationBytes
            removed_bytecode_files = $bytecodeFiles.Count
            removed_bytecode_bytes = $removedBytecodeBytes
        }
        component_sizes = $sizes
    }
    $manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $staging "runtime-manifest.json") -Encoding utf8NoBOM

    Move-Item -LiteralPath $staging -Destination $outputPath
    $previousBytecodeSetting = $env:PYTHONDONTWRITEBYTECODE
    $env:PYTHONDONTWRITEBYTECODE = "1"
    try {
        & (Join-Path $outputPath "runtime\python\python.exe") -m nota_asr_server.cli doctor --config (Join-Path $outputPath "config\server.toml") --output json
        if ($LASTEXITCODE -notin @(0, 5)) { throw "Relocated Runtime doctor check failed." }
    }
    finally {
        $env:PYTHONDONTWRITEBYTECODE = $previousBytecodeSetting
    }
    # A pristine online Runtime intentionally has no model yet, so doctor
    # returns 5. The build itself succeeded and callers (including the release
    # script) must observe a successful command exit status.
    $global:LASTEXITCODE = 0
    Write-Output "Windows CPU Runtime created at $outputPath"
}
catch {
    Write-Error $_
    Write-Error "Staging directory retained for diagnosis: $staging"
    exit 1
}
