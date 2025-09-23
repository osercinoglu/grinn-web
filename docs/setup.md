# gRINN Web Service Setup Guide

This guide provides step-by-step instructions for setting up and deploying the gRINN Web Service.

## Prerequisites

- Python 3.10 or higher
- Docker and Docker Compose
- Google Cloud Platform account with Cloud Storage enabled
- Redis (for development) or access to a Redis instance

## Quick Start

1. **Clone and Setup**
   ```bash
   cd grinn-web
   ./setup.sh
   ```

2. **Configure Environment**
   Edit `config/.env` with your settings:
   ```bash
   cp config/.env.example config/.env
   # Edit config/.env with your actual values
   ```

3. **Setup Google Cloud Storage**
   - Create a GCS bucket for file storage
   - Create a service account with Storage Admin permissions
   - Download the service account key JSON file
   - Update `GCS_CREDENTIALS_PATH` in your `.env` file

4. **Build gRINN Docker Image**
   ```bash
   ./scripts/build-grinn-image.sh
   ```

5. **Start Development Environment**
   ```bash
   ./scripts/start-dev.sh
   ```

## Configuration

### Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `GCS_BUCKET_NAME` | Google Cloud Storage bucket name | Yes | - |
| `GCS_PROJECT_ID` | Google Cloud Project ID | Yes | - |
| `GCS_CREDENTIALS_PATH` | Path to GCS service account key | Yes | - |
| `GRINN_DOCKER_IMAGE` | gRINN Docker image name | No | `grinn:latest` |
| `REDIS_HOST` | Redis server hostname | No | `localhost` |
| `REDIS_PORT` | Redis server port | No | `6379` |
| `MAX_FILE_SIZE_MB` | Maximum upload file size | No | `500` |
| `JOB_RETENTION_DAYS` | Days to keep job data | No | `7` |

### Google Cloud Storage Setup

1. **Create a Bucket**
   ```bash
   gsutil mb gs://your-grinn-bucket
   ```

2. **Set Bucket Permissions**
   ```bash
   gsutil iam ch serviceAccount:your-service-account@project.iam.gserviceaccount.com:objectAdmin gs://your-grinn-bucket
   ```

3. **Create Service Account**
   ```bash
   gcloud iam service-accounts create grinn-web-service
   gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
     --member="serviceAccount:grinn-web-service@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
     --role="roles/storage.admin"
   gcloud iam service-accounts keys create credentials.json \
     --iam-account=grinn-web-service@YOUR_PROJECT_ID.iam.gserviceaccount.com
   ```

## Development

### Local Development

For local development without Docker:

1. **Start Redis**
   ```bash
   docker run -d -p 6379:6379 redis:7.2-alpine
   ```

2. **Start Backend API**
   ```bash
   python backend/api.py
   ```

3. **Start Celery Worker**
   ```bash
   celery -A backend.worker worker --loglevel=info
   ```

4. **Start Frontend**
   ```bash
   python frontend/app.py
   ```

### Docker Development

Using Docker Compose for development:

```bash
./scripts/start-dev.sh
```

This starts:
- Redis container
- Backend API (Python process)
- Celery worker (Python process)
- Frontend (Python process)

## Production Deployment

### Using Docker Compose

1. **Configure Production Environment**
   ```bash
   cp config/.env.example config/.env
   # Edit with production values
   ```

2. **Start Production Services**
   ```bash
   ./scripts/start-prod.sh
   ```

This starts:
- Redis container
- Frontend container
- Backend API container
- Celery worker container
- Flower monitoring (optional)

### Using Kubernetes

See `docs/kubernetes.md` for Kubernetes deployment instructions.

### Environment-Specific Considerations

#### Development
- Use mock API client when backend is unavailable
- Smaller file size limits
- Debug logging enabled
- Local file storage fallback

#### Production
- Use production-grade Redis (Redis Cluster or managed service)
- Enable SSL/TLS
- Use external load balancer
- Implement proper monitoring and logging
- Set up backup strategies for persistent data

## Monitoring and Maintenance

### Health Checks

- Frontend: `GET http://localhost:8050/`
- Backend: `GET http://localhost:5000/api/health`
- Celery: Use Flower at `http://localhost:5555`

### Logs

View logs for all services:
```bash
docker-compose logs -f
```

View logs for specific service:
```bash
docker-compose logs -f frontend
docker-compose logs -f backend
docker-compose logs -f worker
```

### Maintenance Tasks

#### Clean Up Old Jobs
```bash
# Manual cleanup
curl -X POST http://localhost:5000/api/maintenance/cleanup

# Or access Redis directly
redis-cli FLUSHDB
```

#### Update gRINN Image
```bash
./scripts/build-grinn-image.sh
docker-compose restart worker
```

## Troubleshooting

### Common Issues

1. **GCS Authentication Failed**
   - Verify service account key file exists
   - Check file permissions
   - Validate project ID and bucket name

2. **Redis Connection Failed**
   - Ensure Redis is running
   - Check network connectivity
   - Verify Redis configuration

3. **Docker Permission Denied**
   - Add user to docker group: `sudo usermod -a -G docker $USER`
   - Restart Docker service
   - Check Docker socket permissions

4. **Port Already in Use**
   - Check for existing services: `netstat -tlnp | grep :8050`
   - Stop conflicting services
   - Use different ports in configuration

### Debug Mode

Enable debug mode for development:
```bash
export FRONTEND_DEBUG=true
python frontend/app.py
```

### Performance Tuning

- Adjust worker concurrency: `--concurrency=4`
- Increase memory limits in Docker
- Use Redis clustering for high availability
- Optimize file upload chunk sizes

## Security Considerations

- Use HTTPS in production
- Implement rate limiting
- Validate all file uploads
- Use secure secret keys
- Regularly update dependencies
- Monitor for security vulnerabilities

## Backup and Recovery

### Data to Backup
- Redis data (job state)
- GCS bucket contents
- Configuration files
- SSL certificates

### Recovery Procedures
1. Restore Redis data
2. Verify GCS bucket access
3. Restart services
4. Validate functionality

For more detailed information, see the specific documentation files in this directory.