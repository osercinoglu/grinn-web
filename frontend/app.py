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
from dash import Dash, dcc, html, dash_table, Input, Output, State, callback_context, no_update, ALL
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
                padding: 6px 12px;
                border-radius: 5px;
                font-weight: 500;
                font-size: 0.9rem;
                border: 1px solid;
                display: inline-block;
                cursor: default;
                user-select: none;
            }
            
            .status-pending { 
                background-color: rgba(253, 203, 110, 0.1);
                color: #d68910;
                border-color: rgba(253, 203, 110, 0.3);
            }
            .status-queued { 
                background-color: rgba(9, 132, 227, 0.1);
                color: #0984e3;
                border-color: rgba(9, 132, 227, 0.3);
            }
            .status-uploading { 
                background-color: rgba(232, 67, 147, 0.1);
                color: #d63384;
                border-color: rgba(232, 67, 147, 0.3);
            }
            .status-running { 
                background-color: rgba(45, 116, 218, 0.1);
                color: #2d74da;
                border-color: rgba(45, 116, 218, 0.3);
            }
            .status-completed { 
                background-color: rgba(0, 168, 133, 0.1);
                color: #00a085;
                border-color: rgba(0, 168, 133, 0.3);
            }
            .status-failed { 
                background-color: rgba(214, 48, 49, 0.1);
                color: #d63031;
                border-color: rgba(214, 48, 49, 0.3);
            }
            .status-cancelled { 
                background-color: rgba(108, 117, 125, 0.1);
                color: #6c757d;
                border-color: rgba(108, 117, 125, 0.3);
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
            
            .file-table-row:hover {
                background-color: #f8f9fa !important;
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
        
        # Navigation bar - horizontal layout (row)
        html.Div([
            html.Div([
                html.A(
                    [html.I(className="fas fa-home", style={'marginRight': '6px'}), "Submit Job"],
                    href="/",
                    className="nav-link",
                    style={
                        'display': 'inline-block',
                        'padding': '8px 16px',
                        'backgroundColor': 'rgba(90, 122, 96, 0.1)',
                        'color': '#5A7A60',
                        'textDecoration': 'none',
                        'borderRadius': '5px',
                        'marginRight': '10px',
                        'fontSize': '0.9rem',
                        'fontWeight': '500',
                        'textAlign': 'center'
                    }
                ),
                html.A(
                    [html.I(className="fas fa-list-ul", style={'marginRight': '6px'}), "View Job Queue"],
                    href="/queue",
                    target="_blank",
                    className="nav-link",
                    style={
                        'display': 'inline-block',
                        'padding': '8px 16px',
                        'backgroundColor': 'rgba(23, 162, 184, 0.1)',
                        'color': '#17a2b8',
                        'textDecoration': 'none',
                        'borderRadius': '5px',
                        'fontSize': '0.9rem',
                        'fontWeight': '500',
                        'border': '1px solid rgba(23, 162, 184, 0.3)',
                        'textAlign': 'center'
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
                                style={'fontSize': '0.9rem', 'fontWeight': '500', 'color': '#5A7A60'}),
                        html.Div("Tip: For force field folders, upload all files individually or as a ZIP", 
                                style={'fontSize': '0.75rem', 'color': '#8A9A8A', 'marginTop': '4px', 'fontStyle': 'italic'})
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
                                    "Keep job details private"
                                ], style={'fontSize': '0.9rem'}),
                                'value': 'private'
                            }],
                            value=[],
                            className="form-check"
                        ),
                        html.Div([
                            html.I(className="fas fa-exclamation-triangle", style={'marginRight': '5px', 'color': '#FFA500', 'fontSize': '0.8rem'}),
                            html.Small("Private jobs will NOT appear in the public job queue. Bookmark the monitoring page to access results later!", 
                                      style={'color': '#8A9A8A', 'fontSize': '0.8rem'})
                        ], style={'marginTop': '5px', 'display': 'flex', 'alignItems': 'flex-start'})
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
        dcc.Store(id='monitor-dashboard-url-store'),  # Store for dashboard URL to open in new tab
        dcc.Interval(id='monitor-refresh-interval', interval=3000, n_intervals=0),  # Refresh every 3 seconds
        
        # Header with navigation
        create_header(),
        
        # Bookmark reminder
        html.Div([
            html.I(className="fas fa-bookmark", style={'marginRight': '10px', 'fontSize': '0.9rem'}),
            html.Strong("Bookmark this page! "),
            "Save this URL to check your job status anytime: ",
            html.Code(current_url, style={'backgroundColor': 'rgba(255,255,255,0.3)', 'padding': '2px 6px', 'borderRadius': '4px', 'fontSize': '0.9rem'})
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
                    style={
                        'marginRight': '10px',
                        'fontSize': '0.9rem',
                        'padding': '8px 16px',
                        'display': 'inline-block',
                        'backgroundColor': 'rgba(108, 117, 125, 0.1)',
                        'color': '#6c757d',
                        'textDecoration': 'none',
                        'border': '1px solid rgba(108, 117, 125, 0.3)',
                        'borderRadius': '5px',
                        'fontWeight': '500'
                    }
                ),
                html.Button(
                    [html.I(className="fas fa-sync", style={'marginRight': '8px'}), "Refresh Now"],
                    id="manual-refresh-btn",
                    style={
                        'fontSize': '0.9rem',
                        'padding': '8px 16px',
                        'backgroundColor': 'rgba(90, 122, 96, 0.1)',
                        'color': '#5A7A60',
                        'border': '1px solid rgba(90, 122, 96, 0.3)',
                        'borderRadius': '5px',
                        'fontWeight': '500',
                        'cursor': 'pointer'
                    }
                )
            ], style={'textAlign': 'center', 'marginTop': '20px'}),
            
            # Dashboard modal (same as queue page)
            html.Div([
                html.Div([
                    html.Div([
                        html.Div([
                            html.H5("Dashboard Ready", className="modal-title"),
                            html.Button("×", id='close-monitor-dashboard-modal', className="close", 
                                      style={'fontSize': '1.5rem', 'border': 'none', 'background': 'none'})
                        ], className="modal-header"),
                        html.Div([
                            html.P(id='monitor-dashboard-modal-message', children="Dashboard is starting..."),
                            html.Div([
                                html.A("Open Dashboard", 
                                      id='monitor-dashboard-link',
                                      href="",
                                      target="_blank",
                                      className="btn btn-success",
                                      style={'display': 'none'})
                            ], style={'textAlign': 'center', 'marginTop': '20px'})
                        ], className="modal-body"),
                        html.Div([
                            html.Button("Close", id='close-monitor-dashboard-modal-btn', className="btn btn-secondary")
                        ], className="modal-footer")
                    ], className="modal-content")
                ], className="modal-dialog")
            ], id='monitor-dashboard-modal', className="modal", style={'display': 'none'})
        ], style={'maxWidth': '1000px', 'margin': '0 auto', 'padding': '20px'})
    ])

def create_job_queue_page():
    """Create job queue page showing all submitted jobs."""
    return html.Div([
        dcc.Location(id='queue-url', refresh=False),
        dcc.Store(id='dashboard-url-store'),  # Store for dashboard URL to open in new tab
        
        # Header with navigation
        create_header(),
        
        # Queue controls
        html.Div([
            # Filter controls with flexbox layout
            html.Div([
                # Search box
                html.Div([
                    html.Label("Search by Job ID:", style={'marginBottom': '5px', 'fontWeight': 'bold', 'fontSize': '0.9rem', 'display': 'block'}),
                    dcc.Input(
                        id='queue-search-input',
                        type='text',
                        placeholder='e.g., 6-sad-squid-snuggle-softly',
                        style={'width': '100%', 'padding': '8px', 'borderRadius': '4px', 'border': '1px solid #ccc', 'fontSize': '0.9rem'}
                    )
                ], style={'minWidth': '280px', 'flex': '0 0 auto'}),
                
                html.Div([
                    html.Label("Status Filter:", style={'marginBottom': '5px', 'fontWeight': 'bold', 'fontSize': '0.9rem', 'display': 'block'}),
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
                        style={'fontSize': '0.9rem'}
                    )
                ], style={'minWidth': '200px', 'flex': '0 0 auto'}),
                
                html.Div([
                    html.Button(
                        [html.I(className="fas fa-sync", style={'marginRight': '8px'}), "Refresh Queue"],
                        id="queue-refresh-btn",
                        style={
                            'fontSize': '0.9rem',
                            'padding': '8px 16px',
                            'backgroundColor': 'rgba(90, 122, 96, 0.1)',
                            'color': '#5A7A60',
                            'border': '1px solid rgba(90, 122, 96, 0.3)',
                            'borderRadius': '5px',
                            'fontWeight': '500',
                            'cursor': 'pointer',
                            'marginTop': '24px',
                            'whiteSpace': 'nowrap'
                        }
                    )
                ], style={'flex': '0 0 auto'})
            ], style={
                'display': 'flex',
                'alignItems': 'flex-start',
                'gap': '20px',
                'marginBottom': '20px',
                'flexWrap': 'wrap'
            }),
            
            # Jobs table
            html.Div(id="queue-jobs-table"),
            
            # Auto-refresh interval
            dcc.Interval(id='queue-refresh-interval', interval=10000, n_intervals=0),  # Refresh every 10 seconds
            
            # Dashboard modal
            html.Div([
                html.Div([
                    html.Div([
                        html.Div([
                            html.H5("Dashboard Ready", className="modal-title"),
                            html.Button("×", id='close-dashboard-modal', className="close", 
                                      style={'fontSize': '1.5rem', 'border': 'none', 'background': 'none'})
                        ], className="modal-header"),
                        html.Div([
                            html.P(id='dashboard-modal-message', children="Dashboard is starting..."),
                            html.Div([
                                html.A("Open Dashboard", 
                                      id='dashboard-link',
                                      href="",
                                      target="_blank",
                                      className="btn btn-success",
                                      style={'display': 'none'})
                            ], style={'textAlign': 'center', 'marginTop': '20px'})
                        ], className="modal-body"),
                        html.Div([
                            html.Button("Close", id='close-dashboard-modal-btn', className="btn btn-secondary")
                        ], className="modal-footer")
                    ], className="modal-content")
                ], className="modal-dialog")
            ], id='dashboard-modal', className="modal", style={'display': 'none'}),
            
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

def create_dashboard_page(job_id: str):
    """Create dashboard viewing page - shows only the dashboard iframe."""
    return html.Div([
        dcc.Location(id='dashboard-url', refresh=False),
        dcc.Store(id='dashboard-job-id', data=job_id),
        dcc.Interval(id='dashboard-readiness-interval', interval=2000, n_intervals=0),  # Check every 2 seconds
        
        # Dashboard content (full screen, no header)
        html.Div(id="dashboard-status-content", style={
            'width': '100vw',
            'height': '100vh',
            'margin': '0',
            'padding': '0',
            'position': 'fixed',
            'top': '0',
            'left': '0',
            'overflow': 'hidden'
        })
    ], style={'margin': '0', 'padding': '0'})

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
        # Dashboard viewing page with readiness check
        job_id = pathname.split('/')[-1]
        return create_dashboard_page(job_id)
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
                    "Restraint files (.itp), topology includes (.top), parameter files (.prm), or force field folders"
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
                    f"Unsupported file type: {filename}. Supported formats: PDB, XTC, TRR, TPR, GRO, TOP, ITP, RTP, PRM, ZIP."
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
    
    # Create file list display with table layout
    def get_file_purpose(file_type):
        """Return the purpose/usage of each file type in gRINN workflow."""
        purpose_map = {
            'pdb': 'Structure file - Input protein structure',
            'gro': 'Structure file - GROMACS coordinate file',
            'xtc': 'Trajectory file - Compressed trajectory data',
            'trr': 'Trajectory file - Full-precision trajectory',
            'tpr': 'Topology file - Processed GROMACS topology',
            'top': 'Topology file - Molecular topology definition',
            'itp': 'Include topology - Force field parameters',
            'rtp': 'Residue topology - Residue definitions',
            'prm': 'Parameters - Force field parameters',
            'zip': 'Force field archive - Custom force field files'
        }
        return purpose_map.get(file_type, 'Unknown file type')
    
    # Create table header
    table_header = html.Div([
        html.Div('Filename', style={'flex': '2', 'fontWeight': '500', 'fontSize': '0.85rem', 'color': '#495057'}),
        html.Div('Type', style={'flex': '0.6', 'fontWeight': '500', 'fontSize': '0.85rem', 'color': '#495057'}),
        html.Div('Purpose in gRINN', style={'flex': '2.5', 'fontWeight': '500', 'fontSize': '0.85rem', 'color': '#495057'}),
        html.Div('Size', style={'flex': '0.6', 'fontWeight': '500', 'fontSize': '0.85rem', 'color': '#495057', 'textAlign': 'right'}),
        html.Div('', style={'flex': '0.4', 'fontWeight': '500', 'fontSize': '0.85rem'}),
    ], style={
        'display': 'flex',
        'alignItems': 'center',
        'padding': '10px 12px',
        'backgroundColor': '#f8f9fa',
        'borderBottom': '2px solid #dee2e6',
        'borderRadius': '5px 5px 0 0'
    })
    
    # Create table rows
    file_list_items = [table_header]
    for file_data in files:
        size_mb = file_data['size_bytes'] / (1024 * 1024)
        file_type = file_data['file_type']
        purpose = get_file_purpose(file_type)
        
        file_list_items.append(
            html.Div([
                html.Div(
                    file_data['filename'],
                    style={'flex': '2', 'fontSize': '0.85rem', 'color': '#212529', 'overflow': 'hidden', 'textOverflow': 'ellipsis', 'whiteSpace': 'nowrap'},
                    title=file_data['filename']
                ),
                html.Div(
                    f".{file_type.upper()}",
                    style={'flex': '0.6', 'fontSize': '0.8rem', 'color': '#6c757d', 'fontWeight': '500'}
                ),
                html.Div(
                    purpose,
                    style={'flex': '2.5', 'fontSize': '0.8rem', 'color': '#6c757d', 'fontStyle': 'italic'}
                ),
                html.Div(
                    f"{size_mb:.1f} MB",
                    style={'flex': '0.6', 'fontSize': '0.8rem', 'color': '#6c757d', 'textAlign': 'right'}
                ),
                html.Div([
                    html.Button(
                        html.I(className="fas fa-trash"),
                        id={'type': 'remove-file', 'index': files.index(file_data)},
                        style={
                            'fontSize': '0.75rem',
                            'padding': '4px 8px',
                            'backgroundColor': 'rgba(220, 53, 69, 0.1)',
                            'color': '#dc3545',
                            'border': '1px solid rgba(220, 53, 69, 0.3)',
                            'borderRadius': '3px',
                            'cursor': 'pointer',
                            'fontWeight': '500'
                        },
                        title=f"Remove {file_data['filename']}"
                    )
                ], style={'flex': '0.4', 'display': 'flex', 'justifyContent': 'center'})
            ], style={
                'display': 'flex',
                'alignItems': 'center',
                'padding': '8px 12px',
                'borderBottom': '1px solid #e9ecef',
                'backgroundColor': '#ffffff',
                'transition': 'background-color 0.2s',
            }, className='file-table-row')
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
    
    # Wrap file list in a container with border
    file_list_container = html.Div(
        file_list_items,
        style={
            'border': '1px solid #dee2e6',
            'borderRadius': '5px',
            'backgroundColor': '#ffffff',
            'overflow': 'hidden',
            'marginBottom': '15px'
        }
    )
    
    return file_list_container, style, validation_messages, files, submit_disabled, submit_message, submit_style

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
    
    # Create file list display with table layout (same logic as in handle_file_upload)
    def get_file_purpose(file_type):
        """Return the purpose/usage of each file type in gRINN workflow."""
        purpose_map = {
            'pdb': 'Structure file - Input protein structure',
            'gro': 'Structure file - GROMACS coordinate file',
            'xtc': 'Trajectory file - Compressed trajectory data',
            'trr': 'Trajectory file - Full-precision trajectory',
            'tpr': 'Topology file - Processed GROMACS topology',
            'top': 'Topology file - Molecular topology definition',
            'itp': 'Include topology - Force field parameters',
            'rtp': 'Residue topology - Residue definitions',
            'prm': 'Parameters - Force field parameters',
            'zip': 'Force field archive - Custom force field files'
        }
        return purpose_map.get(file_type, 'Unknown file type')
    
    # Create table header
    table_header = html.Div([
        html.Div('Filename', style={'flex': '2', 'fontWeight': '500', 'fontSize': '0.85rem', 'color': '#495057'}),
        html.Div('Type', style={'flex': '0.6', 'fontWeight': '500', 'fontSize': '0.85rem', 'color': '#495057'}),
        html.Div('Purpose in gRINN', style={'flex': '2.5', 'fontWeight': '500', 'fontSize': '0.85rem', 'color': '#495057'}),
        html.Div('Size', style={'flex': '0.6', 'fontWeight': '500', 'fontSize': '0.85rem', 'color': '#495057', 'textAlign': 'right'}),
        html.Div('', style={'flex': '0.4', 'fontWeight': '500', 'fontSize': '0.85rem'}),
    ], style={
        'display': 'flex',
        'alignItems': 'center',
        'padding': '10px 12px',
        'backgroundColor': '#f8f9fa',
        'borderBottom': '2px solid #dee2e6',
        'borderRadius': '5px 5px 0 0'
    })
    
    # Create table rows
    file_list_items = [table_header]
    for file_data in files:
        size_mb = file_data['size_bytes'] / (1024 * 1024)
        file_type = file_data['file_type']
        purpose = get_file_purpose(file_type)
        
        file_list_items.append(
            html.Div([
                html.Div(
                    file_data['filename'],
                    style={'flex': '2', 'fontSize': '0.85rem', 'color': '#212529', 'overflow': 'hidden', 'textOverflow': 'ellipsis', 'whiteSpace': 'nowrap'},
                    title=file_data['filename']
                ),
                html.Div(
                    f".{file_type.upper()}",
                    style={'flex': '0.6', 'fontSize': '0.8rem', 'color': '#6c757d', 'fontWeight': '500'}
                ),
                html.Div(
                    purpose,
                    style={'flex': '2.5', 'fontSize': '0.8rem', 'color': '#6c757d', 'fontStyle': 'italic'}
                ),
                html.Div(
                    f"{size_mb:.1f} MB",
                    style={'flex': '0.6', 'fontSize': '0.8rem', 'color': '#6c757d', 'textAlign': 'right'}
                ),
                html.Div([
                    html.Button(
                        html.I(className="fas fa-trash"),
                        id={'type': 'remove-file', 'index': files.index(file_data)},
                        style={
                            'fontSize': '0.75rem',
                            'padding': '4px 8px',
                            'backgroundColor': 'rgba(220, 53, 69, 0.1)',
                            'color': '#dc3545',
                            'border': '1px solid rgba(220, 53, 69, 0.3)',
                            'borderRadius': '3px',
                            'cursor': 'pointer',
                            'fontWeight': '500'
                        },
                        title=f"Remove {file_data['filename']}"
                    )
                ], style={'flex': '0.4', 'display': 'flex', 'justifyContent': 'center'})
            ], style={
                'display': 'flex',
                'alignItems': 'center',
                'padding': '8px 12px',
                'borderBottom': '1px solid #e9ecef',
                'backgroundColor': '#ffffff',
                'transition': 'background-color 0.2s',
            }, className='file-table-row')
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
    
    # Wrap file list in a container with border
    file_list_container = html.Div(
        file_list_items,
        style={
            'border': '1px solid #dee2e6',
            'borderRadius': '5px',
            'backgroundColor': '#ffffff',
            'overflow': 'hidden',
            'marginBottom': '15px'
        }
    )
    
    return file_list_container, {'display': 'block'}, validation_messages, submit_disabled, status_message, status_style

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
        # Job name is optional - will be None if not provided
        job_name = None
        
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
        
        # Show compact success message with clickable link
        monitor_url = f"/monitor/{job_id}"
        
        # Add extra warning for private jobs
        if is_private:
            success_message = html.Div([
                html.Div([
                    html.I(className="fas fa-check-circle", style={'color': 'green', 'marginRight': '8px'}),
                    html.Span("Job submitted! ", style={'fontWeight': 'bold'}),
                    html.Span(f"ID: {job_id} | ", style={'marginRight': '5px'}),
                    html.A("Monitor →", href=monitor_url, target="_blank", 
                           style={'fontWeight': 'bold', 'textDecoration': 'underline'})
                ]),
                html.Div([
                    html.I(className="fas fa-bookmark", style={'color': '#FFA500', 'marginRight': '5px', 'fontSize': '0.85rem'}),
                    html.Small("Private job - bookmark the monitoring page!", style={'fontSize': '0.85rem'})
                ], style={'marginTop': '5px'})
            ], className="alert alert-success", style={'padding': '10px 15px'})
        else:
            success_message = html.Div([
                html.I(className="fas fa-check-circle", style={'color': 'green', 'marginRight': '8px'}),
                html.Span("Job submitted! ", style={'fontWeight': 'bold'}),
                html.Span(f"ID: {job_id} | ", style={'marginRight': '5px'}),
                html.A("Monitor →", href=monitor_url, target="_blank", 
                       style={'fontWeight': 'bold', 'textDecoration': 'underline'})
            ], className="alert alert-success", style={'padding': '10px 15px'})
        
        # Clear uploaded files after successful submission
        return success_message, []
        
    except Exception as e:
        logger.error(f"Error submitting job: {e}")
        return html.Div([
            html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
            f"Error submitting job: {str(e)}"
        ], className="alert alert-danger"), no_update

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
            html.H3("Job Details", style={'color': '#5A7A60', 'marginBottom': '15px', 'fontSize': '0.9rem'}),
            
            html.Div([
                # Job info cards
                html.Div([
                    html.Div([
                        html.H5(job.job_name or job.job_id, style={'margin': '0', 'fontSize': '0.9rem'}),
                        html.P(job.description or "No description", style={'margin': '5px 0', 'color': '#666', 'fontSize': '0.9rem'}),
                        html.Small(f"Created: {job.created_at.strftime('%Y-%m-%d %H:%M:%S')}", style={'color': '#8A9A8A', 'fontSize': '0.85rem'})
                    ], className="panel", style={'flex': '1', 'marginRight': '10px'}),
                    
                    html.Div([
                        html.Div([
                            html.H5("Status", style={'margin': '0 0 10px 0', 'fontSize': '0.9rem'}),
                            html.Div([
                                html.Span(job.status.value.title() if isinstance(job.status, JobStatus) else job.status.title(), 
                                        className=f"job-status status-{job.status.value if isinstance(job.status, JobStatus) else job.status}",
                                        style={'marginRight': '10px' if (isinstance(job.status, JobStatus) and job.status == JobStatus.COMPLETED) or (isinstance(job.status, str) and job.status.lower() == 'completed') else '0'}),
                                # Show Launch Dashboard button only if job is completed
                                html.Button(
                                    [html.I(className="fas fa-chart-line", style={'marginRight': '8px'}), "Launch Dashboard"],
                                    id="monitor-launch-dashboard-btn",
                                    style={
                                        'fontSize': '0.9rem',
                                        'padding': '6px 12px',
                                        'verticalAlign': 'middle',
                                        'backgroundColor': 'rgba(40, 167, 69, 0.1)',
                                        'color': '#28a745',
                                        'border': '1px solid rgba(40, 167, 69, 0.3)',
                                        'borderRadius': '5px',
                                        'fontWeight': '500',
                                        'cursor': 'pointer'
                                    }
                                ) if (isinstance(job.status, JobStatus) and job.status == JobStatus.COMPLETED) or (isinstance(job.status, str) and job.status.lower() == 'completed') else html.Span()
                            ], style={'display': 'flex', 'alignItems': 'center'}),
                            html.P(job.current_step or "No current step", 
                                  style={'margin': '10px 0 0 0', 'color': '#5A7A60', 'fontSize': '0.9rem'})
                        ])
                    ], className="panel", style={'flex': '1', 'marginLeft': '10px'})
                ], style={'display': 'flex', 'marginBottom': '20px'}),
                
                # Progress section
                html.Div([
                    html.H5("Progress", style={'marginBottom': '10px', 'fontSize': '0.9rem'}),
                    
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
                    html.H5("Input Files", style={'marginBottom': '10px', 'fontSize': '0.9rem'}),
                    html.Ul([
                        html.Li([
                            html.I(className="fas fa-file", style={'marginRight': '8px', 'color': '#5A7A60'}),
                            f"{file_info.filename} ({file_info.file_type.value.upper()}, {file_info.size_bytes/1024/1024:.1f} MB)"
                        ], style={'fontSize': '0.9rem'}) for file_info in job.input_files
                    ] if job.input_files else [html.Li("No files information available", style={'fontSize': '0.9rem'})])
                ], className="panel", style={'marginTop': '20px'})
            ])
        ])
        
        # Create log section - fetch real container logs
        job_logs_content = "No logs available yet."
        log_color = '#666'
        log_bg_color = '#f8f9fa'
        
        try:
            # Fetch logs from backend API
            logs_url = f"http://{config.backend_host}:{config.backend_port}/api/jobs/{job_id}/logs"
            logs_response = requests.get(logs_url, params={'tail': 500}, timeout=5)
            
            if logs_response.status_code == 200:
                logs_data = logs_response.json()
                if logs_data.get('success') and logs_data.get('logs'):
                    job_logs_content = logs_data['logs']
                    # Use terminal-like styling for container logs
                    log_bg_color = '#1e1e1e'
                    log_color = '#d4d4d4'
                elif job.error_message:
                    job_logs_content = job.error_message
                    log_color = '#d32f2f'
        except Exception as log_error:
            logger.warning(f"Could not fetch logs for job {job_id}: {log_error}")
            # Fall back to error message if available
            if job.error_message:
                job_logs_content = job.error_message
                log_color = '#d32f2f'
        
        job_logs = html.Div([
            html.H3("Job Logs", style={'color': '#5A7A60', 'marginBottom': '15px', 'fontSize': '0.9rem'}),
            html.Div([
                html.Pre(
                    job_logs_content,
                    style={
                        'backgroundColor': log_bg_color,
                        'padding': '15px',
                        'borderRadius': '5px',
                        'fontSize': '0.85rem',
                        'fontFamily': 'monospace',
                        'maxHeight': '400px',
                        'overflow': 'auto',
                        'color': log_color,
                        'whiteSpace': 'pre-wrap',
                        'wordWrap': 'break-word'
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
     Input('queue-status-filter', 'value'),
     Input('queue-search-input', 'value')],
    prevent_initial_call=False
)
def update_job_queue(n_intervals, refresh_clicks, status_filter, search_text):
    """Update the job queue table with optional search filter."""
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
        
        # Apply client-side search filter
        if search_text and search_text.strip():
            search_text = search_text.strip().lower()
            jobs = [job for job in jobs if search_text in job.get('job_id', '').lower()]
        
        if not jobs:
            message = f"No jobs found matching '{search_text}'." if search_text else "No jobs found in the queue."
            return html.Div([
                html.I(className="fas fa-info-circle", style={'marginRight': '8px'}),
                message
            ], className="alert alert-info", style={'textAlign': 'center'})
        
        # Create jobs table
        table_header = html.Thead([
            html.Tr([
                html.Th("Job ID", style={'width': '25%', 'fontSize': '0.9rem'}),
                html.Th("Status", style={'width': '15%', 'fontSize': '0.9rem'}),
                html.Th("Created", style={'width': '20%', 'fontSize': '0.9rem'}),
                html.Th("Progress", style={'width': '20%', 'fontSize': '0.9rem'}),
                html.Th("Actions", style={'width': '20%', 'fontSize': '0.9rem'})
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
                    style={
                        'display': 'inline-block',
                        'padding': '6px 12px',
                        'marginRight': '5px',
                        'backgroundColor': 'rgba(0, 123, 255, 0.1)',
                        'color': '#007bff',
                        'textDecoration': 'none',
                        'border': '1px solid rgba(0, 123, 255, 0.3)',
                        'borderRadius': '5px',
                        'fontSize': '0.9rem',
                        'fontWeight': '500'
                    }
                ),
                html.Button(
                    html.I(className="fas fa-chart-line", title="Launch Dashboard"),
                    id={'type': 'launch-dashboard-btn', 'job_id': job_id},
                    disabled=(status not in ['completed']),
                    style={
                        'padding': '6px 12px',
                        'marginRight': '5px',
                        'backgroundColor': 'rgba(40, 167, 69, 0.1)' if status == 'completed' else 'rgba(40, 167, 69, 0.05)',
                        'color': '#28a745' if status == 'completed' else 'rgba(40, 167, 69, 0.5)',
                        'border': '1px solid rgba(40, 167, 69, 0.3)' if status == 'completed' else '1px solid rgba(40, 167, 69, 0.2)',
                        'borderRadius': '5px',
                        'fontSize': '0.9rem',
                        'fontWeight': '500',
                        'cursor': 'pointer' if status == 'completed' else 'not-allowed',
                        'opacity': '1' if status == 'completed' else '0.5'
                    }
                )
            ], style={'display': 'flex', 'gap': '5px'})
            
            # Privacy indicator for job ID display
            job_id_display = job_id
            if is_private:
                job_id_display = html.Span([
                    html.I(className="fas fa-lock", style={'marginRight': '5px', 'color': '#6c757d'}),
                    job_id
                ])
            
            table_rows.append(html.Tr([
                html.Td(job_id_display, style={'font-family': 'monospace', 'fontSize': '0.9rem'}),
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


# ============================================================================
# Dashboard Management Callbacks
# ============================================================================

@app.callback(
    Output('dashboard-url-store', 'data'),
    [Input({'type': 'launch-dashboard-btn', 'job_id': ALL}, 'n_clicks')],
    [State({'type': 'launch-dashboard-btn', 'job_id': ALL}, 'id')],
    prevent_initial_call=True
)
def launch_dashboard(n_clicks_list, button_ids):
    """Handle dashboard launch button clicks - store URL to open in new tab."""
    import requests
    
    # Handle empty lists or no clicks
    if not n_clicks_list or not button_ids or not any(n_clicks_list):
        return no_update
    
    # Find which button was clicked
    clicked_idx = None
    for i, clicks in enumerate(n_clicks_list):
        if clicks and clicks > 0:
            clicked_idx = i
            break
    
    if clicked_idx is None or clicked_idx >= len(button_ids):
        return no_update
    
    job_id = button_ids[clicked_idx]['job_id']
    
    try:
        # Call backend API to start dashboard
        backend_url = f"http://{config.backend_host}:{config.backend_port}/api/jobs/{job_id}/dashboard/start"
        response = requests.post(backend_url, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                # Return URL to be opened in new tab by clientside callback
                return f"/dashboard/{job_id}"
            else:
                logger.error(f"Failed to start dashboard: {data.get('error')}")
                return no_update
        else:
            logger.error(f"Server returned {response.status_code}")
            return no_update
            
    except Exception as e:
        logger.error(f"Error launching dashboard for {job_id}: {e}")
        return no_update


# Clientside callback to open dashboard in new tab
app.clientside_callback(
    """
    function(url) {
        if (url) {
            window.open(url, '_blank');
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output('dashboard-url-store', 'data', allow_duplicate=True),
    Input('dashboard-url-store', 'data'),
    prevent_initial_call=True
)


@app.callback(
    Output('dashboard-modal', 'style', allow_duplicate=True),
    [Input('close-dashboard-modal', 'n_clicks'),
     Input('close-dashboard-modal-btn', 'n_clicks')],
    prevent_initial_call=True
)
def close_dashboard_modal(close_x, close_btn):
    """Close the dashboard modal."""
    return {'display': 'none'}


@app.callback(
    Output('monitor-dashboard-url-store', 'data'),
    [Input('monitor-launch-dashboard-btn', 'n_clicks')],
    [State('monitor-job-id', 'data')],
    prevent_initial_call=True
)
def launch_monitor_dashboard(n_clicks, job_id):
    """Handle dashboard launch from monitor page - store URL to open in new tab."""
    import requests
    
    if not n_clicks:
        return no_update
    
    try:
        # Call backend API to start dashboard
        backend_url = f"http://{config.backend_host}:{config.backend_port}/api/jobs/{job_id}/dashboard/start"
        response = requests.post(backend_url, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                # Return URL to be opened in new tab by clientside callback
                return f"/dashboard/{job_id}"
            else:
                logger.error(f"Failed to start dashboard: {data.get('error')}")
                return no_update
        else:
            logger.error(f"Server returned {response.status_code}")
            return no_update
            
    except Exception as e:
        logger.error(f"Error launching dashboard for {job_id}: {e}")
        return no_update


# Clientside callback to open monitor dashboard in new tab
app.clientside_callback(
    """
    function(url) {
        if (url) {
            window.open(url, '_blank');
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output('monitor-dashboard-url-store', 'data', allow_duplicate=True),
    Input('monitor-dashboard-url-store', 'data'),
    prevent_initial_call=True
)


@app.callback(
    Output('monitor-dashboard-modal', 'style', allow_duplicate=True),
    [Input('close-monitor-dashboard-modal', 'n_clicks'),
     Input('close-monitor-dashboard-modal-btn', 'n_clicks')],
    prevent_initial_call=True
)
def close_monitor_dashboard_modal(close_x, close_btn):
    """Close the monitor dashboard modal."""
    return {'display': 'none'}


# ============================================================================
# Dashboard Viewer Page Callbacks
# ============================================================================

@app.callback(
    Output('dashboard-status-content', 'children'),
    [Input('dashboard-readiness-interval', 'n_intervals')],
    [State('dashboard-job-id', 'data')],
    prevent_initial_call=False
)
def update_dashboard_status(n_intervals, job_id):
    """Update dashboard status and show iframe when ready. Auto-start if not running."""
    import requests
    
    try:
        # Get job details
        job_backend_url = f"http://{config.backend_host}:{config.backend_port}/api/jobs/{job_id}"
        job_response = requests.get(job_backend_url, timeout=10)
        
        if job_response.status_code != 200:
            return html.Div([
                html.Div([
                    html.I(className="fas fa-exclamation-triangle", 
                          style={'fontSize': '3rem', 'color': '#dc3545', 'marginBottom': '20px'}),
                    html.H3(f"Job not found: {job_id}", style={'color': '#5A7A60'})
                ], style={
                    'textAlign': 'center',
                    'paddingTop': '20vh',
                    'display': 'flex',
                    'flexDirection': 'column',
                    'alignItems': 'center'
                })
            ])
        
        job_data = job_response.json()
        job_name = job_data.get('job_name') or f"Job {job_id[:12]}"
        
        # Check dashboard status
        status_url = f"http://{config.backend_host}:{config.backend_port}/api/jobs/{job_id}/dashboard/status"
        status_response = requests.get(status_url, timeout=10)
        
        if status_response.status_code != 200:
            # Dashboard not started - auto-start it
            try:
                start_url = f"http://{config.backend_host}:{config.backend_port}/api/jobs/{job_id}/dashboard/start"
                start_response = requests.post(start_url, timeout=30)
                if start_response.status_code == 200:
                    # Successfully triggered start, show loading screen
                    return html.Div([
                        html.Div([
                            html.I(className="fas fa-spinner fa-spin", 
                                  style={'fontSize': '3rem', 'color': '#7C9885', 'marginBottom': '20px'}),
                            html.H3("Starting Dashboard...", style={'color': '#5A7A60', 'marginBottom': '10px'}),
                            html.P("Please wait while we prepare your data visualization.", 
                                  style={'color': '#666', 'fontSize': '1.1rem'})
                        ], style={
                            'textAlign': 'center',
                            'paddingTop': '20vh',
                            'display': 'flex',
                            'flexDirection': 'column',
                            'alignItems': 'center'
                        })
                    ])
            except Exception as e:
                logger.error(f"Failed to auto-start dashboard: {e}")
            
            # If auto-start failed, show error
            return html.Div([
                html.Div([
                    html.I(className="fas fa-exclamation-circle", 
                          style={'fontSize': '3rem', 'color': '#ffc107', 'marginBottom': '20px'}),
                    html.H3("Dashboard Not Available", style={'color': '#5A7A60', 'marginBottom': '10px'}),
                    html.P(f"Could not start dashboard for job: {job_id}", 
                          style={'color': '#666', 'fontSize': '1rem'})
                ], style={
                    'textAlign': 'center',
                    'paddingTop': '20vh',
                    'display': 'flex',
                    'flexDirection': 'column',
                    'alignItems': 'center'
                })
            ])
        
        status_data = status_response.json()
        
        if not status_data.get('running'):
            # Dashboard not running - try to start it
            try:
                start_url = f"http://{config.backend_host}:{config.backend_port}/api/jobs/{job_id}/dashboard/start"
                start_response = requests.post(start_url, timeout=30)
                if start_response.status_code == 200:
                    return html.Div([
                        html.Div([
                            html.I(className="fas fa-spinner fa-spin", 
                                  style={'fontSize': '3rem', 'color': '#7C9885', 'marginBottom': '20px'}),
                            html.H3("Starting Dashboard...", style={'color': '#5A7A60', 'marginBottom': '10px'}),
                            html.P("Please wait while we prepare your data visualization.", 
                                  style={'color': '#666', 'fontSize': '1.1rem'})
                        ], style={
                            'textAlign': 'center',
                            'paddingTop': '20vh',
                            'display': 'flex',
                            'flexDirection': 'column',
                            'alignItems': 'center'
                        })
                    ])
            except Exception as e:
                logger.error(f"Failed to start dashboard: {e}")
            
            return html.Div([
                html.Div([
                    html.I(className="fas fa-exclamation-circle", 
                          style={'fontSize': '3rem', 'color': '#ffc107', 'marginBottom': '20px'}),
                    html.H3("Dashboard Not Running", style={'color': '#5A7A60'})
                ], style={
                    'textAlign': 'center',
                    'paddingTop': '20vh',
                    'display': 'flex',
                    'flexDirection': 'column',
                    'alignItems': 'center'
                })
            ])
        
        if not status_data.get('ready'):
            # Dashboard starting but not ready yet - show loading with logs
            logs_url = f"http://{config.backend_host}:{config.backend_port}/api/jobs/{job_id}/dashboard/logs"
            try:
                logs_response = requests.get(logs_url, timeout=5)
                if logs_response.status_code == 200:
                    logs_data = logs_response.json()
                    logs_text = logs_data.get('logs', 'Initializing...')
                else:
                    logs_text = 'Preparing data...'
            except:
                logs_text = 'Preparing data...'
            
            return html.Div([
                html.Div([
                    html.I(className="fas fa-spinner fa-spin", 
                          style={'fontSize': '3rem', 'color': '#7C9885', 'marginBottom': '20px'}),
                    html.H3("Preparing Dashboard...", style={'color': '#5A7A60', 'marginBottom': '20px'}),
                    html.Div([
                        html.Pre(
                            logs_text,
                            style={
                                'backgroundColor': '#1e1e1e',
                                'color': '#d4d4d4',
                                'padding': '20px',
                                'borderRadius': '8px',
                                'fontSize': '13px',
                                'fontFamily': 'monospace',
                                'maxHeight': '300px',
                                'maxWidth': '800px',
                                'overflowY': 'auto',
                                'whiteSpace': 'pre-wrap',
                                'wordWrap': 'break-word',
                                'textAlign': 'left'
                            }
                        )
                    ], style={'marginBottom': '20px'}),
                    html.P("This typically takes 5-10 minutes. The page will update automatically.", 
                          style={'color': '#666', 'fontSize': '0.95rem', 'fontStyle': 'italic'})
                ], style={
                    'textAlign': 'center',
                    'paddingTop': '10vh',
                    'display': 'flex',
                    'flexDirection': 'column',
                    'alignItems': 'center',
                    'padding': '20px'
                })
            ])
        
        # Dashboard is ready! Show iframe in full screen
        dashboard_url = status_data.get('url')
        
        return html.Iframe(
            src=dashboard_url,
            style={
                'width': '100%',
                'height': '100%',
                'border': 'none',
                'margin': '0',
                'padding': '0',
                'display': 'block'
            }
        )
        
    except Exception as e:
        logger.error(f"Error updating dashboard status for {job_id}: {e}")
        return html.Div([
            html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
            f"Error loading dashboard: {str(e)}"
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