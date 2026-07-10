"""Tuya Cloud API client, composed from focused mixins.

TuyaApiClient (client.py) provides auth/signing/HTTP. Each mixin below adds
one group of related endpoints. Combining them via multiple inheritance
keeps every endpoint group in its own single-purpose file while callers
outside this package still see one TuyaCloudApi with all methods on it —
no changes needed in lock.py, coordinator/*, etc.
"""

from .client import TuyaApiClient, TuyaApiError
from .discovery import DiscoveryMixin
from .lock_control import LockControlMixin
from .passwords import PasswordsMixin
from .records import RecordsMixin
from .status import StatusMixin


class TuyaCloudApi(
    DiscoveryMixin,
    LockControlMixin,
    PasswordsMixin,
    RecordsMixin,
    StatusMixin,
    TuyaApiClient,
):
    """Tuya Cloud API client for lock operations.

    See the individual mixins for what each group of endpoints does.
    """


__all__ = ["TuyaApiError", "TuyaCloudApi"]
