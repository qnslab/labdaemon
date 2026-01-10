# Basic Streaming

Streaming devices push data continuously via callbacks. This page covers the essential patterns needed to implement and consume streaming devices.

## The Streaming Interface

All streaming devices implement three methods:

```python
class StreamingDevice:
    def start_streaming(self, callback, **kwargs):
        """Start pushing data to callback: callback(data)"""
        pass
    
    def stop_streaming(self, timeout=None):
        """Stop streaming (idempotent)."""
        pass
    
    def is_streaming(self) -> bool:
        """Check if currently streaming."""
        pass
```

The callback runs in the device's streaming thread, **outside the device lock**, so it won't block the device.

## Basic Implementation

```python
import threading
import time

class StreamingDAQ:
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
        self._callback = None
    
    def is_streaming(self) -> bool:
        return self._streaming_thread is not None and self._streaming_thread.is_alive()
    
    def _streaming_loop(self, sample_rate: float):
        try:
            while not self._stop_event.is_set():
                data = self._acquire_sample()
                if self._callback:
                    self._callback(data)
                self._stop_event.wait(timeout=1.0 / sample_rate)
        except Exception as e:
            print(f"Streaming error: {e}")
    
    def _acquire_sample(self) -> float:
        import random
        return random.uniform(0.0, 10.0)
```

The callback runs in the streaming thread outside the device lock, so long-running callbacks won't block other code accessing the device.

## Consuming Streamed Data

Three patterns for consuming streamed data: locally, via remote Python client, or in a web browser.

### Local Consumer

Collect streamed data locally:

```python
import time

class DataCollector:
    def __init__(self, device, duration_seconds: float = 5.0):
        self.device = device
        self.duration_seconds = duration_seconds
        self.data = []
    
    def on_data(self, reading):
        self.data.append({
            "timestamp": time.time(),
            "value": reading
        })
    
    def collect(self):
        self.device.start_streaming(callback=self.on_data, sample_rate=10.0)
        try:
            start_time = time.time()
            while time.time() - start_time < self.duration_seconds:
                time.sleep(0.1)
        finally:
            self.device.stop_streaming()
        return self.data

daemon = LabDaemon()
daq = daemon.add_device("daq1", "StreamingDAQ", device_id="daq1")
daemon.connect_device(daq)

collector = DataCollector(daq, duration_seconds=5.0)
data = collector.collect()
print(f"Collected {len(data)} samples")
```

### Python Remote Client

Connect to a streaming device on a remote server using `SSEClient`:

```python
from labdaemon.server import SSEClient
import time

class RemoteStreamConsumer:
    def __init__(self, server_url: str, device_id: str):
        self.server_url = server_url
        self.device_id = device_id
        self.data_buffer = []
        self.client = None
    
    def on_event(self, event):
        if event.get('event') == 'device_data':
            self.data_buffer.append({
                "sequence": event.get('sequence'),
                "timestamp": event.get('timestamp'),
                "value": event.get('payload')
            })
            print(f"[{event['sequence']}] Received: {event['payload']}")
    
    def start(self):
        self.client = SSEClient(self.server_url, on_event=self.on_event)
        self.client.start_device_stream(self.device_id)
    
    def stop(self):
        if self.client:
            self.client.stop_stream()
        return self.data_buffer

consumer = RemoteStreamConsumer("http://localhost:5000", "daq1")
consumer.start()
time.sleep(5.0)
data = consumer.stop()
print(f"Collected {len(data)} samples")
```

### JavaScript Remote Client

Consume streaming data in a web browser using EventSource:

```javascript
class StreamingDataConsumer {
    constructor(serverUrl, deviceId) {
        this.serverUrl = serverUrl;
        this.deviceId = deviceId;
        this.dataBuffer = [];
        this.eventSource = null;
    }
    
    start() {
        const streamUrl = `${this.serverUrl}/stream/devices/${this.deviceId}`;
        this.eventSource = new EventSource(streamUrl);
        
        this.eventSource.addEventListener('device_data', (e) => {
            const event = JSON.parse(e.data);
            this.dataBuffer.push({
                sequence: event.sequence,
                timestamp: event.timestamp,
                value: event.payload
            });
            console.log(`[${event.sequence}] Received: ${event.payload}`);
        });
        
        this.eventSource.onerror = (e) => {
            console.error('Stream error:', e);
            this.eventSource.close();
        };
    }
    
    stop() {
        if (this.eventSource) {
            this.eventSource.close();
        }
        return this.dataBuffer;
    }
}

const consumer = new StreamingDataConsumer('http://localhost:5000', 'daq1');
consumer.start();
setTimeout(() => {
    const data = consumer.stop();
    console.log(`Collected ${data.length} samples`);
}, 5000);
```

## See Also

- [Advanced Streaming](advanced-streaming.md) - Complex streaming patterns, thread safety, and real hardware examples
- [Device Basics](device-basics.md) - Writing basic devices
