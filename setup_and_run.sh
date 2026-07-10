#!/bin/bash
FIRM=${1:-firm_A}
echo "=== InterOpera Setup ==="
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -q -r requirements.txt
python main.py --firm "$FIRM"
