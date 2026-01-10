"""
GUI helper patterns for LabDaemon.

Provides utilities for GUI applications to dynamically manage devices
and handle common GUI-server interaction patterns.
"""

from typing import Any, Dict, Optional
from labdaemon.server.client import ServerAPI
from labdaemon.server.errors import ServerAPIError, ServerConnectionError


def ensure_device(api: ServerAPI, device_id: str, device_type: str, 
                  connect: bool = True, **params) -> Dict[str, Any]:
    """
    Ensure a device exists and is connected.
    
    Checks if a device exists, adds it if missing, and optionally
    connects it. This is useful for GUI applications that need
    devices that may not be in the initial server configuration.
    
    Args:
        api: ServerAPI client instance
        device_id: Device identifier
        device_type: Registered device type name
        connect: Whether to connect the device if added
        **params: Device-specific parameters
        
    Returns:
        Device information dictionary
        
    Example:
        api = ServerAPI("http://localhost:5000")
        device = ensure_device(api, "laser2", "SantecLaser", 
                              address="GPIB0::2", connect=True)
    """
    # Check if device already exists
    try:
        device = api.get_device(device_id)
        
        # Device exists, check if we should connect it
        if connect and not device.get('connected', False):
            device = api.connect_device(device_id)
        
        return device
        
    except ServerAPIError as e:
        if '404' in str(e):
            # Device doesn't exist, add it
            device = api.add_device(device_id, device_type, **params)
            
            # Connect if requested
            if connect:
                device = api.connect_device(device_id)
            
            return device
        else:
            raise
    
    except Exception:
        # Re-raise other exceptions
        raise