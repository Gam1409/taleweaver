<div align="center">

<img src="docs/branding/visualnovel.png" alt="VisualNovel — a golden book and an eye-shaped feather" width="420" />

# TaleWeaver · Visual Novel Fork

**Your story. Their personalities. A world worth returning to.**

A self-hosted storytelling studio for character-driven roleplay, visual novels, and RPG adventures.<br />
Build a world, give its characters a history, and bring each moment to life with illustrations and voices.

[![CI](https://github.com/Gam1409/taleweaver/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Gam1409/taleweaver/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-0.7.1--beta-f59e0b)](version.json)
[![Code: MIT](https://img.shields.io/badge/code-MIT-0ea5e9.svg)](LICENSE)
![Python 3.12](https://img.shields.io/badge/python-3.12-3776ab?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi&logoColor=white)
![Vue 3](https://img.shields.io/badge/Vue%203-interface-42b883?logo=vue.js&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-ready-2496ed?logo=docker&logoColor=white)

[Why this fork](#-why-this-fork) · [Characters](#-characters-with-a-point-of-view) · [Visuals](#-art-that-fits-the-scene) · [AI providers](#-your-models-your-setup) · [Get started](#-get-started) · [Guides](#-guides)

</div>

<br />

> [!NOTE]
> Built on **[TaleWeaver by jschm42](https://github.com/jschm42/taleweaver)** and maintained by **[Gam1409](https://github.com/Gam1409)**. This fork expands character continuity, Visual Novel play, memory, local inference, and ComfyUI authoring while retaining the original adventure-building foundation.

## ✨ Why This Fork?

<table>
<tr>
<td width="50%" valign="top">

### 🎭 A Character Has Reasons

Optional **NPC Personality** gives selected characters intentions grounded in their traits, values, goals, and experiences. A proud character can negotiate, refuse, or take the initiative; relationships have a history to draw on.

</td>
<td width="50%" valign="top">

### 🧠 A Story Has a Memory

Character journals, historical summaries, and optional **RAG recall** help earlier events remain relevant. Remember a promise, return to a shared experience, or pick up a story after a long break.

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 🎨 Every Image Has a Purpose

Give portraits, locations, items, and story illustrations their own **ComfyUI presets and workflows**. Organize styles, edit node graphs, and choose a compatible reference workflow when the task needs one.

</td>
<td width="50%" valign="top">

### 🔌 Your Setup Has Room to Grow

Start with one model, or assign different models and endpoints to different jobs. Run from the terminal, use a **native tray application**, or host the same browser interface with **Docker**.

</td>
</tr>
</table>

---

## 📖 Play the Story Your Way

| Mode | The experience |
| --- | --- |
| **RPG** | Quests, combat, inventory, loot, progression, and deterministic world rules. |
| **Chat** | Open-ended dialogue, exploration, and story-led interaction. |
| **Visual Novel** | Character-focused scenes, relationships, illustrated moments, and adjustable narrative pacing. |

The comic-style feed combines narration, character portraits, dialogue, and action cues. Add expressive **Gemini or ElevenLabs speech**, or use local **Whisper push-to-talk** for your own replies. Choose a session language for new narration, dialogue, and action suggestions.

Generate an adventure from an idea, import an existing world, or create a sequel or variation through **Cover Mode**. Refresh action suggestions whenever you need inspiration. The separate **Play Agent** can take the protagonist's turns step by step or automatically.

## 🎭 Characters With a Point of View

Meet NPCs, learn who they are, and build a shared history. Character cards bring together portraits, descriptions, appearance, background, and the experiences your protagonist has learned about.

Optional session features add an [emotion palette and character thoughts](docs/npc-portrait-presentation.md) to NPC portraits. Show the dominant emotion as a subtle glow, or hover for a brief fictional thought and click to open the character card. Both options start disabled.

### NPC Personality · Optional · v1.0.0

**NPC Personality** is the player-facing name of the CHPM module. It adds a more deliberate decision layer to VN dialogue:

- **Identity and motivation:** use a character's established traits, values, goals, and commitments to guide intentions.
- **Experience and change:** keep remembered events and their supporting evidence separate from a temporary reaction or an unsupported claim.
- **Bounded agent lookups:** consult accessible memories, possessions, and visible clothing through session-scoped tools.
- **An active cast:** focus detailed analysis on selected interlocutors while keeping other participants in the scene.
- **A choice of depth:** leave it off, observe its decisions, or enable narration guidance and review. The default enabled-mode failure policy keeps RP moving through standard narration when optional analysis fails; strict mode is available for inspection.

Results depend on the models you choose. More active characters and deeper checks mean more requests and longer turns.

[Player guide](docs/chpm-continuation.md) · [Technical guide](docs/chpm-pilot.md) · [Module releases](docs/chpm-changelog.md)

### Clothing, Belongings & Continuity

- **Layered outfits:** record garments by layer and body coverage, with visible clothing available to narration and illustrations.
- **Items from the story:** VN can register supported acquisitions, gifts, transfers, and clothing changes from completed narration, with ownership and evidence checks.
- **Descriptions worth reading:** generate fuller item descriptions about the object itself, alongside its equipment and clothing metadata.
- **Review and repair:** inspect outfits in **Debug → NPCs → Clothing**, recover missing garments from recent history, and select which validated entries to restore.
- **Persistent physical state:** keep injuries, dirt and fluid traces across VN turns; review sources and correct conditions in **Debug → State**. Treatment and partial cleaning keep the remaining condition. [How it works](docs/persistent-physical-state.md).
- **Improve an existing item:** preview and apply description, technical-field, and image repairs separately. An unsuccessful image request preserves the previous image.

Detailed clothing and mature-content preferences are configurable; inner garments remain subject to the saved clothing settings and established adult age requirements.

[Item continuity and clothing recovery](docs/narrated-item-reconciliation.md) · [Item repair](docs/item-repair.md)

## 🌍 A World With a History

### Living World & Concordia

Optional **Living World** lets NPCs follow bounded routines, move through connected locations, and interact beyond the protagonist's immediate reply. Configure activity limits, away-time catch-up, and the decision engine in adventure defaults or an individual session.

Use the built-in engine or the optional **Concordia 2.4** integration. NPC intentions still pass through world rules before becoming actions. NPC Personality and Living World's private-decision mode are alternative decision paths; the [Living World guide](docs/living-world-usage.md) and [NPC Personality guide](docs/chpm-continuation.md) explain their controls.

### Memory & Relevant Recall

Persistent journals focus on meaningful facts, promises, decisions, and relationship changes. Optional **LanceDB-backed retrieval** uses an embedding model to find relevant older dialogue and summaries. Recall is scoped to the adventure/session; character tools respect the information available to that NPC.

The authoritative story and game state stay in SQLite. The search index can be rebuilt separately. Configure embeddings under **Administration → Memory & recall** when you want this extra layer.

[Memory guide](docs/memory-rag.md)

### Explore, Revisit & Share

Discover connected places through the world map, and optionally create nearby locations when the story confirms a local arrival. Keep separate playthroughs, return to saved sessions from the Library, and revisit recent milestones through **Chronicles** checkpoints.

Export adventures and session bundles for backups or sharing. Reuse characters and items across worlds, including their artwork.

## 🎨 Art That Fits the Scene

A portrait, an inventory icon, and a wide scene illustration need different compositions. This fork gives them separate assignments:

**Image task → Preset → Base or reference workflow → ComfyUI**

Illustrate a story moment or regenerate a portrait during play, with task presets controlling how each asset is drawn.

- **A searchable preset library:** organize presets by name and task labels, then assign them to the image tasks they suit.
- **A visual workflow editor:** import ComfyUI editor/API JSON, inspect the node graph in a dedicated expandable window, edit inputs, and bind TaleWeaver's prompts, dimensions, seed, reference, and output.
- **Base and reference variants:** keep both in a preset and use the appropriate compatible workflow for the request.
- **Task templates:** start from **80 recipes across 10 model families and 8 image tasks**, including portraits, inventory items, backgrounds, illustrations, covers, avatars, and style previews.
- **Component-aware setup:** choose embedded or external encoders and VAE, check available model filenames and server nodes, and configure the graph for the actual checkpoint.
- **Model-aware prompts:** use tags, natural descriptions, or mixed formats, with extra positive/negative instructions and optional mature-content rules.

Included families cover **SD 1.5, SDXL, Pony V6 XL, Illustrious XL, Animagine XL 4.0, FLUX.1 Dev, SD3.5 Large, Anima, Nova Anime AM, and Qwen Image**.

ComfyUI is one supported image provider; **Automatic1111 / Forge**, Ollama image generation, and supported cloud image APIs are also available. Checkpoints, custom nodes, and other model assets must be installed on their own server. An img2img reference workflow does not by itself guarantee a character's face or identity.

[ComfyUI task templates and model layouts](docs/comfyui-task-templates.md) · [Portraits and references](docs/portrait-regeneration.md)

## 🛠️ Build Your Own Adventures

The browser workbench brings together locations, routes, NPCs, items, quests, tone, and artwork. Generate drafts, refine their details, and run structural checks or AI-assisted reviews before playing.

<details>
<summary><b>Worldbuilding and editing tools</b></summary>

- Generate new worlds or variations of existing adventures, with supported staged jobs resumable after interruption.
- Edit character traits, appearance, age, equipment, and clothing data.
- Supply an open-ended [world blueprint](docs/world-blueprints.md): setting, history, starting facts and bounded reference excerpts.
- Choose a [narrator style](docs/narrator-styles.md) while preserving each character's own voice.
- Create item drafts from descriptions and review them before saving.
- Inspect connected scenes, route requirements, containers, switches, and readable objects.
- Review validation findings and apply AI-Fix proposals.
- Use debug tools to inspect scene JSON, move NPCs, edit recorded clothing, or repair an item in a saved session.

</details>

<details>
<summary><b>Custom events and scripting</b></summary>

Use validated Python event scripts to define scene-entry events, interactions, turn hooks, and conditional outcomes. The editor provides a scripting workbench for repeatable world logic.

[Adventure format](docs/specs/adventure_format.md) · [Turn pipeline](docs/diagrams/game_session_loop.mermaid) · [World generation](docs/diagrams/adventure_generation.mermaid)

</details>

---

## 🔌 Your Models, Your Setup

Use **Ollama**, an **OpenAI-compatible API**, or supported cloud providers such as **OpenAI, Anthropic, OpenRouter, DeepSeek, and Gemini**. Compatible self-hosted servers include **KoboldCpp, llama.cpp, LM Studio, and vLLM**.

| Role | What it does |
| --- | --- |
| **Small / Utility** | Structured tasks, action interpretation, and mechanics. |
| **Main / Narration** | Prose, dialogue, and storytelling. |
| **Worldbuilder** | Adventure generation and world structure. |
| **Play Agent** | The protagonist's optional automated turns. |
| **Compression** | History compression and summaries. |

Choose a provider and model for each role. **Ollama and OpenAI-compatible APIs support a shared base URL plus individual role URL overrides**, so a technical model and a prose model can run on separate servers. One model can also serve every role. Custom servers can use an optional saved API key or remain keyless when their server permits it.

Memory recall has a separate **embedding endpoint**. Image and voice providers are configured independently, so these capabilities can be enabled as your setup grows.

Your saves and assets live on your TaleWeaver host. Story context is sent to the providers you select; a fully local setup uses your own inference endpoints. Saved provider keys are encrypted at rest.

[OpenAI-compatible setup](docs/custom-openai-compatible.md) · [Ollama roles](docs/ollama-roles.md) · [Generation controls](docs/llm-sampling.md) · [Provider network policy](docs/provider-network-policy.md)

## 🚀 Get Started

### Desktop Apps · Beta

Download the matching archive from **[v0.7.1-beta](https://github.com/Gam1409/taleweaver/releases/tag/v0.7.1-beta)**, extract the complete folder, and launch the application. Development builds remain available under [Desktop distributions → Artifacts](https://github.com/Gam1409/taleweaver/actions/workflows/desktop.yml?query=event%3Aworkflow_dispatch).

| Platform | Launch | Notes |
| --- | --- | --- |
| **Windows x64** | `TaleWeaver.exe` | Native tray application. |
| **Linux x64** | `TaleWeaver` | Built on Ubuntu 22.04; requires a compatible desktop and tray support. |
| **macOS ARM64** | `TaleWeaver.app` | Apple Silicon; the current package does not target Intel Macs. |
| **Docker** | See below | Server deployment with persistent storage. |

The native app starts the service in the background, waits for the browser UI, and opens your default browser. Its tray menu offers **Start / Stop / Restart / Log / Exit**, with a **green** ready indicator, **red** stopped indicator, and **yellow** starting/error indicator.

The package includes its Python runtime and prebuilt web UI; you do not need to install Python or Node.js separately. No Electron browser or AI model weights are embedded. Your user-data profile stays outside the application bundle. Preview builds are unsigned. Full packaging runs on release tags or manual dispatch, rather than every commit.

[Desktop installation, storage, and build details](docs/desktop.md)

### Docker

Install Docker with Compose, then clone the fork:

```bash
git clone https://github.com/Gam1409/taleweaver.git
cd taleweaver
```

Copy `.env.example` to `.env` and set `SECRET_KEY` and `ENCRYPTION_KEY`. To generate both keys using Docker:

```bash
docker run --rm python:3.12-slim python -c "import base64, os, secrets; print('SECRET_KEY=' + secrets.token_hex(32)); print('ENCRYPTION_KEY=' + base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

Paste the values into `.env`, then start the bootstrapper:

```bash
bash scripts/docker-setup.sh
```

On Windows CMD, use `scripts\docker-setup.bat`. The script prints the HTTPS address and uses a self-signed local certificate.

SQLite, RAG, and media use separate persistent directories: **`sqlite-docker/`**, **`db/`**, and **`data-docker/`**. Preserve all three and the original keys when backing up or updating. Existing Docker installations should follow the [storage migration guide](docs/docker-storage.md).

### Run From Source

The regular terminal workflow remains available. Recommended development setup: **Python 3.12, Poetry 2.x, Node.js 22, and Git**. The backend package requires Python 3.11 or later. Current macOS installations require Apple Silicon to match the available LanceDB wheels.

**Windows · PowerShell**

```powershell
git clone https://github.com/Gam1409/taleweaver.git
cd taleweaver
.\setup.ps1
```

For later starts, use `.\run.ps1`. From **CMD**:

```cmd
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

To start from local files without checking GitHub or pulling updates, use `.\run-local.ps1` (or `.\run.ps1 -NoUpdate`). From CMD: `powershell -ExecutionPolicy Bypass -File .\run-local.ps1`. Dependency checks and normal application startup remain the same.

**Linux / macOS**

```bash
git clone https://github.com/Gam1409/taleweaver.git
cd taleweaver
bash setup.sh
```

For later starts, use `bash run.sh`. Add `--no-update` to skip the launcher's Git update check. After pulling changes, refresh dependencies with `.\setup.ps1 -SkipStart` or `bash setup.sh --skip-start`.

<details>
<summary><b>Manual setup and prebuilt frontend</b></summary>

From the repository root, install the dependencies and prepare `.env`:

```bash
poetry install
cp .env.example .env
poetry run python scripts/generate_keys.py
```

Copy both generated key values into `.env`, then continue:

```bash
poetry run alembic upgrade head
cd frontend
npm ci
npm run build
cd ..
poetry run python -m backend.main
```

Open `http://127.0.0.1:8000`. This starts the backend serving the built frontend; Vite is not required. The normal run scripts start the development frontend and backend together.

</details>

### Your First Adventure

1. Open the application locally and create the initial administrator account.
2. Configure your text providers and role models in **Administration**. Test the endpoints before generating a world.
3. Create an adventure or import an existing one, select RPG, Chat, or VN, and begin a new session.
4. Add images, voice, memory recall, Living World, or NPC Personality when you want them. Optional layers have their own setup and request budgets.

For **Concordia**, use Python 3.12+ and install `poetry install --extras concordia` before selecting it. The setup scripts also accept `-Concordia` on Windows and `--concordia` on Linux/macOS. Living World additionally requires `INFERENCE_SERIALIZATION_ENABLED=true`; see its guide for activation and limits.

> [!TIP]
> Start with a small adventure and one active NPC when trying the optional personality layer. A strong structured-output model for utility tasks and your preferred prose model for narration are a useful pairing. Local-model compatibility, RP quality, image consistency, and latency depend on your chosen models and workflows.

## ⚙️ Configuration

Set model routing, credentials, visuals, and optional features through **Administration**. Adventure settings define defaults for new sessions; saved sessions have their own controls.

Source and Docker deployments use [`.env.example`](.env.example) as their server configuration reference. Desktop apps keep their generated keys and overrides in the profile's `server.env`.

| Setting | Purpose |
| --- | --- |
| `SECRET_KEY` / `ENCRYPTION_KEY` | Sign access tokens and encrypt stored provider credentials. Keep the original keys across updates and restores. |
| `DATA_DIR` | Persistent application media and data directory. |
| `DATABASE_URL` | Database destination; Docker uses its separate SQLite mount. |
| `MEMORY_DB_DIR` | RAG index location, independently configurable. |
| `BACKEND_PORT` | Backend port, normally `8000`. |
| `ALLOW_PRIVATE_NETWORK_MODELS` | Explicitly enable intended local/LAN model endpoints when required by the provider policy. |

In Docker, `localhost` refers to the container. Use an address reachable from the backend for your model servers. Private-network access, remote initial setup, and allowed hosts are explained in the [provider policy](docs/provider-network-policy.md) and `.env.example`.

## 📚 Guides

| Explore | Read more |
| --- | --- |
| Visual Novel play | [VN mode](docs/visual-novel-mode.md) · [Session language](docs/session-content-language.md) |
| NPCs and shared history | [Character introductions and journals](docs/npc-introductions.md) |
| Optional personality | [Player controls and fallback](docs/chpm-continuation.md) · [Technical guide](docs/chpm-pilot.md) |
| World simulation | [Living World and Concordia](docs/living-world-usage.md) |
| Long-term recall | [Memory and retrieval](docs/memory-rag.md) |
| Clothing and item continuity | [Narrated items and recovery](docs/narrated-item-reconciliation.md) · [Repair](docs/item-repair.md) |
| ComfyUI | [Task presets and model layouts](docs/comfyui-task-templates.md) · [Prompt presets](docs/comfyui/presets.md) |
| Local text inference | [OpenAI-compatible APIs](docs/custom-openai-compatible.md) · [Ollama role settings](docs/ollama-roles.md) |
| Authoring and exploration | [Staged world generation](docs/staged-world-generation.md) · [Dynamic locations](docs/dynamic-locations.md) |
| Installation and storage | [Desktop apps](docs/desktop.md) · [Docker storage](docs/docker-storage.md) |

## 🤝 Credits & License

**Original author:** [jschm42](https://github.com/jschm42), creator of [TaleWeaver](https://github.com/jschm42/taleweaver). This fork builds on the original author's and contributors' work.

**Fork maintainer:** [Gam1409](https://github.com/Gam1409). Issues and contributions for this version belong in [this repository](https://github.com/Gam1409/taleweaver).

- **Code:** [MIT](LICENSE).
- **Adventures and story content:** [CC-BY-NC 4.0](LICENSE-CC-BY-NC-4.0), unless a file declares a different license, such as the MIT-licensed combat test adventure.
- **Bundled fonts and assets:** see the [font licenses](frontend/public/assets/fonts/licenses/README.txt) and individual asset notices.
- **Community adventures:** the [upstream adventure repository](https://github.com/jschm42/taleweaver-adventures) remains available for shared creations.

---

<p align="center"><b>Build the setting. Meet its people. See what your choices change.</b></p>
