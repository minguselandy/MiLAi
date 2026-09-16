param(
    [string]$ServerName = "milai",
    [string]$CodexCommand = "codex"
)

# Only the named MCP authorization is reset; never read or print stored tokens.
$ErrorActionPreference = "Stop"
$null = Get-Command $CodexCommand -ErrorAction Stop
$loginHelp = (& $CodexCommand mcp login --help 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $loginHelp -notmatch "--scopes" -or
    $loginHelp -notmatch "--oauth-client-registration") {
    throw "This Codex CLI cannot explicitly select OAuth scopes and DCR. Report its version; no credentials were changed."
}

$scopeNames = @(
    "milai.memory.read", "milai.state.read", "milai.state.write",
    "milai.evidence.capture", "milai.evidence.revoke",
    "milai.note.read", "milai.note.write", "milai.note.delete", "milai.evidence.read"
)
$scopeArgument = $scopeNames -join ","

Write-Host "Resetting only the saved MCP authorization for $ServerName."
& $CodexCommand mcp logout $ServerName
if ($LASTEXITCODE -ne 0) { throw "MCP logout failed; login was not attempted." }

Write-Host "Starting a new browser authorization with the compact catalog's 9 scopes and DCR."
& $CodexCommand mcp login $ServerName --oauth-client-registration dcr --scopes $scopeArgument
if ($LASTEXITCODE -ne 0) { throw "MCP authorization did not complete." }

Write-Host "Login completed. Close and restart the old MiLAi test-client process before listing tools."
Write-Host "Expected with all 9 scopes actually granted: 8 tools, including milai_memory_list. Login alone does not prove this."
Write-Host "Return only the count, UTC time, and any scope field already exposed by the client."
Write-Host "Do not export or share access tokens, refresh tokens, authorization codes, or PKCE verifiers."
