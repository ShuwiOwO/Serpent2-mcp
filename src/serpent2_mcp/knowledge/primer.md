# Serpent 2 quick reference (curated)

Serpent 2 is a continuous-energy three-dimensional Monte Carlo particle
transport code (neutrons, photons, coupled neutron–photon, burnup/activation).
It has no interactive input: everything is defined in text input files.

This reference is a curated summary. For any card or `set` option, prefer the
exact syntax returned by the `get_card` tool (it is generated from the official
input syntax manual). Target documentation: serpent.vtt.fi/docs.

---

## 1. How an input file is structured

- The input is a flat sequence of **input cards**. Cards are delimited by the
  next card name (or end of file), *not* by line breaks. One card may span any
  number of lines, and several cards may share a line.
- Card names are **case-insensitive**, order is free.
- Words are whitespace-separated; strings with whitespace must be quoted.
- Comments: `%` starts a comment to end of line; `/* ... */` is a block
  comment (not nestable). Comments do **not** end a card.
- Because card boundaries are detected by name, an argument must never equal a
  reserved card name (see `extra/reserved_card_names`). A mistyped card name
  silently becomes an extra argument of the previous card — check errors
  carefully.
- `include "FILE"` reads another file at that point (recursive; paths relative
  to the current file are recommended as full quoted paths).
- Geometry, materials, etc. may be defined in any order; references are
  resolved after the whole input is read.

Minimum working example (external source):

```
set title "Fictive hydrogen sphere"
surf 1 sph 0.0 0.0 0.0 1.0
cell 1 0 hydrogen -1
cell 2 0 outside    1
mat hydrogen -1.0E-3
1001.03c 1.0
src 1 sp 0 0 0 se 1.0
set nps 10000
set acelib "s2v0_jeff32.xsdata"
```

---

## 2. Simulation modes

| Mode | Trigger | Notes |
|---|---|---|
| Criticality (k-eff) | `set pop NPG NGEN NSKIP` | Source definition is optional; default initial source is a U-235 fission spectrum spread over fissile materials. |
| External source | `src` + `set nps NP [BTCH TBI]` | `src` defines the distribution; `set nps` sets the number of histories. |
| Burnup / activation | `dep` + `div` (+ `set rfw`/`set rfr`) | Requires `set declib` and often `set nfylib`. |
| Decay source | `src NAME ... sg MAT MODE` | Radioactive decay source, no external particles. |
| Group constants | `set gcu`, `set nfg`, `set fum` | Optionally automated: `branch`, `coef`, `casematrix`. |
| Coupled n–γ | `set ngamma` + `det NAME p` | Photon transport on/off via `set ngamma` / detector particle type. |
| Dynamics/transients | `tme` time-bin card, dynamic mode | See user guide. |

`set pop` and `set nps` are mutually exclusive.

---

## 3. Geometry (CSG)

### 3.1 Surfaces

```
surf NAME TYPE PAR1 PAR2 ...
```

Common types (see `extra/csg_surfaces` for all): `sph x0 y0 z0 r` (sphere),
`cylx/cyly/cylz x0 y0 z0 r` (infinite cylinder along axis), `px/py/pz d`
(plane), `plane A B C D`, `cuboid`/`rpp` (box), `cone`, `quadratic`.
Surface names may be numbers or identifiers.

### 3.2 Cells and universes

```
cell NAME UNI0 MAT [SURF1 SURF2 ...]
cell NAME UNI0 fill UNI1 [SURF1 SURF2 ...]
```

- A cell belongs to universe `UNI0` (0 = root universe).
- A **negative** surface entry means "inside that surface", **positive** means
  "outside". Combining several entries is a Boolean intersection; `|` is not
  supported — use separate cells or union via multiple cells in the same
  universe.
- `#NAME` (inside a cell's surface list) excludes the region of another cell.
- `MAT` may be `void` (empty) or `outside` (terminates the geometry; a cell
  filled with `outside` must cover the boundary).
- `fill UNI1` fills the cell with another universe (e.g. a lattice).

Rules of thumb: every point must be covered by exactly one cell; overlaps
cause fatal errors (or wrong results). Always add a root-universe cell filled
with `outside` for the world.

### 3.3 Lattices and nested structures

- `lat UNI0 TYPE X0 Y0 NX NY PITCH UNI1 ...` — square (type 1) and hexagonal
  (2, 3, …; 18 types total, see `extra/lattice_types`). Filling universes are
  listed row by row starting from the lowest level.
- `pin`, `nest`, `pbed` define pin-wise, nested and pebble-bed universes.
- `trans`, `transa`, `transb`, `transv` apply transformations; `strans`
  (legacy) transforms surfaces.

---

## 4. Materials

```
mat NAME DENS [moder THNAME ZA] [burn 1] [vol V] [mass M] [tmp T]
              [tms T] [tft TMIN TMAX] [rgb R G B]
              ZAID1 FRAC1 ZAID2 FRAC2 ...
```

- `DENS` sign convention: **positive = atomic density** in units of
  1e24 atoms/cm³; **negative = mass density** in g/cm³.
- Fractions follow the same sign convention: positive = atomic, negative =
  mass. **Never mix atomic and mass fractions in one material.** Compositions
  are normalized automatically.
- ZAID conventions: `92235.03c` (U-235, library/temperature id `.03c`),
  `1001.03c` (H-1), elemental `48000.03c` or aliases like `Cd-nat.03c`.
  Isomeric states: the isotope number has 400 added by convention in some
  libraries (e.g. `95642`); always prefer the identifiers from the used data
  library. Photon data use `.84p`.
- `burn 1` marks a burnable material (required for depletion).
- `tmp T` sets temperature in K (accepts `K`/`C`/`F` suffix from 2.2.4);
  `tms`/`tft` relate to target-motion-sampling.
- `moder` links nuclides to thermal scattering data declared with `therm`
  (`therm THNAME LIB` or `therm THNAME T LIB1 LIB2`); in the material use
  `moder THNAME [ZA]` (ZA restricts the data to one nuclide).
- `mix NAME MAT1 FRAC1 MAT2 FRAC2 ...` merges materials (no burnable
  materials allowed).
- `div MAT ...` must be used to sub-divide burnable materials into depletion
  zones; combine with `set mvol` (preferred) or `vol` to set volumes.

---

## 5. Sources (`src` card and its parameters)

```
src NAME [PART] [sw WGT] [sc CELL] [sm MAT] [su UNI] [ss SURF] [sp X Y Z]
    [sx XMIN XMAX] [sy YMIN YMAX] [sz ZMIN ZMAX] [srad RMIN RMAX]
    [sd U V W] [sa PHI] [se E] [sb NE INTT E1 F1 E2 F2 ...] [sr NUC MT]
    [st TMIN TMAX] [sf "FILE" TYPE] [so OP OD OE OW OT] [si NA ARG1 ...]
    [sg DMAT MODE]
```

| Parameter | Meaning |
|---|---|
| `sp X Y Z` | point source (cm) |
| `sc CELL` / `sm MAT` / `su UNI` | volume source in a cell/material/universe (`sm fiss` = all fissile) |
| `ss SURF` | surface source (sphere or z-axis cylinder; negative reverses direction) |
| `sx/sy/sz/srad` | spatial sampling limits (box/cylinder) |
| `sd U V W` / `sa PHI` | unidirectional vector / cone half-angle in degrees |
| `se E` | monoenergetic MeV (negative → Maxwellian; `-1.2895` generic fission, `-2.53E-8` thermal) |
| `sb NE INTT E1 F1 …` | tabulated energy spectrum; `NE` = number of points; `INTT`: 0=line, 1=histogram, 2=lin-lin, 4=log-lin; energies ascending, MeV; normalized automatically |
| `sr NUC MT` | energy sampled from a reaction of a nuclide (e.g. `sr 92235.09c 18`) |
| `sf "FILE" TYPE` | source particles read from a file (ASCII type 1 / binary type -1) |
| `sg DMAT MODE` | decay source for material (`-1` = all radioactive, MODE 1 analog / 2 implicit) |
| `sw` | relative weight for multiple sources |
| `st TMIN TMAX` | emission time interval (s) |

**Card continuation trap (important):** `sb` is a parameter, not a card. A
file may look like:

```
src sss1 n
sb 600001 1
1e-06 0.0
1.00002e-06 1.2
...
```

The `sb` data lines belong to the `src` card and continue until the next
reserved card name or EOF. Data lines must not *start* with a reserved card
name (e.g. `mat`, `set`, `cell`, `det`), or the parser will split the card.

### 5.1 Radioactive decay source (`sg`)

```
src NAME p|n sg DMAT MODE
```

- `DMAT`: material name or `-1` for all radioactive materials.
- `MODE`: 1 = analog (intensities), 2 = implicit (weights).
- The emitting nuclides must carry decay data. In photon decks the emitter is
  usually added as a **decay nuclide** (ZAI or element form without a library
  suffix), e.g. `Cm-250 1` or `270600 -4.776E-13`; a transport nuclide such as
  `96250.03c` has decay data but decays via the transport library and may show
  `Photon emission rate 0.00000E+00` in the output.
- Requires `set declib`; spontaneous-fission neutrons additionally require
  `set nfylib`.
- Serpent writes the emitted spectra to `INPUT_gsrc.m` / `INPUT_nsrc.m`. Their
  `mat_<MAT>_tot` and `tot` values are the physical emission rates used for
  `set srcrate` when the source is later replaced by a tabulated `sb` spectrum.

### 5.2 Building an `sb` spectrum from an emission spectrum

Typical procedure: run the decay-source case with a detector on the emission
spectrum (e.g. `det SPEC dr -11 void de GRID` and `ene GRID 4 <structure>`),
read the per-group emission from the detector output, divide by the group
widths to get a histogram source, and use those values as the `sb` table in a
second run with `set srcrate <tot>` from `_gsrc.m`/`_nsrc.m`. `ene` type 4
structures (e.g. `scale44`) are built in — see the appendix.

---

## 6. Data libraries

```
set acelib "PATH/to/xsdata"      % cross section directory file(s)
set declib "PATH/to/sss_endfb7.dec"
set nfylib "PATH/to/sss_endfb7.nfy"
set sfylib "..."                 % spontaneous fission yields (optional)
set bralib "..."                 % isomeric branching ratios (optional)
set pdatadir "..."               % photon physics data (photon transport)
```

Environment variables that can replace the corresponding options:
`SERPENT_DATA`, `SERPENT_ACELIB`, `SERPENT_DECLIB`, `SERPENT_NFYLIB`,
`SERPENT_RNG_SEED`, `SERPENT_OMP_NUM_THREADS`, `SERPENT_MEM_FRAC`.

Path rules (important):

- File names in `set acelib`/`set pdatadir`/... are resolved relative to the
  **working directory where `sss2` is started**, or given as absolute paths.
  Keeping inputs and the `xsdata/` directory under one workspace root and
  starting Serpent there lets you use short relative paths such as
  `set acelib "xsdata/data.xsdata"`.
- `SERPENT_DATA` sets the default search path for the data files referenced
  *inside* directory files; if it is not set, those entries must contain
  directory paths themselves.
- Directory files downloaded from the VTT repository reference data files as
  `/xs/data/...`. The server tools (`download_data_library`,
  `install_photon_data`, `check_data_paths`) rewrite these entries to the
  locally extracted files, relative to the workspace root when possible.
- Typical layout: `xsdata/` containing `data.xsdata`, `acedata/` (ACE files,
  including `mcplib84` for photon transport), `photon_data/` (physics data for
  `set pdatadir`), and `sss_endfb7.dec/.nfy`.

The `list_data_libraries` / `download_data_library` tools know the official
VTT data repository (ENDF/B-VII.1, JEFF-3.2, JENDL-4.0, FENDL-3.0 and others).

---

## 7. Physics and calculation options (frequently used `set` options)

| Option | Purpose |
|---|---|
| `set title "..."` | run title |
| `set egrid E` | unionized energy grid reconstruction tolerance (eV, default 1e-5, `0` = off) |
| `set ures 1` / `set ures 0 [Emin Emax]` | unresolved resonance probability table sampling |
| `set dbrc 1` | Doppler-broadening rejection correction (important for Th/U-233, Pu isotopes) |
| `set impl 0/1` | implicit capture / (n,xn) / fission (default 1) |
| `set delnu 1` | delayed neutrons |
| `set nphys ...` | neutron physics modes (e.g. fission sampling) |
| `set ecut E` | energy cut-off (eV for neutrons, MeV for photons) |
| `set bc ...` | boundary conditions (`set bc 2` reflective, `set bc 3` periodic, albedo etc.) |
| `set opti N` | optimisation mode |
| `set seed X0 [NB]` | random seed; `--replay` reuses the previous seed |
| `set repro ...` | reproducibility flags |
| `set memfrac F` | memory fraction (default 0.8) |
| `SERPENT_OMP_NUM_THREADS` / CLI `--omp M` | OpenMP thread count (not a `set` option) |
| `set gcu UNI ...` | universes for group constant generation (`set gcu -1` = all) |
| `set nfg GROUPS` | macro-group structure (number or named `ene` grid) |
| `set fum ...` / `set micro ...` | critical spectrum / micro-group structure |
| `set coef ...`, `branch`, `casematrix` | automated group constant sequence |
| `set nps NP [BTCH TBI]` | external source histories (batches) |
| `set pop NPG NGEN NSKIP [K0 BTCH NCRIT]` | criticality population / generations (active) / skipped cycles |
| `set power P` / `set powdens PD` | burnup normalization (power W or kW/g) |
| `set inventory ...` | nuclides in burnup output |
| `set rfw 1 "FILE"` / `set rfr ...` | write/read restart file for burnup |
| `set printm 1` | write burned material compositions |
| `set mvol MAT ZIDX VOL ...` | material volumes for burnup/detectors (`ZIDX` = 0 for the whole material) |
| `set dataout ...`, `set depout ...`, `set deppara ...` | output trimming |
| `set pcc ...`, `set bumode ...`, `set xscalc ...` | burnup solver options |
| `set xenon 1` / `set samarium 1` | equilibrium poisons |
| `set ngamma ...` | coupled neutron–photon transport |
| `set edepmode ...`, `set edepdel ...` | energy deposition modes |

Exact syntax, defaults and version notes: use `get_card` for each option.

---

## 8. Detectors

```
det NAME [PART] [dv VOL] [dt OPT...] [dhis TST] [da AMAT FLX] [dc CELL]
    [dm MAT] [du UNI] [dl LAT] [dtl TSURF] [dx XMIN XMAX NX] [dy ...] [dz ...]
    [dn TYPE ...] [dh TYPE ...] [dumsh UMSH ...] [dmesh MESH] [ds SURF DIR]
    [dr MT RMAT] [de EGRID] [di TBIN] [df FILE FRAC] [dfl FLG FOPT]
    [dfet FTYPE ...] [dphb PHB]
```

- `PART` = `n` (default) or `p` for photons in coupled runs.
- Response/quantity is chosen with `dr MT RMAT` (reaction MT for material;
  pre-defined totals such as `-1` flux-like reactions depending on context;
  see `extra/endf_reactions`) or activation detector via `da AMAT FLX`.
- Spatial domain: volume (`dc`/`dm`/`du`/`dl`/`dv`), Cartesian mesh
  (`dx/dy/dz`), curvilinear (`dn`), hexagonal (`dh`), unstructured (`dumsh`),
  or data mesh (`dmesh`); surface (`ds`), surface current (`dtl`).
- Energy domain: `de EGRID` with an `ene` grid; time domain: `di TBIN` with a
  `tme` structure.
- Detector results are **integrals** over the domain, not averages.

Detector output file: `INPUT_detN.m` (N = burnup/dynamic step or VR
iteration). Results table `DET[NAME]` has the columns
`EBI UBI CBI MBI LBI RBI XBI YBI ZBI MEAN ERR` (13 columns with `TBI` first
when time bins are used). Bin boundaries are in `DET[NAME]E`, `DET[NAME]T`,
`DET[NAME]X/Y/Z`, etc. `MEAN` is the result and `ERR` its relative
statistical error; `-1` marks an unavailable error.

---

## 9. Burnup and activation

```
dep bustep STP1 STP2 ...        % incremental burnup steps (MWd/kgU)
dep butot STP1 STP2 ...         % cumulative burnup steps (MWd/kgU)
dep daystep STP1 ...            % incremental time steps (days)
dep daytot STP1 ...             % cumulative time steps (days)
dep decstep STP1 ...            % decay steps (days, no transport)
dep dectot STP1 ...             % cumulative decay steps (days)
dep actstep STP1 ...            % activation steps (reaction rates kept)
dep acttot STP1 ...             % cumulative activation steps
div MAT [sep LVL] [subx ...] [suby ...] [subz ...] [subr ...] [subs ...]
```

- Mark depleted materials with `burn 1`.
- Normalization: `set power P` (W) or `set powdens PD` (kW/g), or `set srcrate`.
- Set volumes (`set mvol` preferred; verify with `--matvolumes N`).
- Output: `INPUT_dep.m` (Matlab tables per material: `ADENS`, `MDENS`, `A`,
  `H`, `SF`, `GSRC`, toxicities; vectors `ZAI`, `NAMES`, `BU`, `DAYS`),
  binary `INPUT.dep` (use `--rdep` to regenerate output without rerunning),
  restart `INPUT.wrk` with `set rfw`.
- `set inventory` selects nuclides for output; `-rdep` reprints with a new
  inventory.

---

## 10. Geometry and mesh plots

```
plot AX NX NY [SYM ...]         % legacy, produces PNG
gplot [name NAME] [ax AX] [pos POS] [box XMIN XMAX YMIN YMAX] [pix NX NY] ...
mesh AX NX NY [SYM XMIN XMAX ...]   % reaction-rate map
mplot NAME [ax AX] [dsc DET CMAP] [lim FMIN FMAX] ...
```

Plots are written as PNG files during processing (`--plot` stops after plots;
`--noplot` skips them; `--qp` quick mode ignores overlaps).

---

## 11. Running Serpent (command line)

```
sss2 INPUT [options]
```

Frequent options (single-dash forms exist in Serpent ≤ 2.2.1; both accepted
from 2.2.2):

| Option | Meaning |
|---|---|
| `--version` | print version and exit |
| `--norun` | process input, build geometry, stop before transport — the fastest full validation |
| `--noplot` / `--plot` | skip plots / stop after plots |
| `--omp M` | OpenMP threads |
| `--mpi N` | MPI tasks (requires MPI build) |
| `--matvolumes N` / `--cellvolumes N` / `--detvolumes N` | Monte Carlo volume check |
| `--replay` | reproduce previous random seed |
| `--matpos X Y Z` | print geometry/material at a position |
| `--elem MAT DENS` / `--mix` | decompose elemental/mixture compositions |
| `--checkstl N M` | check STL geometry for holes |
| `--ip` | interactive command-line plotter |
| `--nofatal` | ignore fatal errors (use with care) |
| `--rdep` | reprint burnup output from binary file |
| `--rfw` | write restart file and stop |

Run-time output goes to **stdout** (not a file); redirect it yourself.
Input errors look like:

```
Input error in parameter "cell" on line 8 in file "geometry.inp":
Surface s1 is not defined
```

Serpent stops at the first input error; fix and rerun. Fatal errors during
transport are bugs or geometry problems — check `set` options and geometry.

---

## 12. Output files

| File | Content |
|---|---|
| stdout | run-time log (batch/generation progress, warnings, errors) |
| `INPUT.out` | processing-stage data: nuclides, reactions, material data |
| `INPUT_res.m` | standard results (Matlab): k-eff, balances, rates, times, group constants |
| `INPUT_detN.m` | detector results (N = step index) |
| `INPUT_dep.m` | burnup inventory tables |
| `INPUT.dep` | binary depletion data (`--rdep`) |
| `INPUT_hisN.m` | history/batch-wise statistical data |
| `INPUT_gsrc.m`, `INPUT_nsrc.m` | photon/neutron emission spectra of a decay source (`sg`), with total emission rates |
| `INPUT_mdxN.m` | micro-depletion output (`set mdep`) |
| `INPUT.coe` | automated group constant sequence |
| `INPUT.wrk` | restart file (`set rfw` / `--rfw`) |
| `INPUT.bumatN` | burned material compositions (`set printm`) |
| `INPUT.seed` | random seed for `--replay` |

In `_res.m`, statistical results are printed as **mean and relative error**;
vectors/matrices with multiple rows correspond to burnup/dynamic/VR steps
(one row per simulation). Group constant variables are prefixed `INF_`, `B1_`
etc.; detectors are also stored as `DET[NAME]`.

---

## 13. Common pitfalls

1. **Card continuation**: a missing/typo'd card name merges its arguments into
   the previous card (often producing "Input error in parameter ..." with a
   confusing line number). Always write one card per logical block and avoid
   reserved names as identifiers.
2. **Units**: distances cm, energies MeV, burnup MWd/kgU, time days in `dep`,
   atomic density 1e24/cm³ vs mass density g/cm³ (sign matters).
3. **Geometry overlaps/gaps**: each point must belong to exactly one cell;
   add a world cell filled with `outside`; use `--plot` and `--matvolumes`.
4. **Burnable volumes**: missing/incorrect volumes ruin burnup results; use
   `set mvol` or `vol` and verify.
5. **`burn 1` without `div`**: depletion zones are not sub-divided
   automatically in modern versions; add `div` for each burnable material.
6. **Missing data libraries**: `set acelib` is mandatory unless
   `SERPENT_ACELIB`/`SERPENT_DATA` is set.
7. **Old versions**: single-dash CLI options, `mat fix`, `burn` semantics and
   some cards changed over time. Check the detected version with
   `get_environment` and consult `version_diffs.md` in the server repository.

---

## Appendix A. Pre-defined energy group structures (`ene` type 4)

```
ene NAME 4 STRUCTURE        % e.g. ene e 4 scale44
```

The structure is selected by name (built into the code); a `_ext` suffix gives
the version spanning all energies (0 ... infinity). Pre-defined structures
cannot be used directly in detectors — redefine them with an `ene` card first.
Use the `list_energy_structures` tool or `get_reference('energy-structures')`
for the full list. Common names: `scale44` (44 groups), `scale56`,
`scale238`, `scale252`, `default2`, `defaultmg` (70), `nj17`/`nj19`,
`cas2`/`cas3`, `wims*`, `sfr24g`/`sfr240g`.

## Appendix B. Special (negative) response numbers

Negative reaction numbers select special macroscopic responses for detectors:
`-1` total flux, `-2` total cross section, `-4` capture, `-6` total absorption,
`-8` fission power, `-9` total energy production, and other values listed in
`extra/endf_reactions`. `-100 NAME` selects a user-defined response declared
with a `fun` card (`fun NAME 1 5 E1 F1 E2 F2 ...`); without the matching `fun`
card the detector fails at input processing.
