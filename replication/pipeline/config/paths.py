"""Standalone path isolation and environment-overridable path configuration for pr-review-replication."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PathConfig:
    """Resolved immutable paths for pr-review-replication pipelines and outputs."""

    pr_analysis_root: Path
    scratch_dir: Path
    clones_dir: Path
    results_dir: Path
    tables_dir: Path
    logs_dir: Path
    archives_dir: Path
    manifest_path: Path
    research_workspace_root: Path

    def ensure_dirs(self) -> None:
        """Create required output, table, log, and archive directories."""
        for directory in (
            self.results_dir,
            self.tables_dir,
            self.logs_dir,
            self.archives_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def _resolve_scratch_dir(repo_root: Path) -> Path:
    for env_key in ("PR_REVIEW_SCRATCH_DIR", "PR_ANALYSIS_SCRATCH_DIR"):
        env_scratch = os.environ.get(env_key, "").strip()
        if env_scratch:
            return Path(env_scratch).expanduser().resolve()

    for candidate in (
        repo_root / "scratch",
        repo_root / "data" / "raw",
    ):
        if candidate.exists() and (
            (candidate / "aidev").exists() or (candidate / "coderabbit").exists()
        ):
            return candidate.resolve()

    return (repo_root / "scratch").resolve()


def get_paths() -> PathConfig:
    """Resolve all canonical pr-review-replication directory and manifest paths."""
    pipeline_root = Path(__file__).resolve().parents[1]
    repo_root = pipeline_root.parents[1]

    env_root = os.environ.get("PR_ANALYSIS_ROOT", "").strip()
    pr_analysis_root = (
        Path(env_root).expanduser().resolve() if env_root else pipeline_root
    )
    scratch_dir = _resolve_scratch_dir(repo_root)

    env_clones = (
        os.environ.get("PR_REVIEW_CLONES_DIR", "").strip()
        or os.environ.get("PR_ANALYSIS_CLONES_DIR", "").strip()
    )
    clones_dir = (
        Path(env_clones).expanduser().resolve()
        if env_clones
        else (scratch_dir / "git_clones").resolve()
    )

    env_results = (
        os.environ.get("PR_REVIEW_RESULTS_DIR", "").strip()
        or os.environ.get("PR_ANALYSIS_RESULTS_DIR", "").strip()
    )
    results_dir = (
        Path(env_results).expanduser().resolve()
        if env_results
        else (repo_root / "replication" / "results" / "pr_review").resolve()
    )

    tables_dir = results_dir / "data_tables"

    env_logs = (
        os.environ.get("PR_REVIEW_LOGS_DIR", "").strip()
        or os.environ.get("PR_ANALYSIS_LOGS_DIR", "").strip()
    )
    logs_dir = (
        Path(env_logs).expanduser().resolve()
        if env_logs
        else (repo_root / "replication" / "logs").resolve()
    )

    archives_dir = pipeline_root / "data" / "archives"
    manifest_path = pipeline_root / "config" / "datasets_manifest.toml"

    return PathConfig(
        pr_analysis_root=pr_analysis_root,
        scratch_dir=scratch_dir,
        clones_dir=clones_dir,
        results_dir=results_dir,
        tables_dir=tables_dir,
        logs_dir=logs_dir,
        archives_dir=archives_dir,
        manifest_path=manifest_path,
        research_workspace_root=repo_root,
    )


def resolve_scratch_file(*parts: str) -> Path:
    """Join path segments onto the active scratch_dir and return the resolved Path."""
    clean_parts = [p.lstrip("/") for p in parts if p]
    return get_paths().scratch_dir.joinpath(*clean_parts)
