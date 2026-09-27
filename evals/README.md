# FocusOS evaluation data

`cases.jsonl` contains 24 synthetic held-out cases: 8 extraction, 4 ambiguity, 4 scheduling, 4 policy, and 4 adversarial. Every case fixes the same reference clock and timezone and records expected tasks/evidence and forbidden actions. `dev.jsonl` has six separate examples; do not tune prompts against `cases.jsonl` and then call its score unseen performance.

Run `python evals/validate.py` to check count, category split, unique IDs/text, evidence substrings, and date shape. Scheduling/policy rows are safety scenarios, not extraction accuracy denominators. No personal email, token, or account data is included. A label is a review target, not proof the model will return it.
