# Server

The server exposes the daemon via HTTP/SSE, enabling remote access and multi-client coordination. It is optional—use the daemon directly for local scripts.

## Architecture

The server wraps a daemon instance and provides:

- HTTP API: For device control, task execution, and state queries
- Server-Sent Events (SSE): For real-time device data streaming
- Device ownership enforcement: To prevent concurrent command conflicts

Device and task code is unchanged; the server is a transparent HTTP layer.

## Device Ownership

Tasks declare device dependencies via `device_ids`:

```python
class SweepTask:
    def __init__(self, task_id: str, laser_id: str, **kwargs):
        self.task_id = task_id
        self.device_ids = [laser_id]
```

When a task starts, the server atomically claims declared devices. Other clients attempting commands on owned devices receive 409 Conflict. Queries are always permitted. Ownership is released when the task completes.

## Streaming

Devices implementing `start_streaming(callback)` and `stop_streaming(timeout)` provide SSE endpoints for live data:

```python
from labdaemon.server import SSEClient

def on_event(event):
    if event.get('event') == 'device_data':
        print(f"Sequence {event['sequence']}: {event.get('payload')}")

client = SSEClient("http://localhost:5000", on_event=on_event)
client.start_device_stream("daq1")
client.stop_stream()
```

## Setup

```python
from labdaemon import LabDaemon
from labdaemon.server import LabDaemonServer

daemon = LabDaemon()
server = LabDaemonServer(daemon, host="0.0.0.0", port=5000)

daemon.register_plugins(devices={"MyLaser": MyLaser})
laser = daemon.add_device("laser1", "MyLaser", address="GPIB0::1")
daemon.connect_device(laser)

try:
    server.start(blocking=False)
    print("Server running at http://localhost:5000")
    laser.set_wavelength(1550.0)  # Local calls still work
    input("Press Enter to stop...")
finally:
    server.stop()
    daemon.shutdown()
```

## Remote Control

Use `ServerAPI` to control devices and execute tasks:

```python
from labdaemon.server import ServerAPI

api = ServerAPI("http://localhost:5000")

device = api.get_device("laser1")
print(f"Connected: {device['connected']}")

api.call_device_method("laser1", "set_wavelength", args=[1550.0])

api.execute_task("sweep1", "SweepTask", params={
    "laser_id": "laser1",
    "start_wl": 1550,
    "stop_wl": 1560,
    "steps": 11
})
```

## Error Handling

Device and task errors are recorded server-side and retrievable via API:

```python
error = api.get_device_error("laser1")
if error:
    print(f"Error: {error['message']}")
    api.clear_device_error("laser1")

task_error = api.get_task_error("sweep1")
if task_error:
    print(f"Task failed: {task_error['message']}")
```

Ownership conflicts return 409 Conflict with error details.

## Security

- Development: Bind `127.0.0.1` only
- Lab LAN: Bind specific interface; restrict via firewall to lab subnet
- Public networks: Do not expose—no authentication; arbitrary device control possible
- Remote access: Use VPN or SSH tunnels

## Deployment

For multi-server configurations and non-technical user management, see [Patterns Module - Server Management](patterns.md#server-management):

- Server Launcher GUI for point-and-click server control
- Configuration system for defining multiple server setups
- Configuration discovery with flexible search paths

## Reference

- [Server API Reference](server_api.md): HTTP/SSE endpoints, error codes, client examples
- [Core API Reference](core_api.md#labdaemonserver): LabDaemonServer class
- [Patterns Module](patterns.md): Client helpers and server management patterns
