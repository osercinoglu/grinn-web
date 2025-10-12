#!/bin/bash

# gRINN Web Service - Enhanced Build Script
# This script builds and tests the enhanced gRINN web service with job queue functionality

set -e

echo "🔧 Building Enhanced gRINN Web Service..."

# Navigate to grinn-web directory
cd "$(dirname "$0")"

# Clean up any existing containers
echo "🧹 Cleaning up existing containers..."
docker compose down --volumes --remove-orphans 2>/dev/null || true

# Build the containers
echo "🏗️  Building Docker containers..."
docker compose build --no-cache

# Start the services
echo "🚀 Starting services..."
docker compose up -d

# Wait for services to be ready
echo "⏳ Waiting for services to be ready..."
sleep 10

# Check service health
echo "🔍 Checking service health..."

# Check PostgreSQL
if docker compose exec -T postgres pg_isready -U grinn_user -d grinn_web; then
    echo "✅ PostgreSQL is ready"
else
    echo "❌ PostgreSQL is not ready"
    exit 1
fi

# Check Redis
if docker compose exec -T redis redis-cli ping | grep -q PONG; then
    echo "✅ Redis is ready"
else
    echo "❌ Redis is not ready"
    exit 1
fi

# Check if webapp is responding
echo "🌐 Checking web application..."
sleep 5

if curl -f http://localhost:8051/health > /dev/null 2>&1; then
    echo "✅ Frontend is responding on port 8051"
else
    echo "⚠️  Frontend health check failed, but service may still be starting"
fi

if curl -f http://localhost:8050/api/health > /dev/null 2>&1; then
    echo "✅ Backend API is responding on port 8050"
else
    echo "⚠️  Backend API health check failed, but service may still be starting"
fi

echo ""
echo "🎉 Enhanced gRINN Web Service is running!"
echo ""
echo "🔗 Access URLs:"
echo "   Main Interface:  http://localhost:8051"
echo "   Job Queue:       http://localhost:8051/queue"
echo "   Backend API:     http://localhost:8050/api"
echo ""
echo "✨ New Features:"
echo "   • Privacy settings for jobs"
echo "   • Public job queue with filtering"
echo "   • Enhanced job monitoring"
echo "   • No polling on main page"
echo ""
echo "📋 Next Steps:"
echo "   1. Open http://localhost:8051 in your browser"
echo "   2. Upload trajectory files and submit a job"
echo "   3. Check 'Keep job details private' if desired"
echo "   4. Monitor job progress in the new tab that opens"
echo "   5. View all jobs at http://localhost:8051/queue"
echo ""
echo "🛑 To stop: docker compose down"
echo "📊 To view logs: docker compose logs -f"