"""Configuration package for pr-analysis."""

from config.bot_catalog import (
    DETERMINISTIC_SAST_BOTS,
    EXCLUDED_AUTHOR_BOT_ACTORS,
    JEV_ADOPTER_REPOS,
    TIER1_PR_COMMENTS_BOTS,
    TIER1_REVIEW_BOTS,
    classify_bot_brain_family,
    sql_in_list,
)
from config.paths import PathConfig, get_paths, resolve_scratch_file

__all__ = [
    "PathConfig",
    "get_paths",
    "resolve_scratch_file",
    "TIER1_REVIEW_BOTS",
    "TIER1_PR_COMMENTS_BOTS",
    "DETERMINISTIC_SAST_BOTS",
    "EXCLUDED_AUTHOR_BOT_ACTORS",
    "JEV_ADOPTER_REPOS",
    "sql_in_list",
    "classify_bot_brain_family",
]
