#!/bin/bash

# gRINN Web Service Docker Build Script
# This script builds all Docker images for the gRINN web service

set -e

echo "🐳 Building gRINN Web Service Docker Images"
echo "==========================================="

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Error: Docker is not running"
    exit 1
fi

# Build web application image (frontend + backend)
echo "📦 Building Web Application Image..."
docker build -f Dockerfile.webapp -t grinn-webapp:latest .

# Build worker image
echo "📦 Building Worker Image..."
docker build -f Dockerfile.worker -t grinn-worker:latest .

# Check if grinn repository exists to build dashboard
if [ -d "../grinn" ]; then
    echo "📦 Building gRINN Dashboard Image..."
    cd ../grinn
    docker build -t grinn-dashboard:latest .
    cd ../grinn-web
else
    echo "⚠️  Warning: grinn repository not found at ../grinn"
    echo "   You'll need to build the gRINN dashboard image separately:"
    echo "   1. Clone the grinn repository"
    echo "   2. Build the image: docker build -t grinn-dashboard:latest ."
    echo "   3. Or pull from registry if available"
fi

echo ""
echo "✅ Docker images built successfully!"
echo ""
echo "Available images:"
docker images | grep -E "(grinn-webapp|grinn-worker|grinn-dashboard)" || echo "No gRINN images found"

echo ""
echo "Next steps:"
echo "1. Copy .env.example to .env and configure your environment"
echo "2. Create storage directory: mkdir -p /data/grinn-jobs"
echo "3. Run: docker-compose up -d"
echo ""
echo "For multi-worker deployments:"
echo "1. Set up NFS storage (see README.md)"
echo "2. Generate worker token: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
echo "3. Configure WORKER_REGISTRATION_TOKEN in .env"