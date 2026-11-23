"""Verified bot catalogs, brain-family taxonomy, and Jev adopter repository lists."""

from __future__ import annotations

from typing import Iterable

# Verified clean 38-bot Tier-1 review catalog (aligned with AIDev construct-validity audit;
# bare "Copilot" and "copilot-swe-agent[bot]" coding-agent author replies are excluded).
TIER1_REVIEW_BOTS: tuple[str, ...] = (
    "copilot-pull-request-reviewer[bot]",
    "coderabbitai[bot]",
    "gemini-code-assist[bot]",
    "greptile-apps[bot]",
    "ellipsis-dev[bot]",
    "cubic-dev-ai[bot]",
    "entelligence-ai-pr-reviews[bot]",
    "entelligence-ai-pr-reviewer[bot]",
    "sourcery-ai[bot]",
    "claude[bot]",
    "cursor[bot]",
    "chatgpt-codex-connector[bot]",
    "graphite-app[bot]",
    "github-advanced-security[bot]",
    "github-code-quality[bot]",
    "codescene-delta-analysis[bot]",
    "recurseml[bot]",
    "kodus-ai[bot]",
    "qodo-merge-for-open-source[bot]",
    "qodo-merge-pro[bot]",
    "codiumai-pr-agent[bot]",
    "sonarqubecloud[bot]",
    "sonarcloud[bot]",
    "codacy-production[bot]",
    "codeant-ai[bot]",
    "korbit-ai[bot]",
    "qlty-cloud[bot]",
    "sweep-ai[bot]",
    "warden-ai[bot]",
    "DryRunSecurity[bot]",
    "delve-auditor[bot]",
    "jazzberry-ai[bot]",
    "deepsource-io[bot]",
    "semgrep-code-assistant-ws[bot]",
    "aikido-pr-checks[bot]",
    "seer-by-sentry[bot]",
    "windsurf-bot[bot]",
    "typesafe-jev[bot]",
)

# In pr_comments.parquet, graphite-app[bot] mostly posts merge-queue/automation banners,
# whereas its real code reviews reside in pr_reviews.parquet and pr_review_comments_v2.parquet.
TIER1_PR_COMMENTS_BOTS: tuple[str, ...] = tuple(
    bot for bot in TIER1_REVIEW_BOTS if bot != "graphite-app[bot]"
)

# Deterministic SAST / static invariant screening bots within the 38-bot catalog.
DETERMINISTIC_SAST_BOTS: tuple[str, ...] = (
    "github-advanced-security[bot]",
    "github-code-quality[bot]",
    "sonarqubecloud[bot]",
    "sonarcloud[bot]",
    "codacy-production[bot]",
    "deepsource-io[bot]",
    "semgrep-code-assistant-ws[bot]",
    "aikido-pr-checks[bot]",
    "DryRunSecurity[bot]",
)

# Bot/agent logins excluded from reviewer attribution to prevent coding-agent self-reply
# or CI/dependency-bump contamination.
EXCLUDED_AUTHOR_BOT_ACTORS: tuple[str, ...] = (
    "Copilot",
    "copilot-swe-agent[bot]",
    "github-actions[bot]",
    "dependabot[bot]",
    "dependabot-preview[bot]",
    "renovate[bot]",
    "pyup-bot",
)

# Bot-operated User-typed accounts discovered in Jev adopter repositories.
JEV_EXTRA_BOT_LOGINS: tuple[str, ...] = (
    "loopway-bot",
    "all-hands-bot",
    "sentry-bot",
)

# 8 already-cloned Jev signal adopter repositories + 18 additional Jev adopter repositories.
JEV_ADOPTER_REPOS: tuple[str, ...] = (
    # 8 already-cloned Jev signal repositories
    "getsentry/sentry",
    "marufeuille/xteink-read-later",
    "craftmilldev/loopway",
    "craftmilldev/sesh",
    "Tgenz1213/ArchGuard",
    "mirrorstack-ai/mirrorstack-cli",
    "craftmilldev/sfml",
    "getsentry/sentry-php",
    # 18 additional Jev adopter repositories for sample-size broadening
    "optomachina/Overdrafter",
    "lolotam/PayPos.systems",
    "lolotam/POSTORA",
    "jaubut/claude-companion",
    "grixu/cc-toolkit",
    "OpenHands/OpenHands",
    "OpenHands/software-agent-sdk",
    "lolotam/eyadex",
    "lolotam/MergePilot",
    "PostHog/posthog",
    "Advanced-Digital-Marketing-LTDA/island-life-custom-pools",
    "verJSON/.github",
    "zeroasterisk/aaif-wiki",
    "Jev-Engineering/jraphyte",
    "career-ops-hq/career-ops",
    "markjspivey-xwisee/interego",
    "jeff-kunkun/multica",
    "sazlin/loadout",
)

# Multi-model RAG / agentic prose review bots within the 38-bot catalog.
MULTIMODEL_RAG_BOTS: tuple[str, ...] = (
    "coderabbitai[bot]",
    "greptile-apps[bot]",
    "ellipsis-dev[bot]",
    "cubic-dev-ai[bot]",
    "sourcery-ai[bot]",
    "qodo-merge-pro[bot]",
    "qodo-merge-for-open-source[bot]",
    "codiumai-pr-agent[bot]",
    "cursor[bot]",
    "entelligence-ai-pr-reviews[bot]",
    "entelligence-ai-pr-reviewer[bot]",
    "codeant-ai[bot]",
    "korbit-ai[bot]",
    "kodus-ai[bot]",
)

_MULTIMODEL_RAG_BOTS: frozenset[str] = frozenset(MULTIMODEL_RAG_BOTS)

_SAST_BOTS_LOWER: frozenset[str] = frozenset(b.lower() for b in DETERMINISTIC_SAST_BOTS)
_MULTIMODEL_RAG_BOTS_LOWER: frozenset[str] = frozenset(b.lower() for b in MULTIMODEL_RAG_BOTS)
_EXCLUDED_BOTS_LOWER: frozenset[str] = frozenset(b.lower() for b in EXCLUDED_AUTHOR_BOT_ACTORS)
_JEV_EXTRA_BOTS_LOWER: frozenset[str] = frozenset(b.lower() for b in JEV_EXTRA_BOT_LOGINS)
_TIER1_BOTS_LOWER: frozenset[str] = frozenset(b.lower() for b in TIER1_REVIEW_BOTS)


def is_bot_login(login: str) -> bool:
    """Return True if a GitHub actor login matches known bot suffixes or explicit bot catalogs."""
    low = (login or "").strip().lower()
    if not low:
        return False
    if low.endswith("[bot]") or low.endswith("-bot"):
        return True
    return (
        low in _JEV_EXTRA_BOTS_LOWER
        or low in _EXCLUDED_BOTS_LOWER
        or low in _TIER1_BOTS_LOWER
    )


def sql_in_list(items: Iterable[str]) -> str:
    """Format an iterable of strings as a single-quoted SQL IN-list literal."""
    escaped = []
    for item in items:
        s = str(item).replace("'", "''")
        escaped.append(f"'{s}'")
    return ", ".join(escaped) if escaped else "NULL"


def clean_jev_author_origin_sql(
    author_login_col: str = "author_login",
    author_origin_col: str = "author_origin",
) -> str:
    """Return SQL CASE expression reclassifying bot-operated Human_Engineer logins dynamically."""
    extra_in = sql_in_list(sorted(_JEV_EXTRA_BOTS_LOWER))
    low_login = f"LOWER(COALESCE({author_login_col}, ''))"
    bot_cond = (
        f"({low_login} LIKE '%-bot' "
        f"OR {low_login} LIKE '%[bot]' "
        f"OR {low_login} IN ({extra_in}))"
    )
    return (
        f"(CASE "
        f"WHEN {author_origin_col} = 'Human_Engineer' AND {bot_cond} THEN "
        f"(CASE WHEN {low_login} = 'all-hands-bot' THEN 'Coding_Agent' ELSE 'Automation_Bot' END) "
        f"ELSE {author_origin_col} END)"
    )


def is_human_login_sql(login_col: str = "author_login") -> str:
    """Return SQL predicate excluding [bot], -bot, and JEV_EXTRA_BOT_LOGINS accounts."""
    extra_in = sql_in_list(sorted(_JEV_EXTRA_BOTS_LOWER))
    low_login = f"LOWER(COALESCE({login_col}, ''))"
    return (
        f"{low_login} NOT LIKE '%[bot]' "
        f"AND {low_login} NOT LIKE '%-bot' "
        f"AND {low_login} NOT IN ({extra_in})"
    )


def classify_bot_brain_family(bot_login: str) -> str:
    """Classify a review bot login into its canonical empirical brain-family regime."""
    login = (bot_login or "").strip()
    low = login.lower()
    if low in _SAST_BOTS_LOWER:
        return "1_Deterministic_SAST_Brain"
    if low in _MULTIMODEL_RAG_BOTS_LOWER:
        return "2_MultiModel_RAG_Agentic_Brain"
    if low in {"copilot-pull-request-reviewer[bot]", "chatgpt-codex-connector[bot]"}:
        return "3_OpenAI_Copilot_Native_Brain"
    if low == "gemini-code-assist[bot]":
        return "4_Google_Gemini_Native_Brain"
    if low == "claude[bot]":
        return "5_Anthropic_Claude_Native_Brain"
    return "6_Other_Bot_Engine"
