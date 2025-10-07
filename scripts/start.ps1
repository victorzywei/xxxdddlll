Param()

if (-Not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[scripts/start.ps1] Created .env from .env.example"
}

docker compose up -d --build
