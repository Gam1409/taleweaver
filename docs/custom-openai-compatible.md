# Self-hosted OpenAI-compatible inference

In **Admin → Intelligence → Local Endpoints & Memory → Local & Custom API Endpoints**, configure **OpenAI-Compatible API**. This is a separate `custom_openai` provider; the official OpenAI and other providers retain their settings.

1. Start your inference server with its OpenAI Chat Completions API enabled.
2. Set the Base URL, including `/v1`:
   - KoboldCpp: `http://127.0.0.1:5001/v1`
   - llama.cpp: `http://127.0.0.1:8080/v1`
   - vLLM or LM Studio: the host and port reported by the server, followed by `/v1`.
   - A protected tunnel: `https://your-chosen-host/v1`.
3. For loopback/LAN endpoints, explicitly set `ALLOW_PRIVATE_NETWORK_MODELS=true` in the server environment or `.env`, then restart TaleWeaver. Custom endpoints require this explicit opt-in even though legacy local providers may allow private networks by default. Metadata/link-local destinations and redirects are rejected even with this setting enabled. Public deployments should keep private-network access disabled.
4. Leave the API key unset for an unauthenticated server. For a protected server, use **Add optional API key in Provider Vault**, save the key under **OpenAI-Compatible API**, then return to Intelligence. Keys use the existing encrypted vault and do not belong in the Base URL.
5. Choose **Detect Models**, or enter the exact **Custom Model ID** in each pass. Detection uses `<base>/models`; servers without that endpoint still support manual selection. Model IDs retain vendor slashes, including IDs starting with `openai/`.
6. Select **OpenAI-Compatible API** for mechanics, narrative, worldbuilder, play agent, and/or compression. Save the settings before clicking **Test Model**. Testing sends a small real structured completion to the saved endpoint, using the selected output mode, and validates a JSON object containing a message. This checks the JSON path used by mechanics rather than only text connectivity.

In Docker, `127.0.0.1` is the container itself. Use `host.docker.internal` where supported, or a deliberately configured host gateway/container network address. Ensure the inference server listens on an interface reachable from TaleWeaver. Restrict its exposure using firewall rules and authentication.

The request timeout defaults to 300 seconds and is editable up to 3600 seconds; it also controls the initial and idle streaming timeouts. Existing per-pass output token settings remain in effect. The server determines the actual context limit.

Custom structured requests always include the JSON schema in the prompt. **Structured output support** defaults to **Prompt only** for compatibility. If your server supports it, choose **JSON object** to request JSON syntax or **JSON schema** to request the complete schema through `response_format`. The latter can improve reliability for mechanics and worldbuilding. Unsupported selected modes produce a server error; change back to Prompt only rather than assuming support from `/models`. No tool-calling support is required. TaleWeaver still parses and validates the response using the requested Pydantic schema, and reports invalid output as an error. This improves compatibility but does not guarantee that every local model can satisfy complex tasks.

Detection errors distinguish authentication failure, missing `/models`, timeout, and invalid/unreachable endpoints. Check the Base URL, the server log, the optional vault key, and container networking before retrying. Detection failure does not disable manual IDs. Requests never fall back to cloud OpenAI or OpenRouter.
