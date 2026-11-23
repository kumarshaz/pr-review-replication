#!/usr/bin/env python3
"""
Base Dataset Handler Interface
==============================
Defines the standardized contract for raw empirical dataset processing handlers.
Every software engineering dataset in the multi-corpus analysis suite implements
this interface, enabling fully extensible, data-driven triangulation without modifying
orchestration or collation pipelines.
"""

from abc import ABC, abstractmethod
import os
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from config.paths import get_paths

if TYPE_CHECKING:
    from config.paths import PathConfig


class BaseDatasetHandler(ABC):
    """Abstract base class for all empirical dataset handlers."""

    def __init__(
        self,
        paths: Optional["PathConfig"] = None,
        scratch_dir: Optional[Union[str, os.PathLike]] = None,
    ) -> None:
        if paths is not None and hasattr(paths, "pr_analysis_root") and hasattr(paths, "scratch_dir"):
            resolved_paths = paths
            self.paths = resolved_paths
            self.repo_root: str = str(resolved_paths.pr_analysis_root)
            self.scratch_dir: str = str(resolved_paths.scratch_dir)
        else:
            fallback_paths = get_paths()
            self.paths = fallback_paths
            self.repo_root = str(paths) if paths is not None else str(fallback_paths.pr_analysis_root)
            self.scratch_dir = str(scratch_dir) if scratch_dir is not None else str(fallback_paths.scratch_dir)

        self.results_dir: str = str(self.paths.results_dir)
        self.tables_dir: str = str(self.paths.tables_dir)
        self.archives_dir: str = str(self.paths.archives_dir)

    def scratch_path(self, *parts: str) -> str:
        """Resolve a path inside the configured scratch directory."""
        return os.path.join(self.scratch_dir, *parts)

    def table_path(self, *parts: str) -> str:
        """Resolve an output table path inside tables_dir, creating it if needed."""
        os.makedirs(self.tables_dir, exist_ok=True)
        return os.path.join(self.tables_dir, *parts)

    def result_path(self, *parts: str) -> str:
        """Resolve an output artifact path inside results_dir, creating it if needed."""
        os.makedirs(self.results_dir, exist_ok=True)
        return os.path.join(self.results_dir, *parts)

    def archive_path(self, *parts: str) -> str:
        """Resolve a path inside the configured archives directory."""
        return os.path.join(self.archives_dir, *parts)

    @property
    @abstractmethod
    def dataset_id(self) -> str:
        """Unique snake_case identifier (e.g. 'dataset_1_aidev_full')."""
        pass

    @property
    @abstractmethod
    def dataset_name(self) -> str:
        """Human-readable corpus title (e.g. 'AIDev-Full & AIDev')."""
        pass

    @property
    @abstractmethod
    def primary_entity(self) -> str:
        """Primary software engineering entity analyzed (e.g. 'Pull Requests (Human vs Agent)')."""
        pass

    @property
    @abstractmethod
    def lemon_market_implication(self) -> str:
        """Theoretical implication regarding supervisory friction or lemon market dynamics."""
        pass

    @property
    @abstractmethod
    def raw_files(self) -> List[str]:
        """Relative paths to raw input files in scratch/ from repository root."""
        pass

    @property
    @abstractmethod
    def calculating_programs(self) -> List[str]:
        """Scripts contributing to the extraction and calculation of this corpus."""
        pass

    @property
    def telemetry_capabilities(self) -> List[str]:
        """List of telemetry capabilities this dataset provides (e.g. 'pr_acceptance', 'review_latency')."""
        return []

    @abstractmethod
    def execute(self, con: Any, repo_root: Optional[str] = None) -> Dict[str, Any]:
        """
        Executes DuckDB, SQLite, or file-level queries over raw scratch files.
        Returns a JSON-serializable dictionary of empirical findings.
        """
        pass

    @abstractmethod
    def get_summary_row(self, result: Dict[str, Any]) -> List[Any]:
        """
        Returns a list of 5 summary fields for multi_dataset_summary_log.csv:
        [primary_entity, sample_size_n, key_metric_1, key_metric_2, lemon_market_implication]
        """
        pass
