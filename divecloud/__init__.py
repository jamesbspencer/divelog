"""DiveCloud automation, parsing, and UDDF synchronization package."""

from divecloud.client import DiveCloudClient
from divecloud.config import DiveCloudConfig
from divecloud.exceptions import (
    DiveCloudAuthError,
    DiveCloudError,
    DiveCloudNetworkError,
    DiveCloudParseError,
    DiveCloudTimeoutError,
)
from divecloud.parser import DiveComputerInfo, DiveRecord, DiveSample, GasMix, TankInfo, ZXUParser
from divecloud.uddf import UDDFExporter

__all__ = [
    "DiveCloudClient",
    "DiveCloudConfig",
    "DiveCloudError",
    "DiveCloudAuthError",
    "DiveCloudTimeoutError",
    "DiveCloudNetworkError",
    "DiveCloudParseError",
    "ZXUParser",
    "DiveRecord",
    "DiveSample",
    "GasMix",
    "TankInfo",
    "DiveComputerInfo",
    "UDDFExporter",
]
