from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def workflow(name):
    return yaml.load((WORKFLOWS / name).read_text(), Loader=yaml.BaseLoader)


def test_smoke_is_dispatch_only():
    assert set(workflow("smoke.yml")["on"]) == {"workflow_dispatch"}


def test_workflows_have_explicit_permissions():
    for path in WORKFLOWS.glob("*.yml"):
        assert "permissions" in workflow(path.name), path.name
    for name in ("ci.yml", "smoke.yml"):
        assert workflow(name)["permissions"] == {"contents": "read"}
    assert workflow("ci.yml")["jobs"]["secrets"]["permissions"]["pull-requests"] == "read"


def test_deploy_health_requires_successful_push_for_workflow_runs():
    condition = workflow("deploy-health.yml")["jobs"]["health"]["if"]
    assert "github.event.workflow_run.event == 'push'" in condition
    assert "github.event.workflow_run.conclusion == 'success'" in condition


def test_deploy_probe_uses_only_public_health_fields():
    probe = workflow("deploy-health.yml")["jobs"]["health"]["steps"][0]["run"]
    assert ".version == $version" in probe
    assert ".ok == true" in probe
    assert ".providers" not in probe and ".mode" not in probe
