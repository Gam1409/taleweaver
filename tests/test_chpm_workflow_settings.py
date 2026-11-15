"""Input-budget warnings describe committed configuration changes without private context."""

import logging

from tests.test_chpm_api import PATH, chpm_world, portrait_world, update

__all__ = ["chpm_world", "portrait_world"]


async def test_warning_only_follows_a_committed_input_budget_increase(
    auth_client, chpm_world, caplog
):
    owner = "backend.api.routes.adventures.chpm"
    with caplog.at_level(logging.WARNING, logger=owner):
        increased = update("live", workflow="integrated", max_input_chars=48000)
        response = await auth_client.patch(PATH, json=increased)
        assert response.status_code == 200, response.text
        assert response.json()["settings"]["max_input_chars"] == 48000
        records = [record for record in caplog.records if record.name == owner]
        assert len(records) == 1
        assert records[0].levelno == logging.WARNING
        message = records[0].getMessage()
        assert "24000" in message and "48000" in message and "integrated" in message
        assert "NPC_NEW" not in message and "portrait-session" not in message
        rejected = update("live", workflow="integrated", max_input_chars=96000)
        assert (await auth_client.patch(PATH, json=rejected)).status_code == 409
        increased["expected_revision"] = 1
        assert (await auth_client.patch(PATH, json=increased)).status_code == 200
        lower = update("live", revision=1, workflow="integrated", max_input_chars=32000)
        assert (await auth_client.patch(PATH, json=lower)).status_code == 200
        assert len([record for record in caplog.records if record.name == owner]) == 1
