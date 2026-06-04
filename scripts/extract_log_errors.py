from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ERROR_PATTERNS = [
    "traceback",
    "error:",
    "exception",
    "failed",
    "childfailederror",
    "runtimeerror",
    "valueerror",
    "typeerror",
    "attributeerror",
    "importerror",
    "modulenotfounderror",
    "outofmemory",
    "out of memory",
    "cuda out of memory",
    "sigterm",
    "exitcode",
]


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="ignore").splitlines()


def context_window(lines: list[str], index: int, before: int, after: int) -> list[str]:
    start = max(0, index - before)
    end = min(len(lines), index + after + 1)
    return lines[start:end]


def first_error_context(lines: list[str], before: int, after: int) -> list[str]:
    for index, line in enumerate(lines):
        lowered = line.lower()
        if any(pattern in lowered for pattern in ERROR_PATTERNS):
            return context_window(lines, index, before, after)
    return []


def traceback_contexts(lines: list[str], before: int, after: int, limit: int) -> list[list[str]]:
    contexts: list[list[str]] = []
    for index, line in enumerate(lines):
        if "traceback (most recent call last)" in line.lower():
            contexts.append(context_window(lines, index, before, after))
            if len(contexts) >= limit:
                break
    return contexts


def matched_lines(lines: list[str], limit: int) -> list[str]:
    matches: list[str] = []
    pattern = re.compile("|".join(re.escape(item) for item in ERROR_PATTERNS), re.IGNORECASE)
    for line in lines:
        if pattern.search(line):
            matches.append(line)
            if len(matches) >= limit:
                break
    return matches


def summarize_log(path: Path, args: argparse.Namespace) -> dict[str, object]:
    lines = read_lines(path)
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "num_lines": len(lines),
        "first_error_context": first_error_context(lines, args.before, args.after),
        "tracebacks": traceback_contexts(lines, args.before, args.after, args.traceback_limit),
        "matched_lines": matched_lines(lines, args.match_limit),
        "tail": lines[-args.tail :] if args.tail > 0 else [],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("logs", nargs="+")
    parser.add_argument("--before", type=int, default=8)
    parser.add_argument("--after", type=int, default=30)
    parser.add_argument("--tail", type=int, default=20)
    parser.add_argument("--traceback-limit", type=int, default=2)
    parser.add_argument("--match-limit", type=int, default=40)
    parser.add_argument("--output")
    args = parser.parse_args()

    paths = [Path(item) for item in args.logs]
    report = {"logs": [summarize_log(path, args) for path in paths if path.exists()]}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
