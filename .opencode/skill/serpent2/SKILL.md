---
name: serpent2
description: Use when writing, validating, running or analysing Serpent 2 Monte Carlo inputs (sss2, input cards, set acelib, criticality/burnup, detectors, _res.m results, decay sources, dose calculations). Covers all simulation modes and the serpent_* MCP tools.
---

# Serpent 2 (Monte Carlo transport)

Serpent 2 is a continuous-energy 3-D Monte Carlo neutron/photon transport code
(VTT). Input is a text file of whitespace-separated **cards**; a card ends when
the next card name appears (lines do not matter), so one card may span many
lines. Cards are case-insensitive. Comments: `%` to end of line and `/* ... */`
blocks. Arguments must never equal a reserved card name.

## Working rules (follow these before anything else)

1. **Read the task literally.** If the user provides a reference input,
   previous-task file, or an exact method (geometry, source type, detector
   response, normalisation), open those files and follow them exactly. Do not
   substitute a different method (e.g. another dose response, another source
   type, another geometry) unless the user explicitly asks for it.
2. **Never guess syntax.** Call `serpent_get_card("<card>")` before using a card
   or parameter you are not 100% sure about; use `serpent_search_docs` when the
   meaning is unclear (e.g. decay sources, group structures, special response
   numbers). `serpent_get_reference` gives the curated summary.
3. **Smoke first, then scale.** Validate the input (`serpent_validate_input`,
   level 3 uses `sss2 --norun`) and run a tiny case (small `set nps`, or
   `--norun`) before a long calculation. Start long runs with `serpent_run`
   (background job) and poll `serpent_job_status`; never wait synchronously.
4. **Verify every run.** Check `_res.m` (`serpent_get_results`:
   `TOT_SRCRATE`, `NORM_COEF`, k-eff), detector files (`_det*.m`), and for
   decay sources `_gsrc.m`/`_nsrc.m` (their `tot` value is the physical
   emission rate for `set srcrate`). Report numbers with their errors; if a
   detector is empty or the source rate is zero, fix the input instead of
   changing the method.
5. **Respect the installed version.** `serpent_get_environment` shows the
   version and warns when it is older than the documentation. Old versions
   (2.1.x) use single-dash CLI flags (handled automatically), and some syntax
   differs — verify with `sss2 --norun`.

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
set acelib "data.xsdata"
```

External source:

```
src 1 sp 0 0 0 se 14.1
src 2 sp 0 0 0 sb 3 1 1e-6 0.0 1e-4 1.0 2e1 0.0
set nps 100000 50
```

Decay source (`sg`) — emitting nuclides need decay data (ZAI or element form
without a library suffix, e.g. `Cm-250` or `270600`), plus `set declib`:

```
mat curium -13.5 vol 0.5
Cm-250 1
src isotope p sg -1 1
set declib "sss_endfb7.dec"
set nfylib "sss_endfb7.nfy"   % spontaneous-fission neutrons
```

Geometry rules: in a `cell` list, `-s` = inside surface `s`, `+s`/bare `s` =
outside, `#cell` = complement of another cell; `fill UNI` fills with a
universe; a root cell with `outside` must close the geometry. Check overlaps
with `--plot` / `--matvolumes`.

Materials: `DENS` and fractions are **atomic** when positive and **mass** when
negative (1e24/cm³ vs g/cm³); never mix signs. `burn 1` marks a depleted
material; add `div MAT ...` and `set mvol` for burnup. ZAID: `92235.03c`,
`1001.03c`, natural `48000.03c`; decay nuclides can be written as `Cm-250` or
`270600`. Photon transport uses `.84p` data (e.g. `H.84p`, or `H-nat.84p`).

Units: cm, MeV, days, MWd/kgU; temperatures in K.

## Frequently needed facts

- **Energy grids**: `ene NAME 4 scale44` selects a built-in group structure
  (also `scale56`, `scale238`, `default2`, `nj17`, ...; `_ext` spans all
  energies). Structures cannot be used directly in detectors — redefine them
  with `ene` first. Use `serpent_list_energy_structures`.
- **Special responses**: negative `dr` numbers select special responses
  (`-1` flux, `-6` absorption, `-9` energy production, ...); `-100 NAME` uses a
  user-defined `fun` card. See the ENDF reaction appendix.
- **Normalisation**: `set srcrate`, `set power`, `set powdens`, `set acti`
  link results to physical rates; `TOT_SRCRATE`/`NORM_COEF` in `_res.m`.
- **Data layout**: all library paths live under one directory
  (`xsdata/`); directory files (`*.xsdata`) use absolute paths after setup.
  Stable aliases `data.xsdata`, `data.dec`, `data.nfy` are created.

## Common mistakes

- A typo in a card name silently merges the text into the previous card → the
  error line points at the wrong place.
- Data lines of a multi-line card (e.g. the `sb` spectrum inside `src`) must
  not start with a reserved name (`mat`, `cell`, `set`, `det`, ...).
- Missing `set acelib` (or `SERPENT_ACELIB`); missing `set nps`/`set pop`.
- `sg` source on a material with no decay-only nuclides → zero emission rate.
- Pre-defined energy structure used directly in `de` → input error.
- `dr -100` without the matching `fun` card.
- Mixing atomic and mass fractions in one material is forbidden.

When results are missing or look wrong, inspect the job log first
(`serpent_job_output`) and the detector/source output files before changing
the physical model.
