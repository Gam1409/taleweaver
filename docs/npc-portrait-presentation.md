# NPC portrait presentation

Session settings provide two independent opt-ins, both off in existing and new sessions:

- **Палитра эмоций**: a subtle glow around NPC portraits. One dominant **overall current emotion** determines its color; the narrator's integer intensity (0–100) determines strength. A separate brightness slider changes the display without changing the assessment.
- **Мысли персонажей**: a short fictional in-character thought appears on portrait hover or keyboard focus. Escape dismisses it. When this option is enabled, portrait hover replaces the usual NPC tooltip, and clicking the portrait opens the character card without preparing a dialogue action. Unassessed portraits show no thought or fallback hover card. Reduced-motion preferences disable its animation.

These are display features, not relationship meters or psychological diagnoses. They do not rewrite personality, memories, motives, consent, possessions or game outcomes. Thoughts can reveal fictional information the protagonist has not learned; enable them when that style of storytelling suits the session.

## Data and cost

The existing narrator request supplies an optional `<npc-state>` JSON footer after the story. No additional model call, hover request, keyword inference or dialogue/voice-tag inference is used. Only enabled fields are requested and accepted. Enabled presentation adds a compact instruction, current cast IDs and a short output entry for each assessed NPC; exact token cost depends on cast size and model.

Story language and machine data have separate contracts: prose and thoughts follow the selected story language, while JSON keys and emotion identifiers keep their specified English spelling. A compact reminder accompanies the current turn so long histories do not leave the footer requirement only in the initial system prompt. NPC Personality's simplified-RP fallback still supports the same display data.

The reminder is also carried into narration repair and the ordinary replacement writer when a reply is rejected. Replacements require their own footer: an emotion or thought attached to rejected prose is never copied onto the replacement. Hovering or focusing the NPC Personality status exposes a fixed explanation of its recovery reason. With system diagnostics enabled, `npc.behavior_fallback` records the reason and safe exception type/source frames when available, without exception messages or model output.

The owner-only NPC Personality settings retain the last two proposal validation messages in the bounded recovery history. During cooldown, **Most recent rejected NPC proposal** shows those earlier messages separately from the current turn's zero analysis usage. For older saves, the panel can read the previous turn snapshot when it belongs to the same session and selected cast. This is inspection only: it does not restore the snapshot, advance time, change psychology or call a model. If neither source still contains the messages, no rejection reason is invented. NPC journal entries and RAG embeddings remain separate from confirmed psychological updates.

Recovery also retains bounded messages from trusted host analysis errors, including context packing, perception and unavailable inference. **Most recent failed NPC analysis** can therefore explain a failure with no proposal feedback. Arbitrary transport exception messages are not copied into this owner report or the system log. The input cap counts serialized instructions, schema and NPC data in characters; it is independent of the model's context capacity and the output token cap. JSON is already serialized compactly. If required data still cannot fit, the decision request is withheld and its size error remains visible. Saving changed settings clears the recovery cooldown for the next player turn while preserving the unreviewed interval and confirmed identity; saving unchanged settings does not clear it. No model call is triggered by saving settings.

Saved roster selections may remain while an NPC is absent, no longer listed or reserved by adventure defaults. Changing request limits retains these existing IDs; adding a new selection still requires a known NPC from this session. The settings panel exposes unlisted saved IDs for explicit removal without revealing unlearned character names. The retry snapshot receives the changed request settings and cleared pause counters while keeping its own historical psychology and continuity gap.

The server validates actor IDs against the visible session cast, emotion names, integer intensity and thoughts up to 160 Unicode characters. At most 20 NPC entries and 10,000 footer characters are accepted. Bad or missing metadata leaves the story usable with no assessment; **unknown is not calm**. Metadata is removed before story streaming, audio, item extraction, NPC review and canonical prose storage. A repaired/replaced reply only uses metadata supplied for that reply.

`ChatMessage.portrait_state` stores the validated cues separately, tied to a hash of the final prose. Nullable data keeps legacy messages compatible. Rewrites, revision restoration, checkpoints, session copies and exports preserve this association. Historical pages use their own latest narration, not the newest assessment from another page. A subsequent unassessed reply clears the display instead of borrowing an earlier emotion.

After committing a reply, the backend logs `NPC presentation` with the session, cast size, assessed count and a fixed reason. The optional system diagnostic log records the same result as `npc.presentation` with `presentation_reason`: `available`, `disabled`, `no_visible_cast`, `incomplete_narration`, `missing_footer`, `incomplete_footer`, `footer_too_large`, `invalid_json`, `invalid_entries`, `no_valid_entries` or `source_mismatch`. These records contain no story text, thoughts or raw model output. A missing/invalid footer is still left unassessed; it is not replaced with a guessed emotion or an old reply's thoughts.

Settings belong to the session, use optimistic conflict detection and survive last-turn replay. Changing them does not modify adventure defaults. Both options off preserves the existing narrator prompt and stream behavior.

## Palette

| Emotion | Color |
| --- | --- |
| Calm | Light blue |
| Joy | Gold |
| Affection | Soft rose |
| Love | Crimson with a pale pink rim |
| Sexual arousal | Pink |
| Ecstasy | Orchid |
| Anger | Red |
| Fear | Near-black with a muted gray-violet rim |
| Sadness | Indigo |
| Embarrassment | Blush |
| Shame | Muted mauve |
| Surprise | Pale yellow |
| Interest | Turquoise |
| Trust | Mint |
| Hope | Light green |
| Anxiety | Lavender |
| Disgust | Olive |
| Confusion | Periwinkle |
| Determination | Orange |
| Tiredness | Blue-gray |
| Boredom | Neutral gray |
| Unknown / unassessed | No glow |

Color associations have common patterns and cultural differences; this is an expressive game palette. See [Jonauskaite et al. (2020)](https://doi.org/10.1177/0956797620948810) and [Wilms & Oberfeld (2018)](https://doi.org/10.1007/s00426-017-0880-8). Black cannot emit light, so fear uses a dark shadow and a faint visible rim.

## Verification

Offline backend tests cover streaming marker splits, malformed metadata, opt-in combinations, scope/ownership, settings conflicts and replay, prose binding, ordinary turn publication and narration revisions. Frontend tests cover palette/schema agreement, Unicode limits, defaults, historical selection and settings persistence. The browser fixture checks hover/focus/Escape, escaped thought text, no hover requests, independent effects and narrow-screen placement:

```sh
cd frontend
npm run dev -- --host 127.0.0.1 --port 5193
# In another terminal with Playwright and Chromium installed:
node tests/browser/npcPresentationSmoke.mjs
```

Live-model assessment quality is separate from these transport and UI checks.
