# Usage Idioms

Practical solutions for common LabDaemon problems. This document focuses on patterns and idioms—reusable approaches for solving recurring problems in experiment code.

## Contents

- [Device Abstraction](#device-abstraction)
- [Performance Optimization](#performance-optimization)
- [Common Pitfalls and Solutions](#common-pitfalls-and-solutions)

# Device Abstraction

Write experiments that work with different hardware by coding against interfaces rather than specific implementations.

### Duck Typing Pattern

```python
class FlexibleSweepTask:
    def run(self, context):
        source = context.daemon.get_device(self.source_id)
        detector = context.daemon.get_device(self.detector_id)
        
        # Works with any source that has set_output()
        # and any detector that has read()
        for value in self.sweep_values:
            source.set_output(value)
            reading = detector.read()
            results.append({"value": value, "reading": reading})
```

### Protocol-Based Interfaces

```python
from typing import Protocol

class TunableSource(Protocol):
    def set_frequency(self, freq: float) -> None: ...
    def get_frequency(self) -> float: ...

class PowerMeter(Protocol):
    def read_power(self) -> float: ...
    def set_range(self, range_dbm: float) -> None: ...

# Task works with any conforming devices
def run(self, context):
    source: TunableSource = context.daemon.get_device(self.source_id)
    meter: PowerMeter = context.daemon.get_device(self.meter_id)
```

### Mock Devices for Testing

```python
class MockLaser:
    def __init__(self, device_id: str):
        self.device_id = device_id
        self._wavelength = 1550.0
        self._power = 10.0
    
    def connect(self): pass
    def disconnect(self): pass
    
    def set_wavelength(self, wl: float):
        self._wavelength = wl
    
    def get_power(self) -> float:
        return self._power + random.gauss(0, 0.1)  # Add noise

# Use in tests
daemon.register_plugins(devices={"MockLaser": MockLaser})
```

### Configuration-Driven Device Selection

```python
# In lab_servers.py - different setups for different environments
def setup_production_server(daemon):
    daemon.register_plugins(devices={"SantecLaser": SantecLaser})
    daemon.add_device("laser1", "SantecLaser", ip="192.168.1.100")

def setup_development_server(daemon):
    daemon.register_plugins(devices={"MockLaser": MockLaser})
    daemon.add_device("laser1", "MockLaser")

# Server startup scripts call the appropriate setup function
# Tasks work with either implementation without code changes
```

# Performance Optimization

### Batch Operations

```python
class BatchDevice:
    """Device that supports batch operations."""
    
    def set_multiple(self, **kwargs):
        """Set multiple parameters in one call."""
        commands = []
        for param, value in kwargs.items():
            commands.append(f"{param.upper()} {value}")
        
        # Send all commands at once
        self._instrument.write(";".join(commands))
    
    # Usage
    device.set_multiple(wavelength=1550.0, power=10.0, temperature=25.0)
```

### Streaming with Rate Limiting

```python
class RateLimitedStreamer:
    def __init__(self, max_rate=100):  # Hz
        self.max_rate = max_rate
        self.min_interval = 1.0 / max_rate
        self.last_time = 0
    
    def _streaming_loop(self):
        while not self._stop_event.is_set():
            current_time = time.time()
            
            # Rate limiting
            elapsed = current_time - self.last_time
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            
            # Acquire and send data
            data = self._acquire_data()
            if self._callback:
                self._callback(data)
            
            self.last_time = time.time()
```

## Common Pitfalls and Solutions

### Blocking in Callbacks

Don't perform long operations in streaming callbacks:

```python
# BAD - blocks streaming thread
def data_callback(data):
    result = slow_processing(data)  # Blocks!
    database.save(result)

# GOOD - offload to worker thread
import queue
import threading

def data_callback(data):
    work_queue.put(data)

def worker_thread():
    while True:
        data = work_queue.get()
        result = slow_processing(data)
        database.save(result)

# Start worker thread
work_queue = queue.Queue()
threading.Thread(target=worker_thread, daemon=True).start()
device.start_streaming(callback=data_callback)
```

### Forgetting Device Ownership

Remember to declare device ownership in server tasks:

```python
class MyTask:
    def __init__(self, task_id: str, laser_id: str, daq_id: str):
        self.task_id = task_id
        self.laser_id = laser_id
        self.daq_id = daq_id
        self.device_ids = [laser_id, daq_id]  # IMPORTANT: Declare ownership
```
