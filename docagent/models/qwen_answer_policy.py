from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docagent.models.base import GenerationError, GenerationResult, ModelLoadError
from docagent.models.output_parser import parse_generation_output
from docagent.schemas import EvidenceBlock
from docagent.workflow.prompts import build_answer_messages, fallback_chat_prompt


@dataclass
class QwenAnswerPolicyConfig:
    mode: str = "base"
    base_model_path: str = ""
    adapter_path: str | None = None
    device: str = "cuda"
    torch_dtype: str = "bfloat16"
    trust_remote_code: bool = True
    local_files_only: bool = True
    max_prompt_tokens: int | None = 4096
    max_new_tokens: int = 1024
    do_sample: bool = False
    temperature: float = 0.0
    top_p: float = 1.0
    enable_thinking: bool = False
    append_no_think: bool = True
    max_chars_per_block: int = 1200
    max_total_chars: int | None = None
    max_reason_chars: int | None = 300


class QwenAnswerPolicy:
    def __init__(
        self,
        config: QwenAnswerPolicyConfig,
        *,
        tokenizer: Any | None = None,
        model: Any | None = None,
    ) -> None:
        if config.mode not in {"base", "sft", "grpo"}:
            raise ValueError(f"unsupported Qwen policy mode: {config.mode}")
        self.config = config
        self.mode = config.mode
        self._tokenizer = tokenizer
        self._model = model
        self._loaded = tokenizer is not None and model is not None

    def generate(
        self,
        *,
        question: str,
        evidence_blocks: list[EvidenceBlock],
        tool_results: list[dict[str, Any]] | None = None,
        answer_type: str | None = None,
        qid: str | None = None,
    ) -> GenerationResult:
        start = time.perf_counter()
        tokenizer, model = self._load()
        messages = build_answer_messages(
            question=question,
            evidence_blocks=evidence_blocks,
            tool_results=tool_results,
            answer_type=answer_type,
            append_no_think=self.config.append_no_think,
            max_chars_per_block=self.config.max_chars_per_block,
            max_total_chars=self.config.max_total_chars,
        )
        prompt_text = self._render_prompt(tokenizer, messages)
        prompt_text = self._cap_prompt(tokenizer, prompt_text)
        prompt_token_count = self._count_tokens(tokenizer, prompt_text)

        try:
            import torch
        except Exception as exc:  # pragma: no cover - exercised on GPU host
            raise GenerationError(f"failed to import torch for generation: {exc}") from exc

        try:
            inputs = tokenizer(prompt_text, return_tensors="pt")
            inputs = {key: value.to(model.device) for key, value in inputs.items()}
            generate_kwargs: dict[str, Any] = {
                "max_new_tokens": self.config.max_new_tokens,
                "do_sample": self.config.do_sample,
                "pad_token_id": tokenizer.eos_token_id,
            }
            if self.config.do_sample:
                generate_kwargs["temperature"] = self.config.temperature
                generate_kwargs["top_p"] = self.config.top_p
            with torch.inference_mode():
                output_ids = model.generate(**inputs, **generate_kwargs)
        except Exception as exc:  # pragma: no cover - exercised on GPU host
            raise GenerationError(f"Qwen generation failed: {exc}") from exc

        prompt_width = inputs["input_ids"].shape[-1]
        generated_ids = output_ids[0, prompt_width:]
        raw_text = tokenizer.decode(generated_ids, skip_special_tokens=True)
        parse_result = parse_generation_output(raw_text, max_reason_chars=self.config.max_reason_chars)
        return GenerationResult(
            raw_text=raw_text,
            parsed=parse_result.parsed,
            prompt_text=prompt_text,
            prompt_token_count=prompt_token_count,
            completion_token_count=int(generated_ids.shape[-1]),
            finish_reason=None,
            latency_ms=(time.perf_counter() - start) * 1000,
            metadata={
                "policy_mode": self.mode,
                "qid": qid,
                "parse_result": parse_result.to_dict(),
                "max_new_tokens": self.config.max_new_tokens,
                "do_sample": self.config.do_sample,
            },
        )

    def _load(self) -> tuple[Any, Any]:
        if self._loaded:
            return self._tokenizer, self._model

        model_path = Path(self.config.base_model_path)
        if not (model_path / "config.json").is_file():
            raise ModelLoadError(f"base model is missing config.json: {model_path}")
        adapter_path = Path(self.config.adapter_path) if self.config.adapter_path else None
        if self.config.mode in {"sft", "grpo"}:
            if adapter_path is None:
                raise ModelLoadError(f"adapter_path is required for mode={self.config.mode}")
            self._check_adapter_path(adapter_path)

        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except Exception as exc:
            raise ModelLoadError(f"failed to import Qwen runtime dependencies: {exc}") from exc

        dtype = self._torch_dtype(torch)
        try:
            tokenizer = AutoTokenizer.from_pretrained(
                str(model_path),
                local_files_only=self.config.local_files_only,
                trust_remote_code=self.config.trust_remote_code,
            )
            if tokenizer.pad_token_id is None:
                tokenizer.pad_token = tokenizer.eos_token
            base_model = AutoModelForCausalLM.from_pretrained(
                str(model_path),
                torch_dtype=dtype,
                local_files_only=self.config.local_files_only,
                trust_remote_code=self.config.trust_remote_code,
            )
            if adapter_path is not None:
                from peft import PeftModel

                model = PeftModel.from_pretrained(base_model, str(adapter_path), is_trainable=False)
            else:
                model = base_model
            if self.config.device == "cuda":
                if not torch.cuda.is_available():
                    raise ModelLoadError("CUDA device requested but torch.cuda.is_available() is false")
                model = model.to("cuda")
            elif self.config.device not in {"auto", "none"}:
                model = model.to(self.config.device)
            model.eval()
        except ModelLoadError:
            raise
        except Exception as exc:
            raise ModelLoadError(f"failed to load Qwen policy: {exc}") from exc

        self._tokenizer = tokenizer
        self._model = model
        self._loaded = True
        return tokenizer, model

    def _torch_dtype(self, torch: Any) -> Any:
        if self.config.torch_dtype == "bfloat16":
            return torch.bfloat16
        if self.config.torch_dtype == "float16":
            return torch.float16
        if self.config.torch_dtype == "float32":
            return torch.float32
        return "auto"

    def _check_adapter_path(self, adapter_path: Path) -> None:
        if not adapter_path.is_dir():
            raise ModelLoadError(f"adapter path does not exist: {adapter_path}")
        if not (adapter_path / "adapter_config.json").is_file():
            raise ModelLoadError(f"adapter checkpoint is missing adapter_config.json: {adapter_path}")
        if not any((adapter_path / name).is_file() for name in ("adapter_model.safetensors", "adapter_model.bin")):
            raise ModelLoadError(f"adapter checkpoint is missing adapter weights: {adapter_path}")

    def _render_prompt(self, tokenizer: Any, messages: list[dict[str, str]]) -> str:
        try:
            return tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=self.config.enable_thinking,
            )
        except TypeError:
            try:
                return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            except Exception:
                return fallback_chat_prompt(messages)
        except Exception:
            return fallback_chat_prompt(messages)

    def _count_tokens(self, tokenizer: Any, text: str) -> int | None:
        try:
            return len(tokenizer(text, add_special_tokens=False)["input_ids"])
        except Exception:
            return None

    def _cap_prompt(self, tokenizer: Any, prompt_text: str) -> str:
        limit = self.config.max_prompt_tokens
        if limit is None or limit <= 0:
            return prompt_text
        try:
            ids = tokenizer(prompt_text, add_special_tokens=False)["input_ids"]
            if len(ids) <= limit:
                return prompt_text
            return tokenizer.decode(ids[-limit:], skip_special_tokens=True)
        except Exception:
            return prompt_text
