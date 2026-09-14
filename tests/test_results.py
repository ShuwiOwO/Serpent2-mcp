"""Matlab output parser and result summaries."""

from __future__ import annotations

from pathlib import Path

from serpent2_mcp.results import (
    detector_series,
    find_outputs,
    parse_matlab,
    parse_matlab_file,
    parse_matlab_file_limited,
    summarize_dep,
    summarize_det,
    summarize_res,
    summarize_source_files,
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


def test_find_outputs_full_input_name(tmp_path: Path):
    (tmp_path / "HW3_N.sh_res.m").write_text("X = 1;\n", encoding="utf-8")
    (tmp_path / "HW3_N.sh_gsrc.m").write_text("mat_a_tot = 1.0E+11;\ntot = 1.0E+11;\n", encoding="utf-8")
    found = find_outputs(tmp_path, "HW3_N.sh")
    assert [p.name for p in found["source"]] == ["HW3_N.sh_gsrc.m"]
    summary = summarize_source_files(found["source"])
    assert summary["total_per_s"] == 1.0e11
    assert summary["materials"]["a"]["total_per_s"] == 1.0e11


def test_parse_matlab_file_limited_streams_large_files(tmp_path: Path):
    path = tmp_path / "big_det.m"
    with path.open("w", encoding="utf-8") as handle:
        handle.write("DETx = [\n")
        for i in range(5000):
            handle.write(f"1 1 1 1 1 1 1 1 1 1 {i}.0 0.01\n")
        handle.write("];\n")
        handle.write("DETxE = [\n 1 2 3\n 4 5 6\n];\n")
    info: dict = {}
    data = parse_matlab_file_limited(path, max_bytes=1024, max_rows=100, info=info)
    assert info["streamed"] is True
    assert "DETx" in info["truncated"]
    assert len(data["DETx"].rows()) == 100
    assert data["DETxE"].rows()[0] == [1.0, 2.0, 3.0]
