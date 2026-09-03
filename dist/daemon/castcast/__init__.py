"""castcast -- a Google-Home-free Chromecast controller daemon.

Speaks CASTv2 directly to the device on the LAN, serves media from local
storage over HTTP, and refuses to send a LOAD it can predict will fail.
"""

__version__ = "1.0.0"

from .capability import Verdict, evaluate            # noqa: F401
from .channel import DEFAULT_MEDIA_RECEIVER_APP_ID, DEFAULT_TEXT_TRACK_STYLE   # noqa: F401
from .discovery import CastDevice, resolve           # noqa: F401
from .probe import MediaInfo, probe                  # noqa: F401
from .service import CastService                     # noqa: F401
from .supervisor import State, Supervisor            # noqa: F401
