# Adventure catalog and original-project exports

The portal's **Catalog** opens the community adventure catalog. Select a story,
review its description and install it into your Library. Existing Library actions,
including Resume, saved sessions and memory controls, remain available.

## Installing an adventure

Downloads pass through a compatibility adapter and the fork's normal importer.
The adapter preserves story identity, author, license, characters, items and artwork
while mapping supported upstream fields to the local format. Unsupported script
features are reported instead of being silently discarded.

An update installs a new template version. Existing games continue using their
previous template and assets; installing an update does not rewrite their history.
The catalog recognizes already installed versions by their stable story identity,
independently of their display title. Different stories may share the same title.

The default source is the original author's
[adventure repository](https://github.com/jschm42/taleweaver-adventures).
Administrators can set `ADVENTURE_LIBRARY_URL` to another compatible HTTPS
repository in `.env`. It must contain `library.json` and the adventure folders
listed there. The index is cached for offline browsing; installing still requires
access to the source files. `ADVENTURE_LIBRARY_TTL` controls cache age and
`ADVENTURE_DOWNLOAD_MAX_BYTES` limits each installation's download size.

## Sharing with the original TaleWeaver

In a Library adventure's menu, choose **Export for original TaleWeaver**.
The compatibility preview lists changes before preparing a downloadable `.adz`.
Set an adventure release version before exporting for publication.
When conversion changes supported behavior, acknowledge the report to continue.

For example, the original project does not provide our VN mode. A compatible copy
can use Chat mode, but will not reproduce VN-specific relationship behavior.
Fork-specific clothing, character-card and image-workflow settings may also need
to be removed. Unsupported behavior that cannot be converted safely blocks export.
The original adventure in your Library is not modified.

The publication copy contains the adventure blueprint and its referenced assets,
not a saved playthrough, accumulated player memories, API keys or model-server
configuration. Character names and story text remain in their original language.
Images must be included in the exported bundle. Upload or replace external image
links before preparing a publication copy; the converter does not fetch them.
Review the resulting story before publishing: compatible structure does not
guarantee identical model behavior between the two applications.

### Command-line preparation

Export a normal adventure `.adz` from the fork, then preview conversion:

```bash
poetry run python scripts/prepare_adventure_publication.py my-adventure.adz
```

Write the compatible copy to a new file:

```bash
poetry run python scripts/prepare_adventure_publication.py my-adventure.adz --output original-compatible.adz
```

If the preview reports changes requiring acknowledgement, review them and repeat
with `--acknowledge-changes`. Existing output files are not overwritten. Saved
sessions (`.ads`) are not accepted as publication input.

The current original project's publishing workflow uses an adventures repository,
not the retired GitHub Releases publisher. In your checkout of that repository,
use its own tool:

```bash
python scripts/add_adventure.py /path/to/original-compatible.adz
```

Review the generated adventure folder and `library.json`, then submit them through
that repository's normal contribution process. TaleWeaver's export action and
preparation CLI do not upload or push anything online.

## Format baseline

The compatibility adapter targets the upstream format at commit `2e042ef2`.
Both projects currently label their adventure format `1.3`; a matching format
number alone does not imply identical features. Conversion checks capabilities
and supported fields, rather than simply replacing a version number.

This integration adapts the catalog originally developed by **jschm42 and the
TaleWeaver contributors**. Original story attribution and licenses are retained.
