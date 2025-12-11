#!/bin/bash
# Frontend Deployment Script for gRINN Web Service
# =================================================

set -e

echo "🚀 Starting gRINN Web Service Frontend Deployment"

# Check if environment file exists
if [ ! -f ".env.frontend" ]; then
    echo "❌ Error: .env.frontend file not found!"
    echo "📝 Please copy .env.frontend.example to .env.frontend and configure it."
    exit 1
fi

# Create storage directory if it doesn't exist
STORAGE_PATH="${STORAGE_PATH:-/data/grinn-jobs}"
mkdir -p "$STORAGE_PATH"
echo "✅ Storage directory ready: $STORAGE_PATH"

# Load environment variables
source .env.frontend

echo "📋 Frontend Configuration:"
echo "   - Storage Path: ${STORAGE_PATH:-/data/grinn-jobs}"
echo "   - Frontend IP: ${FRONTEND_PUBLIC_IP}"
echo "   - Job Retention: ${JOB_FILE_RETENTION_HOURS:-72} hours"

# Build images if they don't exist
echo "🔨 Building frontend images..."
docker build -f Dockerfile.webapp -t grinn-webapp:latest .

# Start frontend services
echo "🌐 Starting frontend services..."
docker-compose -f docker-compose.frontend.yml --env-file .env.frontend up -d

# Wait for services to be ready
echo "⏳ Waiting for services to start..."
sleep 10

# Check service health
echo "🔍 Checking service health..."

# Check database
if docker-compose -f docker-compose.frontend.yml exec postgres pg_isready -U grinn_user -d grinn_web; then
    echo "✅ Database: Ready"
else
    echo "❌ Database: Not ready"
fi

# Check Redis
if docker-compose -f docker-compose.frontend.yml exec redis redis-cli ping; then
    echo "✅ Redis: Ready" 
else
    echo "❌ Redis: Not ready"
fi

# Check web application
if curl -f -s http://localhost:8050/api/health > /dev/null; then
    echo "✅ Backend API: Ready"
else
    echo "❌ Backend API: Not ready"
fi

if curl -f -s -I http://localhost:8051 > /dev/null; then
    echo "✅ Frontend Dashboard: Ready"
else
    echo "❌ Frontend Dashboard: Not ready"
fi

echo ""
echo "🎉 Frontend deployment complete!"
echo ""
echo "📱 Access Points:"
echo "   - Frontend Dashboard: http://localhost:8051"
echo "   - Backend API: http://localhost:8050"
echo "   - API Health: http://localhost:8050/api/health"
echo ""
echo "🔗 For Remote Workers:"
echo "   - Frontend Host: ${FRONTEND_PUBLIC_IP:-localhost}"
echo "   - Redis Port: 6379"
echo "   - Database Port: 5432"
echo ""
echo "⚠️  Security Notes:"
echo "   - Ensure ports 5432 and 6379 are accessible from worker machines"
echo "   - Consider using VPN or firewall rules to restrict access"
echo "   - Use strong passwords in .env.frontend"
echo ""

# Show running containers
echo "📦 Running containers:"
docker-compose -f docker-compose.frontend.yml ps