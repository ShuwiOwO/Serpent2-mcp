"""PNG plotting helpers. matplotlib is an optional dependency ([plots] extra)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .matlab import parse_matlab_file
from .outputs import detector_series


def available() -> bool:
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        return False
    return True


def _plt():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "matplotlib is not installed. Install the plotting extra: "
            "pip install 'serpent2-mcp[plots]' (or run ./setup.sh)."
        ) from exc
    return plt


_LABELS = {
    "ru": {
        "energy": "Энергия, МэВ",
        "index": "Индекс",
        "response": "Отклик (интеграл)",
        "detector": "Детектор",
        "burnup": "Выгорание, МВт·сут/кгU",
        "days": "Время, сут",
        "keff": "k-eff",
        "value": "Значение",
        "error": "Погрешность",
        "all_errors": "Абсолютная погрешность (1σ)",
    },
    "en": {
        "energy": "Energy, MeV",
        "index": "Index",
        "response": "Response (integral)",
        "detector": "Detector",
        "burnup": "Burnup, MWd/kgU",
        "days": "Time, days",
        "keff": "k-eff",
        "value": "Value",
        "error": "Error",
        "all_errors": "Absolute error (1σ)",
    },
}


def _labels(lang: str) -> dict[str, str]:
    return _LABELS.get(lang, _LABELS["en"])


def _finish(plt, fig, out_path: Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def plot_detector(
    det_path: str | Path,
    det_name: str,
    out_path: str | Path,
    lang: str = "ru",
) -> Path:
    plt = _plt()
    labels = _labels(lang)
    det = parse_matlab_file(det_path)
    data = detector_series(det, det_name)
    points = [p for p in data["points"] if p["mean"] is not None]
    if not points:
        raise ValueError(f"detector '{det_name}' has no scores")
    if any(p["emid"] is not None for p in points):
        x = [p["emid"] for p in points]
        xlabel = labels["energy"]
    else:
        x = list(range(1, len(points) + 1))
        xlabel = labels["index"]
    y = [float(p["mean"]) for p in points]
    yerr = [abs(float(p["mean"])) * float(p["error"]) if p["error"] and p["error"] > 0 else 0.0 for p in points]

    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    ax.errorbar(x, y, yerr=yerr, fmt="o-", ms=3.5, lw=1.0, capsize=2)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(labels["response"])
    ax.set_title(f"{labels['detector']} {det_name}")
    ax.grid(alpha=0.3)
    if x and all(v is not None and v > 0 for v in x):
        ax.set_xscale("log")
    positive = [v for v in y if v > 0]
    if positive and max(positive) / max(min(positive), 1e-300) > 1e4:
        ax.set_yscale("log")
    return _finish(plt, fig, Path(out_path))


def plot_keff(
    res_path: str | Path,
    out_path: str | Path,
    lang: str = "ru",
    estimator: str = "ANA_KEFF",
) -> Path:
    plt = _plt()
    labels = _labels(lang)
    res = parse_matlab_file(res_path)
    series = res.get(estimator)
    if series is None:
        raise KeyError(f"variable '{estimator}' not found in {res_path}")
    rows = series.rows()
    means = [row[0] for row in rows]
    errs = [abs(row[0]) * row[1] if len(row) > 1 and row[1] > 0 else 0.0 for row in rows]
    burnup = res.get("BURNUP")
    if burnup is not None and len(burnup.rows()) == len(rows):
        x = [row[0] for row in burnup.rows()]
        xlabel = labels["burnup"]
    else:
        x = list(range(1, len(rows) + 1))
        xlabel = labels["index"]
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    ax.errorbar(x, means, yerr=errs, fmt="s-", ms=4, lw=1.0, capsize=2)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(labels["keff"])
    ax.set_title(estimator)
    ax.grid(alpha=0.3)
    return _finish(plt, fig, Path(out_path))


def plot_variables(
    source_path: str | Path,
    x_name: str,
    y_name: str,
    out_path: str | Path,
    lang: str = "ru",
    log_x: bool = False,
    log_y: bool = False,
) -> Path:
    plt = _plt()
    labels = _labels(lang)
    data = parse_matlab_file(source_path)
    if x_name not in data:
        raise KeyError(f"variable '{x_name}' not found")
    if y_name not in data:
        raise KeyError(f"variable '{y_name}' not found")
    x_rows = data[x_name].rows()
    y_rows = data[y_name].rows()
    x = [row[0] for row in x_rows]
    y = [row[0] for row in y_rows]
    yerr = [abs(row[0]) * row[1] if len(row) > 1 and row[1] > 0 else 0.0 for row in y_rows]
    n = min(len(x), len(y))
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    if any(e > 0 for e in yerr[:n]):
        ax.errorbar(x[:n], y[:n], yerr=yerr[:n], fmt="o-", ms=3.5, lw=1.0, capsize=2)
    else:
        ax.plot(x[:n], y[:n], "o-", ms=3.5, lw=1.0)
    ax.set_xlabel(x_name)
    ax.set_ylabel(y_name)
    ax.set_title(f"{y_name} vs {x_name}")
    ax.grid(alpha=0.3)
    if log_x:
        ax.set_xscale("log")
    if log_y:
        ax.set_yscale("log")
    return _finish(plt, fig, Path(out_path))


def plot_dep_burnup(dep_path: str | Path, out_path: str | Path, lang: str = "ru") -> Path:
    plt = _plt()
    labels = _labels(lang)
    dep = parse_matlab_file(dep_path)
    bu = dep.get("BU")
    days = dep.get("DAYS")
    if bu is None and days is None:
        raise KeyError("neither BU nor DAYS found in the depletion output")
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    if bu is not None and days is not None:
        x = [row[0] for row in days.rows()]
        y = [row[0] for row in bu.rows()]
        n = min(len(x), len(y))
        ax.plot(x[:n], y[:n], "o-", lw=1.0)
        ax.set_xlabel(labels["days"])
        ax.set_ylabel(labels["burnup"])
    elif bu is not None:
        y = [row[0] for row in bu.rows()]
        ax.plot(range(1, len(y) + 1), y, "o-", lw=1.0)
        ax.set_xlabel(labels["index"])
        ax.set_ylabel(labels["burnup"])
    else:
        x = [row[0] for row in days.rows()]
        ax.plot(range(1, len(x) + 1), x, "o-", lw=1.0)
        ax.set_xlabel(labels["index"])
        ax.set_ylabel(labels["days"])
    ax.set_title("Burnup / depletion")
    ax.grid(alpha=0.3)
    return _finish(plt, fig, Path(out_path))
