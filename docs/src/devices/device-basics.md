# Devices

Devices are plain Python classes that represent your laboratory instruments. They're the foundation of LabDaemon—no framework inheritance, no decorators, just your code wrapped with automatic thread safety and lifecycle management.

## Writing a Device

A device needs three essential methods: `__init__`, `connect`, and `disconnect`. Here's the minimal structure:

```python
class MyLaser:
    def __init__(self, device_id: str, address: str, **kwargs):
        self.device_id = device_id
        self.address = address
        self._instrument = None
    
    def connect(self):
        # Connect to hardware
        pass
    
    def disconnect(self):
        # Clean up
        pass
    
    def set_wavelength(self, wl: float):
        # Your device methods
        pass
```

That's it. The framework handles the rest.

### Understanding the Three Methods

**`__init__(device_id, address, **kwargs)`** - Store configuration without touching hardware. The `device_id` is injected by the framework. Additional parameters come from `daemon.add_device()`.

**`connect()`** - Establish the hardware connection. Can fail, be retried, or be deferred. Called explicitly by the user or framework.

**`disconnect()`** - Clean up the connection. Must be idempotent (safe to call multiple times). Called during shutdown or error handling.

### Real Example with PyVISA

```python
import pyvisa

class MyLaser:
    def __init__(self, device_id: str, address: str, **kwargs):
        self.device_id = device_id
        self.address = address
        self._instrument = None
    
    def connect(self):
        try:
            rm = pyvisa.ResourceManager()
            self._instrument = rm.open_resource(self.address)
            self._instrument.query("*IDN?")  # Verify connection
        except Exception as e:
            raise ConnectionError(f"Failed to connect to {self.address}: {e}")
    
    def disconnect(self):
        if self._instrument:
            try:
                self._instrument.close()
            except:
                pass  # Ignore errors during cleanup
            finally:
                self._instrument = None
    
    def set_wavelength(self, wl: float):
        if not self._instrument:
            raise RuntimeError("Device not connected")
        self._instrument.write(f'WAVELENGTH {wl}')
    
    def get_wavelength(self) -> float:
        if not self._instrument:
            raise RuntimeError("Device not connected")
        return float(self._instrument.query('WAVELENGTH?'))
    
    def get_power(self) -> float:
        if not self._instrument:
            raise RuntimeError("Device not connected")
        return float(self._instrument.query('POWER?'))
```

## Using Devices

### Local Script

```python
import labdaemon as ld

daemon = ld.LabDaemon()
daemon.register_plugins(devices={"MyLaser": MyLaser})

# Automatic cleanup with context manager
with daemon.device_context("laser1", "MyLaser", address="GPIB0::1") as laser:
    laser.set_wavelength(1550.0)
    power = laser.get_power()

daemon.shutdown()
```

### Manual Lifecycle

```python
laser = daemon.add_device("laser1", "MyLaser", address="GPIB0::1")
daemon.connect_device(laser)

try:
    laser.set_wavelength(1550.0)
finally:
    daemon.disconnect_device(laser)
    daemon.shutdown()
```

## Thread Safety

The framework automatically wraps all public methods (no leading underscore) with re-entrant locks. Multiple threads calling device methods concurrently will be serialized, so write code as if you're single-threaded.

If your device owns background threads (like streaming devices), use the injected `self._ld_lock` to protect shared state.

## Connect Configuration

If you want to set device config parameters on the fly/at runtime (e.g. the laser `address` parameter above, after `add_device` but before `connect`), you can do so simply with a custom device method. 
Having these device configuration options directly in the `add_device`/`init` method can just make the logic cleaner for simpler applications/scripts.

This is a pattern, not a framework requirement. 
As a device writer, add whatever configuration approach make sense for your hardware. 
Just call them via the remote API using `call_device_method()`.

```python
# Remote usage:
api.call_device_method("laser1", "set_connection_id", args=["TCPIP0::192.168.1.100::inst0::INSTR"])
api.connect_device("laser1")
```

## See Also

- [Basic Streaming](basic-streaming.md) - Essential streaming patterns and implementations
- [Advanced Streaming](advanced-streaming.md) - Complex streaming patterns, thread safety, and real hardware examples
- [Concepts](../concepts.md) - Architecture and design philosophy
