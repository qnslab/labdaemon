# Task Basics

## Writing a Task

```python
class WavelengthSweep:
    def __init__(self, task_id: str, laser_id: str, detector_id: str,
                 start_wl: float, stop_wl: float, steps: int, **kwargs):
        self.task_id = task_id
        self.laser_id = laser_id
        self.detector_id = detector_id
        self.start_wl = start_wl
        self.stop_wl = stop_wl
        self.steps = steps
        self.device_ids = [laser_id, detector_id]  # Required for server use
    
    def run(self, context: TaskContext):
        """Execute in background thread."""
        laser = context.daemon.get_device(self.laser_id)
        detector = context.daemon.get_device(self.detector_id)
        
        results = []
        wavelengths = [
            self.start_wl + i * (self.stop_wl - self.start_wl) / (self.steps - 1)
            for i in range(self.steps)
        ]
        
        for wl in wavelengths:
            # Check for cancellation
            if context.cancel_event.is_set():
                return {"status": "cancelled", "results": results}
            
            laser.set_wavelength(wl)
            power = detector.get_power()
            results.append((wl, power))
        
        return {"status": "completed", "results": results}
```

The `run` method receives a context with two key attributes: `context.daemon` (to access devices) and `context.cancel_event` (to check if the user cancelled the task). All device access is automatically thread-safe because the daemon serializes calls to each device.

## Device Ownership

When using the server, declare which devices your task needs by setting `self.device_ids` in `__init__`:

```python
class WavelengthSweep:
    def __init__(self, task_id: str, laser_id: str, detector_id: str, ...):
        self.task_id = task_id
        self.laser_id = laser_id
        self.detector_id = detector_id
        self.device_ids = [laser_id, detector_id]  # Required for server use
```

This declaration is required when using the server but optional for local scripts. Without it, the server cannot enforce device ownership and prevent conflicts between multiple clients.

The server will atomically claim these devices before starting your task and release them when the task completes. This prevents other clients from interfering with your experiment. If another client tries to control an owned device, they get a 409 Conflict response. Queries are always allowed—only commands are blocked.

## Cancellation and Error Handling

Always check `context.cancel_event` in long loops. This lets users stop experiments gracefully:

```python
def run(self, context):
    for i, wl in enumerate(wavelengths):
        if context.cancel_event.is_set():
            logger.warning(f"Cancelled at step {i+1}")
            return {"status": "cancelled", "step": i}
        
        # Do work...
```

Tasks run in background threads, so exceptions don't propagate to the caller. Instead, catch exceptions and return them in your result:

```python
def run(self, context):
    try:
        result = self._do_measurement(context)
        return {"status": "completed", "data": result}
    except Exception as e:
        logger.exception(f"Task failed: {e}")
        return {"status": "failed", "error": str(e)}
```

The daemon stores these errors centrally for retrieval via the API or for local inspection via `handle.exception()`.