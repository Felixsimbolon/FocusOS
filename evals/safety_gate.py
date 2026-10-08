"""Focused Phase 9 safety gate; standard library only."""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
files = ["test_agent_tools.py", "test_agent_continuation.py", "test_agent_planner.py",
         "test_planning_compiler.py", "test_unified_commands.py", "test_planning_workflow.py", "test_approval_payload.py", "test_approval_preflight.py", "test_approval_execute.py",
         "test_calendar_write.py", "test_approval_audit.py", "test_jobs.py", "test_jobs_workflow.py", "test_product.py", "test_product_tools.py"]
for name in files:
    result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(root / "backend/tests"),
                             "-p", name, "-q"], cwd=root)
    if result.returncode:
        raise SystemExit(result.returncode)
print("Phase 9 safety gate passed")
