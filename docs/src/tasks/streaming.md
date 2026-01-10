# Task Progress Streaming

For long-running tasks, you can stream progress updates to clients in real-time using a virtual streaming device. This creates a lightweight device that clients can subscribe to via Server-Sent Events.

## The Virtual Stream Device

First, here's a simple virtual device implementation:

```python
from typing import Any, Callable, Optional

class VirtStreamDevice:
    """Virtual device for streaming task progress/data."""
    
    def __init__(self, device_id: str, **kwargs):
        self.device_id = device_id
        self._callback: Optional[Callable[[Any], None]] = None
        self._streaming = False
        # Note: LabDaemon will automatically wrap all public methods with thread-safe locking
    
    def connect(self):
        """No connection needed - virtual device."""
        pass
    
    def disconnect(self):
        """Stop streaming if active."""
        if self._streaming:
            self.stop_streaming()
    
    def start_streaming(self, callback: Callable[[Any], None]) -> None:
        """Start streaming with the given callback."""
        self._callback = callback
        self._streaming = True
    
    def stop_streaming(self, timeout: Optional[float] = None) -> None:
        """Stop streaming."""
        self._streaming = False
        self._callback = None
    
    def is_streaming(self) -> bool:
        """Check if streaming is active."""
        return self._streaming
    
    def send_data(self, data: Any) -> None:
        """Send data to all subscribed SSE clients."""
        if self._streaming and self._callback:
            # The callback is provided by the SSEManager and will
            # queue the data for transmission to all connected clients
            self._callback(data)
```

## Using the Virtual Device in Tasks

```python
class LongRunningTask:
    def __init__(self, task_id: str, device_id: str, enable_streaming: bool = False, **kwargs):
        self.task_id = task_id
        self.device_id = device_id
        self.enable_streaming = enable_streaming
        self.device_ids = [device_id]  # Required for server use
    
    def run(self, context: TaskContext):
        # Create virtual streaming device if enabled
        stream = None
        if self.enable_streaming:
            stream_device_id = f"stream-{self.task_id}"
            stream = context.daemon.add_device(
                stream_device_id, 
                VirtStreamDevice
            )
            context.daemon.connect_device(stream_device_id)
            # Start streaming so clients can connect
            context.daemon.start_streaming(stream)
        
        total_steps = 1000
        for i in range(total_steps):
            if context.cancel_event.is_set():
                return {"status": "cancelled", "progress": i}
            
            # Do work...
            result = self._process_step(i)
            
            # Stream progress update
            if stream:
                progress_data = {
                    "step": i,
                    "total": total_steps,
                    "progress_percent": (i / total_steps) * 100,
                    "current_result": result,
                    "message": f"Processing step {i}/{total_steps}"
                }
                stream.send_data(progress_data)  # Send to SSE clients
        
        return {"status": "completed", "total_steps": total_steps}
```

## Client-Side Subscription

Clients can subscribe to task updates using the same SSE pattern as device streams:

```javascript
// After starting the task, get its stream
const taskStream = new EventSource(
    `http://localhost:5000/stream/devices/stream-${taskId}`
);

taskStream.addEventListener('device_data', (e) => {
    const update = JSON.parse(e.data);
    console.log(`Progress: ${update.progress_percent.toFixed(1)}%`);
    console.log(`Message: ${update.message}`);
    
    // Update progress bar
    progressBar.value = update.progress_percent;
});
```

## Key Points

- The virtual device implements the same streaming interface as real devices
- Create it with a unique name like `stream-{task_id}` to avoid conflicts
- Use `send_data()` to push updates to all subscribed clients
- Send updates as JSON objects for structured data
- The device is automatically cleaned up when the daemon shuts down
- This pattern is optional - tasks work normally without streaming
- Multiple clients can subscribe to the same task stream simultaneously

This approach keeps your task logic simple while providing powerful real-time feedback capabilities.