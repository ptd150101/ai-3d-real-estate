@echo off
setlocal

set "COMMAND=%~1"
if "%COMMAND%"=="" set "COMMAND=infra"
set "ROOT=%~dp0.."
set "ENV_FILE=%ROOT%\.env"

if not exist "%ENV_FILE%" (
  copy "%ROOT%\.env.example" "%ENV_FILE%" >nul
  echo Created .env from .env.example. Set the required local credentials before continuing.
)

if /I "%COMMAND%"=="infra" goto infra
if /I "%COMMAND%"=="api" goto api
if /I "%COMMAND%"=="worker" goto worker
if /I "%COMMAND%"=="web" goto web

echo Usage: scripts\dev.bat ^{infra^|api^|worker^|web^}
exit /b 2

:infra
pushd "%ROOT%"
docker compose up -d postgres redis minio minio-init
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%

:api
pushd "%ROOT%\apps\api"
uv run --env-file "%ENV_FILE%" alembic upgrade head
if errorlevel 1 (
  set "EXIT_CODE=%ERRORLEVEL%"
  popd
  exit /b %EXIT_CODE%
)
uv run --env-file "%ENV_FILE%" uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%

:worker
pushd "%ROOT%\apps\api"
uv run --env-file "%ENV_FILE%" python -m app.worker
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%

:web
pushd "%ROOT%"
npm install --prefix apps/web
if errorlevel 1 (
  set "EXIT_CODE=%ERRORLEVEL%"
  popd
  exit /b %EXIT_CODE%
)
npm --prefix apps/web run dev
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%
