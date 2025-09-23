#!/bin/bash

# gRINN Web Service
# A web-based interface for the gRINN molecular dynamics analysis tool

This repository contains a web service implementation of gRINN (Gromacs-based Residue Interaction Network) that allows users to submit computational jobs through a web interface and retrieve results without needing to install or configure local Docker environments.

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
