from __future__ import annotations

import sys

from scripts.no_vllm_stub import install_no_vllm_stub


def main() -> None:
    install_no_vllm_stub()
    from swift.cli.main import cli_main

    sys.argv = ["swift", "rlhf", *sys.argv[1:]]
    cli_main()


if __name__ == "__main__":
    main()
