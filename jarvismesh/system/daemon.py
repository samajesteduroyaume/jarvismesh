"""
Module de gestionnaire de service démon en tâche de fond pour JarvisMesh.

Supporte :
  - macOS via `launchd` (~/Library/LaunchAgents/com.jarvismesh.agent.plist)
  - Linux via `systemd` (~/.config/systemd/user/jarvismesh.service ou /etc/systemd/system/)
"""
from __future__ import annotations
import os
import platform
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Optional


SERVICE_LABEL = "com.jarvismesh.agent"


def get_log_dir() -> Path:
    """Retourne et crée le dossier standard de logs de JarvisMesh."""
    log_dir = Path.home() / ".jarvismesh" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def generate_macos_plist(
    name: str = "mac-node",
    port: int = 8765,
    python_bin: Optional[str] = None,
    extra_args: Optional[list[str]] = None,
) -> dict:
    """Génère la structure du dictionnaire plist pour macOS launchd."""
    py_exec = python_bin or sys.executable
    log_dir = get_log_dir()
    stdout_log = str(log_dir / "jarvismesh.stdout.log")
    stderr_log = str(log_dir / "jarvismesh.stderr.log")

    args = [
        py_exec,
        "-m",
        "jarvismesh.cli",
        "start",
        "--name",
        name,
        "--port",
        str(port),
    ]
    if extra_args:
        args.extend(extra_args)

    return {
        "Label": SERVICE_LABEL,
        "ProgramArguments": args,
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": stdout_log,
        "StandardErrorPath": stderr_log,
        "WorkingDirectory": str(Path.home()),
        "EnvironmentVariables": {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "PYTHONUNBUFFERED": "1",
        },
    }


def generate_systemd_unit(
    name: str = "linux-node",
    port: int = 8765,
    python_bin: Optional[str] = None,
    extra_args: Optional[list[str]] = None,
) -> str:
    """Génère le contenu d'un fichier de service systemd pour Linux."""
    py_exec = python_bin or sys.executable
    args = [py_exec, "-m", "jarvismesh.cli", "start", "--name", name, "--port", str(port)]
    if extra_args:
        args.extend(extra_args)
    exec_str = " ".join(args)

    return f"""[Unit]
Description=JarvisMesh Sovereign Distributed AI Agent Service
After=network.target

[Service]
Type=simple
ExecStart={exec_str}
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
"""


class ServiceManager:
    """Gestionnaire d'installation et de contrôle du service démon JarvisMesh."""

    def __init__(self):
        self.os_type = platform.system().lower()

    def get_service_file_path(self) -> Path:
        if self.os_type == "darwin":
            return Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"
        else:
            return Path.home() / ".config" / "systemd" / "user" / "jarvismesh.service"

    def install(
        self,
        name: str = "local-node",
        port: int = 8765,
        python_bin: Optional[str] = None,
        extra_args: Optional[list[str]] = None,
    ) -> Path:
        """Installe le fichier de service sur l'OS hôte."""
        target_path = self.get_service_file_path()
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if self.os_type == "darwin":
            plist_dict = generate_macos_plist(name, port, python_bin, extra_args)
            with open(target_path, "wb") as f:
                plistlib.dump(plist_dict, f)
        else:
            unit_content = generate_systemd_unit(name, port, python_bin, extra_args)
            target_path.write_text(unit_content, encoding="utf-8")

        return target_path

    def uninstall(self) -> bool:
        """Désinstalle et supprime le fichier de service."""
        self.stop()
        path = self.get_service_file_path()
        if path.exists():
            path.unlink()
            return True
        return False

    def start(self) -> tuple[bool, str]:
        """Démarre le service via le gestionnaire d'init de l'OS."""
        path = self.get_service_file_path()
        if not path.exists():
            return False, f"Le service n'est pas installé ({path} introuvable)"

        if self.os_type == "darwin":
            res = subprocess.run(["launchctl", "load", "-w", str(path)], capture_output=True, text=True)
            return (res.returncode == 0), res.stderr or res.stdout
        else:
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
            res = subprocess.run(["systemctl", "--user", "start", "jarvismesh"], capture_output=True, text=True)
            return (res.returncode == 0), res.stderr or res.stdout

    def stop(self) -> tuple[bool, str]:
        """Arrête le service."""
        path = self.get_service_file_path()
        if not path.exists():
            return False, "Service non installé."

        if self.os_type == "darwin":
            res = subprocess.run(["launchctl", "unload", str(path)], capture_output=True, text=True)
            return (res.returncode == 0), res.stderr or res.stdout
        else:
            res = subprocess.run(["systemctl", "--user", "stop", "jarvismesh"], capture_output=True, text=True)
            return (res.returncode == 0), res.stderr or res.stdout

    def status(self) -> dict:
        """Vérifie l'état d'activité du service."""
        path = self.get_service_file_path()
        installed = path.exists()

        running = False
        details = ""

        if installed:
            if self.os_type == "darwin":
                res = subprocess.run(["launchctl", "list", SERVICE_LABEL], capture_output=True, text=True)
                running = (res.returncode == 0)
                details = res.stdout or res.stderr
            else:
                res = subprocess.run(["systemctl", "--user", "is-active", "jarvismesh"], capture_output=True, text=True)
                running = (res.stdout.strip() == "active")
                details = res.stdout.strip()

        return {
            "os": self.os_type,
            "installed": installed,
            "path": str(path),
            "running": running,
            "details": details.strip(),
            "logs_dir": str(get_log_dir()),
        }
