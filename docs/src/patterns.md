# Client Patterns

The `labdaemon.patterns` module has helper functions for common client operations like health checks and device management. Use them if they're helpful - they're optional and don't add complexity to the core framework.

## Health Checking

Use `ensure_server` to check if a server is responding before trying to use it. This is handy in GUI applications to give users feedback about connectivity.

```python
from labdaemon.patterns import ensure_server

# Check using direct URL
if ensure_server(server_url="http://localhost:5000"):
    print("Server at localhost:5000 is healthy")

# Check with custom timeout
if not ensure_server(server_url="http://192.168.1.100:5000", timeout=2.0):
    print("Remote server not responding within 2 seconds")

# Quick check with short timeout
if not ensure_server(server_url="http://localhost:5000", timeout=0.5):
    print("Server not responding quickly")
```

## Dynamic Device Management

The `ensure_device` function helps GUI applications add devices that may not be in the initial server configuration. It requires a ServerAPI instance:

```python
from labdaemon.server import ServerAPI
from labdaemon.patterns import ensure_device

# Create API client
api = ServerAPI("http://localhost:5000")

# Ensure device exists and is connected
device = ensure_device(
    api,
    device_id="laser2",
    device_type="SantecLaser",
    connect=True,
    address="GPIB0::2"
)

print(f"Device status: {device}")

# Device is now available for use
result = api.call_device_method("laser2", "get_power")
print(f"Laser power: {result['result']}")
```

## Example: GUI Application

Here's a GUI application that uses these client patterns:

```python
#!/usr/bin/env python3
"""GUI application using LabDaemon client patterns."""

from labdaemon.patterns import ensure_server, ensure_device
from labdaemon.server import ServerAPI


class LabControlGUI:
    def __init__(self):
        # API client (will be set when connecting)
        self.api = None
        self.server_url = None
    
    def connect_to_server(self, server_url: str) -> bool:
        """Connect to a LabDaemon server."""
        # Check if server is healthy
        if not ensure_server(server_url=server_url, timeout=3.0):
            print(f"Server at {server_url} is not responding")
            return False
        
        # Create API client
        self.api = ServerAPI(server_url)
        self.server_url = server_url
        
        print(f"Connected to server at {server_url}")
        return True
    
    def ensure_device_available(self, device_id: str, device_type: str, **params):
        """Ensure a device is available on the server."""
        if not self.api:
            print("Not connected to any server")
            return None
        
        try:
            device = ensure_device(
                self.api,
                device_id=device_id,
                device_type=device_type,
                connect=True,
                **params
            )
            print(f"Device '{device_id}' is ready")
            return device
        except Exception as e:
            print(f"Failed to ensure device '{device_id}': {e}")
            return None
    
    def run_experiment(self):
        """Run a simple experiment."""
        if not self.api:
            print("Not connected to server")
            return
        
        # Ensure required devices
        laser = self.ensure_device_available("laser1", "SantecLaser", 
                                            address="GPIB0::1")
        if not laser:
            return
        
        daq = self.ensure_device_available("daq1", "Picoscope", 
                                          serial="ABC123")
        if not daq:
            return
        
        # Configure devices
        self.api.call_device_method("laser1", "set_wavelength", args=[1550.0])
        self.api.call_device_method("laser1", "set_power", args=[10.0])
        
        # Start acquisition
        self.api.call_device_method("daq1", "start_acquisition")
        
        print("Experiment running...")


# Usage
if __name__ == "__main__":
    gui = LabControlGUI()
    
    # Try to connect to server
    if not gui.connect_to_server("http://localhost:5000"):
        print("Failed to connect to server")
        exit(1)
    
    # Run experiment
    gui.run_experiment()
```

## Tips for Using Patterns

Check server connectivity before trying to use it:

```python
if not ensure_server(server_url="http://production-server:5000", timeout=2.0):
    show_error_dialog("Production server is not responding")
    return
```

Devices might not be pre-configured on the server, so handle that gracefully:

```python
try:
    device = ensure_device(api, "laser2", "SantecLaser", address="GPIB0::2")
except Exception as e:
    log_error(f"Failed to add device: {e}")
    return
```

Set timeouts based on your network conditions:

```python
# Local development - fast timeout
api = ServerAPI("http://localhost:5000", timeout=1.0)

# Remote lab - slower timeout
api = ServerAPI("http://lab-server.local:5000", timeout=10.0)
```

Keep device parameters in server configuration, not hardcoded in client apps:

```python
# Good: Configuration handled by server
device = ensure_device(api, "laser1", "SantecLaser")

# Bad: Hardcoded in client
device = ensure_device(api, "laser1", "SantecLaser", address="GPIB0::1")
```

## Integration with Existing Code

The patterns module is optional and doesn't interfere with existing LabDaemon code. You can:

- Use only the parts you need
- Mix patterns with direct LabDaemon usage
- Gradually adopt patterns in existing applications

```python
# Mix direct usage with patterns
from labdaemon import LabDaemon
from labdaemon.server import LabDaemonServer
from labdaemon.patterns import ensure_server

# Traditional setup
daemon = LabDaemon()
server = LabDaemonServer(daemon)
server.start(blocking=False)

# Pattern for health check
if ensure_server(server_url="http://localhost:5000"):
    print("Server is healthy")
```

For comprehensive server management capabilities, see [Server Management](server-management.md).
