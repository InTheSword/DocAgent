from __future__ import annotations

import importlib.abc
import importlib.util
import json
import sys
import traceback
from types import ModuleType
from typing import Any


class DummyMeta(type):
    def __getattr__(cls, name: str) -> Any:
        return cls

    def __iter__(cls):
        return iter(())

    def __bool__(cls) -> bool:
        return False


class Dummy(metaclass=DummyMeta):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs

    def __call__(self, *args: Any, **kwargs: Any) -> "Dummy":
        return Dummy(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return Dummy

    def __iter__(self):
        return iter(())

    def __bool__(self) -> bool:
        return False

    @classmethod
    def create(cls, *args: Any, **kwargs: Any) -> "Dummy":
        return cls(*args, **kwargs)


class LoRARequest:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs


class VllmStubFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname: str, path: object = None, target: object = None):
        if fullname == "vllm" or fullname.startswith("vllm."):
            return importlib.util.spec_from_loader(fullname, self, is_package=True)
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module: ModuleType) -> None:
        module.__path__ = []
        module.__version__ = "0.12.0"

        def __getattr__(name: str) -> Any:
            return Dummy

        module.__getattr__ = __getattr__  # type: ignore[attr-defined]

        if module.__name__ == "vllm.lora.request":
            module.LoRARequest = LoRARequest
        if module.__name__ == "vllm.distributed.utils":
            module.StatelessProcessGroup = Dummy
        if module.__name__.endswith("dp_coordinator"):
            module.DPCoordinator = Dummy


def main() -> None:
    sys.meta_path.insert(0, VllmStubFinder())

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
