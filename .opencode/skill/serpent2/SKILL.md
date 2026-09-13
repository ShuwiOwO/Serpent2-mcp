---
name: serpent2
description: Use when writing, validating, running or analysing Serpent 2 Monte Carlo inputs (sss2, input cards, set acelib, criticality/burnup, detectors, _res.m results). Covers all simulation modes and the serpent_* MCP tools.
---

# Serpent 2 (Monte Carlo transport)

Serpent 2 is a continuous-energy 3-D Monte Carlo neutron/photon transport code
written by VTT. Input is a text file of whitespace-separated **cards**; a card
ends when the next card name appears (lines do not matter), so one card may
span many lines. Cards are case-insensitive. Comments: `%` to end of line and
`/* ... */` blocks. Arguments must never equal a reserved card name.

## Mandatory workflow

1. `serpent_get_reference("")` once per task if you have not read it — it
   contains the full curated syntax summary (geometry, materials, sources,
   detectors, burnup, output files, pitfalls).
2. For every card/option beyond the basics, call `serpent_get_card("<name>")`
   (e.g. `surf`, `set acelib`, `sb`) — never guess syntax.
3. Write the input with normal file tools, then `serpent_validate_input`.
   Fix all errors before running.
4. `serpent_run` starts a **background** job and returns a job id. Poll
   `serpent_job_status`, read `serpent_job_output`, stop with `serpent_job_kill`.
5. Analyse with `serpent_get_results` (`_res.m` k-eff/balances, `_det.m`
   detectors, `_dep.m` burnup) and `serpent_plot_results` for PNG plots.
6. `serpent_get_environment` shows the executable, version and data paths.
   Missing cross sections can be fetched with `serpent_list_data_libraries` /
   `serpent_download_data_library`.

## Minimal input patterns

Criticality:

```
set title "case"
surf fuel_r cylz 0 0 0.4
surf clad_r cylz 0 0 0.46
cell fuel  0 fuel  -fuel_r
cell clad  0 zirc  -clad_r fuel_r
cell out   0 void   clad_r
cell world 0 outside
mat fuel -10.0
92235.03c -0.04
92238.03c -0.85
8016.03c  -0.11
set bc 2
set pop 5000 100 300
set acelib "PATH/data.xsdata"
```

External source:

```
src 1 sp 0 0 0 se 14.1
src 2 sp 0 0 0 sb 3 1 1e-6 0.0 1e-4 1.0 2e1 0.0
set nps 100000 50
```

Geometry rules: in a `cell` list, `-s` = inside surface `s`, `+s`/bare `s` =
outside, `#cell` = complement of another cell; `fill UNI` fills with a
universe; a root cell with `outside` must close the geometry. Check overlaps
with `--plot` / `--matvolumes`.

Materials: `DENS` and fractions are **atomic** when positive and **mass** when
negative (1e24/cm³ vs g/cm³); never mix signs. `burn 1` marks a depleted
material; always add `div MAT ...` and `set mvol MAT ZIDX VOL` for burnup.
ZAID: `92235.03c`, `1001.03c`, natural `48000.03c`/`Cd-nat.03c`.

Units: cm, MeV, days, MWd/kgU; temperatures in K (suffixes K/C/F accepted in
newer versions).

## Run and validate

- CLI: `sss2 INPUT [options]`; `--norun` stops after input processing (fast
  validation), `--noplot`, `--omp N`, `--mpi N`, `--matvolumes N`, `--replay`,
  `--plot`. Serpent ≤ 2.2.1 uses single-dash options.
- Input errors look like:
  `Input error in parameter "cell" on line 8 in file "geometry.inp": ...`
- Runtime log goes to stdout; results to `INPUT_res.m`; detectors to
  `INPUT_detN.m`; depletion to `INPUT_dep.m` + binary `INPUT.dep`; restart
  `INPUT.wrk`; seed `INPUT.seed`.

## Common mistakes

- A typo in a card name silently merges the text into the previous card → the
  error line points at the wrong place.
- Data lines of a multi-line card (e.g. the `sb` spectrum inside `src`) must
  not start with a reserved name (`mat`, `cell`, `set`, `det`, ...).
- Missing `set acelib` (or `SERPENT_ACELIB`); missing `set nps`/`set pop`.
- Burnable material without `burn 1`, `div` or volumes → wrong burnup.
- Mixing atomic and mass fractions in one material is forbidden.

When results are missing, inspect the job log first: `serpent_job_output`.
