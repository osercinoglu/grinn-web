# gRINN Web Service

A comprehensive web-based interface for the gRINN (graph-based Residue Interaction Network) molecular dynamics analysis tool with persistent job storage and real-time monitoring.

## Overview

This service provides a complete web-based solution for:
- Uploading molecular dynamics trajectory files (PDB/GRO structure + XTC trajectory)
- Configuring gRINN analysis parameters
- **Persistent job storage** with PostgreSQL database
- **Real-time job monitoring** with bookmark-able URLs
- **Dedicated monitoring pages** for individual jobs
- Visualizing results through an interactive dashboard
- Downloading analysis results

## 🚀 New Features

### Database-Driven Job Management
- **PostgreSQL integration** for persistent job storage
- Complete job lifecycle tracking with timestamps
- Searchable job history and metadata
- Robust error handling and recovery

### Advanced Job Monitoring
- **Dedicated monitoring pages** at `/monitor/{job_id}`
- **Bookmark-able URLs** for checking job status anytime
- Real-time progress updates every 3 seconds
- Comprehensive job details with timeline information
- Visual progress indicators and status badges

### Enhanced User Experience
- Job submission redirects to monitoring page with bookmark reminder
- Status-specific styling and animations
- Progress bars with smooth transitions
- Error reporting with detailed troubleshooting information

## 📋 Docker Deployment Guide

The gRINN Web Service is designed to run entirely in Docker containers for production deployment. This approach provides:

- **Complete isolation** of all dependencies
- **Easy scaling** of computational workers
- **Consistent deployment** across different environments
- **Integration** with existing gRINN Docker images

### Prerequisites

- **Docker** (version 20.10+) and **Docker Compose** (version 2.0+)
- **Git** for repository management
- **8GB+ RAM** recommended for computational jobs
- **gRINN Docker image** (from the main gRINN repository)

### Quick Start (Recommended)

1. **Clone the repository:**
   ```bash
   git clone https://github.com/osercinoglu/grinn-web.git
   cd grinn-web
   ```

2. **Prepare environment:**
   ```bash
   # Copy environment template
   cp .env.example .env
   
   # Create secrets directory for production credentials
   mkdir -p secrets
   ```

3. **Build Docker images:**
   ```bash
   # Build all images (includes building gRINN dashboard if available)
   ./build-docker.sh
   ```

4. **Start all services:**
   ```bash
   # Start the complete stack
   docker-compose up -d
   
   # Check status
   docker-compose ps
   ```

5. **Access the web interface:**
   - **Frontend Dashboard:** http://localhost:8051
   - **Backend API:** http://localhost:8050/api/health
   - **gRINN Dashboard:** http://localhost:8052 (if available)

### Architecture Overview

The Docker deployment consists of these containers:

#### 🌐 **webapp** - Web Application Container
- **Purpose:** Combined frontend (Dash) and backend (Flask API) 
- **Ports:** 8050 (API), 8051 (Dashboard)
- **Features:** Job submission, monitoring, file upload
- **Scaling:** Single instance (stateless)

#### ⚙️ **worker** - Computational Worker Container  
- **Purpose:** Processes gRINN computational jobs using Docker-in-Docker
- **Features:** Celery-based job processing, gRINN Docker integration
- **Scaling:** Multiple workers (configurable replicas)
- **Resource:** CPU/memory intensive operations

#### 📊 **grinn-dashboard** - Visualization Container
- **Purpose:** Dedicated gRINN results visualization (from main gRINN repo)
- **Port:** 8052
- **Features:** Interactive network analysis, result exploration
- **Integration:** Shared volumes with worker results

#### 🗄️ **postgres** - Database Container
- **Purpose:** Persistent job storage and metadata
- **Port:** 5432 
- **Features:** Job history, status tracking, user data

#### 🔄 **redis** - Queue Container  
- **Purpose:** Celery task queue and result backend
- **Port:** 6379
- **Features:** Job queuing, distributed task management

### Configuration

#### Environment Variables (.env file)

```bash
# Database Settings
POSTGRES_PASSWORD=secure_password_here

# Storage Configuration  
DEVELOPMENT_MODE=false  # Set to true for mock storage
GCS_BUCKET_NAME=your-production-bucket
GCS_PROJECT_ID=your-gcp-project-id

# Security
SECRET_KEY=your-super-secret-key-generate-new-one

# Docker Images
GRINN_DOCKER_IMAGE=grinn:latest
GRINN_DASHBOARD_IMAGE=grinn-dashboard:latest
```

#### Production Storage Setup

For production deployment with Google Cloud Storage:

1. **Create GCS credentials:**
   ```bash
   # Place your GCS service account JSON in secrets/
   cp /path/to/your/gcs-credentials.json secrets/gcs-credentials.json
   ```

2. **Update environment:**
   ```bash
   # In .env file
   DEVELOPMENT_MODE=false
   GCS_BUCKET_NAME=your-production-bucket
   GCS_PROJECT_ID=your-gcp-project-id
   ```

#### Development Setup (Mock Storage)

For development without GCS:

```bash
# In .env file
DEVELOPMENT_MODE=true
GCS_BUCKET_NAME=mock-bucket
GCS_PROJECT_ID=mock-project
```

### Building Components

#### 1. Build gRINN Dashboard Image

First, ensure you have the main gRINN repository:

```bash
# Clone gRINN repository (if not already available)
cd ..
git clone https://github.com/your-org/grinn.git
cd grinn

# Build gRINN dashboard image
docker build -t grinn-dashboard:latest .
cd ../grinn-web
```

#### 2. Build Web Service Images

```bash
# Build webapp container (frontend + backend)
docker build -f Dockerfile.webapp -t grinn-webapp:latest .

# Build worker container  
docker build -f Dockerfile.worker -t grinn-worker:latest .

# Or use the build script
./build-docker.sh
```

### Service Management

#### Start Services
```bash
# Start all services
docker-compose up -d

# Start specific services
docker-compose up -d postgres redis
docker-compose up -d webapp
docker-compose up -d worker

# View logs
docker-compose logs -f webapp
docker-compose logs -f worker
```

#### Scale Workers
```bash
# Scale to 4 worker containers
docker-compose up -d --scale worker=4

# Check worker status
docker-compose ps worker
```

#### Stop Services
```bash
# Stop all services
docker-compose down

# Stop and remove volumes (⚠️ deletes data)
docker-compose down -v
```

### Production Deployment

#### With Nginx Reverse Proxy

For production with SSL and domain names:

```bash
# Start with production profile (includes nginx)
docker-compose --profile production up -d

# Configure SSL certificates in docker/ssl/
# Update docker/nginx.conf with your domain
```

#### Health Monitoring

All containers include health checks:

```bash
# Check container health
docker-compose ps

# View health check logs
docker inspect grinn-web_webapp_1 | grep -A 10 Health
```

#### Backup and Restore

```bash
# Backup database
docker-compose exec postgres pg_dump -U grinn_user grinn_web > backup.sql

# Restore database  
docker-compose exec -T postgres psql -U grinn_user grinn_web < backup.sql

# Backup volumes
docker run --rm -v grinn-web_postgres_data:/data -v $(pwd):/backup ubuntu tar czf /backup/postgres_backup.tar.gz /data
```

### Troubleshooting

#### Common Issues

1. **Port conflicts:**
   ```bash
   # Check what's using ports
   netstat -tulpn | grep :8050
   
   # Modify ports in docker-compose.yml if needed
   ```

2. **Container startup failures:**
   ```bash
   # Check logs
   docker-compose logs webapp
   docker-compose logs worker
   
   # Check container status
   docker-compose ps
   ```

3. **Database connection issues:**
   ```bash
   # Test database connectivity
   docker-compose exec webapp python -c "from shared.database import DatabaseManager; print('OK' if DatabaseManager().test_connection() else 'FAIL')"
   ```

4. **Worker job processing:**
   ```bash
   # Check Celery workers
   docker-compose exec worker celery -A backend.tasks inspect active
   
   # Monitor task queue
   docker-compose exec redis redis-cli monitor
   ```

#### Performance Tuning

1. **Worker scaling:**
   ```bash
   # Adjust worker replicas based on load
   docker-compose up -d --scale worker=6
   ```

2. **Resource limits:**
   ```yaml
   # Add to docker-compose.yml
   worker:
     deploy:
       resources:
         limits:
           memory: 4G
           cpus: '2.0'
   ```

3. **Database optimization:**
   ```bash
   # Increase PostgreSQL shared buffers
   # Add to postgres environment:
   POSTGRES_INITDB_ARGS: "--shared_buffers=256MB"
   ```

### Integration with gRINN Repository

The web service integrates with Docker images from the main gRINN repository:

1. **gRINN computational engine:** Used by workers for trajectory analysis
2. **gRINN dashboard:** Provides visualization interface for results
3. **Shared data volumes:** Results flow between worker and dashboard containers

### Monitoring and Logs

- **Application logs:** Available in container volumes
- **Database logs:** PostgreSQL container logs  
- **Worker logs:** Celery worker output
- **Queue monitoring:** Redis CLI or web interfaces
- **Health endpoints:** Built-in health checks for all services

## 🔧 Development Setup (Alternative)

For development without Docker, you can still run the services directly:

### Prerequisites
- Python 3.10+, PostgreSQL, Redis
- Conda/Miniconda environment

### Quick Development Setup
```bash
# Create conda environment
conda create -n grinn-web python=3.10 -y
conda activate grinn-web

# Install dependencies
pip install -r requirements.txt

# Setup database
createdb grinn_web
python -c "from shared.database import DatabaseManager; DatabaseManager().init_db()"

# Start services (3 terminals)
# Terminal 1: Backend API
python backend/api.py

# Terminal 2: Frontend Dashboard  
python frontend/app.py

# Terminal 3: Celery Worker
celery -A backend.tasks worker --loglevel=info
```

**Note:** Docker deployment is strongly recommended for production use.

### Next Steps

- Set up monitoring and alerting (Prometheus/Grafana)
- Configure automated backups
- Implement user authentication
- Set up CI/CD pipelines for updates
- Configure log aggregation (ELK stack)

## Architecture

The web service consists of:

### Frontend
- **Dash-based Web Interface**: Interactive job submission form with file upload capabilities
- **Job Monitoring**: Real-time status tracking and progress visualization  
- **Results Visualization**: Integration with gRINN dashboard for result exploration
- **Styling**: Matches the existing gRINN dashboard aesthetic

### Backend
- **Job Queue System**: Celery-based distributed task queue with Redis
- **Google Cloud Storage**: Secure file upload/download with unique job IDs
- **Docker Integration**: Containerized gRINN execution environment
- **Error Handling**: Comprehensive error reporting and job management

### Shared Components
- **Data Models**: Common data structures and validation schemas
- **Utilities**: Helper functions for file handling, job management, and cloud operations
- **Configuration**: Environment-specific settings and secrets management

## Directory Structure

```
grinn-web/
├── frontend/           # Dash web application
│   ├── app.py         # Main frontend application
│   ├── components/    # Reusable UI components
│   ├── assets/        # CSS, images, and static files
│   └── pages/         # Multi-page application structure
├── backend/           # Backend worker services
│   ├── worker.py      # Celery worker for job processing
│   ├── tasks/         # Task definitions and processing logic
│   └── grinn_runner/  # Docker-based gRINN execution wrapper
├── shared/            # Common utilities and models
│   ├── models.py      # Data models and schemas
│   ├── storage.py     # Google Cloud Storage utilities
│   ├── queue.py       # Job queue management
│   └── config.py      # Configuration management
├── config/            # Configuration files
│   ├── docker-compose.yml  # Service orchestration
│   ├── Dockerfile.frontend # Frontend container
│   ├── Dockerfile.backend  # Backend container
│   └── requirements/       # Python dependencies
└── docs/              # Documentation and setup guides
```

## Workflow

1. **Job Submission**: User uploads input files through web interface
2. **Cloud Storage**: Files uploaded to Google Cloud Storage with unique job ID
3. **Queue Processing**: Job queued for backend worker processing
4. **Computation**: Backend downloads files, runs gRINN in Docker container
5. **Result Upload**: Computation results uploaded back to cloud storage
6. **Notification**: Frontend notified of job completion status
7. **Visualization**: Results integrated with gRINN dashboard for exploration

## Setup and Installation

See the detailed setup guide in `docs/setup.md` for local development and production deployment instructions.

## Security Considerations

- Unique job IDs prevent unauthorized access to user data
- Google Cloud Storage provides secure, time-limited access tokens
- Docker containers provide isolation for computational workloads
- Input validation prevents malicious file uploads

## Contributing

Please see `CONTRIBUTING.md` for development guidelines and contribution process.
