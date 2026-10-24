# ComfyUI setup review

Scope: preset creation, model selection, workflow editing, prompt configuration and
save/reload in the actual TaleWeaver UI. Chromium was checked at 1440×1000 and
390×844. Screenshots were captured and inspected during the review; the final
settings run used an isolated database and a local copy of the server's node
registry after live GPU testing ended.

| Step | Result | Evidence / changes |
|---|---|---|
| 1. Choose a starter | Working | `01-comfy-workflow-starter.png`: one family selector; model dependencies explained; reference graph collapsed. Matching model paths and compatibility checks run automatically. A loading message replaces an unexplained empty selector. |
| 2. Configure files and parameters | Working | `02-comfy-workflow-parameters.png`: Anima's three files remain visible; numeric sampling controls and sampler/scheduler are under an accordion. Unique datalist IDs prevent one graph's choices from appearing in another. Saving waits for pending model discovery/checks. |
| 3. Edit graph / prompt | Working | Invalid JSON was rejected without changing the draft; valid edits and downloaded API JSON were verified. `03-comfy-prompt-theme.png`: automatic prompt rules remain separate from sampling controls; additional rules and preview are collapsed. The mature-theme preference does not turn off automatic model detection. |
| 4. Save and reopen | Working | Preset name, steps, reference model and theme preference survived a full page reload. `04-comfy-prompt-mobile.png`: drawer fits a narrow viewport; the footer remains available while content scrolls. Escape closes it and returns focus to Configure. DOM IDs are unique. |

Remaining limits:

- The application-wide font and small help text can be dense on mobile. The review
  confirmed layout and keyboard behavior, not full screen-reader or WCAG compliance.
- Setup still has two explicit levels: Apply to form, then Save Visuals Settings.
  The drawer explains this and offers Discard. This follows the existing settings
  model; changes are not silently saved when a dialog closes.
- Custom graph topology is easier to edit visually in ComfyUI. TaleWeaver provides
  import/export, raw JSON and common parameters rather than duplicating its canvas.
- Filename detection cannot inspect model weights. Unknown/ambiguous files need a
  one-time explicit selection. Routine image generation uses the saved rules.
- Images may not follow every semantic detail. Img2img is approximate and is not
  a face/identity guarantee; static compatibility is not a GPU runtime guarantee.

Code review also corrected default avatar dimensions when saved width/height are
null, model-specific dimension alignment, and raw metadata reaching an image model
when LLM adaptation is disabled. Regression coverage is listed in the provider guide.
