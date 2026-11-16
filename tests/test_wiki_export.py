"""Offline Wiki generation reads a pinned commit and protects independently authored pages."""

import json
import sys

import pytest

from scripts import export_wiki


def git(repo, *args):
    return export_wiki._git(repo, *args).decode().strip()


def commit(repo):
    git(repo, "add", "--all")
    git(
        repo,
        "-c",
        "user.name=Documentation test",
        "-c",
        "user.email=docs@example.test",
        "commit",
        "-qm",
        "Update documentation",
    )
    return git(repo, "rev-parse", "HEAD")


def put(repo, name, text):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def source(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    git(repo, "init", "-q", "--initial-branch=main")
    put(repo, "README.md", "# TaleWeaver\n\nProject overview.\n")
    put(repo, "docs/README.md", "# Documentation\n\n## Start here\n\n## Research and history\n")
    put(repo, "docs/guide.md", "# Guide\n\n## Details\n\nCommitted text.\n")
    put(repo, "docs/deep/guide.md", "# Nested guide\n\n## Part\n")
    put(repo, "backend/core.py", "VALUE = 1\n")
    put(repo, "docs/picture space.png", "image bytes")
    commit(repo)
    return repo


def run(source, tmp_path, **options):
    return export_wiki.export(source, tmp_path / "wiki", **options)


def page(tmp_path, result, source_path):
    return (tmp_path / "wiki" / (result["pages"][source_path] + ".md")).read_text()


def test_home_sidebar_footer_and_idempotent_generation(source, tmp_path):
    first = run(source, tmp_path)
    assert first["pages"]["docs/README.md"] == "Home"
    assert first["pages"]["README.md"] == "Project"
    assert first["pages"]["docs/deep/guide.md"] == "deep--guide"
    assert "# Documentation" in (tmp_path / "wiki/Home.md").read_text()
    sidebar = (tmp_path / "wiki/_Sidebar.md").read_text()
    assert "Home#start-here" in sidebar and "Home#research-and-history" in sidebar
    assert first["revision"] in (tmp_path / "wiki/_Footer.md").read_text()
    before = {p.name: p.read_bytes() for p in (tmp_path / "wiki").iterdir()}
    assert run(source, tmp_path) == first
    assert {p.name: p.read_bytes() for p in (tmp_path / "wiki").iterdir()} == before


def test_rewrites_markdown_reference_html_images_and_encoded_paths(source, tmp_path):
    put(
        source,
        "docs/links.md",
        """# Links
[guide](guide.md?mode=read#details)
[reference][nested]
[nested]: deep/guide.md#part "Nested title"
[code](../backend/core.py#L1)
![picture](<picture space.png>)
<img src="picture%20space.png" alt="Picture">
<a href="../backend/core.py?raw=1&amp;view=code#L1">Source</a>
[external](https://example.test/a?x=1#part)
[local](#links)
""",
    )
    sha = commit(source)
    result = run(source, tmp_path)
    text = page(tmp_path, result, "docs/links.md")
    assert "(guide?mode=read#details)" in text
    assert '[nested]: deep--guide#part "Nested title"' in text
    assert f"/blob/{sha}/backend/core.py#L1" in text
    assert f"raw.githubusercontent.com/Gam1409/taleweaver/{sha}/docs/picture%20space.png" in text
    assert f"/blob/{sha}/backend/core.py?raw=1&amp;view=code#L1" in text
    assert "https://example.test/a?x=1#part" in text
    assert "[local](#links)" in text


def test_code_fences_and_inline_examples_are_preserved(source, tmp_path):
    example = "[example](guide.md)"
    put(
        source,
        "docs/code.md",
        f"# Code\n\n```markdown\n{example}\n```\n\n`{example}`\n\n{example}\n",
    )
    commit(source)
    result = run(source, tmp_path)
    text = page(tmp_path, result, "docs/code.md")
    assert f"```markdown\n{example}\n```" in text
    assert f"`{example}`" in text
    assert text.count(example) == 2
    assert "[example](guide)" in text


def test_name_collisions_and_reserved_pages_are_disambiguated(source, tmp_path):
    for name in ["docs/a b.md", "docs/a-b.md", "docs/project.md", "docs/Home.md", "docs/Guide.md"]:
        put(source, name, "# Another document\n")
    commit(source)
    result = run(source, tmp_path)
    names = list(result["pages"].values())
    assert len({name.casefold() for name in names}) == len(names)
    assert result["pages"]["README.md"] == "Project"
    assert result["pages"]["docs/README.md"] == "Home"
    assert result["pages"]["docs/a b.md"] != result["pages"]["docs/a-b.md"]
    assert result["pages"] == export_wiki.export(source, tmp_path / "other")["pages"]


def test_excluded_originals_and_licenses_link_to_pinned_source(source, tmp_path):
    original = "docs/research/chpm/CHPM_Research_Architecture_v0_2_RU.md"
    put(source, original, "# Immutable original\n")
    put(source, "frontend/public/assets/licenses/library-LICENSE.md", "Original notice\n")
    put(
        source,
        "docs/research/chpm/README.md",
        "# Research\n\n[Original](CHPM_Research_Architecture_v0_2_RU.md)\n",
    )
    sha = commit(source)
    result = run(source, tmp_path)
    assert original not in result["pages"]
    assert not any("LICENSE" in key for key in result["pages"])
    assert f"/blob/{sha}/{original}" in page(tmp_path, result, "docs/research/chpm/README.md")


def test_dirty_working_tree_is_never_exported(source, tmp_path):
    sha = git(source, "rev-parse", "HEAD")
    put(source, "docs/guide.md", "# Guide\nPrivate uncommitted draft.\n")
    result = run(source, tmp_path, revision=sha)
    text = page(tmp_path, result, "docs/guide.md")
    assert "Committed text" in text and "Private uncommitted" not in text
    assert result["revision"] == sha


def test_dry_run_creates_nothing_and_output_must_be_external(source, tmp_path):
    result = run(source, tmp_path, dry_run=True)
    assert result["pages"] and not (tmp_path / "wiki").exists()
    with pytest.raises(ValueError, match="outside"):
        export_wiki.export(source, source / "wiki")
    assert not (source / "wiki").exists()


def test_existing_unmanaged_home_is_protected_without_partial_writes(source, tmp_path):
    destination = tmp_path / "wiki"
    destination.mkdir()
    put(destination, "Home.md", "# Independently authored Home\n")
    with pytest.raises(ValueError, match="unmanaged"):
        run(source, tmp_path)
    assert [p.name for p in destination.iterdir()] == ["Home.md"]
    assert "Independently" in (destination / "Home.md").read_text()


def test_cleanup_removes_only_previous_generated_pages(source, tmp_path):
    first = run(source, tmp_path)
    old = tmp_path / "wiki" / (first["pages"]["docs/guide.md"] + ".md")
    put(tmp_path / "wiki", "Manual.md", "# Keep this page\n")
    (source / "docs/guide.md").unlink()
    commit(source)
    run(source, tmp_path)
    assert not old.exists()
    assert (tmp_path / "wiki/Manual.md").read_text() == "# Keep this page\n"


def test_edited_generated_pages_are_protected(source, tmp_path):
    first = run(source, tmp_path)
    changed = tmp_path / "wiki" / (first["pages"]["docs/guide.md"] + ".md")
    changed.write_text(changed.read_text() + "Manual edit.\n")
    with pytest.raises(ValueError, match="modified"):
        run(source, tmp_path)
    assert changed.read_text().endswith("Manual edit.\n")


def test_manifest_traversal_and_symlink_targets_are_rejected(source, tmp_path):
    destination = tmp_path / "wiki"
    destination.mkdir()
    put(
        destination,
        ".taleweaver-wiki-export.json",
        json.dumps({"version": 1, "files": {"../outside.md": "a" * 64}}),
    )
    with pytest.raises(ValueError, match="manifest"):
        run(source, tmp_path)
    (destination / ".taleweaver-wiki-export.json").unlink()
    outside = tmp_path / "outside.md"
    outside.write_text("Keep original")
    (destination / "Home.md").symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        run(source, tmp_path)
    assert outside.read_text() == "Keep original"


def test_ref_and_source_url_validation_and_text_budget(source, tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="revision"):
        run(source, tmp_path, revision="HEAD; execute")
    with pytest.raises(ValueError, match="source URL"):
        run(source, tmp_path, source_url="https://user:password@github.com/owner/repository")
    monkeypatch.setattr(export_wiki, "MAX_FILE_BYTES", 10)
    with pytest.raises(ValueError, match="size"):
        run(source, tmp_path)


def test_cli_dry_run_is_offline_and_prints_a_summary(source, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "export_wiki.py",
            "--repo",
            str(source),
            "--output",
            str(tmp_path / "wiki"),
            "--revision",
            "main",
            "--dry-run",
        ],
    )
    assert export_wiki.main() == 0
    assert json.loads(capsys.readouterr().out)["revision"] == git(source, "rev-parse", "HEAD")
    assert not (tmp_path / "wiki").exists()


def test_mermaid_diagrams_become_renderable_wiki_pages(source, tmp_path):
    put(source, "docs/diagrams/turn.mermaid", "flowchart TD\n  A --> B\n")
    put(source, "docs/diagrams.md", "# Diagrams\n\n[Turn](diagrams/turn.mermaid)\n")
    commit(source)
    result = run(source, tmp_path)
    assert "(diagrams--turn)" in page(tmp_path, result, "docs/diagrams.md")
    assert "```mermaid\nflowchart TD\n  A --> B\n```" in page(
        tmp_path, result, "docs/diagrams/turn.mermaid"
    )


def test_backticks_in_real_link_labels_and_reference_images(source, tmp_path):
    put(
        source,
        "docs/references.md",
        """# References
[`core.py`](../backend/core.py)
`[example](guide.md)`
![Picture][ART]
![icon][]
![shortcut]
[ART]: picture%20space.png
[icon]: <picture space.png>
[shortcut]: picture%20space.png
""",
    )
    sha = commit(source)
    result = run(source, tmp_path)
    text = page(tmp_path, result, "docs/references.md")
    assert f"[`core.py`](https://github.com/Gam1409/taleweaver/blob/{sha}/backend/core.py)" in text
    assert "`[example](guide.md)`" in text
    assert (
        text.count(f"raw.githubusercontent.com/Gam1409/taleweaver/{sha}/docs/picture%20space.png")
        == 3
    )


@pytest.mark.parametrize(
    "payload", ["not JSON", "[]", '{"version":true,"files":{}}', '{"version":1,"files":null}']
)
def test_malformed_export_manifest_is_rejected_without_writes(source, tmp_path, payload):
    destination = tmp_path / "wiki"
    destination.mkdir()
    put(destination, ".taleweaver-wiki-export.json", payload)
    with pytest.raises(ValueError, match="manifest"):
        run(source, tmp_path)
    assert [p.name for p in destination.iterdir()] == [".taleweaver-wiki-export.json"]


def test_managed_page_symlink_is_rejected(source, tmp_path):
    first = run(source, tmp_path)
    managed = tmp_path / "wiki" / (first["pages"]["docs/guide.md"] + ".md")
    managed.unlink()
    outside = tmp_path / "private.txt"
    outside.write_text("Preserve original")
    managed.symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        run(source, tmp_path)
    assert outside.read_text() == "Preserve original"


def test_unmanaged_case_variant_and_manifest_symlink_are_protected(source, tmp_path):
    destination = tmp_path / "wiki"
    destination.mkdir()
    put(destination, "HOME.md", "# Another Home\n")
    with pytest.raises(ValueError, match="unmanaged"):
        run(source, tmp_path)
    (destination / "HOME.md").unlink()
    outside = tmp_path / "manifest.json"
    outside.write_text("{}")
    (destination / ".taleweaver-wiki-export.json").symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        run(source, tmp_path)
    assert outside.read_text() == "{}"


def test_sidebar_avoids_missing_custom_index_anchors(source, tmp_path):
    put(source, "docs/README.md", "# Custom index\n\n## Different section\n")
    commit(source)
    run(source, tmp_path)
    sidebar = (tmp_path / "wiki/_Sidebar.md").read_text()
    assert "(Home)" in sidebar
    assert "#current-guides" not in sidebar and "#research-and-history" not in sidebar


def test_linked_images_rewrite_both_outer_targets_and_inner_images(source, tmp_path):
    put(source, "version.json", '{"version":"1.0"}\n')
    put(source, "LICENSE", "Original license notice.\n")
    literal = "[![Picture](picture%20space.png)](guide.md)"
    put(
        source,
        "docs/badges.md",
        "\n".join(
            [
                "# Badges",
                "[![Version](https://example.test/version.svg)](../version.json)",
                "[![Code: MIT](https://example.test/license.svg)](../LICENSE)",
                "[![Guide](picture%20space.png)](guide.md#details)",
                "[![Artwork](picture%20space.png)](picture%20space.png)",
                f"`{literal}`",
                "```markdown",
                literal,
                "```",
                "",
            ]
        ),
    )
    sha = commit(source)
    result = run(source, tmp_path)
    text = page(tmp_path, result, "docs/badges.md")
    raw = f"https://raw.githubusercontent.com/Gam1409/taleweaver/{sha}/docs/picture%20space.png"
    blob = f"https://github.com/Gam1409/taleweaver/blob/{sha}"
    assert f"[![Version](https://example.test/version.svg)]({blob}/version.json)" in text
    assert f"[![Code: MIT](https://example.test/license.svg)]({blob}/LICENSE)" in text
    assert f"[![Guide]({raw})](guide#details)" in text
    assert f"[![Artwork]({raw})]({blob}/docs/picture%20space.png)" in text
    assert f"`{literal}`" in text
    assert f"```markdown\n{literal}\n```" in text


def test_all_git_commands_disable_lazy_fetch_and_preserve_other_environment(monkeypatch, tmp_path):
    from types import SimpleNamespace

    calls = []
    monkeypatch.setenv("GIT_NO_LAZY_FETCH", "0")
    monkeypatch.setenv("WIKI_EXPORT_TEST_SENTINEL", "preserved")

    def command(arguments, **kwargs):
        environment = kwargs["env"]
        calls.append(
            (environment.get("GIT_NO_LAZY_FETCH"), environment.get("WIKI_EXPORT_TEST_SENTINEL"))
        )
        return SimpleNamespace(returncode=0, stdout=b"result")

    monkeypatch.setattr(export_wiki.subprocess, "run", command)
    for args in [("rev-parse", "HEAD"), ("ls-tree", "HEAD"), ("cat-file", "blob", "f" * 40)]:
        assert export_wiki._git(tmp_path, *args) == b"result"
    assert calls == [("1", "preserved")] * 3


def test_missing_local_object_fails_instead_of_continuing(source):
    with pytest.raises(ValueError, match="Cannot read"):
        export_wiki._git(source, "cat-file", "blob", "f" * 40)
