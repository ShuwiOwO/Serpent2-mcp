"""Execution backends (local, ssh) and background jobs.

Note: ``datadl`` is intentionally not imported here. It is executed as
``python -m serpent2_mcp.runner.datadl`` in a subprocess, and importing it in
this package would trigger a runpy "found in sys.modules" warning.
"""

from . import jobs, probe  # noqa: F401
from .jobs import Job, Jobs  # noqa: F401
from .probe import convert_option_style, probe_cached, resolve_executable  # noqa: F401
