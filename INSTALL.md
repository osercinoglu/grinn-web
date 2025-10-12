# gRINN Web Service Installation Guide

This guide provides detailed installation instructions for setting up the gRINN Web Service on various systems.

## Quick Installation Summary

```bash
# 1. Clone repository
git clone https://github.com/osercinoglu/grinn-web.git
cd grinn-web

# 2. Setup environment
conda create -n grinn-web python=3.10 -y
conda activate grinn-web
pip install pandas dash dash-bootstrap-components plotly flask sqlalchemy psycopg2-binary python-dotenv celery redis requests

# 3. Configure environment
cp .env.example .env
# Edit .env file with your database credentials

# 4. Setup database (PostgreSQL)
sudo -u postgres createdb grinn_web
python -c "from shared.database import DatabaseManager; DatabaseManager().init_db()"

# 5. Start services
./quick-start.sh
```

## Platform-Specific Instructions

### Ubuntu/Debian

1. **Install system dependencies:**
   ```bash
   sudo apt-get update
   sudo apt-get install python3-dev postgresql postgresql-contrib redis-server git
   ```

2. **Start services:**
   ```bash
   sudo systemctl start postgresql
   sudo systemctl start redis-server
   sudo systemctl enable postgresql
   sudo systemctl enable redis-server
   ```

3. **Create database:**
   ```bash
   sudo -u postgres psql
   CREATE DATABASE grinn_web;
   CREATE USER grinn_user WITH ENCRYPTED PASSWORD 'your_password';
   GRANT ALL PRIVILEGES ON DATABASE grinn_web TO grinn_user;
   \q
   ```

### macOS

1. **Install Homebrew (if not installed):**
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```

2. **Install dependencies:**
   ```bash
   brew install postgresql redis git
   brew services start postgresql
   brew services start redis
   ```

3. **Create database:**
   ```bash
   createdb grinn_web
   psql grinn_web
   CREATE USER grinn_user WITH ENCRYPTED PASSWORD 'your_password';
   GRANT ALL PRIVILEGES ON DATABASE grinn_web TO grinn_user;
   \q
   ```

### CentOS/RHEL/Fedora

1. **Install system dependencies:**
   ```bash
   # CentOS/RHEL
   sudo yum install python3-devel postgresql-server postgresql-contrib redis git
   
   # Fedora
   sudo dnf install python3-devel postgresql-server postgresql-contrib redis git
   ```

2. **Initialize and start PostgreSQL:**
   ```bash
   sudo postgresql-setup initdb
   sudo systemctl start postgresql
   sudo systemctl start redis
   sudo systemctl enable postgresql
   sudo systemctl enable redis
   ```

## Docker Installation (Alternative)

If you prefer using Docker:

1. **Install Docker and Docker Compose:**
   ```bash
   # Ubuntu
   sudo apt-get install docker.io docker-compose
   
   # macOS
   brew install docker docker-compose
   ```

2. **Start services:**
   ```bash
   docker-compose up -d
   ```

## Configuration Details

### Environment Variables (.env file)

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `DEVELOPMENT_MODE` | Use mock storage instead of GCS | `true` | No |
| `DATABASE_URL` | PostgreSQL connection string | - | Yes |
| `BACKEND_PORT` | Backend API port | `8050` | No |
| `FRONTEND_PORT` | Frontend dashboard port | `8051` | No |
| `REDIS_HOST` | Redis server host | `localhost` | No |
| `REDIS_PORT` | Redis server port | `6379` | No |
| `SECRET_KEY` | Application secret key | - | Yes |

### Database Configuration

The service uses PostgreSQL for persistent job storage. Default configuration:
- **Database**: `grinn_web`
- **User**: `grinn_user`
- **Host**: `localhost`
- **Port**: `5432`

### File Storage

In development mode, the service uses local file storage. For production:
- Configure Google Cloud Storage credentials
- Set `DEVELOPMENT_MODE=false` in .env
- Provide valid GCS configuration

## Verification

After installation, verify everything works:

1. **Test database connection:**
   ```bash
   conda activate grinn-web
   python -c "from shared.database import DatabaseManager; print('Success' if DatabaseManager().test_connection() else 'Failed')"
   ```

2. **Test services:**
   ```bash
   curl http://localhost:8050/api/health  # Backend
   curl http://localhost:8051             # Frontend
   ```

3. **Access web interface:**
   Open http://localhost:8051 in your browser

## Troubleshooting

### Common Issues

1. **Database connection failed:**
   - Check PostgreSQL is running: `sudo systemctl status postgresql`
   - Verify credentials in .env file
   - Test connection: `psql -h localhost -U grinn_user -d grinn_web`

2. **Port already in use:**
   - Check what's using the port: `lsof -i :8050` or `lsof -i :8051`
   - Change ports in .env file
   - Kill existing processes if needed

3. **Permission denied:**
   - Ensure user has write permissions in upload directory
   - Check file ownership: `ls -la /tmp/grinn-uploads`

4. **Module not found:**
   - Activate conda environment: `conda activate grinn-web`
   - Install missing packages: `pip install package_name`

5. **Redis connection failed:**
   - Check Redis is running: `redis-cli ping`
   - Start Redis: `sudo systemctl start redis`

### Log Files

- Application logs: `grinn-web.log`
- PostgreSQL logs: `/var/log/postgresql/`
- Redis logs: `/var/log/redis/`

### Getting Help

If you encounter issues:
1. Check the logs for error messages
2. Verify all prerequisites are installed
3. Ensure services (PostgreSQL, Redis) are running
4. Check firewall settings for required ports
5. Consult the main README.md for additional information

## Development Setup

For development work on the gRINN web service:

1. **Clone with development branch:**
   ```bash
   git clone -b develop https://github.com/osercinoglu/grinn-web.git
   ```

2. **Install development dependencies:**
   ```bash
   pip install pytest pytest-cov black flake8 mypy
   ```

3. **Run tests:**
   ```bash
   pytest tests/
   ```

4. **Code formatting:**
   ```bash
   black .
   flake8 .
   ```