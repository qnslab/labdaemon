# GUI Development

LabDaemon provides two distinct patterns for building graphical user interfaces: **local GUIs** that use the daemon directly, and **server client GUIs** that connect to a remote LabDaemon server. This page covers both approaches with practical examples.

## Choosing Your Approach

### Local GUI Pattern
Use when you need:
- Direct hardware control from a desktop application
- Maximum performance and minimal latency
- Single-user, single-machine workflows
- Full control over device lifecycle

### Server Client Pattern  
Use when you need:
- Remote monitoring and control capabilities
- Multi-user coordination (shared monitoring, exclusive control)
- Web-based interfaces
- Separation between hardware control and user interfaces

## Local GUI Pattern

Local GUIs use `LabDaemon` directly within the application process. This provides the best performance but requires the GUI to run on the same machine as the hardware.

### Basic Structure

```python
import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QPushButton
from PyQt5.QtCore import QTimer
import labdaemon as ld
from your_devices import MyLaser

class LocalGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.daemon = None
        self.setup_ui()
        
    def setup_ui(self):
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.toggle_connection)
        self.setCentralWidget(self.connect_btn)
        
    def toggle_connection(self):
        if self.daemon is None:
            # Connect to hardware
            self.daemon = ld.LabDaemon()
            self.daemon.register_plugins(devices={"MyLaser": MyLaser})
            
            laser = self.daemon.add_device("laser1", "MyLaser", address="GPIB0::1")
            self.daemon.connect_device(laser)
            
            self.connect_btn.setText("Disconnect")
        else:
            # Disconnect
            self.daemon.shutdown()
            self.daemon = None
            self.connect_btn.setText("Connect")
    
    def closeEvent(self, event):
        if self.daemon:
            self.daemon.shutdown()
        event.accept()

app = QApplication(sys.argv)
window = LocalGUI()
window.show()
app.exec_()
```

### Threading for Responsiveness

Long-running operations should use background tasks to keep the GUI responsive:

```python
from PyQt5.QtCore import QTimer, pyqtSignal

class ResponsiveGUI(QMainWindow):
    task_finished = pyqtSignal(object)  # Signal for task completion
    
    def __init__(self):
        super().__init__()
        self.daemon = None
        self.current_task = None
        self.task_timer = QTimer()
        self.task_timer.timeout.connect(self.check_task_status)
        self.task_finished.connect(self.on_task_finished)
        
    def run_long_operation(self):
        """Start a long-running task in the background."""
        if not self.daemon:
            return
            
        # Disable UI during operation
        self.run_btn.setEnabled(False)
        
        # Start background task
        self.current_task = self.daemon.execute_task(
            task_id="sweep_1",
            task_type="WavelengthSweepTask",
            start_wl=1550.0,
            stop_wl=1560.0
        )
        
        # Poll for completion
        self.task_timer.start(100)  # Check every 100ms
        
    def check_task_status(self):
        """Check if the background task is complete."""
        if self.current_task and not self.current_task.is_running():
            self.task_timer.stop()
            self.task_finished.emit(self.current_task)
            
    def on_task_finished(self, task_handle):
        """Handle task completion in the GUI thread."""
        try:
            result = task_handle.wait()  # Get results
            self.display_results(result)
        except Exception as e:
            self.show_error(f"Task failed: {e}")
        finally:
            self.current_task = None
            self.run_btn.setEnabled(True)
```

### Real-Time Data Streaming

For live data display, use the streaming API with Qt signals:

```python
from PyQt5.QtCore import pyqtSignal
import numpy as np

class StreamingGUI(QMainWindow):
    data_received = pyqtSignal(object)  # Thread-safe signal
    
    def __init__(self):
        super().__init__()
        self.daemon = None
        self.is_streaming = False
        self.data_received.connect(self.update_plot)
        
    def toggle_streaming(self):
        if not self.is_streaming:
            # Start streaming
            daq = self.daemon.get_device("daq1")
            self.daemon.start_streaming(daq, callback=self.on_data_received)
            self.is_streaming = True
            self.stream_btn.setText("Stop Stream")
        else:
            # Stop streaming
            daq = self.daemon.get_device("daq1")
            self.daemon.stop_streaming(daq)
            self.is_streaming = False
            self.stream_btn.setText("Start Stream")
    
    def on_data_received(self, time_data, voltage_data):
        """Called from streaming thread - emit signal to GUI thread."""
        if voltage_data is not None:
            self.data_received.emit(voltage_data)
    
    def update_plot(self, voltage_data):
        """Update plot in GUI thread - safe for UI operations."""
        # Update your matplotlib plot here
        self.plot_widget.update_data(voltage_data)
```

## Server Client Pattern

Server client GUIs connect to a remote LabDaemon server using HTTP and Server-Sent Events. This enables remote control and multi-user coordination. Here we show a PyQt example, but you can use any language, e.g. write a webapp in javascript.

### Basic Server Client

```python
import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QPushButton, QLineEdit
from PyQt5.QtCore import QTimer
from labdaemon.server.client import ServerAPI, SSEClient

class ServerClientGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.server_api = None
        self.sse_client = None
        self.connected = False
        self.setup_ui()
        
    def setup_ui(self):
        # Server URL input
        self.url_edit = QLineEdit("http://localhost:5000")
        
        # Connection button
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.toggle_connection)
        
        # Add to layout...
        
    def toggle_connection(self):
        if not self.connected:
            try:
                # Connect to server
                server_url = self.url_edit.text()
                self.server_api = ServerAPI(server_url)
                
                # Test connection
                devices = self.server_api.list_devices()
                
                self.connected = True
                self.connect_btn.setText("Disconnect")
                self.url_edit.setEnabled(False)
                
            except Exception as e:
                self.show_error(f"Connection failed: {e}")
        else:
            # Disconnect
            if self.sse_client:
                self.sse_client.stop_stream()
                self.sse_client = None
            if self.server_api:
                self.server_api.close()
                self.server_api = None
            
            self.connected = False
            self.connect_btn.setText("Connect")
            self.url_edit.setEnabled(True)
```

### Device Management

Server clients should ensure required devices exist and manage their connections:

```python
def ensure_devices(self):
    """Ensure required devices exist on the server."""
    required_devices = [
        {"device_id": "laser1", "device_type": "SantecLaser"},
        {"device_id": "daq1", "device_type": "Picoscope"},
    ]
    
    for device_info in required_devices:
        try:
            # Check if device exists
            device = self.server_api.get_device(device_info["device_id"])
        except Exception:
            # Device doesn't exist, add it
            self.server_api.add_device(
                device_info["device_id"],
                device_info["device_type"]
            )

def connect_devices(self):
    """Connect all required devices."""
    device_ids = ["laser1", "daq1"]
    
    for device_id in device_ids:
        try:
            self.server_api.connect_device(device_id)
            self.log(f"Connected {device_id}")
        except Exception as e:
            self.log(f"Failed to connect {device_id}: {e}")
```

### Real-Time Streaming via SSE

Server clients use Server-Sent Events for real-time data:

```python
from PyQt5.QtCore import pyqtSignal

class StreamingServerGUI(QMainWindow):
    data_received = pyqtSignal(object)
    
    def __init__(self):
        super().__init__()
        self.server_api = None
        self.sse_client = None
        self.data_received.connect(self.update_plot)
        
    def start_streaming(self):
        """Start streaming from server."""
        try:
            # Configure device for streaming
            self.server_api.call_device_method(
                "daq1",
                "configure_streaming",
                kwargs={
                    "sample_rate": 100000,
                    "voltage_range": 1.0
                }
            )
            
            # Start SSE stream
            self.sse_client = SSEClient(
                self.server_api.base_url,
                on_event=self.on_sse_event
            )
            self.sse_client.start_device_stream("daq1")
            
        except Exception as e:
            self.show_error(f"Failed to start streaming: {e}")
    
    def on_sse_event(self, event_data):
        """Handle SSE events from server."""
        if event_data.get('event') == 'device_data':
            data = event_data.get('data')
            if isinstance(data, list):
                self.data_received.emit(data)
    
    def update_plot(self, voltage_data):
        """Update plot with new data."""
        # Update your plot here
        pass
```

### Task Execution

Server clients can execute tasks and monitor their progress:

```python
def run_sweep(self):
    """Execute a sweep task on the server."""
    try:
        # Start task
        task_id = f"sweep_{int(time.time())}"
        response = self.server_api.execute_task(
            task_id=task_id,
            task_type="WavelengthSweepTask",
            params={
                "laser_id": "laser1",
                "daq_id": "daq1",
                "start_wl": 1550.0,
                "stop_wl": 1560.0
            }
        )
        
        self.current_task_id = response["task_id"]
        
        # Poll for completion
        self.task_timer = QTimer()
        self.task_timer.timeout.connect(self.check_task_status)
        self.task_timer.start(1000)  # Check every second
        
    except Exception as e:
        self.show_error(f"Failed to start sweep: {e}")

def check_task_status(self):
    """Check if the server task is complete."""
    try:
        task_info = self.server_api.get_task(self.current_task_id)
        
        if not task_info.get('running', False):
            self.task_timer.stop()
            self.on_task_finished(task_info)
            
    except Exception as e:
        self.log(f"Error checking task status: {e}")

def on_task_finished(self, task_info):
    """Handle task completion."""
    if task_info.get('exception'):
        error = task_info['exception']['error']['message']
        self.show_error(f"Task failed: {error}")
    else:
        result = task_info.get('result')
        self.display_results(result)
```

## Best Practices

### Error Handling

Always provide clear feedback to users when operations fail:

```python
def show_error(self, message):
    """Display error message to user."""
    QMessageBox.critical(self, "Error", message)
    self.log(f"Error: {message}")

def log(self, message):
    """Add message to log display."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    self.log_text.append(f"[{timestamp}] {message}")
```

### Settings Persistence

Save user preferences between sessions:

```python
from PyQt5.QtCore import QSettings

class PersistentGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings('YourOrg', 'YourApp')
        self.load_settings()
        
    def load_settings(self):
        """Load saved settings."""
        self.server_url_edit.setText(
            self.settings.value("server_url", "http://localhost:5000")
        )
        self.power_edit.setText(
            self.settings.value("laser_power", "1.0")
        )
        
    def save_settings(self):
        """Save current settings."""
        self.settings.setValue("server_url", self.server_url_edit.text())
        self.settings.setValue("laser_power", self.power_edit.text())
        
    def closeEvent(self, event):
        """Save settings on close."""
        self.save_settings()
        # ... cleanup code ...
        event.accept()
```

### Graceful Shutdown

Always clean up resources properly:

```python
def closeEvent(self, event):
    """Handle application shutdown."""
    # Stop any active operations
    if self.is_streaming:
        self.stop_streaming()
    
    # Stop timers
    if hasattr(self, 'task_timer') and self.task_timer.isActive():
        self.task_timer.stop()
    
    # Clean up connections
    if self.sse_client:
        self.sse_client.stop_stream()
    if self.server_api:
        self.server_api.close()
    if self.daemon:
        self.daemon.shutdown()
    
    # Save settings
    self.save_settings()
    
    event.accept()
```
