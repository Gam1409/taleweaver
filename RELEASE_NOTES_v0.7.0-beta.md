# TaleWeaver 0.7.0 beta

This release adds optional NPC Personality, expanded ComfyUI workflows and
session debugging, alongside reliability and security fixes. NPC Personality
has its own module version, 1.0.0; it does not track the application version.

The main audit fixes protect private adventures and exports, preserve more state
across import/checkpoint restore, bound script operations, and improve error and
connection recovery. AI-Fix no longer invents a cloud fallback from an API key.

Deployment uses one application worker because session leases and background
jobs are process-local. The Docker image now uses Python 3.12 and Node 22 for
the frontend build; `INSTALL_CONCORDIA=true` includes the optional engine.
Python 3.10/3.11 remain supported for the native engine outside that image.

`version.json` is the application release source. Python distribution metadata
uses its PEP 440 equivalent `0.7.0b0`, and npm uses `0.7.0-beta`.
Persisted data schemas keep independent compatibility versions.
