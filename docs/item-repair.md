# Repair an existing session item

Enable session debug, then open **Debug → Items → Repair**. Clothing also has a
Repair button inside **Clothing**, next to its layer and existing description.
The tool works on existing items in this session, including garments recovered
from narration. It does not create another item or change its owner.

1. Generate a **text & technical draft** using the configured Complex model.
   Review or edit the name, full description and technical JSON.
2. Select **Apply text**, **Apply technical fields**, or both. Technical fields
   cover item type, portability, equipment slots and clothing metadata. Existing
   scripts, gameplay bonuses, provenance, possession and worn status are preserved.
3. Optionally generate an **image preview**. It uses the current saved description,
   the session's object workflow/preset and image dimensions. Apply improved text
   first when the illustration should follow that description. The saved image
   is replaced only when its preview is explicitly selected and applied.

Text-only repair does not require valid unselected clothing metadata. Technical
repairs must preserve valid worn references and existing detailed-clothing/age
requirements. Correctly spelling a name does not change the item's stable ID.
Descriptions use connected literary prose and the source language, within the
existing 1,000-character storage limit. Unknown history, powers and hidden
properties should not be invented to make the prose longer.

Requests can incur model/provider cost. They are sent only when the corresponding
button is clicked. A failed preview does not modify the saved item; a failed image
request keeps the previous image. Provider/admission timeouts are not bypassed.

If the item or its ownership changed after preview, generate a fresh preview.
Apply waits for the session mutation boundary and refuses an outstanding turn.
A successful edit invalidates an available **last-turn replay** because its older
snapshot would undo the edit. The interface reports this; playing a new turn
creates another replay point. Older checkpoints and frozen scene evidence retain
their historical contents rather than being rewritten by a present-day repair.
