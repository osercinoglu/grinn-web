#!/bin/bash

# Start development environment for gRINN Web Service

set -e

echo "🍀 Starting gRINN Web Service development environment..."

# Load environment variables
if [ -f "config/.env" ]; then
    echo "📋 Loading environment variables..."
    export $(grep -v '^#' config/.env | xargs)
fi

# Start Redis container
echo "🚀 Starting Redis..."
cd config
docker-compose -f docker-compose.dev.yml up -d redis

# Wait for Redis to be ready
echo "⏳ Waiting for Redis to be ready..."
sleep 5

# Go back to project root
cd ..

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Function to cleanup on exit
cleanup() {
    echo ""
    echo "🧹 Cleaning up..."
    cd config
    docker-compose -f docker-compose.dev.yml down
    cd ..
}

# Set trap to cleanup on script exit
trap cleanup EXIT

# Start backend API in background
echo "🔧 Starting backend API..."
export PYTHONPATH="${PWD}:${PYTHONPATH}"
python backend/api.py &
BACKEND_PID=$!

# Give backend time to start
sleep 3

# Start Celery worker in background
echo "⚙️ Starting Celery worker..."
celery -A backend.worker worker --loglevel=info --queues=grinn_jobs --concurrency=1 &
WORKER_PID=$!

# Give worker time to start
sleep 3

# Start frontend
echo "🎨 Starting frontend..."
python frontend/app.py &
FRONTEND_PID=$!

echo ""
echo "🎉 Development environment started!"
echo ""
echo "Services running:"
echo "  Frontend:  http://localhost:8050"
echo "  Backend:   http://localhost:5000"
echo "  Redis:     localhost:6379"
echo ""
echo "Press Ctrl+C to stop all services"

# Wait for any service to exit
wait