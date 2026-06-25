#!/bin/bash
# Setup virtual environment and run the compliance engine
# Usage: bash setup_and_run.sh [firm_A|firm_B]

FIRM=${1:-firm_A}

echo "=== InterOpera Compliance Engine Setup ==="

# Create venv if it doesn't exist
if [ ! -d "venv" ]; then
    echo "[1/3] Creating virtual environment..."
    python3 -m venv venv
else
    echo "[1/3] Virtual environment already exists, skipping..."
fi

# Activate and install
echo "[2/3] Installing dependencies..."
source venv/bin/activate
pip install -q -r requirements.txt

# Run
echo "[3/3] Running for firm: $FIRM"
echo ""
python main.py --firm "$FIRM" --no-narrative

