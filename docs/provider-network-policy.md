# Provider network policy

TaleWeaver supports self-hosted model servers. Legacy Ollama, ComfyUI and
Automatic1111 URLs may target loopback/private addresses by default. Setting
`ALLOW_PRIVATE_NETWORK_MODELS=false` rejects them through the shared URL validator.
For an Internet-facing deployment, restrict administrator accounts and network
egress as well; a URL setting is not a network firewall.

Administrator-managed **Custom OpenAI** endpoints are stricter: private addresses
require explicitly setting `ALLOW_PRIVATE_NETWORK_MODELS=true` in the environment
or `.env` and restarting. An inherited default is insufficient. This additional
check also rejects metadata/link-local, multicast and ambiguous URL forms even
when local access is enabled. Custom endpoints must end in `/v1`.

This distinction preserves existing local installations. Do not change the
legacy default without a migration path for their saved provider settings.

Only configure servers you control or trust. A public HTTPS tunnel is treated as
a public endpoint; private-network opt-in does not fix an expired tunnel, missing
ComfyUI model or failed provider authentication.
