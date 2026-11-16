# AI-Fix provider policy

AI-Fix uses the configured Complex role, then the configured Small role. Their
provider, model and per-role endpoint settings stay paired. A stored API key by
itself does not authorize an extra cloud destination, and an unconfigured role
does not silently become an OpenAI request.

An additional server-level fallback is **disabled by default**. Administrators
can explicitly set `AI_FIX_FALLBACK_PROVIDER` and optionally
`AI_FIX_FALLBACK_MODEL` (default: `gpt-4o-mini`). Enabling a cloud provider can
send adventure context to that provider. Leave the provider empty to disable
this additional fallback.

The suggestions response and dialog show the provider that generated the
proposals. Cache hits retain that provider, even if current settings differ.
Old cached responses without provenance leave the label empty.

A request whose completion is unconfirmed stops the chain. For serialized local
providers, AI-Fix also checks the durable inference fence after a timeout or
transport failure. It does not bypass an UNCERTAIN request by choosing another
role or endpoint. The administrator must verify the server stopped before
clearing that request in the inference queue.
