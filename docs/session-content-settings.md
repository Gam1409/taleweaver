# Content preferences in an existing session

Open the session settings and expand **Mature content**. Enable or disable the
setting, select Soft / Medium / Hard when enabled, and use **Save settings**.
Enabling uses the same typed `NSFW` confirmation as adventure creation. Canceling
the dialog or closing settings without saving does not update the server.

This changes the session's saved manifest only. The adventure template, other
sessions, clothing tracking, inventory, relationships, chat history, and images
are not rewritten. Existing narration and image-adapter gates remain unchanged;
image adaptation still also requires the image profile's Mature themes setting.

The new setting applies to subsequent generation, including Rewrite and full-turn
Regenerate. The pre-turn replay snapshot receives only the preference update, so
regenerating still restores the original gameplay state. If that regeneration
fails, recovery keeps the newly saved preference. Content edits require no LLM
call and no database migration.

An active turn prevents saving. A stale settings dialog or concurrent JSON update
returns a conflict instead of overwriting newer data; reload the settings and try
again. Sessions without a valid saved manifest cannot use this control; other
session settings remain available. Checkpoint restoration follows its existing
snapshot semantics and can restore the preferences saved in that checkpoint.
