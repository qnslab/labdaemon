# Device Interfaces

Device abstraction lets you write experiments that work with any hardware implementing the expected interface. Swap laser models, DAQ cards, or cameras without changing measurement logic.

## The Problem

You write an ODMR measurement that controls an RF generator, pulse sequencer, and camera. Later you upgrade the RF generator or switch to a different camera. Without abstraction, you rewrite measurement code. With interfaces, you swap device implementations and everything works.

## Duck Typing Approach

The simplest approach is duck typing—if it has the methods you need, it works:

```python
# Two different laser implementations
class TunicsLaser:
    def set_wavelength(self, wl: float): ...
    def get_wavelength(self) -> float: ...
    def get_power(self) -> float: ...

class SantecLaser:
    def set_wavelength(self, wl: float): ...
    def get_wavelength(self) -> float: ...
    def get_power(self) -> float: ...

# Task works with either
class WavelengthSweepTask:
    def run(self, context):
        laser = context.daemon.get_device(self.laser_id)
        # Works with any device that has these methods
        laser.set_wavelength(1550.0)
        power = laser.get_power()
```

This works well when device interfaces are naturally similar. Both lasers need wavelength control, so they implement similar methods.

## Protocol-Based Interfaces

For more complex interfaces, Python protocols provide structure:

```python
from typing import Protocol

class LaserProtocol(Protocol):
    def set_wavelength(self, wl: float) -> None: ...
    def get_wavelength(self) -> float: ...
    def get_power(self) -> float: ...
    def is_stable(self) -> bool: ...

class SpectrometerProtocol(Protocol):
    def set_integration_time(self, time_ms: float) -> None: ...
    def acquire_spectrum(self) -> dict: ...

# Devices implement protocols implicitly
class TunicsLaser:  # Implements LaserProtocol
    def set_wavelength(self, wl: float): ...
    def get_wavelength(self) -> float: ...
    def get_power(self) -> float: ...
    def is_stable(self) -> bool: ...

# Tasks declare expected interfaces
class SpectroscopyTask:
    def __init__(self, laser_id: str, spec_id: str):
        self.laser_id = laser_id
        self.spec_id = spec_id
        self.device_ids = [laser_id, spec_id]
    
    def run(self, context):
        # Type hints help but aren't enforced at runtime
        laser: LaserProtocol = context.daemon.get_device(self.laser_id)
        spec: SpectrometerProtocol = context.daemon.get_device(self.spec_id)
```

Protocols document expected interfaces without runtime enforcement. Type checkers can verify compatibility.

## Inheritance-Based Interfaces

For shared implementation, use abstract base classes:

```python
from abc import ABC, abstractmethod

class BaseDAQ(ABC):
    @abstractmethod
    def configure_channels(self, channels: list) -> None: ...
    
    @abstractmethod
    def start_acquisition(self) -> None: ...
    
    @abstractmethod
    def read_data(self) -> dict: ...
    
    # Shared implementation
    def acquire_samples(self, n_samples: int) -> list:
        data = []
        self.start_acquisition()
        for _ in range(n_samples):
            reading = self.read_data()
            data.append(reading)
        return data

class NIDaqDevice(BaseDAQ):
    def configure_channels(self, channels: list): ...
    def start_acquisition(self): ...
    def read_data(self) -> dict: ...
    # acquire_samples() inherited

class PicoscopeDevice(BaseDAQ):
    def configure_channels(self, channels: list): ...
    def start_acquisition(self): ...
    def read_data(self) -> dict: ...
    # acquire_samples() inherited
```

Use inheritance when devices share substantial implementation or when you want to enforce interfaces strictly.


## Configuration Strategies

Device interfaces work best when configuration is handled consistently:

```python
# Bad: Different configuration patterns
laser1 = TunicsLaser(address="COM3", baud=9600)
laser2 = SantecLaser(ip="192.168.1.100", port=8000)

# Better: Common configuration pattern
class LaserConfig:
    def __init__(self, connection_type: str, **params):
        self.connection_type = connection_type
        self.params = params

class TunicsLaser:
    def __init__(self, device_id: str, config: LaserConfig):
        if config.connection_type != "serial":
            raise ValueError("Tunics requires serial connection")
        self.port = config.params["port"]
        self.baud = config.params["baud"]

class SantecLaser:
    def __init__(self, device_id: str, config: LaserConfig):
        if config.connection_type != "ethernet":
            raise ValueError("Santec requires ethernet connection")
        self.ip = config.params["ip"]
        self.port = config.params["port"]
```

Consistent configuration patterns make device swapping easier.

## When to Use Interfaces

Device interfaces add complexity. Use them when:

- You frequently swap hardware implementations
- Multiple people work with different equipment versions
- Measurements should work across different lab setups

Don't use interfaces for one-off devices or when flexibility isn't needed. Simple, direct device classes often work better for unique instruments.

## Interface Design Guidelines

Good interfaces are minimal and focused:

```python
# Good: Focused interface
class TunableLaser(Protocol):
    def set_wavelength(self, wl: float) -> None: ...
    def get_wavelength(self) -> float: ...

# Bad: Kitchen sink interface
class ComplexLaser(Protocol):
    def set_wavelength(self, wl: float) -> None: ...
    def get_wavelength(self) -> float: ...
    def set_power(self, power: float) -> None: ...
    def get_power(self) -> float: ...
    def calibrate(self) -> None: ...
    def self_test(self) -> bool: ...
    def get_temperature(self) -> float: ...
    def reset(self) -> None: ...
```

Small interfaces are easier to implement and test. Compose multiple small interfaces rather than creating large ones.
