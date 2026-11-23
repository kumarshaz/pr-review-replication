#!/usr/bin/env python3
import csv
import os
import re
import zipfile
from typing import Any, Dict, List, Optional

from src.handlers.base import BaseDatasetHandler


class CodeRabbitOSSHandler(BaseDatasetHandler):
    @property
    def dataset_id(self) -> str:
        return "dataset_9_coderabbit_oss_activities"

    @property
    def dataset_name(self) -> str:
        return "CodeRabbit OSS Activities"

    @property
    def primary_entity(self) -> str:
        return "Open-Source Pull Requests, Reviews & YAML Guardrail Policies"

    @property
    def lemon_market_implication(self) -> str:
        return "Most parsed .coderabbit.yaml policies use chill/default profiles without enabled deterministic tools; assertive/tool policies materially alter comment volume"

    @property
    def raw_files(self) -> List[str]:
        return [
            "scratch/coderabbit/pull_requests.parquet",
            "scratch/coderabbit/repositories.parquet",
            "scratch/coderabbit/coderabbit_configuration_files.zip",
        ]

    @property
    def calculating_programs(self) -> List[str]:
        return [
            "p01_verify_raw_datasets.py",
            "p05_multicorpus_triangulation.py",
        ]

    @property
    def telemetry_capabilities(self) -> List[str]:
        return ["bot_comment_density", "operator_execution_boundaries"]

    def execute(self, con: Any, repo_root: Optional[str] = None) -> Dict[str, Any]:
        scratch_coderabbit = self.scratch_path("coderabbit")
        cr_pr_file = os.path.join(scratch_coderabbit, "pull_requests.parquet")
        cr_repo_file = os.path.join(scratch_coderabbit, "repositories.parquet")
        cr_zip_file = os.path.join(scratch_coderabbit, "coderabbit_configuration_files.zip")

        d9_results: Dict[str, Any] = {
            "dataset_name": "CodeRabbit OSS Activities (Zenodo 10.5281/zenodo.21878471)",
            "total_pull_requests": 0,
            "total_repositories": 0,
            "avg_comments_per_pr": 0.0,
            "yaml_configs_parsed": 0,
            "yaml_feature_counts": {},
            "policy_outcomes": [],
            "status": "not_found",
        }

        if not os.path.exists(cr_pr_file):
            return d9_results

        cr_stats = con.execute(
            f"SELECT count(*), count(DISTINCT repo_id), round(avg(number_comments), 2) FROM read_parquet('{cr_pr_file}')"
        ).fetchone()
        repo_cnt = (
            con.execute(f"SELECT count(*) FROM read_parquet('{cr_repo_file}')").fetchone()[0]
            if os.path.exists(cr_repo_file)
            else cr_stats[1]
        )

        lang_rows = (
            con.execute(f"""
                SELECT COALESCE(r.language, 'Unknown') AS language,
                       COUNT(DISTINCT p.repo_id) AS repos,
                       COUNT(*) AS prs,
                       ROUND(AVG(p.number_comments), 2) AS avg_comments
                FROM read_parquet('{cr_pr_file}') p
                JOIN read_parquet('{cr_repo_file}') r ON p.repo_id = r.repo_id
                GROUP BY 1
                ORDER BY prs DESC
                LIMIT 12
            """).fetchall()
            if os.path.exists(cr_repo_file)
            else []
        )

        # Parse all .coderabbit.yaml policies cleanly using stdlib
        yaml_features = {
            "reviews_section": 0,
            "profile_assertive": 0,
            "profile_chill": 0,
            "profile_default": 0,
            "auto_review": 0,
            "path_filters": 0,
            "path_instructions": 0,
            "tools_section": 0,
            "semgrep": 0,
            "ast_grep": 0,
            "ruff": 0,
            "eslint": 0,
        }

        def _strip_yaml_comments(raw_text: str) -> str:
            cleaned_lines = []
            for ln in raw_text.splitlines():
                # Strip inline/full-line YAML comments while preserving quoted strings simply
                stripped = re.sub(r"(^|\s)#.*$", "", ln)
                if stripped.strip():
                    cleaned_lines.append(stripped)
            return "\n".join(cleaned_lines)

        def _tool_enabled(uncomm_txt: str, tool_pattern: str) -> bool:
            m = re.search(rf"^\s*(?:{tool_pattern})\s*:\s*(.*)$", uncomm_txt, flags=re.MULTILINE)
            if not m:
                return False
            # Look at the following indented lines inside that tool block for `enabled: false`
            tail = uncomm_txt[m.end():m.end() + 250]
            block_lines = []
            base_indent = len(m.group(0)) - len(m.group(0).lstrip())
            for ln in tail.splitlines()[1:]:
                if not ln.strip():
                    continue
                ind = len(ln) - len(ln.lstrip())
                if ind <= base_indent:
                    break
                block_lines.append(ln.strip())
            block_str = "\n".join(block_lines)
            if re.search(r"^enabled\s*:\s*false\b", block_str, flags=re.MULTILINE):
                return False
            return True

        cfg_rows = []
        if os.path.exists(cr_zip_file):
            with zipfile.ZipFile(cr_zip_file) as zf:
                for entry in sorted(zf.namelist()):
                    if entry.endswith((".yaml", ".yml")):
                        raw_txt = zf.read(entry).decode("utf-8", errors="ignore").lower()
                        txt = _strip_yaml_comments(raw_txt)
                        has_reviews = bool(re.search(r"^\s*reviews\s*:", txt, flags=re.MULTILINE))
                        is_assertive = bool(re.search(r"^\s*profile\s*:\s*['\"]?assertive['\"]?\b", txt, flags=re.MULTILINE))
                        is_chill = bool(re.search(r"^\s*profile\s*:\s*['\"]?chill['\"]?\b", txt, flags=re.MULTILINE))
                        prof = "assertive" if is_assertive else ("chill" if is_chill else "default")
                        has_auto = bool(re.search(r"^\s*auto_review\s*:", txt, flags=re.MULTILINE))
                        has_pf = bool(re.search(r"^\s*path_filters\s*:", txt, flags=re.MULTILINE))
                        has_pi = bool(re.search(r"^\s*path_instructions\s*:", txt, flags=re.MULTILINE))
                        has_tools = bool(re.search(r"^\s*tools\s*:", txt, flags=re.MULTILINE))
                        has_semgrep = _tool_enabled(txt, r"semgrep")
                        has_ast = _tool_enabled(txt, r"ast[-_]grep")
                        has_ruff = _tool_enabled(txt, r"ruff")
                        has_eslint = _tool_enabled(txt, r"eslint")
                        has_det = has_semgrep or has_ast or has_ruff or has_eslint or _tool_enabled(txt, r"biome|clippy")

                        if has_reviews:
                            yaml_features["reviews_section"] += 1
                        if prof == "assertive":
                            yaml_features["profile_assertive"] += 1
                        elif prof == "chill":
                            yaml_features["profile_chill"] += 1
                        else:
                            yaml_features["profile_default"] += 1
                        if has_auto:
                            yaml_features["auto_review"] += 1
                        if has_pf:
                            yaml_features["path_filters"] += 1
                        if has_pi:
                            yaml_features["path_instructions"] += 1
                        if has_tools:
                            yaml_features["tools_section"] += 1
                        if has_semgrep:
                            yaml_features["semgrep"] += 1
                        if has_ast:
                            yaml_features["ast_grep"] += 1
                        if has_ruff:
                            yaml_features["ruff"] += 1
                        if has_eslint:
                            yaml_features["eslint"] += 1

                        parts = entry.split("/")
                        if len(parts) >= 2 and "__" in parts[1]:
                            repo_slug = parts[1].replace("__", "/")
                            cfg_rows.append((repo_slug, prof, has_pi, has_pf, has_det, has_semgrep, has_ast))

        policy_outcomes = []
        if cfg_rows:
            con.execute("DROP TABLE IF EXISTS _tmp_cr_cfg")
            con.execute(
                "CREATE TEMP TABLE _tmp_cr_cfg (repo VARCHAR, profile VARCHAR, has_path_instr BOOLEAN, has_path_filters BOOLEAN, has_det_tools BOOLEAN, has_semgrep BOOLEAN, has_ast_grep BOOLEAN)"
            )
            con.executemany("INSERT INTO _tmp_cr_cfg VALUES (?, ?, ?, ?, ?, ?, ?)", cfg_rows)
            po_rows = con.execute(f"""
                SELECT
                    c.profile,
                    c.has_path_instr,
                    c.has_det_tools,
                    COUNT(DISTINCT p.repo) AS repos,
                    COUNT(*) AS prs,
                    ROUND(AVG(p.number_comments), 2) AS avg_comments,
                    ROUND(MEDIAN(EPOCH(TRY_CAST(p.closed_at AS TIMESTAMP) - TRY_CAST(p.created_at AS TIMESTAMP)) / 3600.0), 2) AS med_close_hrs
                FROM _tmp_cr_cfg c
                JOIN read_parquet('{cr_pr_file}') p ON LOWER(c.repo) = LOWER(p.repo)
                GROUP BY 1, 2, 3
                ORDER BY prs DESC
            """).fetchall()
            con.execute("DROP TABLE IF EXISTS _tmp_cr_cfg")

            csv_path = self.table_path("coderabbit_policy_outcomes_log.csv")
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["profile", "has_path_instructions", "has_deterministic_tools", "repos", "prs", "avg_comments_per_pr", "median_close_hours"])
                for r in po_rows:
                    w.writerow([r[0], r[1], r[2], r[3], r[4], r[5], r[6]])
                    policy_outcomes.append({
                        "profile": r[0],
                        "has_path_instructions": bool(r[1]),
                        "has_deterministic_tools": bool(r[2]),
                        "repos": r[3],
                        "prs": r[4],
                        "avg_comments_per_pr": float(r[5]),
                        "median_close_hours": float(r[6]) if r[6] is not None else 0.0,
                    })

        d9_results = {
            "dataset_name": "CodeRabbit OSS Activities (Zenodo 10.5281/zenodo.21878471)",
            "total_pull_requests": cr_stats[0],
            "total_repositories": repo_cnt,
            "avg_comments_per_pr": float(cr_stats[2]),
            "yaml_configs_parsed": len(cfg_rows),
            "yaml_feature_counts": yaml_features,
            "language_breakdown": [
                {"language": r[0], "repos": r[1], "prs": r[2], "avg_comments": float(r[3])}
                for r in lang_rows
            ],
            "policy_outcomes": policy_outcomes,
            "status": "verified_on_disk",
        }
        return d9_results

    def get_summary_row(self, result: Dict[str, Any]) -> List[Any]:
        yf = result.get("yaml_feature_counts", {})
        return [
            self.primary_entity,
            f"{result['total_pull_requests']:,} PRs across {result['total_repositories']:,} repos ({result.get('yaml_configs_parsed', 0)} YAMLs)",
            f"Avg Comments/PR: {result['avg_comments_per_pr']} | chill={yf.get('profile_chill', 0)} vs assertive={yf.get('profile_assertive', 0)}",
            f"Deterministic Tools: semgrep={yf.get('semgrep', 0)}, ast-grep={yf.get('ast_grep', 0)}",
            self.lemon_market_implication,
        ]
