"""
Setup management patterns for LabDaemon.

Provides HTTP-based health checking to ensure servers are running.
"""

from typing import Optional
import requests


def ensure_server(server_url: Optional[str] = None, timeout: float = 5.0) -> bool:
    """
    Ensure a LabDaemon server is running and responding.
    
    Performs an HTTP health check and returns the server status.
    This is a simple function that doesn't start servers - it only
    checks if they're responding. Use this in GUI applications
    to verify server connectivity before attempting operations.
    
    Args:
        server_url: Direct server URL to check.
        timeout: Health check timeout in seconds.
        
    Returns:
        True if server is healthy, False otherwise.
        
    Example:
        if ensure_server(server_url="http://192.168.1.100:5000"):
            # Server is running
            pass
    """
    if not server_url:
        return False
    
    try:
        response = requests.get(f"{server_url}/health", timeout=timeout)
        return response.status_code == 200
    except Exception:
        return False
