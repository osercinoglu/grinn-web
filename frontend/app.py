"""
gRINN Web Service Frontend Application
A Dash-based web interface for submitting and monitoring gRINN computational jobs.
"""

import os
import sys
import base64
import json
import logging
import zipfile
from io import BytesIO
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

import dash
from dash import Dash, dcc, html, dash_table, Input, Output, State, callback_context, no_update, ALL
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
import requests
from flask import send_file, abort

# Add shared modules to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'shared'))
from models import Job, JobStatus, JobParameters, FileType, JobSubmissionRequest
from config import get_config, setup_logging

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Initialize config
config = get_config()

# Check if example data is available (mode-specific)
def _check_example_data_available(path: str) -> bool:
    """Check if example data path is configured and contains files."""
    if not path:
        return False
    if not os.path.isdir(path):
        return False
    # Check if folder contains at least one file
    try:
        files = [f for f in os.listdir(path) 
                 if os.path.isfile(os.path.join(path, f))]
        return len(files) > 0
    except Exception:
        return False

def _get_example_files(path: str) -> list:
    """Get list of example files from a path."""
    if not path or not os.path.isdir(path):
        return []
    try:
        return [f for f in os.listdir(path) 
                if os.path.isfile(os.path.join(path, f))]
    except Exception:
        return []

def _validate_example_path(file_path: str) -> bool:
    """
    Validate that a file path is within the configured example data directories.
    Prevents path traversal attacks.
    
    Args:
        file_path: The file path to validate
        
    Returns:
        True if the path is valid and within allowed example data directories
    """
    if not file_path:
        return False
    
    # Normalize the path to resolve any .. or symlinks
    try:
        normalized_path = os.path.realpath(file_path)
    except Exception:
        return False
    
    # Check if file exists
    if not os.path.isfile(normalized_path):
        return False
    
    # Check against allowed example data paths
    allowed_paths = []
    if config.example_data_path_trajectory:
        allowed_paths.append(os.path.realpath(config.example_data_path_trajectory))
    if config.example_data_path_ensemble:
        allowed_paths.append(os.path.realpath(config.example_data_path_ensemble))
    
    # Verify the file is within one of the allowed directories
    for allowed in allowed_paths:
        if normalized_path.startswith(allowed + os.sep) or normalized_path.startswith(allowed):
            return True
    
    return False

EXAMPLE_DATA_TRAJECTORY_AVAILABLE = _check_example_data_available(config.example_data_path_trajectory)
EXAMPLE_DATA_ENSEMBLE_AVAILABLE = _check_example_data_available(config.example_data_path_ensemble)

if EXAMPLE_DATA_TRAJECTORY_AVAILABLE:
    logger.info(f"Trajectory example data available at: {config.example_data_path_trajectory}")
    example_files = _get_example_files(config.example_data_path_trajectory)
    logger.info(f"Trajectory example files: {example_files}")
else:
    logger.info(f"Trajectory example data not configured or folder empty (path: {config.example_data_path_trajectory})")

if EXAMPLE_DATA_ENSEMBLE_AVAILABLE:
    logger.info(f"Ensemble example data available at: {config.example_data_path_ensemble}")
    example_files = _get_example_files(config.example_data_path_ensemble)
    logger.info(f"Ensemble example files: {example_files}")
else:
    logger.info(f"Ensemble example data not configured or folder empty (path: {config.example_data_path_ensemble})")

# Temporary upload directory for server-side file storage
import uuid
import shutil
import secrets
import stat

# World-writable permissions for directories
DIR_PERMISSIONS = stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO  # 0o777

TEMP_UPLOAD_DIR = os.path.join(config.storage_path, 'temp_uploads')
os.makedirs(TEMP_UPLOAD_DIR, mode=0o777, exist_ok=True)
try:
    os.chmod(TEMP_UPLOAD_DIR, 0o777)
except OSError:
    pass

def save_temp_file(content_string: str, filename: str, session_id: str) -> str:
    """Save uploaded file to temporary storage and return the temp file ID."""
    # Create session directory with world-writable permissions
    session_dir = os.path.join(TEMP_UPLOAD_DIR, session_id)
    os.makedirs(session_dir, mode=0o777, exist_ok=True)
    try:
        os.chmod(session_dir, 0o777)
    except OSError:
        pass
    
    # Generate unique file ID
    file_id = f"{uuid.uuid4().hex[:8]}_{filename}"
    file_path = os.path.join(session_dir, file_id)
    
    # Decode and save file
    file_content = base64.b64decode(content_string)
    with open(file_path, 'wb') as f:
        f.write(file_content)
    
    logger.info(f"Saved temp file: {file_path} ({len(file_content)} bytes)")
    return file_id

def get_temp_file_path(file_id: str, session_id: str) -> str:
    """Get the full path to a temporary file."""
    return os.path.join(TEMP_UPLOAD_DIR, session_id, file_id)

def delete_temp_file(file_id: str, session_id: str) -> bool:
    """Delete a temporary file."""
    file_path = get_temp_file_path(file_id, session_id)
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Deleted temp file: {file_path}")
            return True
    except Exception as e:
        logger.error(f"Error deleting temp file {file_path}: {e}")
    return False

def cleanup_session_files(session_id: str):
    """Remove all temporary files for a session."""
    session_dir = os.path.join(TEMP_UPLOAD_DIR, session_id)
    try:
        if os.path.exists(session_dir):
            shutil.rmtree(session_dir)
            logger.info(f"Cleaned up session directory: {session_dir}")
    except Exception as e:
        logger.error(f"Error cleaning up session {session_id}: {e}")

def validate_pdb_multimodel(file_path: str, input_mode: str) -> dict:
    """
    Validate PDB file for multi-model content (ensemble mode).
    
    Args:
        file_path: Path to the PDB file
        input_mode: Current input mode ('ensemble' or 'trajectory')
        
    Returns:
        dict with keys:
        - 'model_count': int (number of MODEL records found)
        - 'is_multimodel': bool
        - 'warning': str or None
        - 'error': str or None
    """
    result = {
        'model_count': 0,
        'is_multimodel': False,
        'warning': None,
        'error': None
    }
    
    try:
        with open(file_path, 'r') as f:
            model_count = 0
            endmdl_count = 0
            has_atom_records = False
            
            for line in f:
                record_type = line[:6].strip()
                if record_type == 'MODEL':
                    model_count += 1
                elif record_type == 'ENDMDL':
                    endmdl_count += 1
                elif record_type in ('ATOM', 'HETATM'):
                    has_atom_records = True
            
            result['model_count'] = model_count
            result['is_multimodel'] = model_count > 1
            
            # Validation checks
            if model_count > 0 and model_count != endmdl_count:
                result['error'] = f"Mismatched MODEL/ENDMDL records ({model_count} MODEL vs {endmdl_count} ENDMDL)"
                return result
            
            if input_mode == 'ensemble':
                if model_count == 0:
                    # Single-model PDB without explicit MODEL records
                    if has_atom_records:
                        result['warning'] = "PDB has no MODEL records - will be treated as single structure. Ensemble analysis requires multiple conformations."
                        result['model_count'] = 1
                    else:
                        result['error'] = "PDB file contains no atom coordinates"
                elif model_count == 1:
                    result['warning'] = "PDB contains only 1 model. Ensemble analysis requires multiple conformations for meaningful results."
                else:
                    # Check against max_frames limit
                    if config.max_frames and model_count > config.max_frames:
                        result['error'] = f"PDB has {model_count} models, which exceeds the limit of {config.max_frames}"
                    
    except Exception as e:
        result['error'] = f"Failed to parse PDB file: {str(e)}"
    
    return result

def get_file_purpose(file_type: str, mode: str = 'trajectory') -> str:
    """
    Return the purpose/usage of each file type in gRINN workflow.
    Purpose descriptions are mode-aware.
    
    Args:
        file_type: File extension (e.g., 'pdb', 'xtc')
        mode: Input mode ('trajectory' or 'ensemble')
    
    Returns:
        Human-readable purpose description
    """
    if mode == 'ensemble':
        # In ensemble mode, only PDB is relevant
        if file_type == 'pdb':
            return 'Ensemble - Multi-model conformational ensemble'
        else:
            return 'Not used in Ensemble mode'
    else:
        # Trajectory mode purposes
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


def get_role_options(file_type: str, mode: str = 'trajectory') -> list:
    """
    Return available role options for a file type.
    
    Args:
        file_type: File extension (e.g., 'pdb', 'xtc')
        mode: Input mode ('trajectory' or 'ensemble')
    
    Returns:
        List of dicts with 'label' and 'value' for dropdown options.
        Empty list means fixed role (no dropdown needed).
    """
    if mode == 'ensemble':
        # In ensemble mode, PDB has fixed role
        return []
    
    # Trajectory mode - define role options per file type
    role_options_map = {
        'top': [
            {'label': 'Topology file (main)', 'value': 'topology'},
            {'label': 'Include file', 'value': 'include'}
        ],
        # Fixed roles - no dropdown
        'pdb': [],  # Always reference structure
        'gro': [],  # Always reference structure
        'itp': [],  # Always include
        'rtp': [],  # Always include
        'prm': [],  # Always include
        'xtc': [],  # Always trajectory
        'trr': [],  # Always trajectory
        'tpr': [],  # Always topology (binary)
        'zip': [],  # Always forcefield
    }
    return role_options_map.get(file_type, [])


def get_default_role(file_type: str, mode: str = 'trajectory') -> str:
    """
    Return the default role for a file type.
    
    Args:
        file_type: File extension (e.g., 'pdb', 'xtc')
        mode: Input mode ('trajectory' or 'ensemble')
    
    Returns:
        Default role string
    """
    if mode == 'ensemble':
        if file_type == 'pdb':
            return 'ensemble_pdb'
        return 'other'
    
    # Trajectory mode defaults
    default_roles = {
        'pdb': 'structure',
        'gro': 'structure',
        'xtc': 'trajectory',
        'trr': 'trajectory',
        'tpr': 'topology',
        'top': 'topology',
        'itp': 'include',
        'rtp': 'include',
        'prm': 'include',
        'zip': 'forcefield'
    }
    return default_roles.get(file_type, 'other')


def get_role_display_name(role: str) -> str:
    """
    Return human-readable display name for a role.
    
    Args:
        role: Role identifier
    
    Returns:
        Human-readable role name
    """
    role_names = {
        'structure': 'Reference structure',
        'topology': 'Topology file (main)',
        'include': 'Include file',
        'trajectory': 'Trajectory file',
        'forcefield': 'Force field archive',
        'ensemble_pdb': 'Ensemble PDB',
        'other': 'Other'
    }
    return role_names.get(role, role)


def detect_role_conflicts(files: list, mode: str = 'trajectory') -> dict:
    """
    Detect files with conflicting exclusive roles.
    
    In trajectory mode:
    - Only one file should have 'topology' role
    - Only one PDB/GRO file should be uploaded (reference structure)
    
    Args:
        files: List of file data dicts
        mode: Input mode ('trajectory' or 'ensemble')
    
    Returns:
        Dict with 'topology' and 'structure' keys, each containing
        list of file keys that have conflicts (conflict if len > 1)
    """
    conflicts = {'topology': [], 'structure': []}
    
    if mode == 'ensemble':
        # No conflicts to detect in ensemble mode
        return conflicts
    
    # Filter to current mode files only
    files_for_mode = [f for f in files if f.get('uploaded_for_mode', 'trajectory') == mode]
    
    for f in files_for_mode:
        file_type = f.get('file_type', '')
        role = f.get('role', get_default_role(file_type, mode))
        file_key = f.get('temp_file_id') or f.get('example_path') or f.get('filename')
        
        if role == 'topology':
            conflicts['topology'].append(file_key)
        
        # Track structure files by type (pdb/gro)
        if file_type in ['pdb', 'gro']:
            conflicts['structure'].append(file_key)
    
    return conflicts


def create_purpose_cell(file_data: dict, file_key: str, input_mode: str, conflicts: dict = None, is_selected_structure: bool = False) -> html.Div:
    """
    Create the purpose cell for a file row - either a dropdown, radio button, or static text.
    
    Args:
        file_data: File metadata dict
        file_key: Unique key for the file (for pattern matching)
        input_mode: Current input mode ('trajectory' or 'ensemble')
        conflicts: Dict of role conflicts from detect_role_conflicts()
        is_selected_structure: Whether this file is the selected reference structure
    
    Returns:
        html.Div containing either a dropdown, radio button, or static text
    """
    file_type = file_data.get('file_type', '')
    role_options = get_role_options(file_type, input_mode)
    current_role = file_data.get('role', get_default_role(file_type, input_mode))
    
    # Check for topology conflict
    has_topology_conflict = False
    if conflicts:
        if file_key in conflicts.get('topology', []) and len(conflicts.get('topology', [])) > 1:
            has_topology_conflict = True
    
    # Check for structure conflict (multiple PDB/GRO files)
    has_structure_conflict = False
    if conflicts and file_type in ['pdb', 'gro']:
        if len(conflicts.get('structure', [])) > 1:
            has_structure_conflict = True
    
    # Determine border style based on conflict state
    dropdown_style = {
        'fontSize': '0.8rem',
        'minWidth': '150px',
    }
    if has_topology_conflict:
        dropdown_style['border'] = '2px solid #dc3545'
        dropdown_style['borderRadius'] = '4px'
    
    if role_options:
        # Multiple options - render dropdown (for topology files)
        purpose_content = html.Div([
            dcc.Dropdown(
                id={'type': 'file-role', 'index': file_key},
                options=role_options,
                value=current_role,
                clearable=False,
                style=dropdown_style,
                className='file-role-dropdown'
            ),
            # Warning icon for conflicts
            html.I(
                className="fas fa-exclamation-triangle",
                style={
                    'color': '#dc3545',
                    'marginLeft': '8px',
                    'display': 'inline-block' if has_topology_conflict else 'none'
                },
                title=f"Conflict: Another file also has this role" if has_topology_conflict else ""
            ) if has_topology_conflict else None
        ], style={'display': 'flex', 'alignItems': 'center', 'flex': '2.5'})
    elif has_structure_conflict:
        # Multiple structure files - show radio button for selection
        purpose_content = html.Div([
            dcc.RadioItems(
                id={'type': 'structure-select', 'index': file_key},
                options=[{'label': ' Use as Reference', 'value': file_key}],
                value=file_key if is_selected_structure else None,
                inline=True,
                style={'fontSize': '0.8rem'},
                inputStyle={'marginRight': '5px'},
                labelStyle={'display': 'flex', 'alignItems': 'center', 'cursor': 'pointer'}
            ),
            html.I(
                className="fas fa-exclamation-triangle",
                style={
                    'color': '#dc3545',
                    'marginLeft': '8px',
                },
                title="Multiple structure files uploaded. Select one to use."
            )
        ], style={'display': 'flex', 'alignItems': 'center', 'flex': '2.5'})
    else:
        # Fixed role - render static text
        purpose_text = get_role_display_name(current_role)
        purpose_content = html.Div(
            purpose_text,
            style={'flex': '2.5', 'fontSize': '0.8rem', 'color': '#6c757d', 'fontStyle': 'italic'}
        )
    
    return purpose_content


def extract_toc_from_markdown(content: str) -> list:
    """
    Extract table of contents from markdown content by parsing headings.
    
    Args:
        content: Markdown text content
        
    Returns:
        List of dicts with 'level', 'title', and 'id' for each heading
    """
    import re
    toc = []
    
    # Match markdown headings (# ## ### etc.)
    heading_pattern = re.compile(r'^(#{1,3})\s+(.+)$', re.MULTILINE)
    
    for match in heading_pattern.finditer(content):
        level = len(match.group(1))  # Number of # symbols
        title = match.group(2).strip()
        
        # Generate slug ID (lowercase, replace spaces with hyphens, remove special chars)
        slug = re.sub(r'[^\w\s-]', '', title.lower())
        slug = re.sub(r'[\s]+', '-', slug)
        
        toc.append({
            'level': level,
            'title': title,
            'id': slug
        })
    
    return toc


def inject_heading_anchors(content: str) -> str:
    """
    Replace markdown headings with HTML heading tags that include IDs for TOC navigation.
    
    Args:
        content: Original markdown content
        
    Returns:
        Modified content with HTML headings that have IDs for anchor navigation
    """
    import re
    
    def replace_heading(match):
        hashes = match.group(1)
        title = match.group(2).strip()
        level = len(hashes)
        # Generate slug ID matching the TOC extraction
        slug = re.sub(r'[^\w\s-]', '', title.lower())
        slug = re.sub(r'[\s]+', '-', slug)
        # Replace markdown heading with HTML heading that has an ID
        return f'<h{level} id="{slug}">{title}</h{level}>'
    
    heading_pattern = re.compile(r'^(#{1,3})\s+(.+)$', re.MULTILINE)
    return heading_pattern.sub(replace_heading, content)


def read_help_content() -> tuple:
    """
    Read help markdown file and extract TOC.
    
    Returns:
        Tuple of (markdown_content, toc_list)
    """
    help_file_path = os.path.join(os.path.dirname(__file__), '..', 'docs', 'help.md')
    
    try:
        with open(help_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        toc = extract_toc_from_markdown(content)
        # Inject anchor tags for TOC navigation
        content_with_anchors = inject_heading_anchors(content)
        return content_with_anchors, toc
    except FileNotFoundError:
        logger.error(f"Help file not found: {help_file_path}")
        return "# Help\n\nHelp documentation is not available.", []
    except Exception as e:
        logger.error(f"Error reading help file: {e}")
        return f"# Help\n\nError loading help documentation: {str(e)}", []


# Initialize Dash app
app = Dash(__name__, 
          external_stylesheets=[
              dbc.themes.BOOTSTRAP,
              "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css",
              "https://cdn.jsdelivr.net/npm/driver.js@1.3.1/dist/driver.css"
          ],
          external_scripts=[
              "https://cdn.jsdelivr.net/npm/driver.js@1.3.1/dist/driver.js.iife.js"
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
            .status-expired { 
                background-color: rgba(149, 165, 166, 0.1);
                color: #95a5a6;
                border-color: rgba(149, 165, 166, 0.3);
                font-style: italic;
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
            
            /* Upload progress animation */
            @keyframes pulse {
                0% { opacity: 0.6; }
                50% { opacity: 1; }
                100% { opacity: 0.6; }
            }
            .upload-processing {
                animation: pulse 1.5s ease-in-out infinite;
            }
            
            /* Upload zone hover effect */
            .upload-zone:hover {
                background-color: #e8f5e9 !important;
                border-color: #5A7A60 !important;
            }
            
            /* File row removal animation */
            .file-table-row.removing {
                opacity: 0.5;
                background-color: #fff3cd !important;
                pointer-events: none;
            }
            .file-table-row.removing .remove-file-btn {
                opacity: 0.5;
                cursor: not-allowed;
            }
            .file-table-row.removed {
                opacity: 0;
                height: 0;
                padding: 0 !important;
                margin: 0;
                overflow: hidden;
                border: none !important;
            }
            
            /* Spinner animation for remove button */
            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
            .fa-spinner {
                animation: spin 1s linear infinite;
            }
            
            /* Help page styles */
            .help-markdown-content h1 {
                color: #5A7A60;
                font-size: 1.8rem;
                margin-top: 40px;
                margin-bottom: 20px;
                padding-bottom: 10px;
                border-bottom: 2px solid rgba(90, 122, 96, 0.2);
            }
            
            .help-markdown-content h1:first-child {
                margin-top: 0;
            }
            
            .help-markdown-content h2 {
                color: #6B8574;
                font-size: 1.4rem;
                margin-top: 30px;
                margin-bottom: 15px;
            }
            
            .help-markdown-content h3 {
                color: #7C9885;
                font-size: 1.15rem;
                margin-top: 25px;
                margin-bottom: 10px;
            }
            
            .help-markdown-content h4 {
                color: #8DAA96;
                font-size: 1.0rem;
                margin-top: 20px;
                margin-bottom: 8px;
            }
            
            .help-markdown-content h5 {
                color: #9EBB97;
                font-size: 0.95rem;
                margin-top: 15px;
                margin-bottom: 6px;
            }
            
            .help-markdown-content h6 {
                color: #AFCCA8;
                font-size: 0.9rem;
                margin-top: 12px;
                margin-bottom: 5px;
            }
            
            .help-markdown-content p {
                margin-bottom: 15px;
                color: #444;
            }
            
            .help-markdown-content ul, .help-markdown-content ol {
                margin-bottom: 15px;
                padding-left: 25px;
            }
            
            .help-markdown-content li {
                margin-bottom: 8px;
                color: #444;
            }
            
            .help-markdown-content code {
                background: rgba(90, 122, 96, 0.1);
                padding: 2px 6px;
                border-radius: 4px;
                font-size: 0.9em;
                color: #5A7A60;
            }
            
            .help-markdown-content pre {
                background: #f8f9fa;
                padding: 15px;
                border-radius: 8px;
                border: 1px solid rgba(90, 122, 96, 0.15);
                overflow-x: auto;
            }
            
            .help-markdown-content pre code {
                background: none;
                padding: 0;
            }
            
            .help-markdown-content blockquote {
                border-left: 4px solid #5A7A60;
                padding-left: 20px;
                margin: 20px 0;
                color: #666;
                font-style: italic;
            }
            
            .help-markdown-content strong {
                color: #333;
            }
            
            .help-markdown-content a {
                color: #5A7A60;
                text-decoration: underline;
            }
            
            .help-markdown-content a:hover {
                color: #495F4F;
            }
            
            .help-toc-sidebar a:hover {
                border-left-color: #5A7A60 !important;
                background: rgba(90, 122, 96, 0.05);
            }
            
            /* Show TOC sidebar on larger screens */
            @media (min-width: 992px) {
                .help-toc-sidebar {
                    display: block !important;
                }
                .help-main-content {
                    padding-left: 30px !important;
                }
            }
            
            @media (max-width: 991px) {
                .help-main-content {
                    padding-left: 0 !important;
                }
            }
        </style>
        <script>
            // File Upload Handler - validates size BEFORE reading files
            (function() {
                function getLimitsFromDom() {
                    var el = document.getElementById('global-limits-config');
                    var maxTrajectoryMb = el && el.dataset && el.dataset.maxTrajectoryMb ? parseInt(el.dataset.maxTrajectoryMb, 10) : 100;
                    var maxOtherMb = el && el.dataset && el.dataset.maxOtherMb ? parseInt(el.dataset.maxOtherMb, 10) : 10;
                    var maxFramesRaw = el && el.dataset ? el.dataset.maxFrames : '';
                    return {
                        maxTrajectoryMb: Number.isFinite(maxTrajectoryMb) && maxTrajectoryMb > 0 ? maxTrajectoryMb : 100,
                        maxOtherMb: Number.isFinite(maxOtherMb) && maxOtherMb > 0 ? maxOtherMb : 10,
                        maxFrames: maxFramesRaw
                    };
                }
                
                // Progress indicator threshold - show for files > 10MB
                var PROGRESS_THRESHOLD = 10 * 1024 * 1024;

                function getFileLimitMb(filename) {
                    var limits = getLimitsFromDom();
                    var name = (filename || '').toLowerCase();
                    var isTrajectory = name.endsWith('.xtc') || name.endsWith('.trr');
                    // Check if we're in ensemble mode - PDB files get trajectory limit
                    // dbc.RadioItems renders as container with radio inputs inside
                    var isEnsembleMode = false;
                    var modeContainer = document.getElementById('input-mode-selector');
                    if (modeContainer) {
                        var checkedRadio = modeContainer.querySelector('input[type="radio"]:checked');
                        if (checkedRadio && checkedRadio.value === 'ensemble') {
                            isEnsembleMode = true;
                        }
                    }
                    var isEnsemblePdb = isEnsembleMode && name.endsWith('.pdb');
                    var useTrajectoryLimit = isTrajectory || isEnsemblePdb;
                    return useTrajectoryLimit ? limits.maxTrajectoryMb : limits.maxOtherMb;
                }

                function getFileKindLabel(filename) {
                    var name = (filename || '').toLowerCase();
                    var isTrajectory = name.endsWith('.xtc') || name.endsWith('.trr');
                    // Check if we're in ensemble mode - PDB files are treated as trajectory-class
                    // dbc.RadioItems renders as container with radio inputs inside
                    var isEnsembleMode = false;
                    var modeContainer = document.getElementById('input-mode-selector');
                    if (modeContainer) {
                        var checkedRadio = modeContainer.querySelector('input[type="radio"]:checked');
                        if (checkedRadio && checkedRadio.value === 'ensemble') {
                            isEnsembleMode = true;
                        }
                    }
                    var isEnsemblePdb = isEnsembleMode && name.endsWith('.pdb');
                    if (isEnsemblePdb) return 'ensemble PDB';
                    if (isTrajectory) return 'trajectory';
                    return 'structure/topology';
                }
                
                function showRejectionWarning(rejectedFiles) {
                    const warningDiv = document.getElementById('file-rejection-warning');
                    if (warningDiv && rejectedFiles.length > 0) {
                        const fileList = rejectedFiles.map(f => 
                            '<li style="margin: 4px 0;">' +
                            '<strong>' + f.name + '</strong> ' +
                            '<span style="color: #721c24;">(' + (f.size / 1024 / 1024).toFixed(1) + ' MB)</span> ' +
                            '<span style="color: #856404;">— limit: ' + f.limitMb + 'MB (' + f.kind + ')</span>' +
                            '</li>'
                        ).join('');
                        warningDiv.innerHTML = 
                            '<div class="alert alert-danger" style="display: flex; align-items: flex-start; margin: 15px 0; padding: 15px; border: 2px solid #f5c6cb; border-radius: 8px;">' +
                            '<i class="fas fa-exclamation-circle" style="margin-right: 12px; color: #dc3545; font-size: 1.5rem; flex-shrink: 0;"></i>' +
                            '<div style="flex: 1;">' +
                            '<div style="font-size: 1rem; font-weight: 600; margin-bottom: 8px; color: #721c24;">⚠️ File(s) rejected - exceeds size limit</div>' +
                            '<ul style="margin: 0 0 10px 0; padding-left: 20px; font-size: 0.9rem;">' + fileList + '</ul>' +
                            '<div style="font-size: 0.85rem; color: #856404; background: #fff3cd; padding: 8px 12px; border-radius: 4px; border: 1px solid #ffeeba;">' +
                            '<i class="fas fa-lightbulb" style="margin-right: 6px;"></i>' +
                            '<strong>Tip:</strong> Extract fewer frames from your trajectory, or split it into smaller parts using GROMACS: ' +
                            '<code style="background: #f8f9fa; padding: 2px 6px; border-radius: 3px;">gmx trjconv -skip 10</code>' +
                            '</div>' +
                            '</div>' +
                            '</div>';
                    }
                }
                
                function clearRejectionWarning() {
                    const warningDiv = document.getElementById('file-rejection-warning');
                    if (warningDiv) {
                        warningDiv.innerHTML = '';
                    }
                }
                
                function showProgress(fileCount, totalSize) {
                    const progressContainer = document.getElementById('upload-progress-container');
                    const progressText = document.getElementById('upload-progress-text');
                    if (progressContainer && progressText) {
                        progressContainer.style.display = 'block';
                        progressContainer.style.marginTop = '10px';
                        progressContainer.style.padding = '10px';
                        progressContainer.style.backgroundColor = '#e8f5e9';
                        progressContainer.style.borderRadius = '5px';
                        progressContainer.style.border = '1px solid #c8e6c9';
                        const sizeMB = (totalSize / 1024 / 1024).toFixed(1);
                        progressText.textContent = 'Reading ' + fileCount + ' file(s) (' + sizeMB + ' MB)... Please wait.';
                    }
                }
                
                function hideProgress() {
                    const progressContainer = document.getElementById('upload-progress-container');
                    if (progressContainer) {
                        progressContainer.style.display = 'none';
                    }
                }
                
                function readFileAsDataURL(file) {
                    return new Promise((resolve, reject) => {
                        const reader = new FileReader();
                        reader.onload = () => resolve({
                            name: file.name,
                            content: reader.result,
                            lastModified: file.lastModified
                        });
                        reader.onerror = reject;
                        reader.readAsDataURL(file);
                    });
                }
                
                async function handleFileSelection(files) {
                    if (!files || files.length === 0) return;
                    
                    const rejectedFiles = [];
                    const acceptedFiles = [];
                    let totalSize = 0;
                    
                    // First pass: check sizes WITHOUT reading files
                    for (let i = 0; i < files.length; i++) {
                        const limitMb = getFileLimitMb(files[i].name);
                        const limitBytes = limitMb * 1024 * 1024;
                        if (files[i].size > limitBytes) {
                            rejectedFiles.push({
                                name: files[i].name,
                                size: files[i].size,
                                limitMb: limitMb,
                                kind: getFileKindLabel(files[i].name)
                            });
                        } else {
                            acceptedFiles.push(files[i]);
                            totalSize += files[i].size;
                        }
                    }
                    
                    // Show rejection warning immediately if any files rejected
                    if (rejectedFiles.length > 0) {
                        showRejectionWarning(rejectedFiles);
                    } else {
                        clearRejectionWarning();
                    }
                    
                    // If no valid files, stop here
                    if (acceptedFiles.length === 0) {
                        return;
                    }
                    
                    // Show progress for large uploads
                    if (totalSize > PROGRESS_THRESHOLD) {
                        showProgress(acceptedFiles.length, totalSize);
                    }
                    
                    try {
                        // Now read only the valid files
                        const fileDataPromises = acceptedFiles.map(f => readFileAsDataURL(f));
                        const fileDataArray = await Promise.all(fileDataPromises);
                        
                        // Trigger Dash upload by updating the dcc.Upload component
                        // We need to programmatically set the contents
                        const contents = fileDataArray.map(f => f.content);
                        const filenames = fileDataArray.map(f => f.name);
                        const lastModified = fileDataArray.map(f => f.lastModified);
                        
                        // Find and trigger the Dash upload component
                        // Dash components store their props in window.dash_clientside
                        if (window.dash_clientside && window.dash_clientside.set_props) {
                            window.dash_clientside.set_props('upload-files', {
                                contents: contents.length === 1 ? contents[0] : contents,
                                filename: filenames.length === 1 ? filenames[0] : filenames,
                                last_modified: lastModified.length === 1 ? lastModified[0] : lastModified
                            });
                        } else {
                            // Fallback: dispatch custom event that a clientside callback can listen to
                            const store = document.getElementById('validated-files-store');
                            if (store) {
                                // Store the data for the clientside callback
                                window._validatedFiles = {
                                    contents: contents,
                                    filenames: filenames,
                                    lastModified: lastModified
                                };
                                // Trigger a change
                                store.click();
                            }
                        }
                    } catch (error) {
                        console.error('Error reading files:', error);
                    } finally {
                        hideProgress();
                    }
                }
                
                function initFileHandler() {
                    // Find the dcc.Upload component's container
                    const uploadContainer = document.getElementById('upload-files');
                    if (!uploadContainer) {
                        setTimeout(initFileHandler, 300);
                        return;
                    }
                    
                    // Find the actual file input inside the dcc.Upload component
                    // dcc.Upload creates an input[type=file] inside its div
                    const fileInput = uploadContainer.querySelector('input[type="file"]');
                    if (!fileInput) {
                        // Wait for it to be created
                        setTimeout(initFileHandler, 300);
                        return;
                    }
                    
                    // Skip if already initialized
                    if (fileInput._sizeCheckInitialized) {
                        return;
                    }
                    fileInput._sizeCheckInitialized = true;
                    
                    // Create a wrapper function that intercepts file selection
                    const originalOnChange = fileInput.onchange;
                    
                    // Intercept the file input's change event BEFORE dcc.Upload processes it
                    fileInput.addEventListener('change', function(e) {
                        const files = e.target.files;
                        if (!files || files.length === 0) return;
                        
                        let hasOversizedFiles = false;
                        let rejectedFiles = [];
                        
                        for (let i = 0; i < files.length; i++) {
                            const limitMb = getFileLimitMb(files[i].name);
                            const limitBytes = limitMb * 1024 * 1024;
                            if (files[i].size > limitBytes) {
                                hasOversizedFiles = true;
                                rejectedFiles.push({
                                    name: files[i].name,
                                    size: files[i].size,
                                    limitMb: limitMb,
                                    kind: getFileKindLabel(files[i].name)
                                });
                            }
                        }
                        
                        if (hasOversizedFiles) {
                            // Show warning
                            showRejectionWarning(rejectedFiles);
                            
                            // IMPORTANT: Prevent dcc.Upload from processing these files
                            // We stop the event propagation and prevent default
                            e.stopImmediatePropagation();
                            e.preventDefault();
                            
                            // Clear the input
                            e.target.value = '';
                            
                            return false;
                        }
                        
                        // Show progress for large files
                        let totalSize = 0;
                        for (let i = 0; i < files.length; i++) {
                            totalSize += files[i].size;
                        }
                        if (totalSize > PROGRESS_THRESHOLD) {
                            showProgress('Processing files...', totalSize);
                            // Hide progress after a timeout (actual hide should be in callback)
                            setTimeout(hideProgress, 10000);
                        }
                        
                        // Let dcc.Upload process accepted files normally
                    }, true);  // Use capture phase to run before dcc.Upload
                    
                    console.log('File upload handler initialized - size validation enabled (interception mode)');
                }
                
                function setupObserverAndDropHandler() {
                    // Watch for dynamic content
                    const observer = new MutationObserver(() => {
                        const uploadContainer = document.getElementById('upload-files');
                        if (uploadContainer && !window._fileHandlerInitialized) {
                            const fileInput = uploadContainer.querySelector('input[type="file"]');
                            if (fileInput && !fileInput._sizeCheckInitialized) {
                                window._fileHandlerInitialized = true;
                                initFileHandler();
                            }
                        }
                    });
                    observer.observe(document.body, { childList: true, subtree: true });
                    
                    // Also intercept drag and drop on the upload container
                    document.addEventListener('drop', function(e) {
                        const uploadContainer = document.getElementById('upload-files');
                        if (!uploadContainer) return;
                        
                        // Check if the drop is on or within the upload container
                        if (uploadContainer.contains(e.target) || e.target === uploadContainer) {
                            const files = e.dataTransfer && e.dataTransfer.files;
                            if (!files || files.length === 0) return;
                            
                            let hasOversizedFiles = false;
                            let rejectedFiles = [];
                            
                            for (let i = 0; i < files.length; i++) {
                                const limitMb = getFileLimitMb(files[i].name);
                                const limitBytes = limitMb * 1024 * 1024;
                                if (files[i].size > limitBytes) {
                                    hasOversizedFiles = true;
                                    rejectedFiles.push({
                                        name: files[i].name,
                                        size: files[i].size,
                                        limitMb: limitMb,
                                        kind: getFileKindLabel(files[i].name)
                                    });
                                }
                            }
                            
                            if (hasOversizedFiles) {
                                e.stopImmediatePropagation();
                                e.preventDefault();
                                showRejectionWarning(rejectedFiles);
                            } else {
                                // Show progress for large files
                                let totalSize = 0;
                                for (let i = 0; i < files.length; i++) {
                                    totalSize += files[i].size;
                                }
                                if (totalSize > PROGRESS_THRESHOLD) {
                                    showProgress('Processing files...', totalSize);
                                    setTimeout(hideProgress, 10000);
                                }
                            }
                        }
                    }, true);  // Capture phase
                }
                
                // Initialize when page is ready
                if (document.readyState === 'loading') {
                    document.addEventListener('DOMContentLoaded', function() {
                        setTimeout(initFileHandler, 200);
                        setupObserverAndDropHandler();
                    });
                } else {
                    setTimeout(initFileHandler, 200);
                    setupObserverAndDropHandler();
                }
                
                // Re-initialize after SPA navigation
                window.addEventListener('load', () => setTimeout(initFileHandler, 500));
            })();
            
            // Immediate visual feedback for file removal
            (function() {
                // Use event delegation for dynamically created remove buttons
                document.addEventListener('click', function(e) {
                    // Check if the clicked element is a remove button or inside one
                    const button = e.target.closest('.remove-file-btn');
                    if (!button) return;
                    
                    // Find the parent row
                    const row = button.closest('.file-table-row');
                    if (!row) return;
                    
                    // Check if already being removed
                    if (row.classList.contains('removing') || row.classList.contains('removed')) {
                        e.preventDefault();
                        e.stopPropagation();
                        return;
                    }

                    // IMPORTANT: let Dash/React receive this click first.
                    // If we disable the button in capture phase (or too early), Dash may never
                    // register the click and n_clicks_timestamp stays None.
                    setTimeout(function() {
                        if (!document.contains(button) || !document.contains(row)) return;

                        // Apply immediate visual feedback
                        row.classList.add('removing');

                        // Change the icon to a spinner
                        const icon = button.querySelector('i');
                        if (icon) {
                            icon.className = 'fas fa-spinner';
                        }

                        // Disable the button
                        button.disabled = true;
                        button.style.cursor = 'not-allowed';
                    }, 0);
                    
                    console.log('File removal initiated - visual feedback applied');

                    // If backend/store update doesn't remove the row within a reasonable time,
                    // restore the button so the user isn't stuck.
                    setTimeout(function() {
                        if (!row || !document.contains(row)) return;
                        if (!row.classList.contains('removing')) return;

                        row.classList.remove('removing');

                        const icon2 = button.querySelector('i');
                        if (icon2) {
                            icon2.className = 'fas fa-trash';
                        }
                        button.disabled = false;
                        button.style.cursor = 'pointer';
                        console.warn('Remove did not complete in time; UI restored');
                    }, 15000);
                }, false);  // Bubble phase: don't interfere with Dash handlers
            })();
            
            // Tab focus auto-refresh for GROMACS versions
            (function() {
                document.addEventListener('visibilitychange', function() {
                    if (document.visibilityState === 'visible') {
                        // Trigger refresh by updating the tab-focus-trigger store
                        const store = document.getElementById('tab-focus-trigger');
                        if (store && window.dash_clientside && window.dash_clientside.set_props) {
                            const newValue = Date.now();
                            window.dash_clientside.set_props('tab-focus-trigger', { data: newValue });
                            console.log('Tab focused - triggering GROMACS versions refresh');
                        }
                    }
                });
            })();
        </script>
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

# Clientside callback to transfer validated files from JavaScript to dcc.Upload
app.clientside_callback(
    """
    function(n_clicks) {
        // This callback is triggered when JavaScript stores validated files
        if (window._validatedFiles) {
            const files = window._validatedFiles;
            window._validatedFiles = null;  // Clear after use
            return [
                files.contents.length === 1 ? files.contents[0] : files.contents,
                files.filenames.length === 1 ? files.filenames[0] : files.filenames,
                files.lastModified.length === 1 ? files.lastModified[0] : files.lastModified
            ];
        }
        return [window.dash_clientside.no_update, window.dash_clientside.no_update, window.dash_clientside.no_update];
    }
    """,
    [Output('upload-files', 'contents'),
     Output('upload-files', 'filename'),
     Output('upload-files', 'last_modified')],
    [Input('validated-files-store', 'n_clicks')],
    prevent_initial_call=True
)

# Clientside callback to start tutorial when Tutorial button is clicked
app.clientside_callback(
    """
    function(n_clicks) {
        if (n_clicks && n_clicks > 0) {
            // Small delay to ensure page is fully rendered
            setTimeout(function() {
                if (window.grinnTutorial && window.grinnTutorial.start) {
                    window.grinnTutorial.start();
                } else {
                    console.error('[Tutorial] Tutorial system not loaded');
                    alert('Tutorial is loading... Please try again in a moment.');
                }
            }, 100);
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output('start-tutorial-btn', 'n_clicks'),
    Input('start-tutorial-btn', 'n_clicks'),
    prevent_initial_call=True
)


# Callback to fetch GROMACS versions from API on page load and tab focus
@app.callback(
    [Output('gromacs-version-display', 'options'),
     Output('gromacs-version-display', 'value'),
     Output('gromacs-version-selector', 'options'),
     Output('gromacs-version-selector', 'value'),
     Output('gromacs-version-warning', 'children')],
    [Input('input-mode-selector', 'value'),
     Input('tab-focus-trigger', 'data')],
    prevent_initial_call=False
)
def fetch_gromacs_versions(mode, tab_focus_trigger):
    """Fetch available GROMACS versions from the API."""
    import requests
    
    # Only relevant for trajectory mode
    if mode != 'trajectory':
        return [], None, [], None, html.Div()
    
    try:
        # Call the API to get available versions
        backend_url = f"{config.backend_url}/api/gromacs-versions"
        response = requests.get(backend_url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            versions = data.get('versions', [])
            default_version = data.get('default')
            worker_count = data.get('worker_count', 0)
            
            if not versions:
                # No workers available
                warning = html.Div([
                    html.I(className="fas fa-exclamation-circle", style={'marginRight': '6px', 'color': '#dc3545'}),
                    html.Span("No workers available. Job submission is currently disabled.", 
                              style={'color': '#dc3545', 'fontSize': '0.85rem'})
                ])
                return [], None, [], None, warning
            
            # Build dropdown options with worker counts
            options = [
                {'label': v['label'], 'value': v['version']}
                for v in versions
            ]
            
            # Set default value
            value = default_version if default_version else (versions[0]['version'] if versions else None)
            
            return options, value, options, value, html.Div()
        else:
            # API error
            warning = html.Div([
                html.I(className="fas fa-exclamation-triangle", style={'marginRight': '6px', 'color': '#ffc107'}),
                html.Span("Could not fetch GROMACS versions. Using default.", 
                          style={'color': '#856404', 'fontSize': '0.85rem'})
            ])
            default_options = [{'label': f"{config.default_gromacs_version}", 'value': config.default_gromacs_version}]
            return default_options, config.default_gromacs_version, default_options, config.default_gromacs_version, warning
            
    except Exception as e:
        logger.warning(f"Error fetching GROMACS versions: {e}")
        # Fallback to default
        warning = html.Div([
            html.I(className="fas fa-exclamation-triangle", style={'marginRight': '6px', 'color': '#ffc107'}),
            html.Span("Could not connect to backend. Using default version.", 
                      style={'color': '#856404', 'fontSize': '0.85rem'})
        ])
        default_options = [{'label': f"{config.default_gromacs_version}", 'value': config.default_gromacs_version}]
        return default_options, config.default_gromacs_version, default_options, config.default_gromacs_version, warning


def create_header():
    """Create the main header component with two-column layout."""
    return html.Div([
        # Two-column layout: icon (left) and content (right)
        html.Div([
            # Left column - Shamrock icon
            html.Div([
                html.Img(
                    src='/assets/shamrock_lucky.svg',
                    style={
                        'width': '120px',
                        'height': 'auto'
                    }
                )
            ], style={
                'flexShrink': '0',
                'marginRight': '25px'
            }),
            
            # Right column - Title, tagline, and navigation
            html.Div([
                # Row 1: Title
                html.H1("i-gRINN", style={
                    'color': '#5A7A60',
                    'marginBottom': '8px',
                    'marginTop': '0',
                    'fontSize': '2.5rem',
                    'fontWeight': 'bold'
                }),
                
                # Row 2: Tagline with bold letters spelling i-gRINN
                html.P([
                    html.Strong("I", style={'color': '#5A7A60'}),
                    "nteractive platform for (",
                    html.Strong("g", style={'color': '#5A7A60'}),
                    "et) ",
                    html.Strong("R", style={'color': '#5A7A60'}),
                    "esidue ",
                    html.Strong("I", style={'color': '#5A7A60'}),
                    "nteractio",
                    html.Strong("n", style={'color': '#5A7A60'}),
                    " energies and ",
                    html.Strong("N", style={'color': '#5A7A60'}),
                    "etworks"
                ], style={
                    'color': '#6A8A70',
                    'fontSize': '1.1rem',
                    'marginBottom': '15px',
                    'marginTop': '0'
                }),
                
                # Row 3: Navigation buttons (left-aligned within this column)
                html.Div([
                    html.A(
                        [html.I(className="fas fa-home", style={'marginRight': '6px'}), "Submit Job"],
                        href="/",
                        id="nav-home-link",
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
                            'fontWeight': '500'
                        }
                    ),
                    html.A(
                        [html.I(className="fas fa-list-ul", style={'marginRight': '6px'}), "View Job Queue"],
                        href="/queue",
                        target="_blank",
                        id="nav-queue-link",
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
                            'marginRight': '10px'
                        }
                    ),
                    html.A(
                        [html.I(className="fas fa-question-circle", style={'marginRight': '6px'}), "Help"],
                        href="/help",
                        target="_blank",
                        id="nav-help-link",
                        className="nav-link",
                        style={
                            'display': 'inline-block',
                            'padding': '8px 16px',
                            'backgroundColor': 'rgba(108, 117, 125, 0.1)',
                            'color': '#6c757d',
                            'textDecoration': 'none',
                            'borderRadius': '5px',
                            'fontSize': '0.9rem',
                            'fontWeight': '500',
                            'border': '1px solid rgba(108, 117, 125, 0.3)',
                            'marginRight': '10px'
                        }
                    ),
                    html.A(
                        [html.I(className="fab fa-github", style={'marginRight': '6px'}), "Standalone gRINN"],
                        href="https://github.com/osercinoglu/grinn",
                        target="_blank",
                        id="nav-standalone-link",
                        className="nav-link",
                        style={
                            'display': 'inline-block',
                            'padding': '8px 16px',
                            'backgroundColor': 'rgba(36, 41, 46, 0.1)',
                            'color': '#24292e',
                            'textDecoration': 'none',
                            'borderRadius': '5px',
                            'fontSize': '0.9rem',
                            'fontWeight': '500',
                            'border': '1px solid rgba(36, 41, 46, 0.3)',
                            'marginRight': '10px'
                        }
                    ),
                    html.Button(
                        [html.I(className="fas fa-graduation-cap", style={'marginRight': '6px'}), "Tutorial"],
                        id="start-tutorial-btn",
                        className="nav-link",
                        style={
                            'display': 'inline-block',
                            'padding': '8px 16px',
                            'backgroundColor': 'rgba(255, 193, 7, 0.15)',
                            'color': '#856404',
                            'border': '1px solid rgba(255, 193, 7, 0.4)',
                            'borderRadius': '5px',
                            'fontSize': '0.9rem',
                            'fontWeight': '500',
                            'cursor': 'pointer'
                        }
                    )
                ])
            ])
        ], style={
            'display': 'flex',
            'alignItems': 'center'
        })
    ], style={
        'margin': '20px',
        'padding': '20px'
    })


def create_footer():
    """Create the footer component with institutional logos and attribution."""
    return html.Footer([
        # Institutional logos section
        html.Div([
            html.A(
                html.Img(
                    src='/assets/costbio.jpg',
                    alt='COSTBIO - Computational Structural Biology Research Group',
                    style={
                        'height': '60px',
                        'width': 'auto',
                        'marginRight': '30px',
                        'mixBlendMode': 'multiply'
                    }
                ),
                href='https://costbio.github.io',
                target='_blank',
                rel='noopener noreferrer'
            ),
            html.A(
                html.Img(
                    src='/assets/GTU_LOGO_1200X768_JPG_EN.jpg',
                    alt='Gebze Technical University',
                    style={
                        'height': '165px',
                        'width': 'auto',
                        'marginRight': '30px',
                        'mixBlendMode': 'multiply'
                    }
                ),
                href='https://www.gtu.edu.tr',
                target='_blank',
                rel='noopener noreferrer'
            ),
            html.A(
                html.Img(
                    src='/assets/Marmara_uni_logo_iki_renkli.png',
                    alt='Marmara University',
                    style={
                        'height': '60px',
                        'width': 'auto'
                    }
                ),
                href='https://www.marmara.edu.tr',
                target='_blank',
                rel='noopener noreferrer'
            )
        ], style={
            'display': 'flex',
            'justifyContent': 'center',
            'alignItems': 'flex-end',
            'marginBottom': '20px'
        }),
        
        # Attribution text section
        html.Div([
            html.P([
                "Developed by ",
                html.A(
                    html.Strong("Computational Structural Biology Research Group (COSTBIO)"),
                    href='https://costbio.github.io',
                    target='_blank',
                    rel='noopener noreferrer',
                    style={'color': '#5A7A60', 'textDecoration': 'none'}
                ),
                ", Bioengineering Department, Gebze Technical University"
            ], style={
                'margin': '0 0 8px 0',
                'fontSize': '0.9rem',
                'color': '#5A7A60'
            }),
            html.P([
                "In collaboration with ",
                html.A(
                    html.Strong("Computational Biology and Bioinformatics Research Group"),
                    href='https://compbio-bioe-eng.marmara.edu.tr',
                    target='_blank',
                    rel='noopener noreferrer',
                    style={'color': '#6A8A70', 'textDecoration': 'none'}
                ),
                ", Marmara University"
            ], style={
                'margin': '0',
                'fontSize': '0.85rem',
                'color': '#6A8A70'
            })
        ], style={
            'textAlign': 'center',
            'marginBottom': '15px'
        }),
        
        # Copyright notice
        html.Div([
            html.P(
                "© 2025 COSTBIO. All rights reserved.",
                style={
                    'margin': '0',
                    'fontSize': '0.8rem',
                    'color': '#8A9A8A'
                }
            )
        ], style={
            'textAlign': 'center'
        })
    ], style={
        'marginTop': '40px',
        'padding': '30px 20px'
    })


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
            
            # Right: Upload zone with custom file input for size validation
            html.Div([
                html.Div([
                    # Visual upload zone - clickable area
                    html.Div([
                        html.Div([
                            html.I(className="fas fa-cloud-upload-alt", style={'fontSize': '1.5rem', 'color': '#7C9885', 'marginBottom': '8px'}),
                            html.Div("Drop files or click to browse", 
                                    style={'fontSize': '0.9rem', 'fontWeight': '500', 'color': '#5A7A60'})
                        ], className="upload-zone", style={'padding': '20px', 'textAlign': 'center', 'cursor': 'pointer'}),
                    ], id='upload-click-zone', style={'cursor': 'pointer'}),

                    # Global limits exposed to browser JS via data-* attributes
                    html.Div(
                        id='global-limits-config',
                        style={'display': 'none'},
                        **{
                            'data-max-trajectory-mb': str(config.max_trajectory_file_size_mb),
                            'data-max-other-mb': str(config.max_other_file_size_mb),
                            'data-max-frames': '' if getattr(config, 'max_frames', None) is None else str(config.max_frames),
                        }
                    ),
                    
                    # Hidden dcc.Upload - we'll use this but intercept via JavaScript
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
                            'cursor': 'pointer',
                            'zIndex': 10
                        },
                        multiple=True
                    ),
                    # Store for files pending validation
                    dcc.Store(id='validated-files-store', data=[]),
                    # Store for tracking rejected files  
                    dcc.Store(id='rejected-files-store', data=[]),
                    # Dedicated file limits info box - dynamically updated based on mode
                    html.Div(id='file-size-limits-info', children=[
                        html.Div([
                            html.I(className="fas fa-info-circle", style={'marginRight': '8px', 'color': '#17a2b8'}),
                            html.Strong("File Size Limits", style={'color': '#17a2b8'})
                        ], style={'marginBottom': '10px', 'display': 'flex', 'alignItems': 'center'}),
                        html.Table([
                            html.Tbody([
                                html.Tr([
                                    html.Td("Trajectory files (.xtc/.trr):", style={'textAlign': 'left', 'paddingRight': '15px', 'paddingBottom': '6px', 'fontWeight': '500', 'whiteSpace': 'nowrap'}),
                                    html.Td(f"max {config.max_trajectory_file_size_mb} MB", style={'textAlign': 'left', 'paddingBottom': '6px'})
                                ]),
                                html.Tr([
                                    html.Td("Structure/topology files (.pdb/.gro/.top/.itp):", style={'textAlign': 'left', 'paddingRight': '15px', 'paddingBottom': '6px', 'fontWeight': '500', 'whiteSpace': 'nowrap'}),
                                    html.Td(f"max {config.max_other_file_size_mb} MB", style={'textAlign': 'left', 'paddingBottom': '6px'})
                                ]),
                                html.Tr([
                                    html.Td("Max frames/models:", style={'textAlign': 'left', 'paddingRight': '15px', 'paddingBottom': '6px', 'fontWeight': '500', 'whiteSpace': 'nowrap'}),
                                    html.Td(f"{config.max_frames}" if getattr(config, 'max_frames', None) else "no limit", style={'textAlign': 'left', 'paddingBottom': '6px'})
                                ])
                            ])
                        ], style={'width': '100%', 'fontSize': '0.85rem', 'color': '#495057', 'borderCollapse': 'collapse'})
                    ], style={
                        'marginTop': '12px',
                        'padding': '12px',
                        'backgroundColor': '#e7f3ff',
                        'border': '1px solid #b8daff',
                        'borderRadius': '6px',
                        'fontSize': '0.85rem'
                    }),
                    # Upload progress indicator (shown for large files)
                    html.Div(id='upload-progress-container', style={'display': 'none'}, children=[
                        html.Div([
                            html.I(className="fas fa-spinner fa-spin", style={'marginRight': '8px'}),
                            html.Span(id='upload-progress-text', children='Uploading...'),
                        ], style={'textAlign': 'center', 'padding': '10px', 'color': '#5A7A60'}),
                        dbc.Progress(id='upload-progress-bar', value=0, striped=True, animated=True, 
                                    style={'height': '8px', 'marginTop': '5px'})
                    ])
                ], id="upload-panel", className="upload-panel", style={'position': 'relative'}),
                # Example Data section (dynamically updated based on mode)
                # Container for button and download links
                html.Div(id="example-data-section", children=[
                    # Default content - will be updated by callback based on mode
                    html.Div([
                        html.Button([
                            html.I(className="fas fa-flask", style={'marginRight': '8px'}),
                            "Load Example Data"
                        ],
                        id="load-example-data-btn",
                        className="btn btn-outline-info btn-sm",
                        style={
                            'width': '100%',
                            'marginTop': '10px',
                            'padding': '8px 16px',
                            'fontSize': '0.85rem'
                        })
                    ], style={'textAlign': 'center'}) if (EXAMPLE_DATA_TRAJECTORY_AVAILABLE or EXAMPLE_DATA_ENSEMBLE_AVAILABLE) else html.Div(id="load-example-data-btn", style={'display': 'none'})
                ]),
                # Confirmation modal for loading example data
                dbc.Modal([
                    dbc.ModalHeader(dbc.ModalTitle([
                        html.I(className="fas fa-exclamation-triangle", style={'marginRight': '10px', 'color': '#ffc107'}),
                        "Load Example Data"
                    ], style={'fontSize': '1.1rem'})),
                    dbc.ModalBody([
                        html.P("This will clear any existing uploaded files and load example data for testing.", 
                               style={'marginBottom': '10px'}),
                        html.P([
                            html.Strong("Do you want to continue?")
                        ], style={'color': '#5A7A60'})
                    ]),
                    dbc.ModalFooter([
                        html.Button("Cancel", id="cancel-example-data-btn", n_clicks=0, style={
                            'fontSize': '0.9rem',
                            'padding': '8px 16px',
                            'backgroundColor': 'rgba(108, 117, 125, 0.1)',
                            'color': '#6c757d',
                            'border': '1px solid rgba(108, 117, 125, 0.3)',
                            'borderRadius': '5px',
                            'fontWeight': '500',
                            'cursor': 'pointer',
                            'marginRight': '10px'
                        }),
                        html.Button([
                            html.I(className="fas fa-check", style={'marginRight': '8px'}),
                            "Load Example Data"
                        ], id="confirm-load-example-btn", n_clicks=0, style={
                            'fontSize': '0.9rem',
                            'padding': '8px 16px',
                            'backgroundColor': 'rgba(23, 162, 184, 0.1)',
                            'color': '#17a2b8',
                            'border': '1px solid rgba(23, 162, 184, 0.3)',
                            'borderRadius': '5px',
                            'fontWeight': '500',
                            'cursor': 'pointer'
                        })
                    ])
                ], id="example-data-modal", is_open=False, centered=True)
            ], style={'flex': '1', 'paddingLeft': '15px'})
            
        ], style={'display': 'flex', 'gap': '15px', 'marginBottom': '15px'}),
        
        # Hidden div for callback compatibility
        html.Div(id="file-requirements-status", style={'display': 'none'}),
        
        # File rejection warning (for oversized files)
        html.Div(id="file-rejection-warning"),
        
        # File list and validation messages
        html.Div(id="file-list-display", style={'display': 'none'}),
        html.Div(id="file-validation-messages")
    ], className="panel", style={'position': 'relative', 'zIndex': 2})

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
                }),
                # Privacy setting - directly below Submit button
                html.Div([
                    dcc.Checklist(
                        id="privacy-setting",
                        options=[{
                            'label': html.Span([
                                "Make job public (visible in Job Queue)"
                            ], style={'fontSize': '0.85rem', 'color': '#666'}),
                            'value': 'public'
                        }],
                        value=[],  # Empty = unchecked = private by default
                        className="form-check",
                        style={'display': 'inline-block'}
                    ),
                    html.Div([
                        html.Small("Jobs are private by default. Bookmark your job monitoring page to track progress.", 
                                  style={'color': '#8A9A8A', 'fontSize': '0.8rem'})
                    ], style={'marginTop': '4px'})
                ], style={'marginTop': '10px', 'textAlign': 'center'})
            ], style={'flex': '1', 'paddingLeft': '15px'})
        ], style={'display': 'flex', 'gap': '15px', 'alignItems': 'flex-start', 'marginBottom': '15px'}),
        
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
                    ], className="form-group")
                ], style={'flex': '1', 'paddingLeft': '15px'})
            ], style={'display': 'flex', 'gap': '15px'})
        ], 
        id="parameters-content",
        className="panel",
        style={'display': 'none', 'marginTop': '15px'})
    ], className="panel", style={'marginBottom': '15px', 'position': 'relative', 'zIndex': 1})


def create_job_monitoring_page(job_id: str):
    """Create dedicated job monitoring page."""
    current_path = f"/monitor/{job_id}"
    # Build full URL using configured base URL or fallback to relative path
    # The client-side callback will update this dynamically with the actual browser URL
    if config.frontend_base_url:
        base = config.frontend_base_url.rstrip('/')
        full_url = f"{base}{current_path}"
    else:
        # Use relative path as safe fallback - client-side callback will update with actual URL
        full_url = current_path
    
    return html.Div([
        dcc.Location(id='monitor-url', refresh=False),
        dcc.Store(id='monitor-job-id', data=job_id),
        dcc.Store(id='monitor-dashboard-url-store'),  # Store for dashboard URL to open in new tab
        dcc.Store(id='monitor-dashboard-availability-store', data={'available': True, 'active': 0, 'max': 10}),  # Store for dashboard availability
        dcc.Interval(id='monitor-refresh-interval', interval=3000, n_intervals=0),  # Refresh every 3 seconds
        dcc.Interval(id='monitor-dashboard-availability-interval', interval=120000, n_intervals=0),  # Poll availability every 2 minutes
        
        # Job details section with header inside
        html.Div([
            # Header with navigation
            create_header(),
            
            # Bookmark reminder - URL is updated dynamically via client-side callback
            html.Div([
                html.Div([
                    html.I(className="fas fa-bookmark", style={'marginRight': '10px', 'fontSize': '0.9rem'}),
                    html.Strong("Bookmark this page! "),
                    "Save this URL to check your job status anytime:"
                ]),
                html.Div([
                    html.A(full_url, id='bookmark-url-link', href=full_url, target="_blank", 
                           style={'backgroundColor': 'rgba(255,255,255,0.3)', 'padding': '4px 8px', 'borderRadius': '4px', 
                                  'fontSize': '0.9rem', 'color': 'white', 'textDecoration': 'none', 'fontFamily': 'monospace',
                                  'wordBreak': 'break-all'})
                ], style={'marginTop': '8px'})
            ], className="bookmark-reminder"),
            
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
            ], id='monitor-dashboard-modal', className="modal", style={'display': 'none'}),
            
            # Footer
            create_footer()
        ], style={'maxWidth': '1000px', 'margin': '0 auto', 'padding': '20px'})
    ])

def create_job_queue_page():
    """Create job queue page showing all submitted jobs."""
    return html.Div([
        dcc.Location(id='queue-url', refresh=False),
        dcc.Store(id='dashboard-url-store'),  # Store for dashboard URL to open in new tab
        dcc.Store(id='dashboard-availability-store', data={'available': True, 'active': 0, 'max': 10}),  # Store for dashboard availability
        dcc.Interval(id='dashboard-availability-interval', interval=120000, n_intervals=0),  # Poll availability every 2 minutes
        
        # Queue controls
        html.Div([
            # Header with navigation
            create_header(),
            
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
                    style={
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
                )
            ], style={'textAlign': 'center', 'marginTop': '30px'}),
            
            # Footer
            create_footer()
            
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
            ], style={'textAlign': 'center', 'marginTop': '20px'}),
            
            # Footer
            create_footer()
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


def create_help_page():
    """Create help/documentation page with floating TOC sidebar."""
    content, toc = read_help_content()
    
    # Build TOC sidebar links
    toc_links = []
    for item in toc:
        indent = (item['level'] - 1) * 15  # Indent based on heading level
        toc_links.append(
            html.A(
                item['title'],
                href=f"#{item['id']}",
                style={
                    'display': 'block',
                    'padding': '6px 12px',
                    'paddingLeft': f'{12 + indent}px',
                    'color': '#5A7A60' if item['level'] == 1 else '#666',
                    'textDecoration': 'none',
                    'fontSize': '0.85rem' if item['level'] > 1 else '0.95rem',
                    'fontWeight': '500' if item['level'] == 1 else '400',
                    'borderLeft': '3px solid transparent',
                    'transition': 'all 0.2s ease'
                }
            )
        )
    
    return html.Div([
        dcc.Location(id='help-url', refresh=False),
        dcc.Store(id='help-scroll-trigger', data=0),  # Dummy store for scroll callback
        
        # Two-column layout container
        html.Div([
            # Left sidebar - Table of Contents (fixed position)
            html.Div([
                html.Div([
                    html.H5([
                        html.I(className="fas fa-list", style={'marginRight': '8px'}),
                        "Contents"
                    ], style={
                        'color': '#5A7A60',
                        'marginBottom': '15px',
                        'paddingBottom': '10px',
                        'borderBottom': '2px solid rgba(90, 122, 96, 0.2)'
                    }),
                    html.Div(toc_links, id='help-toc-links')
                ], style={
                    'position': 'sticky',
                    'top': '20px'
                })
            ], style={
                'width': '250px',
                'flexShrink': '0',
                'paddingRight': '30px',
                'borderRight': '1px solid rgba(90, 122, 96, 0.15)',
                'display': 'none'  # Hide on mobile, show on larger screens via media query
            }, className='help-toc-sidebar', id='help-toc-sidebar'),
            
            # Right content - Main documentation
            html.Div([
                # Header with navigation
                html.Div([
                    html.Div([
                        html.A(
                            [html.I(className="fas fa-arrow-left", style={'marginRight': '8px'}), "Back to Main"],
                            href="/",
                            style={
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
                        )
                    ], style={'marginBottom': '20px'}),
                    
                ]),
                
                # Markdown content
                html.Div([
                    dcc.Markdown(
                        content,
                        id='help-markdown-content',
                        dangerously_allow_html=True,  # Allow anchor tags for TOC navigation
                        style={
                            'lineHeight': '1.8',
                            'fontSize': '1rem'
                        },
                        className='help-markdown-content'
                    )
                ], style={
                    'backgroundColor': 'white',
                    'padding': '40px',
                    'borderRadius': '10px',
                    'boxShadow': '0 2px 10px rgba(0,0,0,0.08)',
                    'border': '1px solid rgba(90, 122, 96, 0.1)'
                }),
                
                # Bottom navigation
                html.Div([
                    html.A(
                        [html.I(className="fas fa-home", style={'marginRight': '8px'}), "Submit a Job"],
                        href="/",
                        style={
                            'fontSize': '0.95rem',
                            'padding': '10px 20px',
                            'display': 'inline-block',
                            'backgroundColor': '#5A7A60',
                            'color': 'white',
                            'textDecoration': 'none',
                            'borderRadius': '5px',
                            'fontWeight': '500',
                            'marginRight': '10px'
                        }
                    ),
                    html.A(
                        [html.I(className="fas fa-list-alt", style={'marginRight': '8px'}), "View Job Queue"],
                        href="/queue",
                        style={
                            'fontSize': '0.95rem',
                            'padding': '10px 20px',
                            'display': 'inline-block',
                            'backgroundColor': 'rgba(90, 122, 96, 0.1)',
                            'color': '#5A7A60',
                            'textDecoration': 'none',
                            'border': '1px solid rgba(90, 122, 96, 0.3)',
                            'borderRadius': '5px',
                            'fontWeight': '500'
                        }
                    )
                ], style={'textAlign': 'center', 'marginTop': '40px'})
            ], style={
                'flex': '1',
                'minWidth': '0',
                'paddingLeft': '30px'
            }, className='help-main-content')
        ], style={
            'display': 'flex',
            'maxWidth': '1200px',
            'margin': '0 auto',
            'padding': '20px',
            'minHeight': '100vh'
        }),
        
        # Footer (outside the flex container for full width)
        html.Div([
            create_footer()
        ], style={'maxWidth': '1200px', 'margin': '0 auto', 'padding': '0 20px'})
    ])


# Clientside callback for TOC scroll navigation on help page
app.clientside_callback(
    """
    function(hash) {
        // Handle hash changes for TOC navigation
        var targetHash = hash || window.location.hash;
        if (targetHash) {
            var elementId = targetHash.replace('#', '');
            // Small delay to ensure DOM is fully rendered
            setTimeout(function() {
                var element = document.getElementById(elementId);
                if (element) {
                    element.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            }, 100);
        }
        return 0;  // Return dummy value
    }
    """,
    Output('help-scroll-trigger', 'data'),
    Input('help-url', 'hash'),
    prevent_initial_call=False
)

# Client-side callback to update bookmark URL with actual browser URL
# This ensures the bookmark link always shows the correct URL regardless of server-side config
app.clientside_callback(
    """
    function(pathname) {
        // Get the full browser URL (origin + pathname)
        var fullUrl = window.location.origin + pathname;
        return [fullUrl, fullUrl];
    }
    """,
    [Output('bookmark-url-link', 'children'),
     Output('bookmark-url-link', 'href')],
    Input('monitor-url', 'pathname'),
    prevent_initial_call=False
)


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
    logger.info(f"display_page called with pathname: {repr(pathname)}")
    
    # Normalize pathname - strip trailing slashes for consistent matching
    if pathname and pathname != '/':
        pathname = pathname.rstrip('/')
    
    if pathname is None or pathname == '/':
        # Generate a unique session ID for this page load
        session_id = secrets.token_hex(16)
        
        # Main page
        return html.Div([
            dcc.Store(id='uploaded-files-store', data=[]),
            dcc.Store(id='file-role-conflicts', data={'structure': [], 'topology': []}),
            dcc.Store(id='session-id-store', data=session_id),  # Session ID for temp file storage
            dcc.Store(id='gromacs-versions-store', data=None),  # Store for available GROMACS versions
            dcc.Store(id='tab-focus-trigger', data=0),  # Trigger for tab focus refresh
            dcc.Store(id='tutorial-modal-helper', data=None),  # Helper for tutorial modal auto-confirm
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
            # Hidden GROMACS version selector - always present for callback consistency
            html.Div([
                dcc.Dropdown(
                    id='gromacs-version-selector',
                    options=[],
                    value=None,
                    placeholder='Select GROMACS version...'
                )
            ], style={'display': 'none'}, id='gromacs-version-selector-hidden'),
            
            html.Div([
                create_header(),
                html.Div([
                    html.I(className="fas fa-info-circle", style={'marginRight': '8px'}),
                    "This website is free and open to all users and there is no login requirement."
                ], style={
                    'textAlign': 'center',
                    'padding': '12px 20px',
                    'backgroundColor': 'rgba(90, 122, 96, 0.08)',
                    'color': '#5A7A60',
                    'borderRadius': '8px',
                    'fontSize': '0.95rem',
                    'marginBottom': '15px',
                    'border': '1px solid rgba(90, 122, 96, 0.15)'
                }),
                create_input_mode_selector(),
                create_file_upload_section(),
                create_submit_section(),
                # Submission status area
                html.Div(id="submission-status", children=[], style={'marginTop': '12px'}),
                # Footer
                create_footer()
            ], style={'maxWidth': '1200px', 'margin': '0 auto'})
        ])
    elif pathname.startswith('/monitor/'):
        # Job monitoring page
        job_id = pathname.split('/')[-1]
        logger.info(f"Routing to monitor page for job: {job_id}")
        return create_job_monitoring_page(job_id)
    elif pathname == '/queue':
        # Job queue page
        return create_job_queue_page()
    elif pathname.startswith('/results/'):
        # Results viewing page
        job_id = pathname.split('/')[-1]
        logger.info(f"Routing to results page for job: {job_id}")
        return create_results_page(job_id)
    elif pathname.startswith('/dashboard/'):
        # Dashboard viewing page with readiness check
        job_id = pathname.split('/')[-1]
        logger.info(f"Routing to dashboard page for job: {job_id}")
        return create_dashboard_page(job_id)
    elif pathname == '/help':
        # Help/documentation page
        return create_help_page()
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
                    "Exactly ONE multi-model PDB file"
                ], style={'fontSize': '0.9rem', 'marginBottom': '4px'}),
                html.Div([
                    html.I(className="fas fa-lightbulb", style={'marginRight': '5px', 'color': '#ffc107'}),
                    "The PDB file should contain all conformations (MODEL/ENDMDL records). ",
                    "The first model will be used as the reference structure."
                ], style={'fontSize': '0.8rem', 'color': '#666', 'marginBottom': '8px', 'fontStyle': 'italic'}),
                
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
                        html.Li(f"Trajectory (.xtc/.trr, max {config.max_trajectory_file_size_mb}MB)", style={'margin': '2px 0'}),
                        html.Li("Topology (.top)", style={'margin': '2px 0'})
                    ], style={'fontSize': '0.85rem', 'marginTop': '5px', 'marginBottom': '5px', 'paddingLeft': '20px'})
                ], style={'fontSize': '0.9rem', 'marginBottom': '5px'}),

                html.Div([
                    html.I(className="fas fa-exclamation-triangle", style={'marginRight': '6px', 'color': '#ffc107'}),
                    html.Strong("Topology Includes: ", style={'color': '#856404'}),
                    html.Span("If your .top file uses ", style={'color': '#856404'}),
                    html.Code("#include", style={'backgroundColor': '#fff3cd', 'padding': '1px 4px', 'borderRadius': '3px'}),
                    html.Span(" directives for .itp files (force field parameters, position restraints), ", style={'color': '#856404'}),
                    html.Strong("upload those files too", style={'color': '#856404'}),
                    html.Span(". Missing includes will cause job failures.", style={'color': '#856404'})
                ], style={
                    'fontSize': '0.85rem', 
                    'backgroundColor': '#fff3cd', 
                    'border': '1px solid #ffc107',
                    'borderRadius': '5px',
                    'padding': '8px 10px',
                    'marginTop': '8px'
                }),
                
                html.Div([
                    html.I(className="fas fa-folder-open", style={'marginRight': '6px', 'color': '#17a2b8'}),
                    html.Strong("Custom Force Fields: ", style={'color': '#0c5460'}),
                    html.Span("You can upload custom force field folders as ", style={'color': '#0c5460'}),
                    html.Code(".zip", style={'backgroundColor': '#d1ecf1', 'padding': '1px 4px', 'borderRadius': '3px'}),
                    html.Span(" files. The zip should contain the force field directory (e.g., ", style={'color': '#0c5460'}),
                    html.Code("myff.ff/", style={'backgroundColor': '#d1ecf1', 'padding': '1px 4px', 'borderRadius': '3px'}),
                    html.Span(").", style={'color': '#0c5460'})
                ], style={
                    'fontSize': '0.85rem', 
                    'backgroundColor': '#d1ecf1', 
                    'border': '1px solid #17a2b8',
                    'borderRadius': '5px',
                    'padding': '8px 10px',
                    'marginTop': '8px'
                }),
                
                # GROMACS version selector
                html.Div([
                    html.Label([
                        html.I(className="fas fa-cogs", style={'marginRight': '6px'}),
                        "GROMACS Version ",
                        html.Small("(for topology compatibility)", style={'color': '#8A9A8A', 'fontWeight': 'normal'})
                    ], style={'fontWeight': '500', 'color': '#5A7A60', 'marginBottom': '5px', 'display': 'block'}),
                    html.Div(id='gromacs-version-dropdown-container', children=[
                        dcc.Dropdown(
                            id='gromacs-version-display',
                            options=[],
                            value=None,
                            placeholder='Loading available versions...',
                            clearable=False,
                            style={'fontSize': '0.9rem'}
                        ),
                        html.Div(id='gromacs-version-warning', style={'marginTop': '5px'})
                    ], style={'position': 'relative', 'zIndex': '1000'})
                ], style={'marginTop': '12px'})
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
    Output('file-size-limits-info', 'children'),
    [Input('input-mode-selector', 'value')]
)
def update_file_size_limits_info(mode):
    """Update file size limits info box based on selected mode."""
    header = html.Div([
        html.I(className="fas fa-info-circle", style={'marginRight': '8px', 'color': '#17a2b8'}),
        html.Strong("File Size Limits", style={'color': '#17a2b8'})
    ], style={'marginBottom': '10px', 'display': 'flex', 'alignItems': 'center'})
    
    # Common table style for consistent layout
    table_style = {
        'width': '100%',
        'fontSize': '0.85rem',
        'color': '#495057',
        'borderCollapse': 'collapse'
    }
    label_cell_style = {
        'textAlign': 'left',
        'paddingRight': '15px',
        'paddingBottom': '6px',
        'fontWeight': '500',
        'whiteSpace': 'nowrap'
    }
    value_cell_style = {
        'textAlign': 'left',
        'paddingBottom': '6px'
    }
    
    if mode == 'ensemble':
        # In ensemble mode, PDB files get trajectory-class limit
        content = html.Table([
            html.Tbody([
                html.Tr([
                    html.Td("Ensemble PDB files:", style=label_cell_style),
                    html.Td(f"max {config.max_trajectory_file_size_mb} MB", style=value_cell_style)
                ]),
                html.Tr([
                    html.Td("Max frames/models:", style=label_cell_style),
                    html.Td(f"{config.max_frames}" if getattr(config, 'max_frames', None) else "no limit", style=value_cell_style)
                ])
            ])
        ], style=table_style)
    else:
        # Trajectory mode - show separate limits
        content = html.Table([
            html.Tbody([
                html.Tr([
                    html.Td("Trajectory files (.xtc/.trr):", style=label_cell_style),
                    html.Td(f"max {config.max_trajectory_file_size_mb} MB", style=value_cell_style)
                ]),
                html.Tr([
                    html.Td("Structure/topology files (.pdb/.gro/.top/.itp):", style=label_cell_style),
                    html.Td(f"max {config.max_other_file_size_mb} MB", style=value_cell_style)
                ]),
                html.Tr([
                    html.Td("Max frames/models:", style=label_cell_style),
                    html.Td(f"{config.max_frames}" if getattr(config, 'max_frames', None) else "no limit", style=value_cell_style)
                ])
            ])
        ], style=table_style)
    
    return [header, content]

@app.callback(
    [Output('file-list-display', 'children'),
     Output('file-list-display', 'style'),
     Output('file-validation-messages', 'children'),
     Output('uploaded-files-store', 'data'),
     Output('submit-job-btn', 'disabled'),
     Output('submit-status-message', 'children'),
     Output('submit-status-message', 'style'),
     Output('upload-progress-container', 'style'),
     Output('upload-progress-text', 'children'),
     Output('upload-progress-bar', 'value'),
     Output('file-rejection-warning', 'children')],
    [Input('upload-files', 'contents'),
     Input('input-mode-selector', 'value')],
    [State('upload-files', 'filename'),
     State('uploaded-files-store', 'data'),
     State('session-id-store', 'data')]
)
def handle_file_upload(contents, input_mode, filenames, stored_files, session_id):
    """Handle file upload and validation. Files are stored server-side, only metadata in browser."""
    # Default progress style (hidden)
    progress_hidden = {'display': 'none'}
    progress_shown = {'display': 'block', 'marginTop': '10px', 'padding': '10px', 'backgroundColor': '#f8f9fa', 'borderRadius': '5px'}

    # Important: `upload-files.contents` can be programmatically cleared (e.g., after a remove click)
    # to allow re-uploading the same file. That clear triggers this callback, and the `stored_files`
    # State arriving here can be stale (race with the remove callback). If we write it back out,
    # we can effectively undo the removal.
    ctx = callback_context
    
    # Check what triggered this callback
    triggered_id = ctx.triggered[0]['prop_id'].split('.')[0] if ctx.triggered else None
    
    # If mode changed (not a file upload), let update_file_display_on_removal handle it
    if triggered_id == 'input-mode-selector':
        return (no_update, no_update, no_update, no_update, no_update, no_update,
                no_update, no_update, no_update, no_update, no_update)
    
    if not contents:
        # If there are already stored files, do not touch outputs here.
        # The UI should be driven by `uploaded-files-store` and updated via
        # `update_file_display_on_removal`.
        if stored_files:
            return (no_update, no_update, no_update, no_update, no_update, no_update,
                    no_update, no_update, no_update, no_update, no_update)

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
        }, progress_hidden, '', 0, []  # Empty rejection warning
    
    if not isinstance(contents, list):
        contents = [contents]
        filenames = [filenames]
    
    # Use default session ID if not available
    if not session_id:
        session_id = secrets.token_hex(16)
    
    files = stored_files.copy() if stored_files else []
    validation_messages = []
    rejected_files = []  # Track files rejected for size
    # Safety cap to avoid excessive memory usage during base64 decode (derived from configured limits)
    hard_limit_mb = max(config.max_trajectory_file_size_mb, config.max_other_file_size_mb)
    HARD_FILE_SIZE_LIMIT = hard_limit_mb * 1024 * 1024
    
    for content, filename in zip(contents, filenames):
        # Decode file content
        content_type, content_string = content.split(',')
        file_size = len(base64.b64decode(content_string))
        
        # First check: hard safety cap (should normally match your configured limits)
        if file_size > HARD_FILE_SIZE_LIMIT:
            rejected_files.append({
                'filename': filename,
                'size_mb': file_size / 1024 / 1024
            })
            logger.warning(
                f"Rejected file {filename}: {file_size/1024/1024:.1f}MB exceeds {hard_limit_mb}MB safety cap"
            )
            continue
        
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
        
        # In ensemble mode, only PDB files are accepted
        if input_mode == 'ensemble' and file_type.value != 'pdb':
            validation_messages.append(
                html.Div([
                    html.I(className="fas fa-times-circle", style={'marginRight': '8px'}),
                    f"Only PDB files are accepted in Ensemble mode. '{filename}' ({file_type.value.upper()}) was rejected."
                ], className="alert alert-danger")
            )
            continue
        
        # Validate file size based on type (type-specific limits still apply)
        # Ensemble PDB files are treated as trajectory-class (larger limit) since they contain trajectory data
        is_trajectory = extension in ['xtc', 'trr']
        is_ensemble_pdb = (input_mode == 'ensemble' and extension == 'pdb')
        use_trajectory_limit = is_trajectory or is_ensemble_pdb
        max_size = (config.max_trajectory_file_size_mb if use_trajectory_limit else config.max_other_file_size_mb) * 1024 * 1024
        max_size_label = f"{config.max_trajectory_file_size_mb}MB" if use_trajectory_limit else f"{config.max_other_file_size_mb}MB"
        
        # Descriptive file type label for error messages
        if is_ensemble_pdb:
            file_type_label = 'ensemble PDB'
        elif is_trajectory:
            file_type_label = 'trajectory'
        else:
            file_type_label = 'structure/topology'
        
        if file_size > max_size:
            validation_messages.append(
                html.Div([
                    html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                    f"File {filename} is too large ({file_size/1024/1024:.1f}MB). Maximum size for {file_type_label} files is {max_size_label}."
                ], className="alert alert-danger")
            )
            continue
        
        # Save file to server-side temporary storage
        try:
            temp_file_id = save_temp_file(content_string, filename, session_id)
        except Exception as e:
            logger.error(f"Failed to save temp file {filename}: {e}")
            validation_messages.append(
                html.Div([
                    html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                    f"Failed to save file {filename}. Please try again."
                ], className="alert alert-danger")
            )
            continue
        
        # Store only metadata in browser (NOT the file content!)
        file_data = {
            'filename': filename,
            'temp_file_id': temp_file_id,  # Reference to server-side file
            'session_id': session_id,
            'source': 'upload',  # Flag to indicate user upload (not example data)
            'size_bytes': file_size,
            'file_type': file_type.value,
            'upload_time': datetime.utcnow().isoformat(),
            'uploaded_for_mode': input_mode,  # Track which mode this file was uploaded for
            'model_count': None,  # Will be set for PDB files in ensemble mode
            'role': get_default_role(file_type.value, input_mode)  # Default role based on file type
        }
        
        # Validate PDB files for multi-model content in ensemble mode
        if file_type.value == 'pdb' and input_mode == 'ensemble':
            temp_path = get_temp_file_path(temp_file_id, session_id)
            pdb_validation = validate_pdb_multimodel(temp_path, input_mode)
            
            if pdb_validation['error']:
                validation_messages.append(
                    html.Div([
                        html.I(className="fas fa-times-circle", style={'marginRight': '8px'}),
                        f"{filename}: {pdb_validation['error']}"
                    ], className="alert alert-danger")
                )
                # Delete the invalid file and skip
                delete_temp_file(temp_file_id, session_id)
                continue
            
            if pdb_validation['warning']:
                validation_messages.append(
                    html.Div([
                        html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                        f"{filename}: {pdb_validation['warning']}"
                    ], className="alert alert-warning")
                )
            elif pdb_validation['model_count'] > 1:
                # Success message showing model count
                validation_messages.append(
                    html.Div([
                        html.I(className="fas fa-check-circle", style={'marginRight': '8px'}),
                        f"{filename}: Found {pdb_validation['model_count']} models for ensemble analysis"
                    ], className="alert alert-success")
                )
            
            # Store model count in file metadata
            file_data['model_count'] = pdb_validation['model_count']
            file_data['is_multimodel'] = pdb_validation['is_multimodel']
        
        # Check for duplicates
        if not any(f['filename'] == filename for f in files):
            files.append(file_data)
    
    # Filter files by current mode for display
    files_for_current_mode = [f for f in files if f.get('uploaded_for_mode', 'trajectory') == input_mode]
    files_for_other_mode = [f for f in files if f.get('uploaded_for_mode', 'trajectory') != input_mode]
    
    # Create hidden files indicator if there are files for other mode
    hidden_files_indicator = None
    if files_for_other_mode:
        other_mode_name = 'Trajectory Analysis' if input_mode == 'ensemble' else 'PDB Ensemble'
        file_count = len(files_for_other_mode)
        hidden_files_indicator = html.Div([
            html.I(className="fas fa-eye-slash", style={'marginRight': '8px'}),
            f"You have {file_count} file{'s' if file_count > 1 else ''} uploaded for {other_mode_name} mode (hidden)"
        ], style={
            'padding': '8px 12px',
            'backgroundColor': 'rgba(108, 117, 125, 0.1)',
            'border': '1px solid rgba(108, 117, 125, 0.2)',
            'borderRadius': '5px',
            'fontSize': '0.85rem',
            'color': '#6c757d',
            'marginTop': '10px'
        })
    
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
    
    # Detect role conflicts for visual feedback
    conflicts = detect_role_conflicts(files, input_mode)
    has_topology_conflict = len(conflicts.get('topology', [])) > 1
    has_structure_conflict = len(conflicts.get('structure', [])) > 1
    
    # Determine which structure file is selected (first one by default, or the one marked)
    selected_structure_key = None
    if conflicts.get('structure'):
        # Check if any file is explicitly marked as selected
        for f in files_for_current_mode:
            if f.get('file_type') in ['pdb', 'gro']:
                f_key = f.get('temp_file_id') or f.get('example_path') or f.get('filename')
                if f.get('is_selected_structure', False):
                    selected_structure_key = f_key
                    break
        # If none explicitly selected, default to first structure file
        if not selected_structure_key and conflicts.get('structure'):
            selected_structure_key = conflicts['structure'][0]
    
    # Create table rows for current mode's files only
    file_list_items = [table_header]
    for idx, file_data in enumerate(files_for_current_mode):
        size_mb = file_data['size_bytes'] / (1024 * 1024)
        file_type = file_data['file_type']
        # Use temp_file_id or example_path as unique key for reliable removal
        file_key = file_data.get('temp_file_id') or file_data.get('example_path') or f"{file_data['filename']}_{idx}"
        
        # Check if this is the selected structure file
        is_selected_structure = (file_key == selected_structure_key)
        
        # Create purpose cell (dropdown, radio button, or static text)
        purpose_cell = create_purpose_cell(file_data, file_key, input_mode, conflicts, is_selected_structure)
        
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
                purpose_cell,
                html.Div(
                    f"{size_mb:.1f} MB",
                    style={'flex': '0.6', 'fontSize': '0.8rem', 'color': '#6c757d', 'textAlign': 'right'}
                ),
                html.Div([
                    html.Button(
                        html.I(className="fas fa-trash", id={'type': 'remove-icon', 'index': file_key}),
                        id={'type': 'remove-file', 'index': file_key},
                        n_clicks=0,
                        className='remove-file-btn',
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
            ], id={'type': 'file-row', 'index': file_key}, style={
                'display': 'flex',
                'alignItems': 'center',
                'padding': '8px 12px',
                'borderBottom': '1px solid #e9ecef',
                'backgroundColor': '#ffffff',
                'transition': 'all 0.3s ease',
            }, className='file-table-row')
        )
    
    # Add conflict warning messages
    if has_structure_conflict:
        validation_messages.append(
            html.Div([
                html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px', 'color': '#dc3545'}),
                html.Strong("Multiple structure files: "),
                f"You have uploaded {len(conflicts['structure'])} PDB/GRO files. Only one can be used as the reference structure. ",
                "Select one file to use and remove the others, or they will be discarded upon submission."
            ], className="alert alert-warning", style={'marginTop': '10px'})
        )
    
    if has_topology_conflict:
        validation_messages.append(
            html.Div([
                html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px', 'color': '#dc3545'}),
                html.Strong("Role conflict: "),
                f"Multiple files assigned as Topology ({len(conflicts['topology'])} files). Please use the dropdown to set one as 'Include file'."
            ], className="alert alert-danger", style={'marginTop': '10px'})
        )
    
    # Validation based on input mode - only check files for current mode
    if input_mode == 'ensemble':
        # For ensemble mode, only need a multi-model PDB file
        has_pdb = any(f['file_type'] == 'pdb' for f in files_for_current_mode)
        required_files_met = has_pdb
        
        # Add file requirements status message
        if files_for_current_mode:
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
        has_structure = any(f['file_type'] in ['gro', 'pdb'] for f in files_for_current_mode)
        has_trajectory = any(f['file_type'] in ['xtc', 'trr'] for f in files_for_current_mode) 
        has_topology = any(f['file_type'] in ['tpr', 'top'] for f in files_for_current_mode)
        required_files_met = has_structure and has_trajectory and has_topology
        
        # Add file requirements status message
        if files_for_current_mode:
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
    file_list_inner = html.Div(
        file_list_items,
        style={
            'border': '1px solid #dee2e6',
            'borderRadius': '5px',
            'backgroundColor': '#ffffff',
            'overflow': 'hidden',
            'marginBottom': '10px' if hidden_files_indicator else '15px'
        }
    )
    
    # Combine file list with hidden files indicator
    file_list_container = html.Div([
        file_list_inner,
        hidden_files_indicator
    ] if hidden_files_indicator else [file_list_inner])
    
    # Calculate total size for progress info
    total_size_bytes = sum(f.get('size_bytes', 0) for f in files)
    # Show progress indicator for files > 10MB
    large_files_exist = any(f.get('size_bytes', 0) > 10 * 1024 * 1024 for f in files)
    
    # Show progress info for large file uploads
    if large_files_exist:
        progress_text = f"Processed {len(files)} file(s) ({total_size_bytes / 1024 / 1024:.1f} MB total)"
    else:
        progress_text = ""
    
    # Hide progress after upload is complete
    progress_style = {'display': 'none'}
    
    # Build rejection warning for files over the configured safety cap
    rejection_warning = []
    if rejected_files:
        rejection_items = [
            html.Li(f"{rf['filename']} ({rf['size_mb']:.1f} MB)") 
            for rf in rejected_files
        ]
        rejection_warning = html.Div([
            html.Div([
                html.I(className="fas fa-ban", style={
                    'marginRight': '12px', 
                    'color': '#dc3545', 
                    'fontSize': '1.5rem',
                    'marginTop': '2px'
                }),
                html.Div([
                    html.Strong(
                        f"File(s) rejected - exceeds {hard_limit_mb}MB size cap:",
                        style={'fontSize': '1rem'}
                    ),
                    html.Ul(rejection_items, style={
                        'margin': '8px 0', 
                        'paddingLeft': '20px',
                        'fontSize': '0.95rem'
                    }),
                    html.Div([
                        html.I(className="fas fa-lightbulb", style={'marginRight': '6px', 'color': '#856404'}),
                        "Tip: Reduce trajectory size by extracting fewer frames or splitting into smaller parts."
                    ], style={'fontSize': '0.85rem', 'color': '#856404', 'marginTop': '5px'})
                ])
            ], style={'display': 'flex', 'alignItems': 'flex-start'})
        ], className="alert alert-danger", style={
            'marginBottom': '15px',
            'padding': '15px',
            'borderRadius': '8px',
            'border': '2px solid #f5c6cb'
        })
    
    return file_list_container, style, validation_messages, files, submit_disabled, submit_message, submit_style, progress_style, progress_text, 100, rejection_warning

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

# =============================================================================
# EXAMPLE DATA CALLBACKS
# =============================================================================

@app.callback(
    Output('example-data-section', 'children'),
    [Input('input-mode-selector', 'value')],
    prevent_initial_call=False
)
def update_example_data_section(input_mode):
    """Update example data section based on selected mode."""
    mode = input_mode or 'trajectory'
    
    # Determine availability and path for current mode
    if mode == 'ensemble':
        data_available = EXAMPLE_DATA_ENSEMBLE_AVAILABLE
        example_path = config.example_data_path_ensemble
        mode_label = "Ensemble"
    else:
        data_available = EXAMPLE_DATA_TRAJECTORY_AVAILABLE
        example_path = config.example_data_path_trajectory
        mode_label = "Trajectory"
    
    if not data_available:
        # No example data for this mode - hide the section
        return html.Div(id="load-example-data-btn", style={'display': 'none'})
    
    # Get list of files and calculate total size
    example_files = _get_example_files(example_path)
    total_size_bytes = 0
    for filename in example_files:
        file_path = os.path.join(example_path, filename)
        if os.path.exists(file_path):
            total_size_bytes += os.path.getsize(file_path)
    total_size_mb = total_size_bytes / (1024 * 1024)
    
    return html.Div([
        # Load Example Data button
        html.Div([
            html.Button([
                html.I(className="fas fa-flask", style={'marginRight': '8px'}),
                f"Load {mode_label} Example Data"
            ],
            id="load-example-data-btn",
            className="btn btn-outline-info btn-sm",
            style={
                'width': '100%',
                'marginTop': '10px',
                'padding': '8px 16px',
                'fontSize': '0.85rem'
            })
        ], style={'textAlign': 'center'}),
        
        # Download zip link
        html.Div([
            html.A([
                html.I(className="fas fa-file-archive", style={'marginRight': '6px'}),
                f"Download example files ({total_size_mb:.1f} MB)"
            ],
            href=f"/download-example/{mode}",
            target="_blank",
            style={
                'display': 'inline-block',
                'fontSize': '0.8rem',
                'color': '#5A7A60',
                'textDecoration': 'none',
                'marginTop': '8px'
            })
        ], style={'textAlign': 'center'}) if example_files else html.Div()
    ])


@app.callback(
    Output('example-data-modal', 'is_open'),
    [Input('load-example-data-btn', 'n_clicks'),
     Input('cancel-example-data-btn', 'n_clicks'),
     Input('confirm-load-example-btn', 'n_clicks')],
    [State('example-data-modal', 'is_open')],
    prevent_initial_call=True
)
def toggle_example_data_modal(load_clicks, cancel_clicks, confirm_clicks, is_open):
    """Toggle the example data confirmation modal. Skip modal in tutorial mode."""
    ctx = callback_context
    if not ctx.triggered:
        return is_open
    
    triggered_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    if triggered_id == 'load-example-data-btn':
        # Guard: Only open if button was actually clicked (n_clicks > 0)
        # When button is recreated by mode change, n_clicks is None or 0
        if load_clicks and load_clicks > 0:
            return True  # Open modal (will be auto-closed by clientside if in tutorial mode)
        return is_open
    elif triggered_id in ['cancel-example-data-btn', 'confirm-load-example-btn']:
        return False  # Close modal
    
    return is_open


# Clientside callback to auto-confirm example data loading in tutorial mode
# This detects when modal opens and immediately clicks confirm if tutorial is active
app.clientside_callback(
    """
    function(is_open) {
        // Check if tutorial is active and modal just opened
        if (is_open && window.grinnTutorialActive) {
            console.log('[Tutorial] Auto-confirming example data load (skipping modal)');
            // Small delay to ensure modal is rendered, then trigger confirm
            setTimeout(function() {
                var confirmBtn = document.getElementById('confirm-load-example-btn');
                if (confirmBtn) {
                    confirmBtn.click();
                }
            }, 50);
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output('tutorial-modal-helper', 'data'),  # Dummy output
    Input('example-data-modal', 'is_open'),
    prevent_initial_call=True
)


@app.callback(
    [Output('uploaded-files-store', 'data', allow_duplicate=True),
     Output('file-rejection-warning', 'children', allow_duplicate=True),
     Output('privacy-setting', 'value', allow_duplicate=True)],
    [Input('confirm-load-example-btn', 'n_clicks')],
    [State('session-id-store', 'data'),
     State('input-mode-selector', 'value')],
    prevent_initial_call=True
)
def load_example_data(n_clicks, session_id, input_mode):
    """Load example data files from configured path based on current mode.
    
    Example data files are NOT copied to temp storage. Instead, metadata stores
    the original file path with source='example'. This avoids session expiry issues
    and reduces disk I/O.
    
    Example data jobs are automatically set to public for demonstration purposes.
    """
    mode = input_mode or 'trajectory'
    
    # Determine availability and path for current mode
    if mode == 'ensemble':
        data_available = EXAMPLE_DATA_ENSEMBLE_AVAILABLE
        example_data_dir = config.example_data_path_ensemble
    else:
        data_available = EXAMPLE_DATA_TRAJECTORY_AVAILABLE
        example_data_dir = config.example_data_path_trajectory
    
    if not n_clicks or not data_available or not example_data_dir:
        return no_update, no_update, no_update
    
    # Note: We don't clear session files here since example data doesn't use temp storage.
    # The uploaded-files-store will be completely replaced with example data below.
    
    # Read files from example data path
    example_files = []
    rejected_files = []
    
    try:
        for filename in os.listdir(example_data_dir):
            file_path = os.path.join(example_data_dir, filename)
            if not os.path.isfile(file_path):
                continue
            
            # Detect file type
            ext = os.path.splitext(filename)[1].lower().lstrip('.')
            file_type = None
            for ft in FileType:
                if ext == ft.value or (ext in ['xtc', 'trr'] and ft.value in ['xtc', 'trr']):
                    file_type = ft.value
                    break
            
            if not file_type:
                # Skip unknown file types
                logger.warning(f"Skipping unknown file type: {filename}")
                continue
            
            # Get file size
            size_bytes = os.path.getsize(file_path)
            size_mb = size_bytes / (1024 * 1024)
            
            # Validate file size - ensemble PDB files get trajectory limit
            is_trajectory = ext in ['xtc', 'trr']
            is_ensemble_pdb = (input_mode == 'ensemble' and ext == 'pdb')
            use_trajectory_limit = is_trajectory or is_ensemble_pdb
            max_size_mb = config.max_trajectory_file_size_mb if use_trajectory_limit else config.max_other_file_size_mb
            
            # Descriptive kind label
            if is_ensemble_pdb:
                kind_label = 'ensemble PDB'
            elif is_trajectory:
                kind_label = 'trajectory'
            else:
                kind_label = 'structure/topology'
            
            if size_mb > max_size_mb:
                rejected_files.append({
                    'filename': filename,
                    'size_mb': size_mb,
                    'limit_mb': max_size_mb,
                    'kind': kind_label
                })
                continue
            
            # Determine file role based on mode and file type
            if mode == 'ensemble' and ext == 'pdb':
                file_role = 'ensemble_pdb'
            elif ext == 'pdb':
                file_role = 'structure'
            elif ext in ['xtc', 'trr']:
                file_role = 'trajectory'
            elif ext in ['gro', 'top', 'tpr']:
                file_role = 'topology'
            else:
                file_role = 'other'
            
            # Build file metadata - store source path instead of temp file
            # This bypasses temp storage entirely for example data
            example_files.append({
                'filename': filename,
                'example_path': file_path,  # Direct path to example file
                'source': 'example',  # Flag to indicate example data (not user upload)
                'size_bytes': size_bytes,
                'file_type': file_type,
                'upload_time': datetime.now().isoformat(),
                'uploaded_for_mode': mode,
                'role': file_role
            })
            
            logger.info(f"Loaded example file: {filename} ({size_mb:.1f} MB)")
    
    except Exception as e:
        logger.error(f"Error loading example data: {e}")
        return [], html.Div([
            html.Div([
                html.I(className="fas fa-exclamation-circle", style={'marginRight': '10px', 'color': '#dc3545'}),
                f"Error loading example data: {str(e)}"
            ], className="alert alert-danger")
        ]), no_update
    
    # Build rejection warning if any files were rejected
    rejection_warning = []
    if rejected_files:
        rejection_items = [
            html.Li(f"{rf['filename']} ({rf['size_mb']:.1f} MB) - limit: {rf['limit_mb']}MB ({rf['kind']})")
            for rf in rejected_files
        ]
        rejection_warning = html.Div([
            html.Div([
                html.I(className="fas fa-exclamation-triangle", style={'marginRight': '10px', 'color': '#ffc107'}),
                html.Div([
                    html.Strong("Some example files were skipped (exceed size limit):"),
                    html.Ul(rejection_items, style={'margin': '8px 0', 'paddingLeft': '20px', 'fontSize': '0.9rem'})
                ])
            ], style={'display': 'flex', 'alignItems': 'flex-start'})
        ], className="alert alert-warning", style={'marginBottom': '15px', 'padding': '15px', 'borderRadius': '8px'})
    
    logger.info(f"Loaded {len(example_files)} example files")
    # Example data jobs are automatically set to public for demonstration purposes
    return example_files, rejection_warning, ['public']


# Separate callback to update display when files are removed or mode changes
@app.callback(
    [Output('file-list-display', 'children', allow_duplicate=True),
     Output('file-list-display', 'style', allow_duplicate=True),
     Output('file-validation-messages', 'children', allow_duplicate=True),
     Output('submit-job-btn', 'disabled', allow_duplicate=True),
     Output('submit-status-message', 'children', allow_duplicate=True),
     Output('submit-status-message', 'style', allow_duplicate=True)],
    [Input('uploaded-files-store', 'data'),
     Input('input-mode-selector', 'value')],
    prevent_initial_call=True
)
def update_file_display_on_removal(stored_files, input_mode):
    """Update file display when files are removed from store or mode changes."""
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
    
    # Filter files by current mode for display
    files_for_current_mode = [f for f in files if f.get('uploaded_for_mode', 'trajectory') == input_mode]
    files_for_other_mode = [f for f in files if f.get('uploaded_for_mode', 'trajectory') != input_mode]
    
    # Create hidden files indicator if there are files from other mode
    hidden_files_indicator = None
    if files_for_other_mode:
        other_mode_name = 'Ensemble' if input_mode == 'trajectory' else 'Trajectory'
        file_count = len(files_for_other_mode)
        hidden_files_indicator = html.Div([
            html.I(className="fas fa-eye-slash", style={'marginRight': '8px', 'color': '#6c757d'}),
            f"{file_count} file{'s' if file_count > 1 else ''} hidden (uploaded for {other_mode_name} mode)"
        ], style={
            'color': '#6c757d',
            'fontSize': '0.85rem',
            'fontStyle': 'italic',
            'textAlign': 'center',
            'padding': '8px',
            'backgroundColor': '#f8f9fa',
            'borderRadius': '4px',
            'marginBottom': '10px'
        })
    
    # Check if any files for current mode
    if not files_for_current_mode:
        # No files for current mode - show empty state with indicator
        empty_display = []
        if hidden_files_indicator:
            empty_display.append(hidden_files_indicator)
        
        return empty_display if empty_display else [], {'display': 'block' if hidden_files_indicator else 'none'}, [], True, [
            html.I(className="fas fa-info-circle", style={'marginRight': '8px'}),
            f"Upload required files for {input_mode.title()} mode to enable analysis"
        ], {
            'color': '#8A9A8A', 
            'fontStyle': 'italic',
            'textAlign': 'center'
        }
    
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
    
    # Detect role conflicts for visual feedback
    conflicts = detect_role_conflicts(files, input_mode)
    has_topology_conflict = len(conflicts.get('topology', [])) > 1
    has_structure_conflict = len(conflicts.get('structure', [])) > 1
    
    # Determine which structure file is selected (first one by default, or the one marked)
    selected_structure_key = None
    if conflicts.get('structure'):
        # Check if any file is explicitly marked as selected
        for f in files_for_current_mode:
            if f.get('file_type') in ['pdb', 'gro']:
                f_key = f.get('temp_file_id') or f.get('example_path') or f.get('filename')
                if f.get('is_selected_structure', False):
                    selected_structure_key = f_key
                    break
        # If none explicitly selected, default to first structure file
        if not selected_structure_key and conflicts.get('structure'):
            selected_structure_key = conflicts['structure'][0]
    
    # Create table rows - only for current mode files
    file_list_items = [table_header]
    for idx, file_data in enumerate(files_for_current_mode):
        size_mb = file_data['size_bytes'] / (1024 * 1024)
        file_type = file_data['file_type']
        # Use temp_file_id or example_path as unique key for reliable removal
        file_key = file_data.get('temp_file_id') or file_data.get('example_path') or f"{file_data['filename']}_{idx}"
        
        # Check if this is the selected structure file
        is_selected_structure = (file_key == selected_structure_key)
        
        # Create purpose cell (dropdown, radio button, or static text)
        purpose_cell = create_purpose_cell(file_data, file_key, input_mode, conflicts, is_selected_structure)
        
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
                purpose_cell,
                html.Div(
                    f"{size_mb:.1f} MB",
                    style={'flex': '0.6', 'fontSize': '0.8rem', 'color': '#6c757d', 'textAlign': 'right'}
                ),
                html.Div([
                    html.Button(
                        html.I(className="fas fa-trash", id={'type': 'remove-icon', 'index': file_key}),
                        id={'type': 'remove-file', 'index': file_key},
                        n_clicks=0,
                        className='remove-file-btn',
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
            ], id={'type': 'file-row', 'index': file_key}, style={
                'display': 'flex',
                'alignItems': 'center',
                'padding': '8px 12px',
                'borderBottom': '1px solid #e9ecef',
                'backgroundColor': '#ffffff',
                'transition': 'all 0.3s ease',
            }, className='file-table-row')
        )
    
    # Validation based on input mode - only check files for current mode
    validation_messages = []
    
    # Add conflict warning messages
    if has_structure_conflict:
        validation_messages.append(
            html.Div([
                html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px', 'color': '#dc3545'}),
                html.Strong("Multiple structure files: "),
                f"You have uploaded {len(conflicts['structure'])} PDB/GRO files. Only one can be used as the reference structure. ",
                "Select one file to use and remove the others, or they will be discarded upon submission."
            ], className="alert alert-warning", style={'marginTop': '10px'})
        )
    
    if has_topology_conflict:
        validation_messages.append(
            html.Div([
                html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px', 'color': '#dc3545'}),
                html.Strong("Role conflict: "),
                f"Multiple files assigned as Topology ({len(conflicts['topology'])} files). Please use the dropdown to set one as 'Include file'."
            ], className="alert alert-danger", style={'marginTop': '10px'})
        )
    
    if input_mode == 'ensemble':
        # For ensemble mode, only need a multi-model PDB file
        has_pdb = any(f['file_type'] == 'pdb' for f in files_for_current_mode)
        required_files_met = has_pdb
        
        if files_for_current_mode:
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
        has_structure = any(f['file_type'] in ['pdb', 'gro'] for f in files_for_current_mode)
        has_topology = any(f['file_type'] in ['tpr', 'top'] for f in files_for_current_mode)
        has_trajectory = any(f['file_type'] in ['xtc', 'trr'] for f in files_for_current_mode)
        required_files_met = has_structure and has_topology and has_trajectory
        
        if files_for_current_mode:
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
    file_list_inner = html.Div(
        file_list_items,
        style={
            'border': '1px solid #dee2e6',
            'borderRadius': '5px',
            'backgroundColor': '#ffffff',
            'overflow': 'hidden',
            'marginBottom': '10px' if hidden_files_indicator else '15px'
        }
    )
    
    # Combine file list with hidden files indicator
    file_list_container = html.Div([
        file_list_inner,
        hidden_files_indicator
    ] if hidden_files_indicator else [file_list_inner])
    
    return file_list_container, {'display': 'block'}, validation_messages, submit_disabled, status_message, status_style

# Clear upload component when files are removed to allow re-uploading the same file
@app.callback(
    Output('upload-files', 'contents', allow_duplicate=True),
    [Input({'type': 'remove-file', 'index': dash.dependencies.ALL}, 'n_clicks_timestamp')],
    prevent_initial_call=True
)
def clear_upload_on_removal(n_clicks_timestamp):
    """Clear the upload component when files are removed to allow re-uploading same files."""
    ctx = callback_context
    # Only clear if an actual click happened (timestamp is a positive number)
    if ctx.triggered:
        triggered_value = ctx.triggered[0].get('value')
        if triggered_value and triggered_value > 0:
            return None
    return no_update


# Update file role when user changes the dropdown selection
@app.callback(
    Output('uploaded-files-store', 'data', allow_duplicate=True),
    [Input({'type': 'file-role', 'index': ALL}, 'value')],
    [State('uploaded-files-store', 'data'),
     State({'type': 'file-role', 'index': ALL}, 'id')],
    prevent_initial_call=True
)
def update_file_role(role_values, stored_files, role_ids):
    """Update file role in store when user changes dropdown selection."""
    logger.info(f"update_file_role callback triggered: role_values={role_values}, role_ids={role_ids}")
    
    ctx = callback_context
    
    # Check if callback was actually triggered by a value change
    if not ctx.triggered:
        logger.info("No trigger, skipping")
        return no_update
    
    if not stored_files or not role_values or not role_ids:
        logger.info("No stored files or role values, skipping")
        return no_update
    
    # Get the triggered dropdown's ID
    triggered_id = ctx.triggered_id
    logger.info(f"triggered_id: {triggered_id}")
    
    if not triggered_id or not isinstance(triggered_id, dict):
        logger.info("No valid triggered_id dict, skipping")
        return no_update
    
    if triggered_id.get('type') != 'file-role':
        logger.info("Not a file-role dropdown, skipping")
        return no_update
    
    # Get the file key from the triggered dropdown's index
    file_key = triggered_id.get('index')
    logger.info(f"Role change for file_key: {file_key}")
    
    # Find the corresponding role value
    new_role = None
    for role_id, role_val in zip(role_ids, role_values):
        if role_id.get('index') == file_key:
            new_role = role_val
            break
    
    if new_role is None:
        logger.info("Could not find new role value, skipping")
        return no_update
    
    # Update the role in stored_files
    updated = False
    for file_data in stored_files:
        # Match by temp_file_id or example_path
        key = file_data.get('temp_file_id') or file_data.get('example_path')
        if key == file_key:
            logger.info(f"Updating role for {file_data['filename']}: {file_data.get('role')} -> {new_role}")
            file_data['role'] = new_role
            updated = True
            break
    
    if not updated:
        logger.info(f"Could not find file with key {file_key} to update")
        return no_update
    
    logger.info(f"Role updated successfully, returning updated files")
    return stored_files


# Update structure selection when user clicks a radio button
@app.callback(
    Output('uploaded-files-store', 'data', allow_duplicate=True),
    [Input({'type': 'structure-select', 'index': ALL}, 'value')],
    [State('uploaded-files-store', 'data'),
     State({'type': 'structure-select', 'index': ALL}, 'id'),
     State('input-mode-selector', 'value')],
    prevent_initial_call=True
)
def update_structure_selection(selected_values, stored_files, select_ids, input_mode):
    """Update structure selection when user clicks radio button to select reference structure."""
    logger.info(f"update_structure_selection triggered: selected_values={selected_values}, select_ids={select_ids}")
    
    ctx = callback_context
    
    # Check if callback was actually triggered
    if not ctx.triggered:
        logger.info("No trigger, skipping")
        return no_update
    
    if not stored_files or not select_ids:
        logger.info("No stored files or select_ids, skipping")
        return no_update
    
    # Get the triggered radio button's ID
    triggered_id = ctx.triggered_id
    logger.info(f"triggered_id: {triggered_id}")
    
    if not triggered_id or not isinstance(triggered_id, dict):
        logger.info("No valid triggered_id dict, skipping")
        return no_update
    
    if triggered_id.get('type') != 'structure-select':
        logger.info("Not a structure-select radio button, skipping")
        return no_update
    
    # Get the file key that was selected
    selected_file_key = triggered_id.get('index')
    logger.info(f"Structure selection for file_key: {selected_file_key}")
    
    # Find the corresponding selected value (should match the file_key if radio was checked)
    is_selected = False
    for select_id, select_val in zip(select_ids, selected_values):
        if select_id.get('index') == selected_file_key and select_val == selected_file_key:
            is_selected = True
            break
    
    if not is_selected:
        logger.info("Radio button was deselected, skipping")
        return no_update
    
    # Update is_selected_structure in stored_files:
    # - Set True for the selected file
    # - Set False for all other structure files in the same mode
    current_mode = input_mode or 'trajectory'
    updated = False
    
    for file_data in stored_files:
        # Only update files for current mode
        if file_data.get('uploaded_for_mode', 'trajectory') != current_mode:
            continue
        
        # Only update structure files (pdb/gro)
        if file_data.get('file_type') not in ['pdb', 'gro']:
            continue
        
        file_key = file_data.get('temp_file_id') or file_data.get('example_path') or file_data.get('filename')
        
        if file_key == selected_file_key:
            logger.info(f"Marking {file_data['filename']} as selected structure")
            file_data['is_selected_structure'] = True
            updated = True
        else:
            # Deselect other structure files
            file_data['is_selected_structure'] = False
    
    if not updated:
        logger.info(f"Could not find file with key {selected_file_key} to select")
        return no_update
    
    logger.info(f"Structure selection updated successfully")
    return stored_files


@app.callback(
    Output('uploaded-files-store', 'data', allow_duplicate=True),
    [Input({'type': 'remove-file', 'index': dash.dependencies.ALL}, 'n_clicks_timestamp')],
    [State('uploaded-files-store', 'data'),
     State('session-id-store', 'data')],
    prevent_initial_call=True
)
def remove_file(n_clicks_timestamp, stored_files, session_id):
    """Remove a file from the upload list and delete from server."""
    logger.info(f"remove_file callback triggered: n_clicks_timestamp={n_clicks_timestamp}, stored_files count={len(stored_files) if stored_files else 0}")
    
    # Use callback_context to determine what triggered the callback
    ctx = callback_context
    
    # Check if callback was actually triggered by a click
    if not ctx.triggered:
        logger.info("No trigger, skipping")
        return no_update
    
    # Get triggered info
    triggered_prop = ctx.triggered[0]
    triggered_value = triggered_prop.get('value')

    logger.info(f"Triggered prop: {triggered_prop}")

    # n_clicks_timestamp is 0/-1/None until actually clicked, then becomes a positive epoch-ms
    if not triggered_value or triggered_value <= 0:
        logger.info(f"Triggered value {triggered_value} is not a valid click timestamp, skipping")
        return no_update
    
    # Get the triggered_id (pattern-matching dict)
    triggered_id = ctx.triggered_id
    logger.info(f"triggered_id: {triggered_id}")
    
    # If no triggered_id or it's not a dict (pattern-matching), skip
    if not triggered_id or not isinstance(triggered_id, dict):
        logger.info("No valid triggered_id dict, skipping")
        return no_update
    
    # Check if this is actually a remove-file button
    if triggered_id.get('type') != 'remove-file':
        logger.info("Not a remove-file button, skipping")
        return no_update
    
    if not stored_files:
        logger.info("No stored files to remove")
        return no_update
    
    # Get the file key from the triggered button's index
    file_key_to_remove = triggered_id.get('index')
    logger.info(f"Looking for file with key: {file_key_to_remove}")
    
    if not file_key_to_remove:
        logger.warning("No file key in triggered_id")
        return no_update
    
    try:
        # Find the file by temp_file_id
        file_to_remove = None
        for idx, f in enumerate(stored_files):
            temp_file_id = f.get('temp_file_id')
            if temp_file_id and temp_file_id == file_key_to_remove:
                file_to_remove = f
                logger.info(f"Found file by temp_file_id: {temp_file_id}")
                break
        
        if file_to_remove:
            filename_to_remove = file_to_remove['filename']
            
            # Delete the temp file from server
            temp_file_id = file_to_remove.get('temp_file_id')
            file_session_id = file_to_remove.get('session_id', session_id)
            if temp_file_id and file_session_id:
                delete_temp_file(temp_file_id, file_session_id)
            
            # Remove the file from the list by comparing temp_file_id
            updated_files = [f for f in stored_files if f.get('temp_file_id') != file_key_to_remove]
            logger.info(f"Removed file: {filename_to_remove}, Remaining files: {len(updated_files)}")
            return updated_files
        else:
            logger.warning(f"File not found for key: {file_key_to_remove}")
            # Log all temp_file_ids for debugging
            for idx, f in enumerate(stored_files):
                logger.info(f"  File {idx}: filename={f.get('filename')}, temp_file_id={f.get('temp_file_id')}")
            return no_update
            
    except Exception as e:
        logger.error(f"Error removing file: {e}")
        return no_update

# Note: Job submission now uses local storage via backend API

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
     State('gromacs-version-selector', 'value'),
     State('uploaded-files-store', 'data'),
     State('session-id-store', 'data')],
    prevent_initial_call=True
)
def handle_job_submission(submit_clicks, skip_frames, initpairfilter_cutoff, 
                         source_sel, target_sel, privacy_setting, input_mode, 
                         force_field, gromacs_version, uploaded_files, session_id):
    """Handle job submission with local file upload to backend."""
    logger.info(f"Job submission callback triggered: submit_clicks={submit_clicks}, files={len(uploaded_files) if uploaded_files else 0}")
    
    if not submit_clicks:
        logger.info("No submit clicks, returning no_update")
        return no_update, no_update
        
    if not uploaded_files:
        logger.warning("No uploaded files for job submission")
        return html.Div("Please upload files to submit a job.", className="alert alert-danger"), no_update
    
    # Filter files to only include those uploaded for the current mode
    current_mode = input_mode or 'trajectory'
    files_for_submission = [f for f in uploaded_files if f.get('uploaded_for_mode', 'trajectory') == current_mode]
    
    if not files_for_submission:
        logger.warning(f"No files uploaded for {current_mode} mode")
        return html.Div(f"No files uploaded for {current_mode.title()} mode. Please upload the required files.", className="alert alert-danger"), no_update
    
    # Check for role conflicts (e.g., multiple topology files)
    conflicts = detect_role_conflicts(uploaded_files, current_mode)
    has_topology_conflict = len(conflicts.get('topology', [])) > 1
    has_structure_conflict = len(conflicts.get('structure', [])) > 1
    
    if has_topology_conflict:
        logger.warning(f"Topology role conflict detected: {len(conflicts['topology'])} files")
        return html.Div([
            html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
            html.Strong("Role conflict: "),
            f"Multiple files assigned as Topology ({len(conflicts['topology'])} files). ",
            "Please use the 'Purpose in gRINN' dropdown to set one as 'Include file'."
        ], className="alert alert-danger"), no_update
    
    # Handle multiple structure files - only use the selected one
    if has_structure_conflict and current_mode == 'trajectory':
        # Find which structure file is selected
        selected_structure_key = None
        for f in files_for_submission:
            if f.get('file_type') in ['pdb', 'gro'] and f.get('is_selected_structure', False):
                selected_structure_key = f.get('temp_file_id') or f.get('example_path') or f.get('filename')
                break
        
        # If none explicitly selected, use the first one
        if not selected_structure_key:
            for f in files_for_submission:
                if f.get('file_type') in ['pdb', 'gro']:
                    selected_structure_key = f.get('temp_file_id') or f.get('example_path') or f.get('filename')
                    break
        
        # Filter out non-selected structure files
        logger.info(f"Structure conflict detected, using selected structure: {selected_structure_key}")
        files_for_submission = [
            f for f in files_for_submission
            if f.get('file_type') not in ['pdb', 'gro'] or 
               (f.get('temp_file_id') or f.get('example_path') or f.get('filename')) == selected_structure_key
        ]
        logger.info(f"Filtered to {len(files_for_submission)} files after structure selection")
    
    # Validate ensemble mode: exactly one PDB file required
    if current_mode == 'ensemble':
        pdb_files = [f for f in files_for_submission if f.get('file_type') == 'pdb']
        if len(pdb_files) == 0:
            return html.Div([
                html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                "Ensemble mode requires a multi-model PDB file. Please upload one."
            ], className="alert alert-danger"), no_update
        if len(pdb_files) > 1:
            return html.Div([
                html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                f"Ensemble mode requires exactly ONE PDB file, but {len(pdb_files)} were found. ",
                "Please remove extra files and keep only the multi-model ensemble PDB."
            ], className="alert alert-danger"), no_update
    
    try:
        # Job name is optional - will be None if not provided
        job_name = None
        
        # Step 1: Create job in backend
        files_info = []
        for file_data in files_for_submission:
            # Use role from file_data if available (user may have changed it via dropdown)
            file_type = file_data.get('file_type', 'unknown')
            role = file_data.get('role')
            
            # Fallback: determine role based on mode and type if not set
            if not role:
                if current_mode == 'ensemble' and file_type == 'pdb':
                    role = 'ensemble_pdb'
                elif file_type in ['pdb', 'gro']:
                    role = 'structure'
                elif file_type in ['xtc', 'trr']:
                    role = 'trajectory'
                elif file_type in ['top', 'tpr', 'itp']:
                    role = 'topology'
                else:
                    role = 'other'
            
            files_info.append({
                'filename': file_data['filename'],
                'file_type': file_type,
                'size': file_data.get('size_bytes', 0),
                'role': role
            })
        
        # Privacy: jobs are private by default, public only if checkbox is checked
        is_private = 'public' not in (privacy_setting or [])
        
        backend_url = f"{config.backend_url}/api/create-job"
        logger.info(f"Creating job via {backend_url}")
        
        response = requests.post(
            backend_url,
            json={
                'files': files_info,
                'input_mode': input_mode or 'trajectory',
                'parameters': {
                    'skip_frames': skip_frames or 1,
                    'initpairfilter_cutoff': initpairfilter_cutoff or 12.0,
                    'source_sel': source_sel or None,
                    'target_sel': target_sel or None,
                    'input_mode': input_mode or 'trajectory',
                    'force_field': force_field if input_mode == 'ensemble' else None,
                    'gromacs_version': gromacs_version if input_mode == 'trajectory' else None
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
                f"Failed to create job: {error_msg}"
            ], className="alert alert-danger"), no_update
        
        result = response.json()
        job_id = result['job_id']
        
        logger.info(f"Job {job_id} created, uploading files")
        
        # Step 2: Upload files to backend local storage
        for file_data in files_for_submission:
            content = None
            
            # Check if this is example data (source='example') or user upload
            if file_data.get('source') == 'example':
                # Example data: read directly from example_path
                example_path = file_data.get('example_path')
                
                # Security: validate path is within allowed example data directories
                if not example_path or not _validate_example_path(example_path):
                    logger.error(f"Invalid example path: {example_path}")
                    return html.Div([
                        html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                        f"Example file path validation failed: {file_data['filename']}. Please reload example data."
                    ], className="alert alert-danger"), no_update
                
                try:
                    with open(example_path, 'rb') as f:
                        content = f.read()
                except Exception as e:
                    logger.error(f"Failed to read example file {example_path}: {e}")
                    return html.Div([
                        html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                        f"Failed to read example file: {file_data['filename']}. Please reload example data."
                    ], className="alert alert-danger"), no_update
            else:
                # User upload: read from temp storage
                temp_file_id = file_data.get('temp_file_id')
                file_session_id = file_data.get('session_id', session_id)
                
                if temp_file_id and file_session_id:
                    # Read from temp file
                    temp_file_path = get_temp_file_path(temp_file_id, file_session_id)
                    if temp_file_path and os.path.exists(temp_file_path):
                        with open(temp_file_path, 'rb') as f:
                            content = f.read()
                    else:
                        logger.error(f"Temp file not found: {temp_file_path}")
                        return html.Div([
                            html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                            f"File expired or not found: {file_data['filename']}. Please re-upload."
                        ], className="alert alert-danger"), no_update
                elif 'content' in file_data:
                    # Fallback: decode from base64 content (legacy support)
                    try:
                        content = base64.b64decode(file_data['content'])
                    except Exception as e:
                        logger.error(f"Failed to decode file {file_data['filename']}: {e}")
                        continue
            
            if content is None:
                logger.error(f"No content available for file {file_data['filename']}")
                continue
            
            upload_url = f"{config.backend_url}/api/jobs/{job_id}/upload"
            
            # Upload file as multipart form data
            files = {'file': (file_data['filename'], content, 'application/octet-stream')}
            
            try:
                upload_response = requests.post(
                    upload_url,
                    files=files,
                    timeout=300  # 5 minutes for large files
                )
                
                if upload_response.status_code == 200:
                    logger.info(f"Successfully uploaded {file_data['filename']}")
                    # Delete temp file after successful upload (only for user uploads, not example data)
                    if file_data.get('source') != 'example':
                        temp_file_id = file_data.get('temp_file_id')
                        file_session_id = file_data.get('session_id', session_id)
                        if temp_file_id and file_session_id:
                            delete_temp_file(temp_file_id, file_session_id)
                else:
                    error_msg = f"Upload failed for {file_data['filename']}: {upload_response.status_code}"
                    logger.error(error_msg)
                    return html.Div([
                        html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                        error_msg
                    ], className="alert alert-danger"), no_update
                    
            except Exception as e:
                error_msg = f"Upload error for {file_data['filename']}: {str(e)}"
                logger.error(error_msg)
                return html.Div([
                    html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                    error_msg
                ], className="alert alert-danger"), no_update
        
        # Step 3: Start job processing
        logger.info(f"Starting processing for job {job_id}")
        
        start_url = f"{config.backend_url}/api/jobs/{job_id}/start"
        start_response = requests.post(start_url, timeout=30)
        
        if start_response.status_code != 200:
            error_msg = start_response.json().get('error', 'Failed to start processing')
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
     Input('manual-refresh-btn', 'n_clicks'),
     Input('monitor-dashboard-availability-store', 'data')],
    [State('monitor-job-id', 'data')],
    prevent_initial_call=True
)
def update_monitor_page(n_intervals, manual_refresh, dashboard_availability, job_id):
    """Update the job monitoring page with real-time data."""
    # Get dashboard availability status
    dashboard_available = dashboard_availability.get('available', True) if dashboard_availability else True
    active_dashboards = dashboard_availability.get('active', 0) if dashboard_availability else 0
    max_dashboards = dashboard_availability.get('max', 10) if dashboard_availability else 10
    
    try:
        # Fetch job details from backend
        backend_url = f"{config.backend_url}/api/jobs/{job_id}"
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
                                # Show Save Results button only if job is completed (not expired)
                                html.A(
                                    [html.I(className="fas fa-download", style={'marginRight': '8px'}), "Save Results"],
                                    id="monitor-save-results-btn",
                                    href=f"{config.backend_public_url}/jobs/{job_id}/download",
                                    download=f"grinn-results-{job_id}.tar.gz",
                                    style={
                                        'fontSize': '0.9rem',
                                        'padding': '6px 12px',
                                        'verticalAlign': 'middle',
                                        'backgroundColor': 'rgba(0, 123, 255, 0.1)',
                                        'color': '#007bff',
                                        'border': '1px solid rgba(0, 123, 255, 0.3)',
                                        'borderRadius': '5px',
                                        'fontWeight': '500',
                                        'cursor': 'pointer',
                                        'textDecoration': 'none',
                                        'display': 'inline-block',
                                        'marginRight': '10px'
                                    }
                                ) if ((isinstance(job.status, JobStatus) and job.status == JobStatus.COMPLETED) or (isinstance(job.status, str) and job.status.lower() == 'completed')) else html.Span(),
                                # Show Launch Dashboard button only if job is completed (not expired)
                                # Also check dashboard availability
                                html.Span([
                                    html.Button(
                                        [html.I(className="fas fa-chart-line", style={'marginRight': '8px'}), "Launch Dashboard"],
                                        id="monitor-launch-dashboard-btn",
                                        disabled=not dashboard_available,
                                        style={
                                            'fontSize': '0.9rem',
                                            'padding': '6px 12px',
                                            'verticalAlign': 'middle',
                                            'backgroundColor': 'rgba(40, 167, 69, 0.1)' if dashboard_available else 'rgba(40, 167, 69, 0.05)',
                                            'color': '#28a745' if dashboard_available else 'rgba(40, 167, 69, 0.5)',
                                            'border': '1px solid rgba(40, 167, 69, 0.3)' if dashboard_available else '1px solid rgba(40, 167, 69, 0.2)',
                                            'borderRadius': '5px',
                                            'fontWeight': '500',
                                            'cursor': 'pointer' if dashboard_available else 'not-allowed',
                                            'opacity': '1' if dashboard_available else '0.5'
                                        }
                                    )
                                ], title=f"Dashboard capacity reached ({active_dashboards}/{max_dashboards}). You can download your results and use the standalone gRINN dashboard: https://github.com/osercinoglu/grinn" if not dashboard_available else "Launch Dashboard"
                                ) if ((isinstance(job.status, JobStatus) and job.status == JobStatus.COMPLETED) or (isinstance(job.status, str) and job.status.lower() == 'completed')) else html.Span(id="monitor-launch-dashboard-btn"),
                                # Show expired message for expired jobs
                                html.Span([
                                    html.I(className="fas fa-clock", style={'marginRight': '6px'}),
                                    "Results expired"
                                ], style={
                                    'color': '#95a5a6',
                                    'fontSize': '0.9rem',
                                    'fontStyle': 'italic'
                                }) if ((isinstance(job.status, JobStatus) and job.status == JobStatus.EXPIRED) or (isinstance(job.status, str) and job.status.lower() == 'expired')) else html.Span()
                            ], style={'display': 'flex', 'alignItems': 'center'}),
                            (
                                None
                                if (
                                    (
                                        (isinstance(job.status, JobStatus) and job.status == JobStatus.FAILED)
                                        or (isinstance(job.status, str) and job.status.lower() == 'failed')
                                    )
                                    and (job.current_step or '').strip().lower() in {'job failed', 'failed'}
                                )
                                else html.P(
                                    job.current_step or "No current step",
                                    style={'margin': '10px 0 0 0', 'color': '#5A7A60', 'fontSize': '0.9rem'}
                                )
                            ),
                            html.Div([
                                html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                                html.Span("Job failed. Please check the Logs below for details.")
                            ], className="alert alert-danger", style={'marginTop': '12px', 'padding': '10px 12px', 'fontSize': '0.9rem'})
                            if (
                                (isinstance(job.status, JobStatus) and job.status == JobStatus.FAILED) or
                                (isinstance(job.status, str) and job.status.lower() == 'failed')
                            ) else None
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
            logs_url = f"{config.backend_url}/api/jobs/{job_id}/logs"
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
        backend_url = f"{config.backend_url}/api/jobs/{job_id}"
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
        
        if not job.results_path:
            return html.Div([
                html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
                "No results available for this job."
            ], className="alert alert-warning")
        
        # Fetch detailed results information
        try:
            results_url = f"{config.backend_url}/api/jobs/{job_id}/results"
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
        backend_url = f"{config.backend_url}/api/jobs/{job_id}/results"
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
        backend_url = f"{config.backend_url}/api/jobs/{job_id}/cancel"
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
     Input('queue-search-input', 'value'),
     Input('dashboard-availability-store', 'data')],
    prevent_initial_call=False
)
def update_job_queue(n_intervals, refresh_clicks, status_filter, search_text, dashboard_availability):
    """Update the job queue table with optional search filter."""
    # Get dashboard availability status
    dashboard_available = dashboard_availability.get('available', True) if dashboard_availability else True
    active_dashboards = dashboard_availability.get('active', 0) if dashboard_availability else 0
    max_dashboards = dashboard_availability.get('max', 10) if dashboard_availability else 10
    
    try:
        # Fetch jobs from backend
        backend_url = f"{config.backend_url}/api/jobs"
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
        
        # Apply client-side search filter (private jobs have no job_id)
        if search_text and search_text.strip():
            search_text = search_text.strip().lower()
            jobs = [job for job in jobs if search_text in str(job.get('job_id', '')).lower()]
        
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
        for idx, job_data in enumerate(jobs):
            job_id = job_data.get('job_id')
            job_name = job_data.get('job_name') or (f"Job {str(job_id)[:8]}" if job_id else "Private job")
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
            
            # Actions (private jobs are visible for queue health but not linkable)
            if is_private or not job_id:
                actions = html.Div([
                    html.Span(
                        html.I(className="fas fa-eye", title="Private job"),
                        style={
                            'display': 'inline-block',
                            'padding': '6px 12px',
                            'marginRight': '5px',
                            'backgroundColor': 'rgba(0, 0, 0, 0.03)',
                            'color': 'rgba(0, 0, 0, 0.35)',
                            'textDecoration': 'none',
                            'border': '1px solid rgba(0, 0, 0, 0.1)',
                            'borderRadius': '5px',
                            'fontSize': '0.9rem',
                            'fontWeight': '500',
                            'cursor': 'not-allowed'
                        }
                    ),
                    html.Span(
                        html.I(className="fas fa-download", title="Private job"),
                        style={
                            'display': 'inline-block',
                            'padding': '6px 12px',
                            'marginRight': '5px',
                            'backgroundColor': 'rgba(0, 0, 0, 0.03)',
                            'color': 'rgba(0, 0, 0, 0.35)',
                            'textDecoration': 'none',
                            'border': '1px solid rgba(0, 0, 0, 0.1)',
                            'borderRadius': '5px',
                            'fontSize': '0.9rem',
                            'fontWeight': '500',
                            'cursor': 'not-allowed'
                        }
                    ),
                    html.Span(
                        html.I(className="fas fa-chart-line", title="Private job"),
                        style={
                            'display': 'inline-block',
                            'padding': '6px 12px',
                            'marginRight': '5px',
                            'backgroundColor': 'rgba(0, 0, 0, 0.03)',
                            'color': 'rgba(0, 0, 0, 0.35)',
                            'textDecoration': 'none',
                            'border': '1px solid rgba(0, 0, 0, 0.1)',
                            'borderRadius': '5px',
                            'fontSize': '0.9rem',
                            'fontWeight': '500',
                            'cursor': 'not-allowed'
                        }
                    )
                ], style={'display': 'flex', 'gap': '5px'})
            else:
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
                    html.A(
                        html.I(className="fas fa-download", title="Save Results"),
                        href=f"{config.backend_public_url}/jobs/{job_id}/download" if status == 'completed' else "#",
                        download=f"grinn-results-{job_id}.tar.gz" if status == 'completed' else None,
                        style={
                            'display': 'inline-block',
                            'padding': '6px 12px',
                            'marginRight': '5px',
                            'backgroundColor': 'rgba(0, 123, 255, 0.1)' if status == 'completed' else 'rgba(0, 123, 255, 0.05)',
                            'color': '#007bff' if status == 'completed' else 'rgba(0, 123, 255, 0.5)',
                            'textDecoration': 'none',
                            'border': '1px solid rgba(0, 123, 255, 0.3)' if status == 'completed' else '1px solid rgba(0, 123, 255, 0.2)',
                            'borderRadius': '5px',
                            'fontSize': '0.9rem',
                            'fontWeight': '500',
                            'cursor': 'pointer' if status == 'completed' else 'not-allowed',
                            'opacity': '1' if status == 'completed' else '0.5',
                            'pointerEvents': 'auto' if status == 'completed' else 'none'
                        }
                    ),
                    # Launch Dashboard button - disabled when capacity is reached
                    html.Span([
                        html.Button(
                            html.I(className="fas fa-chart-line", title="Launch Dashboard" if (status == 'completed' and dashboard_available) else "Dashboard capacity reached"),
                            id={'type': 'launch-dashboard-btn', 'job_id': job_id},
                            disabled=(status not in ['completed'] or not dashboard_available),
                            style={
                                'padding': '6px 12px',
                                'marginRight': '5px',
                                'backgroundColor': 'rgba(40, 167, 69, 0.1)' if (status == 'completed' and dashboard_available) else 'rgba(40, 167, 69, 0.05)',
                                'color': '#28a745' if (status == 'completed' and dashboard_available) else 'rgba(40, 167, 69, 0.5)',
                                'border': '1px solid rgba(40, 167, 69, 0.3)' if (status == 'completed' and dashboard_available) else '1px solid rgba(40, 167, 69, 0.2)',
                                'borderRadius': '5px',
                                'fontSize': '0.9rem',
                                'fontWeight': '500',
                                'cursor': 'pointer' if (status == 'completed' and dashboard_available) else 'not-allowed',
                                'opacity': '1' if (status == 'completed' and dashboard_available) else '0.5'
                            }
                        )
                    ], title=f"Dashboard capacity reached ({active_dashboards}/{max_dashboards}). You can download your results and use the standalone gRINN dashboard: https://github.com/osercinoglu/grinn" if (status == 'completed' and not dashboard_available) else "Launch Dashboard")
                ], style={'display': 'flex', 'gap': '5px'})
            
            # Privacy indicator for job ID display (do not expose private IDs)
            if is_private or not job_id:
                job_id_display = html.Span([
                    html.I(className="fas fa-lock", style={'marginRight': '5px', 'color': '#6c757d'}),
                    "Private job"
                ])
            else:
                job_id_display = job_id
            
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
# Dashboard Availability Callbacks
# ============================================================================

@app.callback(
    Output('dashboard-availability-store', 'data'),
    [Input('dashboard-availability-interval', 'n_intervals'),
     Input('queue-refresh-btn', 'n_clicks')],
    prevent_initial_call=False
)
def update_dashboard_availability(n_intervals, n_clicks):
    """Fetch dashboard availability from backend (polled every 2 minutes)."""
    try:
        response = requests.get(f"{config.backend_url}/api/dashboard/availability", timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.warning(f"Failed to fetch dashboard availability: {e}")
    
    # Default to available if we can't reach backend
    return {'available': True, 'active': 0, 'max': 10}


@app.callback(
    Output('monitor-dashboard-availability-store', 'data'),
    [Input('monitor-dashboard-availability-interval', 'n_intervals')],
    prevent_initial_call=False
)
def update_monitor_dashboard_availability(n_intervals):
    """Fetch dashboard availability from backend for monitor page (polled every 2 minutes)."""
    try:
        response = requests.get(f"{config.backend_url}/api/dashboard/availability", timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.warning(f"Failed to fetch dashboard availability: {e}")
    
    # Default to available if we can't reach backend
    return {'available': True, 'active': 0, 'max': 10}


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
    """Handle dashboard launch button clicks - navigate to dashboard page with loading screen."""
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
    
    # Return URL to navigate to dashboard page (which will show loading screen)
    return f"/dashboard/{job_id}"


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
    """Handle dashboard launch from monitor page - navigate to dashboard page with loading screen."""
    if not n_clicks:
        return no_update
    
    # Return URL to navigate to dashboard page (which will show loading screen)
    return f"/dashboard/{job_id}"


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
        job_backend_url = f"{config.backend_url}/api/jobs/{job_id}"
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
        status_url = f"{config.backend_url}/api/jobs/{job_id}/dashboard/status"
        status_response = requests.get(status_url, timeout=10)
        
        # Fetch logs regardless of status (we'll need them for all loading states)
        logs_url = f"{config.backend_url}/api/jobs/{job_id}/dashboard/logs"
        logs_text = 'Initializing dashboard container...\nWaiting for logs...'
        try:
            logs_response = requests.get(logs_url, timeout=5)
            if logs_response.status_code == 200:
                logs_data = logs_response.json()
                if logs_data.get('success'):
                    fetched_logs = logs_data.get('logs', '').strip()
                    if fetched_logs:
                        logs_text = fetched_logs
                    else:
                        logs_text = 'Container starting...\nNo logs yet. Please wait...'
                else:
                    # Dashboard not started yet
                    logs_text = 'Dashboard not started yet...\nInitializing...'
            else:
                logs_text = 'Waiting for dashboard container...\nLogs will appear once container starts...'
        except Exception as log_error:
            logger.warning(f"Could not fetch dashboard logs: {log_error}")
            logs_text = 'Dashboard starting...\nLogs will appear shortly...'
        
        if status_response.status_code != 200:
            # Dashboard not started - auto-start it and show terminal
            try:
                start_url = f"{config.backend_url}/api/jobs/{job_id}/dashboard/start"
                start_response = requests.post(start_url, timeout=30)
                if start_response.status_code == 200:
                    # Successfully triggered start, show loading screen with terminal
                    return html.Div([
                        # Header section
                        html.Div([
                            html.I(className="fas fa-spinner fa-spin", 
                                  style={'fontSize': '2.5rem', 'color': '#7C9885', 'marginBottom': '15px'}),
                            html.H2("Preparing Dashboard", style={
                                'color': '#5A7A60', 
                                'marginBottom': '10px',
                                'fontSize': '1.8rem',
                                'fontWeight': '500'
                            }),
                            html.P("Setting up data visualization environment...", 
                                  style={
                                      'color': '#666', 
                                      'fontSize': '1rem',
                                      'marginBottom': '25px'
                                  })
                        ], style={
                            'textAlign': 'center',
                            'paddingTop': '8vh',
                            'paddingBottom': '20px'
                        }),
                        
                        # Terminal-style log viewer
                        html.Div([
                            html.Div([
                                html.Span("Dashboard Container Logs", style={
                                    'fontSize': '0.9rem',
                                    'fontWeight': '500',
                                    'color': '#5A7A60'
                                }),
                                html.Span(f"Job ID: {job_id[:16]}...", style={
                                    'fontSize': '0.8rem',
                                    'color': '#8A9A8A',
                                    'marginLeft': '15px'
                                })
                            ], style={
                                'padding': '12px 20px',
                                'backgroundColor': '#2d2d30',
                                'borderBottom': '1px solid #3e3e42',
                                'display': 'flex',
                                'justifyContent': 'space-between',
                                'alignItems': 'center'
                            }),
                            
                            html.Pre(
                                logs_text,
                                id='dashboard-log-content',
                                style={
                                    'backgroundColor': '#1e1e1e',
                                    'color': '#d4d4d4',
                                    'padding': '20px',
                                    'margin': '0',
                                    'fontSize': '13px',
                                    'fontFamily': "'Consolas', 'Monaco', 'Courier New', monospace",
                                    'height': '400px',
                                    'overflowY': 'auto',
                                    'whiteSpace': 'pre-wrap',
                                    'wordWrap': 'break-word',
                                    'lineHeight': '1.5'
                                }
                            )
                        ], style={
                            'maxWidth': '900px',
                            'margin': '0 auto',
                            'borderRadius': '8px',
                            'overflow': 'hidden',
                            'boxShadow': '0 4px 6px rgba(0, 0, 0, 0.1)',
                            'backgroundColor': '#1e1e1e'
                        }),
                        
                        # Status message
                        html.Div([
                            html.Div([
                                html.I(className="fas fa-info-circle", style={'marginRight': '8px', 'color': '#7C9885'}),
                                html.Span("This typically takes 5-10 minutes. ", style={'color': '#666'}),
                                html.Span("The dashboard will appear automatically once ready.", 
                                        style={'color': '#666', 'fontWeight': '500'})
                            ], style={
                                'display': 'inline-flex',
                                'alignItems': 'center',
                                'backgroundColor': '#f8f9fa',
                                'padding': '12px 20px',
                                'borderRadius': '5px',
                                'fontSize': '0.9rem',
                                'marginTop': '25px'
                            })
                        ], style={'textAlign': 'center'}),
                        
                        # JavaScript to auto-scroll logs to bottom
                        html.Script("""
                            setTimeout(function() {
                                var logContent = document.getElementById('dashboard-log-content');
                                if (logContent) {
                                    logContent.scrollTop = logContent.scrollHeight;
                                }
                            }, 100);
                        """)
                    ], style={
                        'width': '100vw',
                        'height': '100vh',
                        'padding': '0 20px',
                        'backgroundColor': '#ffffff',
                        'overflow': 'auto'
                    })
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
        
        # Log the status for debugging
        logger.info(f"Dashboard status for {job_id}: running={status_data.get('running')}, ready={status_data.get('ready')}, started_at={status_data.get('started_at')}")
        
        # Calculate elapsed time since dashboard started
        elapsed_seconds = 0
        if status_data.get('started_at'):
            try:
                from datetime import datetime
                started_at = datetime.fromisoformat(status_data['started_at'].replace('Z', '+00:00'))
                elapsed_seconds = (datetime.utcnow() - started_at).total_seconds()
                logger.info(f"Dashboard for {job_id} has been running for {elapsed_seconds:.1f} seconds")
            except Exception as e:
                logger.warning(f"Could not calculate elapsed time: {e}")
        
        # If not running OR not ready, show terminal with logs
        if not status_data.get('running') or not status_data.get('ready'):
            # Try to start if not running
            if not status_data.get('running'):
                try:
                    start_url = f"{config.backend_url}/api/jobs/{job_id}/dashboard/start"
                    start_response = requests.post(start_url, timeout=30)
                    if start_response.status_code != 200:
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
            
            # Show loading screen with terminal and logs
            return html.Div([
                # Header section
                html.Div([
                    html.I(className="fas fa-spinner fa-spin", 
                          style={'fontSize': '2.5rem', 'color': '#7C9885', 'marginBottom': '15px'}),
                    html.H2("Preparing Dashboard", style={
                        'color': '#5A7A60', 
                        'marginBottom': '10px',
                        'fontSize': '1.8rem',
                        'fontWeight': '500'
                    }),
                    html.P("Setting up data visualization environment...", 
                          style={
                              'color': '#666', 
                              'fontSize': '1rem',
                              'marginBottom': '25px'
                          })
                ], style={
                    'textAlign': 'center',
                    'paddingTop': '8vh',
                    'paddingBottom': '20px'
                }),
                
                # Terminal-style log viewer
                html.Div([
                    html.Div([
                        html.Span("Dashboard Container Logs", style={
                            'fontSize': '0.9rem',
                            'fontWeight': '500',
                            'color': '#5A7A60'
                        }),
                        html.Span(f"Job ID: {job_id[:16]}...", style={
                            'fontSize': '0.8rem',
                            'color': '#8A9A8A',
                            'marginLeft': '15px'
                        })
                    ], style={
                        'padding': '12px 20px',
                        'backgroundColor': '#2d2d30',
                        'borderBottom': '1px solid #3e3e42',
                        'display': 'flex',
                        'justifyContent': 'space-between',
                        'alignItems': 'center'
                    }),
                    
                    html.Pre(
                        logs_text,
                        id='dashboard-log-content',
                        style={
                            'backgroundColor': '#1e1e1e',
                            'color': '#d4d4d4',
                            'padding': '20px',
                            'margin': '0',
                            'fontSize': '13px',
                            'fontFamily': "'Consolas', 'Monaco', 'Courier New', monospace",
                            'height': '400px',
                            'overflowY': 'auto',
                            'whiteSpace': 'pre-wrap',
                            'wordWrap': 'break-word',
                            'lineHeight': '1.5'
                        }
                    )
                ], style={
                    'maxWidth': '900px',
                    'margin': '0 auto',
                    'borderRadius': '8px',
                    'overflow': 'hidden',
                    'boxShadow': '0 4px 6px rgba(0, 0, 0, 0.1)',
                    'backgroundColor': '#1e1e1e'
                }),
                
                # Status message
                html.Div([
                    html.Div([
                        html.I(className="fas fa-info-circle", style={'marginRight': '8px', 'color': '#7C9885'}),
                        html.Span("This typically takes 5-10 minutes. ", style={'color': '#666'}),
                        html.Span("The dashboard will appear automatically once ready.", 
                                style={'color': '#666', 'fontWeight': '500'})
                    ], style={
                        'display': 'inline-flex',
                        'alignItems': 'center',
                        'backgroundColor': '#f8f9fa',
                        'padding': '12px 20px',
                        'borderRadius': '5px',
                        'fontSize': '0.9rem',
                        'marginTop': '25px'
                    })
                ], style={'textAlign': 'center'}),
                
                # JavaScript to auto-scroll logs to bottom
                html.Script("""
                    setTimeout(function() {
                        var logContent = document.getElementById('dashboard-log-content');
                        if (logContent) {
                            logContent.scrollTop = logContent.scrollHeight;
                        }
                    }, 100);
                """)
            ], style={
                'width': '100vw',
                'height': '100vh',
                'padding': '0 20px',
                'backgroundColor': '#ffffff',
                'overflow': 'auto'
            })
        
        # Dashboard is ready! But double-check to be absolutely sure
        # Only show iframe if BOTH running and ready are True, AND at least 3 seconds have passed
        if (status_data.get('running') is True and 
            status_data.get('ready') is True and 
            elapsed_seconds >= 3):
            
            dashboard_url = status_data.get('url')
            logger.info(f"Dashboard ready for {job_id} after {elapsed_seconds:.1f}s, showing iframe at {dashboard_url}")
            
            # Create a wrapper that includes the heartbeat JavaScript
            heartbeat_script = f"""
            <script>
            // Send dashboard heartbeat every 60 seconds
            const jobId = '{job_id}';
            const backendBaseUrl = window.location.origin;
            const heartbeatInterval = 60000; // 60 seconds
            
            function sendDashboardHeartbeat() {{
                const heartbeatUrl = backendBaseUrl + '/api/dashboard/' + jobId + '/heartbeat';
                fetch(heartbeatUrl, {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{closing: false}})
                }})
                .catch(err => console.debug('Dashboard heartbeat error:', err));
            }}
            
            // Send initial heartbeat
            sendDashboardHeartbeat();
            
            // Send heartbeat every 60 seconds
            const heartbeatTimer = setInterval(sendDashboardHeartbeat, heartbeatInterval);
            
            // Send closing notification when window unloads
            window.addEventListener('beforeunload', function() {{
                const heartbeatUrl = backendBaseUrl + '/api/dashboard/' + jobId + '/heartbeat';
                navigator.sendBeacon(heartbeatUrl, JSON.stringify({{closing: true}}));
                clearInterval(heartbeatTimer);
            }});
            
            // Cleanup on page visibility change
            document.addEventListener('visibilitychange', function() {{
                if (document.hidden) {{
                    // Browser tab is hidden
                }} else {{
                    // Browser tab is visible - send heartbeat to keep alive
                    sendDashboardHeartbeat();
                }}
            }});
            </script>
            """
            
            return html.Div([
                html.Iframe(
                    src=dashboard_url,
                    style={
                        'width': '100%',
                        'height': '100%',
                        'border': 'none',
                        'margin': '0',
                        'padding': '0',
                        'display': 'block'
                    },
                    id='dashboard-iframe'
                ),
                html.Script(
                    heartbeat_script,
                    type='text/javascript'
                )
            ], style={
                'width': '100%',
                'height': '100%',
                'margin': '0',
                'padding': '0',
                'position': 'relative'
            })
        elif status_data.get('running') is True and status_data.get('ready') is True:
            # Ready=True but less than 3 seconds - force wait
            logger.info(f"Dashboard marked ready but only {elapsed_seconds:.1f}s elapsed, waiting...")
            return html.Div([
                # Header section
                html.Div([
                    html.I(className="fas fa-spinner fa-spin", 
                          style={'fontSize': '2.5rem', 'color': '#7C9885', 'marginBottom': '15px'}),
                    html.H2("Dashboard Almost Ready", style={
                        'color': '#5A7A60', 
                        'marginBottom': '10px',
                        'fontSize': '1.8rem',
                        'fontWeight': '500'
                    }),
                    html.P("Final checks in progress...", 
                          style={
                              'color': '#666', 
                              'fontSize': '1rem',
                              'marginBottom': '25px'
                          })
                ], style={
                    'textAlign': 'center',
                    'paddingTop': '8vh',
                    'paddingBottom': '20px'
                }),
                
                # Terminal-style log viewer
                html.Div([
                    html.Div([
                        html.Span("Dashboard Container Logs", style={
                            'fontSize': '0.9rem',
                            'fontWeight': '500',
                            'color': '#5A7A60'
                        }),
                        html.Span(f"Job ID: {job_id[:16]}...", style={
                            'fontSize': '0.8rem',
                            'color': '#8A9A8A',
                            'marginLeft': '15px'
                        })
                    ], style={
                        'padding': '12px 20px',
                        'backgroundColor': '#2d2d30',
                        'borderBottom': '1px solid #3e3e42',
                        'display': 'flex',
                        'justifyContent': 'space-between',
                        'alignItems': 'center'
                    }),
                    
                    html.Pre(
                        logs_text,
                        id='dashboard-log-content',
                        style={
                            'backgroundColor': '#1e1e1e',
                            'color': '#d4d4d4',
                            'padding': '20px',
                            'margin': '0',
                            'fontSize': '13px',
                            'fontFamily': "'Consolas', 'Monaco', 'Courier New', monospace",
                            'height': '400px',
                            'overflowY': 'auto',
                            'whiteSpace': 'pre-wrap',
                            'wordWrap': 'break-word',
                            'lineHeight': '1.5'
                        }
                    )
                ], style={
                    'maxWidth': '900px',
                    'margin': '0 auto',
                    'borderRadius': '8px',
                    'overflow': 'hidden',
                    'boxShadow': '0 4px 6px rgba(0, 0, 0, 0.1)',
                    'backgroundColor': '#1e1e1e'
                }),
                
                # Status message
                html.Div([
                    html.Div([
                        html.I(className="fas fa-check-circle", style={'marginRight': '8px', 'color': '#7C9885'}),
                        html.Span(f"Dashboard will appear in {max(0, 3 - elapsed_seconds):.0f} seconds...", 
                                style={'color': '#666', 'fontWeight': '500'})
                    ], style={
                        'display': 'inline-flex',
                        'alignItems': 'center',
                        'backgroundColor': '#e8f5e9',
                        'padding': '12px 20px',
                        'borderRadius': '5px',
                        'fontSize': '0.9rem',
                        'marginTop': '25px'
                    })
                ], style={'textAlign': 'center'}),
                
                # JavaScript to auto-scroll logs to bottom
                html.Script("""
                    setTimeout(function() {
                        var logContent = document.getElementById('dashboard-log-content');
                        if (logContent) {
                            logContent.scrollTop = logContent.scrollHeight;
                        }
                    }, 100);
                """)
            ], style={
                'width': '100vw',
                'height': '100vh',
                'padding': '0 20px',
                'backgroundColor': '#ffffff',
                'overflow': 'auto'
            })
        else:
            # Safety fallback - if we somehow got here without being ready, show loading
            logger.warning(f"Dashboard status check passed but ready={status_data.get('ready')}, running={status_data.get('running')}")
            return html.Div([
                html.Div([
                    html.I(className="fas fa-spinner fa-spin", 
                          style={'fontSize': '2.5rem', 'color': '#7C9885', 'marginBottom': '15px'}),
                    html.H3("Dashboard Status Check...", style={'color': '#5A7A60'}),
                    html.P(f"Running: {status_data.get('running')}, Ready: {status_data.get('ready')}", 
                          style={'color': '#666', 'fontSize': '0.9rem', 'fontFamily': 'monospace'})
                ], style={
                    'textAlign': 'center',
                    'paddingTop': '20vh',
                    'display': 'flex',
                    'flexDirection': 'column',
                    'alignItems': 'center'
                })
            ])
        
    except Exception as e:
        logger.error(f"Error updating dashboard status for {job_id}: {e}")
        return html.Div([
            html.I(className="fas fa-exclamation-triangle", style={'marginRight': '8px'}),
            f"Error loading dashboard: {str(e)}"
        ], className="alert alert-danger")


# =============================================================================
# SECURE DOWNLOAD ENDPOINT FOR EXAMPLE DATA
# =============================================================================

@app.server.route('/download-example/<mode>')
def download_example_zip(mode):
    """
    Secure endpoint to download example data as a zip file.
    
    Creates an in-memory zip of all files in the example data directory
    for the specified mode and serves it for download.
    
    Validates:
    - mode is 'trajectory' or 'ensemble'
    - corresponding example data path is configured and contains files
    """
    # Validate mode
    if mode not in ['trajectory', 'ensemble']:
        logger.warning(f"Invalid mode for example download: {mode}")
        abort(400, description="Invalid mode. Must be 'trajectory' or 'ensemble'.")
    
    # Get the appropriate path based on mode
    if mode == 'trajectory':
        example_path = config.example_data_path_trajectory
    else:
        example_path = config.example_data_path_ensemble
    
    # Check if example data is configured for this mode
    if not example_path or not os.path.isdir(example_path):
        logger.warning(f"Example data not configured for mode: {mode}")
        abort(404, description=f"Example data not available for {mode} mode.")
    
    # Get list of files
    try:
        files = [f for f in os.listdir(example_path) 
                 if os.path.isfile(os.path.join(example_path, f))]
    except Exception as e:
        logger.error(f"Error listing example files: {e}")
        abort(500, description="Error accessing example data.")
    
    if not files:
        logger.warning(f"No files found in example data for mode: {mode}")
        abort(404, description=f"No example files available for {mode} mode.")
    
    # Create in-memory zip file
    zip_buffer = BytesIO()
    try:
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for filename in files:
                file_path = os.path.join(example_path, filename)
                zip_file.write(file_path, arcname=filename)
        
        zip_buffer.seek(0)
    except Exception as e:
        logger.error(f"Error creating zip file: {e}")
        abort(500, description="Error creating download file.")
    
    zip_filename = f"grinn_example_{mode}.zip"
    logger.info(f"Serving example zip: {zip_filename} with {len(files)} files")
    
    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name=zip_filename
    )


if __name__ == '__main__':
    try:
        # Validate configuration
        config.validate()
        logger.info("Starting gRINN Web Service Frontend")
        logger.info(f"Storage path: {config.storage_path}")
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