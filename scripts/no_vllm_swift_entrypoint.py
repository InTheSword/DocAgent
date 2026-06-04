from __future__ import annotations

from scripts.no_vllm_stub import install_no_vllm_stub


def main() -> None:
    install_no_vllm_stub()
    from swift.cli.rlhf import rlhf_main

    rlhf_main()


if __name__ == "__main__":
    main()
