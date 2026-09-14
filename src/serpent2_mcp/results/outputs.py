"""Collect and summarise Serpent output files."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from .matlab import MatValue, parse_matlab_file, parse_matlab_file_limited

RES_KEFF_KEYS = ["ANA_KEFF", "IMP_KEFF", "COL_KEFF", "ABS_KEFF", "ABS_KINF", "SIX_FF_KEFF"]
RES_POWER_KEYS = ["TOT_POWER", "TOT_POWDENS", "TOT_FLUX", "TOT_FISSRATE", "TOT_CAPTRATE", "TOT_GENRATE"]
RES_RUN_KEYS = [
    "VERSION",
    "TITLE",
    "INPUT_FILE_NAME",
    "RUNNING_TIME",
    "TOT_CPU_TIME",
    "SIMULATION_COMPLETED",
    "CYCLES",
    "SKIP",
    "POP",
    "BATCHES",
    "SEED",
    "MPI_TASKS",
    "OMP_THREADS",
]


def find_outputs(workdir: str | Path, input_name: str) -> dict[str, list[Path]]:
    """Find Serpent output files related to an input name.

    Serpent keeps the full input file name including its extension, so both
    ``case.inp -> case.inp_res.m`` and ``case -> case_res.m`` are supported.
    """
    workdir = Path(workdir)
    full = Path(input_name).name
    short = Path(full).stem
    stems = [full] + ([short] if short != full else [])
    outputs: dict[str, list[Path]] = {
        "res": [],
        "det": [],
        "dep": [],
        "his": [],
        "mdx": [],
        "source": [],
        "other": [],
    }
    if not workdir.is_dir():
        return outputs
    for stem in stems:
        patterns = {
            "res": [f"{stem}_res.m"],
            "dep": [f"{stem}_dep.m", f"{stem}_dep*.m"],
            "mdx": [f"{stem}_mdx*.m", f"{stem}_mdep.inc"],
            "his": [f"{stem}_his*.m"],
            "source": [f"{stem}_gsrc.m", f"{stem}_nsrc.m"],
            "other": [f"{stem}.out", f"{stem}_xs*.m", f"{stem}_stat*.m", f"{stem}.seed"],
        }
        for kind, globs in patterns.items():
            for pattern in globs:
                for path in sorted(workdir.glob(pattern)):
                    if path not in outputs[kind]:
                        outputs[kind].append(path)
        det_re = re.compile(rf"^{re.escape(stem)}_det\d*(b\d+)?\.m$")
        for path in sorted(workdir.glob(f"{stem}_det*.m")):
            if det_re.match(path.name) and path not in outputs["det"]:
                outputs["det"].append(path)
    return outputs


def _clean_number(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def summarize_res(res: dict[str, MatValue], max_errors: int = 5) -> dict[str, Any]:
    summary: dict[str, Any] = {"available_variables": sorted(res.keys())}

    info: dict[str, Any] = {}
    for key in ["VERSION", "TITLE", "INPUT_FILE_NAME", "COMPLETE_DATE", "START_DATE"]:
        value = res.get(key)
        if value is not None and value.kind == "string":
            info[key.lower()] = value.value
    run: dict[str, Any] = {}
    for key in ["RUNNING_TIME", "TOT_CPU_TIME", "CYCLES", "SKIP", "POP", "BATCHES", "SEED", "MPI_TASKS", "OMP_THREADS"]:
        value = res.get(key)
        if value is not None:
            scalar = value.scalar()
            run[key.lower()] = scalar if scalar is not None else value.value
    completed = res.get("SIMULATION_COMPLETED")
    if completed is not None:
        run["simulation_completed"] = completed.scalar()

    keff: dict[str, Any] = {}
    for key in RES_KEFF_KEYS:
        value = res.get(key)
        if value is None:
            continue
        rows = value.rows()
        if not rows:
            continue
        series = []
        for row in rows:
            mean = _clean_number(row[0]) if row else None
            err = _clean_number(row[1]) if len(row) > 1 else None
            series.append({"mean": mean, "error": err})
        keff[key.lower()] = series[0] if len(series) == 1 else series

    integral: dict[str, Any] = {}
    for key in RES_POWER_KEYS:
        value = res.get(key)
        if value is None:
            continue
        rows = value.rows()
        if rows:
            integral[key.lower()] = {
                "mean": _clean_number(rows[0][0]),
                "error": _clean_number(rows[0][1]) if len(rows[0]) > 1 else None,
            }

    burnup: dict[str, Any] = {}
    for key in ["BURNUP", "BURN_DAYS", "BURN_STEP", "FIMA"]:
        value = res.get(key)
        if value is None:
            continue
        rows = value.rows()
        if rows:
            burnup[key.lower()] = [row[0] for row in rows]

    summary["info"] = info
    summary["run"] = run
    summary["keff"] = keff
    summary["integral"] = integral
    if burnup:
        summary["burnup"] = burnup
    return summary


def read_res(path: str | Path) -> dict[str, MatValue]:
    return parse_matlab_file(path)


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------

DET_COLUMNS_BASE = [
    "EBI",
    "UBI",
    "CBI",
    "MBI",
    "LBI",
    "RBI",
    "XBI",
    "YBI",
    "ZBI",
    "MEAN",
    "ERR",
]
DET_COLUMNS_TBI = ["TBI"] + DET_COLUMNS_BASE


def summarize_det(det: dict[str, MatValue], max_rows: int = 200) -> dict[str, Any]:
    detectors: dict[str, Any] = {}
    names = sorted({key[3:] for key in det if key.startswith("DET") and not re.match(r"^DET.+(E|T|X|Y|Z|R|PHI|THETA|COORD)$", key)})
    for name in names:
        table = det.get(f"DET{name}")
        if table is None or table.kind not in {"matrix", "scalar"}:
            continue
        rows = table.rows()
        columns = DET_COLUMNS_BASE if rows and len(rows[0]) == 11 else DET_COLUMNS_TBI
        entry: dict[str, Any] = {
            "columns": columns,
            "rows": len(rows),
        }
        # total of all MEAN values, useful for a quick look
        try:
            mean_index = columns.index("MEAN")
            err_index = columns.index("ERR")
            total = sum(row[mean_index] for row in rows if len(row) > mean_index)
            total_err = 0.0
            for row in rows:
                if len(row) > err_index and row[err_index] > 0:
                    total_err += (row[mean_index] * row[err_index]) ** 2
            entry["total"] = total
            entry["total_rel_error"] = math.sqrt(total_err) / abs(total) if total else None
        except (ValueError, ZeroDivisionError):
            pass
        energy = det.get(f"DET{name}E")
        if energy is not None and energy.kind == "matrix":
            entry["energy_bins"] = energy.rows()
        time = det.get(f"DET{name}T")
        if time is not None and time.kind == "matrix":
            entry["time_bins"] = time.rows()
        for axis in ("X", "Y", "Z", "R", "PHI", "THETA"):
            boundaries = det.get(f"DET{name}{axis}")
            if boundaries is not None and boundaries.kind == "matrix":
                entry[f"{axis.lower()}_bins"] = boundaries.rows()
        entry["sample"] = rows[:max_rows]
        detectors[name] = entry
    return {"detectors": detectors, "available_variables": sorted(det.keys())}


def detector_series(det: dict[str, MatValue], name: str) -> dict[str, Any]:
    table = det.get(f"DET{name}")
    if table is None:
        raise KeyError(f"detector '{name}' not found in file")
    rows = table.rows()
    columns = DET_COLUMNS_BASE if rows and len(rows[0]) == 11 else DET_COLUMNS_TBI
    energy = det.get(f"DET{name}E")
    e_bins = energy.rows() if energy is not None and energy.kind == "matrix" else []
    mean_index = columns.index("MEAN")
    err_index = columns.index("ERR")
    ebi_index = columns.index("EBI") if "EBI" in columns else 0
    points = []
    for row in rows:
        ebi = int(row[ebi_index]) if len(row) > ebi_index else 0
        emid = None
        if 0 < ebi <= len(e_bins):
            emid = e_bins[ebi - 1][2] if len(e_bins[ebi - 1]) > 2 else None
        points.append(
            {
                "ebi": ebi,
                "emid": emid,
                "mean": row[mean_index] if len(row) > mean_index else None,
                "error": row[err_index] if len(row) > err_index else None,
            }
        )
    return {"columns": columns, "energy_bins": e_bins, "points": points}


# ---------------------------------------------------------------------------
# Burnup / depletion
# ---------------------------------------------------------------------------


def summarize_dep(dep: dict[str, MatValue], max_points: int = 100) -> dict[str, Any]:
    summary: dict[str, Any] = {"available_variables": sorted(dep.keys())}
    names = dep.get("NAMES")
    if names is not None:
        if names.kind == "strings":
            summary["nuclides"] = names.value[:50]
        elif names.kind == "string":
            summary["nuclides"] = [names.value]
    for key in ("BU", "DAYS"):
        value = dep.get(key)
        if value is not None:
            rows = value.rows()
            if rows:
                summary[key.lower()] = rows[0][:max_points]
    total_mass = dep.get("TOT_MASS")
    if total_mass is not None:
        rows = total_mass.rows()
        if rows:
            summary["total_mass_g"] = rows[0][-1] if rows[0] else None
    materials = sorted({key[len("MAT_"):].rsplit("_", 2)[0] for key in dep if key.startswith("MAT_")})
    summary["materials"] = materials
    return summary


def read_dep(path: str | Path) -> dict[str, MatValue]:
    return parse_matlab_file(path)


MAX_DET_BYTES = 20 * 1024 * 1024


def read_det(
    path: str | Path,
    max_bytes: int = MAX_DET_BYTES,
    max_rows: int = 500,
    info: dict | None = None,
) -> dict[str, MatValue]:
    """Read a detector file; huge files are streamed with row limits."""
    return parse_matlab_file_limited(path, max_bytes=max_bytes, max_rows=max_rows, info=info)


def summarize_source_files(paths: list[Path]) -> dict[str, Any]:
    """Summarise _gsrc.m/_nsrc.m: total emission rates used for set srcrate."""
    summary: dict[str, Any] = {"files": [str(path) for path in paths], "materials": {}}
    for path in paths:
        try:
            data = parse_matlab_file(path)
        except OSError:
            continue
        for name, value in data.items():
            if name.startswith("mat_") and name.endswith("_tot"):
                material = name[len("mat_"):-len("_tot")]
                scalar = value.scalar()
                if scalar is not None:
                    summary["materials"].setdefault(material, {})["total_per_s"] = scalar
            elif name == "tot":
                scalar = value.scalar()
                if scalar is not None:
                    summary["total_per_s"] = scalar
    return summary
