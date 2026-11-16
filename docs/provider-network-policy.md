# Provider network policy

TaleWeaver supports self-hosted model servers. The shared provider URL validator
allows private/loopback addresses by default for legacy local setups. Setting
`ALLOW_PRIVATE_NETWORK_MODELS=false` rejects those destinations on paths that use
that validator, including Ollama role overrides/discovery, ComfyUI client setup
and embedding configuration.

This flag is not uniform dispatch-time protection for every legacy provider.
The shared legacy `ollama_url` and direct Ollama/Automatic1111 image transports do
not revalidate their configured URL at each generation request. Only configure
trusted endpoints, restrict administrator access and enforce deployment network
egress separately. The flag is not a network firewall.

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
