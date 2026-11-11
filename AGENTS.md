# Neura — Codex Development Instructions

## Architecture
- Preserve the existing React frontend and FastAPI backend.
- Use TKP for organizational knowledge retrieval.
- Keep Neura responsible for authentication, chat, history and LLM answers.
- Do not introduce duplicate organizational RAG infrastructure.
- Preserve strict session ownership and authorization.

## Token efficiency
- Read the relevant TKP phase specification before working.
- Inspect Git diffs and affected files first.
- Avoid whole-repository exploration unless necessary.
- Run focused tests during implementation.
- Run full regression tests at final acceptance.
- Keep implementation reports and terminal output concise.
- Resume existing work rather than recreating completed features.

## Safety
- Never modify D:/Project/Neura/ChatBot.
- Preserve unrelated work and existing functionality.
- Never stage generated .pyc files, logs or pytest caches.
- Clean confirmed pytest temporary folders only after tests finish.
- Never reset, delete or overwrite unrelated changes.
- Do not commit, push or merge without explicit instruction.

## Quality
- Enforce authentication, session ownership and CSRF protection.
- Preserve TKP citation and provenance identifiers.
- Fail closed on retrieval authorization or evidence failures.
- Verify backend tests, API contracts and frontend build where relevant.
- Distinguish legacy lint/type failures from new regressions.
