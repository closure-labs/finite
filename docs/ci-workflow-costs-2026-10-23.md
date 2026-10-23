# Workflow cost observation

Observed at 2026-10-23T03:55:00+00:00.

| Window | Category | Profile | Runs | Jobs | Runner seconds | Median job seconds | Queue seconds |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| baseline | merge_queue | finite | 23 | 23 | 27037.0 | 586.0 | 60.0 |
| baseline | merge_queue | finite-dev | 23 | 23 | 31258.0 | 798.0 | 63.0 |
| baseline | merge_queue | shared_or_unknown | 165 | 665 | 80088.0 | 7.0 | 1521.0 |
| baseline | other | finite | 12 | 12 | 4624.0 | 349.0 | 33.0 |
| baseline | other | finite-dev | 3 | 3 | 1228.0 | 199.0 | 9.0 |
| baseline | other | shared_or_unknown | 705 | 1439 | 118564.0 | 38.0 | 45754.0 |
| baseline | publication | finite | 26 | 228 | 86900.0 | 76.5 | 2348.0 |
| baseline | publication | finite-dev | 27 | 232 | 104144.0 | 76.5 | 2072.0 |
| baseline | publication | shared_or_unknown | 122 | 1123 | 346907.0 | 23.0 | 13174.0 |
| baseline | pull_request | finite | 36 | 36 | 39146.0 | 605.0 | 130.0 |
| baseline | pull_request | finite-dev | 36 | 36 | 48343.0 | 775.0 | 108.0 |
| baseline | pull_request | shared_or_unknown | 350 | 1333 | 127981.0 | 7.0 | 6453.0 |
| baseline | recovery | finite | 2 | 20 | 7675.0 | 80.0 | 73.0 |
| baseline | recovery | finite-dev | 3 | 28 | 7700.0 | 91.5 | 80.0 |
| baseline | recovery | shared_or_unknown | 15 | 60 | 12403.0 | 20.0 | 406.0 |
| baseline | scheduled | finite | 17 | 57 | 9048.0 | 54.0 | 797.0 |
| baseline | scheduled | finite-dev | 17 | 58 | 15572.0 | 62.0 | 1384.0 |
| baseline | scheduled | shared_or_unknown | 147 | 442 | 75689.0 | 52.0 | 1220.0 |

Seven-day observation complete: false.

- Runner seconds are elapsed occupancy, not billed cost; active work is right-censored.
- Shared jobs are reported separately; skipped jobs count with zero runner time.
- Native step times include setup and post-job handling; composite cache restore/save substeps are not exposed.
- Internal download retries, inventory eligibility/hits, candidate digests and exact runner/tool versions require retained producer receipts; unknown values are not zero or cache misses.
- Qualification eligibility is observed from context-tool execution; hits require the conditional reused-evidence upload.
- No percentile estimates; sample counts accompany medians. Reports grant no approval authority.
