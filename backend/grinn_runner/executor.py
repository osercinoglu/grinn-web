"""
gRINN Docker runner utilities.
Provides a wrapper for executing gRINN workflows in Docker containers.
"""

import os
import sys
import logging
import subprocess
import json
import time
from typing import Dict, Any, List, Optional, Tuple
import tempfile
import shutil

logger = logging.getLogger(__name__)

class GrinnExecutor:
    """Executes gRINN analysis with proper Docker isolation and monitoring."""
    
    def __init__(self, docker_image: str = "grinn:latest", 
                 timeout: int = 3600, memory_limit: str = "8g", 
                 cpu_limit: str = "4"):
        self.docker_image = docker_image
        self.timeout = timeout
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
        
        # Validate Docker availability
        if not self._check_docker():
            raise RuntimeError("Docker is not available or not accessible")
    
    def _check_docker(self) -> bool:
        """Check if Docker is available and accessible."""
        try:
            result = subprocess.run(['docker', '--version'], 
                                  capture_output=True, text=True, timeout=10)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    def prepare_input_files(self, input_dir: str, file_mapping: Dict[str, str]) -> bool:
        """
        Prepare input files for gRINN analysis.
        
        Args:
            input_dir: Directory containing input files
            file_mapping: Mapping of expected filenames to actual filenames
            
        Returns:
            True if preparation successful
        """
        try:
            # Standard gRINN input file names
            standard_names = {
                'structure': 'system.pdb',
                'trajectory': 'traj.xtc',
                'topology': 'topol.top',
                'parameters': 'md.tpr',
                'config': 'grompp.mdp'
            }
            
            # Create symbolic links or copies with standard names
            for file_type, expected_name in standard_names.items():
                if file_type in file_mapping:
                    source_file = os.path.join(input_dir, file_mapping[file_type])
                    target_file = os.path.join(input_dir, expected_name)
                    
                    if os.path.exists(source_file) and not os.path.exists(target_file):
                        try:
                            os.symlink(source_file, target_file)
                            logger.debug(f"Created symlink: {target_file} -> {source_file}")
                        except OSError:
                            # If symlink fails, copy the file
                            shutil.copy2(source_file, target_file)
                            logger.debug(f"Copied file: {source_file} -> {target_file}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to prepare input files: {e}")
            return False
    
    def build_grinn_command(self, job_params: Dict[str, Any]) -> List[str]:
        """
        Build gRINN command based on job parameters.
        
        Args:
            job_params: Dictionary of job parameters
            
        Returns:
            List of command arguments
        """
        cmd = [
            'python', '/app/grinn_workflow.py',
            '--input-dir', '/input',
            '--output-dir', '/output'
        ]
        
        # Simulation parameters
        if 'simulation_time_ns' in job_params:
            cmd.extend(['--sim-time', str(job_params['simulation_time_ns'])])
        
        if 'temperature_k' in job_params:
            cmd.extend(['--temperature', str(job_params['temperature_k'])])
        
        if 'pressure_bar' in job_params:
            cmd.extend(['--pressure', str(job_params['pressure_bar'])])
        
        # Analysis parameters
        if 'energy_cutoff' in job_params:
            cmd.extend(['--energy-cutoff', str(job_params['energy_cutoff'])])
        
        if 'distance_cutoff_nm' in job_params:
            cmd.extend(['--distance-cutoff', str(job_params['distance_cutoff_nm'])])
        
        if 'network_threshold' in job_params:
            cmd.extend(['--network-threshold', str(job_params['network_threshold'])])
        
        # Boolean parameters
        if job_params.get('include_backbone', True):
            cmd.append('--include-backbone')
        
        if job_params.get('generate_plots', True):
            cmd.append('--generate-plots')
        
        if job_params.get('generate_network', True):
            cmd.append('--generate-network')
        
        # Interaction types
        interaction_types = job_params.get('interaction_types', ['total'])
        for itype in interaction_types:
            cmd.extend(['--interaction-type', itype])
        
        # Output format
        output_formats = job_params.get('output_format', ['csv'])
        for fmt in output_formats:
            cmd.extend(['--output-format', fmt])
        
        # Residue selection
        if job_params.get('residue_selection'):
            cmd.extend(['--residue-selection', job_params['residue_selection']])
        
        return cmd
    
    def execute_analysis(self, input_dir: str, output_dir: str, 
                        job_params: Dict[str, Any], 
                        progress_callback=None) -> Tuple[bool, str, List[str]]:
        """
        Execute gRINN analysis in Docker container.
        
        Args:
            input_dir: Directory containing input files
            output_dir: Directory to store output files
            job_params: Job parameters dictionary
            progress_callback: Optional callback function for progress updates
            
        Returns:
            Tuple of (success, stdout, stderr_lines)
        """
        try:
            # Ensure output directory exists
            os.makedirs(output_dir, exist_ok=True)
            
            # Build Docker command
            docker_cmd = [
                'docker', 'run',
                '--rm',  # Remove container after execution
                '--memory', self.memory_limit,
                '--cpus', self.cpu_limit,
                '-v', f'{os.path.abspath(input_dir)}:/input:ro',
                '-v', f'{os.path.abspath(output_dir)}:/output',
                '--network', 'none',  # No network access for security
                '--user', f'{os.getuid()}:{os.getgid()}',  # Run as current user
                self.docker_image
            ]
            
            # Add gRINN command
            grinn_cmd = self.build_grinn_command(job_params)
            docker_cmd.extend(grinn_cmd)
            
            logger.info(f"Executing Docker command: {' '.join(docker_cmd)}")
            
            # Start process
            process = subprocess.Popen(
                docker_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # Monitor process
            stdout_lines = []
            stderr_lines = []
            start_time = time.time()
            
            try:
                while True:
                    # Check if process finished
                    poll_result = process.poll()
                    if poll_result is not None:
                        # Process finished, read remaining output
                        remaining_stdout, remaining_stderr = process.communicate()
                        if remaining_stdout:
                            stdout_lines.extend(remaining_stdout.strip().split('\n'))
                        if remaining_stderr:
                            stderr_lines.extend(remaining_stderr.strip().split('\n'))
                        break
                    
                    # Read available output
                    try:
                        stdout_line = process.stdout.readline()
                        if stdout_line:
                            line = stdout_line.strip()
                            stdout_lines.append(line)
                            logger.debug(f"gRINN stdout: {line}")
                            
                            # Call progress callback if available
                            if progress_callback:
                                progress_callback(line)
                        
                        stderr_line = process.stderr.readline()
                        if stderr_line:
                            line = stderr_line.strip()
                            stderr_lines.append(line)
                            logger.debug(f"gRINN stderr: {line}")
                    
                    except Exception as e:
                        logger.warning(f"Error reading process output: {e}")
                    
                    # Check timeout
                    if time.time() - start_time > self.timeout:
                        logger.error("gRINN analysis timed out")
                        process.kill()
                        process.wait()
                        return False, "", ["Process timed out"]
                    
                    # Small delay to prevent excessive CPU usage
                    time.sleep(0.1)
                
                # Check return code
                return_code = process.returncode
                success = return_code == 0
                
                if success:
                    logger.info("gRINN analysis completed successfully")
                else:
                    logger.error(f"gRINN analysis failed with return code {return_code}")
                
                return success, '\n'.join(stdout_lines), stderr_lines
                
            except Exception as e:
                logger.error(f"Error during process execution: {e}")
                process.kill()
                process.wait()
                return False, "", [str(e)]
                
        except Exception as e:
            logger.error(f"Failed to execute gRINN analysis: {e}")
            return False, "", [str(e)]
    
    def validate_output(self, output_dir: str) -> Tuple[bool, List[str]]:
        """
        Validate that gRINN analysis produced expected output files.
        
        Args:
            output_dir: Directory containing analysis results
            
        Returns:
            Tuple of (is_valid, list_of_issues)
        """
        try:
            expected_files = [
                'energies_intEnTotal.csv',
                'energies_intEnVdW.csv', 
                'energies_intEnElec.csv',
                'system_dry.pdb'
            ]
            
            issues = []
            
            for expected_file in expected_files:
                file_path = os.path.join(output_dir, expected_file)
                if not os.path.exists(file_path):
                    issues.append(f"Missing expected output file: {expected_file}")
                elif os.path.getsize(file_path) == 0:
                    issues.append(f"Output file is empty: {expected_file}")
            
            # Check for log files that might indicate errors
            log_files = [f for f in os.listdir(output_dir) if f.endswith('.log')]
            for log_file in log_files:
                log_path = os.path.join(output_dir, log_file)
                try:
                    with open(log_path, 'r') as f:
                        content = f.read()
                        if 'error' in content.lower() or 'failed' in content.lower():
                            issues.append(f"Error found in log file {log_file}")
                except Exception:
                    pass  # Ignore log reading errors
            
            is_valid = len(issues) == 0
            
            if is_valid:
                logger.info("gRINN output validation passed")
            else:
                logger.warning(f"gRINN output validation failed: {issues}")
            
            return is_valid, issues
            
        except Exception as e:
            logger.error(f"Failed to validate output: {e}")
            return False, [str(e)]
    
    def get_analysis_summary(self, output_dir: str) -> Dict[str, Any]:
        """
        Generate a summary of the analysis results.
        
        Args:
            output_dir: Directory containing analysis results
            
        Returns:
            Dictionary with analysis summary
        """
        try:
            summary = {
                'output_files': [],
                'file_sizes': {},
                'total_size_mb': 0,
                'analysis_date': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            
            total_size = 0
            
            for item in os.listdir(output_dir):
                item_path = os.path.join(output_dir, item)
                if os.path.isfile(item_path):
                    size = os.path.getsize(item_path)
                    summary['output_files'].append(item)
                    summary['file_sizes'][item] = size
                    total_size += size
            
            summary['total_size_mb'] = round(total_size / (1024 * 1024), 2)
            
            # Try to read some basic statistics from CSV files
            try:
                import pandas as pd
                total_csv = os.path.join(output_dir, 'energies_intEnTotal.csv')
                if os.path.exists(total_csv):
                    df = pd.read_csv(total_csv)
                    summary['interaction_count'] = len(df)
                    if not df.empty:
                        summary['energy_range'] = {
                            'min': float(df.iloc[:, 1:].min().min()),
                            'max': float(df.iloc[:, 1:].max().max())
                        }
            except Exception as e:
                logger.debug(f"Could not extract CSV statistics: {e}")
            
            return summary
            
        except Exception as e:
            logger.error(f"Failed to generate analysis summary: {e}")
            return {'error': str(e)}


def create_progress_callback(update_function):
    """
    Create a progress callback function for monitoring Docker execution.
    
    Args:
        update_function: Function to call with progress updates
        
    Returns:
        Progress callback function
    """
    def callback(output_line: str):
        try:
            # Parse common gRINN progress indicators
            if 'progress' in output_line.lower():
                # Extract percentage if available
                import re
                percentage_match = re.search(r'(\d+)%', output_line)
                if percentage_match:
                    percentage = int(percentage_match.group(1))
                    update_function(percentage, output_line)
                else:
                    update_function(None, output_line)
            elif any(keyword in output_line.lower() for keyword in 
                    ['starting', 'processing', 'analyzing', 'computing', 'writing']):
                update_function(None, output_line)
        except Exception as e:
            logger.debug(f"Error in progress callback: {e}")
    
    return callback