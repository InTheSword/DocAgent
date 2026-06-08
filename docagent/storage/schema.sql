CREATE TABLE IF NOT EXISTS documents (
  doc_id TEXT PRIMARY KEY,
  source TEXT,
  file_path TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS evidence_blocks (
  block_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  page_id INTEGER,
  block_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS qa_logs (
  qid TEXT PRIMARY KEY,
  question TEXT NOT NULL,
  answer_json TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS qa_runs (
  run_id TEXT PRIMARY KEY,
  qid TEXT,
  doc_id TEXT,
  question TEXT NOT NULL,
  policy_mode TEXT NOT NULL,
  status TEXT NOT NULL,
  final_answer_json TEXT,
  error TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  completed_at TEXT
);

CREATE TABLE IF NOT EXISTS tool_traces (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  qid TEXT,
  step TEXT,
  payload_json TEXT,
  run_id TEXT,
  step_index INTEGER,
  node_name TEXT,
  input_summary_json TEXT,
  output_summary_json TEXT,
  success INTEGER,
  latency_ms REAL,
  error TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(run_id) REFERENCES qa_runs(run_id)
);

CREATE TABLE IF NOT EXISTS eval_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_name TEXT NOT NULL,
  metric TEXT NOT NULL,
  value REAL NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
