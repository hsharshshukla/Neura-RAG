# P0 MVP integration acceptance

This opt-in harness validates the final conversation-attachment integration against
disposable PostgreSQL, Qdrant 1.15.1, Redis, and an actual TKP FastAPI/PostgreSQL
service seeded with approved synthetic knowledge. It never invokes TKP ingestion.
The harness generates fresh disposable login, PostgreSQL, JWT, and TKP service
credentials for each run; they are independent of production credentials.

Run it from the registered TKP repository so its migration fixtures are available:

```powershell
$env:TKP_REPOSITORY_ROOT = 'D:\AIDevJob\AI Dev Products\WatsappToVectorDBIngestionpipeline\codebase'
$env:NEURA_BACKEND_ROOT = 'D:\GV\DevController-RAG\worktrees\adf0ce4472174877b7fb6ed769fc2411\component-01\backend'
$env:NEURA_PYTHON = 'D:\Project\Neura\ChatBot-6F-B\backend\.venv\Scripts\python.exe'
$env:P0_EVIDENCE_PATH = "$env:NEURA_BACKEND_ROOT\tests\evidence\p0_mvp_acceptance.json"
$env:PYTHONPATH = "$env:TKP_REPOSITORY_ROOT\src;$env:TKP_REPOSITORY_ROOT"
Set-Location $env:TKP_REPOSITORY_ROOT
.\.venv\Scripts\python.exe -m pytest -q -s -p tests.conftest -p tests.integration.conftest `
  "$env:NEURA_BACKEND_ROOT\tests\test_p0_mvp_acceptance.py"
```

`P0_PROVIDER_MODE=deterministic` (the default) uses only a provider double while
retaining the real HTTP, database, TKP, Qdrant, storage, and SSE paths. A real-provider
run requires a valid `OPENAI_API_KEY`; set `P0_PROVIDER_MODE=real`,
`EMBEDDING_MODEL=text-embedding-3-small`, and `OPENAI_MODEL_PRO=gpt-5.4-mini` only
after applying the approved request and spending limits.

## Browser hold

Set `P0_BROWSER_READY_PATH` to a new JSON path and `P0_BROWSER_HOLD_PATH` to a new
signal-file path before running the same pytest command. After the JSON appears:

1. Read `frontend_port`, `backend_port`, and the synthetic login from the JSON.
2. Start the current worktree frontend with `PORT=<frontend_port>`, `BROWSER=none`,
   and `REACT_APP_API_BASE=http://127.0.0.1:<backend_port>/api/v1`, using dependencies
   restored from this frontend's checked-in `package-lock.json`.
3. Open `http://127.0.0.1:<frontend_port>/`, log in, open the seeded `P0 acceptance`
   chat, attach a small `.txt` file, attach it again to observe duplicate handling,
   ask for its unique text, and inspect the rendered conversation-attachment citation.
4. Create the hold signal only after the UI result is captured. The harness will then
   clean up every disposable container and service.

The ready JSON contains the temporary login password. Place it in a private local
directory, never commit it, and delete it after browser testing.

The final automated evidence is written to
`backend/tests/evidence/p0_mvp_acceptance_final.json` and contains no credentials.
