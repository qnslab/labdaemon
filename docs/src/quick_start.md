# Quick Start

A five-minute introduction to LabDaemon's core concepts. For more detailed examples, see the tutorial below.

## The Basics

LabDaemon manages two things:

1. **Devices** - Plain Python classes wrapping lab instruments
2. **Tasks** - Background functions that coordinate devices

Here's a minimal example:

```python
import labdaemon as ld

# Define a device
class MyLaser:
    def __init__(self, device_id: str, address: str, **kwargs):
        self.device_id = device_id
        self.address = address
        self._instrument = None
    
    def connect(self):
        # Open connection
        pass
    
    def disconnect(self):
        # Close connection
        pass
    
    def set_wavelength(self, wl: float):
        pass

# Use it locally
daemon = ld.LabDaemon()
daemon.register_plugins(devices={"MyLaser": MyLaser})

with daemon.device_context("laser1", "MyLaser", address="GPIB0::1") as laser:
    laser.set_wavelength(1550.0)

daemon.shutdown()
```

That's it. The framework handles thread safety automatically—you just write synchronous code.

## Adding a Background Task

For long-running experiments, use tasks to keep your application responsive:

```python
class WavelengthSweepTask:
    def __init__(self, task_id: str, laser_id: str, start_wl: float, stop_wl: float, steps: int, **kwargs):
        self.task_id = task_id
        self.laser_id = laser_id
        self.start_wl = start_wl
        self.stop_wl = stop_wl
        self.steps = steps
    
    def run(self, context: ld.TaskContext):
        laser = context.daemon.get_device(self.laser_id)
        
        for i, wl in enumerate(wavelengths):
            # Check for cancellation
            if context.cancel_event.is_set():
                return {"status": "cancelled"}
            
            laser.set_wavelength(wl)
        
        return {"status": "completed"}

daemon.register_plugins(tasks={"WavelengthSweepTask": WavelengthSweepTask})

# Runs in background; main thread remains responsive
handle = daemon.execute_task("sweep1", "WavelengthSweepTask", 
                              laser_id="laser1", 
                              start_wl=1540, stop_wl=1560, steps=21)
result = handle.wait()
```

## Adding a Server

To enable remote access, wrap the daemon with a server:

```python
from labdaemon.server import LabDaemonServer

server = LabDaemonServer(daemon, host="0.0.0.0", port=5000)
server.start()

# Now control devices via HTTP from anywhere:
# curl http://localhost:5000/devices/laser1
# POST /tasks to execute tasks
```

## Next: Detailed Tutorial

For step-by-step walkthrough with real code, see the **[Tutorial](tutorial/README.md)** (4 parts, ~15 minutes).

## Next Steps

- [Concepts](concepts.md) — Understand the architecture
- [Core API](core_api.md) — Full Python API reference
- [Cheat Sheet](cheat_sheet.md) — Quick code reference
