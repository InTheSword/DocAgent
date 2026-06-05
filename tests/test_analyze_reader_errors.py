from scripts.analyze_reader_errors import question_buckets, summarize


def test_question_buckets_detect_table_numeric_and_person() -> None:
    assert "table_or_list" in question_buckets("As per the table what is the first item?", "annual reports")
    assert "numeric" in question_buckets("How much amount was expended for Taxes?", "867.33")
    assert "person" in question_buckets("Who is Longmont National Bank's president?", "john meyer")


def test_summarize_buckets_answer_bad_location_ok() -> None:
    eval_records = [
        {
            "id": "q1",
            "gold": {"answer": "john meyer", "evidence_location": {"block_id": "b1"}},
            "prediction": {
                "answer": "Robert Whyte",
                "evidence_location": {"block_id": "b1"},
                "evidence": "john meyer president to Longmont National Bank. robert whyte president.",
            },
            "metrics": {"schema_ok": True, "answer_em": False, "answer_f1": 0.0, "location_ok": True},
        }
    ]
    dataset_records = {
        "q1": {
            "id": "q1",
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "## Question\n"
                        "Who is Longmont National Bank's president?\n\n"
                        "## Answer Type\n"
                        "extractive\n\n"
                        "## Evidence Candidates\n"
                        "john meyer president to Longmont National Bank. robert whyte president."
                    ),
                }
            ],
        }
    }

    report = summarize(eval_records, dataset_records, max_examples=2)

    assert report["outcome_counts"]["answer_bad_location_ok"] == 1
    assert report["outcome_counts"]["gold_in_prompt"] == 1
    assert report["answer_bad_location_ok_f1"]["f1=0"] == 1
    assert report["answer_bad_location_ok_question_types"]["person"] == 1
    assert report["examples"]["person"][0]["id"] == "q1"
