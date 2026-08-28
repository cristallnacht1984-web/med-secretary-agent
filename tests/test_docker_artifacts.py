"""Static validation for Docker artifacts (Task 11b)."""
from pathlib import Path

import yaml


def test_dockerfile_exists():
    assert Path("Dockerfile").exists(), "Dockerfile must exist"


def test_dockerfile_base_image():
    content = Path("Dockerfile").read_text()
    assert "FROM python:3.1" in content and "-slim" in content


def test_dockerfile_cmd():
    content = Path("Dockerfile").read_text()
    assert "main.py" in content and "CMD" in content


def test_dockerfile_non_root():
    content = Path("Dockerfile").read_text()
    assert "USER" in content and "root" not in content.split("USER")[-1]


def test_dockerfile_healthcheck():
    content = Path("Dockerfile").read_text()
    assert "HEALTHCHECK" in content and "/health" in content


def test_compose_parses():
    with open("docker-compose.yml") as f:
        data = yaml.safe_load(f)
    assert "services" in data


def test_compose_restart():
    with open("docker-compose.yml") as f:
        data = yaml.safe_load(f)
    service = data["services"].get("mednews-secretary") or list(data["services"].values())[0]
    assert service.get("restart") == "unless-stopped"


def test_compose_volumes():
    with open("docker-compose.yml") as f:
        data = yaml.safe_load(f)
    service = data["services"].get("mednews-secretary") or list(data["services"].values())[0]
    volumes = service.get("volumes", [])
    volumes_str = str(volumes)
    assert "data" in volumes_str
    assert "logs" in volumes_str or "log" in volumes_str


def test_compose_env_file():
    with open("docker-compose.yml") as f:
        data = yaml.safe_load(f)
    service = data["services"].get("mednews-secretary") or list(data["services"].values())[0]
    env_files = service.get("env_file", [])
    assert any(".env" in str(e) for e in env_files)


def test_dockerignore_contents():
    content = Path(".dockerignore").read_text()
    for pattern in ["__pycache__", ".git", "tests", ".env"]:
        assert pattern in content


def test_dockerignore_env_excluded():
    content = Path(".dockerignore").read_text()
    lines = [line.strip() for line in content.splitlines() if line.strip() and not line.startswith("#")]
    assert ".env" in lines


def test_healthcheck_port_match():
    content = Path("Dockerfile").read_text()
    assert "8080" in content or "HEALTH_CHECK_PORT" in content
