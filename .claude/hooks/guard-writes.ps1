# PreToolUse guard: block Edit/Write/NotebookEdit outside the workspace and log the attempt.
# Fails closed: any unexpected input or error denies the write.

$ErrorActionPreference = 'Stop'

$root = if ($env:CLAUDE_PROJECT_DIR) { $env:CLAUDE_PROJECT_DIR } else { (Get-Location).Path }
$root = [System.IO.Path]::GetFullPath($root).TrimEnd('\')
$logDir = Join-Path $root '.claude\logs'
$logFile = Join-Path $logDir 'outside-workspace.log'
$maxLogBytes = 1MB

function Write-Decision([string]$decision, [string]$reason) {
    @{
        hookSpecificOutput = @{
            hookEventName            = 'PreToolUse'
            permissionDecision       = $decision
            permissionDecisionReason = $reason
        }
    } | ConvertTo-Json -Compress -Depth 5
}

# Keep one line per entry: strip control characters from values that come from the model.
function Get-SafeText([string]$text) {
    return ($text -replace '[\x00-\x1F\x7F]', '?')
}

function Write-Log([string]$line) {
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    if ((Test-Path $logFile) -and ((Get-Item $logFile).Length -gt $maxLogBytes)) {
        Move-Item -Force -Path $logFile -Destination "$logFile.1"
    }
    if (-not (Test-Path $logFile)) {
        Add-Content -Path $logFile -Value "# Blocked writes outside $root (newest at bottom)" -Encoding utf8
    }
    Add-Content -Path $logFile -Value $line -Encoding utf8
}

# True if any existing part of the path (below the workspace root) is a symlink or junction.
function Test-HasReparsePoint([string]$full) {
    $current = $full
    while ($current -and $current.Length -gt $root.Length) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { return $true }
        }
        $current = Split-Path -Parent $current
    }
    return $false
}

try {
    $raw = [Console]::In.ReadToEnd()
    if ([string]::IsNullOrWhiteSpace($raw)) {
        Write-Decision 'deny' 'Blocked: write guard received no input.'
        exit 0
    }
    $data = $raw | ConvertFrom-Json
    $tool = [string]$data.tool_name
    $target = $data.tool_input.file_path
    if (-not $target) { $target = $data.tool_input.notebook_path }
    if (-not $target) {
        Write-Decision 'deny' "Blocked: $tool call has no file path, so the write guard cannot verify it."
        exit 0
    }
    $target = [string]$target

    # Drive-relative paths (C:foo) depend on hidden per-drive state; deny them outright.
    if ($target -match '^[A-Za-z]:(?![\\/])') {
        Write-Decision 'deny' "Blocked: drive-relative path '$target' is not allowed."
        exit 0
    }

    # Combine handles both relative and absolute targets; GetFullPath resolves any ..\ segments.
    $full = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($root, $target))

    $inside = $full.StartsWith($root + '\', [System.StringComparison]::OrdinalIgnoreCase)
    $reason = $null
    if (-not $inside) {
        $reason = "is outside the workspace $root"
    }
    elseif ($full.Substring($root.Length + 1) -match ':') {
        $reason = 'uses an alternate data stream (a colon in the name)'
    }
    elseif ($full.StartsWith((Join-Path $root '.claude') + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        $reason = 'is inside .claude\ (hooks, settings and logs are protected)'
    }
    elseif (Test-HasReparsePoint $full) {
        $reason = 'passes through a symlink or junction'
    }

    if (-not $reason) {
        exit 0
    }

    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $line = "{0} | BLOCKED | {1} | {2} | session {3}" -f $stamp, (Get-SafeText $tool), (Get-SafeText $full), (Get-SafeText ([string]$data.session_id))
    Write-Log $line

    Write-Decision 'deny' "Blocked: $full $reason. Attempt logged."
    exit 0
}
catch {
    Write-Decision 'deny' "Blocked: write guard could not verify the path ($($_.Exception.Message))."
    exit 0
}
