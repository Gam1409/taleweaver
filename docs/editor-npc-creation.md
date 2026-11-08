# Create an NPC from a description

In the adventure editor, open **NPCs** and click **New**. This button is also
available when the adventure has no NPCs. The existing manual creation and
NPC import actions remain available.

1. Choose a location and describe the character: appearance, personality,
   independent goals, clothes and any personal belongings.
2. Choose whether to generate clothing and additional belongings. Underwear
   is optional and requires an explicit adult age (18+) plus the adventure's
   saved mature-content and detailed-clothing settings.
3. Click **Generate NPC draft**. One Small / Utility model request prepares
   the character and up to 16 belongings; it does not change the adventure.
4. Review and edit the character. Expand individual items to edit their
   descriptions and clothing layers. Uncheck any item you do not want.
   Clothes may be worn or carried; owning an item does not make it worn.
5. Click **Create NPC & selected items**. The NPC and selected belongings
   are saved together. A failed save keeps the draft available for retry.

Each selected item is a separate canonical object owned by the new NPC.
Worn clothes reference those same object IDs in the character's visual profile.
Opaque outer layers continue to hide inner clothing. These records survive
adventure export/import and are used when starting new sessions.

Portraits and item images are generated separately using the existing image
actions after saving. This dialog does not start image jobs. Editing a template
does not retroactively insert characters into already-started sessions.

Repeated publication of the same draft uses an idempotency key to avoid
duplicate characters after a lost HTTP response. Concurrent publications from
this dialog are serialized per adventure in the supported single-worker runtime.
