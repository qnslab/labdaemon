# Advanced Streaming

This page covers complex streaming patterns: thread safety with locks, rate limiting, real hardware integration, error handling, and backpressure.

## Thread Safety with _ld_lock

If your streaming device owns background threads, protect shared state with the injected `self._ld_lock`. This prevents race conditions between the streaming thread and other code accessing the device:

```python
class ThreadSafeStreamingDevice:
    def __init__(self, device_id: str, **kwargs):
        self.device_id = device_id
        self._streaming_thread = None
        self._stop_event = threading.Event()
        self._callback = None
        self._latest_data = None
    
    def _streaming_loop(self):
        while not self._stop_event.is_set():
            data = self._acquire_sample()
            
            # Protect shared state
            with self._ld_lock:
                self._latest_data = data
            
            # Callback runs outside lock
            if self._callback:
                self._callback(data)
            
            time.sleep(0.01)
    
    def get_latest_data(self):
        """Public method - automatically locked by framework."""
        return self._latest_data
```

Key points:

- Use `self._ld_lock` for streaming threads: The framework automatically injects this re-entrant lock
- Protect only shared state: Don't hold the lock while calling callbacks (they may block)
- Public methods are auto-locked: Methods without leading underscores are wrapped by the framework
- Streaming thread runs outside public lock: Callbacks intentionally run outside the device lock

## Rate Limiting

Control streaming rate to avoid overwhelming clients and hardware:

```python
class RateLimitedStreamingDevice:
    def __init__(self, device_id: str, **kwargs):
        self.device_id = device_id
        self._streaming_thread = None
        self._stop_event = threading.Event()
        self._callback = None
        self._sample_rate = 10.0
    
    def start_streaming(self, callback, sample_rate: float = 10.0):
        self._sample_rate = sample_rate
        self._callback = callback
        self._stop_event.clear()
        self._streaming_thread = threading.Thread(
            target=self._streaming_loop,
            daemon=True
        )
        self._streaming_thread.start()
    
    def stop_streaming(self, timeout=None):
        self._stop_event.set()
        if self._streaming_thread:
            self._streaming_thread.join(timeout=timeout)
    
    def is_streaming(self) -> bool:
        return self._streaming_thread is not None and self._streaming_thread.is_alive()
    
    def _streaming_loop(self):
        min_interval = 1.0 / self._sample_rate
        last_time = time.time()
        
        while not self._stop_event.is_set():
            current_time = time.time()
            elapsed = current_time - last_time
            
            if elapsed < min_interval:
                self._stop_event.wait(timeout=min_interval - elapsed)
                continue
            
            data = self._acquire_sample()
            if self._callback:
                self._callback(data)
            
            last_time = time.time()
```

The rate limiter waits between samples to maintain consistent throughput without busy-waiting.

## Real Hardware Example

Here's a complete PyVISA streaming device:

```python
import pyvisa
import threading
import time

class VISAStreamingDevice:
    def __init__(self, device_id: str, address: str, query_command: str = "MEAS?", **kwargs):
        self.device_id = device_id
        self.address = address
        self.query_command = query_command
        self._instrument = None
        self._streaming_thread = None
        self._stop_event = threading.Event()
        self._callback = None
    
    def connect(self):
        rm = pyvisa.ResourceManager()
        self._instrument = rm.open_resource(self.address)
        self._instrument.timeout = 5000
    
    def disconnect(self):
        if self.is_streaming():
            self.stop_streaming()
        if self._instrument:
            self._instrument.close()
    
    def start_streaming(self, callback, sample_rate: float = 10.0):
        if not self._instrument:
            raise RuntimeError("Device not connected")
        
        self._callback = callback
        self._stop_event.clear()
        self._streaming_thread = threading.Thread(
            target=self._streaming_loop,
            args=(sample_rate,),
            daemon=True
        )
        self._streaming_thread.start()
    
    def stop_streaming(self, timeout=None):
        self._stop_event.set()
        if self._streaming_thread:
            self._streaming_thread.join(timeout=timeout)
    
    def is_streaming(self) -> bool:
        return self._streaming_thread is not None and self._streaming_thread.is_alive()
    
    def _streaming_loop(self, sample_rate: float):
        try:
            while not self._stop_event.is_set():
                try:
                    response = self._instrument.query(self.query_command)
                    value = float(response.strip())
                    if self._callback:
                        self._callback(value)
                    self._stop_event.wait(timeout=1.0 / sample_rate)
                except pyvisa.VisaIOError as e:
                    print(f"VISA error: {e}")
                    break
        except Exception as e:
            print(f"Streaming error: {e}")
```

## Error Handling in Callbacks

Callbacks can block the streaming loop. Handle exceptions gracefully:

```python
class RobustStreamingDevice:
    def __init__(self, device_id: str, **kwargs):
        self.device_id = device_id
        self._streaming_thread = None
        self._stop_event = threading.Event()
        self._callback = None
        self._error_count = 0
    
    def _streaming_loop(self):
        while not self._stop_event.is_set():
            try:
                data = self._acquire_sample()
                
                if self._callback:
                    try:
                        self._callback(data)
                    except Exception as e:
                        self._error_count += 1
                        print(f"Callback error (#{self._error_count}): {e}")
                        if self._error_count > 10:
                            print("Too many callback errors, stopping stream")
                            break
                
                time.sleep(0.01)
            except Exception as e:
                print(f"Streaming error: {e}")
                break
    
    def get_error_count(self) -> int:
        """Get callback error count."""
        return self._error_count
```

This pattern:
- Catches callback exceptions without stopping the stream
- Tracks error counts for diagnostic purposes
- Stops the stream after too many errors to prevent spam

## Backpressure Handling

When callbacks are slow, queue data to avoid blocking the streaming thread:

```python
import queue
import threading

class BackpressureStreamingDevice:
    def __init__(self, device_id: str, max_queue_size: int = 100, **kwargs):
        self.device_id = device_id
        self._streaming_thread = None
        self._callback_thread = None
        self._stop_event = threading.Event()
        self._callback = None
        self._queue = queue.Queue(maxsize=max_queue_size)
    
    def start_streaming(self, callback, sample_rate: float = 10.0):
        self._callback = callback
        self._stop_event.clear()
        
        self._streaming_thread = threading.Thread(
            target=self._streaming_loop,
            args=(sample_rate,),
            daemon=True
        )
        self._streaming_thread.start()
        
        self._callback_thread = threading.Thread(
            target=self._callback_loop,
            daemon=True
        )
        self._callback_thread.start()
    
    def stop_streaming(self, timeout=None):
        self._stop_event.set()
        if self._streaming_thread:
            self._streaming_thread.join(timeout=timeout)
        if self._callback_thread:
            self._callback_thread.join(timeout=timeout)
    
    def is_streaming(self) -> bool:
        return self._streaming_thread is not None and self._streaming_thread.is_alive()
    
    def _streaming_loop(self, sample_rate: float):
        """Acquire data and queue it."""
        try:
            while not self._stop_event.is_set():
                data = self._acquire_sample()
                
                try:
                    self._queue.put(data, timeout=1.0 / sample_rate)
                except queue.Full:
                    print("Data queue full, dropping sample")
                
                self._stop_event.wait(timeout=0.001)
        except Exception as e:
            print(f"Streaming error: {e}")
    
    def _callback_loop(self):
        """Process queued data in separate thread."""
        try:
            while not self._stop_event.is_set():
                try:
                    data = self._queue.get(timeout=0.1)
                    if self._callback:
                        self._callback(data)
                except queue.Empty:
                    continue
        except Exception as e:
            print(f"Callback error: {e}")
```

This pattern:
- Runs streaming and callbacks in separate threads
- Decouples data acquisition from callback execution
- Queues data to handle slow callbacks
- Drops samples if the queue fills (prevents memory bloat)

## Server Integration

When using the server, streaming devices are automatically exposed via SSE (Server-Sent Events). Each client gets its own SSE connection, and the server proxies data from the device stream to all connected clients. This is best-effort delivery—messages may drop under load—but it's suitable for monitoring and visualization.

Key characteristics:
- **Multiple clients** - Each client receives the same stream independently
- **Best-effort delivery** - Data may be dropped if clients can't keep up
- **Automatic proxying** - Server handles SSE connection management
- **Fair distribution** - Each client gets an equal share of data samples

## See Also

- [Basic Streaming](basic-streaming.md) - Essential streaming patterns
- [Device Basics](device-basics.md) - Writing basic devices
