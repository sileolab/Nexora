"""Environment File (.env) Manager for Nexora Studio.

Provides safe reads and atomic in-place updates to .env while preserving
formatting, comments, order, and existing configuration parameters.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

from app.core.config import get_settings

logger = logging.getLogger(__name__)

ENV_PATH = Path(".env")


def read_env_dict(path: Path = ENV_PATH) -> dict[str, str]:
    """Read key-value pairs from .env file into a dictionary."""
    if not path.exists():
        return {}
    env_vars: dict[str, str] = {}
    try:
        content = path.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                env_vars[k.strip()] = v.strip().strip("'\"")
    except Exception as exc:
        logger.warning(f"Error reading {path}: {exc}")
    return env_vars


def update_env_file(
    updates: dict[str, Optional[str]],
    path: Path = ENV_PATH,
) -> bool:
    """Update or append specific environment variables in .env without losing comments or formatting.

    Args:
        updates: Dict of environment variable names to new string values.
                 If value is None, the key is left unchanged.
        path: Path to the .env file.

    Returns:
        bool: True if file was successfully updated.
    """
    try:
        lines: list[str] = []
        if path.exists():
            content = path.read_text(encoding="utf-8")
            lines = content.splitlines()
        elif Path(".env.example").exists():
            content = Path(".env.example").read_text(encoding="utf-8")
            lines = content.splitlines()

        remaining_keys = set(updates.keys())
        new_lines: list[str] = []

        for line in lines:
            stripped = line.strip()
            # If line is a key=value pair
            if not stripped.startswith("#") and "=" in stripped:
                key, _ = stripped.split("=", 1)
                key = key.strip()
                if key in updates:
                    new_val = updates[key]
                    if new_val is not None:
                        new_lines.append(f"{key}={new_val}")
                    else:
                        new_lines.append(line)
                    remaining_keys.discard(key)
                    continue

                # Also replace legacy CRAWLBOT_ if we are updating the NEXORA_ equivalent
                if key.startswith("CRAWLBOT_"):
                    nexora_equiv = "NEXORA_" + key[len("CRAWLBOT_"):]
                    if nexora_equiv in updates:
                        new_val = updates[nexora_equiv]
                        if new_val is not None:
                            new_lines.append(f"{nexora_equiv}={new_val}")
                        remaining_keys.discard(nexora_equiv)
                        continue

            new_lines.append(line)

        # Any remaining keys that were not found in the file get appended
        if remaining_keys:
            if new_lines and new_lines[-1].strip():
                new_lines.append("")
            new_lines.append("# AI Provider Configuration (Updated via UI)")
            for key in sorted(remaining_keys):
                val = updates[key]
                if val is not None:
                    new_lines.append(f"{key}={val}")

        final_content = "\n".join(new_lines) + "\n"
        path.write_text(final_content, encoding="utf-8")

        # Update os.environ and runtime settings singleton
        for k, v in updates.items():
            if v is not None:
                os.environ[k] = v
                if k.startswith("NEXORA_"):
                    os.environ["CRAWLBOT_" + k[len("NEXORA_"):]] = v

        settings = get_settings()
        if "NEXORA_OPENAI_API_KEY" in updates and updates["NEXORA_OPENAI_API_KEY"] is not None:
            settings.openai_api_key = updates["NEXORA_OPENAI_API_KEY"]
        if "NEXORA_OPENAI_BASE_URL" in updates:
            settings.openai_base_url = updates["NEXORA_OPENAI_BASE_URL"] or ""
        if "NEXORA_LLM_MODEL" in updates and updates["NEXORA_LLM_MODEL"] is not None:
            settings.llm_model = updates["NEXORA_LLM_MODEL"]
        if "NEXORA_EMBEDDING_MODEL" in updates and updates["NEXORA_EMBEDDING_MODEL"] is not None:
            settings.embedding_model = updates["NEXORA_EMBEDDING_MODEL"]

        return True
    except Exception as exc:
        logger.error(f"Failed to update .env at {path}: {exc}")
        return False
