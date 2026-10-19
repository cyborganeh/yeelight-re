"""Local, account-free control for Yeelight YLDP06YL (color2) bulbs."""

from .client import MusicMode, YeelightClient
from .discovery import discover, scan_subnet
from .miio import (
    MiioClient,
    MiioError,
    MiioTokenError,
    enable_lan_control,
    probe as miio_probe,
    provision_wifi,
)
from .protocol import (
    CommandError,
    Device,
    LanControlDisabled,
    ProtocolError,
    YeelightError,
    YeelightTimeout,
)

__version__ = "0.3.0"

__all__ = [
    "CommandError",
    "Device",
    "LanControlDisabled",
    "MiioClient",
    "MiioError",
    "MiioTokenError",
    "MusicMode",
    "ProtocolError",
    "YeelightClient",
    "YeelightError",
    "YeelightTimeout",
    "discover",
    "enable_lan_control",
    "miio_probe",
    "provision_wifi",
    "scan_subnet",
]
