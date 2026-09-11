"""One tiny round trip through app.services.llm to prove the configured
model answers. Run from the project root with the venv active:
    python scripts/smoke_llm.py [model-name]
"""

import sys

from app.services.llm import LLM


def main() -> None:
    llm = LLM.initialize(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"{llm.provider} / {llm.model_name}: {llm.ask('Reply with exactly: ok')!r}")


if __name__ == "__main__":
    main()
