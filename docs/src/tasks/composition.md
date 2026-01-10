# Task Composition

Tasks can be composed hierarchically to build complex experiments from simple components.

## Sequential Composition

Execute tasks one after another, passing results between them:

```python
class CalibratedMeasurement:
    def __init__(self, task_id: str, laser_id: str, daq_id: str, **kwargs):
        self.task_id = task_id
        self.laser_id = laser_id
        self.daq_id = daq_id
        self.device_ids = [laser_id, daq_id]
    
    def run(self, context):
        # Step 1: Calibration
        cal_handle = context.daemon.execute_task(
            "cal", "CalibrationTask",
            laser_id=self.laser_id, daq_id=self.daq_id
        )
        cal_result = cal_handle.wait()
        
        # Step 2: Measurement with calibration result
        measure_handle = context.daemon.execute_task(
            "measure", "MeasurementTask",
            laser_id=self.laser_id, daq_id=self.daq_id,
            calibration=cal_result
        )
        return measure_handle.wait()
```

## Parallel Composition

Run multiple tasks simultaneously and collect results:

```python
import queue

class ParallelAcquisition:
    def __init__(self, task_id: str, detector_ids: list, **kwargs):
        self.task_id = task_id
        self.detector_ids = detector_ids
        self.device_ids = detector_ids
    
    def run(self, context):
        result_queue = queue.Queue()
        handles = []
        
        # Start multiple acquisitions
        for det_id in self.detector_ids:
            h = context.daemon.execute_task(
                f"{self.task_id}-{det_id}", "AcquisitionTask",
                detector_id=det_id,
                result_queue=result_queue
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

## Feedback Composition

Adapt execution based on intermediate results:

```python
class AdaptiveScan:
    def __init__(self, task_id: str, device_id: str, **kwargs):
        self.task_id = task_id
        self.device_id = device_id
        self.device_ids = [device_id]
    
    def run(self, context):
        # Initial scan
        scan_handle = context.daemon.execute_task(
            "scan", "ScanTask",
            device_id=self.device_id
        )
        scan_result = scan_handle.wait()
        
        # Adapt based on results
        if scan_result['feature_found']:
            refine_handle = context.daemon.execute_task(
                "refine", "RefineTask",
                device_id=self.device_id,
                position=scan_result['feature_position']
            )
            return refine_handle.wait()
        
        return scan_result
```

## Communication Between Tasks

Tasks communicate via various mechanisms:

### Return Values

Simple data passing between tasks:

```python
def run(self, context):
    # Task 1
    h1 = context.daemon.execute_task("task1", "DataProducer")
    r1 = h1.wait()
    
    # Task 2 (uses result from Task 1)
    h2 = context.daemon.execute_task("task2", "DataConsumer", data=r1)
    return h2.wait()
```

### Queues

Streaming data collection between producer and consumer:

```python
import queue

# Producer task
class ProducerTask:
    def run(self, context):
        for i in range(100):
            data = self.acquire()
            context.result_queue.put(("producer", data))

# Consumer task
class ConsumerTask:
    def run(self, context):
        results = []
        for _ in range(100):
            source, data = context.result_queue.get()
            results.append(data)
        return results

# Orchestrator
class PipelineTask:
    def run(self, context):
        result_queue = queue.Queue()
        
        # Start producer
        prod = context.daemon.execute_task(
            "prod", "ProducerTask", result_queue=result_queue
        )
        
        # Start consumer
        cons = context.daemon.execute_task(
            "cons", "ConsumerTask", result_queue=result_queue
        )
        
        # Wait for completion
        prod.wait()
        return cons.wait()
```

### Events

Synchronization triggers:

```python
import threading

class TriggeredAcquisition:
    def run(self, context):
        trigger_event = threading.Event()
        
        # Start waiting task
        wait_handle = context.daemon.execute_task(
            "wait", "WaitForTrigger",
            trigger_event=trigger_event
        )
        
        # Do other work...
        self.prepare_system()
        
        # Trigger the waiting task
        trigger_event.set()
        
        # Get result
        return wait_handle.wait()
```
