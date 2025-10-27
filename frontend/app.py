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
          external_stylesheets=[
              dbc.themes.BOOTSTRAP,
              "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css"
          ],
          title="gRINN Web Service",
          suppress_callback_exceptions=True)

# Add custom CSS styles matching gRINN dashboard design
app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&display=swap');
            
            body {
                background: #F5F7F5;
                font-family: 'Roboto', sans-serif;
                margin: 0;
                padding: 0;
            }
            
            .panel {
                background: rgba(255,255,255,0.9);
                border: 3px solid #B5C5B5;
                border-radius: 15px;
                box-shadow: 0 8px 32px rgba(0,0,0,0.1);
                backdrop-filter: blur(10px);
                padding: 20px;
                margin-bottom: 20px;
            }
            
            .main-title {
                font-family: 'Roboto', sans-serif;
                font-weight: 700;
                color: #7C9885;
                text-shadow: 1px 1px 2px rgba(0,0,0,0.1);
                font-size: 2.5rem;
                margin: 20px 0;
                text-align: center;
                position: relative;
                letter-spacing: 1px;
            }
            
            .main-title::before {
                content: "🧬";
                position: absolute;
                left: -60px;
                top: 50%;
                transform: translateY(-50%);
                font-size: 2rem;
            }
            
            .main-title::after {
                content: "🧬";
                position: absolute;
                right: -60px;
                top: 50%;
                transform: translateY(-50%);
                font-size: 2rem;
            }
            
            .job-card {
                background: rgba(255,255,255,0.95);
                border: 2px solid #B5C5B5;
                border-radius: 12px;
                padding: 20px;
                margin-bottom: 15px;
                box-shadow: 0 6px 20px rgba(0,0,0,0.1);
                transition: all 0.3s ease;
                backdrop-filter: blur(5px);
            }
            
            .job-card:hover {
                box-shadow: 0 8px 25px rgba(0,0,0,0.15);
                border-color: #7C9885;
                transform: translateY(-2px);
            }
            
            .job-status {
                padding: 8px 16px;
                border-radius: 25px;
                font-weight: 600;
                text-transform: uppercase;
                font-size: 0.8rem;
                border: 2px solid transparent;
                display: inline-block;
            }
            
            .status-pending { 
                background: linear-gradient(135deg, #ffeaa7, #fdcb6e);
                color: #2d3436;
                border-color: #fdcb6e;
            }
            .status-queued { 
                background: linear-gradient(135deg, #74b9ff, #0984e3);
                color: white;
                border-color: #0984e3;
            }
            .status-uploading { 
                background: linear-gradient(135deg, #fd79a8, #e84393);
                color: white;
                border-color: #e84393;
            }
            .status-running { 
                background: linear-gradient(135deg, #55a3ff, #2d74da);
                color: white;
                border-color: #2d74da;
                animation: pulse 2s infinite;
            }
            .status-completed { 
                background: linear-gradient(135deg, #00b894, #00a085);
                color: white;
                border-color: #00a085;
            }
            .status-failed { 
                background: linear-gradient(135deg, #e17055, #d63031);
                color: white;
                border-color: #d63031;
            }
            .status-cancelled { 
                background: linear-gradient(135deg, #636e72, #2d3436);
                color: white;
                border-color: #2d3436;
            }
            
            @keyframes pulse {
                0% { transform: scale(1); }
                50% { transform: scale(1.05); }
                100% { transform: scale(1); }
            }
            
            .progress-bar {
                background: rgba(181, 197, 181, 0.3);
                border: 1px solid #B5C5B5;
                border-radius: 15px;
                overflow: hidden;
                height: 12px;
                position: relative;
            }
            
            .progress-bar > div {
                background: linear-gradient(90deg, #7C9885, #5A7A60);
                border-radius: 15px;
                height: 100%;
                position: relative;
                overflow: hidden;
            }
            
            .progress-bar > div::after {
                content: '';
                position: absolute;
                top: 0;
                left: -100%;
                width: 100%;
                height: 100%;
                background: linear-gradient(90deg, transparent, rgba(255,255,255,0.4), transparent);
                animation: shimmer 2s infinite;
            }
            
            @keyframes shimmer {
                0% { left: -100%; }
                100% { left: 100%; }
            }
            
            .upload-zone {
                border: 3px dashed #B5C5B5;
                border-radius: 15px;
                background: rgba(248,253,248,0.6);
                padding: 30px;
                text-align: center;
                transition: all 0.3s ease;
                min-height: 120px;
                display: flex;
                flex-direction: column;
                justify-content: center;
                align-items: center;
            }
            
            .upload-zone:hover {
                border-color: #7C9885;
                background: rgba(248,253,248,0.8);
            }
            
            .upload-panel {
                background: transparent;
                border: none;
                border-radius: 15px;
                padding: 0;
                overflow: hidden;
            }
            
            .file-item {
                background: rgba(248,253,248,0.8);
                border: 1px solid #B5C5B5;
                border-radius: 8px;
                margin-bottom: 8px;
                padding: 10px;
                display: flex;
                justify-content: space-between;
                align-items: center;
                transition: all 0.2s ease;
            }
            
            .file-item:hover {
                background: rgba(248,253,248,1);
                border-color: #7C9885;
            }
            
            .alert {
                padding: 15px 20px;
                border-radius: 10px;
                border: 2px solid;
                margin-bottom: 15px;
                font-weight: 500;
            }
            
            .alert-danger {
                background: rgba(248, 215, 218, 0.9);
                border-color: #f5c6cb;
                color: #721c24;
            }
            
            .alert-warning {
                background: rgba(255, 243, 205, 0.9);
                border-color: #ffeaa7;
                color: #856404;
            }
            
            .alert-info {
                background: rgba(209, 236, 241, 0.9);
                border-color: #bee5eb;
                color: #0c5460;
            }
            
            .alert-success {
                background: rgba(212, 237, 218, 0.9);
                border-color: #c3e6cb;
                color: #155724;
            }
            
            .bookmark-reminder {
                background: linear-gradient(135deg, #74b9ff, #0984e3);
                color: white;
                border: 2px solid #0984e3;
                border-radius: 10px;
                padding: 15px;
                text-align: center;
                margin-bottom: 20px;
                animation: gentle-pulse 3s infinite;
            }
            
            @keyframes gentle-pulse {
                0%, 100% { transform: scale(1); }
                50% { transform: scale(1.02); }
            }
            
            .btn {
                border-radius: 8px;
                font-weight: 500;
                border: 2px solid transparent;
                transition: all 0.3s ease;
                text-decoration: none;
                display: inline-block;
                text-align: center;
            }
            
            .btn-primary {
                background: linear-gradient(135deg, #7C9885, #5A7A60);
                border-color: #5A7A60;
                color: white;
            }
            
            .btn-primary:hover {
                background: linear-gradient(135deg, #6B8574, #495F4F);
                transform: translateY(-1px);
                box-shadow: 0 4px 8px rgba(90,122,96,0.3);
            }
            
            .btn-success {
                background: linear-gradient(135deg, #00b894, #00a085);
                border-color: #00a085;
                color: white;
            }
            
            .btn-info {
                background: linear-gradient(135deg, #74b9ff, #0984e3);
                border-color: #0984e3;
                color: white;
            }
            
            .btn-danger {
                background: linear-gradient(135deg, #e17055, #d63031);
                border-color: #d63031;
                color: white;
            }
            
            .btn-secondary {
                background: linear-gradient(135deg, #b2bec3, #636e72);
                border-color: #636e72;
                color: white;
            }
            
            .btn-outline-primary {
                background: transparent;
                border-color: #7C9885;
                color: #7C9885;
            }
            
            .btn-outline-primary:hover {
                background: #7C9885;
                color: white;
            }
            
            .form-input {
                border: 2px solid #B5C5B5;
                border-radius: 8px;
                padding: 10px 12px;
                font-family: 'Roboto', sans-serif;
                transition: border-color 0.3s ease;
                background: rgba(255,255,255,0.9);
            }
            
            .form-input:focus {
                outline: none;
                border-color: #7C9885;
                box-shadow: 0 0 0 3px rgba(124,152,133,0.1);
            }
            
            .form-label {
                font-weight: 500;
                color: #5A7A60;
                margin-bottom: 5px;
                display: block;
            }
            
            .form-group {
                margin-bottom: 15px;
            }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
'''

# Global variables for job tracking
current_jobs = {}

def create_header():
    """Create the main header component."""
    return html.Div([
        html.H1("gRINN Web Service", className="main-title"),
        html.P(
            "Analyze molecular dynamics trajectories and visualize residue interaction networks",
            style={
                'textAlign': 'center',
                'color': '#5A7A60',
                'fontSize': '1.1rem',
                'marginBottom': '15px'
            }
        ),
        
        # Navigation bar
        html.Div([
            html.Div([
                html.A(
                    [html.I(className="fas fa-home", style={'marginRight': '6px'}), "Submit Job"],
                    href="/",
                    className="nav-link",
                    style={
                        'padding': '8px 16px',
                        'backgroundColor': 'rgba(90, 122, 96, 0.1)',
                        'color': '#5A7A60',
                        'textDecoration': 'none',
                        'borderRadius': '5px',
                        'marginRight': '10px',
                        'fontSize': '0.9rem',
                        'fontWeight': '500'
                    }
                ),
                html.A(
                    [html.I(className="fas fa-list-ul", style={'marginRight': '6px'}), "View Job Queue"],
                    href="/queue",
                    target="_blank",
                    className="nav-link",
                    style={
                        'padding': '8px 16px',
                        'backgroundColor': 'rgba(23, 162, 184, 0.1)',
                        'color': '#17a2b8',
                        'textDecoration': 'none',
                        'borderRadius': '5px',
                        'fontSize': '0.9rem',
                        'fontWeight': '500',
                        'border': '1px solid rgba(23, 162, 184, 0.3)'
                    }
                )
            ], style={'textAlign': 'center'})
        ], style={'marginBottom': '20px'})
    ])

def create_input_mode_selector():
    """Create the input mode selection section."""
    return html.Div([
        html.Div([
            html.Label("Analysis Mode:", style={'fontWeight': 'bold', 'color': '#5A7A60', 'marginRight': '15px', 'display': 'inline-block'}),
            dbc.RadioItems(
                id='input-mode-selector',
                options=[
                    {'label': ' Trajectory Analysis', 'value': 'trajectory'},
                    {'label': ' PDB Ensemble', 'value': 'ensemble'}
                ],
                value='trajectory',
                inline=True,
                style={'display': 'inline-block'}
            )
        ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '10px'})
    ], className="panel", style={'padding': '15px', 'marginBottom': '15px'})

def create_file_upload_section():
    """Create the file upload section."""
    return html.Div([
        # Mode-specific instructions and upload in single row
        html.Div([
            # Left: Mode instructions
            html.Div(id='mode-specific-instructions', style={'flex': '1', 'paddingRight': '15px'}),
            
            # Right: Upload zone
            html.Div([
                html.Div([
                    html.Div([
                        html.I(className="fas fa-cloud-upload-alt", style={'fontSize': '1.5rem', 'color': '#7C9885', 'marginBottom': '8px'}),
                        html.Div("Drop files or click to browse", 
                                style={'fontSize': '0.9rem', 'fontWeight': '500', 'color': '#5A7A60'})
                    ], className="upload-zone", style={'padding': '20px', 'textAlign': 'center'}),
                    
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
                ], className="upload-panel", style={'position': 'relative'})
            ], style={'flex': '1', 'paddingLeft': '15px'})
            
        ], style={'display': 'flex', 'gap': '15px', 'marginBottom': '15px'}),
        
        # Hidden div for callback compatibility
        html.Div(id="file-requirements-status", style={'display': 'none'}),
        
        # File list and validation messages
        html.Div(id="file-list-display", style={'display': 'none'}),
        html.Div(id="file-validation-messages")
    ], className="panel")

def create_submit_section():
    """Create the side-by-side submit and parameters section."""
    return html.Div([
        # Side-by-side layout: Advanced Parameters (left) and Submit Job (right)
        html.Div([
            # Left side - Advanced Parameters toggle
            html.Div([
                html.Button([
                    html.I(className="fas fa-cog", style={'marginRight': '8px'}),
                    "Advanced Parameters ",
                    html.Small("(optional - click to customize)", style={'color': '#8A9A8A'})
                ], 
                id="toggle-parameters-btn",
                className="btn btn-outline-secondary btn-sm",
                style={
                    'width': '100%', 
                    'textAlign': 'left',
                    'border': '1px dashed #ccc',
                    'backgroundColor': '#f8f9fa',
                    'color': '#5A7A60',
                    'padding': '12px 16px'
                })
            ], style={'flex': '1', 'paddingRight': '15px'}),
            
            # Right side - Submit Job button
            html.Div([
                html.Button([
                    html.I(className="fas fa-server", style={'marginRight': '10px', 'fontSize': '1.1rem'}),
                    "Submit Job"
                ],
                id="submit-job-btn",
                className="btn btn-primary btn-lg",
                disabled=True,
                style={
                    'width': '100%',
                    'padding': '15px 30px',
                    'fontSize': '1.1rem',
                    'fontWeight': '600',
                    'backgroundColor': '#5A7A60',
                    'borderColor': '#5A7A60',
                    'boxShadow': '0 4px 8px rgba(90, 122, 96, 0.3)',
                    'transition': 'all 0.3s ease'
                })
            ], style={'flex': '1', 'paddingLeft': '15px'})
        ], style={'display': 'flex', 'gap': '15px', 'alignItems': 'center', 'marginBottom': '15px'}),
        
        # Status message for submit requirements (full width below)
        html.Div([
            html.Div([
                html.I(className="fas fa-info-circle", style={'marginRight': '8px'}),
                "Upload required files (structure, trajectory, topology) to enable job submission"
            ], 
            id="submit-status-message",
            style={
                'color': '#8A9A8A', 
                'fontSize': '0.9rem',
                'textAlign': 'center',
                'padding': '10px',
                'backgroundColor': '#f8f9fa',
                'borderRadius': '5px',
                'border': '1px dashed #dee2e6'
            })
        ]),
        
        # Collapsible parameters content (full width below the buttons)
        html.Div([
            html.Div([
                # Left column - Basic parameters
                html.Div([
                    html.Div([
                        html.Label("Skip Frames", className="form-label"),
                        html.Small(" (analyze every Nth frame)", style={'color': '#8A9A8A', 'fontSize': '0.8rem'}),
                        dcc.Input(
                            id="skip-frames",
                            type="number",
                            value=1,
                            min=1,
                            max=1000,
                            step=1,
                            className="form-input",
                            style={'width': '100%'}
                        )
                    ], className="form-group"),
                    
                    html.Div([
                        html.Label("Initial Pair Filter Cutoff (Å)", className="form-label"),
                        html.Small(" (initial distance filter)", style={'color': '#8A9A8A', 'fontSize': '0.8rem'}),
                        dcc.Input(
                            id="initpairfilter-cutoff",
                            type="number",
                            value=12.0,
                            min=1.0,
                            max=50.0,
                            step=0.1,
                            className="form-input",
                            style={'width': '100%'}
                        )
                    ], className="form-group")
                ], style={'flex': '1', 'paddingRight': '15px'}),
                
                # Right column - Selection parameters
                html.Div([
                    html.Div([
                        html.Label("Source Selection (Optional)", className="form-label"),
                        html.Small(" (ProDy selection syntax)", style={'color': '#8A9A8A', 'fontSize': '0.8rem'}),
                        dcc.Input(
                            id="source-sel",
                            type="text",
                            placeholder="e.g., protein and resid 1:100",
                            className="form-input",
                            style={'width': '100%'}
                        )
                    ], className="form-group"),
                    
                    html.Div([
                        html.Label("Target Selection (Optional)", className="form-label"),
                        html.Small(" (ProDy selection syntax)", style={'color': '#8A9A8A', 'fontSize': '0.8rem'}),
                        dcc.Input(
                            id="target-sel",
                            type="text",
                            placeholder="e.g., protein and resid 101:200",
                            className="form-input",
                            style={'width': '100%'}
                        )
                    ], className="form-group"),
                    
                    html.Div([
                        dcc.Checklist(
                            id="privacy-setting",
                            options=[{
                                'label': html.Span([
                                    html.I(className="fas fa-lock", style={'marginRight': '8px', 'color': '#5A7A60'}),
                                    "Keep job details private in public queue"
                                ], style={'fontSize': '0.9rem'}),
                                'value': 'private'
                            }],
                            value=[],
                            className="form-check"
                        ),
                        html.Small("Private jobs appear as 'Private Job' in the public job queue", 
                                  style={'color': '#8A9A8A', 'fontSize': '0.8rem', 'marginTop': '5px'})
                    ], className="form-group")
                ], style={'flex': '1', 'paddingLeft': '15px'})
            ], style={'display': 'flex', 'gap': '15px'})
        ], 
        id="parameters-content",
        className="panel",
        style={'display': 'none', 'marginTop': '15px'})
    ], className="panel", style={'marginBottom': '15px'})


def create_job_monitoring_page(job_id: str):
    """Create dedicated job monitoring page."""
    current_url = f"/monitor/{job_id}"
    return html.Div([
        dcc.Location(id='monitor-url', refresh=False),
        dcc.Store(id='monitor-job-id', data=job_id),
        dcc.Interval(id='monitor-refresh-interval', interval=3000, n_intervals=0),  # Refresh every 3 seconds
        
        # Header
        html.Div([
            html.H1([
                html.I(className="fas fa-eye", style={'marginRight': '12px'}),
                "Job Monitor"
            ], className="main-title"),
            html.P(f"Real-time monitoring for job: {job_id}", 
                  style={'textAlign': 'center', 'color': '#5A7A60', 'fontSize': '1.1rem'})
        ]),
        
        # Bookmark reminder
        html.Div([
            html.I(className="fas fa-bookmark", style={'marginRight': '10px', 'fontSize': '1.2rem'}),
            html.Strong("Bookmark this page! "),
            "Save this URL to check your job status anytime: ",
            html.Code(current_url, style={'backgroundColor': 'rgba(255,255,255,0.3)', 'padding': '2px 6px', 'borderRadius': '4px'})
        ], className="bookmark-reminder"),
        
        # Job details section
        html.Div([
            html.Div(id="monitor-job-details", style={'marginBottom': '20px'}),
            html.Div(id="monitor-job-logs", style={'marginBottom': '20px'}),
            
            # Action buttons
            html.Div([
                html.A(
                    [html.I(className="fas fa-arrow-left", style={'marginRight': '8px'}), "Back to Main"],
                    href="/",
                    className="btn btn-secondary",
                    style={'marginRight': '10px'}
                ),
                html.Button(
                    [html.I(className="fas fa-sync", style={'marginRight': '8px'}), "Refresh Now"],
                    id="manual-refresh-btn",
                    className="btn btn-primary"
                )
            ], style={'textAlign': 'center', 'marginTop': '20px'})
        ], style={'maxWidth': '1000px', 'margin': '0 auto', 'padding': '20px'})
    ])

def create_job_queue_page():
    """Create job queue page showing all submitted jobs."""
    return html.Div([
        dcc.Location(id='queue-url', refresh=False),
        
        # Header
        html.Div([
            html.H1([
                html.I(className="fas fa-list", style={'marginRight': '12px'}),
                "Job Queue"
            ], className="main-title"),
            html.P("View all submitted jobs and their current status", 
                  style={'textAlign': 'center', 'color': '#5A7A60', 'fontSize': '1.1rem'})
        ]),
        
        # Queue controls
        html.Div([
            # Filter controls
            html.Div([
                html.Div([
                    html.Label("Status Filter:", style={'marginBottom': '5px', 'fontWeight': 'bold'}),
                    dcc.Dropdown(
                        id='queue-status-filter',
                        options=[
                            {'label': 'All Jobs', 'value': 'all'},
                            {'label': 'Pending', 'value': 'pending'},
                            {'label': 'Queued', 'value': 'queued'},
                            {'label': 'Running', 'value': 'running'},
                            {'label': 'Completed', 'value': 'completed'},
                            {'label': 'Failed', 'value': 'failed'},
                            {'label': 'Cancelled', 'value': 'cancelled'}
                        ],
                        value='all',
                        style={'width': '200px'}
                    )
                ], style={'display': 'inline-block', 'marginRight': '20px'}),
                
                html.Button(
                    [html.I(className="fas fa-sync", style={'marginRight': '8px'}), "Refresh Queue"],
                    id="queue-refresh-btn",
                    className="btn btn-primary",
                    style={'verticalAlign': 'bottom'}
                )
            ], style={'marginBottom': '20px', 'textAlign': 'left'}),
            
            # Jobs table
            html.Div(id="queue-jobs-table"),
            
            # Auto-refresh interval
            dcc.Interval(id='queue-refresh-interval', interval=10000, n_intervals=0),  # Refresh every 10 seconds
            
            # Back button
            html.Div([
                html.A(
                    [html.I(className="fas fa-arrow-left", style={'marginRight': '8px'}), "Back to Main"],
                    href="/",
                    className="btn btn-secondary"
                )
            ], style={'textAlign': 'center', 'marginTop': '30px'})
            
        ], style={'maxWidth': '1200px', 'margin': '0 auto', 'padding': '20px'})
    ])

def create_results_page(job_id: str):
    """Create results viewing page."""
    return html.Div([
        dcc.Location(id='results-url', refresh=False),
        dcc.Store(id='results-job-id', data=job_id),
        
        # Header
        html.Div([
            html.H1([
                html.I(className="fas fa-chart-bar", style={'marginRight': '12px'}),
                "Job Results"
            ], className="main-title"),
            html.P(f"Analysis results for job: {job_id}", 
                  style={'textAlign': 'center', 'color': '#5A7A60', 'fontSize': '1.1rem'})
        ]),
        
        # Results content
        html.Div([
            html.Div(id="results-content"),
            
            # Back button
            html.Div([
                html.A(
                    [html.I(className="fas fa-arrow-left", style={'marginRight': '8px'}), "Back to Main"],
                    href="/",
                    className="btn btn-secondary"
                )
            ], style={'textAlign': 'center', 'marginTop': '20px'})
        ], style={'maxWidth': '1000px', 'margin': '0 auto', 'padding': '20px'})
    ])

# Main layout with URL routing
app.layout = html.Div([
    dcc.Location(id='url', refresh=False),
    html.Div(id='page-content')
])

# URL routing callback
@app.callback(
    Output('page-content', 'children'),
    [Input('url', 'pathname')]
)
def display_page(pathname):
    """Handle URL routing for different pages."""
    if pathname is None or pathname == '/':
        # Main page
        return html.Div([
            dcc.Store(id='uploaded-files-store', data=[]),
            # Hidden force field selector - always present for callback consistency
            html.Div([
                dcc.Dropdown(
                    id='force-field-selector',
                    options=[
                        {'label': 'AMBER99SB-ILDN', 'value': 'amber99sb-ildn'},
                        {'label': 'CHARMM27', 'value': 'charmm27'},
                        {'label': 'OPLS-AA/L', 'value': 'oplsaa'},
                        {'label': 'GROMOS96 43a1', 'value': 'gromos43a1'},
                        {'label': 'GROMOS96 53a6', 'value': 'gromos53a6'},
                        {'label': 'AMBER03', 'value': 'amber03'},
                        {'label': 'AMBER99SB', 'value': 'amber99sb'}
                    ],
                    value='amber99sb-ildn'
                )
            ], style={'display': 'none'}),
            
            create_header(),
            
            html.Div([
                create_input_mode_selector(),
                create_file_upload_section(),
                create_submit_section(),
                # Submission status area
                html.Div(id="submission-status", children=[], style={'marginTop': '20px'})
            ], style={'maxWidth': '1200px', 'margin': '0 auto', 'padding': '20px'})
        ])
    elif pathname.startswith('/monitor/'):
        # Job monitoring page
        job_id = pathname.split('/')[-1]
        return create_job_monitoring_page(job_id)
    elif pathname == '/queue':
        # Job queue page
        return create_job_queue_page()
    elif pathname.startswith('/results/'):
        # Results viewing page
        job_id = pathname.split('/')[-1]
        return create_results_page(job_id)
    elif pathname.startswith('/dashboard/'):
        # Dashboard page - redirect to dashboard server
        job_id = pathname.split('/')[-1]
        
        try:
            # Get dashboard URL from backend
            backend_url = f"http://{config.backend_host}:{config.backend_port}/api/jobs/{job_id}/dashboard"
            response = requests.get(backend_url, timeout=10)
            
            if response.status_code == 200:
                dashboard_data = response.json()
                dashboard_url = dashboard_data.get('dashboard_url')
                
                return html.Div([
                    dcc.Location(id=f'dashboard-redirect-{job_id}', href=dashboard_url, refresh=True),
                    html.Div([
                        html.H1([
                            html.I(className="fas fa-chart-network", style={'marginRight': '12px'}),
                            "Loading Dashboard..."
                        ], className="main-title"),
                        html.P(f"Redirecting to dashboard for job: {job_id}", 
                              style={'textAlign': 'center', 'color': '#5A7A60'}),
                        html.Div([
                            html.I(className="fas fa-spinner fa-spin", style={'marginRight': '8px'}),
                            "Please wait while we load your interactive dashboard..."
                        ], style={'textAlign': 'center', 'padding': '20px'})
                    ], style={'maxWidth': '600px', 'margin': '50px auto', 'textAlign': 'center'})
                ])
            else:
                return html.Div([
                    html.H1("Dashboard Error"),
                    html.Div([
                        html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                        f"Failed to load dashboard: {response.status_code}"
                    ], className="alert alert-danger"),
                    html.A("Go back to main page", href="/", className="btn btn-secondary")
                ])
                
        except Exception as e:
            logger.error(f"Error accessing dashboard for job {job_id}: {e}")
            return html.Div([
                html.H1("Dashboard Error"),
                html.Div([
                    html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                    f"Error loading dashboard: {str(e)}"
                ], className="alert alert-danger"),
                html.A("Go back to main page", href="/", className="btn btn-secondary")
            ])
    elif pathname == '/queue':
        # Public job queue page
        return create_job_queue_page()
    else:
        # 404 page
        return html.Div([
            html.H1("404 - Page Not Found"),
            html.A("Go back to main page", href="/")
        ])

# Callbacks

@app.callback(
    [Output('mode-specific-instructions', 'children'),
     Output('file-requirements-status', 'children')],
    [Input('input-mode-selector', 'value')]
)
def update_mode_instructions(mode):
    """Update file requirements and instructions based on selected input mode."""
    if mode == 'ensemble':
        # PDB conformational ensemble mode
        instructions = html.Div([
            html.Div([
                html.Strong("PDB Ensemble Mode", style={'color': '#5A7A60', 'display': 'block', 'marginBottom': '8px'}),
                html.Div([
                    html.Strong("Required: "),
                    "Multi-model PDB file"
                ], style={'fontSize': '0.9rem', 'marginBottom': '8px'}),
                
                # Force field selector for display
                html.Div([
                    html.Label("Force Field:", style={'fontWeight': 'bold', 'fontSize': '0.9rem', 'marginBottom': '3px', 'display': 'block'}),
                    dcc.Dropdown(
                        id='force-field-display',
                        options=[
                            {'label': 'AMBER99SB-ILDN', 'value': 'amber99sb-ildn'},
                            {'label': 'CHARMM27', 'value': 'charmm27'},
                            {'label': 'OPLS-AA/L', 'value': 'oplsaa'},
                            {'label': 'GROMOS96 43a1', 'value': 'gromos43a1'},
                            {'label': 'GROMOS96 53a6', 'value': 'gromos53a6'},
                            {'label': 'AMBER03', 'value': 'amber03'},
                            {'label': 'AMBER99SB', 'value': 'amber99sb'}
                        ],
                        value='amber99sb-ildn',
                        placeholder="Select force field...",
                        style={'fontSize': '0.9rem'}
                    )
                ], style={'marginTop': '8px'}),
                
                html.Div([
                    html.I(className="fas fa-info-circle", style={'marginRight': '5px'}),
                    "Topology auto-generated"
                ], style={'fontSize': '0.8rem', 'color': '#666', 'marginTop': '8px'})
            ])
        ], style={'padding': '12px', 'backgroundColor': '#f8f9fa', 'borderRadius': '5px', 'border': '1px solid #dee2e6'})
        
    else:  # trajectory mode (default)
        instructions = html.Div([
            html.Div([
                html.Strong("Trajectory Mode", style={'color': '#5A7A60', 'display': 'block', 'marginBottom': '8px'}),
                html.Div([
                    html.Strong("Required: "),
                    html.Ul([
                        html.Li("Structure (.pdb/.gro)", style={'margin': '2px 0'}),
                        html.Li("Trajectory (.xtc/.trr, max 100MB)", style={'margin': '2px 0'}),
                        html.Li("Topology (.tpr/.top)", style={'margin': '2px 0'})
                    ], style={'fontSize': '0.85rem', 'marginTop': '5px', 'marginBottom': '5px', 'paddingLeft': '20px'})
                ], style={'fontSize': '0.9rem', 'marginBottom': '5px'}),
                
                html.Div([
                    html.Strong("Optional: "),
                    "Restraint files (.itp), topology includes"
                ], style={'fontSize': '0.85rem', 'color': '#666'})
            ])
        ], style={'padding': '12px', 'backgroundColor': '#f8f9fa', 'borderRadius': '5px', 'border': '1px solid #dee2e6'})
    
    return [instructions, html.Div()]  # Return as list

# Sync display force field selector with hidden one
@app.callback(
    Output('force-field-selector', 'value'),
    [Input('force-field-display', 'value')],
    prevent_initial_call=True
)
def sync_force_field_selector(display_value):
    """Sync the hidden force field selector with the display one."""
    return display_value if display_value is not None else 'amber99sb-ildn'

@app.callback(
    [Output('file-list-display', 'children'),
     Output('file-list-display', 'style'),
     Output('file-validation-messages', 'children'),
     Output('uploaded-files-store', 'data'),
     Output('submit-job-btn', 'disabled'),
     Output('submit-status-message', 'children'),
     Output('submit-status-message', 'style')],
    [Input('upload-files', 'contents'),
     Input('input-mode-selector', 'value')],
    [State('upload-files', 'filename'),
     State('uploaded-files-store', 'data')]
)
def handle_file_upload(contents, input_mode, filenames, stored_files):
    """Handle file upload and validation."""
    if not contents:
        return [], {'display': 'none'}, [], stored_files, True, [
            html.I(className="fas fa-info-circle", style={'marginRight': '8px'}),
            "Upload required files to enable analysis"
        ], {
            'color': '#8A9A8A', 
            'fontSize': '0.9rem',
            'textAlign': 'center',
            'padding': '10px',
            'backgroundColor': '#f8f9fa',
            'borderRadius': '5px',
            'border': '1px dashed #dee2e6'
        }
    
    if not isinstance(contents, list):
        contents = [contents]
        filenames = [filenames]
    
    files = stored_files.copy()
    validation_messages = []
    
    for content, filename in zip(contents, filenames):
        # Decode file content
        content_type, content_string = content.split(',')
        file_size = len(base64.b64decode(content_string))
        
        # Determine file type first
        extension = filename.lower().split('.')[-1] if '.' in filename else ''
        try:
            file_type = FileType(extension)
        except ValueError:
            validation_messages.append(
                html.Div([
                    html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                    f"Unsupported file type: {filename}. Supported formats: PDB, XTC, TRR, TPR, GRO, TOP, ITP, RTP."
                ], className="alert alert-warning")
            )
            continue
        
        # Validate file size based on type
        is_trajectory = extension in ['xtc', 'trr']
        max_size = (config.max_trajectory_file_size_mb if is_trajectory else config.max_other_file_size_mb) * 1024 * 1024
        max_size_label = f"{config.max_trajectory_file_size_mb}MB" if is_trajectory else f"{config.max_other_file_size_mb}MB"
        
        if file_size > max_size:
            validation_messages.append(
                html.Div([
                    html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                    f"File {filename} is too large ({file_size/1024/1024:.1f}MB). Maximum size for {'trajectory' if is_trajectory else 'other'} files is {max_size_label}."
                ], className="alert alert-danger")
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
                        id={'type': 'remove-file', 'index': files.index(file_data)},
                        className="btn btn-danger",
                        style={'fontSize': '0.8rem', 'padding': '4px 8px'},
                        title=f"Remove {file_data['filename']}"
                    )
                ], className="file-actions")
            ], className="file-item")
        )
    
    # Validation based on input mode
    if input_mode == 'ensemble':
        # For ensemble mode, only need a multi-model PDB file
        has_pdb = any(f['file_type'] == 'pdb' for f in files)
        required_files_met = has_pdb
        
        # Add file requirements status message
        if files:
            requirements_status = []
            requirements_status.append(html.Li([
                html.I(className="fas fa-check" if has_pdb else "fas fa-times", 
                       style={'color': 'green' if has_pdb else 'red', 'marginRight': '8px'}),
                "Multi-model PDB file"
            ]))
            
            validation_messages.append(
                html.Div([
                    html.H6("File Requirements:", style={'marginBottom': '10px'}),
                    html.Ul(requirements_status, style={'marginBottom': '10px'}),
                    html.P("Multi-model PDB file is required for ensemble analysis. Topology will be generated automatically.",
                           style={'color': '#666', 'fontSize': '0.9rem', 'marginBottom': '0'})
                ], className="alert alert-info" if required_files_met else "alert alert-warning")
            )
    else:
        # For trajectory mode, need structure, trajectory, and topology
        has_structure = any(f['file_type'] in ['gro', 'pdb'] for f in files)
        has_trajectory = any(f['file_type'] in ['xtc', 'trr'] for f in files) 
        has_topology = any(f['file_type'] in ['tpr', 'top'] for f in files)
        required_files_met = has_structure and has_trajectory and has_topology
        
        # Add file requirements status message
        if files:
            requirements_status = []
            requirements_status.append(html.Li([
                html.I(className="fas fa-check" if has_structure else "fas fa-times", 
                       style={'color': 'green' if has_structure else 'red', 'marginRight': '8px'}),
                "Structure file (GRO/PDB)"
            ]))
            requirements_status.append(html.Li([
                html.I(className="fas fa-check" if has_trajectory else "fas fa-times",
                       style={'color': 'green' if has_trajectory else 'red', 'marginRight': '8px'}),
                "Trajectory file (XTC/TRR)"
            ]))
            requirements_status.append(html.Li([
                html.I(className="fas fa-check" if has_topology else "fas fa-times",
                       style={'color': 'green' if has_topology else 'red', 'marginRight': '8px'}),
                "Topology file (TPR/TOP)"
            ]))
            
            validation_messages.append(
                html.Div([
                    html.H6("File Requirements:", style={'marginBottom': '10px'}),
                    html.Ul(requirements_status, style={'marginBottom': '10px'}),
                    html.P("All three file types are required to proceed with trajectory analysis.",
                           style={'color': '#666', 'fontSize': '0.9rem', 'marginBottom': '0'})
                ], className="alert alert-info" if required_files_met else "alert alert-warning")
            )
    
    submit_disabled = not required_files_met
    style = {'display': 'block'} if files else {'display': 'none'}
    
    # Create submit status message
    if required_files_met:
        submit_message = [
            html.I(className="fas fa-check-circle", style={'marginRight': '8px'}),
            "Ready to submit job! Click Submit Job to process on remote server."
        ]
        submit_style = {
            'color': '#28a745', 
            'fontSize': '0.9rem',
            'textAlign': 'center',
            'padding': '10px',
            'backgroundColor': '#d4edda',
            'borderRadius': '5px',
            'border': '1px solid #c3e6cb'
        }
    elif files:
        submit_message = [
            html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
            "Missing required files - upload all three file types to proceed"
        ]
        submit_style = {
            'color': '#856404', 
            'fontSize': '0.9rem',
            'textAlign': 'center',
            'padding': '10px',
            'backgroundColor': '#fff3cd',
            'borderRadius': '5px',
            'border': '1px solid #ffeaa7'
        }
    else:
        submit_message = [
            html.I(className="fas fa-info-circle", style={'marginRight': '8px'}),
            "Upload required files (structure, trajectory, topology) to enable analysis"
        ]
        submit_style = {
            'color': '#8A9A8A', 
            'fontSize': '0.9rem',
            'textAlign': 'center',
            'padding': '10px',
            'backgroundColor': '#f8f9fa',
            'borderRadius': '5px',
            'border': '1px dashed #dee2e6'
        }
    
    return file_list_items, style, validation_messages, files, submit_disabled, submit_message, submit_style

@app.callback(
    [Output('parameters-content', 'style'),
     Output('toggle-parameters-btn', 'children')],
    [Input('toggle-parameters-btn', 'n_clicks')],
    [State('parameters-content', 'style')]
)
def toggle_parameters(n_clicks, current_style):
    """Toggle the advanced parameters section."""
    if n_clicks is None:
        # Initial state - collapsed
        return {'display': 'none'}, [
            html.I(className="fas fa-cog", style={'marginRight': '8px'}),
            "Advanced Parameters ",
            html.Small("(optional - click to customize)", style={'color': '#8A9A8A'})
        ]
    
    # Toggle display
    if current_style.get('display') == 'none':
        # Show parameters
        return {
            'display': 'block', 
            'marginTop': '15px'
        }, [
            html.I(className="fas fa-cog", style={'marginRight': '8px'}),
            "Advanced Parameters ",
            html.Small("(click to hide)", style={'color': '#8A9A8A'})
        ]
    else:
        # Hide parameters
        return {'display': 'none'}, [
            html.I(className="fas fa-cog", style={'marginRight': '8px'}),
            "Advanced Parameters ",
            html.Small("(optional - click to customize)", style={'color': '#8A9A8A'})
        ]

# Separate callback to update display when files are removed
@app.callback(
    [Output('file-list-display', 'children', allow_duplicate=True),
     Output('file-list-display', 'style', allow_duplicate=True),
     Output('file-validation-messages', 'children', allow_duplicate=True),
     Output('submit-job-btn', 'disabled', allow_duplicate=True),
     Output('submit-status-message', 'children', allow_duplicate=True),
     Output('submit-status-message', 'style', allow_duplicate=True)],
    [Input('uploaded-files-store', 'data')],
    [State('input-mode-selector', 'value')],
    prevent_initial_call=True
)
def update_file_display_on_removal(stored_files, input_mode):
    """Update file display when files are removed from store."""
    if not stored_files:
        # No files - hide display and disable submit
        return [], {'display': 'none'}, [], True, [
            html.I(className="fas fa-info-circle", style={'marginRight': '8px'}),
            "Upload required files to enable analysis"
        ], {
            'color': '#8A9A8A', 
            'fontStyle': 'italic',
            'textAlign': 'center'
        }
    
    # Use the same logic as the main file upload handler
    files = stored_files
    input_mode = input_mode or 'trajectory'
    
    # Create file list display (same logic as in handle_file_upload)
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
                        id={'type': 'remove-file', 'index': files.index(file_data)},
                        className="btn btn-danger",
                        style={'fontSize': '0.8rem', 'padding': '4px 8px'},
                        title=f"Remove {file_data['filename']}"
                    )
                ], className="file-actions")
            ], className="file-item")
        )
    
    # Validation based on input mode
    validation_messages = []
    if input_mode == 'ensemble':
        # For ensemble mode, only need a multi-model PDB file
        has_pdb = any(f['file_type'] == 'pdb' for f in files)
        required_files_met = has_pdb
        
        if files:
            if has_pdb:
                validation_messages.append(
                    html.Div([
                        html.I(className="fas fa-check-circle", style={'color': 'green', 'marginRight': '8px'}),
                        "Ready for ensemble analysis"
                    ], className="alert alert-success")
                )
            else:
                validation_messages.append(
                    html.Div([
                        html.I(className="fas fa-exclamation-triangle", style={'color': 'orange', 'marginRight': '8px'}),
                        "Need a PDB file with multiple models for ensemble analysis"
                    ], className="alert alert-warning")
                )
    else:
        # Trajectory mode requirements
        has_structure = any(f['file_type'] in ['pdb', 'gro'] for f in files)
        has_topology = any(f['file_type'] in ['tpr', 'top'] for f in files)
        has_trajectory = any(f['file_type'] in ['xtc', 'trr'] for f in files)
        required_files_met = has_structure and has_topology and has_trajectory
        
        if files:
            missing = []
            if not has_structure:
                missing.append("structure file (PDB/GRO)")
            if not has_topology:
                missing.append("topology file (TPR/TOP)")
            if not has_trajectory:
                missing.append("trajectory file (XTC/TRR)")
            
            if missing:
                validation_messages.append(
                    html.Div([
                        html.I(className="fas fa-exclamation-triangle", style={'color': 'orange', 'marginRight': '8px'}),
                        f"Missing: {', '.join(missing)}"
                    ], className="alert alert-warning")
                )
            else:
                validation_messages.append(
                    html.Div([
                        html.I(className="fas fa-check-circle", style={'color': 'green', 'marginRight': '8px'}),
                        "All required files uploaded"
                    ], className="alert alert-success")
                )
    
    # Submit button state and status
    submit_disabled = not required_files_met
    if required_files_met:
        status_message = [
            html.I(className="fas fa-check-circle", style={'color': 'green', 'marginRight': '8px'}),
            "Ready to submit job"
        ]
        status_style = {
            'color': 'green', 
            'fontWeight': 'bold',
            'textAlign': 'center'
        }
    else:
        status_message = [
            html.I(className="fas fa-upload", style={'marginRight': '8px'}),
            "Upload required files to enable analysis"
        ]
        status_style = {
            'color': '#8A9A8A', 
            'fontStyle': 'italic',
            'textAlign': 'center'
        }
    
    return file_list_items, {'display': 'block'}, validation_messages, submit_disabled, status_message, status_style

# Clear upload component when files are removed to allow re-uploading the same file
@app.callback(
    Output('upload-files', 'contents', allow_duplicate=True),
    [Input({'type': 'remove-file', 'index': dash.dependencies.ALL}, 'n_clicks')],
    prevent_initial_call=True
)
def clear_upload_on_removal(n_clicks):
    """Clear the upload component when files are removed to allow re-uploading same files."""
    if any(n_clicks):
        return None
    return no_update

@app.callback(
    Output('uploaded-files-store', 'data', allow_duplicate=True),
    [Input({'type': 'remove-file', 'index': dash.dependencies.ALL}, 'n_clicks')],
    [State('uploaded-files-store', 'data')],
    prevent_initial_call=True
)
def remove_file(n_clicks, stored_files):
    """Remove a file from the upload list."""
    if not any(n_clicks) or not stored_files:
        return stored_files
    
    # Find which button was clicked
    ctx = callback_context
    if not ctx.triggered:
        return stored_files
    
    # For pattern-matching callbacks, the prop_id contains the full component ID
    triggered_id = ctx.triggered[0]['prop_id']
    
    try:
        # Extract the JSON part from the prop_id (before the '.n_clicks')
        button_id_str = triggered_id.split('.')[0]
        button_data = json.loads(button_id_str)
        index_to_remove = button_data['index']
        
        # Validate index
        if 0 <= index_to_remove < len(stored_files):
            filename_to_remove = stored_files[index_to_remove]['filename']
            # Remove the file at the specified index
            updated_files = [f for i, f in enumerate(stored_files) if i != index_to_remove]
            logger.info(f"Removed file: {filename_to_remove}, Remaining files: {len(updated_files)}")
            return updated_files
        else:
            logger.warning(f"Invalid index to remove: {index_to_remove}, file list length: {len(stored_files)}")
            return stored_files
            
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
        logger.error(f"Error parsing button ID: {triggered_id}, Error: {e}")
        return stored_files

# Note: Old submit_job_to_backend function removed - now using signed URL workflow for direct GCS uploads

# Add div to show submission status
@app.callback(
    [Output('submission-status', 'children'),
     Output('uploaded-files-store', 'data', allow_duplicate=True)],
    [Input('submit-job-btn', 'n_clicks')],
    [State('skip-frames', 'value'),
     State('initpairfilter-cutoff', 'value'),
     State('source-sel', 'value'),
     State('target-sel', 'value'),
     State('privacy-setting', 'value'),
     State('input-mode-selector', 'value'),
     State('force-field-selector', 'value'),
     State('uploaded-files-store', 'data')],
    prevent_initial_call=True
)
def handle_job_submission(submit_clicks, skip_frames, initpairfilter_cutoff, 
                         source_sel, target_sel, privacy_setting, input_mode, 
                         force_field, uploaded_files):
    """Handle job submission with direct GCS upload using signed URLs."""
    logger.info(f"Job submission callback triggered: submit_clicks={submit_clicks}, files={len(uploaded_files) if uploaded_files else 0}")
    
    if not submit_clicks:
        logger.info("No submit clicks, returning no_update")
        return no_update, no_update
        
    if not uploaded_files:
        logger.warning("No uploaded files for job submission")
        return html.Div("Please upload files to submit a job.", className="alert alert-danger"), no_update
    
    try:
        # Generate job name automatically based on timestamp and files
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        structure_file = next((f['filename'] for f in uploaded_files if f['file_type'] in ['gro', 'pdb']), 'structure')
        mode_prefix = "ensemble" if input_mode == 'ensemble' else "trajectory"
        job_name = f"gRINN_{mode_prefix}_{structure_file.split('.')[0]}_{timestamp}"
        
        # Step 1: Request signed URLs from backend
        files_info = []
        for file_data in uploaded_files:
            files_info.append({
                'filename': file_data['filename'],
                'file_type': file_data.get('file_type', 'unknown'),
                'content_type': 'application/octet-stream',  # Generic binary
                'size': file_data.get('size_bytes', 0)
            })
        
        is_private = 'private' in (privacy_setting or [])
        
        backend_url = f"http://{config.backend_host}:{config.backend_port}/api/generate-upload-urls"
        logger.info(f"Requesting signed URLs from {backend_url}")
        
        response = requests.post(
            backend_url,
            json={
                'files': files_info,
                'input_mode': input_mode or 'trajectory',
                'force_field': force_field if input_mode == 'ensemble' else None,
                'parameters': {
                    'skip_frames': skip_frames or 1,
                    'initpairfilter_cutoff': initpairfilter_cutoff or 12.0,
                    'source_sel': source_sel or None,
                    'target_sel': target_sel or None
                },
                'is_private': is_private,
                'job_name': job_name,
                'description': f"{'Ensemble' if input_mode == 'ensemble' else 'Trajectory'} analysis using gRINN"
            },
            timeout=30
        )
        
        if response.status_code != 200:
            error_msg = response.json().get('error', 'Unknown error')
            return html.Div([
                html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                f"Failed to initiate upload: {error_msg}"
            ], className="alert alert-danger"), no_update
        
        result = response.json()
        job_id = result['job_id']
        upload_urls = result['upload_urls']
        
        logger.info(f"Received {len(upload_urls)} signed URLs for job {job_id}")
        
        # Step 2: Upload files directly to GCS using signed URLs (or handle mock storage)
        uploaded_successfully = []
        
        for url_info in upload_urls:
            # Find the corresponding file data
            file_data = next((f for f in uploaded_files if f['filename'] == url_info['filename']), None)
            if not file_data:
                logger.error(f"Could not find file data for {url_info['filename']}")
                continue
            
            # Decode base64 content
            # Note: content is already the base64 string (without the data URI prefix)
            # since it was stored that way in handle_file_upload
            try:
                content = base64.b64decode(file_data['content'])
            except Exception as e:
                logger.error(f"Failed to decode file {url_info['filename']}: {e}")
                continue
            
            upload_url = url_info['upload_url']
            
            # Check if using mock storage (local development)
            if upload_url.startswith('mock://'):
                logger.info(f"Mock storage detected - writing {url_info['filename']} to local file ({len(content)} bytes)")
                try:
                    # Write directly to the file path provided by mock storage
                    os.makedirs(os.path.dirname(url_info['file_path']), exist_ok=True)
                    with open(url_info['file_path'], 'wb') as f:
                        f.write(content)
                    
                    uploaded_successfully.append({
                        'file_type': url_info['file_type'],
                        'filename': url_info['filename'],
                        'file_path': url_info['file_path']
                    })
                    logger.info(f"Successfully wrote {url_info['filename']} to {url_info['file_path']}")
                except Exception as e:
                    error_msg = f"Mock storage write error for {url_info['filename']}: {str(e)}"
                    logger.error(error_msg)
                    return html.Div([
                        html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                        error_msg
                    ], className="alert alert-danger"), no_update
            else:
                # Upload directly to GCS using signed URL
                logger.info(f"Uploading {url_info['filename']} directly to GCS ({len(content)} bytes)")
                
                try:
                    upload_response = requests.put(
                        upload_url,
                        data=content,
                        headers={'Content-Type': 'application/octet-stream'},
                        timeout=300  # 5 minutes for large files
                    )
                    
                    if upload_response.status_code in [200, 201]:
                        uploaded_successfully.append({
                            'file_type': url_info['file_type'],
                            'filename': url_info['filename'],
                            'file_path': url_info['file_path']
                        })
                        logger.info(f"Successfully uploaded {url_info['filename']}")
                    else:
                        error_msg = f"Upload failed for {url_info['filename']}: HTTP {upload_response.status_code}"
                        logger.error(error_msg)
                        return html.Div([
                            html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                            error_msg
                        ], className="alert alert-danger"), no_update
                        
                except Exception as e:
                    error_msg = f"Upload error for {url_info['filename']}: {str(e)}"
                    logger.error(error_msg)
                return html.Div([
                    html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                    error_msg
                ], className="alert alert-danger"), no_update
        
        # Step 3: Confirm uploads and start processing
        logger.info(f"Confirming {len(uploaded_successfully)} uploads for job {job_id}")
        
        confirm_url = f"http://{config.backend_host}:{config.backend_port}/api/jobs/{job_id}/confirm-uploads"
        confirm_response = requests.post(
            confirm_url,
            json={'uploaded_files': uploaded_successfully},
            timeout=30
        )
        
        if confirm_response.status_code != 200:
            error_msg = confirm_response.json().get('error', 'Failed to start processing')
            return html.Div([
                html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                f"Files uploaded but processing failed: {error_msg}"
            ], className="alert alert-danger"), no_update
        
        logger.info(f"Job {job_id} submitted successfully")
        
        # Show success message and auto-open monitoring page
        success_message = html.Div([
            html.Div([
                html.I(className="fas fa-check-circle", style={'color': 'green', 'marginRight': '8px'}),
                html.Strong("Job submitted successfully!")
            ], className="alert alert-success"),
            
            html.Div([
                html.P(f"Job ID: {job_id}"),
                html.P(f"Job Name: {job_name}"),
                html.P(f"Analysis Mode: {input_mode or 'trajectory'}"),
                html.P(f"Files uploaded: {len(uploaded_successfully)}"),
                html.P("Monitoring page will open in a new tab automatically."),
            ], className="info-card"),
            
            # Hidden div to trigger client-side callback
            html.Div(job_id, id="job-id-trigger", style={'display': 'none'})
        ])
        
        # Clear uploaded files after successful submission
        return success_message, []
        
    except Exception as e:
        logger.error(f"Error submitting job: {e}")
        return html.Div([
            html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
            f"Error submitting job: {str(e)}"
        ], className="alert alert-danger"), no_update

# Client-side callback to open monitoring page in new tab
app.clientside_callback(
    """
    function(job_id) {
        if (job_id && job_id !== '') {
            // Open monitoring page in new tab
            window.open('/monitor/' + job_id, '_blank');
        }
        return '';
    }
    """,
    Output('job-id-trigger', 'children'),
    Input('job-id-trigger', 'children'),
    prevent_initial_call=True
)

# Monitoring page callbacks
@app.callback(
    [Output('monitor-job-details', 'children'),
     Output('monitor-job-logs', 'children')],
    [Input('monitor-refresh-interval', 'n_intervals'),
     Input('manual-refresh-btn', 'n_clicks')],
    [State('monitor-job-id', 'data')],
    prevent_initial_call=True
)
def update_monitor_page(n_intervals, manual_refresh, job_id):
    """Update the job monitoring page with real-time data."""
    try:
        # Fetch job details from backend
        backend_url = f"http://{config.backend_host}:{config.backend_port}/api/jobs/{job_id}"
        response = requests.get(backend_url, timeout=10)
        
        if response.status_code != 200:
            return [
                html.Div([
                    html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                    f"Failed to fetch job details: {response.status_code}"
                ], className="alert alert-danger")
            ], []
        
        job_data = response.json()
        job = Job.from_dict(job_data)
        
        # Create detailed job information
        job_details = html.Div([
            html.H3("Job Details", style={'color': '#5A7A60', 'marginBottom': '15px'}),
            
            html.Div([
                # Job info cards
                html.Div([
                    html.Div([
                        html.H5(job.job_name or f"Job {job.job_id[:8]}", style={'margin': '0'}),
                        html.P(job.description or "No description", style={'margin': '5px 0', 'color': '#666'}),
                        html.Small(f"Created: {job.created_at.strftime('%Y-%m-%d %H:%M:%S')}", style={'color': '#8A9A8A'})
                    ], className="panel", style={'flex': '1', 'marginRight': '10px'}),
                    
                    html.Div([
                        html.H5("Status", style={'margin': '0 0 10px 0'}),
                        html.Span(job.status.value.title() if isinstance(job.status, JobStatus) else job.status.title(), 
                                className=f"job-status status-{job.status.value if isinstance(job.status, JobStatus) else job.status}",
                                style={'fontSize': '1.1rem', 'padding': '8px 16px'}),
                        html.P(job.current_step or "No current step", 
                              style={'margin': '10px 0 0 0', 'color': '#5A7A60'})
                    ], className="panel", style={'flex': '1', 'marginLeft': '10px'})
                ], style={'display': 'flex', 'marginBottom': '20px'}),
                
                # Progress section
                html.Div([
                    html.H5("Progress", style={'marginBottom': '10px'}),
                    
                    # Progress bar
                    html.Div([
                        html.Div(
                            style={
                                'width': f'{job.progress_percentage}%' if job.progress_percentage else '0%',
                                'height': '100%',
                                'background': 'linear-gradient(90deg, #7C9885, #5A7A60)',
                                'borderRadius': '10px',
                                'transition': 'width 0.3s ease'
                            }
                        )
                    ], className="progress-bar", style={'height': '20px', 'marginBottom': '10px'}),
                    
                    html.P(f"Progress: {job.progress_percentage or 0}%", 
                          style={'margin': '0', 'fontSize': '0.9rem', 'color': '#666'})
                ], className="panel"),
                
                # Files section
                html.Div([
                    html.H5("Input Files", style={'marginBottom': '10px'}),
                    html.Ul([
                        html.Li([
                            html.I(className="fas fa-file", style={'marginRight': '8px', 'color': '#5A7A60'}),
                            f"{file_info.filename} ({file_info.file_type.value.upper()}, {file_info.size_bytes/1024/1024:.1f} MB)"
                        ]) for file_info in job.input_files
                    ] if job.input_files else [html.Li("No files information available")])
                ], className="panel", style={'marginTop': '20px'})
            ])
        ])
        
        # Create log section (placeholder for now)
        job_logs = html.Div([
            html.H3("Job Logs", style={'color': '#5A7A60', 'marginBottom': '15px'}),
            html.Div([
                html.Pre(
                    job.error_message if job.error_message else "No logs available yet.",
                    style={
                        'backgroundColor': '#f8f9fa', 
                        'padding': '15px', 
                        'borderRadius': '5px',
                        'fontSize': '0.9rem',
                        'maxHeight': '300px',
                        'overflow': 'auto',
                        'color': '#d32f2f' if job.error_message else '#666'
                    }
                )
            ], className="panel")
        ])
        
        return job_details, job_logs
        
    except Exception as e:
        logger.error(f"Error updating monitor page for job {job_id}: {e}")
        return [
            html.Div([
                html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                f"Error loading job details: {str(e)}"
            ], className="alert alert-danger")
        ], []

# Results page callback
@app.callback(
    Output('results-content', 'children'),
    [Input('results-job-id', 'data')],
    prevent_initial_call=True
)
def update_results_page(job_id):
    """Update the results viewing page."""
    try:
        # Fetch job details from backend
        backend_url = f"http://{config.backend_host}:{config.backend_port}/api/jobs/{job_id}"
        response = requests.get(backend_url, timeout=10)
        
        if response.status_code != 200:
            return html.Div([
                html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                f"Failed to fetch job results: {response.status_code}"
            ], className="alert alert-danger")
        
        job_data = response.json()
        job = Job.from_dict(job_data)
        
        if job.status != JobStatus.COMPLETED:
            status_display = job.status.value.title() if isinstance(job.status, JobStatus) else job.status.title()
            return html.Div([
                html.I(className="fas fa-info-circle", style={'marginRight': '8px'}),
                f"Job is not completed yet. Current status: {status_display}"
            ], className="alert alert-info")
        
        if not job.results_gcs_path:
            return html.Div([
                html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                "No results available for this job."
            ], className="alert alert-warning")
        
        # Fetch detailed results information
        try:
            results_url = f"http://{config.backend_host}:{config.backend_port}/api/jobs/{job_id}/results"
            results_response = requests.get(results_url, timeout=10)
            
            if results_response.status_code == 200:
                results_data = results_response.json()
                result_files = results_data.get('files', [])
                download_urls = results_data.get('download_urls', {})
            else:
                result_files = []
                download_urls = {}
                
        except Exception as e:
            logger.error(f"Error fetching results data for job {job_id}: {e}")
            result_files = []
            download_urls = {}
        
        # Display results information
        return html.Div([
            html.H3("Analysis Results Available", style={'color': '#5A7A60', 'marginBottom': '20px'}),
            
            html.Div([
                html.P([
                    html.I(className="fas fa-check-circle", style={'color': 'green', 'marginRight': '8px'}),
                    "gRINN analysis completed successfully!"
                ], style={'fontSize': '1.1rem', 'marginBottom': '20px'}),
                
                # Results files section
                html.Div([
                    html.H4("Available Result Files", style={'color': '#5A7A60', 'marginBottom': '15px'}),
                    
                    html.Div([
                        html.Div([
                            html.Li([
                                html.Div([
                                    html.I(className="fas fa-file-csv" if file_info.get('filename', '').endswith('.csv') 
                                           else "fas fa-file-image" if file_info.get('filename', '').endswith(('.png', '.jpg', '.svg'))
                                           else "fas fa-file", 
                                           style={'marginRight': '10px', 'color': '#5A7A60'}),
                                    html.Span(file_info.get('filename', 'Unknown'), style={'fontWeight': '500'}),
                                    html.Small(f" ({file_info.get('size_bytes', 0) / 1024:.1f} KB)", 
                                             style={'color': '#666', 'marginLeft': '8px'})
                                ], style={'display': 'flex', 'alignItems': 'center', 'justifyContent': 'space-between'}),
                                
                                html.Div([
                                    html.A(
                                        [html.I(className="fas fa-download", style={'marginRight': '6px'}), "Download"],
                                        href=download_urls.get(file_info.get('filename', ''), '#'),
                                        className="btn btn-outline-primary btn-sm",
                                        target="_blank" if download_urls.get(file_info.get('filename', '')) else "",
                                        style={'fontSize': '0.8rem', 'padding': '4px 12px'}
                                    ) if file_info.get('filename') in download_urls else html.Span("Processing...", style={'color': '#666'})
                                ])
                            ], style={'display': 'flex', 'justifyContent': 'space-between', 'alignItems': 'center', 
                                     'padding': '10px', 'border': '1px solid #e0e0e0', 'borderRadius': '5px', 'marginBottom': '8px'})
                            for file_info in result_files
                        ] if result_files else [
                            html.Div([
                                html.I(className="fas fa-info-circle", style={'marginRight': '8px'}),
                                "Results are being processed. Please check back in a few moments."
                            ], style={'color': '#666', 'fontStyle': 'italic', 'textAlign': 'center', 'padding': '20px'})
                        ])
                    ], style={'marginBottom': '30px'}),
                ], className="panel", style={'marginBottom': '20px'}),
                
                # Quick actions
                html.Div([
                    html.H4("Analysis Tools", style={'color': '#5A7A60', 'marginBottom': '15px'}),
                    
                    html.P("Explore your results with these interactive tools:", style={'marginBottom': '15px'}),
                    
                    html.Ul([
                        html.Li("Interactive gRINN Dashboard - Visualize residue interaction networks"),
                        html.Li("Download CSV files - Raw data for further analysis"),
                        html.Li("View plots and graphs - Network visualizations and statistics")
                    ], style={'marginBottom': '20px'}),
                    
                    # Action buttons
                    html.Div([
                        html.A(
                            [html.I(className="fas fa-chart-network", style={'marginRight': '8px'}), "Open Dashboard"],
                            href=f"/dashboard/{job_id}",
                            className="btn btn-primary btn-lg",
                            target="_blank",
                            style={'marginRight': '15px', 'padding': '12px 24px'}
                        ),
                        html.Button(
                            [html.I(className="fas fa-download", style={'marginRight': '8px'}), "Download All"],
                            id={"type": "download-results", "job_id": job_id},
                            className="btn btn-success btn-lg",
                            style={'padding': '12px 24px'},
                            disabled=not download_urls
                        )
                    ], style={'textAlign': 'center'})
                ], className="panel")
            ])
        ])
        
    except Exception as e:
        logger.error(f"Error loading results for job {job_id}: {e}")
        return html.Div([
            html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
            f"Error loading results: {str(e)}"
        ], className="alert alert-danger")

# Download results callback
@app.callback(
    Output({'type': 'download-results', 'job_id': dash.dependencies.MATCH}, 'children'),
    [Input({'type': 'download-results', 'job_id': dash.dependencies.MATCH}, 'n_clicks')],
    [State({'type': 'download-results', 'job_id': dash.dependencies.MATCH}, 'id')],
    prevent_initial_call=True
)
def handle_download_results(n_clicks, button_id):
    """Handle download results button click."""
    if not n_clicks:
        return no_update
    
    job_id = button_id['job_id']
    
    try:
        # Fetch download URLs from backend
        backend_url = f"http://{config.backend_host}:{config.backend_port}/api/jobs/{job_id}/results"
        response = requests.get(backend_url, timeout=10)
        
        if response.status_code == 200:
            results_data = response.json()
            download_urls = results_data.get('download_urls', {})
            
            if download_urls:
                # For now, show a success message. In a real implementation,
                # you might want to open multiple download windows or create a zip file
                return [
                    html.I(className="fas fa-check", style={'marginRight': '8px'}),
                    f"Download links generated ({len(download_urls)} files)"
                ]
            else:
                return [
                    html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                    "No downloadable files found"
                ]
        else:
            return [
                html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                "Failed to generate download links"
            ]
            
    except Exception as e:
        logger.error(f"Error handling download for job {job_id}: {e}")
        return [
            html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
            "Download error"
        ]

# Job queue callback
# Old callback removed - replaced by update_job_queue callback that outputs to 'queue-jobs-table'

# create_public_job_card function removed - replaced by table-based display in update_job_queue callback

# Job cancellation callback
@app.callback(
    Output({'type': 'cancel-job', 'job_id': dash.dependencies.MATCH}, 'disabled'),
    [Input({'type': 'cancel-job', 'job_id': dash.dependencies.MATCH}, 'n_clicks')],
    [State({'type': 'cancel-job', 'job_id': dash.dependencies.MATCH}, 'id')],
    prevent_initial_call=True
)
def handle_cancel_job(n_clicks, button_id):
    """Handle job cancellation."""
    if not n_clicks:
        return no_update
    
    job_id = button_id['job_id']
    
    try:
        # Send cancellation request to backend
        backend_url = f"http://{config.backend_host}:{config.backend_port}/api/jobs/{job_id}/cancel"
        response = requests.post(backend_url, timeout=10)
        
        if response.status_code == 200:
            logger.info(f"Job {job_id} cancellation requested")
            return True  # Disable the button
        else:
            logger.error(f"Failed to cancel job {job_id}: {response.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"Error cancelling job {job_id}: {e}")
        return False

# Job queue page callbacks
@app.callback(
    Output('queue-jobs-table', 'children'),
    [Input('queue-refresh-interval', 'n_intervals'),
     Input('queue-refresh-btn', 'n_clicks'),
     Input('queue-status-filter', 'value')],
    prevent_initial_call=False
)
def update_job_queue(n_intervals, refresh_clicks, status_filter):
    """Update the job queue table."""
    try:
        # Fetch jobs from backend
        backend_url = f"http://{config.backend_host}:{config.backend_port}/api/jobs"
        params = {}
        if status_filter and status_filter != 'all':
            params['status'] = status_filter
        
        response = requests.get(backend_url, params=params, timeout=10)
        
        if response.status_code != 200:
            return html.Div([
                html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                f"Failed to fetch jobs: {response.status_code}"
            ], className="alert alert-danger")
        
        data = response.json()
        jobs = data.get('jobs', [])
        
        if not jobs:
            return html.Div([
                html.I(className="fas fa-info-circle", style={'marginRight': '8px'}),
                "No jobs found in the queue."
            ], className="alert alert-info", style={'textAlign': 'center'})
        
        # Create jobs table
        table_header = html.Thead([
            html.Tr([
                html.Th("Job ID", style={'width': '15%'}),
                html.Th("Name", style={'width': '25%'}),
                html.Th("Status", style={'width': '15%'}),
                html.Th("Created", style={'width': '20%'}),
                html.Th("Progress", style={'width': '15%'}),
                html.Th("Actions", style={'width': '10%'})
            ])
        ])
        
        table_rows = []
        for job_data in jobs:
            job_id = job_data['job_id']
            job_name = job_data.get('job_name', f"Job {job_id[:8]}")
            status = job_data['status']
            created_at = job_data.get('created_at', '')
            progress = job_data.get('progress_percentage', 0)
            is_private = job_data.get('is_private', False)
            
            # Format created time
            created_display = "Unknown"
            if created_at:
                try:
                    created_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    created_display = created_dt.strftime("%m/%d %H:%M")
                except:
                    created_display = created_at[:16] if len(created_at) > 16 else created_at
            
            # Status badge
            status_class = f"status-{status}"
            status_icon = {
                'pending': 'fas fa-clock',
                'queued': 'fas fa-hourglass-half',
                'running': 'fas fa-cog fa-spin',
                'completed': 'fas fa-check-circle',
                'failed': 'fas fa-times-circle',
                'cancelled': 'fas fa-ban'
            }.get(status, 'fas fa-question-circle')
            
            status_badge = html.Span([
                html.I(className=status_icon, style={'marginRight': '5px'}),
                status.title()
            ], className=f"badge job-status {status_class}")
            
            # Progress bar
            progress_bar = html.Div([
                html.Div(
                    style={
                        'width': f'{progress}%',
                        'height': '4px',
                        'backgroundColor': '#5A7A60' if status == 'completed' else '#17a2b8',
                        'transition': 'width 0.3s ease',
                        'borderRadius': '2px'
                    }
                )
            ], style={
                'backgroundColor': '#e9ecef',
                'borderRadius': '2px',
                'width': '100%'
            })
            
            # Actions
            actions = html.Div([
                html.A(
                    html.I(className="fas fa-eye", title="Monitor"),
                    href=f"/monitor/{job_id}",
                    target="_blank",
                    className="btn btn-sm btn-outline-primary",
                    style={'marginRight': '5px'}
                )
            ])
            
            # Privacy indicator
            name_display = job_name
            if is_private:
                name_display = html.Span([
                    html.I(className="fas fa-lock", style={'marginRight': '5px', 'color': '#6c757d'}),
                    job_name
                ])
            
            table_rows.append(html.Tr([
                html.Td(job_id[:8] + "...", style={'font-family': 'monospace'}),
                html.Td(name_display),
                html.Td(status_badge),
                html.Td(created_display, style={'fontSize': '0.9rem'}),
                html.Td(progress_bar),
                html.Td(actions)
            ]))
        
        table_body = html.Tbody(table_rows)
        
        return html.Div([
            html.Table([table_header, table_body], 
                      className="table table-striped table-hover",
                      style={'marginBottom': '0'}),
            html.Div([
                html.Small([
                    html.I(className="fas fa-info-circle", style={'marginRight': '5px'}),
                    f"Showing {len(jobs)} jobs • Updates every 10 seconds • ",
                    html.I(className="fas fa-lock", style={'marginRight': '3px'}),
                    " indicates private jobs"
                ], style={'color': '#6c757d'})
            ], style={'textAlign': 'center', 'marginTop': '10px', 'padding': '10px'})
        ], className="panel")
        
    except Exception as e:
        logger.error(f"Error updating job queue: {e}")
        return html.Div([
            html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
            f"Error loading job queue: {str(e)}"
        ], className="alert alert-danger")

if __name__ == '__main__':
    try:
        # Skip GCS validation for frontend in development mode
        config.validate(skip_gcs_validation=True)
        logger.info("Starting gRINN Web Service Frontend")
        app.run(
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