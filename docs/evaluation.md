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
