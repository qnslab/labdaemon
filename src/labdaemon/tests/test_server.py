"""Integration tests for the LabDaemon server module."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from labdaemon import LabDaemon
from labdaemon.server import LabDaemonServer
from labdaemon.server.managers import OwnershipManager, ErrorManager
from labdaemon.exceptions import TaskError


class TestOwnershipManager:
    """Unit tests for the OwnershipManager."""

    def test_claim_devices_success(self):
        """Test successful device claiming."""
        manager = OwnershipManager()
        
        manager.claim_devices("task1", ["dev1", "dev2"])
        
        assert manager.get_owner("dev1") == "task1"
        assert manager.get_owner("dev2") == "task1"

    def test_claim_devices_conflict(self):
        """Test device claiming raises error on conflict."""
        manager = OwnershipManager()
        
        manager.claim_devices("task1", ["dev1", "dev2"])
        
        with pytest.raises(TaskError, match="already owned"):
            manager.claim_devices("task2", ["dev1"])

    def test_claim_devices_partial_conflict(self):
        """Test claiming multiple devices with partial conflict."""
        manager = OwnershipManager()
        
        manager.claim_devices("task1", ["dev1"])
        
        # Try to claim dev1 (owned) and dev2 (free) - should fail atomically
        with pytest.raises(TaskError, match="already owned"):
            manager.claim_devices("task2", ["dev1", "dev2"])
        
        # dev2 should NOT be claimed (atomic failure)
        assert manager.get_owner("dev2") is None

    def test_release_devices(self):
        """Test device release."""
        manager = OwnershipManager()
        
        manager.claim_devices("task1", ["dev1", "dev2"])
        manager.release_devices("task1")
        
        assert manager.get_owner("dev1") is None
        assert manager.get_owner("dev2") is None

    def test_release_devices_idempotent(self):
        """Test releasing devices multiple times is safe."""
        manager = OwnershipManager()
        
        manager.claim_devices("task1", ["dev1"])
        manager.release_devices("task1")
        manager.release_devices("task1")  # Should not raise
        
        assert manager.get_owner("dev1") is None

    def test_get_owner_unowned_device(self):
        """Test getting owner of unowned device returns None."""
        manager = OwnershipManager()
        
        assert manager.get_owner("dev1") is None

    def test_reclaim_own_devices(self):
        """Test task can re-claim its own devices."""
        manager = OwnershipManager()
        
        manager.claim_devices("task1", ["dev1"])
        manager.claim_devices("task1", ["dev1"])  # Should not raise
        
        assert manager.get_owner("dev1") == "task1"

    def test_clear_all(self):
        """Test clearing all ownership."""
        manager = OwnershipManager()
        
        manager.claim_devices("task1", ["dev1"])
        manager.claim_devices("task2", ["dev2"])
        
        manager.clear_all()
        
        assert manager.get_owner("dev1") is None
        assert manager.get_owner("dev2") is None


class TestErrorManager:
    """Unit tests for the ErrorManager."""

    def test_record_and_get_device_error(self):
        """Test recording and retrieving device errors."""
        manager = ErrorManager()
        
        exc = ValueError("Test error")
        manager.record_device_error("dev1", exc, origin="device")
        
        error = manager.get_device_error("dev1")
        assert error is not None
        assert error["error"]["type"] == "ValueError"
        assert error["error"]["message"] == "Test error"
        assert error["error"]["origin"] == "device"

    def test_get_device_error_not_found(self):
        """Test getting error for device with no error returns None."""
        manager = ErrorManager()
        
        assert manager.get_device_error("dev1") is None

    def test_clear_device_error(self):
        """Test clearing device errors."""
        manager = ErrorManager()
        
        exc = ValueError("Test error")
        manager.record_device_error("dev1", exc)
        manager.clear_device_error("dev1")
        
        assert manager.get_device_error("dev1") is None

    def test_clear_device_error_idempotent(self):
        """Test clearing error multiple times is safe."""
        manager = ErrorManager()
        
        exc = ValueError("Test error")
        manager.record_device_error("dev1", exc)
        manager.clear_device_error("dev1")
        manager.clear_device_error("dev1")  # Should not raise

    def test_record_task_error(self):
        """Test recording and retrieving task errors."""
        manager = ErrorManager()
        
        exc = RuntimeError("Task failed")
        manager.record_task_error("task1", exc, origin="framework")
        
        error = manager.get_task_error("task1")
        assert error is not None
        assert error["error"]["type"] == "RuntimeError"
        assert error["error"]["message"] == "Task failed"
        assert error["error"]["origin"] == "framework"

    def test_error_overwrite(self):
        """Test new errors overwrite old ones."""
        manager = ErrorManager()
        
        exc1 = ValueError("First error")
        exc2 = RuntimeError("Second error")
        
        manager.record_device_error("dev1", exc1)
        manager.record_device_error("dev1", exc2)
        
        error = manager.get_device_error("dev1")
        assert error["error"]["type"] == "RuntimeError"
        assert error["error"]["message"] == "Second error"

    def test_error_context(self):
        """Test error context is stored."""
        manager = ErrorManager()
        
        exc = ValueError("Test error")
        context = {"method": "set_value", "args": [42]}
        manager.record_device_error("dev1", exc, context=context)
        
        error = manager.get_device_error("dev1")
        assert error["error"]["context"]["method"] == "set_value"
        assert error["error"]["context"]["args"] == [42]


class TestServerIntegration:
    """Integration tests for server functionality."""

    def test_server_with_mock_device(self):
        """Test server with a mock device that has methods."""
        class MockDevice:
            def __init__(self, device_id: str):
                self.device_id = device_id
                self._connected = False
                self._streaming = False
            
            def connect(self):
                """Connect the device."""
                self._connected = True
            
            def disconnect(self):
                """Disconnect the device."""
                self._connected = False
                self._streaming = False
            
            def is_connected(self):
                """Check if device is connected."""
                return self._connected
            
            def start_streaming(self, callback):
                """Start streaming data."""
                self._streaming = True
            
            def stop_streaming(self, timeout=None):
                """Stop streaming data."""
                self._streaming = False
            
            def is_streaming(self):
                """Check if device is streaming."""
                return self._streaming
            
            def set_value(self, value: float) -> None:
                """Set a value."""
                pass
            
            def get_value(self) -> float:
                """Get a value."""
                return 42.0
        
        daemon = LabDaemon()
        server = LabDaemonServer(daemon)
        client = TestClient(server.app)
        
        device = MockDevice("test_device")
        daemon._devices["test_device"] = device
        
        response = client.get("/devices")
        assert response.status_code == 200
        data = response.json()
        assert len(data["devices"]) == 1
        assert data["devices"][0]["device_id"] == "test_device"
        assert data["devices"][0]["device_type"] == "MockDevice"
        assert data["devices"][0]["connected"] is False
        assert data["devices"][0]["streaming"] is False
        
        response = client.get("/devices/test_device")
        assert response.status_code == 200
        data = response.json()
        assert data["device_id"] == "test_device"
        assert data["last_error"] is None
        
        response = client.get("/devices/test_device/methods")
        assert response.status_code == 200
        data = response.json()
        methods = {m["name"] for m in data["methods"]}
        expected_methods = {
            "connect", "disconnect", "is_connected", "start_streaming",
            "stop_streaming", "is_streaming", "set_value", "get_value"
        }
        assert expected_methods.issubset(methods)
        
        set_value = next(m for m in data["methods"] if m["name"] == "set_value")
        assert set_value["parameters"][0]["name"] == "value"
        assert set_value["parameters"][0]["required"] is True

    def test_server_error_handling(self):
        """Test server error recording and retrieval."""
        daemon = LabDaemon()
        server = LabDaemonServer(daemon)
        client = TestClient(server.app)
        
        server.errors.record_device_error(
            "test_device",
            ValueError("Device connection failed"),
            origin="device",
            context={"attempt": 1}
        )
        
        response = client.get("/devices/test_device/error")
        assert response.status_code == 404
        
        class MockDevice:
            def __init__(self, device_id: str):
                self.device_id = device_id
        
        daemon._devices["test_device"] = MockDevice("test_device")
        
        response = client.get("/devices/test_device/error")
        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert data["error"]["type"] == "ValueError"
        assert data["error"]["message"] == "Device connection failed"
        assert data["error"]["origin"] == "device"
        assert data["error"]["context"]["attempt"] == 1

    def test_ownership_manager_integration(self):
        """Test ownership tracking with server."""
        daemon = LabDaemon()
        server = LabDaemonServer(daemon)
        client = TestClient(server.app)
        
        class MockDevice:
            def __init__(self, device_id: str):
                self.device_id = device_id
        
        daemon._devices["device1"] = MockDevice("device1")
        
        response = client.get("/devices/device1")
        assert response.status_code == 200
        data = response.json()
        assert data["owned_by"] is None
        
        server.ownership.claim_devices("task1", ["device1"])
        
        response = client.get("/devices/device1")
        assert response.status_code == 200
        data = response.json()
        assert data["owned_by"] == "task1"
        
        server.ownership.release_devices("task1")
        
        response = client.get("/devices/device1")
        assert response.status_code == 200
        data = response.json()
        assert data["owned_by"] is None

    def test_server_lifecycle(self):
        """Test server start and stop lifecycle."""
        daemon = LabDaemon()
        
        server = LabDaemonServer(daemon, host="localhost", port=0)
        
        assert server._server_thread is None
        
        server.start(blocking=False)
        
        assert server._server_thread is not None
        assert server._server_thread.is_alive()
        
        server.stop(timeout=2.0)
        
        assert not server._server_thread.is_alive()

    def test_server_with_real_workflow(self):
        """Test a more realistic workflow with devices and tasks."""
        class MockLaser:
            def __init__(self, device_id: str):
                self.device_id = device_id
                self._wavelength = 1550.0
                self._power = 0.0
                self._connected = False
            
            def connect(self):
                self._connected = True
            
            def disconnect(self):
                self._connected = False
            
            def is_connected(self):
                return self._connected
            
            def set_wavelength(self, wavelength_nm: float):
                """Set laser wavelength in nm."""
                self._wavelength = wavelength_nm
            
            def get_wavelength(self) -> float:
                """Get current wavelength in nm."""
                return self._wavelength
            
            def set_power(self, power_mw: float):
                """Set laser power in mW."""
                self._power = power_mw
            
            def get_power(self) -> float:
                """Get current power in mW."""
                return self._power
        
        daemon = LabDaemon()
        server = LabDaemonServer(daemon)
        client = TestClient(server.app)
        
        laser = MockLaser("laser1")
        daemon._devices["laser1"] = laser
        
        laser.connect()
        
        response = client.get("/devices/laser1")
        assert response.status_code == 200
        data = response.json()
        assert data["connected"] is True
        
        response = client.get("/devices/laser1/methods")
        assert response.status_code == 200
        data = response.json()
        
        set_wl = next(m for m in data["methods"] if m["name"] == "set_wavelength")
        assert set_wl["parameters"][0]["name"] == "wavelength_nm"
        assert "nm" in set_wl["doc"] if "doc" in set_wl else True
        
        device = daemon.get_device("laser1")
        assert device is laser
        assert device.get_wavelength() == 1550.0
        
        device.set_wavelength(1555.0)
        assert device.get_wavelength() == 1555.0

    def test_device_method_calling(self):
        """Test remote device method calling."""
        class MockDevice:
            def __init__(self, device_id: str):
                self.device_id = device_id
                self._value = 0
                self._connected = False
            
            def connect(self):
                self._connected = True
            
            def disconnect(self):
                self._connected = False
            
            def is_connected(self):
                return self._connected
            
            def set_value(self, value: int) -> int:
                """Set a value and return the old value."""
                old = self._value
                self._value = value
                return old
            
            def get_value(self) -> int:
                return self._value
            
            def add_numbers(self, a: int, b: int) -> int:
                return a + b
            
            def _private_method(self):
                return "should not be callable"
        
        daemon = LabDaemon()
        server = LabDaemonServer(daemon)
        client = TestClient(server.app)
        
        device = MockDevice("test_device")
        daemon._devices["test_device"] = device
        
        response = client.post("/devices/test_device/call", json={
            "method": "get_value"
        })
        assert response.status_code == 200
        data = response.json()
        if "error" in data:
            print(f"Unexpected error response: {data}")
        assert "error" not in data
        assert "result" in data
        assert data["result"] == 0
        
        response = client.post("/devices/test_device/call", json={
            "method": "set_value",
            "args": [42]
        })
        assert response.status_code == 200
        data = response.json()
        assert "error" not in data
        assert data["result"] == 0
        assert device.get_value() == 42
        
        response = client.post("/devices/test_device/call", json={
            "method": "add_numbers",
            "args": [2, 3]
        })
        assert response.status_code == 200
        data = response.json()
        assert "error" not in data
        assert data["result"] == 5
        
        response = client.post("/devices/test_device/call", json={
            "method": "get_value",
            "args": [],
            "kwargs": {}
        })
        assert response.status_code == 200
        data = response.json()
        assert "error" not in data
        assert data["result"] == 42
        
        response = client.post("/devices/test_device/call", json={})
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert "Method name is required" in data["error"]["message"]
        
        response = client.post("/devices/test_device/call", json={
            "method": "_private_method"
        })
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert "Private methods cannot be called" in data["error"]["message"]
        
        response = client.post("/devices/test_device/call", json={
            "method": "nonexistent_method"
        })
        assert response.status_code == 404
        data = response.json()
        assert "error" in data
        assert "not found on device" in data["error"]["message"]
        
        response = client.post("/devices/test_device/call", json={
            "method": "device_id"
        })
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert "is not a method" in data["error"]["message"]
        
        response = client.post("/devices/test_device/call", json={
            "method": "set_value",
            "args": "not a list"
        })
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert "'args' must be a list" in data["error"]["message"]
        
        response = client.post("/devices/test_device/call", json={
            "method": "set_value",
            "kwargs": "not a dict"
        })
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert "'kwargs' must be a dict" in data["error"]["message"]
        
        def failing_method():
            raise ValueError("Test error")
        
        device.failing_method = failing_method
        
        response = client.post("/devices/test_device/call", json={
            "method": "failing_method"
        })
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert data["error"]["type"] == "ValueError"
        assert data["error"]["message"] == "Test error"
        assert data["error"]["origin"] == "device"
        
        response = client.get("/devices/test_device/error")
        assert response.status_code == 200
        error = response.json()
        assert "error" in error
        assert error["error"]["type"] == "ValueError"
        assert error["error"]["message"] == "Test error"
        assert error["error"]["origin"] == "device"
        
        response = client.delete("/devices/test_device/error")
        assert response.status_code == 204
        
        response = client.get("/devices/test_device/error")
        assert response.status_code == 404
        
        response = client.post("/devices/nonexistent/call", json={
            "method": "get_value"
        })
        assert response.status_code == 404

    def test_device_method_calling_with_ownership(self):
        """Test device method calling respects ownership."""
        class MockDevice:
            def __init__(self, device_id: str):
                self.device_id = device_id
            
            def set_value(self, value: int):
                pass
        
        daemon = LabDaemon()
        server = LabDaemonServer(daemon)
        client = TestClient(server.app)
        
        device = MockDevice("test_device")
        daemon._devices["test_device"] = device
        
        server.ownership.claim_devices("owner_task", ["test_device"])
        
        response = client.post("/devices/test_device/call", json={
            "method": "set_value",
            "args": [42]
        })
        assert response.status_code == 409
        data = response.json()
        assert "error" in data
        assert data["error"]["type"] == "DeviceInUse"
        assert "is owned by task" in data["error"]["message"]
        assert data["error"]["context"]["task_id"] == "owner_task"
        
        server.ownership.release_devices("owner_task")
        
        response = client.post("/devices/test_device/call", json={
            "method": "set_value",
            "args": [42]
        })
        assert response.status_code == 200
        data = response.json()
        assert "error" not in data

    def test_task_execution_endpoints(self):
        """Test task execution HTTP endpoints."""
        class MockTask:
            def __init__(self, task_id: str, device_id: str):
                self.task_id = task_id
                self.device_id = device_id
                self.device_ids = [device_id]
            
            def run(self, context):
                import time; time.sleep(0.1)
                return {"result": "task completed"}
        
        class MockDevice:
            def __init__(self, device_id: str):
                self.device_id = device_id
        
        daemon = LabDaemon()
        server = LabDaemonServer(daemon)
        client = TestClient(server.app)
        
        daemon.register_plugins(devices={}, tasks={"MockTask": MockTask})
        
        device = MockDevice("test_device")
        daemon._devices["test_device"] = device
        
        response = client.post("/tasks", json={
            "task_id": "task1",
            "task_type": "MockTask",
            "params": {"device_id": "test_device"}
        })
        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == "task1"
        assert data["task_type"] == "MockTask"
        assert data["device_ids"] == ["test_device"]
        assert data["status"] == "started"
        
        response = client.get("/devices/test_device")
        assert response.status_code == 200
        device_info = response.json()
        assert device_info["owned_by"] == "task1"
        
        response = client.post("/tasks", json={
            "task_id": "task2",
            "task_type": "MockTask",
            "params": {"device_id": "test_device"}
        })
        assert response.status_code == 409
        data = response.json()
        assert "error" in data
        assert data["error"]["type"] == "DeviceInUse"
        assert "already owned" in data["error"]["message"]
        
        response = client.post("/tasks", json={
            "task_type": "MockTask"
        })
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert "task_id is required" in data["error"]["message"]
        
        response = client.post("/tasks", json={
            "task_id": "task3"
        })
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert "task_type is required" in data["error"]["message"]
        
        response = client.post("/tasks", json={
            "task_id": "task3",
            "task_type": "MockTask",
            "params": "not a dict"
        })
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert "params must be a dict" in data["error"]["message"]
        
        response = client.post("/tasks", json={
            "task_id": "task3",
            "task_type": "UnknownTask"
        })
        assert response.status_code == 404
        data = response.json()
        assert "error" in data
        assert "Unknown task type" in data["error"]["message"]
        
        class BadTask:
            def __init__(self, task_id: str):
                self.task_id = task_id
                self.device_ids = "not a list"
            
            def run(self, context):
                pass
        
        daemon.register_plugins(devices={}, tasks={"BadTask": BadTask})
        
        response = client.post("/tasks", json={
            "task_id": "bad_task",
            "task_type": "BadTask"
        })
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert "device_ids must be a list" in data["error"]["message"]
        
        class BadTask2:
            def __init__(self, task_id: str):
                self.task_id = task_id
                self.device_ids = [123]
            
            def run(self, context):
                pass
        
        daemon.register_plugins(devices={}, tasks={"BadTask2": BadTask2})
        
        response = client.post("/tasks", json={
            "task_id": "bad_task2",
            "task_type": "BadTask2"
        })
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert "must contain only strings" in data["error"]["message"]
        
        class FailingTask:
            def __init__(self, task_id: str):
                raise ValueError("Task init failed")
        
        daemon.register_plugins(devices={}, tasks={"FailingTask": FailingTask})
        
        response = client.post("/tasks", json={
            "task_id": "failing_task",
            "task_type": "FailingTask"
        })
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert "Failed to instantiate task" in data["error"]["message"]
        assert "Task init failed" in data["error"]["message"]
        
        response = client.delete("/tasks/failing_task/error")
        assert response.status_code == 204
        
        response = client.get("/tasks/failing_task/error")
        assert response.status_code == 404
