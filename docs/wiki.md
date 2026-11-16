# GitHub Wiki synchronization

The repository documentation is the source of truth. The GitHub Wiki is a generated
reading view of one reviewed, published source commit. Update the source documents,
review the change and regenerate the Wiki from that same commit.

The offline [exporter](../scripts/export_wiki.py) only reads Git objects and writes
an explicitly selected local directory. It never creates a remote page, performs
an HTTP request, commits files or pushes a repository. No server, model or provider
credentials are required to generate the pages.

## What is mirrored

Authored Markdown guides, specifications, reports and release notes become Wiki
pages. Mermaid diagrams become Markdown pages containing a `mermaid` fence.
Research and historical status notices remain part of their source documents.

| Repository source | Wiki page |
| --- | --- |
| `docs/README.md` | `Home` |
| `README.md` | `Project` |
| `ASSETS.md` | `Assets` |
| `AGENTS.md` | `Contributor-Instructions` |
| `docs/npc-notebook.md` | `npc-notebook` |
| `docs/comfyui/README.md` | `comfyui` |
| `docs/comfyui/presets.md` | `comfyui--presets` |

Nested paths use `--`. Ambiguous path, case or reserved-name combinations receive
a deterministic suffix derived from the complete source path. A remaining name
collision stops the export rather than overwriting another page.

Relative Markdown, reference and HTML links point to the matching Wiki page when
that document is mirrored. Other source files use commit-pinned GitHub links;
images use commit-pinned raw asset URLs. Anchors and query strings are retained.
External URLs, inline code and fenced examples retain their original meaning.

License texts and the original immutable CHPM research specification are not
rewritten or mirrored. Links reach their pinned repository versions. JSON, ADV,
XLSX and other supporting files also remain source attachments. The research
wrapper records the original source hashes.

`Home` uses the repository's documentation index when available. `_Sidebar` groups
current guides and research/history links. `_Footer` identifies the exact source
revision and directs corrections back to the repository.

## Export and review

Initialize the Wiki through GitHub once if its Git repository does not yet exist.
Clone it to a directory outside the source checkout:

```bash
git clone https://github.com/Gam1409/taleweaver.wiki.git ../taleweaver-wiki
```

Inspect any existing Wiki pages. The exporter refuses to replace an independently
authored `Home`, sidebar, footer or other page. If GitHub created a trivial bootstrap
Home, review and explicitly preserve or rename it before the first export.

From the application checkout, select a reviewed commit already published to the
source repository. For a synchronized `main` snapshot in a POSIX shell:

```bash
git fetch origin main
WIKI_SOURCE_REVISION=$(git rev-parse origin/main)
python scripts/export_wiki.py --revision "$WIKI_SOURCE_REVISION" --output ../taleweaver-wiki --dry-run
python scripts/export_wiki.py --revision "$WIKI_SOURCE_REVISION" --output ../taleweaver-wiki
git -C ../taleweaver-wiki status --short
git -C ../taleweaver-wiki diff --stat
git -C ../taleweaver-wiki diff
```

PowerShell users can pass the published commit SHA directly to `--revision`.
`--repo` selects another local source checkout. `--source-url` selects its public
GitHub repository URL; the default is `https://github.com/Gam1409/taleweaver`.
Source URLs must use HTTPS without embedded credentials, a query or a fragment.

The exporter resolves the ref to a commit SHA and reads that commit's tree.
Uncommitted or untracked worktree text is never included, even when its file has
the same name as a source document. Dry-run performs the same validation and
prints a summary, but creates or changes no files.

After reviewing all generated changes, commit and push the Wiki using ordinary
Git authentication:

```bash
git -C ../taleweaver-wiki add -- '*.md' .taleweaver-wiki-export.json
git -C ../taleweaver-wiki commit -m "Synchronize documentation from reviewed source"
git -C ../taleweaver-wiki push
```

Wiki Git access is separate from a normal application push. Do not assume an
Actions `GITHUB_TOKEN` can write the Wiki. Use an account/key with the appropriate
Wiki repository permission; keep credentials outside remote URLs and generated
files. No automatic publication workflow is installed by this exporter.

## Ownership and limits

The generated manifest `.taleweaver-wiki-export.json` records each managed filename
and its content hash. Commit it alongside the pages. Later exports remove only
obsolete files from this manifest, preserve unrelated pages, and refuse to replace
or delete managed pages whose bytes were edited independently.

Malformed manifests, non-flat paths and symlink targets stop the export before
page writes or cleanup. `_snapshot` reads the pinned Git objects; `_existing` and
`_validate_output` validate the destination manifest and page ownership. Output is
anchored to the explicitly selected external directory, independently of the
application's `DATA_DIR`; backend configuration is not loaded.

At most 512 source pages are mirrored, with a 2 MiB per-page and 32 MiB aggregate
text budget. Generated pages use LF line endings; retain an LF-preserving Wiki
checkout so ownership hashes remain stable between platforms.

For an ownership conflict, review the local change, preserve its contents and
apply the intended correction in the source repository. Regenerate from the new
reviewed commit. The tool has no force-overwrite or automatic adoption option.
