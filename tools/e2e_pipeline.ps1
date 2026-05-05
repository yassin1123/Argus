# Requires: docker compose up, OPENAI_API_KEY set for worker/backend
$base = $env:ARGUS_API_URL
if (-not $base) { $base = "http://localhost:8000" }

$body = @{
  query = "Should a UK startup expand to Germany or France first? Give a concise strategic view."
  title = "E2E test"
} | ConvertTo-Json

$r = Invoke-RestMethod -Method POST -Uri "$base/api/sessions" -ContentType "application/json" -Body $body
$sid = $r.session_id
Write-Host "Created session $sid"

Invoke-RestMethod -Method POST -Uri "$base/api/sessions/$sid/run" | Out-Null
Write-Host "Run enqueued; poll GET $base/api/sessions/$sid until status is complete"

do {
  Start-Sleep -Seconds 3
  $s = Invoke-RestMethod -Uri "$base/api/sessions/$sid"
  Write-Host "status=$($s.status) agents=$($s.agent_outputs.Count)"
} while ($s.status -ne "complete" -and $s.status -ne "failed")

if ($s.status -eq "complete") {
  Write-Host "OK: report recommendation = $($s.report.recommendation)"
  exit 0
}
Write-Host "FAILED"
exit 1
