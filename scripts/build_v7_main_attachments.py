"""Bind the published pilot evidence to its ten V7 task-review pages."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from build_v7_pilot_site import DRIVE, ORDER, REPO


SITE = REPO / "docs/gatsby-v7"
PILOT = SITE / "pilot-2026-09-28"
TASKS = SITE / "tasks"


def json_file(path: Path):
    return json.loads(path.read_text())


def preview_url(code: str, references: list[str]) -> str | None:
    for reference in references:
        name = Path(reference).name
        if name and (PILOT / "runs" / code / "previews" / name).is_file():
            return f"pilot-2026-09-28/runs/{code}/previews/{name}"
    return None


def trajectory_steps(code: str, trajectory: dict) -> list[dict]:
    steps = []
    for event in trajectory.get("events", []):
        rationale = event.get("rationale_summary") or {}
        tool = event.get("tool_call") or {}
        output = event.get("output_state") or {}
        verification = event.get("verification") or {}
        snapshots = output.get("preview_refs") or []
        tool_name = tool.get("tool_name")
        surface = tool.get("connector_surface")
        steps.append({
            "stage": event.get("sequence"),
            "title": event.get("phase") or event.get("intent") or event.get("event_kind"),
            "action": event.get("intent"),
            "decision": rationale.get("decision"),
            "reasoning": rationale.get("why"),
            "tool": " / ".join(str(part) for part in (surface, tool_name) if part),
            "parameters": tool.get("sanitized_parameters") or None,
            "evidence": rationale.get("evidence_considered") or [],
            "tradeoffs": rationale.get("tradeoffs") or [],
            "verification": verification.get("result") if verification.get("performed") else None,
            "status": event.get("status"),
            "timestamp": event.get("timestamp"),
            "snapshot_url": preview_url(code, snapshots),
            "snapshot_note": output.get("preview_unavailable_reason") if not snapshots else None,
        })
    return steps


def attachment(code: str) -> dict:
    run_dir = PILOT / "runs" / code
    manifest = json_file(run_dir / "DELIVERY_MANIFEST.json")
    verifier_results = json_file(run_dir / "verifier-results.json")
    trajectory = json_file(run_dir / "trajectory.json")
    contract = json_file(TASKS / code / "OUTPUT_REGISTER.json")
    canonical = json_file(TASKS / code / "VERIFIERS.json")
    contract_outputs = {item["output_id"]: item for item in contract}
    auto_ids = {item["check_id"] for item in canonical if item["type"] == "auto"}
    assert len(auto_ids) == len([item for item in canonical if item["type"] == "auto"])
    assert len(manifest["deliverables"]) == len(contract_outputs), code

    outputs = []
    for item in manifest["deliverables"]:
        output_id = item["deliverable_id"]
        assert output_id in contract_outputs, (code, output_id)
        assert len(item["files"]) == 1, (code, output_id)
        record = item["files"][0]
        filename = record["filename"]
        assert filename == Path(contract_outputs[output_id]["path"]).name, (code, output_id)
        file_path = run_dir / "deliverables" / filename
        assert file_path.is_file(), file_path
        digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
        assert digest == record["sha256"], (code, filename)
        dimensions = record.get("dimensions") or {}
        output = {
            "output_id": output_id,
            "artifact_url": f"pilot-2026-09-28/runs/{code}/deliverables/{filename}",
            "preview_url": f"pilot-2026-09-28/runs/{code}/thumbnails/{filename}.jpg",
            "bytes": record["bytes"],
            "sha256": digest,
            "actual_pixels": [dimensions["width"], dimensions["height"]] if "width" in dimensions and "height" in dimensions else None,
            "actual_pages": dimensions.get("pages") or record.get("pages"),
            "note": item.get("notes") or "",
        }
        assert (run_dir / "thumbnails" / f"{filename}.jpg").is_file(), (code, filename)
        outputs.append(output)

    raw_results = verifier_results.get("results") or verifier_results.get("auto_verifiers") or []
    auto_results = {}
    for result in raw_results:
        check_id = result["verifier_id"]
        if check_id not in auto_ids:
            continue
        assert check_id not in auto_results, (code, check_id)
        status = result["status"]
        assert status in {"pass", "fail", "not_run", "not_assessed"}, (code, check_id, status)
        auto_results[check_id] = {
            "check_id": check_id,
            "status": {"pass": "passed", "fail": "failed"}.get(status, status),
            "answer": result.get("answer") if status in {"pass", "fail"} else None,
        }
    assert set(auto_results) == auto_ids, (code, "missing auto check results", len(auto_ids - set(auto_results)))
    auto_passed = sum(result["status"] == "passed" for result in auto_results.values())
    auto_failed = sum(result["status"] == "failed" for result in auto_results.values())
    auto_unassessed = len(auto_results) - auto_passed - auto_failed

    completed_at = trajectory.get("run", {}).get("completed_at") or manifest["generated_at"]
    return {
        "task_id": code,
        "completed_at": completed_at[:10],
        "execution_status": manifest["status"],
        "execution_mode": manifest["execution_mode"].replace("_", " "),
        "outputs": outputs,
        "auto_checks": list(auto_results.values()),
        "verifier_summary": {
            "automatic_total": len(auto_ids),
            "automatic_passed": auto_passed,
            "automatic_failed": auto_failed,
            "automatic_unassessed": auto_unassessed,
        },
        "trajectory_steps": trajectory_steps(code, trajectory),
        "exceptions": manifest.get("declared_exceptions") or [],
        "links": {
            "pilot_view": f"pilot-2026-09-28/#{code}",
            "google_drive_folder": DRIVE[code],
            "manifest": f"pilot-2026-09-28/runs/{code}/DELIVERY_MANIFEST.json",
            "verifier_results": f"pilot-2026-09-28/runs/{code}/verifier-results.json",
            "trajectory_report": f"pilot-2026-09-28/runs/{code}/trajectory.html",
            "trajectory_json": f"pilot-2026-09-28/runs/{code}/trajectory.json",
            "trajectory_jsonl": f"pilot-2026-09-28/runs/{code}/trajectory.jsonl",
        },
    }


def build() -> None:
    items = [attachment(code) for code in ORDER]
    payload = json.dumps(items, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    script = """/* Generated by scripts/build_v7_main_attachments.py. */
(() => {
  const attachments = __PAYLOAD__;
  for (const item of attachments) {
    const task = data.tasks.find(task => task.id === item.task_id);
    if (!task) throw new Error(`Missing V7 task ${item.task_id}`);
    for (const output of item.outputs) {
      const target = task.outputs.find(candidate => candidate.output_id === output.output_id);
      if (!target) throw new Error(`Missing V7 output ${item.task_id}/${output.output_id}`);
      Object.assign(target, output, {status: 'produced', verification: 'delivered; not creatively rated'});
    }
    for (const result of item.auto_checks) {
      const target = task.checks.find(candidate => candidate.check_id === result.check_id && candidate.type === 'auto');
      if (!target) throw new Error(`Missing V7 verifier ${result.check_id}`);
      if (task.input_revision) target.historical_result = {...target.historical_result, ...result};
      else Object.assign(target, result);
    }
    task.run = {
      completed_at: item.completed_at,
      execution_status: item.execution_status,
      execution_mode: item.execution_mode,
      outputs: item.outputs,
      verifier_summary: item.verifier_summary,
      trajectory_steps: item.trajectory_steps,
      exceptions: item.exceptions,
      links: item.links,
      trajectory_scores: []
    };
  }
  nav();
  render();
})();
""".replace("__PAYLOAD__", payload)
    destination = PILOT / "main-page-attachments.js"
    destination.write_text(script)
    print(json.dumps({
        "attachment_file": str(destination),
        "tasks": len(items),
        "outputs": sum(len(item["outputs"]) for item in items),
        "auto_passed": sum(item["verifier_summary"]["automatic_passed"] for item in items),
        "auto_unassessed": sum(item["verifier_summary"]["automatic_unassessed"] for item in items),
        "trajectory_events": sum(len(item["trajectory_steps"]) for item in items),
    }, indent=2))


if __name__ == "__main__":
    build()
