"""
Server Launcher Pattern for LabDaemon.

Provides a desktop GUI for starting and stopping LabDaemon servers
with different configurations. This is designed for non-technical
users who need to manage servers without using the command line.

The launcher pattern:
- Starts/stops server processes
- Monitors server health via HTTP checks
- Displays live logs from server processes
- Manages multiple server configurations
- Auto-cleanup on exit

This is for single-user desktop workflows only.
"""

import os
import sys
import time
import threading
import subprocess
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QPushButton, QLabel, QTextEdit, QGroupBox,
    QMessageBox, QComboBox, QSpinBox, QCheckBox, QTabWidget,
    QSplitter, QTreeWidget, QTreeWidgetItem, QProgressBar,
    QHeaderView, QMenu, QAction, QFileDialog, QDialog,
    QDialogButtonBox, QLineEdit, QPlainTextEdit
)
from PyQt5.QtCore import QSettings, Qt, QTimer, pyqtSignal, QProcess, QObject, QThread
from PyQt5.QtGui import (
    QFont, QIcon, QPalette, QTextCursor, QPixmap, QSyntaxHighlighter, 
    QTextCharFormat, QTextDocument, QColor
)

from loguru import logger

import requests

# Optional dependencies
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# Compile ANSI escape sequence regex once for performance
ANSI_ESCAPE_REGEX = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')





class PythonSyntaxHighlighter(QSyntaxHighlighter):
    """Basic Python syntax highlighter for the configuration editor."""
    
    def __init__(self, document: QTextDocument):
        super().__init__(document)
        
        # Define syntax rules
        self._highlighting_rules = []
        
        # Python keywords
        keyword_format = QTextCharFormat()
        keyword_format.setForeground(Qt.blue)
        keyword_format.setFontWeight(QFont.Bold)
        
        keywords = [
            'and', 'as', 'assert', 'break', 'class', 'continue', 'def',
            'del', 'elif', 'else', 'except', 'exec', 'finally', 'for',
            'from', 'global', 'if', 'import', 'in', 'is', 'lambda',
            'not', 'or', 'pass', 'print', 'raise', 'return', 'try',
            'while', 'with', 'yield', 'None', 'True', 'False'
        ]
        
        for word in keywords:
            pattern = r'\b' + word + r'\b'
            self._highlighting_rules.append((pattern, keyword_format))
        
        # Strings
        string_format = QTextCharFormat()
        string_format.setForeground(Qt.darkGreen)
        
        self._highlighting_rules.append((r'"[^"\\]*(\\.[^"\\]*)*"', string_format))
        self._highlighting_rules.append((r"'[^'\\]*(\\.[^'\\]*)*'", string_format))
        self._highlighting_rules.append((r'""".*?"""', string_format))
        self._highlighting_rules.append((r"'''.*?'''", string_format))
        
        # Comments
        comment_format = QTextCharFormat()
        comment_format.setForeground(Qt.darkGray)
        comment_format.setFontItalic(True)
        
        self._highlighting_rules.append((r'#.*', comment_format))
        
        # Numbers
        number_format = QTextCharFormat()
        number_format.setForeground(Qt.darkMagenta)
        
        self._highlighting_rules.append((r'\b[0-9]+\b', number_format))
        self._highlighting_rules.append((r'\b0x[0-9a-fA-F]+\b', number_format))
        
        # Function definitions
        function_format = QTextCharFormat()
        function_format.setForeground(Qt.darkBlue)
        function_format.setFontWeight(QFont.Bold)
        
        self._highlighting_rules.append((r'\bdef\s+([a-zA-Z_][a-zA-Z0-9_]*)', function_format))
        
        # Class definitions
        class_format = QTextCharFormat()
        class_format.setForeground(Qt.darkBlue)
        class_format.setFontWeight(QFont.Bold)
        
        self._highlighting_rules.append((r'\bclass\s+([a-zA-Z_][a-zA-Z0-9_]*)', class_format))
    
    def highlightBlock(self, text: str):
        """Apply syntax highlighting to a block of text."""
        for pattern, format in self._highlighting_rules:
            import re
            for match in re.finditer(pattern, text):
                self.setFormat(match.start(), match.end() - match.start(), format)


def find_lab_servers_config(custom_path: Optional[str] = None) -> Optional[Path]:
    """
    Find lab_servers.py using a flexible search strategy.
    
    Parameters
    ----------
    custom_path : Optional[str], default None
        Custom path provided by user (CLI argument or file dialog)
    
    Returns
    -------
    Optional[Path]
        Path to lab_servers.py if found, None otherwise
    """
    search_paths = []
    
    # 1. Custom path (highest priority)
    if custom_path:
        search_paths.append(Path(custom_path))
    
    # 2. Environment variable
    env_path = os.environ.get("LABDAEMON_CONFIG")
    if env_path:
        search_paths.append(Path(env_path))
    
    # 3. Current working directory
    search_paths.append(Path.cwd() / "lab_servers.py")
    
    # 4. User's home directory
    search_paths.append(Path.home() / ".labdaemon" / "lab_servers.py")
    
    # 5. Repository root (fallback for development)
    # Find the repository root by looking for pyproject.toml
    current = Path(__file__).resolve()
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            search_paths.append(current / "lab_servers.py")
            break
        current = current.parent
    
    for path in search_paths:
        if path.exists() and path.is_file():
            logger.debug(f"Found lab_servers.py at: {path}")
            return path
    
    logger.debug("lab_servers.py not found in any search location")
    return None


class LogViewerWidget(QPlainTextEdit):
    """A simple widget for viewing live logs."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(1000)  # Qt handles memory management
        self.setFont(QFont("Consolas", 9))
    
    def append_log(self, text: str, level: str = 'INFO'):
        """Append a log line."""
        self.appendPlainText(f"[{level}] {text}")


class ServerProcess(QObject):
    """Manages a single LabDaemon server process."""
    
    # Signals
    started = pyqtSignal(str)  # server_name
    stopped = pyqtSignal(str)  # server_name
    error = pyqtSignal(str, str)  # server_name, error_message
    output = pyqtSignal(str, str)  # server_name, line
    health_changed = pyqtSignal(str, bool)  # server_name, is_healthy
    
    def __init__(self, server_name: str, config: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.server_name = server_name
        self.config = config
        self.process: Optional[QProcess] = None
        self.is_healthy = False
        self.health_check_timer = QTimer()
        self.health_check_timer.timeout.connect(self._check_health)
        self.health_check_timer.setInterval(2000)  # Check every 2 seconds
        
    def start(self) -> bool:
        """Start the server process."""
        if self.process and self.process.state() == QProcess.Running:
            return True
        
        try:
            script_path = Path(self.config['script'])
            if not script_path.exists():
                self.error.emit(self.server_name, f"Script not found: {script_path}")
                return False
            
            # Build command
            # Use -u flag for unbuffered output to ensure live log updates
            cmd = [sys.executable, "-u", str(script_path)]
            cmd.extend(self.config.get('args', []))
            
            # Create process
            self.process = QProcess()
            self.process.setWorkingDirectory(str(script_path.parent))
            
            # Connect signals
            self.process.readyReadStandardOutput.connect(self._read_output)
            self.process.readyReadStandardError.connect(self._read_error)
            self.process.finished.connect(self._on_finished)
            
            # Start process
            logger.info(f"Starting server '{self.server_name}': {' '.join(cmd)}")
            self.process.start(cmd[0], cmd[1:])
            
            if self.process.waitForStarted(3000):
                self.started.emit(self.server_name)
                # Start health checks after a short delay
                QTimer.singleShot(3000, self.health_check_timer.start)
                return True
            else:
                error = self.process.errorString()
                self.error.emit(self.server_name, f"Failed to start: {error}")
                self.process = None
                return False
                
        except Exception as e:
            self.error.emit(self.server_name, f"Exception: {str(e)}")
            return False
    
    def stop(self) -> bool:
        """Stop the server process."""
        if not self.process or self.process.state() != QProcess.Running:
            return True
        
        try:
            logger.info(f"Stopping server '{self.server_name}'")
            self.process.terminate()
            
            if self.process.waitForFinished(3000):
                self.stopped.emit(self.server_name)
            else:
                logger.warning(f"Server '{self.server_name}' did not stop gracefully, killing...")
                self.process.kill()
                self.process.waitForFinished(1000)
                self.stopped.emit(self.server_name)
            
            self.health_check_timer.stop()
            self.process = None
            self.is_healthy = False
            return True
            
        except Exception as e:
            self.error.emit(self.server_name, f"Exception: {str(e)}")
            return False
    
    def _read_output(self):
        """Read standard output from the process."""
        if self.process:
            data = self.process.readAllStandardOutput().data().decode('utf-8', errors='replace')
            for line in data.strip().split('\n'):
                if line:
                    self.output.emit(self.server_name, line)
    
    def _read_error(self):
        """Read standard error from the process."""
        if self.process:
            data = self.process.readAllStandardError().data().decode('utf-8', errors='replace')
            for line in data.strip().split('\n'):
                if line:
                    self.output.emit(self.server_name, line)
    
    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus):
        """Handle process completion."""
        self.health_check_timer.stop()
        self.process = None
        self.is_healthy = False
        if exit_code != 0:
            self.error.emit(self.server_name, f"Process exited with code {exit_code}")
        self.stopped.emit(self.server_name)
    
    def _update_health_status(self, new_status: bool, reason: str = ""):
        """Update health status and emit signal if changed."""
        was_healthy = self.is_healthy
        self.is_healthy = new_status
        
        if self.is_healthy != was_healthy:
            self.health_changed.emit(self.server_name, self.is_healthy)
            if self.is_healthy:
                logger.debug(f"Server '{self.server_name}' health check passed")
            else:
                logger.debug(f"Server '{self.server_name}' health check failed: {reason}")
    
    def _check_health(self):
        """Check server health via HTTP."""
        if not self.process or self.process.state() != QProcess.Running:
            self._update_health_status(False, "process not running")
            return
        
        try:
            port = self.config.get('port', 5000)
            url = f"http://localhost:{port}/health"
            
            response = requests.get(url, timeout=1.0)
            self._update_health_status(response.status_code == 200, f"HTTP {response.status_code}")
                
        except requests.ConnectionError:
            self._update_health_status(False, "connection refused")
        except requests.Timeout:
            self._update_health_status(False, "timeout")
        except Exception as e:
            self._update_health_status(False, str(e))


class ServerLauncherWindow(QMainWindow):
    """Main window for the LabDaemon Server Launcher."""
    
    def __init__(self):
        super().__init__()
        self.settings = QSettings('LabDaemon', 'ServerLauncher')
        self.server_processes: Dict[str, ServerProcess] = {}
        
        self.setWindowTitle("LabDaemon Server Launcher")
        self.setGeometry(100, 100, 1200, 800)
        
        # Try to set window icon
        icon_path = Path(__file__).parent.parent.parent.parent.parent / "assets" / "icons" / "app.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        
        self.setup_ui()
        self.load_configurations()
        self.load_settings()
        
        # Check for orphaned processes on startup
        self._check_orphaned_processes()
        
        # Setup health check timer
        self.health_timer = QTimer()
        self.health_timer.timeout.connect(self._update_all_health)
        self.health_timer.start(1000)  # Update every second
        
    def setup_ui(self):
        """Set up the user interface."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout - vertical
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)
        
        # Top splitter for server config and details
        top_splitter = QSplitter(Qt.Horizontal)
        
        # Left side - Server configuration group
        config_group = QGroupBox("Server Configurations")
        config_layout = QVBoxLayout()
        
        # Server tree
        self.server_tree = QTreeWidget()
        self.server_tree.setHeaderLabels(["Server", "Status", "Port", "URL"])
        self.server_tree.itemSelectionChanged.connect(self._on_server_selected)
        self.server_tree.itemDoubleClicked.connect(self._toggle_server)
        self.server_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.server_tree.customContextMenuRequested.connect(self._show_context_menu)
        
        # Configure columns
        header = self.server_tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        
        config_layout.addWidget(self.server_tree)
        
        # Control buttons
        button_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self._start_selected_server)
        self.start_btn.setEnabled(False)
        
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self._stop_selected_server)
        self.stop_btn.setEnabled(False)
        
        self.stop_all_btn = QPushButton("Stop All")
        self.stop_all_btn.clicked.connect(self._stop_all_servers)
        
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._refresh_configurations)
        
        button_layout.addWidget(self.start_btn)
        button_layout.addWidget(self.stop_btn)
        button_layout.addWidget(self.stop_all_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.refresh_btn)
        
        config_layout.addLayout(button_layout)
        
        # Status bar for config group
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("QLabel { color: #666; }")
        config_layout.addWidget(self.status_label)
        
        config_group.setLayout(config_layout)
        top_splitter.addWidget(config_group) # Add to splitter
        
        # Right side - Server details group
        details_group = QGroupBox("Server Details")
        details_layout = QFormLayout()
        details_layout.setSpacing(5)
        details_layout.setContentsMargins(10, 10, 10, 10)
        
        self.details_name = QLabel("-")
        self.details_script = QLabel("-")
        self.details_script.setWordWrap(True) # Enable word wrap for long paths
        self.details_port = QLabel("-")
        self.details_url = QLabel("-")
        self.details_status = QLabel("-")
        
        details_layout.addRow("Name:", self.details_name)
        details_layout.addRow("Script:", self.details_script)
        details_layout.addRow("Port:", self.details_port)
        details_layout.addRow("URL:", self.details_url)
        details_layout.addRow("Status:", self.details_status)
        
        details_group.setLayout(details_layout)
        top_splitter.addWidget(details_group) # Add to splitter
        
        # Set initial sizes for the splitter (e.g., 1:1 ratio)
        top_splitter.setSizes([self.width() // 2, self.width() // 2])
        
        # Set maximum height for top panel to ensure logs get most space
        top_splitter.setMaximumHeight(150)
        main_layout.addWidget(top_splitter) # Add splitter to main layout
        
        # Bottom panel - logs only
        logs_group = QGroupBox("Server Logs")
        logs_layout = QVBoxLayout()
        
        # Log controls
        log_controls = QHBoxLayout()
        
        self.clear_logs_btn = QPushButton("Clear")
        self.clear_logs_btn.clicked.connect(self._clear_logs)
        
        self.save_logs_btn = QPushButton("Save...")
        self.save_logs_btn.clicked.connect(self._save_logs)
        
        self.auto_scroll_check = QCheckBox("Auto-scroll")
        self.auto_scroll_check.setChecked(True)
        
        log_controls.addWidget(self.clear_logs_btn)
        log_controls.addWidget(self.save_logs_btn)
        
        
        log_controls.addStretch()
        log_controls.addWidget(self.auto_scroll_check)
        
        logs_layout.addLayout(log_controls)
        
        # Log viewer - now gets much more space
        self.log_viewer = LogViewerWidget()
        logs_layout.addWidget(self.log_viewer)
        
        logs_group.setLayout(logs_layout)
        main_layout.addWidget(logs_group)
        
        # Create menu bar
        self.create_menu_bar()
        
        # Store current configuration path
        self.current_config_path = find_lab_servers_config()
        self._update_config_status()
        
    def create_menu_bar(self):
        """Create the menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu('File')
        
        open_config_action = QAction('Open Configuration...', self)
        open_config_action.setShortcut('Ctrl+O')
        open_config_action.triggered.connect(self._open_configuration)
        file_menu.addAction(open_config_action)
        
        edit_config_action = QAction('Edit Configuration...', self)
        edit_config_action.setShortcut('Ctrl+E')
        edit_config_action.triggered.connect(self._edit_configuration)
        file_menu.addAction(edit_config_action)
        
        reload_config_action = QAction('Reload Configuration', self)
        reload_config_action.setShortcut('F5')
        reload_config_action.triggered.connect(self._refresh_configurations)
        file_menu.addAction(reload_config_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction('Exit', self)
        exit_action.setShortcut('Ctrl+Q')
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Servers menu
        servers_menu = menubar.addMenu('Servers')
        
        stop_all_action = QAction('Stop All', self)
        stop_all_action.triggered.connect(self._stop_all_servers)
        servers_menu.addAction(stop_all_action)
        
        # Help menu
        help_menu = menubar.addMenu('Help')
        
        about_action = QAction('About', self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
    
    def load_configurations(self, custom_path: Optional[str] = None):
        """Load server configurations from lab_servers.py."""
        self.server_tree.clear()
        self.server_processes.clear()
        
        # Find the configuration file
        lab_servers_path = find_lab_servers_config(custom_path)
        
        if not lab_servers_path:
            self.log_viewer.append_log("lab_servers.py not found in any search location", "ERROR")
            self.log_viewer.append_log("Check: current directory, ~/.labdaemon/, or set LABDAEMON_CONFIG", "ERROR")
            self._add_default_config()
            return
        
        try:
            # Load the module
            import importlib.util
            spec = importlib.util.spec_from_file_location("lab_servers", lab_servers_path)
            lab_servers = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(lab_servers)
            
            # Get configurations
            configs = getattr(lab_servers, 'CONFIGS', {})
            
            # Validate configurations
            valid_configs = {}
            for name, config in configs.items():
                if self._validate_config(name, config, lab_servers):
                    valid_configs[name] = config
                    self._add_server_config(name, config)
            
            if valid_configs:
                self.log_viewer.append_log(f"Loaded {len(valid_configs)} valid server configurations from {lab_servers_path}", "INFO")
                if len(valid_configs) < len(configs):
                    self.log_viewer.append_log(f"Skipped {len(configs) - len(valid_configs)} invalid configurations", "WARNING")
            else:
                self.log_viewer.append_log("No valid configurations found", "ERROR")
                
        except Exception as e:
            self.log_viewer.append_log(f"Error loading configurations from {lab_servers_path}: {e}", "ERROR")
            self._add_default_config()
    
    def _check_orphaned_processes(self):
        """Check for orphaned LabDaemon server processes and offer cleanup."""
        if not HAS_PSUTIL:
            logger.debug("psutil not available, skipping orphaned process detection")
            return
            
        try:
            orphaned_processes = []
            
            # Look for Python processes running LabDaemon server scripts
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if proc.info['name'] and 'python' in proc.info['name'].lower():
                        cmdline = proc.info['cmdline']
                        if cmdline and any('run_' in arg and 'server.py' in arg for arg in cmdline):
                            # Check if it's responding to HTTP requests
                            for arg in cmdline:
                                if '--port' in cmdline:
                                    port_idx = cmdline.index('--port')
                                    if port_idx + 1 < len(cmdline):
                                        try:
                                            port = int(cmdline[port_idx + 1])
                                            url = f"http://localhost:{port}/health"
                                            response = requests.get(url, timeout=1.0)
                                            if response.status_code == 200:
                                                orphaned_processes.append((proc.info['pid'], port, ' '.join(cmdline)))
                                        except (ValueError, Exception):
                                            pass
                                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            if orphaned_processes:
                self._offer_cleanup_orphaned_processes(orphaned_processes)
                
        except Exception as e:
            logger.debug(f"Error checking for orphaned processes: {e}")
    
    def _offer_cleanup_orphaned_processes(self, processes):
        """Offer to clean up orphaned processes."""
        process_list = "\n".join([f"PID {pid} on port {port}" for pid, port, _ in processes])
        
        reply = QMessageBox.question(
            self,
            "Orphaned Processes Detected",
            f"Found {len(processes)} running LabDaemon server process(es):\n\n{process_list}\n\n"
            "These may be left over from previous sessions. Stop them?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            stopped_count = 0
            for pid, port, cmdline in processes:
                try:
                    proc = psutil.Process(pid)
                    proc.terminate()
                    proc.wait(timeout=3)
                    stopped_count += 1
                    self.log_viewer.append_log(f"Stopped orphaned process PID {pid} (port {port})", "INFO")
                except Exception as e:
                    self.log_viewer.append_log(f"Failed to stop process PID {pid}: {e}", "WARNING")
            
            if stopped_count > 0:
                self.log_viewer.append_log(f"Cleaned up {stopped_count} orphaned process(es)", "INFO")
    
    def _validate_config(self, name: str, config: Dict[str, Any], lab_servers_module) -> bool:
        """Validate a server configuration."""
        required_fields = ['name', 'port', 'script']
        
        # Check required fields
        for field in required_fields:
            if field not in config:
                self.log_viewer.append_log(f"Configuration '{name}' missing required field: {field}", "ERROR")
                return False
        
        # Check script exists
        script_path = Path(config['script'])
        if not script_path.exists():
            self.log_viewer.append_log(f"Configuration '{name}' script not found: {script_path}", "ERROR")
            return False
        
        # Check if setup function exists (if it follows the naming convention)
        setup_function_name = f"setup_{name}_server"
        if hasattr(lab_servers_module, setup_function_name):
            self.log_viewer.append_log(f"Configuration '{name}' has setup function: {setup_function_name}", "DEBUG")
        else:
            # This is just a warning, not an error - scripts might handle setup differently
            self.log_viewer.append_log(f"Configuration '{name}' has no setup function: {setup_function_name}", "DEBUG")
        
        # Validate port number
        try:
            port = int(config['port'])
            if not (1 <= port <= 65535):
                self.log_viewer.append_log(f"Configuration '{name}' invalid port: {port}", "ERROR")
                return False
        except (ValueError, TypeError):
            self.log_viewer.append_log(f"Configuration '{name}' port must be a number", "ERROR")
            return False
        
        return True

    def _add_default_config(self):
        """Add a default configuration for testing."""
        # Try to find an existing mock server script
        possible_scripts = [
            Path(__file__).parent.parent.parent.parent.parent / "scripts" / "run_mock_server.py",
            Path(__file__).parent.parent.parent.parent.parent / "scripts" / "run_spectrum_server_mock.py",
        ]
        
        script_path = None
        for script in possible_scripts:
            if script.exists():
                script_path = str(script)
                break
        
        if not script_path:
            # Create a minimal inline script path that we know exists
            script_path = str(Path(__file__).parent.parent.parent.parent.parent / "scripts" / "run_mock_server.py")
        
        default_config = {
            "name": "Mock Server (Default)",
            "port": 5000,
            "script": script_path,
            "args": ["--port", "5000"]
        }
        self._add_server_config("mock", default_config)
        
        if Path(script_path).exists():
            self.log_viewer.append_log("Using default mock configuration", "WARNING")
        else:
            self.log_viewer.append_log(f"Default script not found: {script_path}", "ERROR")
            self.log_viewer.append_log("Please create a lab_servers.py configuration file", "ERROR")
    
    def _add_server_config(self, name: str, config: Dict[str, Any]):
        """Add a server configuration to the tree."""
        item = QTreeWidgetItem(self.server_tree)
        item.setText(0, config.get('name', name))
        item.setText(1, "Stopped")
        item.setText(2, str(config.get('port', '?')))
        item.setText(3, f"http://localhost:{config.get('port', '?')}")
        item.setData(0, Qt.UserRole, name)  # Store server name
        
        # Color code based on type
        if 'mock' in name.lower():
            item.setIcon(0, self._get_color_icon('#8f8'))  # Green for mock
        else:
            item.setIcon(0, self._get_color_icon('#88f'))  # Blue for real
    
    def _get_color_icon(self, color: str) -> QIcon:
        """Create a simple color icon."""
        pixmap = QPixmap(16, 16)
        pixmap.fill(QColor(color))
        return QIcon(pixmap)
    
    def _on_server_selected(self):
        """Handle server selection in the tree."""
        items = self.server_tree.selectedItems()
        if not items:
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self._clear_details()
            return
        
        item = items[0]
        server_name = item.data(0, Qt.UserRole)
        
        # Update button states
        process = self.server_processes.get(server_name)
        if process and process.process and process.process.state() == QProcess.Running:
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
        else:
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
        
        # Update details
        if self.current_config_path:
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location("lab_servers", self.current_config_path)
                lab_servers = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(lab_servers)
                configs = getattr(lab_servers, 'CONFIGS', {})
                config = configs.get(server_name, {})
                
                self.details_name.setText(config.get('name', server_name))
                self.details_script.setText(config.get('script', '-'))
                self.details_port.setText(str(config.get('port', '-')))
                self.details_url.setText(f"http://localhost:{config.get('port', '?')}")
                
                process = self.server_processes.get(server_name)
                if process and process.is_healthy:
                    self.details_status.setText('<font color="green">● Healthy</font>')
                elif process and process.process and process.process.state() == QProcess.Running:
                    self.details_status.setText('<font color="orange">● Starting</font>')
                else:
                    self.details_status.setText('<font color="red">● Stopped</font>')
            except Exception as e:
                logger.exception(f"Error updating details: {e}")
    
    def _clear_details(self):
        """Clear the details panel."""
        self.details_name.setText("-")
        self.details_script.setText("-")
        self.details_port.setText("-")
        self.details_url.setText("-")
        self.details_status.setText("-")
    
    def _toggle_server(self, item: QTreeWidgetItem, column: int):
        """Toggle server start/stop on double-click."""
        server_name = item.data(0, Qt.UserRole)
        process = self.server_processes.get(server_name)
        
        if process and process.process and process.process.state() == QProcess.Running:
            self._stop_server(server_name)
        else:
            self._start_server(server_name)
    
    def _start_selected_server(self):
        """Start the selected server."""
        items = self.server_tree.selectedItems()
        if items:
            server_name = items[0].data(0, Qt.UserRole)
            self._start_server(server_name)
    
    def _stop_selected_server(self):
        """Stop the selected server."""
        items = self.server_tree.selectedItems()
        if items:
            server_name = items[0].data(0, Qt.UserRole)
            self._stop_server(server_name)
    
    def _start_server(self, server_name: str):
        """Start a server."""
        try:
            # Get configuration from current loaded path
            if not self.current_config_path:
                self.log_viewer.append_log("No configuration file loaded", "ERROR")
                return
            
            import importlib.util
            spec = importlib.util.spec_from_file_location("lab_servers", self.current_config_path)
            lab_servers = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(lab_servers)
            configs = getattr(lab_servers, 'CONFIGS', {})
            config = configs.get(server_name)
            
            if not config:
                self.log_viewer.append_log(f"Configuration not found: {server_name}", "ERROR")
                return
            
            # Create and start process
            process = ServerProcess(server_name, config, self)
            process.started.connect(self._on_server_started)
            process.stopped.connect(self._on_server_stopped)
            process.error.connect(self._on_server_error)
            process.output.connect(self._on_server_output)
            process.health_changed.connect(self._on_server_health_changed)
            
            self.server_processes[server_name] = process
            
            if process.start():
                self.log_viewer.append_log(f"Starting server: {server_name}", "INFO")
            else:
                self.server_processes.pop(server_name, None)
                
        except Exception as e:
            self.log_viewer.append_log(f"Error starting server: {e}", "ERROR")
            logger.exception("Error starting server")
    
    def _stop_server(self, server_name: str):
        """Stop a server."""
        process = self.server_processes.get(server_name)
        if process:
            if process.stop():
                self.log_viewer.append_log(f"Stopping server: {server_name}", "INFO")
            # Remove from processes after it actually stops
            # The _on_server_stopped handler will clean up
    
    def _stop_all_servers(self):
        """Stop all servers."""
        for server_name in list(self.server_processes.keys()):
            self._stop_server(server_name)
    
    def _refresh_configurations(self):
        """Reload configurations from lab_servers.py."""
        # Stop all servers first
        reply = QMessageBox.question(
            self,
            "Refresh Configurations",
            "This will stop all running servers. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self._stop_all_servers()
            time.sleep(1)  # Give servers time to stop
            self.load_configurations()
            self.log_viewer.append_log("Configurations refreshed", "INFO")
    
    def _update_all_health(self):
        """Update health status for all servers."""
        for i in range(self.server_tree.topLevelItemCount()):
            item = self.server_tree.topLevelItem(i)
            server_name = item.data(0, Qt.UserRole)
            process = self.server_processes.get(server_name)
            
            if process and process.process and process.process.state() == QProcess.Running:
                if process.is_healthy:
                    item.setText(1, "● Running")
                    item.setIcon(0, self._get_color_icon('#8f8'))
                else:
                    item.setText(1, "● Starting")
                    item.setIcon(0, self._get_color_icon('#ff8'))
        
        # Also update the details panel if a server is selected
        items = self.server_tree.selectedItems()
        if items:
            self._on_server_selected()
    
    def _show_context_menu(self, position):
        """Show context menu for server tree."""
        item = self.server_tree.itemAt(position)
        if not item:
            return
        
        server_name = item.data(0, Qt.UserRole)
        process = self.server_processes.get(server_name)
        
        menu = QMenu(self)
        
        if process and process.process and process.process.state() == QProcess.Running:
            stop_action = QAction("Stop", self)
            stop_action.triggered.connect(lambda: self._stop_server(server_name))
            menu.addAction(stop_action)
        else:
            start_action = QAction("Start", self)
            start_action.triggered.connect(lambda: self._start_server(server_name))
            menu.addAction(start_action)
        
        menu.addSeparator()
        
        open_url_action = QAction("Open in Browser", self)
        open_url_action.triggered.connect(lambda: self._open_server_url(server_name))
        menu.addAction(open_url_action)
        
        menu.exec_(self.server_tree.mapToGlobal(position))
    
    def _open_server_url(self, server_name: str):
        """Open server URL in browser."""
        try:
            if not self.current_config_path:
                self.log_viewer.append_log("No configuration file loaded", "ERROR")
                return
            
            import importlib.util
            spec = importlib.util.spec_from_file_location("lab_servers", self.current_config_path)
            lab_servers = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(lab_servers)
            configs = getattr(lab_servers, 'CONFIGS', {})
            config = configs.get(server_name)
            
            if config:
                import webbrowser
                url = f"http://localhost:{config.get('port', 5000)}"
                webbrowser.open(url)
                self.log_viewer.append_log(f"Opened {url} in browser", "INFO")
        except Exception as e:
            self.log_viewer.append_log(f"Error opening URL: {e}", "ERROR")
    
    def _on_server_started(self, server_name: str):
        """Handle server started signal."""
        self.log_viewer.append_log(f"Server '{server_name}' started", "INFO")
        self._update_server_item(server_name, "Starting")
    
    def _on_server_stopped(self, server_name: str):
        """Handle server stopped signal."""
        self.log_viewer.append_log(f"Server '{server_name}' stopped", "INFO")
        self._update_server_item(server_name, "Stopped")
        # Clean up process
        self.server_processes.pop(server_name, None)
    
    def _on_server_error(self, server_name: str, error_message: str):
        """Handle server error signal."""
        self.log_viewer.append_log(f"Error '{server_name}': {error_message}", "ERROR")
    
    def _on_server_output(self, server_name: str, line: str):
        """Handle server output signal."""
        # Strip ANSI escape codes from the line
        clean_line = ANSI_ESCAPE_REGEX.sub('', line)
        
        # Try to extract log level from line
        level = 'INFO'
        line_upper = clean_line.upper()
        if 'DEBUG' in line_upper and ('|' in line_upper or '[' in line_upper):
            level = 'DEBUG'
        elif 'WARNING' in line_upper and ('|' in line_upper or '[' in line_upper):
            level = 'WARNING'
        elif 'ERROR' in line_upper and ('|' in line_upper or '[' in line_upper):
            level = 'ERROR'
        elif 'CRITICAL' in line_upper and ('|' in line_upper or '[' in line_upper):
            level = 'CRITICAL'
        
        # Add timestamp and server name
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_line = f"[{timestamp}] [{server_name}] {clean_line}"
        
        # Add to log viewer
        self.log_viewer.append_log(formatted_line, level)
        
        # Auto-scroll if enabled
        if self.auto_scroll_check.isChecked():
            self.log_viewer.ensureCursorVisible()
    
    
    def _on_server_health_changed(self, server_name: str, is_healthy: bool):
        """Handle server health change."""
        self._update_server_item(server_name, "Running" if is_healthy else "Starting")
    
    def _update_server_item(self, server_name: str, status: str):
        """Update server item in tree."""
        for i in range(self.server_tree.topLevelItemCount()):
            item = self.server_tree.topLevelItem(i)
            if item.data(0, Qt.UserRole) == server_name:
                item.setText(1, f"● {status}")
                
                # Update button states if this is selected
                if self.server_tree.selectedItems() and self.server_tree.selectedItems()[0] == item:
                    if status == "Running":
                        self.start_btn.setEnabled(False)
                        self.stop_btn.setEnabled(True)
                    else:
                        self.start_btn.setEnabled(True)
                        self.stop_btn.setEnabled(False)
                break
    
    def _clear_logs(self):
        """Clear the log viewer."""
        self.log_viewer.clear()
    
    def _save_logs(self):
        """Save logs to a file."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Logs",
            f"server_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            "Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(self.log_viewer.toPlainText())
                
                self.log_viewer.append_log(f"Logs saved to {file_path}", "INFO")
            except Exception as e:
                self.log_viewer.append_log(f"Error saving logs: {e}", "ERROR")
    
    
    def _show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About LabDaemon Server Launcher",
            "LabDaemon Server Launcher\n\n"
            "A desktop GUI for managing LabDaemon servers.\n\n"
            "Part of the LabDaemon framework."
        )

    def _update_config_status(self):
        """Update the status bar with current configuration path."""
        if self.current_config_path:
            # Show relative path if it's in the current directory
            try:
                rel_path = self.current_config_path.relative_to(Path.cwd())
                config_text = f"Config: {rel_path}"
            except ValueError:
                config_text = f"Config: {self.current_config_path}"
            self.status_label.setText(config_text)
            self.status_label.setStyleSheet("QLabel { color: #333; }")
        else:
            self.status_label.setText("No configuration file found")
            self.status_label.setStyleSheet("QLabel { color: #d00; }")
    
    def _open_configuration(self):
        """Open a file dialog to select a configuration file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Configuration File",
            str(Path.cwd()),
            "Python Files (*.py);;All Files (*)"
        )
        
        if file_path:
            # Validate it looks like a lab_servers.py file
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if 'CONFIGS' not in content:
                        QMessageBox.warning(
                            self,
                            "Invalid Configuration",
                            "Selected file doesn't appear to contain server configurations.\n"
                            "Expected to find a CONFIGS dictionary."
                        )
                        return
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Could not read configuration file:\n{e}"
                )
                return
            
            # Load the new configuration
            self.current_config_path = Path(file_path)
            self._update_config_status()
            
            # Stop all servers before reloading
            reply = QMessageBox.question(
                self,
                "Load Configuration",
                "This will stop all running servers. Continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                self._stop_all_servers()
                time.sleep(1)  # Give servers time to stop
                self.load_configurations(str(self.current_config_path))
                self.log_viewer.append_log(f"Loaded custom configuration from {file_path}", "INFO")
    
    def _edit_configuration(self):
        """Open the configuration editor dialog."""
        dialog = ConfigurationEditorDialog(self, self.current_config_path)
        result = dialog.exec_()
        
        if result == QDialog.Accepted:
            # Configuration was saved, reload it
            self.load_configurations()
            self.log_viewer.append_log("Configuration reloaded after edit", "INFO")
    
    def load_settings(self):
        """Load settings."""
        self.restoreGeometry(self.settings.value('geometry', b''))
        self.restoreState(self.settings.value('windowState', b''))
    
    def save_settings(self):
        """Save settings."""
        self.settings.setValue('geometry', self.saveGeometry())
        self.settings.setValue('windowState', self.saveState())
    
    def closeEvent(self, event):
        """Handle window close event."""
        # Stop all servers
        self._stop_all_servers()
        
        # Wait a moment for servers to stop
        time.sleep(1)
        
        # Save settings
        self.save_settings()
        
        event.accept()


class ConfigurationEditorDialog(QDialog):
    """A dialog for editing lab_servers.py configuration files."""
    
    def __init__(self, parent=None, file_path: Optional[Path] = None):
        super().__init__(parent)
        self.file_path = file_path
        self.original_content = ""
        self.setWindowTitle("Configuration Editor")
        self.setGeometry(200, 200, 800, 600)
        
        self.setup_ui()
        
        if file_path and file_path.exists():
            self.load_file()
        
    def setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout()
        
        # File path label
        self.path_label = QLabel(str(self.file_path) if self.file_path else "New configuration")
        self.path_label.setStyleSheet("QLabel { font-style: italic; color: #666; }")
        layout.addWidget(self.path_label)
        
        # Text editor with syntax highlighting
        self.editor = QPlainTextEdit()
        self.editor.setFont(QFont("Consolas", 10))
        
        # Apply syntax highlighting
        if self.editor.document():
            self.highlighter = PythonSyntaxHighlighter(self.editor.document())
        
        layout.addWidget(self.editor)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.validate_btn = QPushButton("Validate")
        self.validate_btn.clicked.connect(self.validate_syntax)
        button_layout.addWidget(self.validate_btn)
        
        button_layout.addStretch()
        
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.save_file)
        self.save_btn.setDefault(True)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        
        button_layout.addWidget(self.save_btn)
        button_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
        
        # Status label for validation results
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("QLabel { color: #666; }")
        layout.addWidget(self.status_label)
    
    def load_file(self):
        """Load the configuration file into the editor."""
        if not self.file_path or not self.file_path.exists():
            return
        
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                self.original_content = f.read()
                self.editor.setPlainText(self.original_content)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load file:\n{e}")
    
    def save_file(self):
        """Save the configuration file."""
        if not self.file_path:
            # Ask user for file path
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Configuration",
                "lab_servers.py",
                "Python Files (*.py);;All Files (*)"
            )
            if not file_path:
                return
            self.file_path = Path(file_path)
            self.path_label.setText(str(self.file_path))
        
        # Validate before saving
        if not self.validate_syntax(silent=True):
            reply = QMessageBox.question(
                self,
                "Syntax Error",
                "The file contains syntax errors. Save anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.No:
                return
        
        try:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                f.write(self.editor.toPlainText())
            
            self.original_content = self.editor.toPlainText()
            QMessageBox.information(self, "Success", "Configuration saved successfully!")
            self.accept()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save file:\n{e}")
    
    def validate_syntax(self, silent: bool = False) -> bool:
        """Validate the Python syntax of the configuration."""
        content = self.editor.toPlainText()
        
        # Try to compile the code
        try:
            compile(content, str(self.file_path or "lab_servers.py"), 'exec')
            
            if not silent:
                self.status_label.setText("✓ Syntax is valid")
                self.status_label.setStyleSheet("QLabel { color: #080; }")
                QMessageBox.information(self, "Validation", "Syntax is valid!")
            
            return True
            
        except SyntaxError as e:
            if not silent:
                self.status_label.setText(f"✗ Syntax error: {e}")
                self.status_label.setStyleSheet("QLabel { color: #d00; }")
                QMessageBox.critical(self, "Syntax Error", f"Line {e.lineno}: {e.msg}")
            
            return False
        except Exception as e:
            if not silent:
                self.status_label.setText(f"✗ Error: {e}")
                self.status_label.setStyleSheet("QLabel { color: #d00; }")
                QMessageBox.critical(self, "Error", f"Failed to validate: {e}")
            
            return False
    
    def has_changes(self) -> bool:
        """Check if the content has been modified."""
        return self.editor.toPlainText() != self.original_content
    
    def closeEvent(self, event):
        """Handle close event with unsaved changes check."""
        if self.has_changes():
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved changes. Save before closing?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Cancel
            )
            
            if reply == QMessageBox.Yes:
                self.save_file()
                if self.has_changes():  # Save was cancelled
                    event.ignore()
                    return
            elif reply == QMessageBox.Cancel:
                event.ignore()
                return
        
        event.accept()


def main():
    """Main entry point for the server launcher."""
    app = QApplication(sys.argv)
    app.setApplicationName("LabDaemon Server Launcher")
    app.setOrganizationName("LabDaemon")
    
    window = ServerLauncherWindow()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
