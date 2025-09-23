#!/bin/bash

# Start production environment for gRINN Web Service

set -e

echo "🍀 Starting gRINN Web Service production environment..."

# Check required environment variables
required_vars=("GCS_BUCKET_NAME" "GCS_PROJECT_ID" "GCS_CREDENTIALS_PATH")

for var in "${required_vars[@]}"; do
    if [ -z "${!var}" ]; then
        echo "❌ Required environment variable $var is not set"
        exit 1
    fi
done

# Check if GCS credentials file exists
if [ ! -f "$GCS_CREDENTIALS_PATH" ]; then
    echo "❌ GCS credentials file not found: $GCS_CREDENTIALS_PATH"
    exit 1
fi

echo "✅ Environment validation passed"

# Load environment variables from .env if it exists
if [ -f "config/.env" ]; then
    echo "📋 Loading additional environment variables..."
    export $(grep -v '^#' config/.env | xargs)
fi

# Start production services
echo "🚀 Starting production services..."
cd config
docker-compose up -d

echo ""
echo "🎉 Production environment started!"
echo ""
echo "Services running:"
echo "  Frontend:  http://localhost:8050"
echo "  Backend:   http://localhost:5000"
echo "  Flower:    http://localhost:5555 (if monitoring profile enabled)"
echo ""
echo "To view logs:"
echo "  docker-compose logs -f"
echo ""
echo "To stop services:"
echo "  docker-compose down"