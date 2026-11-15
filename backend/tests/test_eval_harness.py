"""Eval harness (0.5.0) with mock members only. No model is called."""

import json
from pathlib import Path

import pytest

from eval.mock import MockEvalProvider
from eval.run_eval import QUESTIONS, evaluate, markdown, score, write

MEMBERS = [{"nickname": f"模拟{n}{i}", "provider": "mock", "model_id": "mock-eval"} for i, n in enumerate("甲乙丙", start=1)]


def test_question_set_is_fixed_and_balanced():
    kinds = [q["kind"] for q in QUESTIONS]
    assert len(QUESTIONS) == 10
    assert {"reasoning", "factual", "opinion"} == set(kinds)
    assert len({q["id"] for q in QUESTIONS}) == 10


def test_score_rules():
    q = next(q for q in QUESTIONS if q["id"] == "r1")
    assert score(q, "球 0.05 元")["correct"] is True
    assert score(q, "0.05 还是 0.10？")["correct"] is False
    o = next(q for q in QUESTIONS if q["id"] == "o1")
    assert score(o, "成本和迭代")["coverage"] == 0.5


class Judge:
    def preflight(self, req):
        return None

    async def stream(self, req, cancel, stale):
        yield "4"


@pytest.mark.asyncio
async def test_mock_run_produces_labeled_report(tmp_path):
    report = await evaluate(MEMBERS, MockEvalProvider(), "mock", rounds=3, timeout=30, judge_member={"provider": "mock", "model_id": "judge"}, judge_provider=Judge(), limit=4)
    assert [i["id"] for i in report["items"]] == ["r1", "r2", "r3", "r4"]
    item = report["items"][0]
    assert item["single"]["score"]["correct"] is False  # 模拟甲1 独立回答时犯直觉错误
    assert item["group"]["ai_messages"] > item["single"]["ai_messages"]
    assert item["single"]["judge"] == 4 and report["totals"]["group"]["judge_mean"] == 4
    write(report, tmp_path, mock=True)
    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert md.startswith("> **模拟运行（MOCK）**")
    assert json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))["mock"] is True


def test_shipped_results_are_marked_mock():
    out = Path(__file__).resolve().parents[1] / "eval" / "results" / "mock"
    assert json.loads((out / "report.json").read_text(encoding="utf-8"))["mock"] is True
    assert "模拟运行（MOCK）" in (out / "report.md").read_text(encoding="utf-8")
