from scripts.build_answer_hard_grpo_subset import answer_issue_type, build_subset


def _eval_record(row_id: str, answer_em: bool, location_ok: bool, answer_f1: float, pred_answer: str) -> dict:
    return {
        "id": row_id,
        "gold": {"answer": "600 MG", "evidence_location": {"block_id": "b1"}},
        "prediction": {"answer": pred_answer, "evidence_location": {"block_id": "b1"}},
        "metrics": {
            "schema_ok": True,
            "answer_em": answer_em,
            "answer_f1": answer_f1,
            "location_ok": location_ok,
        },
    }


def _grpo_record(row_id: str) -> dict:
    return {
        "id": row_id,
        "messages": [
            {"role": "system", "content": "Use evidence."},
            {
                "role": "user",
                "content": (
                    "## Question\n"
                    "How much calcium is listed?\n\n"
                    "## Answer Type\n"
                    "extractive\n\n"
                    "## Evidence Candidates\n"
                    "generic lilly 600 mg 4 tablets"
                ),
            },
        ],
        "gold_answer": "600 MG",
        "gold_location": {"block_id": "b1"},
        "answer_type": "extractive",
    }


def test_answer_issue_type_detects_common_extraction_errors() -> None:
    assert answer_issue_type("600 MG", "4 tablets", 0.0) == "numeric_mismatch"
    assert answer_issue_type("Patent Rights", "Patent Rights Agreement", 0.8) == "over_extracted"
    assert answer_issue_type("Fourteen posters", "Fourteen", 0.66) == "under_extracted"
    assert answer_issue_type("Prague", "Praga", 0.8) == "near_miss"
    assert answer_issue_type("Prague", "London", 0.0) == "no_overlap"


def test_build_subset_keeps_answer_hard_location_ok_records() -> None:
    selected, report = build_subset(
        eval_records=[
            _eval_record("q1", answer_em=False, location_ok=True, answer_f1=0.0, pred_answer="4 tablets"),
            _eval_record("q2", answer_em=True, location_ok=True, answer_f1=1.0, pred_answer="600 MG"),
            _eval_record("q3", answer_em=False, location_ok=False, answer_f1=0.0, pred_answer="4 tablets"),
            _eval_record("missing", answer_em=False, location_ok=True, answer_f1=0.0, pred_answer="4 tablets"),
        ],
        grpo_records=[_grpo_record("q1"), _grpo_record("q2"), _grpo_record("q3")],
        sft_records=None,
        limit=10,
        max_answer_f1=0.999,
        max_per_question_type=0,
    )

    assert [record["id"] for record in selected] == ["q1"]
    assert selected[0]["metadata"]["hard_case"]["issue_type"] == "numeric_mismatch"
    assert selected[0]["metadata"]["hard_case"]["f1_bucket"] == "f1=0"
    assert report["num_answer_hard_candidates"] == 1
    assert report["num_selected"] == 1
    assert report["skipped_missing_grpo"] == 1


def test_build_subset_falls_back_to_sft_records() -> None:
    sft_record = _grpo_record("q1")
    sft_record["messages"] = [
        *sft_record["messages"],
        {
            "role": "assistant",
            "content": (
                '{"answer": "600 MG", "evidence_location": {"block_id": "b1"}, '
                '"evidence": "generic lilly 600 mg 4 tablets", "reason": "supported"}'
            ),
        },
    ]

    selected, report = build_subset(
        eval_records=[_eval_record("q1", answer_em=False, location_ok=True, answer_f1=0.0, pred_answer="4 tablets")],
        grpo_records=[],
        sft_records=[sft_record],
        limit=10,
        max_answer_f1=0.999,
        max_per_question_type=0,
    )

    assert [record["id"] for record in selected] == ["q1"]
    assert [message["role"] for message in selected[0]["messages"]] == ["system", "user"]
    assert selected[0]["gold_answer"] == "600 MG"
    assert report["candidate_source_counts"] == {"sft_converted": 1}
    assert report["skipped_missing_grpo"] == 0
