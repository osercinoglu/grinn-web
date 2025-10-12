# i-gRINN Web Service

A comprehensive and interactive web interface for the gRINN (get Residue iNteraction eNergies and Networks) tool with persistent job storage and distributed processing capabilities.

## ✨ Key Features

- 🚀 **Easy Job Submission** - Upload trajectory files and configure analysis parameters
- 📊 **Real-time Monitoring** - Track job progress with dedicated monitoring pages  
- 🔒 **Privacy Controls** - Option to hide job details from public queue
- 💾 **Persistent Storage** - Jobs and results saved with full history
- 🐳 **Docker Integration** - Containerized gRINN processing with scaling support
- 🌐 **Web Dashboard** - Interactive interface for job management
- 🏢 **Distributed Architecture** - Frontend and workers can run at different facilities

## Overview

This service provides a complete web-based solution for:
- Uploading molecular dynamics trajectory files (PDB/GRO structure + XTC trajectory)
- Configuring gRINN analysis parameters
- **Persistent job storage** with PostgreSQL database
- **Real-time job monitoring** with bookmark-able URLs
- **Dedicated monitoring pages** for individual jobs
- **Distributed processing** with remote computational workers
- Visualizing results through an interactive dashboard
- Downloading analysis results

## 🚀 Features

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

### Distributed Architecture
- **Frontend hosting** - Web interface, database, and job queue
- **Remote workers** - Computational facilities can host processing nodes
- **Scalable processing** - Multiple workers at different locations
- **Network connectivity** - Secure connections between frontend and workers

## 📋 Deployment Options

The gRINN Web Service supports three deployment modes:

### 1. Distributed Production Deployment (Recommended)

This architecture separates the frontend (web interface, database, job queue) from computational workers, allowing workers to run at remote facilities while the frontend can be hosted anywhere.

**Frontend Server:**
- Web interface (Dash + Flask)
- PostgreSQL database
- Redis job queue
- gRINN Dashboard

**Remote Workers:**
- Celery workers
- Docker containers for gRINN processing  
- Network connection to frontend services

### 2. Single-Host Docker Deployment

Traditional deployment where all components run on a single machine.

### 3. Development Setup

Local development with Conda environment and mock services.

---

## 🏢 Distributed Production Deployment

### Architecture Overview

```
Frontend Server (Public)          Remote Facility Workers
├── Web Interface (Port 80/443)   ├── Worker 1 (gRINN Processing)
├── PostgreSQL (Port 5432) ←──────┼── Worker 2 (gRINN Processing)  
├── Redis Queue (Port 6379) ←─────├── Worker 3 (gRINN Processing)
└── gRINN Dashboard               └── ... (Scalable)
```

### Prerequisites

**Frontend Server:**
- Docker & Docker Compose
- Public network access for web interface
- Open ports for worker connections (5432, 6379)

**Worker Facilities:**
- Docker installed
- Network access to frontend server
- gRINN Docker image

### Frontend Deployment

1. **Clone and setup:**
   ```bash
   git clone https://github.com/osercinoglu/grinn-web.git
   cd grinn-web
   ```

2. **Configure environment:**
   ```bash
   # Copy frontend environment template
   cp .env.frontend.example .env.frontend
   
   # Edit configuration
   nano .env.frontend
   ```

3. **Setup credentials (Production only):**
   ```bash
   mkdir -p secrets
   # Add your GCS credentials
   cp /path/to/your/gcs-credentials.json secrets/
   ```

4. **Deploy frontend:**
   ```bash
   # Make deployment script executable
   chmod +x deploy-frontend.sh
   
   # Deploy frontend services
   ./deploy-frontend.sh
   ```

5. **Verify deployment:**
   ```bash
   # Check service health
   docker-compose -f docker-compose.frontend.yml ps
   
   # View logs
   docker-compose -f docker-compose.frontend.yml logs webapp
   ```

### Worker Deployment

Deploy at each computational facility:

1. **Setup worker environment:**
   ```bash
   # Clone repository at worker facility
   git clone https://github.com/osercinoglu/grinn-web.git
   cd grinn-web
   
   # Copy worker environment template
   cp .env.worker.example .env.worker
   
   # Configure frontend connection
   nano .env.worker
   ```

2. **Configure worker connection:**
   ```bash
   # In .env.worker, set:
   FRONTEND_HOST=your.frontend.server.ip
   FACILITY_NAME=facility-1
   WORKER_COUNT=2
   ```

3. **Deploy workers:**
   ```bash
   # Make deployment script executable  
   chmod +x deploy-worker.sh
   
   # Deploy worker services
   ./deploy-worker.sh
   ```

4. **Verify worker connection:**
   ```bash
   # Check worker health
   docker-compose -f docker-compose.worker.yml ps
   
   # View worker logs
   docker-compose -f docker-compose.worker.yml logs worker
   ```

### Alternative: Standalone Worker

For maximum flexibility, use the standalone worker script:

```bash
# At each worker facility
python standalone-worker.py \
    --frontend-host your.frontend.server.ip \
    --facility facility-1 \
    --gcs-bucket your-bucket-name \
    --gcs-project your-project-id
```

### Network Requirements

**Frontend Server Firewall:**
```bash
# Allow worker connections
sudo ufw allow 5432/tcp  # PostgreSQL
sudo ufw allow 6379/tcp  # Redis
sudo ufw allow 80/tcp    # Web interface
sudo ufw allow 443/tcp   # HTTPS (if configured)
```

**Security Considerations:**
- Use strong passwords for Redis and PostgreSQL
- Consider VPN connections for sensitive facilities
- Implement IP-based access controls if needed
- Use HTTPS for web interface in production

### Monitoring

**Frontend Monitoring:**
```bash
# Check all services
docker-compose -f docker-compose.frontend.yml ps

# Monitor logs
docker-compose -f docker-compose.frontend.yml logs -f webapp

# Database status
docker-compose -f docker-compose.frontend.yml exec postgres psql -U grinn_user -d grinn_web -c "SELECT count(*) FROM jobs;"
```

**Worker Monitoring:**
```bash
# At each facility
docker-compose -f docker-compose.worker.yml ps
docker-compose -f docker-compose.worker.yml logs -f worker
```

**Job Queue Monitoring:**
```bash
# Connect to Redis
docker-compose -f docker-compose.frontend.yml exec redis redis-cli
> INFO
> LLEN grinn_tasks  # Check queue length
```

---

## 🐳 Single-Host Docker Deployment

For traditional single-machine deployment:

### Prerequisites

- **Docker** (version 20.10+) and **Docker Compose** (version 2.0+)  
- **Git** for repository management
- **8GB+ RAM** recommended for computational jobs
- **gRINN Docker image** (from the main gRINN repository)

### Quick Start

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
   ```

5. **Verify deployment:**
   ```bash
   # Check service health
   docker-compose ps
   
   # View application logs
   docker-compose logs webapp
   ```

6. **Access the service:**
   - **Main Interface:** http://localhost:8050
   - **Job Queue:** http://localhost:8050/queue  
   - **gRINN Dashboard:** http://localhost:8051

### Production Configuration

For production deployment, configure:

1. **Google Cloud Storage (Recommended):**
   ```bash
   # Add your GCS credentials
   cp /path/to/your/service-account.json secrets/gcs-credentials.json
   
   # Update .env with your GCS settings:
   GCS_BUCKET_NAME=your-bucket-name
   GCS_PROJECT_ID=your-project-id
   DEVELOPMENT_MODE=false
   ```

2. **Security settings:**
   ```bash
   # Generate strong passwords in .env
   POSTGRES_PASSWORD=your-secure-password
   REDIS_PASSWORD=your-redis-password
   ```

3. **Resource limits:**
   ```yaml
   # Adjust in docker-compose.yml
   services:
     worker:
       deploy:
         resources:
           limits:
             memory: 4G
             cpus: '2'
   ```

---

## 🔧 Development Setup

For local development without Docker:

### Prerequisites

- **Python 3.8+** with conda/miniconda
- **PostgreSQL** (optional - SQLite used by default)
- **Redis** (optional - in-memory broker used by default)

### Setup

1. **Clone and create environment:**
   ```bash
   git clone https://github.com/osercinoglu/grinn-web.git
   cd grinn-web
   
   # Create conda environment
   conda create -n grinn-web python=3.10
   conda activate grinn-web
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure for development:**
   ```bash
   cp .env.example .env
   
   # Edit .env to enable development mode:
   DEVELOPMENT_MODE=true
   DATABASE_URL=sqlite:///./dev-jobs.db
   ```

4. **Run services:**
   ```bash
   # Terminal 1: Start Celery worker (for job processing)
   celery -A backend.tasks worker --loglevel=info
   
   # Terminal 2: Start web application
   python frontend/app.py
   ```

5. **Access the application:**
   - **Main Interface:** http://localhost:8050
   - **Job Queue:** http://localhost:8050/queue

### Development Features

- **Hot reloading** - Code changes reload automatically
- **Mock storage** - No GCS credentials required
- **SQLite database** - No PostgreSQL setup needed
- **In-memory job queue** - No Redis required
- **Debug mode** - Detailed error information

---

## 🚀 Usage Guide

### Job Submission

1. **Upload Files:**
   - Structure file (PDB/GRO format)
   - Trajectory file (XTC format)

2. **Configure Parameters:**
   - Residue selection (default: all)
   - Analysis type
   - Privacy settings

3. **Submit and Monitor:**
   - Job redirects to monitoring page
   - Bookmark the URL for later access
   - Real-time progress updates

### Privacy Controls

- **Public Jobs:** Visible in job queue, accessible to all users
- **Private Jobs:** Hidden from public queue, accessible only via direct URL

### Monitoring

- **Individual Job Monitoring:** `/monitor/{job_id}`
- **Job Queue Overview:** `/queue`
- **Real-time Updates:** Automatic refresh every 3 seconds

### Results

- **Interactive Dashboard:** Visualize interaction networks
- **Download Results:** CSV files and analysis outputs
- **Persistent Storage:** Results available indefinitely

---

## 📁 Project Structure

```
grinn-web/
├── frontend/                    # Dash web application
│   ├── app.py                  # Main web interface
│   └── assets/                 # CSS styling
├── backend/                     # Flask API and tasks
│   ├── api.py                  # REST API endpoints
│   └── tasks.py                # Celery task definitions
├── shared/                      # Shared utilities
│   ├── models.py               # Database models
│   ├── database.py             # Database utilities
│   └── storage.py              # File storage utilities
├── docker-compose.yml           # Single-host deployment
├── docker-compose.frontend.yml  # Frontend-only deployment
├── docker-compose.worker.yml    # Worker-only deployment
├── standalone-worker.py         # Standalone worker script
├── deploy-frontend.sh          # Frontend deployment script
├── deploy-worker.sh            # Worker deployment script
└── .env.frontend/.env.worker   # Environment configurations
```

---

## 🔍 Troubleshooting

### Common Issues

**Job Status "Processing" but not progressing:**
```bash
# Check worker logs
docker-compose logs worker

# Check Celery worker status
docker-compose exec webapp celery -A backend.tasks inspect active
```

**Database connection errors:**
```bash
# Check PostgreSQL status
docker-compose exec postgres pg_isready

# Reset database
docker-compose down
docker volume rm grinn-web_postgres_data
docker-compose up -d
```

**File upload issues:**
```bash
# Check storage configuration in .env
cat .env | grep -E "(GCS|DEVELOPMENT)"

# Check mounted volumes
docker-compose exec webapp ls -la /app/uploads/
```

**Worker connection issues (Distributed mode):**
```bash
# Test network connectivity from worker facility
nc -zv <frontend-host> 5432  # PostgreSQL
nc -zv <frontend-host> 6379  # Redis

# Check firewall settings on frontend server
sudo ufw status
```

### Distributed Deployment Debugging

**Frontend Issues:**
```bash
# Check service accessibility from worker network
docker-compose -f docker-compose.frontend.yml exec postgres pg_isready
docker-compose -f docker-compose.frontend.yml exec redis redis-cli ping

# Monitor connections
docker-compose -f docker-compose.frontend.yml logs -f postgres | grep connection
```

**Worker Issues:**
```bash
# Check worker connection to frontend
docker-compose -f docker-compose.worker.yml exec worker ping <frontend-host>

# Monitor task processing
docker-compose -f docker-compose.worker.yml logs -f worker | grep "Received task"
```

### Performance Tuning

**For High-Volume Processing:**
```yaml
# Increase worker concurrency in docker-compose.worker.yml
services:
  worker:
    command: ["celery", "-A", "backend.tasks", "worker", "--concurrency=4"]
    deploy:
      resources:
        limits:
          memory: 8G
          cpus: '4'
```

**Database Optimization:**
```bash
# Monitor database performance
docker-compose -f docker-compose.frontend.yml exec postgres psql -U grinn_user -d grinn_web -c "
SELECT COUNT(*) as total_jobs, status, 
       AVG(EXTRACT(epoch FROM (completed_at - started_at))) as avg_duration_seconds
FROM jobs 
WHERE status = 'completed'
GROUP BY status;"
```

### Logs and Debugging

**Application Logs:**
```bash
# Frontend logs
docker-compose -f docker-compose.frontend.yml logs -f webapp

# Worker logs  
docker-compose -f docker-compose.worker.yml logs -f worker

# Database logs
docker-compose -f docker-compose.frontend.yml logs postgres
```

**Job Debugging:**
```bash
# Check specific job in database
docker-compose -f docker-compose.frontend.yml exec postgres psql -U grinn_user -d grinn_web -c "
SELECT id, status, error_message, created_at, started_at, completed_at 
FROM jobs 
WHERE id = 'your-job-id';"
```

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

---

## 🆘 Support

- **Issues:** [GitHub Issues](https://github.com/osercinoglu/grinn-web/issues)
- **Documentation:** This README and inline code comments
- **gRINN Tool:** [Main gRINN Repository](https://github.com/osercinoglu/grinn)

For deployment assistance or questions about distributed setups, please open an issue with:
- Deployment mode (single-host/distributed)
- Error messages and logs  
- Network configuration details
- Hardware specifications