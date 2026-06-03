from __future__ import annotations

from .coldstart_artifact_impl import *  # noqa: F401,F403
from . import coldstart_artifact_impl as _impl


if __name__ == "__main__":
    raise SystemExit(_impl.main())
