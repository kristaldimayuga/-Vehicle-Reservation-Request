<#
.SYNOPSIS
  Creates the GovFleet PostgreSQL role and database from values in .env.

.DESCRIPTION
  Prompts for the PostgreSQL superuser (default: postgres) password
  interactively; it is never stored. The app role's password is read from .env.

.EXAMPLE
  .\scripts\setup_db.ps1
  .\scripts\setup_db.ps1 -SuperUser postgres -PsqlPath "C:\Program Files\PostgreSQL\17\bin\psql.exe"
#>
param(
    [string]$SuperUser = "postgres",
    [string]$PsqlPath = "C:\Program Files\PostgreSQL\17\bin\psql.exe"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root ".env"

if (-not (Test-Path $envFile)) { throw ".env not found. Copy .env.example to .env first." }
if (-not (Test-Path $PsqlPath)) { throw "psql not found at '$PsqlPath'. Pass -PsqlPath." }

$vars = @{}
Get-Content $envFile | Where-Object { $_ -match '^\s*[A-Z_]+\s*=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2
    $vars[$k.Trim()] = $v.Trim()
}
foreach ($key in "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT") {
    if (-not $vars[$key]) { throw "$key missing in .env" }
}

& $PsqlPath -h $vars.DB_HOST -p $vars.DB_PORT -U $SuperUser -d postgres `
    -v "app_user=$($vars.DB_USER)" `
    -v "app_password=$($vars.DB_PASSWORD)" `
    -v "db_name=$($vars.DB_NAME)" `
    -f (Join-Path $PSScriptRoot "setup_db.sql")

if ($LASTEXITCODE -ne 0) { throw "Database setup failed (psql exit code $LASTEXITCODE)." }
