#!/bin/bash
# Breeze Options Trader PRO v10.0 — Launch Script

set -e

echo "=========================================="
echo " Breeze Options Trader PRO v10.0"
echo "=========================================="

# Activate venv if exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Create required dirs
mkdir -p data logs

echo "🚀 Starting app on http://localhost:8501"
echo "   Press Ctrl+C to stop"
echo ""

streamlit run app.py \
    --server.port 8501 \
    --server.address 0.0.0.0 \
    --browser.gatherUsageStats false \
    --theme.base dark
