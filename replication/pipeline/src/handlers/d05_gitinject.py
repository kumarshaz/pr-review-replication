#!/usr/bin/env python3
import ast
import os
import re
from typing import Any, Dict, List, Optional

from src.handlers.base import BaseDatasetHandler

# Deterministic Layer-0 Static Invariant Detectors (zero label/path-name cheating):
# Inspects ONLY untrusted runtime inputs (file paths under contents/, file contents,
# and AST event/template payloads—NEVER class docstrings, scenario_type, labels, or evaluators).
INV02_OPERATOR_BOUNDARY_RE = re.compile(
    r"(^|/)(CLAUDE\.md|AGENTS\.md|GEMINI\.md|\.cursorrules|\.cursor/.*|"
    r"\.github/workflows/.*|Dockerfile|docker-compose.*\.ya?ml|serverless\.ya?ml|deploy_check\.sh)$",
    re.IGNORECASE,
)

INV05_PAYLOAD_RULES = [
    (re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.IGNORECASE), "INV-05_PROMPT_INJECTION_OVERRIDE"),
    (re.compile(r"(do\s+not\s+flag|always\s+approve|approve\s+(this\s+)?pr\s+without|skip\s+security\s+check)", re.IGNORECASE), "INV-05_APPROVAL_MANIPULATION"),
    (re.compile(r"(\$?GITHUB_TOKEN|http\.extraheader|STRIPE_LIVE_KEY|AWS_SECRET_ACCESS_KEY)", re.IGNORECASE), "INV-05_SECRET_OR_TOKEN_TARGETING"),
    (re.compile(r"(exfiltrat|curl\s+.*https?://|wget\s+.*https?://).*(token|secret|env|key|credential|base64)", re.IGNORECASE | re.DOTALL), "INV-05_EXFILTRATION_COMMAND"),
    (re.compile(r"<!--\s*(system|assistant|agent|instruction|important)", re.IGNORECASE), "INV-05_HIDDEN_HTML_INJECTION"),
]


def _extract_untrusted_event_strings(py_src: str) -> str:
    """
    Parses scenario.py via AST and extracts ONLY untrusted runtime input payloads:
      - Module-level string/template assignments (e.g., ISSUE_BODY_TEMPLATE, _PR_BODY, _FILLER)
      - String constants inside `get_event()`
    Strictly excludes class docstrings, `labels`, `scenario_type`, and evaluator rubrics
    so zero ground-truth metadata leaks into the static detector.
    """
    chunks: List[str] = []
    try:
        tree = ast.parse(py_src)
    except SyntaxError:
        return ""

    # Track simple string constants & repeated string expressions at module level
    env: Dict[str, str] = {}

    def _eval_str(node: ast.AST) -> str:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name) and node.id in env:
            return env[node.id]
        if isinstance(node, ast.BinOp):
            if isinstance(node.op, ast.Add):
                return _eval_str(node.left) + _eval_str(node.right)
            if isinstance(node.op, ast.Mult):
                if isinstance(node.right, ast.Constant) and isinstance(node.right.value, int):
                    return _eval_str(node.left) * min(node.right.value, 5000)
                if isinstance(node.left, ast.Constant) and isinstance(node.left.value, int):
                    return _eval_str(node.right) * min(node.left.value, 5000)
        return ""

    for node in tree.body:
        if isinstance(node, ast.Assign):
            val = _eval_str(node.value)
            if val:
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        env[tgt.id] = val
                        chunks.append(val)
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "get_event":
                    for sub in ast.walk(item):
                        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and len(sub.value) > 4:
                            chunks.append(sub.value)
                        elif isinstance(sub, ast.Name) and sub.id in env:
                            chunks.append(env[sub.id])
    return "\n".join(chunks)


def _evaluate_scenario_static_gate(scenario_dir: str) -> Dict[str, Any]:
    """Executes deterministic static INV-02 / INV-05 inspection over untrusted inputs."""
    py_path = os.path.join(scenario_dir, "scenario.py")
    with open(py_path, "r", encoding="utf-8", errors="replace") as f:
        py_src = f.read()
    untrusted_event_text = _extract_untrusted_event_strings(py_src)

    cdir = os.path.join(scenario_dir, "contents")
    content_files: List[str] = []
    content_bodies: List[str] = []
    if os.path.exists(cdir):
        for cr, _cd, cfs in sorted(os.walk(cdir)):
            for cf in sorted(cfs):
                fpath = os.path.join(cr, cf)
                rel_f = os.path.relpath(fpath, cdir)
                content_files.append(rel_f)
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    content_bodies.append(f.read())

    triggered: List[str] = []

    # 1. INV-02: Operator trust / execution boundary file modification
    for rel_f in content_files:
        if INV02_OPERATOR_BOUNDARY_RE.search(rel_f):
            triggered.append(f"INV-02_OPERATOR_BOUNDARY_FILE:{rel_f}")

    # 2. INV-05: Context-exhaustion / oversized untrusted PR body (> 32,768 chars)
    if len(untrusted_event_text) > 32768:
        triggered.append(f"INV-05_OVERSIZED_PAYLOAD_DOS:{len(untrusted_event_text)}_chars")

    # 3. INV-05: Lexical injection / token exfiltration rules over untrusted event + non-test files
    combined_untrusted = untrusted_event_text + "\n" + "\n".join(
        body for rel_f, body in zip(content_files, content_bodies)
        if not rel_f.startswith("tests/")
    )
    for rx, code in INV05_PAYLOAD_RULES:
        if rx.search(combined_untrusted):
            triggered.append(code)

    # 4. INV-05: Non-constant-time comparison check inside crypto utility files
    for rel_f, body in zip(content_files, content_bodies):
        if "crypto" in rel_f.lower() or "csrf" in rel_f.lower():
            if re.search(r"def\s+constant_time_compare[\s\S]{0,400}if\s+len\(", body) or re.search(
                r"(csrf_token|signature|hmac)\s*==(?!=)", body
            ):
                triggered.append(f"INV-05_CRYPTO_TIMING_INVARIANT:{rel_f}")

    triggered_unique = sorted(set(triggered))
    return {
        "quarantined": len(triggered_unique) > 0,
        "triggered_invariants": triggered_unique,
        "content_files": content_files,
        "untrusted_event_chars": len(untrusted_event_text),
    }


class GitInjectHandler(BaseDatasetHandler):
    @property
    def dataset_id(self) -> str:
        return "dataset_5_gitinject"

    @property
    def dataset_name(self) -> str:
        return "GitInject"

    @property
    def primary_entity(self) -> str:
        return "CI/CD & Review Agent Prompt Injection"

    @property
    def lemon_market_implication(self) -> str:
        return "Empirically evaluates static INV-02 boundary and INV-05 payload gates against adversarial CI/CD injection scenarios without LLM execution"

    @property
    def raw_files(self) -> List[str]:
        return ["scratch/gitinject"]

    @property
    def calculating_programs(self) -> List[str]:
        return ["p05_multicorpus_triangulation.py"]

    @property
    def telemetry_capabilities(self) -> List[str]:
        return ["adversarial_injection_quarantine"]

    def execute(self, con: Any, repo_root: Optional[str] = None) -> Dict[str, Any]:
        scenarios_dir = self.scratch_path("gitinject", "src", "gitinject", "scenarios")

        benign_scenarios: List[str] = []
        malicious_scenarios: List[str] = []
        per_scenario_eval: List[Dict[str, Any]] = []
        inv02_caught: List[str] = []
        inv05_caught: List[str] = []
        missed_malicious: List[str] = []
        false_positives: List[str] = []

        if os.path.exists(scenarios_dir):
            for root, _dirs, files in sorted(os.walk(scenarios_dir)):
                if "scenario.py" not in files:
                    continue
                rel = os.path.relpath(root, scenarios_dir)
                is_mal = rel.startswith("malicious")
                if is_mal:
                    malicious_scenarios.append(rel)
                elif rel.startswith("benign"):
                    benign_scenarios.append(rel)
                else:
                    continue

                ev = _evaluate_scenario_static_gate(root)
                per_scenario_eval.append({
                    "scenario": rel,
                    "ground_truth": "malicious" if is_mal else "benign",
                    **ev,
                })
                if is_mal:
                    if ev["quarantined"]:
                        if any(t.startswith("INV-02_") for t in ev["triggered_invariants"]):
                            inv02_caught.append(rel)
                        if any(t.startswith("INV-05_") for t in ev["triggered_invariants"]):
                            inv05_caught.append(rel)
                    else:
                        missed_malicious.append(rel)
                else:
                    if ev["quarantined"]:
                        false_positives.append(rel)

        tp = sum(1 for r in per_scenario_eval if r["ground_truth"] == "malicious" and r["quarantined"])
        fn = sum(1 for r in per_scenario_eval if r["ground_truth"] == "malicious" and not r["quarantined"])
        fp = sum(1 for r in per_scenario_eval if r["ground_truth"] == "benign" and r["quarantined"])
        tn = sum(1 for r in per_scenario_eval if r["ground_truth"] == "benign" and not r["quarantined"])

        recall_pct = round(100.0 * tp / (tp + fn), 2) if (tp + fn) > 0 else 0.0
        prec_pct = round(100.0 * tp / (tp + fp), 2) if (tp + fp) > 0 else 0.0
        fpr_pct = round(100.0 * fp / (fp + tn), 2) if (fp + tn) > 0 else 0.0

        return {
            "total_scenarios": len(benign_scenarios) + len(malicious_scenarios),
            "benign_scenarios_count": len(benign_scenarios),
            "malicious_scenarios_count": len(malicious_scenarios),
            "malicious_scenario_catalog": sorted(malicious_scenarios),
            "static_gate_evaluation": {
                "tp": tp,
                "fn": fn,
                "fp": fp,
                "tn": tn,
                "precision_pct": prec_pct,
                "recall_pct": recall_pct,
                "false_positive_rate_pct": fpr_pct,
                "missed_malicious": sorted(missed_malicious),
                "false_positive_benign": sorted(false_positives),
            },
            "quarantine_containment_rate_pct": recall_pct,
            "enforced_invariants": {
                "INV-02_operator_boundary_files_caught": sorted(inv02_caught),
                "INV-05_payload_and_crypto_invariants_caught": sorted(inv05_caught),
            },
            "per_scenario_results": per_scenario_eval,
        }

    def get_summary_row(self, result: Dict[str, Any]) -> List[Any]:
        ev = result.get("static_gate_evaluation", {})
        return [
            self.primary_entity,
            f"{result['total_scenarios']} scenarios ({result['malicious_scenarios_count']} malicious, {result['benign_scenarios_count']} benign)",
            f"Static Gate Recall: {result['quarantine_containment_rate_pct']}% ({ev.get('tp', 0)}/{result['malicious_scenarios_count']}) | FPR: {ev.get('false_positive_rate_pct', 0.0)}%",
            f"INV-02 caught={len(result.get('enforced_invariants', {}).get('INV-02_operator_boundary_files_caught', []))}, INV-05 caught={len(result.get('enforced_invariants', {}).get('INV-05_payload_and_crypto_invariants_caught', []))}",
            self.lemon_market_implication,
        ]
