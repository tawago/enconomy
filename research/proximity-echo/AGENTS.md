# Proximity-Echo experimental workflow

The user explicitly chose to remove automated tests during this experimental phase.

- Do not add, restore, or run automated test suites, regression suites, synthetic self-tests, test fixtures, commit test hooks, or test gates unless the user explicitly requests them.
- Use lightweight syntax, compilation, or import checks after code changes. `./run.sh check` checks syntax; `./run.sh serve` checks syntax and starts the server.
- Keep implementation checks proportional to the change. Do not claim a syntax check validates signal processing or physical accuracy.
- Analysis of saved recordings and user-run physical experiments remains the core development workflow. Preserve original WAVs, metadata, reports, and scientific findings.
- Runtime input validation, capture-quality checks, and INCONCLUSIVE decisions are measurement logic, not automated tests. Keep them unless the algorithm task explicitly calls for changing them.
- Historical documents may mention removed suites or test commands. This current workflow supersedes those instructions. Do not recreate test machinery to satisfy an older plan.
