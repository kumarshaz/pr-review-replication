#!/usr/bin/env python3
"""
Step 1 (Optional Full Recompute): End-to-End Track-3 Empirical Pipeline Runner
==============================================================================
Executes the standalone Track-3 analysis pipeline directly against raw on-disk
Parquet/CSV corpora and bare-git SZZ ledgers into an isolated output directory
(defaulting to a temporary audit directory so checked-in canonical files remain
untouched unless `--in-place` is explicitly requested).

Stages executed:
  1. p00_reparse_jev_offline.py        -> Offline deterministic Jev signal reparsing
  2. p16_jev_judgment_and_szz_outcomes -> NQ-01 & NQ-02 (Jev triage, hotspot control, DiD)
  3. p17_open_questions_nq01_to_nq08   -> NQ-03..NQ-08 (PR bloat, force-push, Bot-First,
                                          cold-file tests, language tiers, Gini, CodeRabbit)
  4. p14_sample_power_audit            -> 6-Ring multi-scale sample size & power audit

Usage:
  python3 replication/scripts/01_recompute_track3_pipeline.py
  python3 replication/scripts/01_recompute_track3_pipeline.py --output-dir /tmp/pr_review_recompute
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPLICATION_DIR = SCRIPT_DIR.parent
REPO_ROOT = REPLICATION_DIR.parent
PIPELINE_ROOT = REPLICATION_DIR / "pipeline"
CANONICAL_RESULTS_DIR = REPLICATION_DIR / "results" / "pr_review"

if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

from config.paths import get_paths  # noqa: E402


RECOMPUTE_STAGES: list[tuple[str, str]] = [
    ("Offline Jev Signal Reparse", "p00_reparse_jev_offline.py"),
    ("NQ-01 & NQ-02: Jev Self-Triage & Bare-Git SZZ", "p16_jev_judgment_and_szz_outcomes.py"),
    ("NQ-03..NQ-08: Myths 1-5, Gini, CodeRabbit & BH-FDR", "p17_open_questions_nq01_to_nq08.py"),
    ("Multi-Scale Statistical Power Audit", "p14_sample_power_audit.py"),
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recompute Track-3 empirical JSON/CSV outputs from raw scratch/ corpora."
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Target directory for recomputed results (defaults to an isolated temp directory).",
    )
    parser.add_argument(
        "--include-szz-rebuild",
        action="store_true",
        help="Also re-run p00b_build_szz_constraints.py across all 300 bare-git clones (slow).",
    )
    args = parser.parse_args()

    paths = get_paths()
    if not (paths.scratch_dir / "aidev" / "pull_request.parquet").exists():
        print("[ERROR] Raw datasets not found in scratch_dir:", paths.scratch_dir)
        print("        Run: python3 replication/scripts/00_fetch_datasets.py --all --clone-tier 1")
        sys.exit(2)

    cleanup_tmp = False
    if args.output_dir:
        out_dir = Path(args.output_dir).expanduser().resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = Path(tempfile.mkdtemp(prefix="pr_review_recompute_"))
        cleanup_tmp = True

    (out_dir / "data_tables").mkdir(parents=True, exist_ok=True)

    # Seed upstream precomputed ledgers needed by p14/p16/p17 unless rebuilding SZZ from scratch
    for seed_file in CANONICAL_RESULTS_DIR.iterdir():
        if seed_file.is_file() and seed_file.suffix in (".json", ".md"):
            shutil.copy2(seed_file, out_dir / seed_file.name)
    for seed_csv in (CANONICAL_RESULTS_DIR / "data_tables").glob("*.csv"):
        shutil.copy2(seed_csv, out_dir / "data_tables" / seed_csv.name)

    stages = list(RECOMPUTE_STAGES)
    if args.include_szz_rebuild:
        stages.insert(1, ("Bare-Git 300-Clone SZZ Rebuild", "p00b_build_szz_constraints.py"))

    env = dict(os.environ)
    env["PYTHONPATH"] = str(PIPELINE_ROOT)
    env["PR_REVIEW_SCRATCH_DIR"] = str(paths.scratch_dir)
    env["PR_REVIEW_RESULTS_DIR"] = str(out_dir)
    env["PR_ANALYSIS_SCRATCH_DIR"] = str(paths.scratch_dir)
    env["PR_ANALYSIS_RESULTS_DIR"] = str(out_dir)

    print("=" * 80)
    print("TRACK-3 END-TO-END RECOMPUTATION PIPELINE")
    print(f"  Scratch Dir : {paths.scratch_dir}")
    print(f"  Output Dir  : {out_dir}")
    print("=" * 80)

    t_all = time.perf_counter()
    for title, script_name in stages:
        script_path = PIPELINE_ROOT / "src" / "pipelines" / script_name
        print(f"\n>>> RUNNING: {title} ({script_name}) <<<")
        t0 = time.perf_counter()
        proc = subprocess.run([sys.executable, str(script_path)], env=env, cwd=str(PIPELINE_ROOT))
        dt = time.perf_counter() - t0
        if proc.returncode != 0:
            print(f"[FAIL] {title} exited with code {proc.returncode} in {dt:.2f}s")
            sys.exit(proc.returncode)
        print(f"[PASS] {title} completed in {dt:.2f}s")

    print(f"\n[OK] All {len(stages)} Track-3 recomputation stages succeeded in {time.perf_counter() - t_all:.2f}s.")
    if cleanup_tmp:
        shutil.rmtree(out_dir, ignore_errors=True)
        print("[OK] Cleaned temporary isolated recompute directory (canonical results untouched).")


if __name__ == "__main__":
    main()
