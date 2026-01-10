# Device-Agnostic Tasks

Tasks that work with device interfaces rather than specific implementations enable hardware flexibility and comprehensive testing. Write measurement logic once, run it with different equipment.

## Basic Pattern

Instead of assuming specific device types, tasks declare what interfaces they need:

```python
class WavelengthSweepTask:
    def __init__(self, task_id: str, laser_id: str, detector_id: str, 
                 start_wl: float, stop_wl: float, steps: int):
        self.task_id = task_id
        self.laser_id = laser_id
        self.detector_id = detector_id
        self.start_wl = start_wl
        self.stop_wl = stop_wl
        self.steps = steps
        self.device_ids = [laser_id, detector_id]
    
    def run(self, context):
        # Works with any laser that has these methods
        laser = context.daemon.get_device(self.laser_id)
        detector = context.daemon.get_device(self.detector_id)
        
        wavelengths = np.linspace(self.start_wl, self.stop_wl, self.steps)
        results = []
        
        for wl in wavelengths:
            if context.cancel_event.is_set():
                break
                
            laser.set_wavelength(wl)
            time.sleep(0.1)  # Stabilization
            power = detector.read_power()
            results.append({"wavelength": wl, "power": power})
        
        return {"wavelengths": [r["wavelength"] for r in results],
                "powers": [r["power"] for r in results]}
```

This task works with any laser implementing `set_wavelength()` and any detector implementing `read_power()`.

## Complex Example: ODMR Measurement

An ODMR measurement coordinates multiple devices with different interfaces:

```python
class ODMRTask:
    def __init__(self, task_id: str, rf_gen_id: str, pulse_gen_id: str, 
                 camera_id: str, freq_start: float, freq_stop: float, steps: int):
        self.task_id = task_id
        self.rf_gen_id = rf_gen_id
        self.pulse_gen_id = pulse_gen_id
        self.camera_id = camera_id
        self.freq_start = freq_start
        self.freq_stop = freq_stop
        self.steps = steps
        self.device_ids = [rf_gen_id, pulse_gen_id, camera_id]
    
    def run(self, context):
        # Get devices - assume interfaces but not implementations
        rf_gen = context.daemon.get_device(self.rf_gen_id)
        pulse_gen = context.daemon.get_device(self.pulse_gen_id)
        camera = context.daemon.get_device(self.camera_id)
        
        # Configure pulse sequence
        pulse_gen.load_sequence([
            {"channel": 0, "duration": 1000, "amplitude": 1.0},  # Laser pulse
            {"channel": 1, "duration": 100, "amplitude": 1.0},   # MW pulse
            {"channel": 0, "duration": 1000, "amplitude": 1.0}   # Readout
        ])
        
        frequencies = np.linspace(self.freq_start, self.freq_stop, self.steps)
        odmr_data = []
        
        for freq in frequencies:
            if context.cancel_event.is_set():
                break
            
            # Set MW frequency
            rf_gen.set_frequency(freq)
            rf_gen.set_power(-10)  # dBm
            rf_gen.enable_output(True)
            
            # Run pulse sequence and collect data
            pulse_gen.trigger()
            time.sleep(0.01)  # Sequence duration
            
            # Read fluorescence
            image = camera.acquire_image()
            fluorescence = np.mean(image[100:200, 100:200])  # ROI
            odmr_data.append({"frequency": freq, "signal": fluorescence})
        
        rf_gen.enable_output(False)
        
        return {
            "frequencies": [d["frequency"] for d in odmr_data],
            "signals": [d["signal"] for d in odmr_data],
            "metadata": {
                "freq_range": [self.freq_start, self.freq_stop],
                "steps": self.steps
            }
        }
```

This task works with any RF generator that has `set_frequency()`, `set_power()`, and `enable_output()`, any pulse generator with `load_sequence()` and `trigger()`, and any camera with `acquire_image()`.

## Interface Documentation

Document expected interfaces clearly:

```python
class SpectroscopyTask:
    """Automated spectroscopy measurement.
    
    Required device interfaces:
    
    laser_id device must implement:
    - set_wavelength(wl: float) -> None
    - get_wavelength() -> float
    - is_stable() -> bool
    
    spectrometer_id device must implement:
    - set_integration_time(time_ms: float) -> None
    - acquire_spectrum() -> dict with 'wavelengths' and 'intensities'
    """
    
    def __init__(self, task_id: str, laser_id: str, spectrometer_id: str,
                 wl_start: float, wl_stop: float, wl_step: float):
        self.task_id = task_id
        self.laser_id = laser_id
        self.spectrometer_id = spectrometer_id
        self.wl_start = wl_start
        self.wl_stop = wl_stop
        self.wl_step = wl_step
        self.device_ids = [laser_id, spectrometer_id]
```

Clear interface documentation helps others implement compatible devices.

## Testing with Multiple Implementations

Device-agnostic tasks enable comprehensive testing:

```python
# Real hardware test
daemon.register_plugins(devices={
    "TunicsLaser": TunicsLaser,
    "OceanSpectrometer": OceanSpectrometer
})

with daemon.task_context("spec1", "SpectroscopyTask",
                        laser_id="laser1", spectrometer_id="spec1",
                        wl_start=1550, wl_stop=1560, wl_step=0.5) as handle:
    result = handle.wait()

# Mock hardware test
daemon.register_plugins(devices={
    "MockLaser": MockLaser,
    "MockSpectrometer": MockSpectrometer
})

with daemon.task_context("spec1", "SpectroscopyTask",
                        laser_id="laser1", spectrometer_id="spec1",
                        wl_start=1550, wl_stop=1560, wl_step=0.5) as handle:
    result = handle.wait()
    assert len(result["wavelengths"]) == 21  # Test logic without hardware
```

The same task code runs with real or mock devices.

## Configuration Strategies

Handle device-specific configuration through the daemon:

```python
# Different laser implementations, same interface
daemon.register_plugins(devices={
    "TunicsLaser": TunicsLaser,
    "SantecLaser": SantecLaser
})

# Task works with either
if lab_config["laser_type"] == "tunics":
    laser = daemon.add_device("laser1", "TunicsLaser", 
                             address="COM3", baud=9600)
elif lab_config["laser_type"] == "santec":
    laser = daemon.add_device("laser1", "SantecLaser",
                             ip="192.168.1.100", port=8000)

# Same task code regardless
handle = daemon.execute_task("sweep1", "WavelengthSweepTask",
                           laser_id="laser1", detector_id="det1",
                           start_wl=1550, stop_wl=1560, steps=11)
```

Configuration happens at device registration, not in task code.

## Composition Patterns

Device-agnostic tasks compose well:

```python
class CharacterizationSuite:
    def __init__(self, task_id: str, laser_id: str, detector_id: str):
        self.task_id = task_id
        self.laser_id = laser_id
        self.detector_id = detector_id
        self.device_ids = [laser_id, detector_id]
    
    def run(self, context):
        results = {}
        
        # Power vs wavelength
        power_task = WavelengthSweepTask(
            "power_sweep", self.laser_id, self.detector_id,
            1540, 1560, 21
        )
        results["power_spectrum"] = power_task.run(context)
        
        # Stability measurement
        stability_task = StabilityMeasurement(
            "stability", self.laser_id, self.detector_id,
            duration=300  # 5 minutes
        )
        results["stability"] = stability_task.run(context)
        
        return results
```

Composite tasks combine smaller measurements without knowing specific device implementations.

## Error Handling

Device-agnostic tasks should handle interface mismatches gracefully:

```python
def run(self, context):
    laser = context.daemon.get_device(self.laser_id)
    
    # Check for required methods
    if not hasattr(laser, "set_wavelength"):
        raise ValueError(f"Device {self.laser_id} missing set_wavelength() method")
    
    if not hasattr(laser, "get_wavelength"):
        raise ValueError(f"Device {self.laser_id} missing get_wavelength() method")
    
    # Or use duck typing and let AttributeError bubble up
    try:
        laser.set_wavelength(1550.0)
        current_wl = laser.get_wavelength()
    except AttributeError as e:
        raise ValueError(f"Device {self.laser_id} interface mismatch: {e}")
```

Explicit interface checking provides clearer error messages than relying on AttributeError.

## When to Use Device-Agnostic Tasks

Use device-agnostic tasks when:

- Measurements will run on different hardware setups
- You want comprehensive testing without all hardware present
- Multiple labs use the same measurement protocols
- Equipment gets upgraded or replaced frequently

Use device-specific tasks when:

- Leveraging unique device capabilities
- Performance optimization requires device-specific code
- Interface abstraction adds unnecessary complexity
- Working with one-off or highly specialized instruments

Device abstraction adds flexibility at the cost of complexity. Use it when the flexibility is valuable.