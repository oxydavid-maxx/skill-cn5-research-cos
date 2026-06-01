"""LLM transport for the cockpit (shared by P2a + later phases).

`sdk_client.call_structured` is the single narrow entry point: system+user prompt
+ a JSON schema -> validated structured JSON dict. Key-gated and degrades
gracefully. Mirrors the escape-mrc / Albert sdk_client pattern.
"""
