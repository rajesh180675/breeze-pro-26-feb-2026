#!/bin/bash
# Breeze Options Trader PRO v10.0 — Setup Script

set -e

echo "=========================================="
echo " Breeze Options Trader PRO v10.0 — Setup"
echo "=========================================="

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.9+"
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "✅ Python $PY_VER detected"

# Create venv
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip --quiet

# Install deps
echo "📦 Installing dependencies..."
pip install -r requirements.txt --quiet

# Create directories
mkdir -p data logs .streamlit

# Create secrets template if not exists
if [ ! -f ".streamlit/secrets.toml" ]; then
    cat > .streamlit/secrets.toml << 'EOF'
# Breeze API Credentials
# Fill in your ICICI Breeze API credentials here
BREEZE_API_KEY = "your_api_key_here"
BREEZE_API_SECRET = "your_api_secret_here"
EOF
    echo "📝 Created .streamlit/secrets.toml — please fill in your credentials"
fi

echo ""
echo "=========================================="
echo " ✅ Setup complete!"
echo ""
echo " Next steps:"
echo " 1. Edit .streamlit/secrets.toml with your API key & secret"
echo " 2. Run: ./run.sh"
echo " 3. Enter your daily session token in the app"
echo "=========================================="
