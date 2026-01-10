class LabDaemonException(Exception):
    """Base exception for all labdaemon errors."""

    pass


class DeviceError(LabDaemonException):
    """Base exception for device-related errors."""

    pass


class DeviceConnectionError(DeviceError):
    """Raised when a device fails to connect or disconnect."""

    pass


class DeviceNotConnectedError(DeviceError):
    """Raised when an operation is attempted on a disconnected device."""

    pass


class DeviceTimeoutError(DeviceError):
    """Raised when a device operation times out."""

    pass


class DeviceConfigurationError(DeviceError):
    """Raised for errors related to device configuration."""

    pass


class DeviceOperationError(DeviceError):
    """Raised for general errors during device operation."""

    pass


class TaskError(LabDaemonException):
    """Base exception for task-related errors."""

    pass


class TaskCancelledError(TaskError):
    """Raised when a task is cancelled."""

    pass


class TaskFailedError(TaskError):
    """Raised when a task fails during execution."""

    pass
