#!/bin/bash

# gRINN Web Service Docker Build Script
# This script builds all Docker images for the gRINN web service
# Including all GROMACS versions and the dashboard-only image

set -e

# =============================================================================
# Configuration
# =============================================================================

# All supported GROMACS versions (from grinn/build-grinn.sh)
# Order: newest first so you can start testing sooner
GROMACS_VERSIONS=(
    "2025.2" "2025.1"
    "2024.3" "2024.2" "2024.1"
    "2023.5" "2023.4" "2023.3" "2023.2" "2023.1"
    "2022.6" "2022.5" "2022.4" "2022.3" "2022.2" "2022.1"
    "2021.7"
    "2020.7"
)

# Track failed builds
FAILED_BUILDS=()

# Options
NO_CACHE=""
SKIP_WEBAPP=false
SKIP_GRINN=false

# =============================================================================
# Usage
# =============================================================================

show_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Build all Docker images for gRINN Web Service"
    echo ""
    echo "Options:"
    echo "  --no-cache      Build without Docker cache"
    echo "  --skip-webapp   Skip building webapp and worker images"
    echo "  --skip-grinn    Skip building gRINN GROMACS images"
    echo "  --help          Show this help message"
    echo ""
    echo "This script builds:"
    echo "  - grinn-webapp:latest       Frontend + Backend web application"
    echo "  - grinn-worker:latest       Celery worker for job processing"
    echo "  - grinn-dashboard:latest    Lightweight dashboard for visualization"
    echo "  - grinn:gromacs-<VERSION>   GROMACS containers for each supported version"
    echo ""
    echo "Supported GROMACS versions: ${GROMACS_VERSIONS[*]}"
    echo ""
    echo "Examples:"
    echo "  $0                    # Build everything"
    echo "  $0 --no-cache         # Build everything without cache"
    echo "  $0 --skip-grinn       # Only build webapp and worker"
    echo "  $0 --skip-webapp      # Only build gRINN images"
    echo ""
}

# =============================================================================
# Parse Arguments
# =============================================================================

while [[ $# -gt 0 ]]; do
    case $1 in
        --no-cache)
            NO_CACHE="--no-cache"
            shift
            ;;
        --skip-webapp)
            SKIP_WEBAPP=true
            shift
            ;;
        --skip-grinn)
            SKIP_GRINN=true
            shift
            ;;
        --help|-h)
            show_usage
            exit 0
            ;;
        *)
            echo "❌ Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# =============================================================================
# Main Build Process
# =============================================================================

echo "🐳 Building gRINN Web Service Docker Images"
echo "==========================================="
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Error: Docker is not running"
    exit 1
fi

# Track start time
START_TIME=$(date +%s)

# -----------------------------------------------------------------------------
# Build webapp and worker images
# -----------------------------------------------------------------------------

if [ "$SKIP_WEBAPP" = false ]; then
    echo "📦 Building Web Application Image..."
    docker build $NO_CACHE -f Dockerfile.webapp -t grinn-webapp:latest .
    echo "✅ grinn-webapp:latest built"
    echo ""

    echo "📦 Building Worker Image..."
    docker build $NO_CACHE -f Dockerfile.worker -t grinn-worker:latest .
    echo "✅ grinn-worker:latest built"
    echo ""
else
    echo "⏭️  Skipping webapp and worker builds (--skip-webapp)"
    echo ""
fi

# -----------------------------------------------------------------------------
# Build gRINN images (GROMACS versions + dashboard)
# -----------------------------------------------------------------------------

if [ "$SKIP_GRINN" = false ]; then
    # Check if grinn repository exists
    if [ ! -d "../grinn" ]; then
        echo "❌ Error: grinn repository not found at ../grinn"
        echo "   Please clone the grinn repository first:"
        echo "   git clone https://github.com/costbio/grinn.git ../grinn"
        exit 1
    fi

    # Check if build-grinn.sh exists
    if [ ! -f "../grinn/build-grinn.sh" ]; then
        echo "❌ Error: build-grinn.sh not found in ../grinn"
        exit 1
    fi

    # Make sure build-grinn.sh is executable
    chmod +x ../grinn/build-grinn.sh

    # Build dashboard-only image first
    echo "📦 Building gRINN Dashboard Image (dashboard-only)..."
    cd ../grinn
    if ./build-grinn.sh --dashboard-only $NO_CACHE; then
        echo "✅ grinn-dashboard:latest built"
    else
        echo "⚠️  Failed to build dashboard-only image"
        FAILED_BUILDS+=("dashboard-only")
    fi
    cd ../grinn-web
    echo ""

    # Build all GROMACS versions
    TOTAL_VERSIONS=${#GROMACS_VERSIONS[@]}
    CURRENT=0

    echo "🔬 Building gRINN GROMACS Images ($TOTAL_VERSIONS versions)"
    echo "============================================================"
    echo ""

    for VERSION in "${GROMACS_VERSIONS[@]}"; do
        CURRENT=$((CURRENT + 1))
        echo "📦 [$CURRENT/$TOTAL_VERSIONS] Building gRINN with GROMACS $VERSION..."
        
        cd ../grinn
        if ./build-grinn.sh "$VERSION" $NO_CACHE; then
            echo "✅ grinn:gromacs-$VERSION built"
        else
            echo "⚠️  Failed to build grinn:gromacs-$VERSION"
            FAILED_BUILDS+=("gromacs-$VERSION")
        fi
        cd ../grinn-web
        echo ""
    done
else
    echo "⏭️  Skipping gRINN image builds (--skip-grinn)"
    echo ""
fi

# =============================================================================
# Summary
# =============================================================================

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))
ELAPSED_MIN=$((ELAPSED / 60))
ELAPSED_SEC=$((ELAPSED % 60))

echo ""
echo "==========================================="
echo "🏁 Build Complete!"
echo "==========================================="
echo ""
echo "⏱️  Total time: ${ELAPSED_MIN}m ${ELAPSED_SEC}s"
echo ""

# Report failed builds
if [ ${#FAILED_BUILDS[@]} -gt 0 ]; then
    echo "⚠️  Failed builds (${#FAILED_BUILDS[@]}):"
    for FAILED in "${FAILED_BUILDS[@]}"; do
        echo "   - $FAILED"
    done
    echo ""
fi

# Show available images
echo "📋 Available gRINN Docker Images:"
echo "-------------------------------------------"
echo ""
echo "Web Service Images:"
docker images --format "   {{.Repository}}:{{.Tag}}\t{{.Size}}" | grep -E "^   grinn-(webapp|worker)" || echo "   (none)"
echo ""
echo "Dashboard Image:"
docker images --format "   {{.Repository}}:{{.Tag}}\t{{.Size}}" | grep -E "^   grinn-dashboard" || echo "   (none)"
echo ""
echo "GROMACS Images:"
docker images --format "   {{.Repository}}:{{.Tag}}\t{{.Size}}" | grep -E "^   grinn:gromacs-" | sort -t'-' -k2 -V -r || echo "   (none)"
echo ""

# Calculate total disk usage
TOTAL_SIZE=$(docker images --format "{{.Size}}" | grep -E "grinn" | awk '{
    size=$1;
    if (index(size, "GB")) { gsub("GB","",size); total+=size*1024 }
    else if (index(size, "MB")) { gsub("MB","",size); total+=size }
    else if (index(size, "KB")) { gsub("KB","",size); total+=size/1024 }
} END { printf "%.1f GB", total/1024 }')
echo "💾 Total disk usage: $TOTAL_SIZE (approximate)"
echo ""

echo "Next steps:"
echo "1. Copy .env.example to .env and configure your environment"
echo "2. Set EXAMPLE_DATA_PATH in .env to your example data directory"
echo "3. Create storage directory: mkdir -p /data/grinn-jobs"
echo "4. Run: docker-compose up -d"
echo ""

# Exit with error if any builds failed
if [ ${#FAILED_BUILDS[@]} -gt 0 ]; then
    exit 1
fi
echo "For multi-worker deployments:"
echo "1. Set up NFS storage (see README.md)"
echo "2. Generate worker token: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
echo "3. Configure WORKER_REGISTRATION_TOKEN in .env"