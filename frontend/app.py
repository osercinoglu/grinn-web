"""
gRINN Web Service Frontend Application
A Dash-based web interface for submitting and monitoring gRINN computational jobs.
"""

import os
import sys
import base64
import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

import dash
from dash import Dash, dcc, html, dash_table, Input, Output, State, callback_context, no_update
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
import requests

# Add shared modules to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'shared'))
from models import Job, JobStatus, JobParameters, FileType, JobSubmissionRequest
from config import get_config, setup_logging

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Initialize config
config = get_config()

# Initialize Dash app
app = Dash(__name__, 
          external_stylesheets=[dbc.themes.BOOTSTRAP],
          title="gRINN Web Service",
          suppress_callback_exceptions=True)

# Global variables for job tracking
current_jobs = {}

def create_header():
    """Create the main header component."""
    return html.Div([
        html.H1("gRINN Web Service", className="main-title"),
        html.P(
            "Submit molecular dynamics analysis jobs and visualize interaction networks",
            style={
                'textAlign': 'center',
                'color': '#5A7A60',
                'fontSize': '1.2rem',
                'marginBottom': '30px'
            }
        )
    ])

def create_file_upload_section():
    """Create the file upload section."""
    return html.Div([
        html.H3("Upload Input Files", style={'color': '#5A7A60', 'marginBottom': '20px'}),
        
        html.Div([
            html.Div([
                html.I(className="fas fa-cloud-upload-alt upload-icon"),
                html.Div("Drop files here or click to browse", className="upload-text"),
                html.Div("Supported formats: PDB, XTC, TPR, MDP, GRO, TOP, ITP", className="upload-subtext"),
            ], className="upload-zone"),
            
            dcc.Upload(
                id='upload-files',
                children=html.Div([]),
                style={
                    'position': 'absolute',
                    'top': 0,
                    'left': 0,
                    'width': '100%',
                    'height': '100%',
                    'opacity': 0,
                    'cursor': 'pointer'
                },
                multiple=True
            )
        ], className="upload-panel", style={'position': 'relative'}),
        
        # File list display
        html.Div(id="file-list-display", className="file-list", style={'display': 'none'}),
        
        # File validation messages
        html.Div(id="file-validation-messages")
    ], className="panel")

def create_job_configuration_section():
    """Create the job configuration section."""
    return html.Div([
        html.H3("Job Configuration", style={'color': '#5A7A60', 'marginBottom': '20px'}),
        
        html.Div([
            # Job basic information
            html.Div([
                html.Div([
                    html.Label("Job Name*", className="form-label"),
                    dcc.Input(
                        id="job-name",
                        type="text",
                        placeholder="Enter a descriptive name for your job",
                        className="form-input",
                        required=True
                    )
                ], className="form-group"),
                
                html.Div([
                    html.Label("Description (Optional)", className="form-label"),
                    dcc.Textarea(
                        id="job-description",
                        placeholder="Describe your analysis...",
                        className="form-input form-textarea"
                    )
                ], className="form-group"),
                
                html.Div([
                    html.Label("Email (Optional)", className="form-label"),
                    dcc.Input(
                        id="user-email",
                        type="email",
                        placeholder="your.email@example.com",
                        className="form-input"
                    )
                ], className="form-group")
            ], style={'flex': '1'}),
            
            # Analysis parameters
            html.Div([
                html.H4("Analysis Parameters", style={'color': '#5A7A60', 'marginBottom': '15px'}),
                
                html.Div([
                    html.Label("Simulation Time (ns)", className="form-label"),
                    dcc.Input(
                        id="simulation-time",
                        type="number",
                        value=100.0,
                        min=1.0,
                        max=1000.0,
                        step=1.0,
                        className="form-input"
                    )
                ], className="form-group"),
                
                html.Div([
                    html.Label("Temperature (K)", className="form-label"),
                    dcc.Input(
                        id="temperature",
                        type="number",
                        value=310.0,
                        min=200.0,
                        max=400.0,
                        step=1.0,
                        className="form-input"
                    )
                ], className="form-group"),
                
                html.Div([
                    html.Label("Energy Cutoff (kJ/mol)", className="form-label"),
                    dcc.Input(
                        id="energy-cutoff",
                        type="number",
                        value=-1.0,
                        step=0.1,
                        className="form-input"
                    )
                ], className="form-group"),
                
                html.Div([
                    html.Label("Distance Cutoff (nm)", className="form-label"),
                    dcc.Input(
                        id="distance-cutoff",
                        type="number",
                        value=0.5,
                        min=0.1,
                        max=2.0,
                        step=0.1,
                        className="form-input"
                    )
                ], className="form-group"),
                
                html.Div([
                    html.Label("Interaction Types", className="form-label"),
                    dcc.Checklist(
                        id="interaction-types",
                        options=[
                            {'label': 'Total Energy', 'value': 'total'},
                            {'label': 'Van der Waals', 'value': 'vdw'},
                            {'label': 'Electrostatic', 'value': 'elec'}
                        ],
                        value=['total', 'vdw', 'elec'],
                        inline=True,
                        style={'marginTop': '8px'}
                    )
                ], className="form-group"),
                
                html.Div([
                    html.Label("Network Threshold (kJ/mol)", className="form-label"),
                    dcc.Input(
                        id="network-threshold",
                        type="number",
                        value=-2.0,
                        step=0.1,
                        className="form-input"
                    )
                ], className="form-group"),
                
                html.Div([
                    dcc.Checklist(
                        id="analysis-options",
                        options=[
                            {'label': 'Include Backbone', 'value': 'include_backbone'},
                            {'label': 'Generate Plots', 'value': 'generate_plots'},
                            {'label': 'Generate Network', 'value': 'generate_network'}
                        ],
                        value=['include_backbone', 'generate_plots', 'generate_network'],
                        style={'marginTop': '15px'}
                    )
                ], className="form-group")
            ], style={'flex': '1', 'marginLeft': '20px'})
        ], style={'display': 'flex', 'gap': '20px'}),
        
        # Submit button
        html.Div([
            html.Button(
                "Submit Job",
                id="submit-job-btn",
                className="btn btn-primary",
                disabled=True,
                style={'width': '200px', 'margin': '20px auto', 'display': 'block'}
            )
        ])
    ], className="panel")

def create_job_monitor_section():
    """Create the job monitoring section."""
    return html.Div([
        html.H3("Job Status", style={'color': '#5A7A60', 'marginBottom': '20px'}),
        
        # Job list
        html.Div(id="job-list", children=[
            html.Div(
                "No jobs submitted yet.",
                style={
                    'textAlign': 'center',
                    'color': '#8A9A8A',
                    'padding': '40px',
                    'fontStyle': 'italic'
                }
            )
        ]),
        
        # Refresh button
        html.Div([
            html.Button(
                "Refresh Jobs",
                id="refresh-jobs-btn",
                className="btn btn-secondary",
                style={'margin': '10px auto', 'display': 'block'}
            )
        ])
    ], className="panel")

def create_job_card(job: Job):
    """Create a job status card."""
    # Calculate progress
    if job.status == JobStatus.PENDING:
        progress = 0
    elif job.status == JobStatus.UPLOADING:
        progress = 10
    elif job.status == JobStatus.QUEUED:
        progress = 20
    elif job.status == JobStatus.RUNNING:
        progress = job.progress_percentage if job.progress_percentage > 20 else 50
    elif job.status == JobStatus.COMPLETED:
        progress = 100
    else:  # FAILED or CANCELLED
        progress = 0
    
    # Create status badge
    status_class = f"status-{job.status.value}"
    
    # Calculate duration
    duration_text = ""
    if job.started_at and job.completed_at:
        duration = job.completed_at - job.started_at
        duration_text = f" (Duration: {str(duration).split('.')[0]})"
    elif job.started_at:
        duration = datetime.utcnow() - job.started_at
        duration_text = f" (Running: {str(duration).split('.')[0]})"
    
    # Create action buttons
    action_buttons = []
    if job.status == JobStatus.COMPLETED and job.results_gcs_path:
        action_buttons.append(
            html.A(
                [html.I(className="fas fa-chart-network dashboard-icon"), "View Results"],
                href=f"/dashboard/{job.job_id}",
                className="dashboard-link",
                target="_blank"
            )
        )
    elif job.status in [JobStatus.PENDING, JobStatus.QUEUED]:
        action_buttons.append(
            html.Button(
                "Cancel",
                id={"type": "cancel-job", "job_id": job.job_id},
                className="btn btn-danger",
                style={'fontSize': '0.8rem', 'padding': '6px 12px'}
            )
        )
    
    return html.Div([
        html.Div([
            html.Div([
                html.H4(job.job_name or f"Job {job.job_id[:8]}", 
                       style={'margin': '0', 'color': '#5A7A60'}),
                html.Span(job.status.value.title(), className=f"job-status {status_class}")
            ], style={'display': 'flex', 'justifyContent': 'space-between', 'alignItems': 'center'}),
            
            html.P(job.description or "No description provided", 
                  style={'margin': '10px 0', 'color': '#666'}),
            
            html.Div([
                html.Small(f"Created: {job.created_at.strftime('%Y-%m-%d %H:%M:%S')}{duration_text}",
                         style={'color': '#8A9A8A'})
            ]),
            
            # Progress bar
            html.Div([
                html.Div(
                    style={
                        'width': f'{progress}%',
                        'height': '100%',
                        'background': 'linear-gradient(90deg, #7C9885, #5A7A60)',
                        'borderRadius': '10px',
                        'transition': 'width 0.3s ease'
                    }
                )
            ], className="progress-bar"),
            
            # Current step
            html.Div([
                html.Small(
                    job.current_step or f"Status: {job.status.value.title()}",
                    style={'color': '#5A7A60', 'fontWeight': '500'}
                )
            ], style={'marginTop': '5px'}),
            
            # Error message
            html.Div([
                html.Div([
                    html.I(className="fas fa-exclamation-triangle", 
                          style={'marginRight': '8px', 'color': '#721C24'}),
                    job.error_message
                ], className="alert alert-danger")
            ] if job.error_message else []),
            
            # Action buttons
            html.Div(action_buttons, style={'marginTop': '15px'}) if action_buttons else html.Div()
        ])
    ], className="job-card", id=f"job-card-{job.job_id}")

# Layout
app.layout = html.Div([
    dcc.Store(id='uploaded-files-store', data=[]),
    dcc.Store(id='job-data-store', data={}),
    dcc.Interval(id='job-refresh-interval', interval=5000, n_intervals=0),  # Refresh every 5 seconds
    
    create_header(),
    
    html.Div([
        create_file_upload_section(),
        create_job_configuration_section(),
        create_job_monitor_section()
    ], style={'maxWidth': '1200px', 'margin': '0 auto', 'padding': '20px'})
])

# Callbacks

@app.callback(
    [Output('file-list-display', 'children'),
     Output('file-list-display', 'style'),
     Output('file-validation-messages', 'children'),
     Output('uploaded-files-store', 'data'),
     Output('submit-job-btn', 'disabled')],
    [Input('upload-files', 'contents')],
    [State('upload-files', 'filename'),
     State('uploaded-files-store', 'data')]
)
def handle_file_upload(contents, filenames, stored_files):
    """Handle file upload and validation."""
    if not contents:
        return [], {'display': 'none'}, [], stored_files, True
    
    if not isinstance(contents, list):
        contents = [contents]
        filenames = [filenames]
    
    files = stored_files.copy()
    validation_messages = []
    
    for content, filename in zip(contents, filenames):
        # Decode file content
        content_type, content_string = content.split(',')
        file_size = len(base64.b64decode(content_string))
        
        # Validate file size
        max_size = config.max_file_size_mb * 1024 * 1024
        if file_size > max_size:
            validation_messages.append(
                html.Div([
                    html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                    f"File {filename} is too large ({file_size/1024/1024:.1f}MB). Maximum size is {config.max_file_size_mb}MB."
                ], className="alert alert-danger")
            )
            continue
        
        # Determine file type
        extension = filename.lower().split('.')[-1] if '.' in filename else ''
        try:
            file_type = FileType(extension)
        except ValueError:
            validation_messages.append(
                html.Div([
                    html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                    f"Unsupported file type: {filename}. Supported formats: PDB, XTC, TPR, MDP, GRO, TOP, ITP."
                ], className="alert alert-warning")
            )
            continue
        
        # Add file to store
        file_data = {
            'filename': filename,
            'content': content_string,
            'size_bytes': file_size,
            'file_type': file_type.value,
            'upload_time': datetime.utcnow().isoformat()
        }
        
        # Check for duplicates
        if not any(f['filename'] == filename for f in files):
            files.append(file_data)
    
    # Create file list display
    file_list_items = []
    for file_data in files:
        size_mb = file_data['size_bytes'] / (1024 * 1024)
        file_list_items.append(
            html.Div([
                html.Div([
                    html.I(className="fas fa-file file-icon"),
                    html.Span(file_data['filename'], className="file-name"),
                    html.Span(f" ({size_mb:.1f} MB)", className="file-size")
                ], className="file-info"),
                html.Div([
                    html.Button(
                        html.I(className="fas fa-trash"),
                        id={'type': 'remove-file', 'filename': file_data['filename']},
                        className="btn btn-danger",
                        style={'fontSize': '0.8rem', 'padding': '4px 8px'}
                    )
                ], className="file-actions")
            ], className="file-item")
        )
    
    # Determine if submit should be enabled
    has_files = len(files) > 0
    submit_disabled = not has_files
    
    style = {'display': 'block'} if files else {'display': 'none'}
    
    return file_list_items, style, validation_messages, files, submit_disabled

@app.callback(
    Output('uploaded-files-store', 'data', allow_duplicate=True),
    [Input({'type': 'remove-file', 'filename': dash.dependencies.ALL}, 'n_clicks')],
    [State('uploaded-files-store', 'data')],
    prevent_initial_call=True
)
def remove_file(n_clicks, stored_files):
    """Remove a file from the upload list."""
    if not any(n_clicks):
        return stored_files
    
    # Find which button was clicked
    ctx = callback_context
    if not ctx.triggered:
        return stored_files
    
    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    button_data = json.loads(button_id)
    filename_to_remove = button_data['filename']
    
    # Filter out the removed file
    updated_files = [f for f in stored_files if f['filename'] != filename_to_remove]
    
    return updated_files

@app.callback(
    [Output('job-data-store', 'data'),
     Output('job-list', 'children')],
    [Input('submit-job-btn', 'n_clicks'),
     Input('job-refresh-interval', 'n_intervals'),
     Input('refresh-jobs-btn', 'n_clicks')],
    [State('job-name', 'value'),
     State('job-description', 'value'),
     State('user-email', 'value'),
     State('simulation-time', 'value'),
     State('temperature', 'value'),
     State('energy-cutoff', 'value'),
     State('distance-cutoff', 'value'),
     State('interaction-types', 'value'),
     State('network-threshold', 'value'),
     State('analysis-options', 'value'),
     State('uploaded-files-store', 'data'),
     State('job-data-store', 'data')]
)
def handle_job_submission_and_monitoring(submit_clicks, interval_clicks, refresh_clicks,
                                       job_name, job_description, user_email,
                                       sim_time, temperature, energy_cutoff, distance_cutoff,
                                       interaction_types, network_threshold, analysis_options,
                                       uploaded_files, current_job_data):
    """Handle job submission and monitoring."""
    ctx = callback_context
    
    if not ctx.triggered:
        # Initial load - show existing jobs
        job_cards = []
        for job_id, job_data in current_job_data.items():
            job = Job.from_dict(job_data)
            job_cards.append(create_job_card(job))
        
        if not job_cards:
            job_cards = [html.Div(
                "No jobs submitted yet.",
                style={
                    'textAlign': 'center',
                    'color': '#8A9A8A',
                    'padding': '40px',
                    'fontStyle': 'italic'
                }
            )]
        
        return current_job_data, job_cards
    
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    if trigger_id == 'submit-job-btn' and submit_clicks:
        # Handle job submission
        if not job_name or not uploaded_files:
            return current_job_data, [html.Div("Please provide a job name and upload files.", className="alert alert-danger")]
        
        try:
            # Create job parameters
            parameters = JobParameters(
                simulation_time_ns=sim_time or 100.0,
                temperature_k=temperature or 310.0,
                energy_cutoff=energy_cutoff or -1.0,
                distance_cutoff_nm=distance_cutoff or 0.5,
                interaction_types=interaction_types or ['total'],
                network_threshold=network_threshold or -2.0,
                include_backbone='include_backbone' in (analysis_options or []),
                generate_plots='generate_plots' in (analysis_options or []),
                generate_network='generate_network' in (analysis_options or [])
            )
            
            # Create job
            job = Job(
                job_name=job_name,
                description=job_description,
                user_email=user_email,
                parameters=parameters
            )
            
            # Add files to job
            for file_data in uploaded_files:
                job.add_file(
                    filename=file_data['filename'],
                    file_type=FileType(file_data['file_type']),
                    size_bytes=file_data['size_bytes']
                )
            
            # Store job data
            job_dict = job.to_dict()
            job_dict['uploaded_files'] = uploaded_files  # Store file contents
            current_job_data[job.job_id] = job_dict
            
            # TODO: In a real implementation, this would submit to the backend
            # For now, simulate job progression
            job.update_status(JobStatus.UPLOADING, "Uploading files to cloud storage...")
            current_job_data[job.job_id] = job.to_dict()
            current_job_data[job.job_id]['uploaded_files'] = uploaded_files
            
            logger.info(f"Job {job.job_id} submitted: {job.job_name}")
            
        except Exception as e:
            logger.error(f"Error submitting job: {e}")
            return current_job_data, [html.Div(f"Error submitting job: {str(e)}", className="alert alert-danger")]
    
    # Create job cards for display
    job_cards = []
    for job_id, job_data in current_job_data.items():
        job = Job.from_dict(job_data)
        job_cards.append(create_job_card(job))
    
    if not job_cards:
        job_cards = [html.Div(
            "No jobs submitted yet.",
            style={
                'textAlign': 'center',
                'color': '#8A9A8A',
                'padding': '40px',
                'fontStyle': 'italic'
            }
        )]
    
    return current_job_data, job_cards

if __name__ == '__main__':
    try:
        config.validate()
        logger.info("Starting gRINN Web Service Frontend")
        app.run_server(
            host=config.frontend_host,
            port=config.frontend_port,
            debug=config.frontend_debug
        )
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        print(f"Configuration error: {e}")
        print("Please check your environment variables and try again.")
    except Exception as e:
        logger.error(f"Failed to start frontend: {e}")
        print(f"Failed to start frontend: {e}")