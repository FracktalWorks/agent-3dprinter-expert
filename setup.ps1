# 3D Printer Expert - Automated Setup Script
# Run this script to set up the agent environment from scratch
# Usage: .\setup.ps1

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "Setting up: 3D Printer Expert" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Check Python is installed
$pythonVersion = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Python is not installed or not in PATH" -ForegroundColor Red
    Write-Host "Please install Python 3.10+ from https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}
Write-Host "✓ Found $pythonVersion" -ForegroundColor Green

# Create virtual environment if it doesn't exist
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Failed to create virtual environment" -ForegroundColor Red
        exit 1
    }
    Write-Host "✓ Virtual environment created" -ForegroundColor Green
} else {
    Write-Host "✓ Virtual environment already exists" -ForegroundColor Green
}

# Activate virtual environment
Write-Host "Activating virtual environment..." -ForegroundColor Yellow
& .\.venv\Scripts\Activate.ps1

# Upgrade pip
Write-Host "Upgrading pip..." -ForegroundColor Yellow
python -m pip install --upgrade pip --quiet

# Install requirements
Write-Host "Installing dependencies..." -ForegroundColor Yellow
if (Test-Path "requirements.txt") {
    pip install -r requirements.txt --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Failed to install requirements" -ForegroundColor Red
        exit 1
    }
    Write-Host "✓ Dependencies installed" -ForegroundColor Green
} else {
    Write-Host "WARNING: requirements.txt not found" -ForegroundColor Yellow
}

# Copy .env.example to .env if .env doesn't exist
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host "✓ Created .env from .env.example" -ForegroundColor Green
        Write-Host "  IMPORTANT: Edit .env with your API keys!" -ForegroundColor Yellow
    }
} else {
    Write-Host "✓ .env file already exists" -ForegroundColor Green
}

# Create .tmp directory if it doesn't exist
if (-not (Test-Path ".tmp")) {
    New-Item -ItemType Directory -Path ".tmp" | Out-Null
    Write-Host "✓ Created .tmp directory" -ForegroundColor Green
}

# Create memory directory if it doesn't exist
if (-not (Test-Path "memory")) {
    New-Item -ItemType Directory -Path "memory" | Out-Null
    Write-Host "✓ Created memory directory" -ForegroundColor Green
}

# Initialize memory database
Write-Host "Initializing memory database..." -ForegroundColor Yellow
python .tmp/scripts/memory_db.py status 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Memory database initialized" -ForegroundColor Green
} else {
    Write-Host "WARNING: Memory database initialization skipped (run manually)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "✓ SETUP COMPLETE!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor White
Write-Host "  1. Edit .env with your API keys (if any required)" -ForegroundColor White
Write-Host "  2. Open this folder in VS Code" -ForegroundColor White
Write-Host "  3. Select '3D Printer Expert' from Copilot Chat agent dropdown" -ForegroundColor White
Write-Host ""
Write-Host "To activate the environment manually:" -ForegroundColor Gray
Write-Host "  .\.venv\Scripts\Activate.ps1" -ForegroundColor Gray
Write-Host ""
