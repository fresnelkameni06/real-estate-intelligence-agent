"""Run the multi-tool real-estate agent in one-shot or interactive mode."""

from __future__ import annotations

import argparse
import sys
from importlib import import_module
from pathlib import Path

from real_estate_agent.agent import ConversationMessage

# Direct execution (`py scripts/chat_agent.py`) puts scripts/ rather than the
# repository root on sys.path. Add that root before loading the FastAPI composition.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
get_agent_service = import_module("app.api.dependencies").get_agent_service


def _print_result(result) -> None:
    print(f"\n{result.answer}\n")
    if result.tool_executions:
        tools = ", ".join(
            execution.name
            for execution in result.tool_executions
            if execution.success
        )
        if tools:
            print(f"Outils: {tools}")
    if result.citations:
        print("Sources:")
        seen: set[tuple[str, str]] = set()
        for citation in result.citations:
            key = (citation.title, citation.url)
            if key in seen:
                continue
            seen.add(key)
            print(f"- {citation.title}: {citation.url}")


def _ask(question: str, history: list[ConversationMessage]):
    return get_agent_service().answer(question, history=history)


def _interactive() -> int:
    print("Analyste IA immobilier — tapez 'quit' pour terminer.")
    history: list[ConversationMessage] = []
    while True:
        try:
            question = input("\nVous > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if question.casefold() in {"exit", "quit", "quitter"}:
            return 0
        if not question:
            continue
        try:
            result = _ask(question, history)
        except RuntimeError:
            print("L’Agent est indisponible. Vérifiez FastAPI, PostgreSQL et votre clé API.")
            return 1
        _print_result(result)
        history.extend(
            [
                ConversationMessage(role="user", content=question),
                ConversationMessage(role="assistant", content=result.answer),
            ]
        )
        history = history[-12:]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="*", help="Question for a one-shot run")
    args = parser.parse_args()
    if not args.question:
        return _interactive()
    try:
        result = _ask(" ".join(args.question), [])
    except RuntimeError:
        print(
            "L’Agent est indisponible. Vérifiez PostgreSQL, les embeddings et "
            "OPENAI_API_KEY.",
            file=sys.stderr,
        )
        return 1
    _print_result(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
