"""Matlab output parser and result summaries."""

from __future__ import annotations

from pathlib import Path

from serpent2_mcp.results import (
    detector_series,
    parse_matlab,
    parse_matlab_file,
    summarize_dep,
    summarize_det,
    summarize_res,
)


def test_scalars_and_matrices():
    text = """
VERSION = 2;
TITLE = 'hello world';
ANA_KEFF = [
    1.01234E+00 0.00042
];
BURNUP = [
    0.5 0.0
    1.0 0.0
];
"""
    data = parse_matlab(text)
    assert data["VERSION"].scalar() == 2
    assert data["TITLE"].value == "hello world"
    assert data["ANA_KEFF"].mean_err() == (1.01234, 0.00042)
    assert len(data["BURNUP"].rows()) == 2


def test_indexed_strings():
    text = """
nuc(   1, :) = '   1001.06c';
nuc(   2, :) = '   8016.06c';
"""
    data = parse_matlab(text)
    assert data["nuc"].kind == "strings"
    assert data["nuc"].value == ["1001.06c", "8016.06c"]


def test_nan_and_comments():
    text = """
X = [
    NaN 0.0
];
Y = 1.5; % trailing comment
"""
    data = parse_matlab(text)
    assert data["X"].rows()[0][0] != data["X"].rows()[0][0]  # NaN
    assert data["Y"].scalar() == 1.5


def test_summarize_res(fixtures_dir: Path):
    res = parse_matlab_file(fixtures_dir / "res_mini.m")
    summary = summarize_res(res)
    assert summary["keff"]["ana_keff"]["mean"] == 1.01234
    assert summary["keff"]["imp_keff"]["error"] == 0.00040
    assert summary["run"]["cycles"] == 100
    assert summary["integral"]["tot_power"]["mean"] == 150.0
    assert summary["burnup"]["burnup"] == [0.5, 1.0, 5.0]


def test_summarize_det(fixtures_dir: Path):
    det = parse_matlab_file(fixtures_dir / "det_mini.m")
    summary = summarize_det(det)
    assert "flux" in summary["detectors"]
    entry = summary["detectors"]["flux"]
    assert entry["columns"][-2:] == ["MEAN", "ERR"]
    assert len(entry["energy_bins"]) == 2
    series = detector_series(det, "flux")
    assert series["points"][0]["emid"] == 1.0e-7
    assert series["points"][1]["mean"] == 2.54321e13


def test_summarize_dep(fixtures_dir: Path):
    dep = parse_matlab_file(fixtures_dir / "dep_mini.m")
    summary = summarize_dep(dep)
    assert summary["nuclides"] == ["U-235", "U-238", "O-16"]
    assert summary["bu"] == [0.0, 1.0, 5.0]
    assert summary["days"] == [0.0, 30.0, 150.0]
