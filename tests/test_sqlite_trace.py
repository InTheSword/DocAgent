from docagent.storage.db import connect
from docagent.storage.repositories import TraceRepository


def test_trace_repository_persists_run_and_ordered_traces(tmp_path) -> None:
    conn = connect(tmp_path / "trace.sqlite")
    repo = TraceRepository(conn)

    run_id = repo.create_run(qid="q1", doc_id="doc1", question="What?", policy_mode="fake")
    repo.append_trace(run_id=run_id, step_index=0, node_name="retrieve", output_summary={"hits": 1})
    repo.append_trace(run_id=run_id, step_index=1, node_name="generate", success=False, error="boom")
    repo.complete_run(run_id=run_id, final_answer={"answer": "A"})

    run = repo.get_run(run_id)
    traces = repo.list_traces(run_id)

    assert run["status"] == "completed"
    assert run["final_answer"] == {"answer": "A"}
    assert [item["node_name"] for item in traces] == ["retrieve", "generate"]
    assert traces[1]["success"] is False
    assert traces[1]["error"] == "boom"
