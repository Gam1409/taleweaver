# Session checkpoints

A checkpoint restores the avatar, session state, inventory and worn clothing,
sequence progress, session status, canonical item definitions and the discovered
map. Repair changes to item text, image references and technical fields are
rewound together with their inventory representations. Only the restored session
is affected; template and other-session records remain unchanged.

New checkpoints include an explicit map and canonical item snapshot. Invalid
snapshot structures are rejected before changing the runtime state. Generated
image files remain on disk; their saved references are restored.

Older checkpoints without these snapshots still load. Map nodes and edges are
filtered to their saved discovered scenes and current location. Item fields can
only be recovered where an inline inventory record preserved them; unknown old
fields cannot be reconstructed. The restore response and UI show a warning about
that limitation instead of claiming an exact item rollback.

Manual and pinned checkpoints are retained. At most five unpinned automatic
checkpoints are kept per session. Real playtime is not rewound.
