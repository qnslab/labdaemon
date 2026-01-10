# Part 3: Real-Time Streaming

Stream data from devices for monitoring and analysis.

**Use this when:** You need continuous data from an instrument (detector, ADC, sensor) rather than discrete reads. Useful for real-time monitoring, live plots, or buffering data during long experiments.

## Streaming Devices

A streaming device calls a callback function with data as it arrives. Implement three methods:

```python
import threading
import time

class SimpleDetector:
    def __init__(self, device_id: str, **kwargs):
        self.device_id = device_id
        self._streaming_thread = None
        self._stop_event = threading.Event()
        self._callback = None
    
    def connect(self):
        pass
    
    def disconnect(self):
        if self.is_streaming():
            self.stop_streaming()
    
    def start_streaming(self, callback, sample_rate: float = 10.0):
        if self.is_streaming():
            return
        
        self._callback = callback
        self._stop_event.clear()
        self._streaming_thread = threading.Thread(
            target=self._streaming_loop,
            args=(sample_rate,),
            daemon=True
        )
        self._streaming_thread.start()
    
    def stop_streaming(self, timeout=None):
        if not self.is_streaming():
            return
        
        self._stop_event.set()
        if self._streaming_thread:
            self._streaming_thread.join(timeout=timeout)
            self._streaming_thread = None
    
    def is_streaming(self) -> bool:
        return self._streaming_thread is not None and self._streaming_thread.is_alive()
    
    def _streaming_loop(self, sample_rate: float):
        try:
            while not self._stop_event.is_set():
                data = self._acquire_reading()
                if self._callback:
                    self._callback(data)
                self._stop_event.wait(timeout=1.0 / sample_rate)
        except Exception as e:
            print(f"Streaming error: {e}")
    
    def _acquire_reading(self) -> float:
        # Read from instrument
        import random
        return random.uniform(0.0, 100.0)
```

The callback runs in the streaming thread outside the device lock, so it won't block the device.

## Using Streaming Locally

Collect streamed data in a task or script:

```python
class DataCollectionTask:
    def __init__(self, task_id: str, detector_id: str, duration_seconds: float, **kwargs):
        self.task_id = task_id
        self.detector_id = detector_id
        self.duration_seconds = duration_seconds
    
    def run(self, context: ld.TaskContext):
        detector = context.daemon.get_device(self.detector_id)
        readings = []
        
        def on_reading(value):
            readings.append({
                "timestamp": time.time(),
                "value": value
            })
        
        context.daemon.start_streaming(detector, callback=on_reading, sample_rate=10.0)
        
        try:
            start_time = time.time()
            while time.time() - start_time < self.duration_seconds:
                if context.cancel_event.is_set():
                    return {"status": "cancelled"}
                time.sleep(0.1)
            
            return {
                "status": "completed",
                "readings": readings
            }
        finally:
            context.daemon.stop_streaming(detector)
```

## Remote Streaming via Python

Connect to a streaming device on a remote server:

```python
from labdaemon.server import SSEClient
import time

def on_event(event):
    if event.get('event') == 'device_data':
        print(f"Sequence {event['sequence']}: {event['payload']}")

client = SSEClient("http://localhost:5000", on_event=on_event)
client.start_device_stream("detector1")

# Stream runs in background
time.sleep(10.0)

client.stop_stream()
```

## Remote Streaming via JavaScript

Stream data in a web browser:

```javascript
const consumer = new EventSource('http://localhost:5000/stream/devices/detector1');

consumer.addEventListener('device_data', (e) => {
    const event = JSON.parse(e.data);
    console.log(`Sequence ${event.sequence}: ${event.payload}`);
    updateUI(event.payload);
});

consumer.onerror = (e) => {
    console.error('Stream error:', e);
    consumer.close();
};
```

## Key Points

- Callbacks run outside device lock: Long-running callbacks won't block the device
- Best-effort delivery: Remote clients may drop messages under load
- Server-side proxying: The server automatically proxies device streams to all connected SSE clients

## Next Steps

- [Part 4: Adding a Server](part4_add_a_server.md): Coordinate multiple tools accessing the same devices
- [Back to Tutorial](..) — Return to tutorial overview
- [Basic Streaming](../devices/basic-streaming.md) — Detailed streaming documentation
- [Advanced Streaming](../devices/advanced-streaming.md) — Thread safety, rate limiting, backpressure
