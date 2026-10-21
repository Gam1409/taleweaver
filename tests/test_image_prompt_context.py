from backend.engine.image_prompt_context import (
    MAX_APPEARANCE_LENGTH,
    MAX_PLOT_CONTEXT_LENGTH,
    MAX_SCENE_NPCS,
    build_npc_image_prompt,
    build_object_image_prompt,
    build_protagonist_image_prompt,
    build_scene_image_prompt,
    clean_appearance,
    manifest_scene_npcs,
    protagonist_context,
    scene_context,
)


def test_scene_prompt_includes_decorations_and_npcs():
    # Arrange
    npcs = [{"name": "Old Librarian", "description": "A hunched man with ink-stained fingers."}]

    # Act
    prompt = build_scene_image_prompt(
        "Library", "Dusty shelves.", decorative_objects=["candelabra", "globe"], npcs=npcs
    )

    # Assert
    assert prompt.startswith("Background scene: Library. Dusty shelves. ")
    assert "candelabra, globe" in prompt
    assert "Old Librarian (A hunched man with ink-stained fingers.)" in prompt
    assert "3:2 aspect ratio" in prompt


def test_scene_prompt_without_context_keeps_base_template():
    # Act
    prompt = build_scene_image_prompt("Cave", "Dark and damp.")

    # Assert
    assert prompt.startswith("Background scene: Cave. Dark and damp. 3:2 aspect ratio")


def test_scene_context_limits_npcs_and_skips_blank_decorations():
    # Arrange
    npcs = [{"name": f"NPC {i}", "description": ""} for i in range(MAX_SCENE_NPCS + 2)]

    # Act
    context = scene_context(["  ", "lantern"], npcs)

    # Assert
    assert "Visible details in the environment: lantern." in context
    assert f"NPC {MAX_SCENE_NPCS - 1}" in context
    assert f"NPC {MAX_SCENE_NPCS}" not in context


def test_manifest_scene_npcs_filters_by_scene_and_visibility():
    # Arrange
    npcs = [
        {"id": "A", "name": "A", "start_scene_id": "HALL"},
        {"id": "B", "name": "B", "current_scene_id": "CELLAR"},
        {"id": "C", "name": "C"},
        {"id": "D", "name": "D", "start_scene_id": "HALL", "is_hidden": True},
    ]

    # Act
    hall = manifest_scene_npcs(npcs, "HALL", default_scene_id="HALL")
    cellar = manifest_scene_npcs(npcs, "CELLAR", default_scene_id="HALL")

    # Assert
    assert [npc["id"] for npc in hall] == ["A", "C"]
    assert [npc["id"] for npc in cellar] == ["B"]


def test_protagonist_prompt_includes_clipped_plot():
    # Arrange
    plot = "A steampunk heist in Victorian London. " * 100

    # Act
    prompt = build_protagonist_image_prompt("Ada", "Thief", "Wiry and quick.", plot=plot)
    context = protagonist_context(plot)

    # Assert
    assert prompt.startswith("Portrait of character Ada, Thief. Wiry and quick. Adventure setting")
    assert "steampunk heist" in prompt
    assert context.endswith("...")
    assert len(context) < MAX_PLOT_CONTEXT_LENGTH + 200


def test_protagonist_prompt_without_plot_has_no_context():
    # Act
    prompt = build_protagonist_image_prompt("Ada", "Thief", "Wiry and quick.", plot="  ")

    # Assert
    assert "Adventure setting" not in prompt
    assert "Wiry and quick. Game attribute art style." in prompt


def test_clean_appearance_collapses_whitespace_and_clips():
    # Act
    cleaned = clean_appearance("  tall,\n  scarred   face " + "x" * 200)

    # Assert
    assert cleaned is not None
    assert cleaned.startswith("tall, scarred face x")
    assert len(cleaned) == MAX_APPEARANCE_LENGTH
    assert clean_appearance("   ") is None
    assert clean_appearance(None) is None


def test_npc_and_object_prompts_include_appearance():
    # Act
    npc_prompt = build_npc_image_prompt("Guard", "A bored guard.", "burly, chainmail, red cape")
    object_prompt = build_object_image_prompt("Key", "A key.", "brass, ornate bow")
    plain_prompt = build_npc_image_prompt("Guard", "A bored guard.")

    # Assert
    assert "A bored guard. Visual keywords: burly, chainmail, red cape. Game" in npc_prompt
    assert "A key. Visual keywords: brass, ornate bow. Centered" in object_prompt
    assert "Visual keywords" not in plain_prompt


def test_protagonist_prompt_puts_appearance_before_plot():
    # Act
    prompt = build_protagonist_image_prompt(
        "Ada", "Thief", "Wiry.", plot="Heist in London.", appearance="red hair, goggles"
    )

    # Assert
    assert prompt.index("Visual keywords: red hair, goggles.") < prompt.index("Adventure setting")


def test_scene_npc_phrase_prefers_appearance_over_description():
    # Arrange
    npcs = [{"name": "Guard", "description": "Long biography text.", "appearance": "burly, chainmail"}]

    # Act
    context = scene_context(None, npcs)

    # Assert
    assert "Guard (burly, chainmail)" in context
    assert "biography" not in context
