"""Evaluate the live Agent against versioned structural expectations."""

from __future__ import annotations

import argparse
import sys
from importlib import import_module
from pathlib import Path

from real_estate_agent.agent import AgentModelTurn, AgentService
from real_estate_agent.evaluation import load_evaluation_suite, run_evaluation
from real_estate_agent.evaluation.runner import select_cases
from real_estate_agent.tools import ToolRegistry

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUITE_PATH = PROJECT_ROOT / "config" / "evaluation" / "agent_cases.json"
EVALUATION_CATEGORIES = (
    "conversation",
    "market",
    "dpe",
    "documentary",
    "combined",
    "memory",
    "scope",
    "security",
)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
get_agent_service = import_module("app.api.dependencies").get_agent_service


class _ForbiddenExternalModel:
    """Fail loudly if a declared local-only case reaches model orchestration."""

    model = "forbidden-external-model"

    def respond(self, **_kwargs: object) -> AgentModelTurn:
        raise AssertionError("A local-only evaluation case reached the model.")


def _service_for(cases):
    if all(case.expected_model == "local-conversation-router" for case in cases):
        return AgentService(
            model=_ForbiddenExternalModel(),
            registry=ToolRegistry([]),
        )
    return get_agent_service()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        type=Path,
        default=DEFAULT_SUITE_PATH,
        help="Path to the versioned JSON evaluation suite.",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="Run one case by ID; repeat the option to select several cases.",
    )
    parser.add_argument(
        "--category",
        choices=EVALUATION_CATEGORIES,
        help="Run only cases from one category.",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        help="Limit live calls while performing a low-cost smoke test.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and list selected cases without calling PostgreSQL or OpenAI.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optionally write the complete machine-readable result as JSON.",
    )
    parser.add_argument(
        "--fail-below",
        type=float,
        default=0.80,
        help="Return a failing exit code below this pass rate (default: 0.80).",
    )
    return parser


def _print_selected(cases) -> None:
    print(f"Selected evaluation cases: {len(cases)}")
    for case in cases:
        tools = ", ".join(case.required_tools) or "none"
        print(
            f"- {case.case_id} | category={case.category} | "
            f"route={case.expected_route} | required_tools={tools}"
        )


def _print_case_result(result) -> None:
    status = "PASS" if result.passed else "FAIL"
    tools = ", ".join(result.successful_tools) or "none"
    print(
        f"[{status}] {result.case_id} | route={result.actual_route or 'error'} | "
        f"tools={tools} | {result.latency_ms:.0f} ms"
    )
    for failure in result.failures:
        print(f"       - {failure}")


def _print_summary(summary) -> None:
    print("\nAgent evaluation summary")
    print("=" * 72)
    print("-" * 72)
    print(
        f"Passed: {summary.passed_cases}/{summary.evaluated_cases} "
        f"({summary.pass_rate:.1%})"
    )
    print(f"Route accuracy:        {summary.route_accuracy:.1%}")
    print(f"Tool selection:        {summary.tool_selection_accuracy:.1%}")
    print(f"Citation compliance:   {summary.citation_accuracy:.1%}")
    print(f"Visualization checks:  {summary.visualization_accuracy:.1%}")
    print(f"Memory checks:         {summary.memory_accuracy:.1%}")
    print(f"Model policy:          {summary.model_policy_accuracy:.1%}")
    print(f"Answer constraints:    {summary.answer_constraint_accuracy:.1%}")
    print(f"Average latency:       {summary.average_latency_ms:.0f} ms")


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    if not 0 <= args.fail_below <= 1:
        parser.error("--fail-below must be between 0 and 1")

    try:
        suite = load_evaluation_suite(args.suite)
        cases = select_cases(
            suite,
            case_ids=args.case_id,
            category=args.category,
            max_cases=args.max_cases,
        )
    except ValueError as exc:
        parser.error(str(exc))

    _print_selected(cases)
    if args.dry_run:
        print("Dry run complete: no database or OpenAI call was made.")
        return 0

    print("\nRunning live evaluation…")
    summary = run_evaluation(
        _service_for(cases),
        suite,
        cases,
        on_result=_print_case_result,
    )
    _print_summary(summary)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            summary.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Detailed JSON written to: {args.output}")

    return 0 if summary.pass_rate >= args.fail_below else 1


if __name__ == "__main__":
    sys.exit(main())
