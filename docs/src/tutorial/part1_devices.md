# Part 1: Basic Device Control

Write a device driver and use it to control an instrument.

**Use this when:** You need to wrap an instrument for use in scripts, GUIs, or interactive sessions. Devices are the foundation—every experiment starts here.

## Writing a Device

A device is a plain Python class with three required methods: `__init__`, `connect`, and `disconnect`.

```python
import pyvisa

class MyLaser:
    def __init__(self, device_id: str, address: str, **kwargs):
        self.device_id = device_id
        self.address = address
        self._instrument = None
    
    def connect(self):
        rm = pyvisa.ResourceManager()
        self._instrument = rm.open_resource(self.address)
    
    def disconnect(self):
        if self._instrument:
            self._instrument.close()
            self._instrument = None
    
    def set_wavelength(self, wl: float):
        self._instrument.write(f'WAVELENGTH {wl}')
    
    def get_wavelength(self) -> float:
        return float(self._instrument.query('WAVELENGTH?'))
```

The `__init__` method receives configuration from the framework. The `connect` and `disconnect` methods handle lifecycle. Everything else is your device logic.

## Using a Device Locally

Register your device with the daemon and use it:

```python
import labdaemon as ld

daemon = ld.LabDaemon()
daemon.register_plugins(devices={"MyLaser": MyLaser})

# Add device
laser = daemon.add_device("laser1", "MyLaser", address="GPIB0::1")

# Connect
daemon.connect_device(laser)

# Use it
laser.set_wavelength(1550.0)
wl = laser.get_wavelength()
print(f"Wavelength: {wl}")

# Disconnect
daemon.disconnect_device(laser)
daemon.shutdown()
```

Or use a context manager for automatic cleanup:

```python
with daemon.device_context("laser1", "MyLaser", address="GPIB0::1") as laser:
    laser.set_wavelength(1550.0)
    wl = laser.get_wavelength()
```

## Thread Safety

All public methods (no leading underscore) are automatically wrapped with locks. You don't need to worry about thread safety—just write synchronous code:

```python
def set_wavelength(self, wl: float):
    # Framework automatically wraps this with a lock
    self._instrument.write(f'WAVELENGTH {wl}')
```

Multiple threads calling device methods will be serialized by the framework. This means your device never needs explicit locking.

## Next Steps

- [Part 2: Background Tasks](part2_tasks.md): Run experiments without blocking
- [Back to Tutorial](..) — Return to tutorial overview
- [Device Basics](../devices/device-basics.md) — Writing more complex devices
- [Concepts](../concepts.md) — Understand the architecture
