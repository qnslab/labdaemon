# Interactive Tasks

Some tasks support runtime parameter updates. Implement `set_parameter(key, value)` and `get_parameter(key)` to enable this:

```python
class InteractiveSweep:
    def __init__(self, task_id: str, laser_id: str, **kwargs):
        self.task_id = task_id
        self.laser_id = laser_id
        self._sweep_speed = 1.0  # Default
        self.device_ids = [laser_id]  # Required for server use
    
    def set_parameter(self, key: str, value):
        """Update parameter while task is running."""
        if key == "sweep_speed":
            self._sweep_speed = value
    
    def get_parameter(self, key: str):
        """Query current parameter or state."""
        if key == "sweep_speed":
            return self._sweep_speed
        if key == "progress":
            return self._progress
    
    def run(self, context):
        for wl in wavelengths:
            if context.cancel_event.is_set():
                return {"status": "cancelled"}
            
            # Use current sweep speed
            delay = 1.0 / self._sweep_speed
            time.sleep(delay)
            
            # Do measurement...
```

The server exposes these methods via `/tasks/{task_id}/parameters` endpoints, allowing remote clients to adjust experiments in real time.