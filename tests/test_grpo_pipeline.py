from scripts.build_grpo_from_sft_dataset import convert_record
from scripts.train_custom_grpo import build_prompt as build_custom_prompt
from scripts.train_trl_grpo import build_prompt as build_trl_prompt
from scripts.train_trl_grpo import set_grpo_config_arg_if_supported


class FakeTokenizer:
    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=False, enable_thinking=False):
        rendered = "\n".join(f"{message.get('role')}:{message.get('content')}" for message in messages)
        return rendered + ("\nassistant:" if add_generation_prompt else "")

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": text.split()}

    def decode(self, ids, skip_special_tokens=True):
        return " ".join(ids)


def _sft_record() -> dict:
    return {
        "id": "q1",
        "source": "mp_docvqa",
        "messages": [
            {"role": "system", "content": "Use only evidence."},
            {
                "role": "user",
                "content": "## Question\nWhat is the answer?\n\n## Answer Type\nextractive",
            },
            {
                "role": "assistant",
                "content": '{"answer": "GOLD_LEAK", "evidence_location": {"block_id": "b1"}}',
            },
        ],
    }


def _candidate_sft_record() -> dict:
    record = _sft_record()
    record["messages"][-1]["content"] = (
        '{"answer": "GOLD_LEAK", "reasoning_summary": "cited", '
        '"citation_block_ids": ["b1"], '
        '"evidence_used": [{"block_id": "b1", "text_preview": "GOLD_LEAK"}]}'
    )
    return record


def test_convert_sft_record_to_grpo_record_removes_assistant_target() -> None:
    converted = convert_record(_sft_record())

    assert converted["gold_answer"] == "GOLD_LEAK"
    assert converted["gold_location"] == {"block_id": "b1"}
    assert converted["answer_type"] == "extractive"
    assert [message["role"] for message in converted["messages"]] == ["system", "user"]


def test_convert_candidate_sft_record_to_grpo_record_uses_citation_location() -> None:
    converted = convert_record(_candidate_sft_record())

    assert converted["gold_answer"] == "GOLD_LEAK"
    assert converted["gold_location"] == {"block_id": "b1"}
    assert [message["role"] for message in converted["messages"]] == ["system", "user"]


def test_grpo_prompt_builders_drop_assistant_targets() -> None:
    tokenizer = FakeTokenizer()
    record = _sft_record()

    trl_prompt = build_trl_prompt(tokenizer, record, max_prompt_tokens=None)
    custom_prompt = build_custom_prompt(tokenizer, record)

    assert "GOLD_LEAK" not in trl_prompt
    assert "GOLD_LEAK" not in custom_prompt
    assert "Return only one valid JSON object" in trl_prompt
    assert "Return only one valid JSON object" in custom_prompt


def test_grpo_config_optional_arg_is_signature_gated() -> None:
    class SupportsMaxPrompt:
        def __init__(self, max_prompt_length=None):
            pass

    class NoMaxPrompt:
        def __init__(self, output_dir=None):
            pass

    kwargs = {}
    assert set_grpo_config_arg_if_supported(kwargs, SupportsMaxPrompt, "max_prompt_length", 4096)
    assert kwargs == {"max_prompt_length": 4096}

    kwargs = {}
    assert not set_grpo_config_arg_if_supported(kwargs, NoMaxPrompt, "max_prompt_length", 4096)
    assert kwargs == {}
