# Player input and character history

The narrative input wraps automatically and grows up to a bounded height before
scrolling internally. **Enter** sends an action; **Shift+Enter** inserts a newline.
Composing text with an IME does not send an unfinished message. Newlines are kept
in the submitted action. On multiline or visually wrapped input, arrow keys move
the caret; **Alt+Up/Down** explicitly browses recent submitted actions. The existing
Tab `/say` shortcut and voice controls remain available.

The character window has a visible scrollbar. **General history** and **History
with your character** each have a bounded, keyboard-focusable history panel with
its own scrollbar. **Load earlier entries** appends the next page. Changing tabs
returns that panel to the top, while retaining the profile and history tabs.
History remains observed information, not a live inventory or access to private
NPC knowledge.

## Local browser regression checks

These fixtures mount the production Vue components and intercept all API calls;
they never contact an LLM or image server. Start Vite on port 5187, then run from
`frontend/` with Playwright and Chromium installed:

```bash
npm run dev -- --host 127.0.0.1 --port 5187
# In another terminal; optional PLAYWRIGHT_MODULE/CHROMIUM_PATH select local installs.
node tests/browser/npcSettingsSmoke.mjs
node tests/browser/playerToolsSmoke.mjs
```

The first script checks AI-Fix modal placement and its request, the debug toolbar,
clothing layers and repair controls, VN diagnostics and responsive session settings.
The second checks actual textarea wrapping/keys/IME, paged history scrolling, and
the full Admin view's discovery/test/save chain for all five custom API role URLs.
They supplement the complete `node --test tests/*.test.mjs` suite and backend
integration tests. Mock responses establish UI behavior, not model prose quality.
