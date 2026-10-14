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

Synthetic workspace in `evals/qa_corpus.json` (8 tasks, 15 memories, 3 FocusOS Calendar blocks, fixed clock 2026-10-14 09:00 Asia/Jakarta) and 24 questions in `evals/qa_cases.jsonl`: 11 memory, 3 task, 1 Calendar, 3 cross-language paraphrases, 6 unanswerable distractors (for example the Wi-Fi password when only the network name is saved). Each case lists the references that must be cited, references that may also be cited, and words a correct answer contains.

Retrieval compares four strategies, ported from SQL to Python: `legacy` (the pre-fix search: semantic ≥ 0.2 first, then every memory because `ts_rank` gives non-matching rows 1e-20), `lexical`, `semantic` (live only) and `hybrid` (reciprocal-rank fusion, constant 60). Metrics: recall@k and MRR over expected memories, precision@k over expected or acceptable memories. Answers run through the real `answer_questions` with the database patched to the corpus. Metrics: pass rate, status accuracy, citation precision/recall, keyword hit, and **false answer rate** (answering an unanswerable question). `--judge` adds an LLM-as-judge faithfulness rate in live mode, reported separately because the judge is the same model family.

Mock baseline (2026-10-14, k=8, no provider calls, oracle answer model, so not a Gemini score):

| Retrieval | recall@8 | MRR | precision@8 | missed |
|---|---|---|---|---|
| legacy | 0.79 | 0.70 | 0.19 | q15, q16, q18 |
| lexical | 0.86 | 0.74 | 0.50 | q15, q18 |
| hybrid (no vectors) | 0.86 | 0.74 | 0.50 | q15, q18 |

Answers (oracle): pass 0.92, false answer rate 0.00. The two failures are the cross-language paraphrases that keyword search cannot find, so the oracle had nothing to cite. CI runs `python evals/qa_eval.py --mock` with floors at this baseline (hybrid recall ≥ 0.85, precision ≥ 0.45, oracle pass ≥ 0.9, false answers = 0).

Live: **not measured yet.** Run with the key set privately (see above), then record the table here:

```powershell
.\.venv\Scripts\python.exe evals/qa_eval.py --live --judge
.\.venv\Scripts\python.exe evals/qa_eval.py --live --semantic-threshold 0.4   # compare configurations
```

Embeddings are cached in ignored `evals/output/qa_embeddings.json`, so configuration sweeps reuse vectors and only pay for answer calls.
