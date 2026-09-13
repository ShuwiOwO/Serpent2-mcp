"""Result parsing and plotting for Serpent output files."""

from .matlab import MatValue, parse_matlab, parse_matlab_file  # noqa: F401
from .outputs import (  # noqa: F401
    detector_series,
    find_outputs,
    read_dep,
    read_res,
    summarize_dep,
    summarize_det,
    summarize_res,
)
