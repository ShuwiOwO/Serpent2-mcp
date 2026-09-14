"""Tokenizer, card splitter and static lint checks."""

from __future__ import annotations

from serpent2_mcp.lint import lint_path, lint_text

GOOD_INPUT = """
set title "test"
surf 1 sph 0 0 0 1
cell 1 0 hydrogen -1
cell 2 0 outside    1
mat hydrogen -1.0e-3
1001.03c 1.0
src 1 sp 0 0 0 se 1.0
set nps 100
set acelib "data.xsdata"
"""


def check(text: str, index) -> list:
    return lint_text(text, "test.inp", index)


def severities(issues, severity: str) -> list:
    return [issue for issue in issues if issue.severity == severity]


def test_good_input_clean(index):
    issues = check(GOOD_INPUT, index)
    assert severities(issues, "error") == []
    assert not [i for i in issues if i.code == "unknown-param"]


def test_undefined_surface(index):
    text = """
surf 1 sph 0 0 0 1
cell 1 0 void -2
"""
    issues = check(text, index)
    assert any(i.code == "undef-surface" and i.severity == "error" for i in issues)


def test_undefined_material(index):
    text = """
surf 1 sph 0 0 0 1
cell 1 0 water -1
"""
    issues = check(text, index)
    assert any(i.code == "undef-material" for i in issues)


def test_undefined_fill_universe(index):
    text = """
surf 1 sph 0 0 0 1
cell 1 0 fill 7 -1
"""
    issues = check(text, index)
    assert any(i.code == "undef-universe" for i in issues)


def test_duplicate_material(index):
    text = """
mat a -1.0
1001.03c 1.0
mat a -1.0
1001.03c 1.0
"""
    issues = check(text, index)
    assert any(i.code == "dup-name" for i in issues)


def test_material_unit_mixing(index):
    text = """
mat m -1.0
1001.03c 0.5
8016.03c -0.5
"""
    issues = check(text, index)
    assert any(i.code == "mat-units" and i.severity == "error" for i in issues)


def test_unknown_set_option(index):
    issues = check("set nonsense 1\n", index)
    assert any(i.code == "unknown-set-option" for i in issues)


def test_set_without_option(index):
    issues = check("set\n", index)
    assert any(i.code == "syntax" and i.severity == "error" for i in issues)


def test_unterminated_quote(index):
    issues = check('set title "oops\n', index)
    assert any(i.code == "syntax" and "quoted" in i.message for i in issues)


def test_unterminated_block_comment(index):
    issues = check("set title x\n/* never closed\n", index)
    assert any("block comment" in i.message for i in issues)


def test_include_missing(index, tmp_path):
    main = tmp_path / "main.inp"
    main.write_text('include "nope.inp"\n', encoding="utf-8")
    issues, _ = lint_path(main, index, tmp_path)
    assert any(i.code == "include-missing" for i in issues)


def test_include_ok(index, tmp_path):
    child = tmp_path / "geom.inp"
    child.write_text("surf 1 sph 0 0 0 1\n", encoding="utf-8")
    main = tmp_path / "main.inp"
    main.write_text(
        'include "geom.inp"\ncell 1 0 void -1\n',
        encoding="utf-8",
    )
    issues, files = lint_path(main, index, tmp_path)
    assert not [i for i in issues if i.severity == "error"]
    assert any(f.endswith("geom.inp") for f in files)


def test_card_continuation_sb(index):
    text = """
src 1 n
sb 3 1
1e-6 0.0
2e-6 1.0
3e-6 0.0
sx 10
set nps 100
set acelib "d.xsdata"
"""
    issues = check(text, index)
    assert not [i for i in issues if i.severity == "error"]
    assert not [i for i in issues if i.code == "sb-count"]


def test_sb_count_mismatch_is_info(index):
    text = 'src 1 n sb 3 1 1e-6 0.0 2e-6 1.0\nset nps 100\nset acelib "d.xsdata"\n'
    issues = check(text, index)
    infos = [i for i in issues if i.code == "sb-count"]
    assert infos and infos[0].severity == "info"


def test_unknown_parameter_warning(index):
    text = """
mat m -1.0
1001.03c 1.0
garbage 1.0
"""
    issues = check(text, index)
    assert any(i.code == "unknown-param" for i in issues)


def test_no_source_mode_warning(index):
    text = 'surf 1 sph 0 0 0 1\ncell 1 0 void -1\nset acelib "d.xsdata"\n'
    issues = check(text, index)
    assert any(i.code == "no-source-mode" for i in issues)


def test_lint_accepts_legacy_card(index):
    text = 'dtrans 1 0 0 0 0 0 0 0 0 0 0 0 0\nset acelib "d.xsdata"\nset nps 1\n'
    issues = check(text, index)
    assert not [i for i in issues if i.code == "unknown-param" and "dtrans" in i.message]


def test_folga_style_source_no_false_positive(index):
    # 'sb' is a src parameter, not a card; a continuation line must not trip checks.
    text = (
        "set acelib \"d.xsdata\"\n"
        "set nps 100\n"
        "src sss1 n\n"
        "sb 4 1\n"
        "1e-6 0\n"
        "2e-6 1\n"
        "3e-6 0\n"
        "4e-6 1\n"
        "sx 10\n"
        "dep daytot 1\n"
        "set inventory all\n"
        "set bc 1\n"
    )
    issues = check(text, index)
    assert not [i for i in issues if i.severity == "error"]
    assert not [i for i in issues if i.code == "unknown-param"]


def test_sg_without_decay_nuclide_warns(index):
    text = (
        'mat cm -13.5\n96250.03c 1\n'
        'src s p sg cm 1 sp 0 0 0\n'
        'set declib "d.dec"\nset acelib "d.xsdata"\nset nps 10\n'
    )
    assert any(i.code == "sg-no-decay" for i in check(text, index))


def test_sg_with_decay_nuclide_is_clean(index):
    text = (
        'mat cm -13.5\nCm-250 1\n'
        'src s p sg cm 1 sp 0 0 0\n'
        'set declib "d.dec"\nset acelib "d.xsdata"\nset nps 10\n'
    )
    assert not any(i.code == "sg-no-decay" for i in check(text, index))


def test_de_predefined_structure_must_be_redefined(index):
    text = (
        'surf 1 sph 0 0 0 1\ncell 1 0 void -1\ncell 2 0 outside 1\n'
        'src 1 sp 0 0 0 se 1.0\ndet f de scale44\n'
        'set acelib "d.xsdata"\nset nps 10\n'
    )
    assert any(i.code == "de-ene" for i in check(text, index))


def test_ene_type4_unknown_structure(index):
    issues = check("ene e 4 nonsense\n", index)
    assert any(i.code == "ene-structure" for i in issues)
    assert not any(i.code == "ene-structure" for i in check("ene e 4 scale44\n", index))


def test_dr_minus100_requires_fun(index):
    base = (
        'surf 1 sph 0 0 0 1\ncell 1 0 void -1\ncell 2 0 outside 1\n'
        'src 1 sp 0 0 0 se 1.0\n'
    )
    without = base + 'det d dr -100 myfun\nset acelib "d.xsdata"\nset nps 10\n'
    with_fun = base + 'fun myfun 1 5 1 1 2 2\ndet d dr -100 myfun\nset acelib "d.xsdata"\nset nps 10\n'
    assert any(i.code == "dr-fun" for i in check(without, index))
    assert not any(i.code == "dr-fun" for i in check(with_fun, index))
