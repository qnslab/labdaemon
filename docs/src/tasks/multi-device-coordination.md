# Multi-Device Coordination

### How to Orchestrate Experiments

Coordinator tasks compose other tasks:

```python
class CalibratedSweep:
    def __init__(self, task_id: str, laser_id: str, daq_id: str, **kwargs):
        self.task_id = task_id
        self.laser_id = laser_id
        self.daq_id = daq_id
        self.device_ids = [laser_id, daq_id]
    
    def run(self, context: ld.TaskContext):
        # Step 1: Run calibration
        cal_handle = context.daemon.execute_task(
            f"{self.task_id}-cal", "CalibrationTask",
            laser_id=self.laser_id, daq_id=self.daq_id
        )
        cal_result = cal_handle.wait()
        
        # Step 2: Run measurement with calibration result
        sweep_handle = context.daemon.execute_task(
            f"{self.task_id}-sweep", "SweepTask",
            laser_id=self.laser_id, daq_id=self.daq_id,
            power_mw=cal_result['optimal_power']
        )
        return sweep_handle.wait()
```

### How to Run Tasks in Parallel

```python
import queue

class ParallelAcquisition:
    def __init__(self, task_id: str, detector_ids: list, **kwargs):
        self.task_id = task_id
        self.detector_ids = detector_ids
        self.device_ids = detector_ids
    
    def run(self, context: ld.TaskContext):
        result_queue = queue.Queue()
        handles = []
        
        # Start all acquisitions
        for det_id in self.detector_ids:
            h = context.daemon.execute_task(
                f"{self.task_id}-{det_id}", "AcquisitionTask",
                detector_id=det_id, result_queue=result_queue
            )
            handles.append(h)
        
        # Collect results
        results = {}
        for h in handles:
            det_id, data = result_queue.get()
            results[det_id] = data
            h.wait()
        
        return results
```
