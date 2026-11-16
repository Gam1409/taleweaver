"""Object descriptions are intrinsic prose; actions and temporary state live elsewhere."""

ITEM_DESCRIPTION_STYLE = """
ITEM DESCRIPTION STYLE:
Write item.description in the source language as fluent, detailed literary prose,
with correct spelling, grammar and punctuation. Use connected sentences and, when
supported by the task, one or two compact paragraphs rather than a name plus a
generic sentence or a list of tags. Develop the object's intrinsic appearance:
shape, colour, material, texture, cut, construction, fastenings and distinctive design.
Describe the thing itself. Do not narrate its acquisition, transfer, use, current
owner, location, being worn/held/removed, or the surrounding scene. Do not blend
temporary status (dirty, torn, broken, wet, displaced) into the description.
Keep any supported action/status in the task's existing fields or exact evidence;
do not invent a new status field. Exact source quotations keep their original spelling.
Respect this task's evidence rules: recovery/registration cannot invent unknown
materials, brands or provenance merely to lengthen prose. Authoring drafts may
develop a coherent design while preserving explicit facts and exclusions.
The full item description is at most 1000 characters; respect any shorter field
limit (such as a readable object's 200-character summary). clothing.description is
a separate concise intrinsic visual specification, at most 400 characters.
"""
