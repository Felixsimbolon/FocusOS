# FocusOS evaluation data

`cases.jsonl` contains 24 synthetic held-out cases: 8 extraction, 4 ambiguity, 4 scheduling, 4 policy, and 4 adversarial. Every case fixes the same reference clock and timezone and records expected tasks/evidence and forbidden actions. `dev.jsonl` has six separate examples; do not tune prompts against `cases.jsonl` and then call its score unseen performance.

Run `python evals/validate.py` to check count, category split, unique IDs/text, evidence substrings, and date shape. Scheduling/policy rows are safety scenarios, not extraction accuracy denominators. No personal email, token, or account data is included. A label is a review target, not proof the model will return it.


`python evals/run.py --dry-run` validates and writes 16 `skipped` observations to ignored `evals/output/`; it never claims a model score. `python evals/run.py --live` is opt-in and requires `FOCUSOS_OPENAI_API_KEY` in the local process environment. It calls `focusos_api.extractor.extract_structured` with each case's fixed clock/zone. Output includes versions, status/failure code, latency, usage, task title/date, and SHA-256 evidence fingerprints. It excludes source body, raw evidence, credentials, and provider response. Scheduling/policy rows are evaluated by safety tests, not this extraction runner.
