# Generation settings and sampling

Open **Administration → Intelligence (LLM)**. Each role has one collapsible
**Generation settings** panel containing its applicable output-token limit,
reasoning controls, sampling settings and endpoint overrides. The **?** buttons
explain each control; click again, press Escape or click outside to close help.

## Shared and independent profiles

**Local Endpoints & Memory → Shared generation defaults** sets a shared sampling
profile. Every role initially follows it. All numeric fields start blank,
preserving the existing provider/server behavior.

Enable **Use an independent sampling profile for this role** to copy the shared
values into a separate profile. This is a complete independent profile: blank
fields use server defaults. Further shared changes do not overwrite it. Disabling
it returns to shared values while preserving the independent draft for later use.

The five roles keep separate profiles even with the same model and endpoint.
A role inheriting another role's model still uses its own sampling selection.
NPC Personality uses the profile of its selected Small/Complex role; it does not
have an additional sampling profile in this release.

## Controls

| Control | Meaning | Details |
| --- | --- | --- |
| Temperature | Changes the preference for likely next tokens | Lower values usually narrow variation; higher values can increase novelty and errors. Zero does not guarantee reproducibility. |
| Top P | Retains tokens until their cumulative probability reaches the threshold | 1 disables this filter. |
| Top K | Retains the K most likely next tokens | 0 disables it on the supported local servers. |
| Min P | Filters tokens relative to the most likely token | 0 disables it; high values narrow choices. |
| Repetition penalty | Changes the weight of tokens already used | 1 is neutral. Strong penalties can damage grammar, names and JSON. This differs from frequency/presence penalties. |

Temperature and Top P use provider-standard fields. Top K, Min P and repetition
penalty are sent directly to Ollama. For OpenAI-compatible APIs, explicitly enable
**local sampler extensions** when supported by the server, such as KoboldCpp or
llama.cpp. This feature never sends those local fields to cloud providers.
Individual models can restrict even standard sampling fields, especially in
reasoning mode; clear them when using a model that does not support them.

Avoid changing every filter together: strong combined filters can make prose
less varied. Compare one change while keeping the scene, model and template fixed.
Sampling controls token selection. Character independence also depends on cards,
goals, evidence, selected intentions and narration instructions.

## Save, test and verification

Changes remain local until **Save Intelligence Settings**. **Test Model** uses
the role's unsaved effective sampling profile and selected endpoint, without
persisting that test profile.

Automated tests inspect HTTP bodies through LiteLLM and the OpenAI SDK. They
cover text, structured JSON and streaming, all five Ollama router paths,
independent roles, save/reload, explicit zeros and empty defaults. Compatible
extensions become top-level request JSON fields; Ollama receives native `options`
fields, including `repeat_penalty`.

Transport tests do not establish live model quality. Start from the model author's
guidance, then compare repeated scenes for style and decisions.

References: [Artemis 31B v1.2](https://huggingface.co/TheDrummer/Artemis-31B-v1.2)
and [KoboldCpp](https://github.com/LostRuins/koboldcpp).
