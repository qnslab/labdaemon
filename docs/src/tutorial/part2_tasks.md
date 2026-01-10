# Part 2: Background Tasks

Run long experiments in the background without blocking the main thread.

**Use this when:** You need to run operations longer than ~1 second, enable GUIs to stay responsive, or coordinate multiple devices.

## Writing a Task

A task is a class with an `__init__` method and a `run` method. The `run` method receives a context object with access to the daemon and a cancellation event:

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
        
        wavelengths = [self.start_wl + (self.stop_wl - self.start_wl) * i / (self.steps - 1) 
                       for i in range(self.steps)]
        
        for wl in wavelengths:
            # Check for cancellation
            if context.cancel_event.is_set():
                return {"status": "cancelled"}
            
            laser.set_wavelength(wl)
        
        return {"status": "completed"}
```

## Executing a Task

Register and execute the task:

```python
daemon.register_plugins(tasks={"WavelengthSweepTask": WavelengthSweepTask})

# Execute in background
handle = daemon.execute_task("sweep1", "WavelengthSweepTask",
                             laser_id="laser1",
                             start_wl=1540, stop_wl=1560, steps=21)

# Main thread is now free to do other work
print("Sweep running in background...")

# Wait for completion
result = handle.wait()
print(f"Result: {result}")
```

## Handling Cancellation

Tasks should check `context.cancel_event` periodically to allow graceful cancellation:

```python
def run(self, context):
    for iteration in range(1000):
        if context.cancel_event.is_set():
            return {"status": "cancelled", "iterations": iteration}
        
        # Do work
        self._run_iteration()
        
        # Give cancellation a chance to be noticed
        time.sleep(0.1)
    
    return {"status": "completed"}
```

Users can cancel a running task via:

```python
# From the main thread
handle.cancel()

# Or via server API
api.cancel_task("sweep1")
```

## Device Ownership (Server Only)

When using the server, declare device dependencies via `device_ids`. The server will prevent other clients from accessing owned devices while the task runs:

```python
class ExclusiveTask:
    def __init__(self, task_id: str, laser_id: str, daq_id: str, **kwargs):
        self.task_id = task_id
        self.laser_id = laser_id
        self.daq_id = daq_id
        self.device_ids = [laser_id, daq_id]  # Declare ownership
    
    def run(self, context):
        laser = context.daemon.get_device(self.laser_id)
        daq = context.daemon.get_device(self.daq_id)
        
        # Do work—other clients cannot access these devices
        laser.set_wavelength(1550.0)
        # ...
```

This is optional for local scripts but recommended when using a server with multiple clients.

## Next Steps

- [Part 3: Real-Time Streaming](part3_streaming.md): Stream data from devices
- [Back to Tutorial](..) — Return to tutorial overview
- [Task Basics](../tasks/task-basics.md) — Detailed task documentation
- [Task Composition](../tasks/composition.md) — Coordinate multiple tasks
