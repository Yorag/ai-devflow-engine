# LangSmith Runtime Observability

LangSmith tracing is the preferred way to inspect live agent chain behavior during local model-provider runs. It is cloud observability only; product state remains in runtime tables, stage artifacts, domain events, audit records, and existing runtime logs.

## Enable

Set these environment variables before starting the backend:

```powershell
$env:LANGSMITH_TRACING = "true"
$env:LANGSMITH_API_KEY = "<langsmith api key>"
$env:LANGSMITH_PROJECT = "ai-devflow-engine-demo"
$env:LANGSMITH_ENDPOINT = "https://api.smith.langchain.com"
uv run uvicorn backend.app.main:app --reload
```

`LANGCHAIN_TRACING_V2=true` also enables tracing for the installed LangSmith/LangChain version. `LANGSMITH_PROJECT` controls the project shown in LangSmith.

## Trace Shape

The runtime adds explicit spans around the stage agent loop:

- `stage_agent.<stage_type>`: one root span per stage agent run.
- `stage_agent.iteration.<n>`: one child span per model decision iteration.
- `stage_agent.tool.<tool_name>`: one tool span per runtime tool execution.

Model calls made through LangChain are traced by LangSmith when tracing is enabled. The explicit runtime spans add the orchestration facts needed to debug loops: stage ids, iteration indexes, decision type/status, tool name, call id, tool status, artifact refs, side-effect refs, and final stage status.

## Redaction Boundary

The runtime wrapper does not write local `.agent.jsonl` chain logs and does not send raw file contents, raw prompts, API keys, provider keys, or large edit payloads as custom span metadata. Tool inputs are summarized with stable fields such as `path`, `pattern`, `command`, `argv`, input keys, and payload size. Tool result details use existing safe details and refs.

LangChain's own model traces may include prompt and response content according to LangSmith/LangChain tracing behavior. Use LangSmith project access controls and tracing settings accordingly.

## Failure Behavior

Tracing is optional. If tracing is disabled or LangSmith raises an error, the runtime continues with no-op tracing and the delivery chain remains responsible for producing normal artifacts and events.
