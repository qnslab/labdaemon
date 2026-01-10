# Part 4: Adding a Server

Coordinate multiple tools accessing the same devices without conflicts.

**Use this when:** Multiple tools need to access the same devices—a script running complex workflows, an existing GUI monitoring the same laser, a web dashboard viewing real-time data—without forcing connect/disconnect cycles. The server keeps devices accessible to all clients and prevents accidental conflicts when multiple tools try to control the same device. You can also use the server to expose your lab instruments over the network for remote access from other machines.

## Starting a Server

Wrap your daemon with a server to expose it via HTTP and SSE:

```python
import labdaemon as ld
from labdaemon.server import LabDaemonServer

# Create daemon and register devices/tasks as usual
daemon = ld.LabDaemon()
daemon.register_plugins(devices={"MyLaser": MyLaser, "SimpleDetector": SimpleDetector})

# Add devices
laser = daemon.add_device("laser1", "MyLaser", address="GPIB0::1")
detector = daemon.add_device("detector1", "SimpleDetector")
daemon.connect_device(laser)
daemon.connect_device(detector)

# Start server
server = LabDaemonServer(daemon, host="0.0.0.0", port=5000)
server.start(blocking=False)

print("Server running at http://localhost:5000")

try:
    # Local code can still use devices
    laser.set_wavelength(1550.0)
    
    # Keep server running
    input("Press Enter to stop...")
finally:
    server.stop()
    daemon.shutdown()
```

## Device Ownership for Multi-Client Safety

When multiple clients connect to the same server, they could race. The server prevents this via device ownership.

Tasks can declare which devices they need. The server will atomically claim those devices for the duration of the task. Other clients trying to call methods on owned devices get a 409 Conflict error.

```python
class MeasurementTask:
    def __init__(self, task_id: str, laser_id: str, detector_id: str, **kwargs):
        self.task_id = task_id
        self.laser_id = laser_id
        self.detector_id = detector_id
        self.device_ids = [laser_id, detector_id]  # Declare ownership
    
    def run(self, context: ld.TaskContext):
        laser = context.daemon.get_device(self.laser_id)
        detector = context.daemon.get_device(self.detector_id)
        
        # These devices are now locked to this task
        # Other clients cannot call methods on them
        
        laser.set_wavelength(1550.0)
        reading = detector.read()
        
        return {"wavelength": 1550.0, "reading": reading}
```

Register the task:

```python
daemon.register_plugins(tasks={"MeasurementTask": MeasurementTask})
```

Now when a client executes this task, the devices are protected.

**Note:** Device ownership is optional for local scripts but strongly recommended when using a server with multiple clients.

## Controlling Remotely via Python

Use the `ServerAPI` client to control devices and execute tasks remotely:

```python
from labdaemon.server import ServerAPI

api = ServerAPI("http://localhost:5000")

# List devices
devices = api.list_devices()
print(f"Available devices: {devices}")

# Get device info
laser_info = api.get_device("laser1")
print(f"Laser connected: {laser_info['connected']}")

# Call device methods
api.call_device_method("laser1", "set_wavelength", args=[1560.0])

# Execute task
api.execute_task("measurement1", "MeasurementTask",
                 params={"laser_id": "laser1", "detector_id": "detector1"})

# Check task status
task = api.get_task("measurement1")
print(f"Task status: {task['status']}")

# Cancel task
api.cancel_task("measurement1")
```

## Controlling Remotely via HTTP

Make HTTP requests directly:

```bash
# Get device info
curl http://localhost:5000/devices/laser1

# Call a method
curl -X POST http://localhost:5000/devices/laser1/call \
  -H "Content-Type: application/json" \
  -d '{"method": "set_wavelength", "args": [1560.0]}'

# Execute a task
curl -X POST http://localhost:5000/tasks \
  -H "Content-Type: application/json" \
  -d '{"task_id": "measurement1", "task_type": "MeasurementTask", "params": {"laser_id": "laser1", "detector_id": "detector1"}}'

# Stream device data (Server-Sent Events)
curl http://localhost:5000/stream/devices/detector1
```

## Web Dashboard

Create a simple web dashboard to monitor experiments:

```html
<!DOCTYPE html>
<html>
<head>
    <title>Lab Dashboard</title>
    <style>
        body { font-family: sans-serif; margin: 20px; }
        .device { border: 1px solid #ccc; padding: 10px; margin: 10px 0; }
        .stream { color: #00aa00; font-family: monospace; }
    </style>
</head>
<body>
    <h1>LabDaemon Dashboard</h1>
    
    <div id="devices"></div>
    <div id="detector-stream" class="stream"></div>
    
    <script>
        const api = "http://localhost:5000";
        
        async function updateDevices() {
            const resp = await fetch(`${api}/devices`);
            const devices = await resp.json();
            
            const html = devices.map(d => `
                <div class="device">
                    <strong>${d.device_id}</strong>
                    <p>Status: ${d.connected ? "Connected" : "Disconnected"}</p>
                </div>
            `).join('');
            
            document.getElementById('devices').innerHTML = html;
        }
        
        function streamDetector() {
            const stream = new EventSource(`${api}/stream/devices/detector1`);
            
            stream.addEventListener('device_data', (e) => {
                const event = JSON.parse(e.data);
                const log = document.getElementById('detector-stream');
                log.innerHTML += `[${event.sequence}] ${event.payload}<br>`;
                log.scrollTop = log.scrollHeight;
            });
        }
        
        updateDevices();
        setInterval(updateDevices, 2000);
        streamDetector();
    </script>
</body>
</html>
```

## Security

For development, bind to localhost only:

```python
server = LabDaemonServer(daemon, host="127.0.0.1", port=5000)
```

For lab network access, bind to a specific interface:

```python
server = LabDaemonServer(daemon, host="192.168.1.50", port=5000)
```

**Never** expose LabDaemon directly to untrusted networks—there is no authentication. If you need remote access outside your lab, use a VPN or SSH tunnel.

## Next Steps

- [Back to Tutorial](..) — Return to tutorial overview
- [Concepts](../concepts.md) — Deep dive into architecture
- [Server API Reference](../server_api.md) — Complete HTTP/SSE API
- [Cheat Sheet](../cheat_sheet.md) — Quick code reference
