#!/usr/bin/env python3
"""
Step 0C: Offline Deterministic Jev Signal Reparser (Zero API Calls)
===================================================================
Reads the cached `jev_bot_signals_and_comments.parquet` in `paths.scratch_dir`
(never mutating raw `scratch/`!) and applies an expanded, strictly deterministic
regex parser to rescue unparsed Jev decision-model signals while explicitly keeping
non-Jev deterministic merge gates (`<!-- ovd-merge-gate-status -->`) separate:

  1. Preserves all existing `is_jev_signal == True` classifications
     (`jev_decision_model_linter`, `jev_pr_risk_histogram`, `jev_taste_policy_gate`).
  2. Rescues `jaubut/claude-companion` (`<!-- review-tier: ... -->` /
     `<!-- review-route: ... -->` / `Jev:` markers -> `bot_family = 'jev_review_router'`).
  3. Rescues `optomachina/Overdrafter`:
     - Genuine Jev council/review comments (`Architect review (Jev ...)` and
       `## Jev review @<sha>: PASS|FAIL` -> `is_jev_signal = True`,
       `bot_family = 'jev_council_architect_review'`, keeping `mirrorstack-ai/mirrorstack-cli`
       `jev_taste_policy_gate` pure).
     - `<!-- ovd-merge-gate-status -->`: verified deterministic CI merge-gate status
       aggregator (`bot_family = 'deterministic_merge_gate'`, `is_jev_signal = False`).
  4. Rescues `fabiankaegy/pr-risk` (`<!-- pr-risk -->` with `### Risk: **high/medium/low**`).
  5. Rescues `qnimbus/home-lab` (`<!-- pr-risk -->` with `PR risk:` + `Jev answers`).
  6. Rescues `marcusbandit/Anibeam` (`<!-- loop-review v1 ... verdict=... risk=... -->`).
  7. Rescues `Shahrukh-cyber/jev-pr-reviewer` (`<!-- jev-pr-review -->`).
  8. Rescues `misty-step/chrondle` (`Jev — Way of working`).

Outputs:
  - `paths.results_dir / "jev_bot_signals_reparsed.parquet"`
  - `paths.results_dir / "jev_offline_reparse_audit.json"`
"""

from __future__ import annotations

import datetime
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

PR_ANALYSIS_ROOT = Path(__file__).resolve().parents[2]
if str(PR_ANALYSIS_ROOT) not in sys.path:
    sys.path.insert(0, str(PR_ANALYSIS_ROOT))

from config.bot_catalog import JEV_EXTRA_BOT_LOGINS
from config.paths import PathConfig, get_paths
from src.utils.logging_utils import setup_verbose_logger

# Precompiled deterministic marker patterns grounded in on-disk parquet samples
RE_REVIEW_TIER = re.compile(r"<!--\s*review-tier:\s*([a-zA-Z0-9_-]+)\s*-->", re.I)
RE_REVIEW_ROUTE = re.compile(r"<!--\s*review-route:\s*([a-zA-Z0-9_-]+)(?:\s+([0-9a-f]{7,40}))?\s*-->", re.I)
RE_ROUTE_CONF = re.compile(r"confidence\s+([0-9]*\.?[0-9]+)", re.I)
RE_ROUTE_JEV = re.compile(r"\bJev:\s*([a-zA-Z0-9_-]+)", re.I)
RE_ROUTE_LENSES = re.compile(r"\blenses:\s*([^\s<]+)", re.I)

RE_OVD_GATE = re.compile(
    r"<!--\s*ovd-merge-gate-status\s*-->.*?\*\*ovd-merge-gate\*\*\s*`([^`]+)`\s*for\s*`([0-9a-f]{7,40})`\s*\(mode\s*`([^`]+)`\)",
    re.I | re.S,
)
RE_OVD_BLOCKING = re.compile(r"blocking codes:\s*([^\n]+)", re.I)

RE_ARCH_JEV_HDR = re.compile(
    r"Architect review\s*\(Jev\s+([^)]+)\)\s*@\s*([0-9a-f]{7,40})",
    re.I,
)
RE_ARCH_VERDICT = re.compile(r"\bVERDICT:\s*([A-Z_]+)", re.I)
RE_ARCH_SCREEN = re.compile(
    r"Jev risk screen\s*\(([^)]+)\):\s*tier=([a-zA-Z_-]+)\s+status=([a-zA-Z_-]+)\s+confidence=([0-9]*\.?[0-9]+)\s+pIncident=([0-9]*\.?[0-9]+)",
    re.I,
)
RE_MD_JEV_REVIEW = re.compile(r"^##\s*Jev review\s*@([0-9a-f]{7,40}):\s*([A-Z_]+)", re.I | re.M)

RE_PR_RISK_HEADING = re.compile(r"###\s*Risk:\s*\*\*([a-zA-Z_-]+)\*\*", re.I)
RE_ASSESSED_BY_JEV = re.compile(
    r"Assessed by Jev at\s+([0-9a-f]{7,40})\s*·\s*chance of high risk\s*([0-9.]+)%\s*·\s*confidence\s*([0-9.]+)%",
    re.I,
)
RE_PR_RISK_LANE = re.compile(r"PR risk:\s*\*\*([^*]+?)\*\*", re.I)
RE_JEV_ANSWERS_CONF = re.compile(r"(?:\(conf\s+([0-9.]+)\)|Low confidence[^()\n]*\(([0-9.]+)\))", re.I)

RE_LOOP_REVIEW = re.compile(
    r"<!--\s*loop-review\s+v\d+\s+sha=([0-9a-f]{7,40})\s+verdict=([^\s]+)\s+risk=([^\s>]+)\s*-->",
    re.I,
)

RE_JEV_PR_REVIEW_COMMIT = re.compile(r"\*\*Commit\*\*\s*`([0-9a-f]{7,40})`", re.I)
RE_JEV_PR_REVIEW_CLASS = re.compile(r"\|\s*Classification\s*\|\s*\*\*([^*]+?)\*\*\s*\|\s*([0-9.]+)%\s*confidence", re.I)
RE_JEV_PR_REVIEW_RISK = re.compile(
    r"\|\s*Engineering risk\s*\|\s*\*\*([0-9.]+)\s*/\s*3\*\*[^|]*\|\s*[^|]*?([0-9.]+)%\s*confidence",
    re.I,
)
RE_JEV_PR_REVIEW_HUMAN = re.compile(r"\|\s*Human review\s*\|\s*\*\*([0-9.]+)%\*\*", re.I)

RE_WAY_OF_WORKING_HDR = re.compile(r"Jev\s+[—-]\s+Way of working", re.I)
RE_WAY_HEAD = re.compile(r"\bHead\s+`([0-9a-f]{7,40})`", re.I)
RE_WAY_CONF = re.compile(r"Confidence:\s*([0-9.]+)%", re.I)
RE_WAY_KAYLEE = re.compile(r"Kaylee:\s*([a-zA-Z0-9_-]+)", re.I)
RE_WAY_MODEL = re.compile(r"Model:\s*`(typesafe/jev-[^`]+)`", re.I)
RE_WAY_METRIC = re.compile(r"^(Duplicate fact|Gate/rule|Widen verification|Workaround/narration):\s*([0-9.]+)%", re.I | re.M)

_JEV_EXTRA_BOT_SET = frozenset(b.lower() for b in JEV_EXTRA_BOT_LOGINS)


def is_bot_login_misclassified_as_human(bot_family: str, author_login: str) -> bool:
    """Return True when a `human_comment` row was authored by a known bot login."""
    if bot_family != "human_comment":
        return False
    low = (author_login or "").strip().lower()
    return low.endswith("-bot") or low.endswith("[bot]") or low in _JEV_EXTRA_BOT_SET


def classify_unparsed_comment(body: str, repo_full_name: str, author_login: str) -> Optional[Dict[str, Any]]:
    """
    Attempt deterministic Jev (or non-Jev merge-gate) classification on an unparsed comment excerpt.
    Returns None when no known marker matches.
    """
    text = body or ""
    if not text.strip():
        return None

    # 1. jaubut/claude-companion: <!-- review-tier: ... --> / <!-- review-route: ... --> / Jev:
    m_tier = RE_REVIEW_TIER.search(text)
    m_route = RE_REVIEW_ROUTE.search(text)
    if m_tier or m_route:
        tier = (m_tier.group(1) if m_tier else "unknown").lower()
        route = (m_route.group(1) if m_route else "unknown").lower()
        sha = (m_route.group(2) if m_route and m_route.group(2) else "")
        m_conf = RE_ROUTE_CONF.search(text)
        m_jev = RE_ROUTE_JEV.search(text)
        m_lenses = RE_ROUTE_LENSES.search(text)
        jev_route = (m_jev.group(1).lower() if m_jev else "")
        conf = float(m_conf.group(1)) if m_conf else 0.0
        lenses = m_lenses.group(1) if m_lenses else ""

        is_high_risk = (tier == "high") or (route == "full") or (jev_route == "full")
        risk_map = {"high": 0.85, "medium": 0.50, "normal": 0.35, "low": 0.15}
        risk_norm = risk_map.get(tier, 0.85 if is_high_risk else 0.35)
        return {
            "is_jev_signal": True,
            "bot_family": "jev_review_router",
            "jev_model_tag": "jev-review-router",
            "overall_verdict": f"ROUTE_{route.upper()}:TIER_{tier.upper()}",
            "risk_score_normalized": risk_norm,
            "jev_confidence": conf,
            "predicted_pr_type": "review_router",
            "alerts_count": 1 if is_high_risk else 0,
            "rule_alerts_json": json.dumps(
                {
                    "review_tier": tier,
                    "review_route": route,
                    "jev_route": jev_route,
                    "lenses": lenses,
                }
            ),
            "calls_count": 1,
            "bound_commit_sha": sha,
            "reparse_pattern": "claude_companion_review_router",
        }

    # 2A. optomachina/Overdrafter: <!-- ovd-merge-gate-status --> (deterministic CI merge gate, NOT Jev!)
    if "<!-- ovd-merge-gate-status -->" in text:
        m_gate = RE_OVD_GATE.search(text)
        status = (m_gate.group(1).lower() if m_gate else ("failure" if "`failure`" in text else "neutral"))
        sha = (m_gate.group(2) if m_gate else "")
        mode = (m_gate.group(3).lower() if m_gate else ("enforce" if "mode `enforce`" in text else "report"))
        m_blk = RE_OVD_BLOCKING.search(text)
        blocking_str = m_blk.group(1).strip() if m_blk else ""
        return {
            "is_jev_signal": False,
            "bot_family": "deterministic_merge_gate",
            "jev_model_tag": "ovd-merge-gate",
            "overall_verdict": f"GATE_{status.upper()}:{mode.upper()}",
            "risk_score_normalized": 1.0 if status == "failure" else 0.25,
            "jev_confidence": 1.0,
            "predicted_pr_type": "deterministic_merge_gate",
            "alerts_count": 1 if status == "failure" else 0,
            "rule_alerts_json": json.dumps(
                {
                    "gate_status": status,
                    "mode": mode,
                    "jev_not_pass": ("jev_not_pass" in text),
                    "blocking_codes_excerpt": blocking_str[:240],
                }
            ),
            "calls_count": 1,
            "bound_commit_sha": sha,
            "reparse_pattern": "ovd_merge_gate_status_non_jev",
        }

    # 2B. optomachina/Overdrafter: Architect review (Jev <model>) @ <sha>
    m_arch = RE_ARCH_JEV_HDR.search(text)
    if m_arch:
        model_tag = m_arch.group(1).strip()
        sha = m_arch.group(2).strip()
        m_verd = RE_ARCH_VERDICT.search(text)
        verdict = m_verd.group(1).upper() if m_verd else "REVIEWED"
        m_scr = RE_ARCH_SCREEN.search(text)
        tier = m_scr.group(2).lower() if m_scr else "unknown"
        scr_status = m_scr.group(3).lower() if m_scr else "unknown"
        conf = float(m_scr.group(4)) if m_scr else 0.8
        p_inc = float(m_scr.group(5)) if m_scr else (0.75 if verdict == "FAIL" else 0.25)
        is_flagged = (verdict == "FAIL") or (tier in ("risky", "high"))
        return {
            "is_jev_signal": True,
            "bot_family": "jev_council_architect_review",
            "jev_model_tag": model_tag,
            "overall_verdict": f"{verdict}:{tier.upper()}",
            "risk_score_normalized": round(max(0.0, min(1.0, p_inc)), 4),
            "jev_confidence": round(max(0.0, min(1.0, conf)), 4),
            "predicted_pr_type": "architect_council_jev",
            "alerts_count": 1 if is_flagged else 0,
            "rule_alerts_json": json.dumps(
                {"verdict": verdict, "tier": tier, "screen_status": scr_status, "p_incident": p_inc}
            ),
            "calls_count": 1,
            "bound_commit_sha": sha,
            "reparse_pattern": "overdrafter_architect_jev_review",
        }

    # 2C. optomachina/Overdrafter: ## Jev review @<sha>: PASS|FAIL
    # Route to jev_council_architect_review (never jev_taste_policy_gate, keeping mirrorstack-cli pure)
    m_md_jev = RE_MD_JEV_REVIEW.search(text)
    if m_md_jev:
        sha = m_md_jev.group(1).strip()
        verdict = m_md_jev.group(2).upper()
        is_fail = verdict in ("FAIL", "BLOCK", "REJECT")
        return {
            "is_jev_signal": True,
            "bot_family": "jev_council_architect_review",
            "jev_model_tag": "jev-review",
            "overall_verdict": verdict,
            "risk_score_normalized": 1.0 if is_fail else 0.0,
            "jev_confidence": 1.0,
            "predicted_pr_type": "architect_council_jev",
            "alerts_count": 1 if is_fail else 0,
            "rule_alerts_json": json.dumps({"verdict": verdict, "sha": sha}),
            "calls_count": 1,
            "bound_commit_sha": sha,
            "reparse_pattern": "overdrafter_md_jev_review",
        }

    # 3. fabiankaegy/pr-risk: <!-- pr-risk --> with ### Risk: **high/medium/low** + Assessed by Jev
    if "<!-- pr-risk -->" in text and (RE_PR_RISK_HEADING.search(text) or "Assessed by Jev" in text):
        m_risk = RE_PR_RISK_HEADING.search(text)
        m_jev = RE_ASSESSED_BY_JEV.search(text)
        risk_lbl = m_risk.group(1).lower() if m_risk else "unknown"
        sha = m_jev.group(1) if m_jev else ""
        chance_pct = float(m_jev.group(2)) if m_jev else None
        conf_pct = float(m_jev.group(3)) if m_jev else None
        risk_map = {"high": 0.90, "critical": 0.95, "medium": 0.55, "low": 0.15}
        norm_risk = round(chance_pct / 100.0, 4) if chance_pct is not None else risk_map.get(risk_lbl, 0.50)
        conf = round(conf_pct / 100.0, 4) if conf_pct is not None else 0.80
        is_flagged = risk_lbl in ("high", "critical", "medium")
        return {
            "is_jev_signal": True,
            "bot_family": "jev_pr_risk_histogram",
            "jev_model_tag": "jev-pr-risk-assessed",
            "overall_verdict": f"RISK_{risk_lbl.upper()}",
            "risk_score_normalized": norm_risk,
            "jev_confidence": conf,
            "predicted_pr_type": "pr_risk_assessed",
            "alerts_count": 1 if is_flagged else 0,
            "rule_alerts_json": json.dumps(
                {"risk": risk_lbl, "chance_high_risk_pct": chance_pct, "confidence_pct": conf_pct}
            ),
            "calls_count": 1,
            "bound_commit_sha": sha,
            "reparse_pattern": "pr_risk_assessed_by_jev",
        }

    # 4. qnimbus/home-lab: <!-- pr-risk --> with PR risk: **...** and Jev answers / | jev |
    if "<!-- pr-risk -->" in text and ("Jev answers" in text or "| jev |" in text.lower() or "PR risk:" in text):
        m_lane = RE_PR_RISK_LANE.search(text)
        lane = m_lane.group(1).strip().lower() if m_lane else "unknown"
        uncertain = "uncertain" in text.lower()
        confs = [float(g1 or g2) for g1, g2 in RE_JEV_ANSWERS_CONF.findall(text)]
        conf = round(min(confs), 4) if confs else (0.35 if uncertain else 0.80)
        is_flagged = lane in ("review", "high", "red", "block", "medium") or uncertain
        risk_map = {"high": 0.90, "red": 0.90, "review": 0.65, "medium": 0.60, "low": 0.20, "green": 0.10}
        return {
            "is_jev_signal": True,
            "bot_family": "jev_pr_risk_histogram",
            "jev_model_tag": "jev-pr-risk-answers",
            "overall_verdict": f"LANE_{lane.upper()}" + (":UNCERTAIN" if uncertain else ""),
            "risk_score_normalized": risk_map.get(lane, 0.60 if uncertain else 0.25),
            "jev_confidence": conf,
            "predicted_pr_type": "pr_risk_answers",
            "alerts_count": 1 if is_flagged else 0,
            "rule_alerts_json": json.dumps({"lane": lane, "uncertain": uncertain, "confidences": confs}),
            "calls_count": 1,
            "bound_commit_sha": "",
            "reparse_pattern": "pr_risk_jev_answers",
        }

    # 5. marcusbandit/Anibeam: <!-- loop-review v1 sha=... verdict=... risk=... -->
    m_loop = RE_LOOP_REVIEW.search(text)
    if m_loop:
        sha = m_loop.group(1).strip()
        verdict = m_loop.group(2).strip().lower()
        risk = m_loop.group(3).strip().lower()
        risk_map = {"high": 0.90, "critical": 0.95, "medium": 0.60, "low": 0.20}
        is_flagged = risk in ("high", "critical", "medium") or verdict in ("changes", "fail", "block", "reject")
        return {
            "is_jev_signal": True,
            "bot_family": "jev_loop_review_gate",
            "jev_model_tag": "jev-loop-review-v1",
            "overall_verdict": f"LOOP_{verdict.upper()}:RISK_{risk.upper()}",
            "risk_score_normalized": risk_map.get(risk, 0.50),
            "jev_confidence": 0.85,
            "predicted_pr_type": "loop_review_gate",
            "alerts_count": 1 if is_flagged else 0,
            "rule_alerts_json": json.dumps({"verdict": verdict, "risk": risk, "sha": sha}),
            "calls_count": 1,
            "bound_commit_sha": sha,
            "reparse_pattern": "anibeam_loop_review_v1",
        }

    # 6. Shahrukh-cyber/jev-pr-reviewer: <!-- jev-pr-review -->
    if "<!-- jev-pr-review -->" in text:
        m_sha = RE_JEV_PR_REVIEW_COMMIT.search(text)
        m_cls = RE_JEV_PR_REVIEW_CLASS.search(text)
        m_risk = RE_JEV_PR_REVIEW_RISK.search(text)
        m_hr = RE_JEV_PR_REVIEW_HUMAN.search(text)
        sha = m_sha.group(1) if m_sha else ""
        pr_cls = m_cls.group(1).strip().lower() if m_cls else "pr_review"
        risk_3 = float(m_risk.group(1)) if m_risk else 1.5
        conf_pct = float(m_risk.group(2)) if m_risk else 85.0
        hr_pct = float(m_hr.group(1)) if m_hr else 0.0
        norm_risk = round(min(1.0, max(0.0, risk_3 / 3.0)), 4)
        is_flagged = norm_risk >= 0.50 or hr_pct >= 50.0
        return {
            "is_jev_signal": True,
            "bot_family": "jev_pr_risk_histogram",
            "jev_model_tag": "jev-pr-reviewer",
            "overall_verdict": f"RISK_{risk_3:.2f}_OF_3:HR_{int(round(hr_pct))}PCT",
            "risk_score_normalized": norm_risk,
            "jev_confidence": round(conf_pct / 100.0, 4),
            "predicted_pr_type": pr_cls,
            "alerts_count": 1 if is_flagged else 0,
            "rule_alerts_json": json.dumps(
                {"classification": pr_cls, "engineering_risk_of_3": risk_3, "human_review_pct": hr_pct}
            ),
            "calls_count": 1,
            "bound_commit_sha": sha,
            "reparse_pattern": "jev_pr_review_html_marker",
        }

    # 7. misty-step/chrondle: Jev — Way of working
    if RE_WAY_OF_WORKING_HDR.search(text):
        m_head = RE_WAY_HEAD.search(text)
        m_conf = RE_WAY_CONF.search(text)
        m_kay = RE_WAY_KAYLEE.search(text)
        m_mod = RE_WAY_MODEL.search(text)
        metrics = {k.lower(): float(v) for k, v in RE_WAY_METRIC.findall(text)}
        kaylee = (m_kay.group(1).lower() if m_kay else "advisory")
        conf = round(float(m_conf.group(1)) / 100.0, 4) if m_conf else 0.5
        max_pct = max(metrics.values(), default=0.0)
        is_flagged = kaylee in ("inspect", "flag", "block") or max_pct >= 40.0
        return {
            "is_jev_signal": True,
            "bot_family": "jev_way_of_working_advisor",
            "jev_model_tag": m_mod.group(1) if m_mod else "typesafe/jev-1.14",
            "overall_verdict": f"WAY_OF_WORKING:{kaylee.upper()}",
            "risk_score_normalized": round(min(1.0, max_pct / 100.0), 4),
            "jev_confidence": conf,
            "predicted_pr_type": "way_of_working",
            "alerts_count": 1 if is_flagged else 0,
            "rule_alerts_json": json.dumps({"kaylee": kaylee, "metrics_pct": metrics}),
            "calls_count": 1,
            "bound_commit_sha": m_head.group(1) if m_head else "",
            "reparse_pattern": "chrondle_jev_way_of_working",
        }

    return None


def run_reparse(paths: PathConfig, log: Any) -> Dict[str, Any]:
    """Execute deterministic offline reparsing over cached Jev comments without mutating scratch/."""
    src_pq = paths.scratch_dir / "jev_pr_reviews" / "jev_bot_signals_and_comments.parquet"
    if not src_pq.exists():
        raise FileNotFoundError(f"Missing cached Jev signals parquet: {src_pq}")

    df = pd.read_parquet(src_pq)
    log.info("Loaded %d cached rows from %s (pre-reparse is_jev_signal=%d).", len(df), src_pq, int(df["is_jev_signal"].sum()))

    pre_jev_rows = int(df["is_jev_signal"].sum())
    pre_jev_prs = int(
        df.loc[df["is_jev_signal"] == True, ["repo_full_name", "pr_number"]]
        .drop_duplicates()
        .shape[0]
    )

    reparse_rescued: List[bool] = []
    reparse_patterns: List[str] = []
    rescued_by_repo: Counter[str] = Counter()
    rescued_by_pattern: Counter[str] = Counter()
    non_jev_gate_by_repo: Counter[str] = Counter()
    reclassified_human_to_other_bot_count = 0
    reclassified_human_to_other_bot_by_author: Counter[str] = Counter()
    sample_rescued: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for idx, row in df.iterrows():
        if bool(row["is_jev_signal"]):
            reparse_rescued.append(False)
            reparse_patterns.append("existing_jev_signal")
            continue

        body = str(row.get("body_excerpt") or "")
        repo = str(row.get("repo_full_name") or "")
        author = str(row.get("author_login") or "")
        orig_bot_family = str(row.get("bot_family") or "")
        parsed = classify_unparsed_comment(body, repo, author)
        if parsed is None:
            if is_bot_login_misclassified_as_human(orig_bot_family, author):
                df.at[idx, "bot_family"] = "other_bot"
                reclassified_human_to_other_bot_count += 1
                reclassified_human_to_other_bot_by_author[author] += 1
                reparse_rescued.append(False)
                reparse_patterns.append("reclassified_bot_login_to_other_bot")
                continue
            reparse_rescued.append(False)
            reparse_patterns.append("unmatched")
            continue

        pat = parsed["reparse_pattern"]
        is_jev = bool(parsed["is_jev_signal"])

        df.at[idx, "is_jev_signal"] = is_jev
        df.at[idx, "bot_family"] = parsed["bot_family"]
        df.at[idx, "jev_model_tag"] = parsed["jev_model_tag"]
        df.at[idx, "overall_verdict"] = parsed["overall_verdict"]
        df.at[idx, "risk_score_normalized"] = parsed["risk_score_normalized"]
        df.at[idx, "jev_confidence"] = parsed["jev_confidence"]
        df.at[idx, "predicted_pr_type"] = parsed["predicted_pr_type"]
        df.at[idx, "alerts_count"] = int(parsed["alerts_count"])
        df.at[idx, "rule_alerts_json"] = parsed["rule_alerts_json"]
        df.at[idx, "calls_count"] = int(parsed["calls_count"])
        df.at[idx, "bound_commit_sha"] = parsed["bound_commit_sha"]

        reparse_patterns.append(pat)
        if is_jev:
            reparse_rescued.append(True)
            rescued_by_repo[repo] += 1
            rescued_by_pattern[pat] += 1
            if len(sample_rescued[pat]) < 3:
                sample_rescued[pat].append(
                    {
                        "repo_full_name": repo,
                        "pr_number": int(row["pr_number"]),
                        "author_login": author,
                        "bot_family": parsed["bot_family"],
                        "overall_verdict": parsed["overall_verdict"],
                        "alerts_count": int(parsed["alerts_count"]),
                    }
                )
        else:
            reparse_rescued.append(False)
            non_jev_gate_by_repo[f"{repo}::{pat}"] += 1

    df["reparse_rescued"] = reparse_rescued
    df["reparse_pattern"] = reparse_patterns

    out_pq = paths.results_dir / "jev_bot_signals_reparsed.parquet"
    df.to_parquet(out_pq, index=False)

    post_jev_rows = int(df["is_jev_signal"].sum())
    post_jev_prs = int(
        df.loc[df["is_jev_signal"] == True, ["repo_full_name", "pr_number"]]
        .drop_duplicates()
        .shape[0]
    )
    bot_family_counts = {str(k): int(v) for k, v in df["bot_family"].value_counts().items()}

    audit = {
        "execution_timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source_parquet": str(src_pq),
        "output_parquet": str(out_pq),
        "total_comment_rows": int(len(df)),
        "pre_reparse_jev_signal_rows": pre_jev_rows,
        "post_reparse_jev_signal_rows": post_jev_rows,
        "rescued_jev_signal_rows": int(sum(reparse_rescued)),
        "pre_reparse_jev_distinct_prs": pre_jev_prs,
        "post_reparse_jev_distinct_prs": post_jev_prs,
        "rescued_by_repo": dict(rescued_by_repo.most_common()),
        "rescued_by_pattern": dict(rescued_by_pattern.most_common()),
        "non_jev_merge_gate_reclassified": dict(non_jev_gate_by_repo.most_common()),
        "reclassified_human_comment_to_other_bot_count": reclassified_human_to_other_bot_count,
        "reclassified_human_comment_to_other_bot_by_author": dict(reclassified_human_to_other_bot_by_author.most_common()),
        "post_reparse_bot_family_counts": bot_family_counts,
        "sample_rescued_records": dict(sample_rescued),
    }
    out_audit = paths.results_dir / "jev_offline_reparse_audit.json"
    out_audit.write_text(json.dumps(audit, indent=2), encoding="utf-8")

    log.info(
        "Offline Jev reparse complete: pre_jev_rows=%d (%d PRs) -> post_jev_rows=%d (%d PRs) | rescued=%d | human->other_bot=%d | out=%s",
        pre_jev_rows,
        pre_jev_prs,
        post_jev_rows,
        post_jev_prs,
        audit["rescued_jev_signal_rows"],
        reclassified_human_to_other_bot_count,
        out_pq,
    )
    log.info("Rescued by repo: %s", json.dumps(audit["rescued_by_repo"]))
    log.info("Rescued by pattern: %s", json.dumps(audit["rescued_by_pattern"]))
    log.info("Non-Jev deterministic merge gates separated: %s", json.dumps(audit["non_jev_merge_gate_reclassified"]))
    log.info(
        "Reclassified human_comment -> other_bot (%d total): %s",
        reclassified_human_to_other_bot_count,
        json.dumps(audit["reclassified_human_comment_to_other_bot_by_author"]),
    )
    return audit


def main() -> None:
    paths = get_paths()
    paths.ensure_dirs()
    log, _ = setup_verbose_logger(
        "p00_reparse_jev_offline",
        paths.logs_dir,
        cumulative_filename="pr_analysis_execution.log",
    )
    run_reparse(paths, log)


if __name__ == "__main__":
    main()
