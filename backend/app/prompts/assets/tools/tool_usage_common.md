---
prompt_id: tool_usage_template
prompt_version: 2026-05-04.1
prompt_type: tool_usage_template
authority_level: tool_description_rendered
model_call_type: tool_call_preparation
cache_scope: run_static
source_ref: backend://prompts/tools/tool_usage_common.md
---
# Tool Usage Template

Treat tool descriptions as contract-bound capability references. Use only the tools currently allowed by the stage contract and explain intended side effects through structured tool-call arguments rather than free-form permission claims.
