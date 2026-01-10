"""
LabDaemon Server Implementation

Provides HTTP/SSE server functionality for LabDaemon using FastAPI.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse, ServerSentEvent
from loguru import logger

from ..daemon import LabDaemon
from ..exceptions import DeviceError, TaskError
from ..handlers import TaskHandle
from .._version import __version__
from .managers import ErrorManager, OwnershipManager, SSEManager


class LabDaemonServer:
    """
    HTTP/SSE server for LabDaemon.
    
    Provides monitoring and control endpoints for remote clients.
    
    Parameters
    ----------
    daemon : LabDaemon
        The LabDaemon instance to expose.
    host : str, default "0.0.0.0"
        Host to bind to.
    port : int, default 5000
        Port to bind to.
    
    Notes
    -----
    Only one server per daemon is supported.
    
    Examples
    --------
    >>> from labdaemon import LabDaemon
    >>> from labdaemon.server import LabDaemonServer
    >>> 
    >>> daemon = LabDaemon()
    >>> server = LabDaemonServer(daemon, host="0.0.0.0", port=5000)
    >>> 
    >>> # Register plugins, add devices, etc.
    >>> daemon.register_plugins(devices={...}, tasks={...})
    >>> 
    >>> # Start server
    >>> server.start(blocking=False)
    >>> 
    >>> # ... do work ...
    >>> 
    >>> # Shutdown
    >>> server.stop()
    >>> daemon.shutdown()
    """
    
    def __init__(
        self,
        daemon: LabDaemon,
        host: str = "0.0.0.0",
        port: int = 5000
    ):
        if hasattr(daemon, '_server_attached'):
            raise ValueError("Only one server per LabDaemon instance is allowed")
        
        self.daemon = daemon
        self.host = host
        self.port = port
        self._server_thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()
        self._server_instance: Optional[Any] = None
        daemon._server_attached = True
        
        # Initialize managers
        self.ownership = OwnershipManager()
        # Phase 1: Pass the daemon's task buffer to ErrorManager for consistent retention
        self.errors = ErrorManager(task_error_buffer=daemon._completed_task_buffer)
        self.sse = SSEManager(daemon_ref=daemon)
        
        # Create FastAPI app
        self.app = FastAPI(
            title="LabDaemon Server",
            description="HTTP/SSE API for LabDaemon",
            version=__version__
        )
        
        # Add CORS middleware
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],  # Allow all origins for development
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # Add request logging middleware
        @self.app.middleware("http")
        async def log_requests(request: Request, call_next):
            start_time = time.time()
            
            # Log incoming request
            logger.debug(f"[HTTP] {request.method} {request.url.path} - Request received")
            
            try:
                response = await call_next(request)
                duration = time.time() - start_time
                
                # Log response with different levels based on status
                if response.status_code >= 500:
                    logger.error(f"[HTTP] {request.method} {request.url.path} - {response.status_code} ({duration:.3f}s)")
                elif response.status_code >= 400:
                    logger.warning(f"[HTTP] {request.method} {request.url.path} - {response.status_code} ({duration:.3f}s)")
                elif request.url.path == "/health":
                    # Health checks at debug level to avoid spam
                    logger.debug(f"[HTTP] {request.method} {request.url.path} - {response.status_code} ({duration:.3f}s)")
                else:
                    logger.info(f"[HTTP] {request.method} {request.url.path} - {response.status_code} ({duration:.3f}s)")
                
                return response
                
            except Exception as e:
                duration = time.time() - start_time
                logger.exception(f"[HTTP] {request.method} {request.url.path} - Exception after {duration:.3f}s: {e}")
                raise
        
        # Setup routes
        self._setup_routes()
    
    def start(self, blocking: bool = False) -> None:
        """
        Start the server.
        
        Parameters
        ----------
        blocking : bool, default False
            If True, blocks until server is stopped.
            If False, runs in background thread.
        """
        if blocking:
            self._run_server_blocking()
        else:
            self._server_thread = threading.Thread(
                target=self._run_server_blocking,
                daemon=True,
                name="LabDaemonServer"
            )
            self._server_thread.start()
            logger.info(f"LabDaemon server started on http://{self.host}:{self.port}")
    
    def stop(self, timeout: float = 5.0) -> None:
        """
        Stop the server gracefully.
        
        Parameters
        ----------
        timeout : float, default 5.0
            Maximum time to wait for server to stop.
        """
        logger.info("LabDaemon server shutdown initiated")
        
        # Stop all SSE streams first
        self.sse.shutdown() # Call the new shutdown method on SSEManager
        
        # Signal shutdown
        self._shutdown_event.set()
        
        # Stop uvicorn server if running
        if self._server_instance is not None:
            self._server_instance.should_exit = True
        
        # Wait for server thread
        if self._server_thread:
            self._server_thread.join(timeout=timeout)
            if self._server_thread.is_alive():
                logger.warning(
                    f"Server thread did not stop within {timeout}s"
                )
        
        # Clean up server attachment flag
        if hasattr(self.daemon, '_server_attached'):
            delattr(self.daemon, '_server_attached')
        
        logger.info("LabDaemon server stopped")
    
    def _execute_task_with_ownership(self, task_id: str, task_type: str, **kwargs) -> TaskHandle:
        """
        Execute a task with device ownership enforcement.
        
        This wraps the daemon's execute_task to claim devices BEFORE the task
        thread starts, preventing race conditions.
        
        Parameters
        ----------
        task_id : str
            Unique identifier for the task.
        task_type : str
            The registered task type name.
        **kwargs
            Arguments passed to the task constructor.
        
        Returns
        -------
        TaskHandle
            Handle to the running task.
        
        Raises
        ------
        ValueError
            If task type is unknown.
        TaskError
            If devices are already owned by another task.
        Exception
            If task instantiation fails.
        """
        # 1. Check if task type is registered
        try:
            task_class = self.daemon._task_classes[task_type]
        except KeyError:
            raise ValueError(
                f"Unknown task type: '{task_type}'. Is the plugin registered?"
            )
        
        # 2. Instantiate task to read device_ids
        logger.debug(f"Instantiating task {task_id} of type {task_type}")
        try:
            task_instance = task_class(task_id=task_id, **kwargs)
        except Exception as e:
            logger.exception(f"Failed to instantiate task {task_id}")
            raise Exception(
                f"Failed to instantiate task '{task_id}' of type '{task_type}': {str(e)}"
            )
        
        # 3. Validate and extract device_ids
        device_ids = getattr(task_instance, 'device_ids', [])
        
        if device_ids and not isinstance(device_ids, list):
            raise TaskError(
                f"Task '{task_id}': self.device_ids must be a list of strings"
            )
        
        # 4. Claim devices BEFORE starting task (atomic)
        try:
            if device_ids:
                logger.info(f"[OWNERSHIP] Task '{task_id}' attempting to claim devices: {device_ids}")
                self.ownership.claim_devices(task_id, device_ids)
                logger.info(f"[OWNERSHIP] Task '{task_id}' successfully claimed devices: {device_ids}")
            else:
                logger.debug(f"[OWNERSHIP] Task '{task_id}' requires no device ownership")
        except TaskError as e:
            logger.error(f"[OWNERSHIP] Task '{task_id}' failed to claim devices {device_ids}: {e}")
            # Record ownership conflict error before propagating
            self.errors.record_task_error(
                task_id,
                e,
                origin="framework",
                context={"task_type": task_type}
            )
            raise  # Propagate conflict error
        
        # 5. Start task (now safe - devices are claimed)
        try:
            # Define cleanup callback to be passed to the daemon
            def cleanup():
                # Release devices first
                self.ownership.release_devices(task_id)
                
                # Record exception if the task failed
                try:
                    handle = self.daemon._tasks[task_id]
                    if handle._exception:
                        self.errors.record_task_error(
                            task_id,
                            handle._exception,
                            origin="framework",
                            context={"task_id": task_id}
                        )
                except (KeyError, AttributeError):
                    logger.warning(
                        f"Could not record error for task '{task_id}' during cleanup."
                    )

            handle = self.daemon.execute_task(
                task_id, task_type, **kwargs, _server_cleanup_func=cleanup
            )
            
            return handle
            
        except Exception as e:
            # Rollback: release devices if task start fails
            if device_ids:
                self.ownership.release_devices(task_id)
            
            # Record error
            self.errors.record_task_error(
                task_id,
                e,
                origin="framework",
                context={"task_type": task_type}
            )
            
            raise
    
    def _run_server_blocking(self) -> None:
        """Internal: Run the FastAPI server (blocking)."""
        import uvicorn
        
        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_config=None,  # Use our own logging
        )
        server = uvicorn.Server(config)
        self._server_instance = server
        
        try:
            server.run()
        except Exception as e:
            if not self._shutdown_event.is_set():
                logger.exception(f"Server error: {e}")
        finally:
            self._server_instance = None
    
    def _error_response(
        self,
        status_code: int,
        error_type: str,
        message: str,
        origin: str = "framework",
        context: Optional[dict] = None
    ) -> JSONResponse:
        """
        Create a standardised error response.
        
        Parameters
        ----------
        status_code : int
            HTTP status code.
        error_type : str
            Error type name.
        message : str
            Error message.
        origin : str, default "framework"
            Error origin: "framework", "device", or "callback".
        context : dict, optional
            Additional context information.
        
        Returns
        -------
        JSONResponse
            FastAPI JSON response with error wrapped in {"error": {...}}.
        """
        return JSONResponse(
            status_code=status_code,
            content={
                "error": {
                    "type": error_type,
                    "message": message,
                    "origin": origin,
                    "timestamp": self._get_timestamp(),
                    "context": context or {}
                }
            }
        )
    
    def _setup_routes(self) -> None:
        """Setup FastAPI routes."""
        
        @self.app.get("/")
        async def root():
            """Root endpoint with server info."""
            return {
                "name": "LabDaemon Server",
                "version": "0.2.0",
                "phase": "2 (full-control)",
                "endpoints": {
                    "devices": "/devices",
                    "device_detail": "/devices/{device_id}",
                    "device_methods": "/devices/{device_id}/methods",
                    "device_error": "/devices/{device_id}/error",
                    "clear_device_error": "/devices/{device_id}/error",
                    "device_call": "/devices/{device_id}/call",
                    "add_device": "/devices",
                    "connect_device": "/devices/{device_id}/connect",
                    "disconnect_device": "/devices/{device_id}/disconnect",
                    "health": "/health",
                    "tasks": "/tasks",
                    "execute_task": "/tasks",
                    "task_detail": "/tasks/{task_id}",
                    "task_error": "/tasks/{task_id}/error",
                    "clear_task_error": "/tasks/{task_id}/error",
                    "cancel_task": "/tasks/{task_id}/cancel",
                    "pause_task": "/tasks/{task_id}/pause",
                    "resume_task": "/tasks/{task_id}/resume",
                    "set_task_parameter": "/tasks/{task_id}/parameters",
                    "device_stream": "/stream/devices/{device_id}",
                    "stop_device_stream": "/devices/{device_id}/stream/stop"
                }
            }
        
        @self.app.get("/health")
        async def health_check():
            """Health check endpoint."""
            return {"status": "healthy", "timestamp": self._get_timestamp()}
        
        @self.app.get("/devices")
        async def list_devices():
            """List all devices with basic status."""
            devices = []
            for device_id, device in self.daemon._devices.items():
                device_info = {
                    "device_id": device_id,
                    "device_type": type(device).__name__,
                    "connected": getattr(device, 'is_connected', lambda: False)(),
                    "streaming": getattr(device, 'is_streaming', lambda: False)(),
                    "owned_by": self.ownership.get_owner(device_id)
                }
                
                # Add error if present
                error = self.errors.get_device_error(device_id)
                if error:
                    device_info["last_error"] = error
                else:
                    device_info["last_error"] = None
                
                devices.append(device_info)
            
            return {"devices": devices}
        
        @self.app.get("/devices/{device_id}")
        async def get_device(device_id: str):
            """Get detailed information about a device."""
            try:
                device = self.daemon.get_device(device_id)
            except ValueError as e:
                return self._error_response(404, "DeviceNotFound", str(e))
            
            device_info = {
                "device_id": device_id,
                "device_type": type(device).__name__,
                "connected": getattr(device, 'is_connected', lambda: True)(),
                "streaming": getattr(device, 'is_streaming', lambda: False)(),
                "owned_by": self.ownership.get_owner(device_id)
            }
            
            # Add error if present
            error = self.errors.get_device_error(device_id)
            if error:
                device_info["last_error"] = error
            else:
                device_info["last_error"] = None
            
            return device_info
        
        @self.app.get("/devices/{device_id}/methods")
        async def list_device_methods(device_id: str):
            """List available methods for a device."""
            try:
                device = self.daemon.get_device(device_id)
            except ValueError as e:
                return self._error_response(404, "DeviceNotFound", str(e))
            
            import inspect
            
            methods = []
            for name in dir(device):
                if name.startswith("_"):
                    continue
                
                attr = getattr(device, name)
                if not callable(attr):
                    continue
                
                method_info = {"name": name}
                
                # Try to get signature
                try:
                    sig = inspect.signature(attr)
                    # Remove 'self' parameter for bound methods
                    params = [
                        p for p_name, p in sig.parameters.items()
                        if p_name != 'self'
                    ]
                    method_info["parameters"] = []
                    
                    for p in params:
                        param_info = {"name": p.name}
                        
                        # Map Python type to JSON Schema type
                        TYPE_MAP = {
                            int: "integer",
                            float: "number",
                            str: "string",
                            bool: "boolean",
                            list: "array",
                            dict: "object",
                            type(None): "null"
                        }
                        
                        if p.annotation != inspect.Parameter.empty:
                            python_type = p.annotation
                            param_info["type"] = TYPE_MAP.get(python_type, "any")
                        else:
                            param_info["type"] = "any"
                        
                        # Handle default values
                        if p.default != inspect.Parameter.empty:
                            param_info["required"] = False
                            if isinstance(p.default, bool):
                                param_info["default"] = p.default
                            elif isinstance(p.default, (int, float, str)):
                                param_info["default"] = p.default
                            elif p.default is None:
                                param_info["default"] = None
                            else:
                                param_info["default"] = str(p.default)
                        else:
                            param_info["required"] = True
                        
                        method_info["parameters"].append(param_info)
                        
                except (ValueError, TypeError):
                    # Signature unavailable
                    method_info["parameters"] = []
                
                # Try to get docstring
                doc = inspect.getdoc(attr)
                if doc:
                    method_info["doc"] = doc
                
                methods.append(method_info)
            
            return {"methods": methods}
        
        @self.app.get("/devices/{device_id}/error")
        async def get_device_error(device_id: str):
            """Get the last error for a device."""
            # Check if device exists first
            try:
                self.daemon.get_device(device_id)
            except ValueError as e:
                return self._error_response(404, "DeviceNotFound", str(e))
            
            error = self.errors.get_device_error(device_id)
            if error is None:
                return self._error_response(404, "NoError", "No error recorded for device")
            
            return error
        
        @self.app.delete("/devices/{device_id}/error")
        async def clear_device_error(device_id: str):
            """Clear the last error for a device."""
            error = self.errors.get_device_error(device_id)
            if error is None:
                return self._error_response(404, "NoError", "No error recorded for device")

            self.errors.clear_device_error(device_id)
            return JSONResponse(status_code=204, content=None)
        
        @self.app.post("/devices")
        async def add_device(body: dict):
            """Add a new device to the daemon."""
            device_id = body.get("device_id")
            device_type = body.get("device_type")
            params = body.get("params", {})
            
            if not device_id:
                return self._error_response(
                    400, "InvalidRequest", "device_id is required"
                )
            
            if not device_type:
                return self._error_response(
                    400, "InvalidRequest", "device_type is required"
                )
            
            if not isinstance(params, dict):
                return self._error_response(
                    400, "InvalidRequest", "params must be a dict"
                )
            
            # Check if device already exists
            if device_id in self.daemon._devices:
                return self._error_response(
                    409,
                    "DeviceExists",
                    f"Device '{device_id}' already exists",
                    context={"device_id": device_id}
                )
            
            # Check if device type is registered
            if device_type not in self.daemon._device_classes:
                return self._error_response(
                    404,
                    "DeviceTypeNotFound",
                    f"Device type '{device_type}' is not registered",
                    context={"device_type": device_type}
                )
            
            try:
                # Add device using daemon's method
                device = self.daemon.add_device(device_id, device_type, **params)
                
                return {
                    "device_id": device_id,
                    "device_type": device_type,
                    "connected": getattr(device, 'is_connected', lambda: False)(),
                    "streaming": getattr(device, 'is_streaming', lambda: False)(),
                    "owned_by": self.ownership.get_owner(device_id)
                }
                
            except Exception as e:
                return self._error_response(
                    400,
                    "DeviceCreationError",
                    f"Failed to create device '{device_id}': {str(e)}",
                    origin="device",
                    context={"device_id": device_id, "device_type": device_type}
                )
        
        @self.app.post("/devices/{device_id}/connect")
        async def connect_device(device_id: str):
            """Connect a device with timeout protection."""
            try:
                device = self.daemon.get_device(device_id)
            except ValueError as e:
                return self._error_response(404, "DeviceNotFound", str(e))
            
            # Check if already connected
            if getattr(device, 'is_connected', lambda: True)():
                return {
                    "device_id": device_id,
                    "connected": True,
                    "message": "Device is already connected"
                }
            
            try:
                # Add timeout to connection operation using threading
                import threading
                
                result = {"success": False, "error": None}
                
                def connect_with_timeout():
                    try:
                        self.daemon.connect_device(device)
                        result["success"] = True
                    except Exception as e:
                        result["error"] = e
                
                thread = threading.Thread(target=connect_with_timeout, daemon=True)
                thread.start()
                thread.join(timeout=30.0)  # 30 second timeout
                
                if thread.is_alive():
                    # Timeout occurred, but we can't force stop the underlying operation.
                    # Log a warning and proceed as if it failed.
                    logger.warning(f"Device connection for '{device_id}' timed out after 30 seconds. "
                                   "The underlying connection attempt may still be running.")
                    raise TimeoutError("Device connection timed out after 30 seconds")
                
                if not result["success"]:
                    if result["error"]:
                        raise result["error"]
                    else:
                        raise RuntimeError("Connection failed for unknown reason")
                
                # Phase 4: Broadcast connection event
                logger.info(f"[Phase4] Device '{device_id}' connected successfully")
                # TODO (future): Broadcast connection_status event via SSE to all listeners
                # This would allow clients to receive real-time notifications when devices connect
                
                return {
                    "device_id": device_id,
                    "connected": getattr(device, 'is_connected', lambda: False)(),
                    "streaming": getattr(device, 'is_streaming', lambda: False)(),
                    "owned_by": self.ownership.get_owner(device_id)
                }
                
            except Exception as e:
                self.errors.record_device_error(
                    device_id,
                    e,
                    origin="device",
                    context={"action": "connect"}
                )
                
                return self._error_response(
                    400,
                    "DeviceConnectionError",
                    f"Failed to connect device '{device_id}': {str(e)}",
                    origin="device",
                    context={"device_id": device_id}
                )
        
        @self.app.post("/devices/{device_id}/disconnect")
        async def disconnect_device(device_id: str):
            """Disconnect a device with timeout protection."""
            try:
                device = self.daemon.get_device(device_id)
            except ValueError as e:
                return self._error_response(404, "DeviceNotFound", str(e))
            
            # Check if device is owned by a task
            owner_task_id = self.ownership.get_owner(device_id)
            if owner_task_id is not None:
                return self._error_response(
                    409,
                    "DeviceInUse",
                    f"Device '{device_id}' is owned by task '{owner_task_id}' and cannot be disconnected",
                    context={"device_id": device_id, "task_id": owner_task_id}
                )
            
            # Check if already disconnected
            if not getattr(device, 'is_connected', lambda: True)():
                return {
                    "device_id": device_id,
                    "connected": False,
                    "message": "Device is already disconnected"
                }
            
            try:
                # Add timeout to disconnection operation using threading
                import threading
                
                result = {"success": False, "error": None}
                
                def disconnect_with_timeout():
                    try:
                        self.daemon.disconnect_device(device)
                        result["success"] = True
                    except Exception as e:
                        result["error"] = e
                
                thread = threading.Thread(target=disconnect_with_timeout, daemon=True)
                thread.start()
                thread.join(timeout=30.0)  # 30 second timeout
                
                if thread.is_alive():
                    # Timeout occurred, but we can't force stop the underlying operation.
                    # Log a warning and proceed as if it failed.
                    logger.warning(f"Device disconnection for '{device_id}' timed out after 30 seconds. "
                                   "The underlying disconnection attempt may still be running.")
                    raise TimeoutError("Device disconnection timed out after 30 seconds")
                
                if not result["success"]:
                    if result["error"]:
                        raise result["error"]
                    else:
                        raise RuntimeError("Disconnection failed for unknown reason")
                
                # Phase 4: Broadcast disconnection event
                logger.info(f"[Phase4] Device '{device_id}' disconnected successfully")
                # TODO (future): Broadcast connection_status event via SSE to all listeners
                # This would allow clients to receive real-time notifications when devices disconnect
                
                return {
                    "device_id": device_id,
                    "connected": getattr(device, 'is_connected', lambda: False)(),
                    "streaming": getattr(device, 'is_streaming', lambda: False)(),
                    "owned_by": None
                }
                
            except Exception as e:
                self.errors.record_device_error(
                    device_id,
                    e,
                    origin="device",
                    context={"action": "disconnect"}
                )
                
                return self._error_response(
                    400,
                    "DeviceDisconnectionError",
                    f"Failed to disconnect device '{device_id}': {str(e)}",
                    origin="device",
                    context={"device_id": device_id}
                )
        
        @self.app.post("/devices/{device_id}/call")
        async def call_device_method(device_id: str, body: dict):
            """Call a method on a device."""
            try:
                device = self.daemon.get_device(device_id)
            except ValueError as e:
                return self._error_response(404, "DeviceNotFound", str(e))

            # Check ownership before allowing a command
            owner_task_id = self.ownership.get_owner(device_id)
            if owner_task_id is not None:
                return self._error_response(
                    409,
                    "DeviceInUse",
                    f"Device '{device_id}' is owned by task '{owner_task_id}'",
                    context={"device_id": device_id, "task_id": owner_task_id},
                )

            # Validate method name
            method_name = body.get("method")
            if not method_name:
                return self._error_response(
                    400, "InvalidRequest", "Method name is required"
                )

            if method_name.startswith("_"):
                return self._error_response(
                    400, "InvalidRequest", "Private methods cannot be called remotely"
                )

            if not hasattr(device, method_name):
                return self._error_response(
                    404,
                    "MethodNotFound",
                    f"Method '{method_name}' not found on device '{device_id}'",
                )

            method = getattr(device, method_name)
            if not callable(method):
                return self._error_response(
                    400, "InvalidRequest", f"'{method_name}' is not a method"
                )

            # Extract args and kwargs
            args = body.get("args", [])
            kwargs = body.get("kwargs", {})

            if not isinstance(args, list):
                return self._error_response(
                    400, "InvalidRequest", "'args' must be a list"
                )

            if not isinstance(kwargs, dict):
                return self._error_response(
                    400, "InvalidRequest", "'kwargs' must be a dict"
                )

            # Call method and handle result
            try:
                result = method(*args, **kwargs)
                return {
                    "result": result,
                    "success": True
                }
            except Exception as e:
                # Record error in error manager
                self.errors.record_device_error(
                    device_id,
                    e,
                    origin="device",
                    context={
                        "method": method_name,
                        "args": args,
                        "kwargs": kwargs
                    }
                )
                
                # Return error response with appropriate status code
                if isinstance(e, (ValueError, TypeError, RuntimeError)):
                    # Common device errors - return 400
                    status_code = 400
                else:
                    # Unexpected errors - return 500
                    status_code = 500
                
                return self._error_response(
                    status_code,
                    type(e).__name__,
                    str(e),
                    origin="device",
                    context={"device_id": device_id, "method": method_name}
                )
        
        @self.app.post("/devices/{device_id}/stream/stop")
        async def stop_device_stream(device_id: str):
            """
            Stop streaming on a device and close any active SSE connections.
            
            This endpoint provides explicit control over device streaming lifecycle.
            It stops the device's streaming immediately and closes any active SSE
            connections, ensuring a clean state for subsequent operations.
            
            This is the recommended way to stop streaming before starting a new stream,
            as it guarantees the device is in a clean state and prevents race conditions
            where a new stream might be rejected due to the old stream still being active.
            
            Parameters
            ----------
            device_id : str
                The device identifier.
            
            Returns
            -------
            dict
                Response with stop status and timestamp.
            
            Notes
            -----
            This endpoint is idempotent - calling it multiple times is safe.
            It does not require the device to be currently streaming.
            
            Examples
            --------
            Stop streaming on a device:
            
            >>> POST /devices/daq1/stream/stop
            >>> {"status": "stopped", "device_id": "daq1", "timestamp": "2024-01-15T10:30:00+00:00"}
            """
            try:
                device = self.daemon.get_device(device_id)
            except ValueError as e:
                return self._error_response(404, "DeviceNotFound", str(e))
            
            logger.info(f"[STREAM] Stopping device stream for '{device_id}'")
            
            # Stop the device streaming (idempotent - safe to call if not streaming)
            try:
                if hasattr(device, 'stop_streaming'):
                    device.stop_streaming(timeout=2.0)
                    logger.info(f"[STREAM] Device '{device_id}' streaming stopped")
            except Exception as e:
                logger.warning(f"[STREAM] Error stopping device streaming for '{device_id}': {e}")
                # Don't fail the request - continue to close SSE connections
            
            # Stop any active SSE stream (closes client connections)
            self.sse.stop_stream(device_id)
            logger.info(f"[STREAM] SSE stream closed for '{device_id}'")
            
            return {
                "status": "stopped",
                "device_id": device_id,
                "timestamp": self._get_timestamp()
            }
        
        @self.app.get("/tasks")
        async def list_tasks():
            """List all tasks with basic status."""
            tasks = []
            for task_id, handle in self.daemon._tasks.items():
                task_info = {
                    "task_id": task_id,
                    "task_type": type(handle._task_instance).__name__,
                    "running": handle.is_running()
                }
                tasks.append(task_info)
            
            return {"tasks": tasks}
        
        @self.app.get("/tasks/{task_id}")
        async def get_task(task_id: str):
            """Get detailed information about a task."""
            try:
                handle = self.daemon._tasks[task_id]
            except KeyError:
                return self._error_response(404, "TaskNotFound", "Task not found")
            
            task_info = {
                "task_id": task_id,
                "task_type": type(handle._task_instance).__name__,
                "running": handle.is_running(),
                "result": handle._result if not handle.is_running() else None,
                "exception": None
            }
            
            # Add exception if present (wrapped in error format)
            if handle._exception:
                task_info["exception"] = {
                    "error": {
                        "type": type(handle._exception).__name__,
                        "message": str(handle._exception),
                        "origin": "framework",
                        "timestamp": self._get_timestamp(),
                        "context": {"task_id": task_id}
                    }
                }
            
            return task_info
        
        @self.app.get("/tasks/{task_id}/error")
        async def get_task_error(task_id: str):
            """Get the last error for a task."""
            error = self.errors.get_task_error(task_id)
            if error is None:
                return self._error_response(404, "NoError", "No error recorded for task")
            
            return error
        
        @self.app.post("/tasks")
        async def execute_task(body: dict):
            """Execute a task with device ownership enforcement."""
            
            # Extract and validate request body
            task_id = body.get("task_id")
            task_type = body.get("task_type")
            params = body.get("params", {})
            
            logger.info(f"[TASK] Execute task request: task_id='{task_id}', task_type='{task_type}'")
            
            if not task_id:
                return self._error_response(
                    400, "InvalidRequest", "task_id is required"
                )
            
            if not task_type:
                return self._error_response(
                    400, "InvalidRequest", "task_type is required"
                )
            
            if not isinstance(params, dict):
                return self._error_response(
                    400, "InvalidRequest", "params must be a dict"
                )
            
            # Check if task already exists
            if task_id in self.daemon._tasks and self.daemon._tasks[task_id].is_running():
                return self._error_response(
                    409,
                    "TaskExists",
                    f"Task '{task_id}' is already running"
                )
            
            # Execute task using server's _execute_task_with_ownership method
            # This handles all validation, ownership claiming, and cleanup
            try:
                handle = self._execute_task_with_ownership(task_id, task_type, **params)
                
                # Extract device_ids from the task instance for response
                device_ids = getattr(handle._task_instance, 'device_ids', [])
                
                logger.info(f"[TASK] Task '{task_id}' started successfully with devices: {device_ids}")
                
                # Double-check that the task is actually running
                if not handle.is_running():
                    # Task might have failed immediately
                    if handle._exception:
                        error_msg = f"Task failed to start: {str(handle._exception)}"
                        logger.error(f"[TASK] Task '{task_id}': {error_msg}")
                        # Record the error
                        self.errors.record_task_error(
                            task_id,
                            handle._exception,
                            origin="framework",
                            context={"task_type": task_type}
                        )
                        return self._error_response(
                            400,
                            type(handle._exception).__name__,
                            error_msg,
                            origin="framework",
                            context={"task_type": task_type}
                        )
                    else:
                        # Task stopped without exception - might have completed immediately
                        logger.warning(f"[TASK] Task '{task_id}' stopped immediately after start")
                        return {
                            "task_id": task_id,
                            "task_type": task_type,
                            "device_ids": device_ids,
                            "status": "completed_immediately"
                        }
                
                return {
                    "task_id": task_id,
                    "task_type": task_type,
                    "device_ids": device_ids,
                    "status": "started"
                }
                
            except ValueError as e:
                # Unknown task type
                error_msg = str(e)
                logger.error(f"[TASK] ValueError for task '{task_id}': {error_msg}")
                if "Unknown task type" in error_msg:
                    return self._error_response(
                        404,
                        "TaskTypeNotFound",
                        error_msg,
                        origin="framework"
                    )
                else:
                    # Task instantiation failed
                    return self._error_response(
                        400,
                        "TaskInstantiationError",
                        error_msg,
                        origin="framework",
                        context={"task_type": task_type}
                    )
            
            except TaskError as e:
                # Ownership conflict or validation error
                error_msg = str(e)
                logger.error(f"[TASK] TaskError for task '{task_id}': {error_msg}")
                if "already owned" in error_msg:
                    return self._error_response(
                        409,
                        "DeviceInUse",
                        error_msg,
                        origin="framework",
                        context={"task_type": task_type}
                    )
                else:
                    # Validation error (e.g., invalid device_ids)
                    return self._error_response(
                        400,
                        "InvalidTaskDefinition",
                        error_msg,
                        origin="framework",
                        context={"task_type": task_type}
                    )
            
            except Exception as e:
                # Unexpected error during task execution
                logger.exception(f"[TASK] Unexpected error for task '{task_id}': {e}")
                # Record error before returning response
                self.errors.record_task_error(
                    task_id,
                    e,
                    origin="framework",
                    context={"task_type": task_type}
                )
                
                return self._error_response(
                    400,
                    "TaskInstantiationError",
                    f"Failed to instantiate task: {str(e)}",
                    origin="framework",
                    context={"task_type": task_type}
                )
        
        @self.app.delete("/tasks/{task_id}/error")
        async def clear_task_error(task_id: str):
            """Clear the last error for a task."""
            # Check if error exists (don't require task to exist in daemon)
            error = self.errors.get_task_error(task_id)
            if error is None:
                return self._error_response(404, "NoError", "No error recorded for task")
            
            self.errors.clear_task_error(task_id)
            return JSONResponse(status_code=204, content=None)
        
        @self.app.post("/tasks/{task_id}/cancel")
        async def cancel_task(task_id: str):
            """Cancel a running task."""
            try:
                handle = self.daemon._tasks[task_id]
            except KeyError:
                return self._error_response(404, "TaskNotFound", "Task not found")
            
            try:
                handle.cancel()
                return {"status": "cancellation_requested"}
            except Exception as e:
                return self._error_response(
                    500,
                    "TaskCancellationError",
                    f"Failed to cancel task '{task_id}': {str(e)}",
                    origin="framework"
                )
        
        @self.app.post("/tasks/{task_id}/pause")
        async def pause_task(task_id: str):
            """Pause a running task."""
            try:
                handle = self.daemon._tasks[task_id]
            except KeyError:
                return self._error_response(404, "TaskNotFound", "Task not found")
            
            try:
                handle.pause()
                return {"status": "paused"}
            except NotImplementedError as e:
                return self._error_response(
                    400,
                    "NotSupported",
                    f"Task '{task_id}' does not support pausing: {str(e)}",
                    origin="framework"
                )
            except Exception as e:
                return self._error_response(
                    500,
                    "TaskPauseError",
                    f"Failed to pause task '{task_id}': {str(e)}",
                    origin="framework"
                )
        
        @self.app.post("/tasks/{task_id}/resume")
        async def resume_task(task_id: str):
            """Resume a paused task."""
            try:
                handle = self.daemon._tasks[task_id]
            except KeyError:
                return self._error_response(404, "TaskNotFound", "Task not found")
            
            try:
                handle.resume()
                return {"status": "resumed"}
            except NotImplementedError as e:
                return self._error_response(
                    400,
                    "NotSupported",
                    f"Task '{task_id}' does not support resuming: {str(e)}",
                    origin="framework"
                )
            except Exception as e:
                return self._error_response(
                    500,
                    "TaskResumeError",
                    f"Failed to resume task '{task_id}': {str(e)}",
                    origin="framework"
                )
        
        @self.app.post("/tasks/{task_id}/parameters")
        async def set_task_parameter(task_id: str, body: dict):
            """Set a parameter on a running task."""
            try:
                handle = self.daemon._tasks[task_id]
            except KeyError:
                return self._error_response(404, "TaskNotFound", "Task not found")

            key = body.get("key")
            if "value" not in body:
                return self._error_response(
                    400, "InvalidRequest", "'value' is required in request body"
                )
            value = body.get("value")

            if not key:
                return self._error_response(
                    400, "InvalidRequest", "'key' is required in request body"
                )

            try:
                handle.set_parameter(key, value)
                return {"status": "parameter_set", "key": key, "value": value}
            except NotImplementedError as e:
                return self._error_response(
                    400,
                    "NotSupported",
                    f"Task '{task_id}' does not support setting parameters: {str(e)}",
                    origin="framework"
                )
            except Exception as e:
                return self._error_response(
                    500,
                    "TaskParameterError",
                    f"Failed to set parameter '{key}' on task '{task_id}': {str(e)}",
                    origin="framework"
                )
        
        @self.app.get("/stream/devices/{device_id}")
        async def stream_device_data(device_id: str):
            """SSE stream for a single device's data."""
            try:
                device = self.daemon.get_device(device_id)
            except ValueError as e:
                return self._error_response(404, "DeviceNotFound", str(e))

            # EventSourceResponse expects dictionaries, not strings
            # The library handles SSE formatting internally
            # We disable automatic ping to avoid encoding issues
            async def sse_generator():
                async for event_obj in self.sse.device_stream(device_id, device):
                    yield event_obj

            # Explicitly set content-type to text/event-stream with charset=utf-8
            response = EventSourceResponse(sse_generator(), ping=None)
            response.headers["Cache-Control"] = "no-cache"
            response.headers["Connection"] = "keep-alive"
            response.headers["X-Accel-Buffering"] = "no"  # Disable nginx buffering
            
            return response
    
    def _get_timestamp(self) -> str:
        """Generate ISO 8601 UTC timestamp without microseconds."""
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
