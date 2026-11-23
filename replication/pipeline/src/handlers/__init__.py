#!/usr/bin/env python3
"""
Dynamic Dataset Handler Discovery & Registry
============================================
Discovers, instantiates, and registers all BaseDatasetHandler implementations
in src/handlers/. When a new raw dataset is added, simply drop a new handler file
into this directory—the analysis pipeline will automatically incorporate it into
triangulation and collation without any modifications to orchestrators or collation scripts.
"""

import importlib
import inspect
import logging
import os
import re
from typing import TYPE_CHECKING, List, Optional, Type

from src.handlers.base import BaseDatasetHandler

if TYPE_CHECKING:
    from config.paths import PathConfig

logger = logging.getLogger(__name__)


def _discover_handler_classes() -> List[Type[BaseDatasetHandler]]:
    handlers_dir = os.path.dirname(os.path.abspath(__file__))
    handler_classes: List[Type[BaseDatasetHandler]] = []

    for fname in sorted(os.listdir(handlers_dir)):
        if fname.endswith(".py") and not fname.startswith("__") and fname != "base.py":
            mod_name = f"src.handlers.{fname[:-3]}"
            try:
                mod = importlib.import_module(mod_name)
                for attr_name in dir(mod):
                    attr = getattr(mod, attr_name)
                    if (
                        inspect.isclass(attr)
                        and issubclass(attr, BaseDatasetHandler)
                        and attr is not BaseDatasetHandler
                    ):
                        handler_classes.append(attr)
            except Exception as e:
                logger.warning("Could not load dataset handler from %s: %s", fname, e)

    # Sort handlers naturally by filename / index (e.g. d01, d02, ... d16, d17)
    def _sort_key(cls: Type[BaseDatasetHandler]) -> int:
        match_mod = re.search(r"d(\d+)", cls.__module__)
        if match_mod:
            return int(match_mod.group(1))
        try:
            instance = cls()
            match_id = re.search(r"dataset_(\d+)", instance.dataset_id)
            if match_id:
                return int(match_id.group(1))
        except Exception:
            pass
        return 999

    return sorted(handler_classes, key=_sort_key)


def get_all_dataset_handlers(paths: Optional["PathConfig"] = None) -> List[BaseDatasetHandler]:
    """Instantiate and return all registered dataset handlers in natural order."""
    classes = _discover_handler_classes()
    return [cls(paths=paths) for cls in classes]


def get_handler_by_id(dataset_id: str, paths: Optional["PathConfig"] = None) -> BaseDatasetHandler:
    """Find a specific dataset handler by its dataset_id."""
    for h in get_all_dataset_handlers(paths=paths):
        if h.dataset_id == dataset_id:
            return h
    raise KeyError(f"No registered dataset handler found with dataset_id='{dataset_id}'")


def get_handlers_by_capability(
    capability: str, paths: Optional["PathConfig"] = None
) -> List[BaseDatasetHandler]:
    """Return all dataset handlers that declare support for the given telemetry capability."""
    return [h for h in get_all_dataset_handlers(paths=paths) if capability in h.telemetry_capabilities]
