"""Data update coordinators for Tuya Smart Lock.

Each coordinator centralizes polling for a group of related entities, so
they share a single HTTP call instead of each entity hitting the Tuya API
independently.
"""

from .records import TuyaLockRecordsCoordinator
from .status import TuyaLockStatusCoordinator
from .temp_passwords import TuyaLockTempPasswordsCoordinator

__all__ = [
    "TuyaLockRecordsCoordinator",
    "TuyaLockStatusCoordinator",
    "TuyaLockTempPasswordsCoordinator",
]
