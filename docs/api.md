# API Documentation

The gRINN Web Service provides a RESTful API for job management and monitoring.

## Base URL

- Development: `http://localhost:5000`
- Production: `https://your-domain.com`

## Authentication

Currently, the API does not require authentication. In production, implement appropriate authentication mechanisms.

## Endpoints

### Health Check

Check API health status.

**GET** `/api/health`

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2023-12-07T10:30:00Z",
  "version": "1.0.0"
}
```

### Job Management

#### Submit Job

Submit a new gRINN analysis job.

**POST** `/api/jobs`

**Request Body:**
```json
{
  "job_name": "My Analysis",
  "description": "Optional description",
  "user_email": "user@example.com",
  "parameters": {
    "simulation_time_ns": 100.0,
    "temperature_k": 310.0,
    "energy_cutoff": -1.0,
    "distance_cutoff_nm": 0.5,
    "interaction_types": ["total", "vdw", "elec"],
    "network_threshold": -2.0,
    "include_backbone": true,
    "generate_plots": true,
    "generate_network": true
  },
  "uploaded_files": [
    {
      "filename": "protein.pdb",
      "file_type": "pdb",
      "size_bytes": 1024000,
      "content": "base64-encoded-content"
    }
  ]
}
```

**Response:**
```json
{
  "success": true,
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Job submitted successfully",
  "status": "uploading"
}
```

#### Get All Jobs

Retrieve list of jobs with pagination.

**GET** `/api/jobs?limit=50&offset=0`

**Parameters:**
- `limit` (optional): Maximum number of jobs to return (default: 50, max: 100)
- `offset` (optional): Number of jobs to skip (default: 0)

**Response:**
```json
{
  "jobs": [
    {
      "job_id": "550e8400-e29b-41d4-a716-446655440000",
      "job_name": "My Analysis",
      "status": "completed",
      "created_at": "2023-12-07T10:00:00Z",
      "updated_at": "2023-12-07T10:30:00Z",
      "progress_percentage": 100.0,
      "error_message": null
    }
  ],
  "total": 25,
  "limit": 50,
  "offset": 0,
  "has_more": false
}
```

#### Get Job Details

Get detailed information about a specific job.

**GET** `/api/jobs/{job_id}`

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "job_name": "My Analysis",
  "description": "Optional description",
  "status": "completed",
  "created_at": "2023-12-07T10:00:00Z",
  "updated_at": "2023-12-07T10:30:00Z",
  "started_at": "2023-12-07T10:05:00Z",
  "completed_at": "2023-12-07T10:30:00Z",
  "progress_percentage": 100.0,
  "current_step": "Job completed",
  "user_email": "user@example.com",
  "parameters": {
    "simulation_time_ns": 100.0,
    "temperature_k": 310.0
  },
  "input_files": [
    {
      "filename": "protein.pdb",
      "file_type": "pdb",
      "size_bytes": 1024000,
      "gcs_path": "jobs/550e8400.../input/protein.pdb"
    }
  ],
  "results_gcs_path": "jobs/550e8400.../output/",
  "error_message": null
}
```

#### Get Job Status

Get current status and progress of a job.

**GET** `/api/jobs/{job_id}/status`

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "running",
  "progress_percentage": 75.0,
  "current_step": "Running analysis",
  "created_at": "2023-12-07T10:00:00Z",
  "updated_at": "2023-12-07T10:25:00Z",
  "started_at": "2023-12-07T10:05:00Z",
  "duration_seconds": 1200,
  "error_message": null
}
```

#### Cancel Job

Cancel a job that is pending, queued, or running.

**POST** `/api/jobs/{job_id}/cancel`

**Response:**
```json
{
  "success": true,
  "message": "Job cancelled successfully"
}
```

### Results

#### Get Job Results

Get information about job results and download URLs.

**GET** `/api/jobs/{job_id}/results`

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "results_available": true,
  "results_gcs_path": "jobs/550e8400.../output/",
  "files": [
    {
      "filename": "energies_intEnTotal.csv",
      "gcs_path": "jobs/550e8400.../output/energies_intEnTotal.csv",
      "size_bytes": 256000,
      "created": "2023-12-07T10:30:00Z"
    }
  ],
  "download_urls": {
    "energies_intEnTotal.csv": "https://storage.googleapis.com/signed-url..."
  }
}
```

#### Get Dashboard URL

Get URL for gRINN dashboard to visualize results.

**GET** `/api/jobs/{job_id}/dashboard`

**Response:**
```json
{
  "dashboard_url": "/dashboard?job_id=550e8400...&results_path=gs://bucket/...",
  "job_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Monitoring

#### Queue Statistics

Get statistics about the job queue.

**GET** `/api/queue/stats`

**Response:**
```json
{
  "total_jobs": 150,
  "by_status": {
    "pending": 2,
    "uploading": 1,
    "queued": 5,
    "running": 3,
    "completed": 135,
    "failed": 4,
    "cancelled": 0
  },
  "celery": {
    "active_tasks": 3,
    "reserved_tasks": 5
  }
}
```

#### Storage Health

Check storage system health.

**GET** `/api/storage/health`

**Response:**
```json
{
  "storage_healthy": true,
  "bucket_name": "my-grinn-bucket"
}
```

## Job Status Values

- `pending`: Job created but not yet started
- `uploading`: Files being uploaded to cloud storage
- `queued`: Job waiting in processing queue
- `running`: Job currently being processed
- `completed`: Job finished successfully
- `failed`: Job failed with error
- `cancelled`: Job cancelled by user

## File Types

Supported file types for upload:
- `pdb`: Protein structure files
- `xtc`: Trajectory files
- `tpr`: GROMACS binary topology files
- `mdp`: GROMACS parameter files
- `gro`: GROMACS coordinate files
- `top`: GROMACS topology files
- `itp`: GROMACS include topology files

## Error Codes

- `400 Bad Request`: Invalid request data
- `404 Not Found`: Job or resource not found
- `409 Conflict`: Job in invalid state for operation
- `413 Payload Too Large`: File size exceeds limit
- `422 Unprocessable Entity`: Invalid file format
- `500 Internal Server Error`: Server error
- `503 Service Unavailable`: Service temporarily unavailable

## Rate Limiting

- Job submissions: 10 per minute per IP
- Status checks: 60 per minute per IP
- File downloads: 100 per hour per IP

## WebSocket Events (Future)

For real-time job updates, the API will support WebSocket connections:

```javascript
const ws = new WebSocket('ws://localhost:5000/ws/jobs/{job_id}');
ws.onmessage = function(event) {
  const update = JSON.parse(event.data);
  console.log('Job update:', update);
};
```

## SDK Examples

### Python
```python
import requests

# Submit job
response = requests.post('http://localhost:5000/api/jobs', json={
    'job_name': 'My Analysis',
    'uploaded_files': [...]
})
job_id = response.json()['job_id']

# Check status
status = requests.get(f'http://localhost:5000/api/jobs/{job_id}/status')
print(status.json())
```

### JavaScript
```javascript
// Submit job
const response = await fetch('http://localhost:5000/api/jobs', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    job_name: 'My Analysis',
    uploaded_files: [...]
  })
});
const {job_id} = await response.json();

// Check status
const status = await fetch(`http://localhost:5000/api/jobs/${job_id}/status`);
console.log(await status.json());
```

### cURL
```bash
# Submit job
curl -X POST http://localhost:5000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_name": "My Analysis", "uploaded_files": [...]}'

# Check status
curl http://localhost:5000/api/jobs/{job_id}/status
```