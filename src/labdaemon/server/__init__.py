"""
LabDaemon Server Module

Provides HTTP/SSE server capabilities for LabDaemon, enabling remote monitoring
and control of devices and tasks.

The server is an optional, in-process wrapper around LabDaemon that exposes
functionality via HTTP endpoints and Server-Sent Events (SSE).

Example:
    from labdaemon import LabDaemon
    from labdaemon.server import LabDaemonServer, ServerAPI, SSEClient
    
    # Server side
    daemon = LabDaemon()
    server = LabDaemonServer(daemon, host="0.0.0.0", port=5000)
    server.start(blocking=False)
    
    # Client side
    api = ServerAPI("http://localhost:5000")
    devices = api.list_devices()
    
    # Streaming
    def on_data(event):
        print(f"Data: {event['payload']}")
    
    client = SSEClient("http://localhost:5000", on_event=on_data)
    client.start_device_stream("daq1")
"""

from .server import LabDaemonServer
from .client import ServerAPI, SSEClient
from .errors import ServerAPIError, ServerConnectionError

__all__ = [
    "LabDaemonServer",
    "ServerAPI",
    "SSEClient",
    "ServerAPIError",
    "ServerConnectionError",
]
