# Concepts

LabDaemon has five core ideas: devices, tasks, the daemon, streaming, and the server. Understanding how these fit together helps you structure code that scales from simple scripts to complex multi-interface systems.

If you haven't already, start with [Magic 🪄✨](magic.md) to understand the design philosophy and what LabDaemon handles automatically.

## Devices

A device is a Python class that wraps an instrument. It's your laser, spectrometer, DAQ, or whatever hardware you're controlling. Just write a class with methods that do things:

```python
class MyLaser:
    def __init__(self, address: str):
        self.address = address
        self._connection = None
    
    def connect(self):
        self._connection = connect_to_gpib(self.address)
    
    def set_wavelength(self, wl: float):
        self._connection.write(f'WAVELENGTH {wl}')
    
    def get_wavelength(self) -> float:
        return self._connection.query('WAVELENGTH?')
```

That's it. No inheritance, no decorators, no framework knowledge required. Your device is just Python.

LabDaemon expects two optional methods: `connect()` (called when the device is instantiated) and `disconnect()` (called when it's cleaned up). If you have those, the framework handles lifecycle. If not, it just creates and uses your class.

How to think about devices: Write them as if they're running in a single thread. Don't worry about locks, don't worry about being called from multiple places. Just write the straightforward code that talks to your instrument. The framework handles the threading complexity automatically.

## Tasks

A task is a function that runs in the background and uses one or more devices. It's how you orchestrate your experiment: sweep the laser wavelength while reading the detector, wait for stability, collect data, repeat.

```python
class WavelengthSweepTask:
    def __init__(self, task_id: str, laser_id: str, detector_id: str):
        self.task_id = task_id
        self.laser_id = laser_id
        self.detector_id = detector_id
        self.device_ids = [laser_id, detector_id]  # Declare dependencies
    
    def run(self, context: TaskContext) -> dict:
        laser = context.daemon.get_device(self.laser_id)
        detector = context.daemon.get_device(self.detector_id)
        
        results = []
        for wl in range(1540, 1560):
            if context.cancel_event.is_set():
                break
            
            laser.set_wavelength(wl)
            reading = detector.read()
            results.append({"wavelength": wl, "reading": reading})
        
        return {"results": results}
```

Tasks declare which devices they need (the `device_ids` list). This declaration matters when you use the server—it tells the server which hardware this task claims while it's running.

How to think about tasks: Write them as if you're in a dedicated thread that can call any device whenever you want. Check `context.cancel_event` periodically so users can stop long-running experiments. Access devices through `context.daemon`. Return a dict with your results.

Tasks can be written against device interfaces rather than specific implementations. A wavelength sweep task might assume any device with `set_wavelength()` and `get_power()` methods, letting you swap laser models without changing measurement logic. This enables testing with mock devices and hardware-independent experiments.

## The Daemon

The daemon is the coordinator. It holds all your registered devices and manages access to them. Locally, in a script, you just instantiate it, register your devices, and use them.

```python
daemon = ld.LabDaemon()
daemon.register_plugins(devices={"MyLaser": MyLaser, "MyDetector": MyDetector})

with daemon.device_context("laser1", "MyLaser", address="GPIB0::1") as laser:
    laser.set_wavelength(1550.0)
```

The daemon does three things:
- Holds devices: You create and configure devices through it
- Enforces thread safety: Every device call automatically acquires that device's lock
- Runs tasks: You submit tasks to the daemon, it runs them in background threads

How to think about the daemon: It's your entry point. You tell it what devices you have, then use it to access them. Locally, the daemon is just a coordinator. When you add a server, the daemon becomes the shared state that the server exposes over HTTP.

## Streaming

Some devices produce continuous data: a camera, a digitiser, a power meter reading every millisecond. Streaming is how you get that data out.

A device implements `start_streaming(callback)` and `stop_streaming()`. When you start streaming, the device calls your callback function with data as it arrives:

```python
class MyCameraDevice:
    def start_streaming(self, callback):
        self.streaming = True
        self._stream_thread = threading.Thread(
            target=self._stream_loop,
            args=(callback,)
        )
        self._stream_thread.start()
    
    def _stream_loop(self, callback):
        while self.streaming:
            frame = self._camera.read_frame()
            callback(frame)
```

The callback receives raw data and runs outside device locks, so it can do work without blocking your device.

How to think about streaming: Your device pushes data to a callback. Locally, you provide the callback directly. When you use the server, the same device stream automatically becomes a web endpoint (Server-Sent Events) that remote clients can subscribe to. The device doesn't change—it just calls the callback the same way.

## The Server

The server is optional. It wraps your daemon with HTTP, exposing devices and tasks over the network. You can monitor your experiment from a web browser or control it from a remote client. The same code that runs in a script works identically through the server.

The server adds one important feature: device ownership. When multiple clients connect to the same hardware, they could interfere. The server prevents this by having tasks claim devices while they run. A task declares `device_ids = ["laser1", "detector1"]`, and while the task is running, other clients trying to control those devices get a "device is busy" response. Monitoring (GET requests) always works—only commands (POST requests) are blocked.

```python
server = LabDaemonServer(daemon, port=5000)
server.start()

# Now your devices and tasks are accessible via:
# GET /api/devices/laser1/wavelength
# POST /api/tasks/WavelengthSweepTask
# SSE /api/streams/camera1
```

How to think about the server: It's how your local daemon becomes a multi-user system. You don't rewrite anything. The same devices and tasks work. The server just enforces that multiple people don't accidentally step on each other.

## How They Work Together

In a script:
1. Create a daemon
2. Register your device classes
3. Get device instances and call methods on them
4. Submit tasks to run in the background

When you add a server:
1. Create the same daemon
2. Wrap it in a LabDaemonServer
3. Remote clients now call the same tasks and devices over HTTP
4. Device ownership prevents interference

When you add a GUI:
1. Use the same daemon, either in-process or via the server
2. Your GUI calls device methods and submits tasks
3. Everything just works

The code you write for step 1 works unchanged in steps 2 and 3. That's the point.