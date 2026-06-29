from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
import json
from pathlib import Path

from docagent.parser.mineru_converter import content_list_to_blocks, find_content_list
from docagent.schemas import EvidenceBlock


@dataclass
class MinerUParserBackend:
    mode: str = "parse_existing"
    command: str = "mineru"
    timeout_seconds: int = 600
    backend_name: str = "mineru"

    def parse(self, *, file_path: Path, doc_id: str, output_dir: Path) -> list[EvidenceBlock]:
        output_dir.mkdir(parents=True, exist_ok=True)
        if self.mode == "local_cli":
            self._run_local_cli(file_path=file_path, output_dir=output_dir)
        elif self.mode != "parse_existing":
            raise ValueError(f"unsupported MinerU parser mode: {self.mode}")
        content_list = find_content_list(output_dir)
        return content_list_to_blocks(doc_id=doc_id, content_list_path=content_list, document_dir=output_dir.parent)

    def _run_local_cli(self, *, file_path: Path, output_dir: Path) -> None:
        command = [self.command, "-p", str(file_path), "-o", str(output_dir)]
        if shutil.which(self.command) is None:
            self._write_cli_result(
                output_dir,
                {
                    "command": self.command,
                    "argv": command,
                    "returncode": None,
                    "stdout": "",
                    "stderr": f"{self.command} is not installed or not on PATH",
                    "timeout_seconds": self.timeout_seconds,
                    "timed_out": False,
                    "command_found": False,
                },
            )
            raise RuntimeError(f"{self.command} is not installed or not on PATH")
        try:
            completed = subprocess.run(
                command,
                check=False,
                timeout=self.timeout_seconds,
                capture_output=True,
                text=True,
            )
        except subprocess.TimeoutExpired as exc:
            self._write_cli_result(
                output_dir,
                {
                    "command": self.command,
                    "argv": command,
                    "returncode": None,
                    "stdout": exc.stdout,
                    "stderr": exc.stderr,
                    "timeout_seconds": self.timeout_seconds,
                    "timed_out": True,
                    "command_found": True,
                },
            )
            raise
        self._write_cli_result(
            output_dir,
            {
                "command": self.command,
                "argv": command,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "timeout_seconds": self.timeout_seconds,
                "timed_out": False,
                "command_found": True,
            },
        )
        if completed.returncode != 0:
            raise RuntimeError(f"MinerU CLI failed with return code {completed.returncode}")

    @staticmethod
    def _write_cli_result(output_dir: Path, payload: dict[str, object]) -> None:
        (output_dir / "mineru_cli_result.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
