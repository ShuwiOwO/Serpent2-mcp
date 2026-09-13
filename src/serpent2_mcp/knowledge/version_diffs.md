# Serpent version differences (curated)

The online documentation at serpent.vtt.fi/docs describes the **latest**
release (currently Serpent 2.2.5, doc version 0.21.0). Older installations can
differ. Use `get_environment` to see which version is actually installed, and
prefer conservative syntax when targeting more than one version.

| Feature | Change | Notes |
|---|---|---|
| Command-line options | Up to 2.2.1 only single dash (`-omp`, `-norun`). From 2.2.2 both `-` and `--` are accepted. | The server probes the executable and selects the right style. |
| `burn` parameter of `mat` | Before 2.2.2 the value could define sub-zone division for pin structures. From 2.2.2 the value must be `1`; use the `div` card. Fallback `2.2.2-001` re-enables the old behaviour. | Old inputs with `burn 2`, `burn 3`, … need `div` or a fallback option. |
| `mat fix ID0 T0` | Disabled in 2.2.2+ (decay nuclides no longer need it). Fallback `2.2.2-004`. | Rarely needed. |
| `dtrans` / `ftrans` | Obsolete; use `trans d` / `trans f`. | Still accepted by old versions. |
| Volume checking | `-checkvolumes` in ≤ 2.2.3; `--matvolumes` from 2.2.4; `--cellvolumes` and `--detvolumes` added in 2.2.4. | |
| Temperature units | `tmp`/`tms`/`tft` accept `K`, `C`, `F` suffixes from 2.2.4; without suffix the value is Kelvin. | |
| Geometry plots | `gplot` (extended) and `mplot` (extended mesh plot) are newer additions; older versions use `plot` and `mesh`. | Prefer `plot`/`mesh` for maximum compatibility. |
| Fallback options | `set fallback` and the `extra/fallbacks` list are a modern compatibility mechanism. | Not available in old versions. |
| Group constant automation | `branch`, `coef`, `casematrix`, `hisv` evolved over 2.2.x. | Check the syntax manual version. |
| `set coef` vs `set casematrix` | Case matrix replaces several older automation workflows. | |

## Pre-2.0 beta installations

Serpent 2 beta releases (before 2.0.0) predate most of the current syntax
manual. Known practical implications:

- CLI flags are single-dash; `--version` may not exist — run the executable
  without arguments to print usage/version.
- Extended cards (`gplot`, `mplot`, `datamesh`, `casematrix`, `hisv`) are
  absent. Use `plot`, `mesh`, `det`, basic `set` options.
- Input validation error messages use the same general format
  (`Input error in parameter ... on line ... in file ...`), but only the first
  error is reported.
- `%` comments and `/* */` blocks are supported, but old manuals should be
  consulted for obscure cards.
- When the docs of the installed version are unavailable, prefer the syntax
  patterns in `primer.md` (they are deliberately conservative) and validate
  with the actual binary via `validate_input` level 3.

Last reviewed against doc version 0.21.0 (Serpent 2.2.5).
