from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.eval.answer_metrics import exact_match, token_f1
from docagent.models.output_parser import has_thinking_text as model_has_thinking_text
from docagent.models.output_parser import parse_generation_output
from docagent.rewards.answer_reward import answer_reward
from docagent.rewards.combined import docqa_reward
from docagent.rewards.location_reward import location_reward
from docagent.tools.format_check import check_answer_format
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.build_sft_dataset import EXTRACTION_RULES_TEXT


def batched(items: list[Any], batch_size: int) -> list[list[Any]]:
    if batch_size < 1:
        raise ValueError("--batch-size must be >= 1")
    return [items[index : index + batch_size] for index in range(0, len(items), batch_size)]


def parse_target(record: dict[str, Any]) -> dict[str, Any]:
    messages = record.get("messages") or []
    if not messages or messages[-1].get("role") != "assistant":
        raise ValueError(f"missing assistant target for record {record.get('id')}")
    return json.loads(messages[-1].get("content") or "{}")


def build_inference_messages(
    record: dict[str, Any],
    disable_thinking: bool,
    strict_extraction: bool = False,
) -> list[dict[str, Any]]:
    messages = [dict(message) for message in record["messages"][:-1]]
    if strict_extraction:
        for message in messages:
            if message.get("role") == "user":
                content = message.get("content", "")
                if EXTRACTION_RULES_TEXT not in content:
                    message["content"] = (
                        f"{content}\n\n"
                        "Additional extraction rules:\n"
                        f"{EXTRACTION_RULES_TEXT}"
                    )
                break
    if not disable_thinking:
        return messages
    for message in messages:
        if message.get("role") == "system":
            message["content"] = (
                f"{message.get('content', '')} "
                "Do not include analysis, chain-of-thought, markdown, or <think> tags. "
                "Return only one valid JSON object."
            )
        elif message.get("role") == "user":
            message["content"] = (
                f"{message.get('content', '')}\n\n"
                "/no_think\n"
                "Return only one valid JSON object. Start with { and end with }."
            )
    return messages


def build_prompt(
    tokenizer: Any,
    record: dict[str, Any],
    disable_thinking: bool,
    strict_extraction: bool = False,
) -> str:
    messages = build_inference_messages(record, disable_thinking, strict_extraction)
    try:
        return tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=not disable_thinking,
        )
    except TypeError:
        try:
            return tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
        except Exception:
            pass
    except Exception:
        pass

    parts = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")
    parts.append("<|im_start|>assistant\n")
    return "\n".join(parts)


def decode_first_json(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def extract_json_object(text: str) -> dict[str, Any] | None:
    return parse_generation_output(text).parsed


def has_thinking_text(text: str) -> bool:
    return model_has_thinking_text(text)


def infer_answer_type(record: dict[str, Any]) -> str:
    for message in record.get("messages") or []:
        if message.get("role") != "user":
            continue
        match = re.search(r"(?:Answer type:|## Answer Type\s*)\s*([A-Za-z_-]+)", message.get("content", ""), re.IGNORECASE)
        if match:
            return match.group(1)
    return "extractive"


def evaluate_prediction(prediction: dict[str, Any] | None, gold: dict[str, Any], answer_type: str) -> dict[str, Any]:
    if prediction is None:
        return {
            "json_ok": False,
            "schema_ok": False,
            "answer_em": False,
            "answer_f1": 0.0,
            "location_ok": False,
            "reward": 0.0,
        }
    format_check = check_answer_format(prediction)
    gold_answer = str(gold.get("answer", ""))
    pred_answer = str(prediction.get("answer", ""))
    gold_location = gold.get("evidence_location") or {}
    pred_location = prediction.get("evidence_location") or {}
    ans_score = answer_reward(pred_answer, gold_answer, answer_type)
    loc_score = location_reward(pred_location, gold_location)
    return {
        "json_ok": True,
        "schema_ok": bool(format_check["success"]),
        "answer_em": exact_match(pred_answer, gold_answer),
        "answer_f1": token_f1(pred_answer, gold_answer),
        "answer_score": ans_score,
        "location_ok": loc_score == 1.0,
        "reward": docqa_reward(prediction, gold_answer, gold_location, answer_type),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "num_samples": 0,
            "json_pass_rate": 0.0,
            "schema_pass_rate": 0.0,
            "thinking_rate": 0.0,
            "answer_em": 0.0,
            "answer_f1": 0.0,
            "answer_score": 0.0,
            "location_accuracy": 0.0,
            "mean_reward": 0.0,
        }
    n = len(rows)
    return {
        "num_samples": n,
        "json_pass_rate": sum(row["metrics"]["json_ok"] for row in rows) / n,
        "schema_pass_rate": sum(row["metrics"]["schema_ok"] for row in rows) / n,
        "thinking_rate": sum(row["metrics"]["has_thinking"] for row in rows) / n,
        "answer_em": sum(row["metrics"]["answer_em"] for row in rows) / n,
        "answer_f1": sum(row["metrics"]["answer_f1"] for row in rows) / n,
        "answer_score": sum(row["metrics"].get("answer_score", 0.0) for row in rows) / n,
        "location_accuracy": sum(row["metrics"]["location_ok"] for row in rows) / n,
        "mean_reward": sum(row["metrics"]["reward"] for row in rows) / n,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="/root/autodl-tmp/models/Qwen3-1.7B")
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--input", default="data/benchmark/tatqa_sft_smoke.jsonl")
    parser.add_argument("--output", default="outputs/eval/sft_checkpoint_eval.jsonl")
    parser.add_argument("--summary-output", default="outputs/eval/sft_checkpoint_eval_summary.json")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--enable-thinking", action="store_true")
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--num-shards", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--strict-extraction", action="store_true")
    args = parser.parse_args()

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    model_path = Path(args.model)
    adapter_path = Path(args.adapter)
    input_path = ROOT / args.input
    if not (model_path / "config.json").is_file():
        raise FileNotFoundError(f"local model is missing config.json: {model_path}")
    if not (adapter_path / "adapter_model.safetensors").is_file():
        raise FileNotFoundError(f"adapter checkpoint is missing adapter_model.safetensors: {adapter_path}")
    if args.num_shards < 1:
        raise ValueError("--num-shards must be >= 1")
    if not 0 <= args.shard_index < args.num_shards:
        raise ValueError("--shard-index must satisfy 0 <= shard-index < num-shards")
    records = read_jsonl(input_path)[: args.limit]
    records = [record for index, record in enumerate(records) if index % args.num_shards == args.shard_index]

    tokenizer = AutoTokenizer.from_pretrained(
        str(model_path),
        local_files_only=True,
        trust_remote_code=True,
    )
    tokenizer.padding_side = "left"
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
    base_model = AutoModelForCausalLM.from_pretrained(
        str(model_path),
        torch_dtype=dtype,
        local_files_only=True,
        trust_remote_code=True,
    )
    model = PeftModel.from_pretrained(base_model, str(adapter_path))
    if args.device == "cuda" and torch.cuda.is_available():
        model = model.to("cuda")
    model.eval()

    rows: list[dict[str, Any]] = []
    with torch.inference_mode():
        for batch_records in batched(records, args.batch_size):
            golds = [parse_target(record) for record in batch_records]
            answer_types = [infer_answer_type(record) for record in batch_records]
            prompts = [
                build_prompt(
                    tokenizer,
                    record,
                    disable_thinking=not args.enable_thinking,
                    strict_extraction=args.strict_extraction,
                )
                for record in batch_records
            ]
            inputs = tokenizer(prompts, return_tensors="pt", padding=True)
            inputs = {key: value.to(model.device) for key, value in inputs.items()}
            do_sample = args.temperature > 0
            generate_kwargs = {
                "max_new_tokens": args.max_new_tokens,
                "do_sample": do_sample,
                "pad_token_id": tokenizer.eos_token_id,
            }
            if do_sample:
                generate_kwargs["temperature"] = args.temperature
            output_ids = model.generate(**inputs, **generate_kwargs)
            prompt_width = inputs["input_ids"].shape[-1]
            for row_index, record in enumerate(batch_records):
                generated_ids = output_ids[row_index, prompt_width:]
                generated = tokenizer.decode(generated_ids, skip_special_tokens=True)
                prediction = extract_json_object(generated)
                metrics = evaluate_prediction(prediction, golds[row_index], answer_types[row_index])
                metrics["has_thinking"] = has_thinking_text(generated)
                rows.append(
                    {
                        "id": record.get("id"),
                        "answer_type": answer_types[row_index],
                        "gold": golds[row_index],
                        "generated": generated,
                        "prediction": prediction,
                        "metrics": metrics,
                    }
                )

    output = ROOT / args.output
    summary_output = ROOT / args.summary_output
    write_jsonl(output, rows)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "model": str(model_path),
        "adapter": str(adapter_path),
        "input": args.input,
        "output": args.output,
        **summarize(rows),
    }
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
