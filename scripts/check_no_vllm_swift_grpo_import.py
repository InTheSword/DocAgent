from __future__ import annotations

import json
import traceback
from scripts.no_vllm_stub import install_no_vllm_stub


def main() -> None:
    install_no_vllm_stub()

    results: dict[str, dict[str, object]] = {}
    for name in [
        "swift.infer_engine.grpo_vllm_engine",
        "swift.rlhf_trainers.rollout_mixin",
        "swift.rlhf_trainers.grpo_trainer",
    ]:
        try:
            __import__(name)
            results[name] = {"status": "ok"}
        except Exception as exc:
            results[name] = {
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback_tail": traceback.format_exc().splitlines()[-25:],
            }

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
