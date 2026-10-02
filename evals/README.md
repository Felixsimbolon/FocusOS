# FocusOS evaluation data

`cases.jsonl` contains 24 synthetic held-out cases: 8 extraction, 4 ambiguity, 4 scheduling, 4 policy, and 4 adversarial. Every case fixes the same reference clock and timezone and records expected tasks/evidence and forbidden actions. `dev.jsonl` has six separate examples; do not tune prompts against `cases.jsonl` and then call its score unseen performance.

Run `python evals/validate.py` to check count, category split, unique IDs/text, evidence substrings, and date shape. Scheduling/policy rows are safety scenarios, not extraction accuracy denominators. No personal email, token, or account data is included. A label is a review target, not proof the model will return it.


`python evals/run.py --dry-run` validates and writes 16 `skipped` observations to ignored `evals/output/`; it never claims a model score. `python evals/run.py --live` is opt-in and requires `GEMINI_API_KEY` in the local process environment. It calls `focusos_api.extractor.extract_structured` with each case's fixed clock/zone. Output includes versions, status/failure code, latency, usage, task title/date, and SHA-256 evidence fingerprints. It excludes source body, raw evidence, credentials, and provider response. Scheduling/policy rows are evaluated by safety tests, not this extraction runner.


Run `python evals/score.py` after the runner. The scorer requires one observation per extraction case, matches tasks one-to-one by normalized exact title, then uses optional reviewer judgments from ignored `evals/output/judgments.jsonl` (`case_id`, `observed_title`, `expected_title`, `equivalent`: boolean). Record a judgment only after reading the synthetic case and output. Missing or failed outputs count as misses; `skipped` records never produce an accuracy claim. The report states task match, exact deadline and evidence fingerprint counts, versions, case failures, and limitations. `docs/evaluation.md` is the current static, unmeasured baseline until a live key is available.


`python evals/safety_gate.py` runs the named provider-mocked agent, approval, Calendar write, and audit regression suites. It checks denied tools, bounded continuation, stale permissions, unapproved writes, one claim winner, timeout reconciliation, and unknown outcomes independently of extraction quality. It does not assert a real provider event was created.


## Planning regression and synthetic live evaluation

Run `python evals/planning_eval.py --mock` for eight deterministic backend cases with fixture model selections. This is regression coverage, not model accuracy. Run `python evals/planning_eval.py --live` only with `GEMINI_API_KEY` configured privately to exercise Gemini on the same synthetic tasks. Both modes compile against a synthetic Calendar and never write real events. Results, model/prompt/schema versions, and denominators are saved to ignored `evals/output/planning.json`. See [planning hardening](../docs/planning-hardening.md).
