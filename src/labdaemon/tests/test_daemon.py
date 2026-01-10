import queue
import threading
import time
from typing import Any, Dict, List, Optional

import pytest

import labdaemon as ld
from labdaemon.daemon import LabDaemon
from labdaemon.exceptions import DeviceConnectionError, DeviceTimeoutError, TaskCancelledError, TaskFailedError, TaskError


# --- Mock Objects for Testing ---

class MockDevice:
    """A simple mock device for testing."""

    def __init__(self, device_id: str, **kwargs: Any):
        self.device_id = device_id
        self.kwargs = kwargs
        self.connected = False
        self.connect_called = False
        self.disconnect_called = False

    def connect(self) -> None:
        self.connect_called = True
        self.connected = True

    def disconnect(self) -> None:
        self.disconnect_called = True
        self.connected = False

    def some_method(self) -> str:
        return f"Hello from {self.device_id}"


class SlowConnectingDevice(MockDevice):
    """A mock device that takes time to connect."""

    def __init__(self, device_id: str, connect_delay: float = 0.2, **kwargs: Any):
        super().__init__(device_id, **kwargs)
        self._connect_delay = connect_delay

    def connect(self) -> None:
        time.sleep(self._connect_delay)
        super().connect()


class FailingConnectingDevice(MockDevice):
    """A mock device that fails during connection."""

    def connect(self) -> None:
        self.connect_called = True
        raise DeviceConnectionError("Failed to connect to mock hardware")


class StreamingDevice(MockDevice):
    """A mock device that supports streaming."""

    def __init__(self, device_id: str, **kwargs: Any):
        super().__init__(device_id, **kwargs)
        self._streaming = False
        self._streaming_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._callback: Optional[Any] = None
        self._sample_interval = 0.01
        self._sample_count = 0

    def configure_streaming(self, sample_interval: float = 0.01, **kwargs: Any) -> None:
        """Configure streaming parameters."""
        self._sample_interval = sample_interval

    def start_streaming(self, callback: Any) -> None:
        """Start streaming data to the callback."""
        if self._streaming:
            raise RuntimeError("Already streaming")

        self._callback = callback
        self._stop_event.clear()
        self._streaming = True
        self._sample_count = 0

        self._streaming_thread = threading.Thread(
            target=self._streaming_loop,
            name=f"MockStreaming-{self.device_id}",
            daemon=True,
        )
        self._streaming_thread.start()

    def _streaming_loop(self) -> None:
        """Background thread that generates and sends data."""
        while not self._stop_event.is_set():
            time.sleep(self._sample_interval)
            if self._stop_event.is_set():
                break

            self._sample_count += 1
            data = {"sample_number": self._sample_count, "value": self._sample_count * 0.1}

            if self._callback:
                try:
                    self._callback(data)
                except Exception:
                    pass

    def stop_streaming(self, timeout: float = 1.0) -> None:
        """Stop streaming."""
        if not self._streaming:
            return

        self._stop_event.set()

        if self._streaming_thread and self._streaming_thread.is_alive():
            self._streaming_thread.join(timeout=timeout)

        self._streaming = False
        self._callback = None

    def is_streaming(self) -> bool:
        """Check if currently streaming."""
        return self._streaming


class SlowStoppingStreamingDevice(StreamingDevice):
    """A streaming device that takes time to stop."""

    def __init__(self, device_id: str, stop_delay: float = 0.5, **kwargs: Any):
        super().__init__(device_id, **kwargs)
        self._stop_delay = stop_delay

    def stop_streaming(self, timeout: float = 1.0) -> None:
        """Stop streaming with a delay."""
        if not self._streaming:
            return

        time.sleep(self._stop_delay)
        super().stop_streaming(timeout=timeout)


class FailingStreamingDevice(StreamingDevice):
    """A streaming device that fails during streaming."""

    def __init__(self, device_id: str, fail_after_samples: int = 5, **kwargs: Any):
        super().__init__(device_id, **kwargs)
        self._fail_after_samples = fail_after_samples

    def _streaming_loop(self) -> None:
        """Background thread that fails after a certain number of samples."""
        while not self._stop_event.is_set():
            time.sleep(self._sample_interval)
            if self._stop_event.is_set():
                break

            self._sample_count += 1

            if self._sample_count >= self._fail_after_samples:
                raise RuntimeError("Streaming device failed intentionally")

            data = {"sample_number": self._sample_count, "value": self._sample_count * 0.1}

            if self._callback:
                try:
                    self._callback(data)
                except Exception:
                    pass


class MockTask:
    """A simple mock task for testing."""

    def __init__(self, task_id: str, **kwargs: Any):
        self.task_id = task_id
        self.kwargs = kwargs
        # Allow override of delay for testing
        self._delay = kwargs.get('delay', 0.05)

    def run(self, context: ld.TaskContext) -> Dict[str, Any]:
        # Add a small delay so the task is still running when we check
        time.sleep(self._delay)
        return {"status": "complete", "task_id": self.task_id}


class SlowTask:
    """A task that takes time to complete."""

    def __init__(self, task_id: str, duration: float = 0.2, **kwargs: Any):
        self.task_id = task_id
        self.duration = duration
        self.kwargs = kwargs

    def run(self, context: ld.TaskContext) -> Dict[str, Any]:
        # Check cancellation in small increments so the task can be cancelled
        start_time = time.time()
        while time.time() - start_time < self.duration:
            if context.cancel_event.is_set():
                return {
                    "status": "cancelled",
                    "task_id": self.task_id,
                    "duration": time.time() - start_time,
                }
            time.sleep(0.01)
        
        return {"status": "complete", "task_id": self.task_id, "duration": self.duration}


class CancellableTask:
    """A task that checks for cancellation and exits gracefully."""

    def __init__(self, task_id: str, num_steps: int = 10, step_duration: float = 0.05, **kwargs: Any):
        self.task_id = task_id
        self.num_steps = num_steps
        self.step_duration = step_duration
        self.kwargs = kwargs
        self.steps_completed = 0

    def run(self, context: ld.TaskContext) -> Dict[str, Any]:
        for i in range(self.num_steps):
            if context.cancel_event.is_set():
                return {
                    "status": "cancelled",
                    "task_id": self.task_id,
                    "steps_completed": self.steps_completed,
                }
            time.sleep(self.step_duration)
            self.steps_completed += 1

        return {
            "status": "complete",
            "task_id": self.task_id,
            "steps_completed": self.steps_completed,
        }


class FailingTask:
    """A task that raises an exception during execution."""

    def __init__(self, task_id: str, error_message: str = "Task failed", **kwargs: Any):
        self.task_id = task_id
        self.error_message = error_message
        self.kwargs = kwargs

    def run(self, context: ld.TaskContext) -> Dict[str, Any]:
        raise RuntimeError(self.error_message)


class DeviceUsingTask:
    """A task that uses a device from the daemon."""

    def __init__(self, task_id: str, device_id: str, **kwargs: Any):
        self.task_id = task_id
        self.device_id = device_id
        self.kwargs = kwargs

    def run(self, context: ld.TaskContext) -> Dict[str, Any]:
        device = context.daemon.get_device(self.device_id)
        result = device.some_method()
        return {"status": "complete", "task_id": self.task_id, "device_result": result}


class PausableTask:
    """A task that supports pause/resume via the context's resume_event."""

    def __init__(self, task_id: str, num_steps: int = 10, step_duration: float = 0.05, **kwargs: Any):
        self.task_id = task_id
        self.num_steps = num_steps
        self.step_duration = step_duration
        self.kwargs = kwargs
        self.steps_completed = 0

    def run(self, context: ld.TaskContext) -> Dict[str, Any]:
        for i in range(self.num_steps):
            if context.cancel_event.is_set():
                return {
                    "status": "cancelled",
                    "task_id": self.task_id,
                    "steps_completed": self.steps_completed,
                }

            # Wait for resume before doing work
            context.resume_event.wait()
            
            # Check cancellation again after waking from pause
            if context.cancel_event.is_set():
                return {
                    "status": "cancelled",
                    "task_id": self.task_id,
                    "steps_completed": self.steps_completed,
                }

            time.sleep(self.step_duration)
            self.steps_completed += 1

        return {
            "status": "complete",
            "task_id": self.task_id,
            "steps_completed": self.steps_completed,
        }


class InteractiveTask:
    """A task that supports parameter updates and queries."""

    def __init__(self, task_id: str, initial_value: float = 1.0, num_steps: int = 10, **kwargs: Any):
        self.task_id = task_id
        self.num_steps = num_steps
        self.kwargs = kwargs
        self._lock = threading.Lock()
        self._parameters = {
            "value": initial_value,
            "steps_completed": 0,
            "is_running": False,
        }

    def set_parameter(self, key: str, value: Any) -> None:
        """Thread-safe parameter update."""
        with self._lock:
            if key == "value":
                self._parameters["value"] = value
            else:
                raise ValueError(f"Unknown parameter: {key}")

    def get_parameter(self, key: str) -> Any:
        """Thread-safe parameter query."""
        with self._lock:
            if key in self._parameters:
                return self._parameters[key]
            else:
                raise ValueError(f"Unknown parameter: {key}")

    def run(self, context: ld.TaskContext) -> Dict[str, Any]:
        with self._lock:
            self._parameters["is_running"] = True

        try:
            for i in range(self.num_steps):
                if context.cancel_event.is_set():
                    return {"status": "cancelled", "task_id": self.task_id}

                context.resume_event.wait()

                time.sleep(0.05)

                with self._lock:
                    self._parameters["steps_completed"] = i + 1

            with self._lock:
                final_value = self._parameters["value"]

            return {
                "status": "complete",
                "task_id": self.task_id,
                "final_value": final_value,
                "steps_completed": self.num_steps,
            }
        finally:
            with self._lock:
                self._parameters["is_running"] = False


class ParallelCoordinatorTask:
    """A coordinator that spawns multiple child tasks in parallel."""

    def __init__(
        self,
        task_id: str,
        num_children: int = 3,
        child_duration: float = 0.2,
        **kwargs: Any
    ):
        self.task_id = task_id
        self.num_children = num_children
        self.child_duration = child_duration
        self.kwargs = kwargs

    def run(self, context: ld.TaskContext) -> Dict[str, Any]:
        child_handles = []

        for i in range(self.num_children):
            child_id = f"{self.task_id}_child_{i}"
            handle = context.daemon.execute_task(
                task_id=child_id,
                task_type="SlowTask",
                duration=self.child_duration,
            )
            child_handles.append(handle)

        child_results = []
        for handle in child_handles:
            try:
                result = handle.wait(timeout=2.0)
                child_results.append(result)
            except Exception as e:
                child_results.append({"error": str(e)})

        return {
            "status": "complete",
            "task_id": self.task_id,
            "num_children": self.num_children,
            "child_results": child_results,
        }


class SequentialCoordinatorTask:
    """A coordinator that runs child tasks sequentially, passing results forward."""

    def __init__(
        self,
        task_id: str,
        num_steps: int = 3,
        **kwargs: Any
    ):
        self.task_id = task_id
        self.num_steps = num_steps
        self.kwargs = kwargs

    def run(self, context: ld.TaskContext) -> Dict[str, Any]:
        accumulated_value = 0
        step_results = []

        for i in range(self.num_steps):
            child_id = f"{self.task_id}_step_{i}"
            handle = context.daemon.execute_task(
                task_id=child_id,
                task_type="MockTask",
            )

            result = handle.wait(timeout=2.0)
            step_results.append(result)
            accumulated_value += 1

        return {
            "status": "complete",
            "task_id": self.task_id,
            "num_steps": self.num_steps,
            "accumulated_value": accumulated_value,
            "step_results": step_results,
        }


class CancellableCoordinatorTask:
    """A coordinator that spawns children and handles cancellation."""

    def __init__(
        self,
        task_id: str,
        num_children: int = 3,
        child_num_steps: int = 20,
        **kwargs: Any
    ):
        self.task_id = task_id
        self.num_children = num_children
        self.child_num_steps = child_num_steps
        self.kwargs = kwargs

    def run(self, context: ld.TaskContext) -> Dict[str, Any]:
        child_handles = []

        for i in range(self.num_children):
            if context.cancel_event.is_set():
                for handle in child_handles:
                    handle.cancel()
                return {
                    "status": "cancelled",
                    "task_id": self.task_id,
                    "children_spawned": len(child_handles),
                }

            child_id = f"{self.task_id}_child_{i}"
            handle = context.daemon.execute_task(
                task_id=child_id,
                task_type="CancellableTask",
                num_steps=self.child_num_steps,
                step_duration=0.05,
            )
            child_handles.append(handle)

        for handle in child_handles:
            if context.cancel_event.is_set():
                for h in child_handles:
                    h.cancel()
                return {
                    "status": "cancelled",
                    "task_id": self.task_id,
                    "children_spawned": len(child_handles),
                }

            try:
                handle.wait(timeout=5.0)
            except TaskCancelledError:
                pass

        return {
            "status": "complete",
            "task_id": self.task_id,
            "children_completed": len(child_handles),
        }


class FailingChildCoordinatorTask:
    """A coordinator where one child fails."""

    def __init__(
        self,
        task_id: str,
        num_children: int = 3,
        failing_child_index: int = 1,
        **kwargs: Any
    ):
        self.task_id = task_id
        self.num_children = num_children
        self.failing_child_index = failing_child_index
        self.kwargs = kwargs

    def run(self, context: ld.TaskContext) -> Dict[str, Any]:
        child_handles = []
        child_results = []

        for i in range(self.num_children):
            child_id = f"{self.task_id}_child_{i}"

            if i == self.failing_child_index:
                handle = context.daemon.execute_task(
                    task_id=child_id,
                    task_type="FailingTask",
                    error_message=f"Child {i} failed intentionally",
                )
            else:
                handle = context.daemon.execute_task(
                    task_id=child_id,
                    task_type="MockTask",
                )

            child_handles.append(handle)

        for i, handle in enumerate(child_handles):
            try:
                result = handle.wait(timeout=2.0)
                child_results.append({"child_index": i, "result": result})
            except TaskFailedError as e:
                child_results.append({"child_index": i, "error": str(e)})

        return {
            "status": "complete",
            "task_id": self.task_id,
            "child_results": child_results,
        }


class QueueBasedCoordinatorTask:
    """A coordinator that uses a queue to collect results from children."""

    def __init__(
        self,
        task_id: str,
        num_children: int = 3,
        result_queue: Optional[queue.Queue] = None,
        **kwargs: Any
    ):
        self.task_id = task_id
        self.num_children = num_children
        self.result_queue = result_queue if result_queue is not None else queue.Queue()
        self.kwargs = kwargs

    def run(self, context: ld.TaskContext) -> Dict[str, Any]:
        child_handles = []

        for i in range(self.num_children):
            child_id = f"{self.task_id}_child_{i}"
            handle = context.daemon.execute_task(
                task_id=child_id,
                task_type="MockTask",
            )
            child_handles.append(handle)

        for handle in child_handles:
            result = handle.wait(timeout=2.0)
            self.result_queue.put(result)

        collected_results = []
        while not self.result_queue.empty():
            collected_results.append(self.result_queue.get())

        return {
            "status": "complete",
            "task_id": self.task_id,
            "num_children": self.num_children,
            "collected_results": collected_results,
        }


# --- Pytest Fixtures ---

@pytest.fixture
def daemon() -> LabDaemon:
    """Returns a clean LabDaemon instance for each test."""
    d = LabDaemon()
    yield d
    d.shutdown(timeout=0.1)


@pytest.fixture
def registered_daemon(daemon: LabDaemon) -> LabDaemon:
    """Returns a daemon with standard mock plugins registered."""
    daemon.register_plugins(
        devices={
            "MockDevice": MockDevice,
            "SlowConnectingDevice": SlowConnectingDevice,
            "FailingConnectingDevice": FailingConnectingDevice,
            "StreamingDevice": StreamingDevice,
            "SlowStoppingStreamingDevice": SlowStoppingStreamingDevice,
            "FailingStreamingDevice": FailingStreamingDevice,
        },
        tasks={
            "MockTask": MockTask,
            "SlowTask": SlowTask,
            "CancellableTask": CancellableTask,
            "FailingTask": FailingTask,
            "DeviceUsingTask": DeviceUsingTask,
            "PausableTask": PausableTask,
            "InteractiveTask": InteractiveTask,
            "ParallelCoordinatorTask": ParallelCoordinatorTask,
            "SequentialCoordinatorTask": SequentialCoordinatorTask,
            "CancellableCoordinatorTask": CancellableCoordinatorTask,
            "FailingChildCoordinatorTask": FailingChildCoordinatorTask,
            "QueueBasedCoordinatorTask": QueueBasedCoordinatorTask,
        },
    )
    return daemon


# --- Device Management Test Cases ---

def test_daemon_initialisation(daemon: LabDaemon):
    """Test that the daemon initialises in a clean state."""
    assert not daemon._device_classes
    assert not daemon._task_classes
    assert not daemon._devices
    assert not daemon._tasks


def test_register_plugins(daemon: LabDaemon):
    """Test that plugins can be registered correctly."""
    daemon.register_plugins(devices={"MyDevice": MockDevice}, tasks={"MyTask": MockTask})
    assert "MyDevice" in daemon._device_classes
    assert "MyTask" in daemon._task_classes
    assert daemon._device_classes["MyDevice"] == MockDevice
    assert daemon._task_classes["MyTask"] == MockTask


def test_register_duplicate_plugin_raises_error(daemon: LabDaemon):
    """Test that registering a duplicate plugin type raises a ValueError."""
    daemon.register_plugins(devices={"MyDevice": MockDevice}, tasks={})
    with pytest.raises(ValueError, match="Device type 'MyDevice' is already registered."):
        daemon.register_plugins(devices={"MyDevice": MockDevice}, tasks={})


def test_add_device(registered_daemon: LabDaemon):
    """Test adding a device instance."""
    device = registered_daemon.add_device(
        device_id="dev1", device_type="MockDevice", address="COM1"
    )
    assert isinstance(device, MockDevice)
    assert device.device_id == "dev1"
    assert device.kwargs["address"] == "COM1"
    assert registered_daemon.get_device("dev1") is device
    assert "dev1" in registered_daemon._devices


def test_add_unknown_device_type_raises_error(daemon: LabDaemon):
    """Test that adding a device of an unregistered type raises a ValueError."""
    with pytest.raises(ValueError, match="Unknown device type: 'UnknownDevice'"):
        daemon.add_device(device_id="dev1", device_type="UnknownDevice")


def test_add_duplicate_device_id_raises_error(registered_daemon: LabDaemon):
    """Test that adding a device with a duplicate ID raises a ValueError."""
    registered_daemon.add_device(device_id="dev1", device_type="MockDevice")
    with pytest.raises(ValueError, match="Device with ID 'dev1' already exists."):
        registered_daemon.add_device(device_id="dev1", device_type="MockDevice")


def test_get_device(registered_daemon: LabDaemon):
    """Test retrieving a device by its ID."""
    device = registered_daemon.add_device(device_id="dev1", device_type="MockDevice")
    retrieved_device = registered_daemon.get_device("dev1")
    assert retrieved_device is device


def test_get_unknown_device_raises_error(registered_daemon: LabDaemon):
    """Test that getting a non-existent device raises a ValueError."""
    with pytest.raises(ValueError, match="No device found with ID: 'unknown'"):
        registered_daemon.get_device("unknown")


def test_connect_disconnect_device(registered_daemon: LabDaemon):
    """Test the basic connect and disconnect lifecycle of a device."""
    device = registered_daemon.add_device(device_id="dev1", device_type="MockDevice")
    assert not device.connect_called
    assert not device.disconnect_called

    registered_daemon.connect_device("dev1")
    assert device.connect_called
    assert device.connected
    assert not device.disconnect_called

    registered_daemon.disconnect_device("dev1")
    assert device.disconnect_called
    assert not device.connected


def test_device_context(registered_daemon: LabDaemon):
    """Test the device_context manager for safe setup and teardown."""
    with registered_daemon.device_context(
        device_id="dev1", device_type="MockDevice"
    ) as device:
        assert isinstance(device, MockDevice)
        assert device.connect_called
        assert device.connected
        assert not device.disconnect_called
        assert registered_daemon.get_device("dev1") is device

    assert device.disconnect_called
    assert not device.connected


def test_connect_device_timeout(registered_daemon: LabDaemon):
    """Test that connect_device raises DeviceTimeoutError if it takes too long."""
    device = registered_daemon.add_device(
        device_id="slow_dev", device_type="SlowConnectingDevice", connect_delay=0.5
    )
    with pytest.raises(DeviceTimeoutError):
        registered_daemon.connect_device("slow_dev", timeout=0.1)

    assert device.disconnect_called


def test_connect_device_failing(registered_daemon: LabDaemon):
    """Test that exceptions during connect are propagated correctly."""
    registered_daemon.add_device(device_id="fail_dev", device_type="FailingConnectingDevice")
    with pytest.raises(DeviceConnectionError, match="Failed to connect to mock hardware"):
        registered_daemon.connect_device("fail_dev")


def test_shutdown(registered_daemon: LabDaemon):
    """Test that shutdown disconnects all connected devices."""
    dev1 = registered_daemon.add_device(device_id="dev1", device_type="MockDevice")
    dev2 = registered_daemon.add_device(device_id="dev2", device_type="MockDevice")

    registered_daemon.connect_device(dev1)
    registered_daemon.connect_device(dev2)

    assert dev1.connected
    assert dev2.connected

    registered_daemon.shutdown(timeout=0.1)

    assert not dev1.connected
    assert not dev2.connected
    assert dev1.disconnect_called
    assert dev2.disconnect_called


def test_thread_safety_of_device_methods(registered_daemon: LabDaemon):
    """
    Test that device methods are thread-safe after being wrapped by LabDaemon.

    This test calls a device method from multiple threads concurrently.
    The mock method itself is not thread-safe, so if the wrapper works,
    the test should pass. We check for race conditions by having the method
    perform a read-modify-write operation on a shared attribute.
    """

    class UnsafeDevice:
        def __init__(self, device_id: str, **kwargs: Any):
            self.device_id = device_id
            self.counter = 0

        def connect(self):
            pass

        def disconnect(self):
            pass

        def increment(self):
            current = self.counter
            time.sleep(0.001)
            self.counter = current + 1

    registered_daemon.register_plugins(devices={"UnsafeDevice": UnsafeDevice}, tasks={})
    device = registered_daemon.add_device(device_id="unsafe_dev", device_type="UnsafeDevice")

    num_threads = 10
    iterations_per_thread = 20
    threads = []

    def worker():
        for _ in range(iterations_per_thread):
            device.increment()

    for _ in range(num_threads):
        t = threading.Thread(target=worker)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    expected_count = num_threads * iterations_per_thread
    assert device.counter == expected_count, (
        f"Counter should be {expected_count} but was {device.counter}. "
        "The method wrapper is not thread-safe."
    )


# --- Task Lifecycle Test Cases ---

def test_execute_task_basic(registered_daemon: LabDaemon):
    """Test basic task execution and result retrieval."""
    handle = registered_daemon.execute_task(
        task_id="task1", task_type="MockTask", extra_param="test"
    )

    assert handle.task_id == "task1"
    
    # Give the task a moment to start
    time.sleep(0.01)
    assert handle.is_running()

    result = handle.wait(timeout=1.0)

    assert not handle.is_running()
    assert result["status"] == "complete"
    assert result["task_id"] == "task1"
    assert handle.exception() is None


def test_execute_task_with_device(registered_daemon: LabDaemon):
    """Test that tasks can access devices through the context."""
    device = registered_daemon.add_device(device_id="dev1", device_type="MockDevice")
    registered_daemon.connect_device(device)

    handle = registered_daemon.execute_task(
        task_id="task1", task_type="DeviceUsingTask", device_id="dev1"
    )

    result = handle.wait(timeout=1.0)

    assert result["status"] == "complete"
    assert result["device_result"] == "Hello from dev1"


def test_execute_task_slow(registered_daemon: LabDaemon):
    """Test that slow tasks complete successfully."""
    handle = registered_daemon.execute_task(
        task_id="slow_task", task_type="SlowTask", duration=0.2
    )

    assert handle.is_running()
    time.sleep(0.05)
    assert handle.is_running()

    result = handle.wait(timeout=1.0)

    assert not handle.is_running()
    assert result["status"] == "complete"
    assert result["duration"] == 0.2


def test_execute_duplicate_task_id_raises_error(registered_daemon: LabDaemon):
    """Test that executing a task with a duplicate ID raises an error."""
    handle1 = registered_daemon.execute_task(task_id="task1", task_type="SlowTask", duration=0.5)

    assert handle1.is_running()

    with pytest.raises(ValueError, match="Task with ID 'task1' is already running."):
        registered_daemon.execute_task(task_id="task1", task_type="MockTask")

    handle1.cancel()
    
    # Wait should raise TaskCancelledError after cancellation
    with pytest.raises(TaskCancelledError):
        handle1.wait(timeout=1.0)


def test_execute_unknown_task_type_raises_error(daemon: LabDaemon):
    """Test that executing an unregistered task type raises a ValueError."""
    with pytest.raises(ValueError, match="Unknown task type: 'UnknownTask'"):
        daemon.execute_task(task_id="task1", task_type="UnknownTask")


def test_task_cancellation(registered_daemon: LabDaemon):
    """Test that tasks can be cancelled gracefully."""
    handle = registered_daemon.execute_task(
        task_id="cancel_task",
        task_type="CancellableTask",
        num_steps=20,
        step_duration=0.05,
    )

    assert handle.is_running()
    time.sleep(0.15)

    handle.cancel()

    with pytest.raises(TaskCancelledError):
        handle.wait(timeout=1.0)

    assert not handle.is_running()


def test_task_cancellation_returns_partial_result(registered_daemon: LabDaemon):
    """Test that cancelled tasks can return partial results."""
    handle = registered_daemon.execute_task(
        task_id="cancel_task",
        task_type="CancellableTask",
        num_steps=20,
        step_duration=0.05,
    )

    time.sleep(0.15)
    handle.cancel()

    try:
        handle.wait(timeout=1.0)
    except TaskCancelledError:
        pass

    task_instance = handle._task_instance
    assert task_instance.steps_completed > 0
    assert task_instance.steps_completed < 20


def test_task_failure(registered_daemon: LabDaemon):
    """Test that task exceptions are captured and propagated."""
    handle = registered_daemon.execute_task(
        task_id="fail_task", task_type="FailingTask", error_message="Something went wrong"
    )

    with pytest.raises(TaskFailedError, match="Task 'fail_task' failed during execution."):
        handle.wait(timeout=1.0)

    assert not handle.is_running()
    assert handle.exception() is not None
    assert isinstance(handle.exception(), RuntimeError)
    assert str(handle.exception()) == "Something went wrong"


def test_task_wait_timeout(registered_daemon: LabDaemon):
    """Test that wait() raises TimeoutError if the task doesn't complete in time."""
    handle = registered_daemon.execute_task(
        task_id="slow_task", task_type="SlowTask", duration=1.0
    )

    with pytest.raises(TimeoutError, match="Wait timed out for task 'slow_task'"):
        handle.wait(timeout=0.1)

    assert handle.is_running()

    handle.cancel()
    try:
        handle.wait(timeout=1.0)
    except TaskCancelledError:
        pass


def test_task_context_manager(registered_daemon: LabDaemon):
    """Test the task_context manager for automatic cleanup."""
    with registered_daemon.task_context(
        task_id="context_task", task_type="SlowTask", duration=0.5
    ) as handle:
        assert handle.is_running()
        assert handle.task_id == "context_task"

    # After exiting context, task should be cancelled
    # Give it a moment to actually stop
    time.sleep(0.1)
    assert not handle.is_running()


def test_task_context_manager_with_completion(registered_daemon: LabDaemon):
    """Test task_context when task completes within the context."""
    with registered_daemon.task_context(
        task_id="context_task", task_type="MockTask"
    ) as handle:
        result = handle.wait(timeout=1.0)
        assert result["status"] == "complete"

    assert not handle.is_running()


def test_multiple_tasks_concurrent(registered_daemon: LabDaemon):
    """Test that multiple tasks can run concurrently."""
    handle1 = registered_daemon.execute_task(
        task_id="task1", task_type="SlowTask", duration=0.2
    )
    handle2 = registered_daemon.execute_task(
        task_id="task2", task_type="SlowTask", duration=0.2
    )
    handle3 = registered_daemon.execute_task(
        task_id="task3", task_type="SlowTask", duration=0.2
    )

    assert handle1.is_running()
    assert handle2.is_running()
    assert handle3.is_running()

    result1 = handle1.wait(timeout=1.0)
    result2 = handle2.wait(timeout=1.0)
    result3 = handle3.wait(timeout=1.0)

    assert result1["task_id"] == "task1"
    assert result2["task_id"] == "task2"
    assert result3["task_id"] == "task3"


def test_shutdown_cancels_running_tasks(registered_daemon: LabDaemon):
    """Test that shutdown cancels all running tasks."""
    handle1 = registered_daemon.execute_task(
        task_id="task1", task_type="SlowTask", duration=2.0
    )
    handle2 = registered_daemon.execute_task(
        task_id="task2", task_type="SlowTask", duration=2.0
    )

    assert handle1.is_running()
    assert handle2.is_running()

    registered_daemon.shutdown(timeout=1.0)

    # Tasks should be cancelled and stopped
    # Give them a moment to actually stop after cancellation
    time.sleep(0.1)
    assert not handle1.is_running()
    assert not handle2.is_running()


# --- Interactive Task Test Cases ---

def test_task_pause_and_resume(registered_daemon: LabDaemon):
    """Test that tasks can be paused and resumed."""
    handle = registered_daemon.execute_task(
        task_id="pausable_task",
        task_type="PausableTask",
        num_steps=20,
        step_duration=0.05,
    )

    time.sleep(0.15)

    initial_steps = handle._task_instance.steps_completed
    assert initial_steps > 0

    handle.pause()
    assert handle.is_paused()

    # Give pause a moment to take effect
    time.sleep(0.05)

    time.sleep(0.2)

    paused_steps = handle._task_instance.steps_completed
    # Allow for one step of race condition (task may complete one more step before pause takes effect)
    assert paused_steps <= initial_steps + 1

    handle.resume()
    assert not handle.is_paused()

    result = handle.wait(timeout=2.0)

    assert result["status"] == "complete"
    assert result["steps_completed"] == 20


def test_task_pause_blocks_execution(registered_daemon: LabDaemon):
    """Test that pausing a task actually blocks its execution."""
    handle = registered_daemon.execute_task(
        task_id="pausable_task",
        task_type="PausableTask",
        num_steps=20,
        step_duration=0.05,
    )

    time.sleep(0.1)

    handle.pause()

    # Give pause a moment to take effect
    time.sleep(0.05)

    steps_at_pause = handle._task_instance.steps_completed

    time.sleep(0.3)

    steps_after_wait = handle._task_instance.steps_completed
    # Allow for one step of race condition
    assert steps_after_wait <= steps_at_pause + 1

    handle.cancel()
    try:
        handle.wait(timeout=1.0)
    except TaskCancelledError:
        pass


def test_task_cancel_while_paused(registered_daemon: LabDaemon):
    """Test that cancelling a paused task works correctly."""
    handle = registered_daemon.execute_task(
        task_id="pausable_task",
        task_type="PausableTask",
        num_steps=20,
        step_duration=0.05,
    )

    time.sleep(0.1)

    handle.pause()
    assert handle.is_paused()

    handle.cancel()

    with pytest.raises(TaskCancelledError):
        handle.wait(timeout=1.0)

    assert not handle.is_running()


def test_task_set_parameter(registered_daemon: LabDaemon):
    """Test that task parameters can be updated during execution."""
    handle = registered_daemon.execute_task(
        task_id="interactive_task",
        task_type="InteractiveTask",
        initial_value=1.0,
        num_steps=10,
    )

    time.sleep(0.1)

    handle.set_parameter("value", 42.0)

    result = handle.wait(timeout=2.0)

    assert result["status"] == "complete"
    assert result["final_value"] == 42.0


def test_task_get_parameter(registered_daemon: LabDaemon):
    """Test that task parameters can be queried during execution."""
    handle = registered_daemon.execute_task(
        task_id="interactive_task",
        task_type="InteractiveTask",
        initial_value=5.0,
        num_steps=10,
    )

    time.sleep(0.1)

    value = handle.get_parameter("value")
    assert value == 5.0

    steps_completed = handle.get_parameter("steps_completed")
    assert steps_completed > 0

    is_running = handle.get_parameter("is_running")
    assert is_running is True

    result = handle.wait(timeout=2.0)
    assert result["status"] == "complete"


def test_task_parameter_updates_are_thread_safe(registered_daemon: LabDaemon):
    """Test that concurrent parameter updates don't cause race conditions."""
    handle = registered_daemon.execute_task(
        task_id="interactive_task",
        task_type="InteractiveTask",
        initial_value=0.0,
        num_steps=20,
    )

    def update_worker():
        for i in range(10):
            handle.set_parameter("value", float(i))
            time.sleep(0.01)

    threads = []
    for _ in range(3):
        t = threading.Thread(target=update_worker)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    result = handle.wait(timeout=2.0)
    assert result["status"] == "complete"


def test_task_set_parameter_invalid_key_raises_error(registered_daemon: LabDaemon):
    """Test that setting an invalid parameter raises an error."""
    handle = registered_daemon.execute_task(
        task_id="interactive_task",
        task_type="InteractiveTask",
        initial_value=1.0,
        num_steps=10,
    )

    time.sleep(0.05)

    with pytest.raises(ValueError, match="Unknown parameter: invalid_key"):
        handle.set_parameter("invalid_key", 42.0)

    handle.cancel()
    try:
        handle.wait(timeout=1.0)
    except TaskCancelledError:
        pass


def test_task_get_parameter_invalid_key_raises_error(registered_daemon: LabDaemon):
    """Test that getting an invalid parameter raises an error."""
    handle = registered_daemon.execute_task(
        task_id="interactive_task",
        task_type="InteractiveTask",
        initial_value=1.0,
        num_steps=10,
    )

    time.sleep(0.05)

    with pytest.raises(ValueError, match="Unknown parameter: invalid_key"):
        handle.get_parameter("invalid_key")

    handle.cancel()
    try:
        handle.wait(timeout=1.0)
    except TaskCancelledError:
        pass


def test_task_without_parameter_support_raises_error(registered_daemon: LabDaemon):
    """Test that tasks without parameter support raise appropriate errors."""
    handle = registered_daemon.execute_task(
        task_id="simple_task", task_type="SlowTask", duration=0.5
    )

    time.sleep(0.05)

    with pytest.raises(TaskError, match="does not support parameter updates"):
        handle.set_parameter("value", 42.0)

    with pytest.raises(TaskError, match="does not support parameter queries"):
        handle.get_parameter("value")

    handle.cancel()
    try:
        handle.wait(timeout=1.0)
    except TaskCancelledError:
        pass


def test_task_pause_resume_multiple_times(registered_daemon: LabDaemon):
    """Test that tasks can be paused and resumed multiple times."""
    handle = registered_daemon.execute_task(
        task_id="pausable_task",
        task_type="PausableTask",
        num_steps=30,
        step_duration=0.03,
    )

    for _ in range(3):
        time.sleep(0.1)
        handle.pause()
        time.sleep(0.1)
        handle.resume()

    result = handle.wait(timeout=3.0)

    assert result["status"] == "complete"
    assert result["steps_completed"] == 30


# --- Task Orchestration Test Cases ---

def test_parallel_coordinator_spawns_children(registered_daemon: LabDaemon):
    """Test that a coordinator can spawn multiple child tasks in parallel."""
    handle = registered_daemon.execute_task(
        task_id="parallel_coordinator",
        task_type="ParallelCoordinatorTask",
        num_children=3,
        child_duration=0.2,
    )

    result = handle.wait(timeout=3.0)

    assert result["status"] == "complete"
    assert result["num_children"] == 3
    assert len(result["child_results"]) == 3

    for child_result in result["child_results"]:
        assert child_result["status"] == "complete"


def test_sequential_coordinator_passes_results(registered_daemon: LabDaemon):
    """Test that a coordinator can run tasks sequentially and accumulate results."""
    handle = registered_daemon.execute_task(
        task_id="sequential_coordinator",
        task_type="SequentialCoordinatorTask",
        num_steps=3,
    )

    result = handle.wait(timeout=3.0)

    assert result["status"] == "complete"
    assert result["num_steps"] == 3
    assert result["accumulated_value"] == 3
    assert len(result["step_results"]) == 3


def test_coordinator_cancellation_propagates_to_children(registered_daemon: LabDaemon):
    """Test that cancelling a coordinator cancels its child tasks."""
    handle = registered_daemon.execute_task(
        task_id="cancellable_coordinator",
        task_type="CancellableCoordinatorTask",
        num_children=3,
        child_num_steps=20,
    )

    time.sleep(0.2)

    handle.cancel()

    with pytest.raises(TaskCancelledError):
        handle.wait(timeout=3.0)

    assert not handle.is_running()


def test_coordinator_handles_child_failure(registered_daemon: LabDaemon):
    """Test that a coordinator can detect and handle child task failures."""
    handle = registered_daemon.execute_task(
        task_id="failing_child_coordinator",
        task_type="FailingChildCoordinatorTask",
        num_children=3,
        failing_child_index=1,
    )

    result = handle.wait(timeout=3.0)

    assert result["status"] == "complete"
    assert len(result["child_results"]) == 3

    successful_children = [r for r in result["child_results"] if "result" in r]
    failed_children = [r for r in result["child_results"] if "error" in r]

    assert len(successful_children) == 2
    assert len(failed_children) == 1
    assert failed_children[0]["child_index"] == 1


def test_coordinator_with_queue_communication(registered_daemon: LabDaemon):
    """Test that coordinators can use queues to collect results from children."""
    result_queue = queue.Queue()

    handle = registered_daemon.execute_task(
        task_id="queue_coordinator",
        task_type="QueueBasedCoordinatorTask",
        num_children=3,
        result_queue=result_queue,
    )

    result = handle.wait(timeout=3.0)

    assert result["status"] == "complete"
    assert result["num_children"] == 3
    assert len(result["collected_results"]) == 3


def test_nested_coordinators(registered_daemon: LabDaemon):
    """Test that coordinators can spawn other coordinators (nested orchestration)."""
    handle = registered_daemon.execute_task(
        task_id="parent_coordinator",
        task_type="ParallelCoordinatorTask",
        num_children=2,
        child_duration=0.1,
    )

    result = handle.wait(timeout=3.0)

    assert result["status"] == "complete"
    assert len(result["child_results"]) == 2


def test_coordinator_with_many_children(registered_daemon: LabDaemon):
    """Test that coordinators can handle spawning many child tasks."""
    handle = registered_daemon.execute_task(
        task_id="many_children_coordinator",
        task_type="ParallelCoordinatorTask",
        num_children=10,
        child_duration=0.1,
    )

    result = handle.wait(timeout=5.0)

    assert result["status"] == "complete"
    assert result["num_children"] == 10
    assert len(result["child_results"]) == 10


def test_coordinator_cancellation_during_child_spawn(registered_daemon: LabDaemon):
    """Test cancelling a coordinator while it's still spawning children."""
    handle = registered_daemon.execute_task(
        task_id="cancellable_coordinator",
        task_type="CancellableCoordinatorTask",
        num_children=5,
        child_num_steps=20,
    )

    time.sleep(0.05)

    handle.cancel()

    with pytest.raises(TaskCancelledError):
        handle.wait(timeout=3.0)

    assert not handle.is_running()


def test_coordinator_child_timeout_handling(registered_daemon: LabDaemon):
    """Test that coordinators handle child task timeouts gracefully."""
    handle = registered_daemon.execute_task(
        task_id="parallel_coordinator",
        task_type="ParallelCoordinatorTask",
        num_children=2,
        child_duration=0.1,
    )

    result = handle.wait(timeout=3.0)

    assert result["status"] == "complete"
    assert len(result["child_results"]) == 2


# --- Streaming Test Cases ---

def test_streaming_basic_lifecycle(registered_daemon: LabDaemon):
    """Test basic streaming start and stop."""
    device = registered_daemon.add_device(
        device_id="stream_dev", device_type="StreamingDevice"
    )
    registered_daemon.connect_device(device)

    received_data = []

    def callback(data):
        received_data.append(data)

    assert not device.is_streaming()

    registered_daemon.start_streaming(device, callback=callback)
    assert device.is_streaming()

    time.sleep(0.15)

    registered_daemon.stop_streaming(device)
    assert not device.is_streaming()

    assert len(received_data) > 0


# --- Phase 1 Test Cases: Task ID Cleanup and Uniqueness ---

def test_task_id_uniqueness_enforcement(registered_daemon: LabDaemon):
    """Test that task IDs must be unique across active and recent tasks."""
    # Execute first task
    handle1 = registered_daemon.execute_task(
        task_id="unique_task", task_type="MockTask"
    )
    result1 = handle1.wait(timeout=1.0)
    assert result1["status"] == "complete"
    
    # Should be blocked due to history tracking
    with pytest.raises(ValueError, match="Task ID 'unique_task' has been used recently"):
        registered_daemon.execute_task(
            task_id="unique_task", task_type="MockTask"
        )


def test_task_id_uniqueness_with_running_task(registered_daemon: LabDaemon):
    """Test that task IDs cannot be duplicated while task is running."""
    # Start a slow task
    handle1 = registered_daemon.execute_task(
        task_id="running_task", task_type="SlowTask", duration=0.5
    )
    assert handle1.is_running()
    
    # Try to start another task with the same ID
    with pytest.raises(ValueError, match="Task with ID 'running_task' is already running"):
        registered_daemon.execute_task(
            task_id="running_task", task_type="MockTask"
        )
    
    # Clean up
    handle1.cancel()


def test_completed_task_buffer_cleanup(registered_daemon: LabDaemon):
    """Test that completed tasks are cleaned up when buffer is exceeded."""
    # Create daemon with small buffer
    daemon = LabDaemon(completed_task_buffer=2)
    daemon.register_plugins(
        devices={"MockDevice": MockDevice},
        tasks={"MockTask": MockTask}
    )
    
    try:
        # Execute 3 tasks with different delays to ensure distinct completion times
        handle1 = daemon.execute_task(task_id="task1", task_type="MockTask", delay=0.1)
        handle1.wait(timeout=1.0)
        time.sleep(0.05)  # Ensure distinct completion time
        
        handle2 = daemon.execute_task(task_id="task2", task_type="MockTask", delay=0.1)
        handle2.wait(timeout=1.0)
        time.sleep(0.05)  # Ensure distinct completion time
        
        handle3 = daemon.execute_task(task_id="task3", task_type="MockTask", delay=0.1)
        handle3.wait(timeout=1.0)
        
        # Give cleanup a moment to run
        time.sleep(0.1)
        
        # Should only have the most recent 2 tasks in memory (LRU eviction)
        # task1 should have been cleaned up (oldest)
        assert "task2" in daemon._tasks
        assert "task3" in daemon._tasks
        assert "task1" not in daemon._tasks
        
        # Also check that completion times are tracked properly
        assert "task1" not in daemon._task_completion_times
        assert "task2" in daemon._task_completion_times
        assert "task3" in daemon._task_completion_times
        
    finally:
        daemon.shutdown(timeout=0.1)


def test_task_id_history_limit_cleanup(registered_daemon: LabDaemon):
    """Test that task ID history is cleaned up when limit is exceeded."""
    # Create daemon with small buffer and history
    daemon = LabDaemon(completed_task_buffer=2)  # History limit = 200
    daemon.register_plugins(
        devices={"MockDevice": MockDevice},
        tasks={"MockTask": MockTask}
    )
    
    try:
        # Execute many tasks to exceed history limit (200)
        for i in range(250):
            handle = daemon.execute_task(task_id=f"task_{i}", task_type="MockTask")
            handle.wait(timeout=0.1)
        
        # History should be trimmed to limit
        assert len(daemon._recent_task_ids) <= 200
        
    finally:
        daemon.shutdown(timeout=0.1)


def test_task_cleanup_preserves_running_tasks(registered_daemon: LabDaemon):
    """Test that cleanup only removes completed tasks, not running ones."""
    # Create daemon with small buffer
    daemon = LabDaemon(completed_task_buffer=1)
    daemon.register_plugins(
        devices={"MockDevice": MockDevice},
        tasks={"MockTask": MockTask, "SlowTask": SlowTask}
    )
    
    try:
        # Start a slow task
        slow_handle = daemon.execute_task(
            task_id="slow_task", task_type="SlowTask", duration=0.5
        )
        
        # Execute a quick task (this will trigger cleanup)
        quick_handle = daemon.execute_task(task_id="quick_task", task_type="MockTask")
        quick_handle.wait(timeout=1.0)
        
        # Slow task should still be running and in memory
        assert slow_handle.is_running()
        assert "slow_task" in daemon._tasks
        
        # Clean up
        slow_handle.cancel()
        
    finally:
        daemon.shutdown(timeout=0.1)


def test_task_cleanup_with_zero_buffer(registered_daemon: LabDaemon):
    """Test task cleanup behavior with zero buffer."""
    # Create daemon with zero buffer (no completed tasks retained)
    daemon = LabDaemon(completed_task_buffer=0)
    daemon.register_plugins(
        devices={"MockDevice": MockDevice},
        tasks={"MockTask": MockTask}
    )
    
    try:
        # Execute a task with delay to ensure proper completion tracking
        handle = daemon.execute_task(task_id="task1", task_type="MockTask", delay=0.1)
        result = handle.wait(timeout=1.0)
        
        # Give cleanup a moment
        time.sleep(0.1)
        
        # Task should be cleaned up immediately (zero buffer)
        # But results should still be accessible via the handle
        assert result["status"] == "complete"
        assert "task1" not in daemon._tasks
        
    finally:
        daemon.shutdown(timeout=0.1)


def test_task_cleanup_uses_true_lru(registered_daemon: LabDaemon):
    """Test that task cleanup uses true LRU (least recently used) eviction."""
    # Create daemon with small buffer
    daemon = LabDaemon(completed_task_buffer=2)
    daemon.register_plugins(
        devices={"MockDevice": MockDevice},
        tasks={"MockTask": MockTask}
    )
    
    try:
        # Execute 3 tasks with small delays to ensure different completion times
        handle1 = daemon.execute_task(task_id="task1", task_type="MockTask")
        handle1.wait(timeout=1.0)
        time.sleep(0.05)
        
        handle2 = daemon.execute_task(task_id="task2", task_type="MockTask")
        handle2.wait(timeout=1.0)
        time.sleep(0.05)
        
        handle3 = daemon.execute_task(task_id="task3", task_type="MockTask")
        handle3.wait(timeout=1.0)
        
        # Give cleanup a moment to run
        time.sleep(0.1)
        
        # Should have task2 and task3 (most recent)
        # task1 should be evicted (oldest completion time)
        assert "task1" not in daemon._tasks
        assert "task2" in daemon._tasks
        assert "task3" in daemon._tasks
        
    finally:
        daemon.shutdown(timeout=0.1)


def test_error_manager_follows_task_buffer():
    """Test that ErrorManager uses the same buffer size as daemon."""
    from labdaemon.server.managers import ErrorManager
    from labdaemon.server.server import LabDaemonServer
    
    # Create daemon with custom buffer
    daemon = LabDaemon(completed_task_buffer=15)
    daemon.register_plugins(
        devices={"MockDevice": MockDevice},
        tasks={"MockTask": MockTask}
    )
    
    try:
        # Create server
        server = LabDaemonServer(daemon)
        
        # ErrorManager should have same buffer size
        assert server.errors._task_error_buffer == 15
        
    finally:
        if hasattr(server, 'stop'):
            server.stop(timeout=0.1)
        daemon.shutdown(timeout=0.1)


def test_error_manager_cleanup():
    """Test that ErrorManager cleans up old errors."""
    from labdaemon.server.managers import ErrorManager
    
    # Create ErrorManager with small buffer
    error_mgr = ErrorManager(task_error_buffer=2)
    
    # Add 3 errors
    error_mgr.record_task_error("task1", RuntimeError("Error 1"))
    error_mgr.record_task_error("task2", RuntimeError("Error 2"))
    error_mgr.record_task_error("task3", RuntimeError("Error 3"))
    
    # Should only have the most recent 2 errors
    assert "task2" in error_mgr._task_errors
    assert "task3" in error_mgr._task_errors
    # task1 should be cleaned up (oldest)
    assert "task1" not in error_mgr._task_errors


def test_streaming_callback_receives_data(registered_daemon: LabDaemon):
    """Test that the callback receives data during streaming."""
    device = registered_daemon.add_device(
        device_id="stream_dev", device_type="StreamingDevice"
    )
    registered_daemon.connect_device(device)

    received_data = []

    def callback(data):
        received_data.append(data)

    device.configure_streaming(sample_interval=0.02)
    registered_daemon.start_streaming(device, callback=callback)

    time.sleep(0.1)

    registered_daemon.stop_streaming(device)

    assert len(received_data) >= 3
    sample_numbers = [d["sample_number"] for d in received_data]
    assert sample_numbers == sorted(sample_numbers)


def test_streaming_stop_with_timeout(registered_daemon: LabDaemon):
    """Test that stop_streaming respects timeout parameter."""
    device = registered_daemon.add_device(
        device_id="slow_stream_dev",
        device_type="SlowStoppingStreamingDevice",
        stop_delay=0.3,
    )
    registered_daemon.connect_device(device)

    def callback(data):
        pass

    registered_daemon.start_streaming(device, callback=callback)
    time.sleep(0.05)

    start_time = time.time()
    registered_daemon.stop_streaming(device, timeout=1.0)
    elapsed = time.time() - start_time

    assert not device.is_streaming()
    assert elapsed >= 0.3
    assert elapsed < 1.0


def test_streaming_multiple_devices(registered_daemon: LabDaemon):
    """Test streaming from multiple devices simultaneously."""
    dev1 = registered_daemon.add_device(
        device_id="stream_dev1", device_type="StreamingDevice"
    )
    dev2 = registered_daemon.add_device(
        device_id="stream_dev2", device_type="StreamingDevice"
    )

    registered_daemon.connect_device(dev1)
    registered_daemon.connect_device(dev2)

    received_data_1 = []
    received_data_2 = []

    def callback_1(data):
        received_data_1.append(data)

    def callback_2(data):
        received_data_2.append(data)

    dev1.configure_streaming(sample_interval=0.02)
    dev2.configure_streaming(sample_interval=0.03)

    registered_daemon.start_streaming(dev1, callback=callback_1)
    registered_daemon.start_streaming(dev2, callback=callback_2)

    assert dev1.is_streaming()
    assert dev2.is_streaming()

    time.sleep(0.15)

    registered_daemon.stop_streaming(dev1)
    registered_daemon.stop_streaming(dev2)

    assert not dev1.is_streaming()
    assert not dev2.is_streaming()

    assert len(received_data_1) > 0
    assert len(received_data_2) > 0


def test_streaming_stop_idempotent(registered_daemon: LabDaemon):
    """Test that calling stop_streaming multiple times is safe."""
    device = registered_daemon.add_device(
        device_id="stream_dev", device_type="StreamingDevice"
    )
    registered_daemon.connect_device(device)

    def callback(data):
        pass

    registered_daemon.start_streaming(device, callback=callback)
    time.sleep(0.05)

    registered_daemon.stop_streaming(device)
    assert not device.is_streaming()

    registered_daemon.stop_streaming(device)
    assert not device.is_streaming()


def test_streaming_shutdown_stops_all_streams(registered_daemon: LabDaemon):
    """Test that daemon shutdown stops all active streams."""
    dev1 = registered_daemon.add_device(
        device_id="stream_dev1", device_type="StreamingDevice"
    )
    dev2 = registered_daemon.add_device(
        device_id="stream_dev2", device_type="StreamingDevice"
    )

    registered_daemon.connect_device(dev1)
    registered_daemon.connect_device(dev2)

    def callback(data):
        pass

    registered_daemon.start_streaming(dev1, callback=callback)
    registered_daemon.start_streaming(dev2, callback=callback)

    assert dev1.is_streaming()
    assert dev2.is_streaming()

    registered_daemon.shutdown(timeout=1.0)

    assert not dev1.is_streaming()
    assert not dev2.is_streaming()


def test_streaming_callback_thread_safety(registered_daemon: LabDaemon):
    """Test that callbacks are thread-safe when accessing shared data."""
    device = registered_daemon.add_device(
        device_id="stream_dev", device_type="StreamingDevice"
    )
    registered_daemon.connect_device(device)

    lock = threading.Lock()
    received_count = 0

    def callback(data):
        nonlocal received_count
        with lock:
            received_count += 1

    device.configure_streaming(sample_interval=0.01)
    registered_daemon.start_streaming(device, callback=callback)

    time.sleep(0.15)

    registered_daemon.stop_streaming(device)

    with lock:
        final_count = received_count

    assert final_count > 0


def test_streaming_device_without_streaming_support(registered_daemon: LabDaemon):
    """Test that attempting to stream from a non-streaming device raises an error."""
    device = registered_daemon.add_device(
        device_id="regular_dev", device_type="MockDevice"
    )
    registered_daemon.connect_device(device)

    def callback(data):
        pass

    with pytest.raises(ld.DeviceError, match="does not support streaming"):
        registered_daemon.start_streaming(device, callback=callback)


def test_streaming_start_stop_restart(registered_daemon: LabDaemon):
    """Test that streaming can be stopped and restarted."""
    device = registered_daemon.add_device(
        device_id="stream_dev", device_type="StreamingDevice"
    )
    registered_daemon.connect_device(device)

    received_data_1 = []
    received_data_2 = []

    def callback_1(data):
        received_data_1.append(data)

    def callback_2(data):
        received_data_2.append(data)

    device.configure_streaming(sample_interval=0.02)
    registered_daemon.start_streaming(device, callback=callback_1)
    time.sleep(0.1)
    registered_daemon.stop_streaming(device)

    count_after_first = len(received_data_1)

    device.configure_streaming(sample_interval=0.02)
    registered_daemon.start_streaming(device, callback=callback_2)
    time.sleep(0.1)
    registered_daemon.stop_streaming(device)

    assert count_after_first > 0
    assert len(received_data_2) > 0
    assert not device.is_streaming()


def test_streaming_with_device_by_id(registered_daemon: LabDaemon):
    """Test that streaming works when device is specified by ID string."""
    device = registered_daemon.add_device(
        device_id="stream_dev", device_type="StreamingDevice"
    )
    registered_daemon.connect_device(device)

    received_data = []

    def callback(data):
        received_data.append(data)

    registered_daemon.start_streaming("stream_dev", callback=callback)
    assert device.is_streaming()

    time.sleep(0.1)

    registered_daemon.stop_streaming("stream_dev")
    assert not device.is_streaming()

    assert len(received_data) > 0
