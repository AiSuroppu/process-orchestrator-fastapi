import subprocess
import os
import signal
import threading
import time
import yaml
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

# Conditionally import pty for TTY emulation on Unix-like systems
if sys.platform != "win32":
    import pty

from models import ServiceStatus
from console_manager import console_manager

# --- Color formatting for console output ---
class TColors:
    # Basic colors
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    
    # Formatting
    ENDC = '\033[0m'
    BOLD = '\033[1m'

    # A list of 10 contrasting colors for group tags, ordered by perceptual distinction.
    GROUP_COLORS = [
        '\033[93m', # 1. Bright Yellow
        '\033[96m', # 2. Bright Cyan
        '\033[92m', # 3. Bright Green
        '\033[95m', # 4. Bright Magenta
        '\033[97m', # 5. Bright White
        '\033[91m', # 6. Bright Red
        '\033[94m', # 7. Bright Blue
        '\033[36m', # 8. Normal Cyan
        '\033[35m', # 9. Normal Magenta
        '\033[32m', # 10. Normal Green
    ]

def print_orchestrator(message, level="info"):
    color = {
        "info": TColors.OKGREEN,
        "warn": TColors.WARNING,
        "error": TColors.FAIL
    }.get(level, TColors.OKGREEN)
    prefix = f"{color}{TColors.BOLD}[Orchestrator]{TColors.ENDC} "
    # Use the console manager, giving it a unique name
    console_manager.print("Orchestrator", message + "\n", prefix) # Add newline for orchestrator logs

class ProcessInfo:
    """Holds all state for a single managed process."""
    def __init__(self, group_id: str, config: Dict[str, Any]):
        self.group_id = group_id
        self.config = config
        self.name = config['name']
        self.popen: Optional[subprocess.Popen] = None
        self.log_thread: Optional[threading.Thread] = None
        self.start_time: Optional[datetime] = None
        self.manually_stopped: bool = False

class ProcessManager:
    def __init__(self, config_path: str):
        self.config = self._load_config(config_path)
        # We store processes by their unique name
        self.running_processes: Dict[str, ProcessInfo] = {}
        # Threading events for graceful shutdown
        self._monitor_thread = threading.Thread(target=self._monitor_and_restart, daemon=True)
        self._shutdown_event = threading.Event()

    def _load_config(self, config_path: str) -> Dict:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)

    def start_monitoring(self):
        """Starts the background monitoring thread."""
        if not self._monitor_thread.is_alive():
            print_orchestrator("Starting background process monitor...")
            self._monitor_thread.start()

    def stop_monitoring(self):
        """Signals the monitoring thread to shut down."""
        print_orchestrator("Stopping background process monitor...")
        self._shutdown_event.set()
        # Wait for the thread to finish
        self._monitor_thread.join(timeout=2)

    def _log_forwarder(self, process_name: str, group_id: str, pty_master_fd: Optional[int], popen_instance: subprocess.Popen):
        """
        Reads raw output from a process and forwards it to the console manager.
        This function reads in chunks to handle interactive output like progress bars correctly.
        """
        # Consistently select a color based on the group_id hash
        color_index = hash(group_id) % len(TColors.GROUP_COLORS)
        group_color = TColors.GROUP_COLORS[color_index]
        # Build the prefix using the selected color for the tag
        prefix = f"{TColors.BOLD}{group_color}[{process_name}]{TColors.ENDC} "

        # Use the pty file descriptor on Unix, otherwise use the process's stdout pipe
        stream = pty_master_fd if pty_master_fd is not None else popen_instance.stdout.fileno()

        try:
            while True:
                # Read in small chunks to get real-time updates.
                # This is non-blocking on pty and will capture \r immediately.
                raw_output = os.read(stream, 1024)
                if not raw_output:
                    # An empty read means the other end of the pipe was closed.
                    break
                
                # Decode the bytes into a string, replacing any malformed characters.
                message = raw_output.decode('utf-8', errors='replace')
                if message:
                    console_manager.print(process_name, message, prefix)

        except (IOError, OSError) as e:
            # This can happen if the process closes abruptly.
            print_orchestrator(f"Log forwarder for '{process_name}' stopped due to IO error: {e}", level="warn")
        finally:
            # Clean up resources
            if pty_master_fd is not None:
                os.close(pty_master_fd)
            elif popen_instance.stdout:
                popen_instance.stdout.close()
    
    def _start_single_service(self, info: ProcessInfo) -> bool:
        """Internal method to start one service and its log forwarder."""
        try:
            service_name = info.name
            config = info.config
            working_dir = Path(config['working_dir']).expanduser()
            
            print_orchestrator(f"Starting service '{service_name}' in '{working_dir}'...")

            pty_master_fd = None # Default for Windows
            if sys.platform != "win32":
                master_fd, slave_fd = pty.openpty()
                stdout_target = slave_fd
                pty_master_fd = master_fd
            else:
                # pty is not available on Windows, fall back to standard pipe.
                stdout_target = subprocess.PIPE

            info.popen = subprocess.Popen(
                config['script'],
                cwd=working_dir,
                stdout=stdout_target,
                stderr=subprocess.STDOUT,
                text=True if sys.platform == "win32" else False, # text=False for raw bytes with PTY
                bufsize=1,
                shell=True,
                preexec_fn=os.setsid if sys.platform != "win32" else None
            )
            
            if sys.platform != "win32":
                os.close(stdout_target) # Close the slave fd in the parent

            # Start the log forwarding thread
            info.log_thread = threading.Thread(
                target=self._log_forwarder,
                args=(service_name, info.group_id, pty_master_fd, info.popen),
                daemon=True
            )
            info.log_thread.start()
            
            info.start_time = datetime.now()
            info.manually_stopped = False
            self.running_processes[service_name] = info
            
            print_orchestrator(f"Service '{service_name}' started with PID {info.popen.pid}.", level="info")
            return True
        except Exception as e:
            print_orchestrator(f"Failed to start service '{info.name}': {e}", level="error")
            return False

    def _stop_single_service(self, service_name: str):
        """Internal method to stop one service."""
        info = self.running_processes.get(service_name)
        if not info or not info.popen:
            return

        print_orchestrator(f"Stopping service '{service_name}' (PID: {info.popen.pid})...")
        info.manually_stopped = True # Mark for monitor to ignore
        
        try:
            if sys.platform != "win32":
                os.killpg(os.getpgid(info.popen.pid), signal.SIGINT)
            else:
                # Windows does not support process groups well, send CTRL+BREAK
                info.popen.send_signal(signal.CTRL_BREAK_EVENT)
            
            info.popen.wait(timeout=10)
            print_orchestrator(f"Service '{service_name}' stopped gracefully.")
        except subprocess.TimeoutExpired:
            print_orchestrator(f"Service '{service_name}' did not stop gracefully, sending SIGKILL/Terminate.", level="warn")
            if sys.platform != "win32":
                os.killpg(os.getpgid(info.popen.pid), signal.SIGKILL)
            else:
                info.popen.terminate()
        except ProcessLookupError:
            print_orchestrator(f"Process for '{service_name}' already gone.", level="warn")
        except Exception as e:
             print_orchestrator(f"Error stopping process '{service_name}': {e}", level="error")
        finally:
            # The log thread will exit automatically when the pipe closes
            if service_name in self.running_processes:
                del self.running_processes[service_name]

    def _monitor_and_restart(self):
        """Thread target: checks for crashed processes and restarts them."""
        while not self._shutdown_event.is_set():
            time.sleep(5) # Check every 5 seconds
            
            # Iterate over a copy of the items to allow modification
            crashed_services = []
            for name, info in list(self.running_processes.items()):
                if info.popen.poll() is not None: # Process has terminated
                    if not info.manually_stopped:
                        print_orchestrator(f"Service '{name}' crashed (exit code {info.popen.returncode}). Scheduling restart.", level="error")
                        crashed_services.append(info)
                    
                    # Clean up the dead process entry
                    del self.running_processes[name]

            # Restart crashed services
            for info in crashed_services:
                self._start_single_service(info)

    def start_group(self, group_id: str) -> List[ServiceStatus]:
        """Starts all services defined under a group_id in the config."""
        group_services = self.config.get("service_groups", {}).get(group_id)
        if not group_services:
            return [ServiceStatus(name=f"group_{group_id}", group_id=group_id, status="stopped", detail="Group ID not found in config.")]

        statuses = []
        for service_config in group_services:
            name = service_config['name']
            if name in self.running_processes:
                statuses.append(self.get_status_for_service(name, group_id))
                continue
            
            info = ProcessInfo(group_id, service_config)
            self._start_single_service(info)
            statuses.append(self.get_status_for_service(name, group_id))
        return statuses

    def stop_group(self, group_id: str):
        """Stops all running services that belong to a specific group."""
        # Find all services in the group that are currently running
        services_to_stop = [
            name for name, info in self.running_processes.items()
            if info.group_id == group_id
        ]
        for name in services_to_stop:
            self._stop_single_service(name)

    def stop_all(self):
        """Stops all managed processes, for server shutdown."""
        print_orchestrator("Shutting down all managed services...")
        for name in list(self.running_processes.keys()):
            self._stop_single_service(name)

    def get_all_statuses(self) -> List[ServiceStatus]:
        """Returns the status of all configured services."""
        statuses = []
        all_services = self.config.get("service_groups", {})
        for group_id, services in all_services.items():
            for service_config in services:
                statuses.append(self.get_status_for_service(service_config['name'], group_id))
        return statuses

    def get_status_for_service(self, service_name: str, group_id: str) -> ServiceStatus:
        info = self.running_processes.get(service_name)
        if info and info.popen and info.popen.poll() is None:
            return ServiceStatus(
                name=service_name,
                group_id=group_id,
                status="running",
                pid=info.popen.pid,
                start_time=info.start_time,
                detail=f"Running since {info.start_time.isoformat()}"
            )
        return ServiceStatus(
            name=service_name,
            group_id=group_id,
            status="stopped",
            detail="Service is not running."
        )

# Create a single, global instance
process_manager = ProcessManager(config_path="config.yaml")