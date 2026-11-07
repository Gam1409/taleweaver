<div align="center">
<img src="https://raw.githubusercontent.com/Gam1409/taleweaver/v0.7.0-beta/docs/branding/visualnovel.png" alt="VisualNovel" width="300" />

# TaleWeaver · Visual Novel Fork
### v0.7.0-beta — Your story. Their personalities.
</div>

Welcome to the first beta release of the **Visual Novel fork of TaleWeaver** —
a self-hosted place for character-driven roleplay, branching stories and illustrated
adventures. Create a setting, meet its characters, and let conversations develop
through their motives, memories and choices.

Use your own local models or supported cloud providers. Play in your browser,
run a native tray application, or host the same interface with Docker.

## 🎭 Characters with a point of view

The optional **NPC Personality** module helps characters retain original traits,
values and goals while responding to what happens around them. NPCs can disagree,
negotiate, take conversational initiative and pursue unfinished business.
Recent feelings and longer-term developing tendencies have separate roles in behavior.

Source-backed memories, ongoing undertakings and causal continuity help retain
**what happened, why it mattered and what remains to be done**. Optional semantic
recall finds relevant observations across different wording within each NPC's own
recorded knowledge and the current session.

- Select a roster of up to 20 characters and deeply process active interlocutors.
- Use bounded agent lookups for known memories, own possessions and visible clothing.
- Choose Standard, Observe or Enabled mode per session, with defaults for new sessions.
- Keep playing through optional analysis failures, or use Strict mode for inspection.

NPC Personality has its own version, **1.2.0**, independent of the application.
It remains experimental; consistency depends on the models and available evidence.

## ✨ A story you can see

- **Emotion Palette:** optional portrait lighting follows the dominant emotion and
  its model-supplied intensity.
- **Character Thoughts:** short optional thoughts appear on hover; clicking opens
  the character card.
- **ComfyUI presets by task:** assign workflows for portraits, illustrations,
  backgrounds and items, with separate base/reference workflows where supported.
- Browse presets, import workflow JSON, expand the graph editor, map application
  inputs, and check required nodes against your server.
- Inspect layered clothing and item ownership, recover source-backed missing records,
  and review repairs to item descriptions, visual metadata and images.

Image templates require the matching model files and ComfyUI nodes on your server.
Visual quality depends on the model, workflow and prompt.

## 🧠 Your models, configured for their jobs

Route narration, technical processing, world generation, memory compression and
the play agent to shared or independent providers and endpoints.

Every role has **one Generation settings panel** for its applicable token limits,
reasoning controls, sampling profile and connection settings. Configure Temperature,
Top P and supported local Top K / Min P / repetition controls separately for prose
and technical responses. Small **?** buttons explain each control; blank sampling
values preserve provider defaults.

Use Ollama, OpenAI-compatible servers such as KoboldCpp, or supported cloud providers.
Local sampler extensions are explicitly enabled for compatible APIs and kept out
of cloud requests.

## 🛠️ Inspect, repair and keep your progress

The unified debug inspector brings NPCs, world state, items, scene JSON and VN
diagnostics together. Move NPCs, inspect and edit clothing by layer, and examine
the technical state behind a scene.

This beta also includes fixes for turn recovery, regeneration, settings drafts,
clothing recovery, NPC identity matching and memory retrieval. RAG preserves source
references and distinct episodes with similar wording, supports embedding prefixes
and Unicode lexical fallback, and rotates idle indexing and compression work.

Living World and optional Concordia integration remain available. Living World's
private-decision mode and Enabled NPC Personality are alternative decision paths.

## 📦 Choose your installation

| Platform | Archive / start | What you get |
| --- | --- | --- |
| **Windows x64** | `TaleWeaver-windows-X64.zip` | Extract the whole folder and start `TaleWeaver.exe`. |
| **Linux x64** | `TaleWeaver-linux-X64.tar.gz` | Extract and start `TaleWeaver`; built on Ubuntu 22.04. |
| **macOS Apple Silicon** | `TaleWeaver-macos-ARM64.tar.gz` | Extract and open `TaleWeaver.app`. |
| **Docker** | [Docker setup](https://github.com/Gam1409/taleweaver/tree/v0.7.0-beta#docker) | Build the tagged source with separate persistent SQLite, RAG and media storage. |
| **From source** | [Setup instructions](https://github.com/Gam1409/taleweaver/tree/v0.7.0-beta#get-started) | Terminal startup remains supported. |

Native archives include the Python runtime, libraries and built web interface.
**Extract the complete archive**, rather than moving out only the executable.
AI model weights and ComfyUI are configured separately.

The app starts the service in the background, opens your default browser and
stays in the tray. Use **Start / Stop / Restart / Log / Exit**; the icon shows
green for ready, red for stopped, and yellow for startup or a problem.

These beta builds are unsigned. macOS targets Apple Silicon; an Intel Mac package
is not included. Linux needs a compatible desktop/tray setup.

## 💾 Updating and storage

Native applications keep saves, media, memory and generated keys in the OS user
profile, outside the application bundle. Back up that complete profile before
updating. Docker users should preserve all persistent mounts and original keys.
Startup applies the normal database migrations.

`version.json` defines the app release; npm uses `0.7.0-beta` and Python metadata
uses `0.7.0b0`. NPC Personality and persisted data contracts have separate versions.

## 📚 Start here

[Project overview](https://github.com/Gam1409/taleweaver/blob/v0.7.0-beta/README.md) ·
[Desktop guide](https://github.com/Gam1409/taleweaver/blob/v0.7.0-beta/docs/desktop.md) ·
[NPC Personality](https://github.com/Gam1409/taleweaver/blob/v0.7.0-beta/docs/chpm-continuation.md) ·
[Memory & recall](https://github.com/Gam1409/taleweaver/blob/v0.7.0-beta/docs/memory-rag.md) ·
[Generation controls](https://github.com/Gam1409/taleweaver/blob/v0.7.0-beta/docs/llm-sampling.md)

Built on the original TaleWeaver project, with thanks to its author and contributors.
Please report issues for this fork in [Gam1409/taleweaver](https://github.com/Gam1409/taleweaver/issues).
