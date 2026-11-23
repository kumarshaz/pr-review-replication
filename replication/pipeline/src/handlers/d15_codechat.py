#!/usr/bin/env python3
"""
Dataset 15 Handler: CodeChat Multi-Turn Developer Interactions (arXiv:2509.10402 / shareAI)
Captures real-world multi-turn developer prompts and assistant code generations
to analyze cognitive intent debt, prompt length expansion, and clarification cycles.
"""
import json
import os
from typing import Any, Dict, List, Optional

from src.handlers.base import BaseDatasetHandler


class CodeChatHandler(BaseDatasetHandler):
    @property
    def dataset_id(self) -> str:
        return "dataset_15_codechat_conversations"

    @property
    def dataset_name(self) -> str:
        return "CodeChat Multi-Turn Developer Interactions"

    @property
    def primary_entity(self) -> str:
        return "Multi-Turn Developer-LLM Interactive Dialogues"

    @property
    def lemon_market_implication(self) -> str:
        return "Demonstrates conversational cognitive intent debt and iterative prompt expansion in real-world AI coding"

    @property
    def raw_files(self) -> List[str]:
        return ["scratch/codechat/codechat_conversations.jsonl"]

    @property
    def calculating_programs(self) -> List[str]:
        return ["p05_multicorpus_triangulation.py"]

    @property
    def telemetry_capabilities(self) -> List[str]:
        return [
            "conversation_turns",
            "prompt_typologies",
            "rationale_sharing",
        ]

    def execute(self, con: Any, repo_root: Optional[str] = None) -> Dict[str, Any]:
        f_chat = self.scratch_path("codechat", "codechat_conversations.jsonl")

        d15_results: Dict[str, Any] = {
            "dataset_name": "CodeChat Multi-Turn Developer-LLM Dialogues (arXiv:2509.10402)",
            "sample_size_n": 0,
            "total_conversations": 0,
            "total_turns": 0,
            "avg_turns_per_conversation": 0.0,
            "avg_human_prompt_length_chars": 0.0,
            "avg_assistant_response_length_chars": 0.0,
            "multi_turn_conversations_pct": 0.0,
            "status": "not_found",
        }

        if os.path.exists(f_chat):
            with open(f_chat, "r", encoding="utf-8") as f:
                lines = [json.loads(line) for line in f if line.strip()]

            total_convs = len(lines)
            total_turns = sum(len(c.get("conversation", [])) for c in lines)
            multi_turn_count = sum(1 for c in lines if len(c.get("conversation", [])) > 1)
            total_human_chars = sum(sum(len(t.get("human", "")) for t in c.get("conversation", [])) for c in lines)
            total_asst_chars = sum(sum(len(t.get("assistant", "")) for t in c.get("conversation", [])) for c in lines)

            avg_turns = round(total_turns / total_convs, 2) if total_convs else 0.0
            avg_human_len = round(total_human_chars / total_turns, 1) if total_turns else 0.0
            avg_asst_len = round(total_asst_chars / total_turns, 1) if total_turns else 0.0
            multi_turn_pct = round(multi_turn_count * 100.0 / total_convs, 2) if total_convs else 0.0

            d15_results = {
                "dataset_name": "CodeChat Multi-Turn Developer-LLM Dialogues (arXiv:2509.10402)",
                "sample_size_n": total_convs,
                "total_conversations": total_convs,
                "total_turns": total_turns,
                "avg_turns_per_conversation": avg_turns,
                "avg_human_prompt_length_chars": avg_human_len,
                "avg_assistant_response_length_chars": avg_asst_len,
                "multi_turn_conversations_pct": multi_turn_pct,
                "status": "verified_on_disk",
            }
        return d15_results

    def get_summary_row(self, result: Dict[str, Any]) -> List[Any]:
        n = result.get("sample_size_n", 0)
        turns = result.get("total_turns", 0)
        return [
            self.primary_entity,
            f"{n:,} dialogues ({turns:,} turns)",
            f"Avg Turns/Conv: {result.get('avg_turns_per_conversation', 0.0)}",
            f"Prompt vs Resp: {result.get('avg_human_prompt_length_chars', 0.0):.0f} vs {result.get('avg_assistant_response_length_chars', 0.0):.0f} chars",
            self.lemon_market_implication,
        ]
