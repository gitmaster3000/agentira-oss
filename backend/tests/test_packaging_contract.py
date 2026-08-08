from pathlib import Path
import tomllib


def test_mcp_sdk_stays_on_v1_until_server_is_migrated():
    pyproject = Path(__file__).parents[2] / "pyproject.toml"
    dependencies = tomllib.loads(pyproject.read_text())["project"]["dependencies"]
    mcp_requirement = next(dep for dep in dependencies if dep.startswith("mcp[cli]"))

    assert "<2" in mcp_requirement
