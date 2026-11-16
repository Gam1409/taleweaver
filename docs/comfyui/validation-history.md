# Historical ComfyUI validation records

Status: historical development evidence, retained from the original integration and
starter-workflow updates. Counts, failures, timings, hardware and UI observations
below describe those checkouts. They are not the current CI status or a benchmark
for another installation. No live image-generation run was repeated for the
2026-11-16 documentation review.

Use [the current setup guide](README.md), [task recipes](../comfyui-task-templates.md)
and [default-workflow validation record](../comfyui-default-validation.md) for
current configuration and the scope of later recorded tests.

Branch validation results:

- Broad selection: 226 passed, three pre-existing failures in `test_adventures_api.py`
  (legacy consumable import, readable inventory snapshot, and manifest start scene).
- Earlier preset update: 118 tests passed across ComfyUI, prompt presets, existing media
  behavior and adventure lifecycle suites. This includes timeout before image
  submission, automatic/manual rules, profile overrides, settings persistence and
  preset IDs surviving cloning/export/import.
- The latest affected regression selection passed 113 existing media/configuration,
  filesystem security and adventure lifecycle tests.
- Full manifest application generated all five visual types through the fake ComfyUI
  transport and verified the Simple/Advanced assignments.
- Chromium verified API JSON import, bindings, compatibility checking, generation
  using unsaved settings, saved settings after reload, and repeated generation.
- Live ComfyUI 0.42.5 on NVIDIA A40 generated a five-image world with SDXL/FLUX
  assignments and then processed the previous scene via img2img. The six initial
  remote jobs completed in approximately 16–29 seconds each. Required nodes/models
  and filename detection were checked against the real server. LLM adaptation was
  disabled for these GPU tests; its routing and assembly were tested with mocks.
- Two further GPU jobs passed: generation through the browser's background-job flow
  and a reference comparison at denoise 0.25 (about 13 seconds end to end). The latter
  retained the original lighthouse/boat/pier much better than denoise 0.55, which
  changed major structures. Eight live jobs succeeded in that earlier round. This is transport
  and workflow validation, not a guarantee of exact semantic/identity preservation.
- Chromium saved a story-specific preset, verified it after reload and restored its
  original choice; desktop and mobile drawer layouts were inspected.
- Frontend production build passed; TypeScript diagnostics match the previous base
  diagnostic set. New Python modules/tests pass Ruff check and format check.
- Full-file Ruff reports 39 existing diagnostics in modified legacy files, compared
  with 40 on the same files at the previous commit; no new diagnostic locations.
  Two legacy files still fail the full-file format check. New modules pass both.

The final starter-workflow regression selection passed **166 tests**. All nine
Python modules/tests changed in this update pass Ruff check and format check. The
frontend production build passes with no additional TypeScript diagnostics relative
to the preceding commit.

The starter-workflow update adds 24 successful live jobs (eight each for SDXL,
FLUX.1 Dev FP8 and Prefect Anima), plus an initial Anima smoke image. The family
matrix and current limitations are documented in [starters.md](starters.md).

The setup flow and accessibility observations from that update are retained in the
[historical UI review](ux-review.md).
