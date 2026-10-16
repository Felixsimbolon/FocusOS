# FocusOS extraction evaluation

Cases: 16 extraction/ambiguity/adversarial; 8 scheduling/policy safety cases excluded.
Completed: 0/16; failed: 0/16; skipped: 16/16.
Historical dry-run model/prompt/schema versions: gpt-4.1-mini/1/1. Current Gemini code uses gemini-3.5-flash-lite/2/1; rerun the evaluator before claiming a new score.

No live model result is available. Accuracy is **not measured**; dry-run records are not scored.

Limitations: synthetic held-out source text; task matching first uses normalized exact titles, then explicit reviewer judgments. No live Gmail, Calendar write, or scheduling score is implied.

$secret = Read-Host "Gemini API key" -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
try { $env:GEMINI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
npm.cmd run dev:api


# Memory retrieval and grounded answers (`evals/qa_eval.py`)

Synthetic workspace in `evals/qa_corpus.json` (18 tasks, 35 memories, 5 FocusOS Calendar blocks, fixed clock 2026-10-14 09:00 Asia/Jakarta) and 55 questions in `evals/qa_cases.jsonl`. The corpus deliberately holds look-alike facts (two contracts, Q3/Q4/travel budgets, office vs home Wi-Fi, two workshops, two streaming subscriptions) so retrieval must tell them apart. Questions cover memory, task and Calendar lookups, 7 cross-language paraphrases, one answer that needs two memories, and 14 unanswerable near-misses (for example the home Wi-Fi password when only its name is saved). Each case lists the references that must be cited, references that may also be cited, and words a correct answer contains.

Retrieval compares four strategies, ported from SQL to Python: `legacy` (the pre-2026-10-14 search, effectively semantic top-5), `lexical`, `semantic` (live only) and `hybrid` (reciprocal-rank fusion, constant 60). Metrics: recall@k and MRR over expected memories, precision@k over expected or acceptable memories, and `returned` (memories sent to the answer model per question). Answers run through the real `answer_questions` with the database patched to the corpus. Metrics: pass rate, status accuracy, citation precision/recall, keyword hit, and **false answer rate** (answering an unanswerable question). `--judge` adds an LLM-as-judge faithfulness rate, reported separately because the judge is the same model family. Live runs retry a provider 503 up to three times; what still fails is reported as `unavailable`, not as a wrong answer.

Mock baseline (2026-10-16, k=8, no provider calls, oracle answer model, so not a Gemini score):

| Retrieval | recall@8 | MRR | precision@8 | missed |
|---|---|---|---|---|
| legacy | 0.91 | 0.83 | 0.22 | q15, q16, q18 |
| lexical / hybrid (no vectors) | 0.88 | 0.79 | 0.43 | q15, q18, q39, q40 |

Answers (oracle): pass 0.93, false answer rate 0.00. The failures are cross-language paraphrases that keyword search cannot find. CI floors: hybrid recall ≥ 0.85, precision ≥ 0.40, oracle pass ≥ 0.9, false answers = 0.

**Live baseline (2026-10-16, gemini-3.5-flash-lite + gemini-embedding-2/256, k=8, semantic floor 0.2):**

| Retrieval | recall@8 | MRR | precision@8 | returned |
|---|---|---|---|---|
| legacy | 1.00 | 0.99 | 0.24 | 5.0 |
| lexical | 0.88 | 0.79 | 0.43 | 3.0 |
| hybrid | 1.00 | 0.91 | 0.15 | 8.0 |
| semantic | 1.00 | 0.99 | 0.15 | 8.0 |

Answers: pass 0.93, status accuracy 0.96, citation precision 0.96, recall 0.98, **false answers 0.00**, judge-supported 0.95, 2 provider 503s (before the runner retried). Findings:
- The semantic floor 0.2 filtered nothing: sweeps from 0.2 to 0.5 were identical and every question sent 8 memories. Cosine on the cached vectors: relevant memories 0.67–0.88, unrelated 0.33–0.82 (median 0.55). At 0.6 every relevant memory stays and 19% of unrelated ones pass (vs 81% at 0.5); at 0.7 recall drops to 0.86. The SQL floor moved to 0.6 (migration `20261016090000`). The best score on unanswerable questions reached 0.79, so the floor cannot decide "no reference"; the cited-answer contract does.
- Hybrid did not beat the old search on this corpus (MRR 0.91 vs 0.99). It is kept because recall is equal and exact names and codes match by keyword; no accuracy gain is claimed.
- The judge caught a real defect (q45): given two raw ISO timestamps, the model wrote the wrong end date. Calendar references now reach the model as one local range ("Friday 2026-10-16, 14:00–15:30 (Asia/Jakarta)").
- q46 (add two budgets) lists both figures but does not sum them; it is kept as a failing case.

```powershell
.\.venv\Scripts\python.exe evals/qa_eval.py --live --judge
.\.venv\Scripts\python.exe evals/qa_eval.py --live --sweep   # semantic floors 0.2-0.75, retrieval only
```

Embeddings are cached in ignored `evals/output/qa_embeddings.json`, so configuration sweeps reuse vectors and only pay for answer calls.
