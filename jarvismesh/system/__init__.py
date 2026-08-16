"""
Sous-package System : Démons de service launchd/systemd, Interface CLI et Dashboard Web.
"""
from .daemon import (
    SERVICE_LABEL,
    get_log_dir,
    generate_macos_plist,
    generate_systemd_unit,
    ServiceManager,
)
from .cli import main
from .dashboard.server import DashboardServer, run_dashboard

__all__ = [
    "SERVICE_LABEL",
    "get_log_dir",
    "generate_macos_plist",
    "generate_systemd_unit",
    "ServiceManager",
    "main",
    "DashboardServer",
    "run_dashboard",
]
