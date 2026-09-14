$ErrorActionPreference = "Stop"

Write-Host "Creating a new test dining session for the UI..."
$response = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/dining-sessions" -Method Post -Body '{"table_number": "1", "pax": 2}' -ContentType "application/json"
$token = $response.token

Write-Host "✅ Session Token created: $token"
Write-Host "Starting Chainlit UI..."

# Clear DATABASE_URL so Chainlit's asyncpg data layer doesn't crash
$env:DATABASE_URL = ""
$env:AINZA_API_URL = "http://localhost:8000"
$env:AINZA_SESSION_TOKEN = $token

.venv\Scripts\chainlit run ui\chainlit_app.py --port 8001
