"""Skill auto-discovery and registry access.

Calling discover_skills() imports every non-underscore module in this
package, triggering __init_subclass__() registration on ActivitySkill
subclasses.  This happens once at module import time.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import Optional

from status_report.skills.base import ActivitySkill

logger = logging.getLogger(__name__)


def discover_skills() -> None:
    """Import all skill modules so their classes register themselves."""
    skills_dir = str(Path(__file__).parent)
    for _, name, _ in pkgutil.iter_modules([skills_dir]):
        if name.startswith("_"):
            continue
        module_name = f"status_report.skills.{name}"
        try:
            importlib.import_module(module_name)
            logger.debug("Discovered skill module: %s", module_name)
        except ImportError as exc:
            logger.warning("Failed to import skill module %s: %s", module_name, exc)


def get_enabled_skills(
    config: object,
    requested_sources: Optional[list[str]] = None,
) -> tuple[list[ActivitySkill], list[str]]:
    """Return configured-and-enabled skill instances plus unconfigured-but-requested names.

    Args:
        config: Config instance (passed to skill constructors).
        requested_sources: If provided, restrict to these skill names.
            Unknown names are warned about by the caller (main.py).

    Returns:
        A tuple of:
        - List of ActivitySkill instances whose is_configured() returns True.
        - List of skill names that were requested (known to registry) but not configured.
          These should be reported as skipped in the final report.
    """
    registry = ActivitySkill._registry
    enabled: list[ActivitySkill] = []
    not_configured: list[str] = []

    target_names = requested_sources if requested_sources is not None else list(registry.keys())

    for name in target_names:
        if name not in registry:
            # Unknown skill name — caller already warned; skip silently here
            continue
        skill_cls = registry[name]
        skill = skill_cls(config)
        if skill.is_configured():
            enabled.append(skill)
        else:
            if requested_sources is not None:
                # User explicitly requested this source but credentials are missing
                logger.warning(
                    "Skill '%s' was requested but is not configured (credentials missing) — skipping.",
                    name,
                )
                not_configured.append(name)
            else:
                logger.debug("Skill '%s' is not configured (credentials missing)", name)

    return enabled, not_configured


# Auto-discover at import time so skills are registered before any caller
# checks ActivitySkill._registry.
discover_skills()
