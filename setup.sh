#!/bin/bash

# Setup script for gRINN Web Service
# This script sets up the development environment

set -e

echo "🍀 Setting up gRINN Web Service..."

# Check Python version
python_version=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1-2)
required_version="3.10"

if [ "$(printf '%s\n' "$required_version" "$python_version" | sort -V | head -n1)" != "$required_version" ]; then
    echo "❌ Python 3.10+ is required (found $python_version)"
    exit 1
fi

echo "✅ Python version $python_version is compatible"

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

echo "✅ Docker is available"

# Check Docker Compose
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "❌ Docker Compose is not available. Please install Docker Compose."
    exit 1
fi

echo "✅ Docker Compose is available"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "📦 Creating Python virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "⬆️ Upgrading pip..."
pip install --upgrade pip

# Install requirements
echo "📚 Installing Python dependencies..."
pip install -r config/requirements/dev.txt

# Create .env file if it doesn't exist
if [ ! -f "config/.env" ]; then
    echo "📝 Creating environment configuration..."
    cp config/.env.example config/.env
    echo "⚠️  Please edit config/.env with your actual configuration values"
fi

# Create directories
echo "📁 Creating necessary directories..."
mkdir -p logs
mkdir -p data/uploads
mkdir -p data/temp

# Check if gRINN Docker image exists
if ! docker image inspect grinn:latest >/dev/null 2>&1; then
    echo "⚠️  gRINN Docker image 'grinn:latest' not found"
    echo "   Please build the gRINN Docker image first or update GRINN_DOCKER_IMAGE in .env"
fi

echo ""
echo "🎉 Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit config/.env with your configuration"
echo "2. Set up Google Cloud Storage bucket and credentials"
echo "3. Build or pull the gRINN Docker image"
echo "4. Start the development environment:"
echo "   ./scripts/start-dev.sh"
echo ""
echo "For production deployment, see docs/deployment.md"