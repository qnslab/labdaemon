<p align="center">
  <img src="mascot-200.png" alt="LabDaemon Mascot" width="150">
</p>

# LabDaemon

Write device drivers and tasks once, run everywhere. Start with simple scripts and painlessly move to GUI and then server. Plain Python device classes, safe concurrency, reusable across scripts, GUIs, and automated experiments. Optional HTTP/SSE server for remote access and multi-client coordination.

## Why LabDaemon?

- **Write once, run anywhere:** Same device code works in scripts, GUIs, and web interfaces
- **Thread-safe by default:** Automatic per-device locking lets you write simple single-threaded code
- **Progressive complexity:** Start local, add server when you need remote access
- **Plain Python classes:** No framework lock-in or inheritance hierarchies
- **Real-world tested:** Designed for research labs with GPIB, DAQs, lasers, and detectors

## Documentation

[LabDaemon docs](https://docs.samsci.com/labdaemon/)

[LabDaemon template](https://github.com/qnslab/labdaemon-template) - Structuring lab code around this framework

## Quick Start

### Local Script

```python
import labdaemon as ld

class MyLaser:
    def __init__(self, device_id: str, address: str, **kwargs):
        self.device_id = device_id
        self.address = address
        self._instrument = None
    
    def connect(self):
        import pyvisa
        rm = pyvisa.ResourceManager()
        self._instrument = rm.open_resource(self.address)
    
    def disconnect(self):
        if self._instrument:
            self._instrument.close()
    
    def set_wavelength(self, wl: float):
        self._instrument.write(f'WAVELENGTH {wl}')

# Use it
daemon = ld.LabDaemon()
daemon.register_plugins(devices={"MyLaser": MyLaser})

with daemon.device_context("laser1", "MyLaser", address="GPIB0::1") as laser:
    laser.set_wavelength(1550.0)

daemon.shutdown()
```

### Add Server for Remote Access

```python
from labdaemon.server import LabDaemonServer

daemon = ld.LabDaemon()
server = LabDaemonServer(daemon, host="0.0.0.0", port=5000)

# Same device code, now accessible via HTTP
daemon.register_plugins(devices={"MyLaser": MyLaser})
laser = daemon.add_device("laser1", "MyLaser", address="GPIB0::1")
daemon.connect_device(laser)

try:
    server.start(blocking=False)
    print("Server running at http://localhost:5000")
    
    # Control locally OR via HTTP/SSE
    laser.set_wavelength(1550.0)
    
    input("Press Enter to stop...")
finally:
    server.stop()
    daemon.shutdown()
```

## Installation

```bash
pip install labdaemon[server]
```