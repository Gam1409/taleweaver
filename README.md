<div align="center">

<img src="frontend/src/assets/svg/app-logo.svg" alt="TaleWeaver Logo" width="100" height="100" />

# TaleWeaver

**Weave Infinite Adventures. Direct and Star in Your Own Playable Audiobook.**

A self-hosted storytelling studio for RPG adventures, open-ended conversations, and visual novels.
Create worlds, meet memorable characters, and bring your stories to life with illustrated scenes and cinematic voices.

[![License: MIT](https://img.shields.io/badge/license-MIT-0ea5e9.svg)](LICENSE)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776ab?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi&logoColor=white)
![Vue 3](https://img.shields.io/badge/Vue%203-SPA-42b883?logo=vue.js&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-local%20data-003b57?logo=sqlite&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-ready-2496ed?logo=docker&logoColor=white)

[Features](#-features) · [Supported AI](#-supported-ai-ecosystem) · [Quick Start](#-quick-start) · [Docker](#-running-with-docker) · [Configuration](#%EF%B8%8F-configuration) · [Editor & Scripting](#-adventure-editor--scripting)

</div>

<br />

> [!NOTE]
> **This is a fork of [TaleWeaver by jschm42](https://github.com/jschm42/taleweaver).** The original project was created by [jschm42](https://github.com/jschm42). This fork is maintained by [Gam1409](https://github.com/Gam1409) and extends the original with additional storytelling, character, image-generation, and local-model features.

![Adventure Gameplay](docs/screenshots/gameplay.jpg)

<table>
  <tr>
    <td width="50%"><a href="docs/screenshots/generator.jpg"><img src="docs/screenshots/generator.jpg" alt="World Generator" /></a></td>
    <td width="50%"><a href="docs/screenshots/editor-map.jpg"><img src="docs/screenshots/editor-map.jpg" alt="Interactive Directed Map" /></a></td>
  </tr>
  <tr>
    <td align="center"><sub><b>World Generator</b> – synthesize complete adventures, lore, and Python scripts from a prompt</sub></td>
    <td align="center"><sub><b>Directed Cartography</b> – interactive topological maps with real-time pathfinding</sub></td>
  </tr>
  <tr>
    <td width="50%"><a href="docs/screenshots/editor-scenes.jpg"><img src="docs/screenshots/editor-scenes.jpg" alt="World Workbench" /></a></td>
    <td width="50%"><a href="docs/screenshots/editor-validation.jpg"><img src="docs/screenshots/editor-validation.jpg" alt="Dual-Tier AI Validation" /></a></td>
  </tr>
  <tr>
    <td align="center"><sub><b>Adventure Workbench</b> – full visual CRUD for scenes, NPCs, items, containers, and switches</sub></td>
    <td align="center"><sub><b>Dual-Tier Validation</b> – structural graph audits paired with semantic AI story critiques</sub></td>
  </tr>
</table>

<p align="center">
  <em>For detailed descriptions and feature breakdowns of each screen, see the <a href="docs/SCREENSHOTS.md">Screenshot Guide</a>.</em>
</p>

## 1. The Vision

Create a world, choose your character, and discover where your decisions take you. TaleWeaver combines an AI storyteller with persistent adventures, expressive dialogue, illustrations, and voice narration. Play a quest-driven RPG, explore through conversation, or slow down for a character-focused visual novel.

This fork builds on [jschm42/taleweaver](https://github.com/jschm42/taleweaver), with expanded local-model support, ComfyUI integration, character continuity, and optional long-term memory.

## 2. Core Features

### 🧠 Choose Your Story

* **RPG, Chat & Visual Novel:** Choose the experience that fits your story. RPG provides quests, encounters, and progression; Chat emphasizes conversation and exploration; experimental VN focuses on characters and relationships without quests or XP.
* **Your Own Worlds:** Generate adventures from an idea, including places, characters, items, and story hooks. Staged generation lets you resume supported interrupted generation jobs.
* **Narration at Your Pace:** In VN, choose leisurely, balanced, or brisk narration. Characters have their own personalities, motivations, and reactions to the story.
* **Cover Mode:** Create sequels, spin-offs, or variations of an existing adventure, with optional reuse of its artwork.
* **Action Ideas & Play Agent:** Refresh suggested actions without advancing the story, or let a play agent take turns automatically or step by step, with a personality of your choice.
* **Your Story Language:** Save a language for each session and use it for new narration, dialogue, and action ideas. Existing world descriptions and interface labels remain unchanged.

### 🎭 Characters That Become Part of the Story

* **Meet & Remember:** NPCs who introduce themselves by name can gain their own persistent character cards and portraits during play.
* **Character Cards:** View a portrait, description, general background, and a separate history of shared experiences. Known attitudes toward your character can appear when supported by the story.
* **Appearance & Clothing:** VN tracks individual outfits and changes such as gifts, dressing, and removing items. Visible clothing helps guide both narration and illustrations; more detailed clothing is optional.
* **Private Knowledge:** A character card shows what your protagonist has learned. It does not reveal an NPC's hidden inventory or private thoughts.

### 🗺️ Explore, Save & Return

* **Local Discoveries:** Optional dynamic exploration can add nearby places when your character actually arrives, such as a tavern in the current town. Mentioning a distant place alone does not create it.
* **Interactive World Map:** Follow connected locations, inspect places, and navigate the adventure visually.
* **Resume from Library:** Return to an existing saved session directly from an adventure card, or start a separate playthrough.
* **Chronicles Timeline:** Automatic milestone checkpoints let you return to a recent point in the story. Each session retains its five most recent checkpoints.
* **Portable Adventures:** Copy, export, and import adventures and saves to keep backups or share your creations.

### 🧠 Memory That Matters

* **Meaningful Character History:** Journals focus on significant facts, promises, boundaries, decisions, and relationship changes rather than every movement or glance.
* **Optional Relevant Recall:** Connect an embedding model to help retrieve older events that matter to the current conversation, with summaries organized around characters, places, and the wider story.
* **Background Updates:** Memory maintenance waits for idle opportunities so it does not continuously take priority over play.
* **Simple Controls:** Enable recall under **Admin → Memory & recall**. Clear or rebuild an adventure's search index from its Library menu without deleting the story or saved progress. See the [memory guide](docs/memory-rag.md).

### 🎨 Illustration & Cinematic Audio

* **Comic-Style Story Feed:** Narration, character dialogue, portraits, and expressive speech bubbles bring each turn to life.
* **ComfyUI Workflows:** Use **ComfyUI (Local)** for covers, backgrounds, portraits, items, and scene illustrations. Choose a starter workflow or import your own API workflow JSON.
* **Ready-to-Edit Presets:** Starters cover SDXL, Illustrious XL, Animagine XL, FLUX.1, and Anima / Prefect Anima. Adjust common settings in the interface and expand advanced controls when needed.
* **Style & Image References:** Choose a visual style, adapt prompts to supported model families, and optionally use a previous image as a reference with a compatible workflow. Portraits can be generated or regenerated during a session.
* **Illustrate a Moment:** VN offers manual scene illustrations alongside the story. Visual results depend on the chosen model and workflow.
* **Playable Audiobook:** Add expressive text-to-speech narration and local push-to-talk speech input.

### 🔌 Bring Your Own Models

* **Cloud or Self-Hosted:** Connect supported cloud providers, Ollama, or an **OpenAI-Compatible API** such as a compatible KoboldCpp, llama.cpp, LM Studio, or vLLM server.
* **Models by Role:** Choose different models for mechanics, narration, worldbuilding, the play agent, and history compression. Ollama roles can also use different server URLs.
* **Optional API Keys:** Custom OpenAI-compatible servers can use a saved key or run without one when the server allows it.
* **Local Data:** Saves and assets are stored on your TaleWeaver host. Requests are sent to the AI providers you select; local inference is available when you want to keep those requests on your own hardware.

> [!NOTE]
> Local-model support and VN remain experimental. Story interpretation, memory selection, and image consistency depend on your models. Start with a small adventure and a setup that fits your hardware.

### 🛠️ Build & Share Your Worlds

* **Adventure Editor:** Refine locations, routes, NPCs, objects, quests, tone, and visuals in the browser.
* **World Validation:** Check connections and story consistency, review generation reports, and apply suggested improvements.
* **Event Scripting:** Add custom events and outcomes through the editor's scripting tools.
* **Reusable Characters & Items:** Export and import protagonists, NPCs, and items with their portraits to reuse them in other adventures.
* **Community Adventures:** Browse and install shared adventures, then make your own variations.

---

## ✨ Features

<table>
<tr>
<td width="50%" valign="top">

### 🧠 Stories & Characters

- **Three Ways to Play** – RPG adventures, open-ended Chat, and character-focused Visual Novels
- **Dynamic Living NPCs** – expressive multi-turn dialogue, autonomous scene movements, and individual motives
- **Persistent Character Cards** – portraits, known background, and shared history
- **Cover Mode** – generate sequels, alternate timelines, or spinoffs from existing adventure blueprints
- **Tactical Encounters & Loot** – dedicated combat modal, locked container mechanics, item passcodes, and consumable handling

</td>
<td width="50%" valign="top">

### 🎭 Comic Feed & Cinematic Audio

- **Comic-Style Turn Feed** – dynamic speech bubbles, speaker avatars, action markers, and character staging
- **Playable Audiobook** – cinematic AI narration with emotional depth powered by Google Gemini TTS & ElevenLabs
- **Push-to-Talk Speech Input** – hands-free roleplaying with local background Whisper speech-to-text
- **In-Character Speech Shortcuts** – hold `B`, `T`, or `Shift` to automatically speak in-character (`/say `) to NPCs
- **Chronicles Timeline** – milestone-based auto-save checkpoints with instant one-click timeline rewinds

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 🛠️ World-Builder & Scripting

- **In-Browser Adventure Studio** – comprehensive visual authoring for scenes, directed routes, NPCs, and loot tables
- **Sandboxed Python Event Scripts** – author deterministic event logic (`on_enter_scene`, `on_interact`, `on_turn_start`, `on_turn_end`) in an isolated AST sandbox
- **Dual-Tier Validation Suite** – graph connectivity audits combined with semantic LLM plot-hole detection
- **One-Click AI Diagnostics** – intelligent AI repairs for broken exits, missing keys, or narrative inconsistencies
- **Dynamic Cartography** – explore connected places on a hand-drawn-style map

</td>
<td width="50%" valign="top">

### 🔐 Private & Local-First

- **Bring Your Own Models** – choose cloud providers, Ollama, or an OpenAI-compatible server
- **Zero Lock-In Blueprints** – export and share complete adventure blueprints as standalone `.adv` or `.adz` packages
- **Optional Long-Term Recall** – find relevant earlier events with a separate embedding model
- **Protected Credentials** – provider keys are stored encrypted
- **Self-Hosted Setup** – install locally or run with Docker

</td>
</tr>
</table>

---

## 🔌 Supported AI Ecosystem

TaleWeaver uses an adapter layer ([LiteLLM](https://github.com/BerriAI/litellm)) to connect supported AI services. You can choose different models for story logic and narration:

| Capability | Recommended Models | Supported Providers | Notes |
|---|---|---|---|
| **World Generation** | Anthropic Opus 5.x, OpenAI 5.x, DeepSeek v4 Pro | OpenRouter, Anthropic, OpenAI, DeepSeek, Kimi, Ollama, OpenAI-compatible APIs | Requires deep reasoning to generate complex, valid JSON schemas |
| **Mechanics (Pass 1)** | DeepSeek Flash, GPT-6 Luna, Claude 4.5 Haiku | OpenAI, OpenRouter, Anthropic, DeepSeek, Ollama, OpenAI-compatible APIs | Resolve actions, inventory changes, and game rules |
| **Narrative (Pass 2)** | DeepSeek v4 Pro, GPT-6 Luna Pro, Claude 4.5 Sonnet | OpenAI, Anthropic, OpenRouter, DeepSeek, Ollama, OpenAI-compatible APIs | Rich, atmospheric prose adapting to player choices and mood |
| **Text-to-Speech (TTS)** | Google Gemini TTS, ElevenLabs | Google Gemini, ElevenLabs | High-fidelity voice narration; feels like a live audiobook |
| **Speech-to-Text (STT)**| OpenAI Whisper (Base / Small / Medium) | Local Whisper (background thread) | Hands-free microphone input with Push-to-Talk hotkeys |
| **Visual Scene Art** | SDXL, Illustrious, Animagine, FLUX, Anima | ComfyUI, Automatic1111 / Forge, Ollama, supported cloud APIs | Covers, backgrounds, portraits, items, and scene illustrations |
| **Optional Memory Recall** | A multilingual embedding model suited to your stories | Ollama, OpenAI-compatible embedding APIs | Retrieve relevant earlier events |

> [!TIP]
> **Mix Models to Fit Your Setup**: Use a model that follows structured instructions for mechanics and worldbuilding, and choose your preferred writing model for narration. Speed and cost depend on the models, providers, and adventure size. Pre-configured test adventures are included in `/adventures`, and community creations are available in the **[Community Adventure Repository](https://github.com/jschm42/taleweaver-adventures)**.

---

## 🚀 Quick Start

### Option A: Automatic Setup Script (Recommended)

The setup script creates a virtual environment, installs backend and frontend dependencies, runs database migrations, and initializes your environment keys.

**Linux / macOS:**

```bash
git clone https://github.com/Gam1409/taleweaver.git
cd taleweaver
chmod +x setup.sh && ./setup.sh
```

**Windows (PowerShell):**

```powershell
git clone https://github.com/Gam1409/taleweaver.git
cd taleweaver
.\setup.ps1
```

For subsequent Windows starts, use `.\run.ps1` from the project directory. After updating the repository, run `.\setup.ps1 -SkipStart` to refresh dependencies and apply updates; on Linux/macOS, use `bash setup.sh --skip-start`.

The setup scripts install the memory-search dependency too. To use semantic recall, configure an embedding model separately in **Admin → Memory & recall**.

---

### Option B: Manual Development Setup

**Requirements:** Python 3.10–3.13, [Poetry](https://python-poetry.org/) 2.x, Node.js 20.19+ or 22.12+ (supported LTS recommended)

```bash
# 1. Clone & install Python dependencies
git clone https://github.com/Gam1409/taleweaver.git
cd taleweaver
poetry install

# 2. Configure environment & encryption keys
cp .env.example .env
poetry run python scripts/generate_keys.py
# Copy both generated values into .env before continuing.

# 3. Apply database migrations
poetry run alembic upgrade head

# 4. Install & build frontend
cd frontend
npm ci
npm run build
cd ..

# 5. Start TaleWeaver
poetry run taleweaver
```

Open `http://127.0.0.1:8000` in your browser. Complete the initial setup, add your API keys under **Administration**, and jump into an adventure!

---

## 🐳 Running with Docker

Run the frontend and backend together in a container:

```bash
git clone https://github.com/Gam1409/taleweaver.git
cd taleweaver

# Run the automated container bootstrapper
bash scripts/docker-setup.sh      # Windows: scripts\docker-setup.bat
```

The Compose configuration keeps game data in `./data-docker` by default and the optional memory index in `./db`. Keep these folders when updating containers to preserve your saves and assets.

---

## ⚙️ Configuration

Core server and security settings are configured in `.env` (refer to [`.env.example`](.env.example)):

| Variable | Purpose | Default / Example |
|---|---|---|
| `SECRET_KEY` | **Required** – JWT token signing key (min 32 random characters) | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ENCRYPTION_KEY` | **Required** – 32-byte Fernet key for encrypting stored provider API keys | `python scripts/generate_fernet_key.py` |
| `DATA_DIR` | Directory for persistent database, session state, and uploads | `./data` |
| `ALLOWED_HOSTS` | Comma-separated domain whitelist for HTTP request validation | `localhost,127.0.0.1` |
| `ALLOW_PRIVATE_NETWORK_MODELS` | Allow connections to intended local AI servers (Ollama, ComfyUI, custom APIs) | `true` |
| `ALLOW_REMOTE_SETUP` | Allow non-loopback clients to execute initial root bootstrap | `false` |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` | Optional default provider keys | Set in `.env` or save encrypted keys in Administration |

---

## 🛠️ Adventure Editor & Scripting

TaleWeaver includes a comprehensive browser-based authoring workbench that puts you in full control of your worlds:

<details>
<summary><b>🐍 Sandboxed Python Event Scripting Engine</b></summary>

Use the scripting workbench to define repeatable events and outcomes for your adventure:

- **Lifecycle Hooks**: Attach custom logic to `on_enter_scene`, `on_interact`, `on_turn_start`, and `on_turn_end`.
- **State Manipulation**: Safely query and mutate scene descriptions, room exits, inventory items, NPC dialogue states, avatar hitpoints, and custom session variables.
- **Victory & Defeat Triggers**: Define custom branching conditions that evaluate player actions and story milestones.
- **In-Editor Workbench**: Test, debug, and lint event scripts directly inside the **Scripts Tab** with syntax assistance and priority scheduling.

</details>

<details>
<summary><b>🛡️ Security & Hardening Architecture</b></summary>

TaleWeaver includes protections for self-hosted play:

- **Encrypted Provider Keys:** Saved API credentials are encrypted at rest.
- **Protected Saves & Uploads:** Access checks help keep each user's sessions and files separate.
- **Local Setup:** Initial administrator setup is restricted to the local host by default.
- **Your Choice of Providers:** Choose where model requests are sent and which services receive your story content.

</details>

<details>
<summary><b>🗺️ Architecture Diagrams & Turn Flow</b></summary>

Inspect the internal engine workflows through Mermaid diagrams in the repository:

- [Adventure Generation Workflow](docs/diagrams/adventure_generation.mermaid)
- [Adventure Generation Activity Flow](docs/diagrams/adventure_generation_activity.mermaid)
- [Game Session Loop Sequence](docs/diagrams/game_session_loop.mermaid)
- [Game Session Loop Activity](docs/diagrams/game_session_loop_activity.mermaid)

</details>

<details>
<summary><b>📚 Feature Guides</b></summary>

- [Visual Novel mode](docs/visual-novel-mode.md)
- [Character introductions and journals](docs/npc-introductions.md)
- [Dynamic exploration](docs/dynamic-locations.md)
- [Memory and relevant recall](docs/memory-rag.md)
- [ComfyUI image generation](docs/comfyui/README.md)
- [ComfyUI workflow starters](docs/comfyui/starters.md)
- [Ollama role settings](docs/ollama-roles.md)
- [OpenAI-compatible APIs](docs/custom-openai-compatible.md)
- [Portrait regeneration and references](docs/portrait-regeneration.md)
- [Session language](docs/session-content-language.md)
- [Staged world generation](docs/staged-world-generation.md)
- [Action ideas](docs/idea-refresh.md)
- [Adventure catalog and original-project exports](docs/adventure-catalog.md)

</details>

---

## 📜 License & Acknowledgments

**Original author:** [jschm42](https://github.com/jschm42), creator of [TaleWeaver](https://github.com/jschm42/taleweaver). Thank you to the original author and contributors for the foundation of this project.

**Fork maintainer:** [Gam1409](https://github.com/Gam1409). This repository develops additional features on top of the original project.

- **Code**: Licensed under the [MIT License](LICENSE).
- **Adventures & Story Content**: Licensed under [CC-BY-NC 4.0](LICENSE-CC-BY-NC-4.0).
- **Fonts & Assets**: Bundled frontend typography assets and licenses are documented in `frontend/public/assets/fonts/licenses`.
