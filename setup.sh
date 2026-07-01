#!/bin/bash
# 3D Printer Expert - Automated Setup Script
# Run this script to set up the agent environment from scratch
# Usage: ./setup.sh

echo "============================================"
echo "Setting up: 3D Printer Expert"
echo "============================================"
echo ""

# Check Python is installed
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python3 is not installed"
    echo "Please install Python 3.10+ from https://www.python.org/downloads/"
    exit 1
fi
echo "✓ Found $(python3 --version)"

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment already exists"
fi

# Activate virtual environment
echo "Activating virtual environment..."
source .venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip --quiet

# Install requirements
echo "Installing dependencies..."
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt --quiet
    echo "✓ Dependencies installed"
else
    echo "WARNING: requirements.txt not found"
fi

# Copy .env.example to .env if .env doesn't exist
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "✓ Created .env from .env.example"
        echo "  IMPORTANT: Edit .env with your API keys!"
    fi
else
    echo "✓ .env file already exists"
fi

# Create .tmp directory if it doesn't exist
mkdir -p .tmp
echo "✓ Created .tmp directory"

# Create memory directory and initialize database
mkdir -p memory
echo "✓ Created memory directory"
python .tmp/scripts/memory_db.py status >/dev/null 2>&1 && echo "✓ Memory database initialized" || echo "WARNING: Memory DB init skipped"

echo ""
echo "============================================"
echo "✓ SETUP COMPLETE!"
echo "============================================"
echo ""
echo "Next steps:"
echo "  1. Edit .env with your API keys (if any required)"
echo "  2. Open this folder in VS Code"
echo "  3. Select '3D Printer Expert' from Copilot Chat agent dropdown"
echo ""
echo "To activate the environment manually:"
echo "  source .venv/bin/activate"
echo ""
