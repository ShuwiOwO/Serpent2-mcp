# Project rules for working with Serpent 2

When a task involves the Serpent 2 Monte Carlo code (`sss2`), writing or
editing input files, running calculations, or interpreting `_res.m`/`_det.m`/
`_dep.m` output:

- Use the `serpent_*` MCP tools: `serpent_get_reference` and
  `serpent_get_card` for syntax, `serpent_validate_input` before runs,
  `serpent_run` + `serpent_job_*` for background calculations,
  `serpent_get_results` and `serpent_plot_results` for analysis.
- Never guess input card syntax — fetch it with `serpent_get_card`.
- Do not wait synchronously for long calculations; poll the job status.
