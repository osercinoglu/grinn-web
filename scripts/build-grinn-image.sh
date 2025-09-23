#!/bin/bash

# Build gRINN Docker image script
# This script builds a Docker image containing the gRINN tool

set -e

echo "🍀 Building gRINN Docker image..."

# Check if grinn directory exists
if [ ! -d "../grinn" ]; then
    echo "❌ gRINN source directory not found at ../grinn"
    echo "   Please ensure the gRINN repository is available"
    exit 1
fi

# Create temporary build context
BUILD_DIR="temp_grinn_build"
echo "📁 Creating build context..."
mkdir -p "$BUILD_DIR"

# Copy gRINN files
echo "📋 Copying gRINN files..."
cp -r ../grinn/* "$BUILD_DIR/"

# Create Dockerfile for gRINN
cat > "$BUILD_DIR/Dockerfile" << 'EOF'
FROM continuumio/miniconda3:latest

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy environment file
COPY environment.yml .

# Create conda environment
RUN conda env create -f environment.yml

# Make RUN commands use the new environment
SHELL ["conda", "run", "-n", "grinn", "/bin/bash", "-c"]

# Copy gRINN source
COPY . .

# Install additional Python packages if needed
RUN conda run -n grinn pip install --no-deps .

# Create entrypoint script
RUN echo '#!/bin/bash\nconda run -n grinn python "$@"' > /entrypoint.sh && \
    chmod +x /entrypoint.sh

# Set entrypoint
ENTRYPOINT ["/entrypoint.sh"]

# Default command
CMD ["grinn_workflow.py", "--help"]
EOF

# Build Docker image
echo "🔨 Building Docker image..."
cd "$BUILD_DIR"
docker build -t grinn:latest .
cd ..

# Cleanup
echo "🧹 Cleaning up..."
rm -rf "$BUILD_DIR"

echo "✅ gRINN Docker image built successfully!"
echo ""
echo "Image: grinn:latest"
echo "Test with: docker run --rm grinn:latest --help"