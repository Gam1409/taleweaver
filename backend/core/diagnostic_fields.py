"""Strict metadata-only serialization for the system diagnostic log."""

import math
import re
from pathlib import Path
from uuid import UUID

EVENTS = {
    "inference.queued",
    "inference.admitted",
    "inference.sent",
    "inference.completed",
    "inference.uncertain",
    "inference.blocked",
    "npc.learning.phase",
    "npc.presentation",
    "npc.behavior_fallback",
    "http.started",
    "http.completed",
    "http.failed",
    "http.cancelled",
    "http.disconnected",
    "llm.started",
    "llm.completed",
    "llm.failed",
    "llm.cancelled",
    "llm.retry",
    "llm.output_contract",
    "embedding.started",
    "embedding.completed",
    "embedding.failed",
    "embedding.cancelled",
    "image.started",
    "image.completed",
    "image.failed",
    "image.cancelled",
    "job.started",
    "job.completed",
    "job.failed",
    "job.cancelled",
    "db.query",
    "db.error",
    "db.transaction",
    "system.log",
    "diagnostics.enabled",
    "diagnostics.disabled",
    "adventure.generation.apply_manifest.complete",
    "adventure.generation.apply_manifest.start",
    "adventure.generation.manifest_received",
    "adventure.generation.start",
    "adventure.generation.status",
    "adventure.generation.world_applied",
    "gm.turn.memory_recall",
    "gm.turn.pipeline.context",
    "gm.turn.pipeline.cycle_total",
    "gm.turn.pipeline.pass",
    "gm.turn.pipeline.tokens",
    "gm.turn.pipeline.total",
    "gm.turn.response",
    "gm.turn.request",
    "gm.turn.stream.request",
    "llm_interaction",
}
IDENTIFIERS = {
    "reservation_id",
    "request_id",
    "session_id",
    "game_id",
    "adventure_id",
    "turn_id",
    "message_id",
    "call_id",
}
NUMBERS = {
    "queue_ms",
    "provider_attempts",
    "ttft_ms",
    "stream_generation_ms",
    "prefill_ms",
    "server_generation_ms",
    "model_load_ms",
    "delay_ms",
    "duration_ms",
    "elapsed_ms",
    "status_code",
    "bytes_sent",
    "chunks",
    "attempt",
    "attempts",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cached_prompt_tokens",
    "timeout",
    "timeout_seconds",
    "max_tokens",
    "message_count",
    "history_messages",
    "history_messages_count",
    "memory_turns",
    "chars",
    "count",
    "documents",
    "candidates",
    "selected_count",
    "input_chars",
    "output_chars",
    "duration_seconds",
    "retrieved_chars",
    "local_check_count",
}
ENUMS = {
    "output_mode": {"prompt", "json_object", "json_schema"},
    "operation": {
        "simple",
        "structured",
        "stream",
        "embedding",
        "image",
        "memory_maintenance",
        "npc_learning",
        "npc_portrait",
        "scene_background",
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
        "BEGIN",
        "COMMIT",
        "ROLLBACK",
        "PRAGMA",
        "OTHER",
    },
    "role": {
        "small",
        "complex",
        "generator",
        "compression",
        "play_agent",
        "narration",
        "mechanics",
        "utility",
    },
    "provider": {
        "bfl",
        "black_forest_labs",
        "comfyui",
        "sd",
        "stable_diffusion",
        "automatic1111",
        "forge",
        "openai",
        "custom_openai",
        "ollama",
        "ollama_chat",
        "openrouter",
        "anthropic",
        "gemini",
        "google",
        "deepseek",
        "kimi",
        "minimax",
        "together_ai",
        "fireworks_ai",
        "groq",
        "mistral",
        "xai",
    },
    "method": {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"},
}

ENUMS["retrieval_method"] = {"disabled", "hybrid", "sql_lexical"}
ENUMS["audience"] = {"narrator", "vn_continuity", "vn_social"}
ENUMS["fallback_reason"] = {
    "analysis_failed",
    "review_unavailable",
    "review_rejected",
    "narration_incomplete",
    "cooldown",
}
ENUMS["presentation_reason"] = {
    "disabled",
    "no_visible_cast",
    "incomplete_narration",
    "missing_footer",
    "incomplete_footer",
    "footer_too_large",
    "invalid_json",
    "invalid_entries",
    "no_valid_entries",
    "source_mismatch",
    "available",
}
ENUMS["inference_reason"] = {
    "completion_unconfirmed",
    "caller_cancelled",
    "request_timeout",
    "incomplete_stream",
    "connection_failure",
    "provider_or_processing_error",
}

ENUMS["purpose"] = {
    "wardrobe_recovery",
    "item_repair",
    "living_world_decision",
    "living_world_dialogue_choice",
    "chpm_evaluation",
    "narrated_items",
    "scene_staging",
    "rp_continuation",
    "regenerate_narration",
    "chpm",
    "image_prompt",
    "ai_fix",
    "generate_world",
    "translate_text_log",
    "vn_social",
    "session_illustration",
    "combat.special_event",
    "npc_journal",
    "chat_turn",
    "agent_turn",
    "editor_clothing_conversion",
    "history_compression",
    "visible_frame",
    "memory_summary",
}
ENUMS["phase"] = {
    "preview",
    "schema_retry",
    "evidence_retry",
    "agent_lookup",
    "repair",
    "rp_continuation",
    "reconciliation",
    "proposal",
    "proposal_repair",
    "perception",
    "review",
    "narration_repair",
    "agent",
    "prompt_preparation",
    "suggestions",
    "preparing",
    "extracting",
    "waiting_to_save",
    "saving",
    "npc_summary",
    "scene_summary",
    "story_summary",
    "prompt_suggestions",
    "apply_manifest",
    "chat_progression",
    "mechanics",
    "decision",
    "context",
    "total",
    "narration",
    "reaction_plan",
    "dynamic_location",
    "translation",
    "cycle_total",
    "generator_tool_intent",
    "inspect_search_intent_guard",
    "observations",
}


def safe_fields(fields: dict) -> dict:
    result = {}
    for key, value in fields.items():
        if key == "schema_fingerprint" and isinstance(value, str):
            if re.fullmatch(r"[a-f0-9]{64}", value):
                result[key] = value
        elif key in IDENTIFIERS and isinstance(value, str):
            try:
                result[key] = str(UUID(value))
            except ValueError:
                continue
        elif (
            key in NUMBERS
            and type(value) in (int, float)
            and abs(value) <= 1e15
            and math.isfinite(value)
            or key in ENUMS
            and isinstance(value, str)
            and value in ENUMS[key]
            or key in {"final_sent", "streaming", "success", "thinking"}
            and type(value) is bool
        ):
            result[key] = value
    return result


def safe_error(error: BaseException) -> dict:
    """Never inspect exception text/args, SQL parameters, source lines or locals."""
    result: dict[str, object] = {"type": type(error).__name__}
    frames = []
    trace = error.__traceback__
    while trace is not None:
        code = trace.tb_frame.f_code
        frames.append(
            {"file": Path(code.co_filename).name, "function": code.co_name, "line": trace.tb_lineno}
        )
        trace = trace.tb_next
    result["frames"] = frames[-20:]
    status = getattr(error, "status_code", None)
    if type(status) is int:
        result["status_code"] = status
    original = getattr(error, "orig", error)
    sqlite_code = getattr(original, "sqlite_errorcode", None)
    if type(sqlite_code) is int:
        result["sqlite_code"] = sqlite_code
    cause = error.__cause__ or error.__context__
    if cause is not None:
        result["cause_type"] = type(cause).__name__
    return result
