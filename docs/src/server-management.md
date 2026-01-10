# Server Management

The LabDaemon server launcher provides a GUI for starting and managing different server configurations. Instead of juggling command line arguments and different scripts, you can define your setups once and start them with a button click.

You might have the same type of laser at different GPIB addresses, or need to switch between a mock DAQ for development and the real hardware for experiments. Different labs often have their own instrument configurations, and the launcher makes it easy to switch between these setups without remembering which address corresponds to which instrument in each location.

Rather than typing:
```bash
python run_server.py --devices real --port 5000 --address GPIB0::1
```

You just click the "Real Hardware" button.

## Quick Start

1. Create `lab_servers.py` configuration file
2. Run launcher GUI: `just launcher`
3. Click "Start" on desired configuration

## Setting Up Configurations

Create a `lab_servers.py` file in your project directory. This is where you'll define all your server setups:

```python
# lab_servers.py
from labdaemon import LabDaemon
from my_devices import MyLaser, MockLaser

def setup_mock_server(daemon):
    """Mock devices - no hardware needed."""
    daemon.register_plugins(devices={"MyLaser": MockLaser})
    laser = daemon.add_device("laser1", "MyLaser")
    daemon.connect_device(laser)

def setup_real_server(daemon):
    """Real hardware setup."""
    daemon.register_plugins(devices={"MyLaser": MyLaser})
    laser = daemon.add_device("laser1", "MyLaser", address="GPIB0::1")
    daemon.connect_device(laser)

# Launcher reads this
CONFIGS = {
    "mock": {
        "name": "Mock Devices (Testing)",
        "port": 5000,
        "script": "run_mock.py"
    },
    "real": {
        "name": "Real Hardware",
        "port": 5001,
        "script": "run_real.py"
    }
}
```

Create corresponding server scripts:

```python
# run_mock.py
from labdaemon import LabDaemon, LabDaemonServer
from lab_servers import setup_mock_server

daemon = LabDaemon()
setup_mock_server(daemon)
server = LabDaemonServer(daemon, port=5000)

try:
    print("Mock server running at http://localhost:5000")
    server.start(blocking=True)
except KeyboardInterrupt:
    pass
finally:
    server.stop()
    daemon.shutdown()
```

## Finding Your Configuration

The launcher will look for your `lab_servers.py` file in several places, in this order:

1. Custom path: Use `--config` or set the `LABDAEMON_CONFIG` environment variable
2. Current directory: Looks for `./lab_servers.py` 
3. Home directory: Checks `~/.labdaemon/lab_servers.py`
4. File browser: If none are found, it will open a file picker

```bash
# Default search
just launcher

# Specify a custom location
just launcher --config /path/to/my_lab_config.py

# Or set it once
export LABDAEMON_CONFIG=/path/to/lab_servers.py
just launcher
```

## More Configuration Options

You can include all device parameters in your setup functions:

```python
def setup_real_server(daemon):
    """Real hardware with full configuration."""
    daemon.register_plugins(devices={"SantecLaser": SantecLaser})
    
    laser = daemon.add_device(
        "santec_tsl",
        "SantecLaser",
        address="GPIB0::1",
        timeout=5.0,
        stabilization_timeout=60.0
    )
    daemon.connect_device(laser)
```

Give your configurations clear, descriptive names so everyone knows what they're starting:

```python
CONFIGS = {
    "lab_a_real": {
        "name": "Lab A - Real Hardware (Santec TSL-710)",
        "port": 5000,
        "script": "run_lab_a.py"
    },
    "lab_a_mock": {
        "name": "Lab A - Mock Devices (Testing)",
        "port": 5001,
        "script": "run_lab_a_mock.py"
    },
    "lab_b_real": {
        "name": "Lab B - Real Hardware (Different Setup)",
        "port": 5002,
        "script": "run_lab_b.py"
    }
}
```

You can also mix real and mock devices in the same configuration - useful for development:

```python
def setup_development_server(daemon):
    """Development setup - real laser, mock DAQ."""
    daemon.register_plugins(devices={
        "SantecLaser": SantecLaser,
        "MockPicoscope": MockPicoscope
    })
    
    # Real laser for testing wavelength control
    laser = daemon.add_device("santec_tsl", "SantecLaser", address="GPIB0::1")
    daemon.connect_device(laser)
    
    # Mock DAQ for development without hardware
    daq = daemon.add_device("picoscope_daq", "MockPicoscope")
    daemon.connect_device(daq)
```

## Launcher Features

The launcher handles all the process management for you:

- Start/Stop buttons: Toggle server processes with a click
- Health monitoring: Visual status indicators show if servers are responding
- Auto-cleanup: Stops all servers when you close the launcher
- Multiple servers: Run different configurations on different ports at the same time

You can also watch what's happening:

- Real-time logs: See server output directly in the launcher window
- Status indicators: Green/red indicators show server health at a glance
- PID management: Detects and helps clean up orphaned processes

The built-in editor makes it easy to tweak configurations:

- Edit in-place: Modify `lab_servers.py` without leaving the launcher
- Syntax highlighting: Python code is properly highlighted and readable
- Validation: Automatic syntax checking when you save

## How People Use It

**Desktop users** typically:
1. Open the Server Launcher and click Start for their configuration
2. Open their client app and connect to `http://localhost:5000`
3. Run experiments and view data

**In a lab network**:
1. An admin starts the server on the lab machine using the launcher
2. Users connect their clients to a known URL like `http://lab-pc:5000`
3. Multiple people can monitor the same experiment from different computers

**Developers** often:
1. Run the server script directly: `python scripts/run_real_server.py`
2. Connect their client to `http://localhost:5000`
3. Develop and test their code

## Security

Keep your servers secure:

- Development: Bind to `127.0.0.1` (localhost only)
- Lab LAN: Bind to a specific interface and restrict access with a firewall
- Never expose to the internet: There's no authentication, so anyone could control your devices
- Remote access: Use a VPN or SSH tunnels instead of opening ports to the internet

### SSH Port Forwarding

Access the LabDaemon server's HTTP interface remotely to control devices from your local machine.

Port forwarding is possible if you can make a Secure Shell (SSH) connection to the lab machine. 

**Find the lab machine IP:**
- Windows: `ipconfig` (look for IPv4 Address)
- Linux/Mac: `ip addr show` or `ifconfig` (look for inet address)

First test the basic connection:

```bash
# Verify SSH access (replace 192.168.1.100 with actual IP)
ssh labuser@192.168.1.100
# Exit after confirming access
exit
```

**Note**: LabDaemon server must bind to `127.0.0.1` (localhost) for SSH forwarding to work.

#### Basic Forwarding (Home/Campus → Lab)

If LabDaemon serves at `http://localhost:5000` on lab machine (IP: 192.168.1.100):

**On your local machine:**
```bash
# Replace 'labuser' with the actual account name on the lab machine
ssh -L 8080:localhost:5000 labuser@192.168.1.100
# Access at http://localhost:8080
```

#### Multiple Ports

If LabDaemon serves at ports 5000, 5001, 5002:

**On your local machine:**
```bash
ssh -L 8080:localhost:5000 -L 8081:localhost:5001 -L 8082:localhost:5002 labuser@192.168.1.100
```

#### VPN Access

1. Connect to institutional VPN on your local machine
2. SSH to lab machine using internal IP or hostname
3. Forward ports as above

#### Reverse Tunneling (Lab → Home)

Use when lab network blocks inbound connections or has restrictive firewalls. The lab machine initiates the connection to bypass these restrictions.

**On lab machine:**
```bash
ssh -R 8080:localhost:5000 user@home-pc.example.com
```

**On your home machine:**
```bash
# Access at http://localhost:8080
```

#### Common Issues

- "Connection refused": Server must bind to 127.0.0.1, not 0.0.0.0
- "Port already in use": Use different local port (e.g., 8081 instead of 8080)
- "Channel open failed": Check firewall and service status

#### Best Practices

- Use SSH keys for authentication (see e.g. [SSH key setup](https://quickref.me/ssh.html))
- Background with `-f -N` flags: `ssh -f -N -L 8080:localhost:5000 user@192.168.1.100`
- Configure aliases in `~/.ssh/config`

## Troubleshooting

### Common Issues

"No configurations found"
- Check `lab_servers.py` exists in current directory
- Verify file syntax is valid Python
- Use `--config` to specify custom path

"Server won't start"
- Check port conflicts (another service using the port)
- Verify device addresses are correct
- Check hardware connections and power

"Can't connect to devices"
- Verify hardware connections
- Check device drivers are installed
- Ensure device addresses match configuration


### Configuration Validation

Test your configuration without starting servers:

```python
# test_config.py
from lab_servers import setup_real_server
from labdaemon import LabDaemon

# Test configuration loading
daemon = LabDaemon()
try:
    setup_real_server(daemon)
    print("Configuration is valid")
except Exception as e:
    print(f"Configuration error: {e}")
finally:
    daemon.shutdown()
```

## Integration with Client Applications

Client applications should connect to running servers rather than managing servers themselves. See [GUI Development](gui-development.md) for patterns on building client applications that work with the server management system.

### Recommended Client Pattern

```python
from labdaemon.patterns import ensure_server
from labdaemon.server import ServerAPI

# Let user specify server URL
server_url = input("Enter server URL: ")

# Check server health before connecting
if not ensure_server(server_url=server_url):
    print("Server not responding")
    exit(1)

# Connect and use
api = ServerAPI(server_url)
# ... use API normally
```

This separation allows:
- Server management: Handled by launcher (or scripts)
- Client applications: Focus on user interface and experiment logic
- Multiple clients: Can connect to the same server
- Non-technical users: Can start servers without command line
