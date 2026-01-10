"""
Server-specific exceptions for LabDaemon HTTP/SSE API.
"""


class ServerAPIError(Exception):
    """Base exception for server API errors."""
    pass


class ServerConnectionError(ServerAPIError):
    """Failed to connect to server."""
    pass
