param(
    [ValidateSet("infra", "api", "worker", "web")]
    [string]$Command = "infra"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$EnvFile = Join-Path $Root ".env"

if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $Root ".env.example") $EnvFile
    Write-Host "Created .env from .env.example. Set the required local credentials before continuing."
}

switch ($Command) {
    "infra" {
        Push-Location $Root
        try {
            docker compose up -d postgres redis minio minio-init
        }
        finally {
            Pop-Location
        }
    }
    "api" {
        Push-Location (Join-Path $Root "apps/api")
        try {
            uv run --env-file $EnvFile alembic upgrade head
            uv run --env-file $EnvFile uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
        }
        finally {
            Pop-Location
        }
    }
    "worker" {
        Push-Location (Join-Path $Root "apps/api")
        try {
            uv run --env-file $EnvFile python -m app.worker
        }
        finally {
            Pop-Location
        }
    }
    "web" {
        Push-Location $Root
        try {
            npm install --prefix apps/web
            npm --prefix apps/web run dev
        }
        finally {
            Pop-Location
        }
    }
}
