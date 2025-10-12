#!/bin/bash

# Quick Start Script for gRINN Web Service
# Run this after completing the setup to start both services

set -e

echo "🚀 Starting gRINN Web Service"
echo "============================="

# Check if we're in the right directory
if [ ! -f "frontend/app.py" ] || [ ! -f "backend/api.py" ]; then
    echo "❌ Error: Please run this script from the grinn-web repository root directory"
    exit 1
fi

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "❌ Error: .env file not found. Please run setup first or copy from .env.example"
    exit 1
fi

# Detect conda environment
CONDA_ENV=""
if conda env list | grep -q "^grinn "; then
    CONDA_ENV="grinn"
elif conda env list | grep -q "^grinn-web "; then
    CONDA_ENV="grinn-web"
else
    echo "❌ Error: No 'grinn' or 'grinn-web' conda environment found"
    echo "Please create one with: conda create -n grinn-web python=3.10 -y"
    exit 1
fi

echo "✅ Using conda environment: $CONDA_ENV"

# Function to start backend
start_backend() {
    echo "🔧 Starting Backend API on port 8050..."
    conda run -n $CONDA_ENV python backend/api.py
}

# Function to start frontend  
start_frontend() {
    echo "🌐 Starting Frontend Dashboard on port 8051..."
    conda run -n $CONDA_ENV python frontend/app.py
}

# Check command line argument
case "${1:-both}" in
    backend)
        start_backend
        ;;
    frontend)
        start_frontend
        ;;
    both)
        echo "🎯 Starting both services..."
        echo "📝 You can also start them separately with:"
        echo "   ./quick-start.sh backend   # Start only backend"
        echo "   ./quick-start.sh frontend  # Start only frontend"
        echo ""
        echo "🔧 Starting Backend API..."
        conda run -n $CONDA_ENV python backend/api.py &
        BACKEND_PID=$!
        sleep 3
        
        echo "🌐 Starting Frontend Dashboard..."
        conda run -n $CONDA_ENV python frontend/app.py &
        FRONTEND_PID=$!
        
        echo ""
        echo "✅ Services started!"
        echo "🔧 Backend API: http://localhost:8050"
        echo "🌐 Frontend Dashboard: http://localhost:8051"
        echo ""
        echo "Press Ctrl+C to stop both services"
        
        # Wait for interrupt
        trap "echo 'Stopping services...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" INT
        wait
        ;;
    *)
        echo "Usage: $0 [backend|frontend|both]"
        echo "  backend  - Start only the backend API"
        echo "  frontend - Start only the frontend dashboard"
        echo "  both     - Start both services (default)"
        exit 1
        ;;
esac