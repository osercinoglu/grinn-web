#!/bin/bash
# Remote Worker Deployment Script for gRINN Web Service
# ======================================================

set -e

echo "⚙️  Starting gRINN Remote Worker Deployment"

# Check if environment file exists
if [ ! -f ".env.worker" ]; then
    echo "❌ Error: .env.worker file not found!"
    echo "📝 Please copy .env.worker.example to .env.worker and configure it."
    exit 1
fi

# Load environment variables
source .env.worker

# Check NFS mount if using shared storage
NFS_STORAGE_PATH="${NFS_STORAGE_PATH:-/mnt/grinn-storage}"
if [ -d "$NFS_STORAGE_PATH" ]; then
    echo "✅ NFS storage mounted: $NFS_STORAGE_PATH"
    # Test write access
    if touch "$NFS_STORAGE_PATH/.write-test" 2>/dev/null; then
        rm "$NFS_STORAGE_PATH/.write-test"
        echo "✅ NFS write access: OK"
    else
        echo "❌ Error: Cannot write to NFS storage at $NFS_STORAGE_PATH"
        exit 1
    fi
else
    echo "⚠️  Warning: NFS storage not found at $NFS_STORAGE_PATH"
    echo "📝 Make sure NFS is mounted for multi-worker setups"
fi

echo "📋 Worker Configuration:"
echo "   - Frontend Host: ${FRONTEND_HOST}"
echo "   - Facility: ${WORKER_FACILITY}"
echo "   - Worker Replicas: ${WORKER_REPLICAS}"
echo "   - CPU Limit: ${WORKER_CPU_LIMIT}"
echo "   - Memory Limit: ${WORKER_MEMORY_LIMIT}"
echo "   - gRINN Image: ${GRINN_DOCKER_IMAGE}"
echo "   - Storage Path: ${NFS_STORAGE_PATH}"

# Test connectivity to frontend
echo "🔗 Testing connection to frontend server..."

if ! nc -z ${FRONTEND_HOST} 6379; then
    echo "❌ Cannot connect to Redis at ${FRONTEND_HOST}:6379"
    echo "💡 Check network connectivity and firewall settings"
    exit 1
else
    echo "✅ Redis connection: OK"
fi

if ! nc -z ${FRONTEND_HOST} 5432; then
    echo "❌ Cannot connect to Database at ${FRONTEND_HOST}:5432"  
    echo "💡 Check network connectivity and firewall settings"
    exit 1
else
    echo "✅ Database connection: OK"
fi

if ! nc -z ${FRONTEND_HOST} 5000; then
    echo "❌ Cannot connect to Backend API at ${FRONTEND_HOST}:5000"  
    echo "💡 Check network connectivity and firewall settings"
    exit 1
else
    echo "✅ Backend API connection: OK"
fi

# Check if gRINN Docker image exists
echo "🔍 Checking gRINN Docker image..."
if docker images -q ${GRINN_DOCKER_IMAGE} | grep -q .; then
    echo "✅ gRINN image found: ${GRINN_DOCKER_IMAGE}"
else
    echo "⚠️  gRINN image not found: ${GRINN_DOCKER_IMAGE}"
    echo "📥 You may need to build or pull the gRINN image first"
    echo "🔗 See: https://github.com/your-org/grinn for build instructions"
fi

# Build worker image
echo "🔨 Building worker image..."
docker build -f Dockerfile.worker -t grinn-worker:latest .

# Start worker services
echo "⚙️  Starting worker services..."
docker-compose -f docker-compose.worker.yml --env-file .env.worker up -d

# Wait for workers to be ready
echo "⏳ Waiting for workers to start..."
sleep 15

# Check worker health
echo "🔍 Checking worker status..."
docker-compose -f docker-compose.worker.yml ps

# Test job processing capability
echo "🧪 Testing worker capabilities..."
if docker run --rm ${GRINN_DOCKER_IMAGE:-grinn:latest} --help > /dev/null 2>&1; then
    echo "✅ gRINN executable: Ready"
else
    echo "❌ gRINN executable: Not accessible"
fi

echo ""
echo "🎉 Remote worker deployment complete!"
echo ""
echo "📊 Worker Status:"
docker-compose -f docker-compose.worker.yml ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"
echo ""
echo "📡 Connection Info:"
echo "   - Connected to: ${FRONTEND_HOST}"
echo "   - Facility ID: ${WORKER_FACILITY}"
echo "   - Active Workers: ${WORKER_REPLICAS}"
echo "   - Storage: ${NFS_STORAGE_PATH}"
echo ""
echo "📈 Monitoring:"
echo "   - Worker logs: docker-compose -f docker-compose.worker.yml logs -f"
echo "   - Scaling: docker-compose -f docker-compose.worker.yml up -d --scale worker=N"
echo ""
echo "⚠️  Notes:"
echo "   - Workers will automatically connect to the job queue"
echo "   - Ensure NFS is properly mounted for shared storage"
echo "   - Monitor worker logs for job processing status"