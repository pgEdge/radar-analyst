"""The guided walkthrough starts the analyst and opens the console.

The tour is a bash script, so it is exercised the way a user runs it:
as a subprocess, on a PATH holding a stub ``docker`` that records
every call and answers the few subcommands the tour uses, and a stub
browser that records the URL it is handed. Nothing here needs Docker.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[3]
_GUIDE = _REPO_ROOT / "examples" / "walkthrough" / "guide.sh"
_COMPOSE = _REPO_ROOT / "docker-compose.yml"

pytestmark = pytest.mark.skipif(
    not _GUIDE.is_file(),
    reason="the walkthrough is only present in a source checkout",
)

# The tools the script reaches for besides docker. They are linked
# into the sandbox PATH so the real docker, wherever it is installed,
# cannot be found from inside a test.
_TOOLS = ("bash", "env", "uname", "dirname", "tail", "grep", "rm")

_DOCKER_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$STUB_LOG"
case "$*" in
  info) ;;
  "compose version"*) echo "Docker Compose version v2.40.0" ;;
  *"ps -q --status running app")
    if [ -n "${STUB_RUNNING:-}" ]; then echo c0ffee; fi ;;
  *"up -d --wait")
    if [ -n "${STUB_UP_ERROR:-}" ]; then echo "$STUB_UP_ERROR"; exit 1; fi ;;
  *"port app 8080") echo "127.0.0.1:${STUB_PORT:-8080}" ;;
  *make_sample_zip*) ;;
  *" cp app:/tmp/radar-sample.zip "*) : > "${@: -1}" ;;
  *"down -v") ;;
  *) echo "unexpected docker call: $*" >&2; exit 97 ;;
esac
"""

_BROWSER_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$STUB_BROWSER_LOG"
"""


def _executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@dataclass
class Sandbox:
    """A PATH with stubs on it, the logs they write, and a cwd."""

    root: Path
    docker: bool = True
    extra_env: dict[str, str] = field(default_factory=dict)

    @property
    def bin(self) -> Path:
        """Directory placed first on PATH."""
        return self.root / "bin"

    @property
    def docker_log(self) -> Path:
        """Every docker invocation, one line of arguments each."""
        return self.root / "docker.log"

    @property
    def browser_log(self) -> Path:
        """Every URL the browser stub was handed."""
        return self.root / "browser.log"

    @property
    def cwd(self) -> Path:
        """Where the tour runs, and where it writes the sample."""
        return self.root / "work"

    def run(self, **env: str) -> subprocess.CompletedProcess[str]:
        """Run the tour non-interactively and return the result."""
        self.bin.mkdir(exist_ok=True)
        self.cwd.mkdir(exist_ok=True)
        for tool in _TOOLS:
            real = shutil.which(tool)
            assert real, f"{tool} is needed to run the tour"
            link = self.bin / tool
            if not link.exists():
                link.symlink_to(real)
        if self.docker:
            _executable(self.bin / "docker", _DOCKER_STUB)
        _executable(self.bin / "browser", _BROWSER_STUB)
        full_env = {
            "PATH": str(self.bin),
            "HOME": str(self.root),
            "LC_ALL": "C.UTF-8",
            "STUB_LOG": str(self.docker_log),
            "STUB_BROWSER_LOG": str(self.browser_log),
            "BROWSER": str(self.bin / "browser"),
            "WALKTHROUGH_NONINTERACTIVE": "1",
        }
        full_env.update(self.extra_env)
        full_env.update(env)
        args = full_env.pop("WALKTHROUGH_ARGS", "").split()
        return subprocess.run(
            ["bash", str(_GUIDE), *args],
            cwd=self.cwd,
            env=full_env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def docker_calls(self) -> list[str]:
        """The recorded docker invocations, in order."""
        if not self.docker_log.is_file():
            return []
        return self.docker_log.read_text().splitlines()

    def opened(self, expected: bool = True) -> list[str]:
        """The URLs handed to the browser, in order.

        The tour hands the URL off in the background so a blocking
        launcher cannot stall it, so when a URL is expected the stub
        is given a moment to write its log.
        """
        deadline = time.monotonic() + (2.0 if expected else 0.0)
        while not self.browser_log.is_file():
            if time.monotonic() >= deadline:
                return []
            time.sleep(0.05)
        return self.browser_log.read_text().splitlines()


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    """A sandbox with a working stub docker."""
    return Sandbox(tmp_path)


def test_starts_the_analyst_with_the_deployment_compose_file(
    sandbox: Sandbox,
) -> None:
    """The tour runs the documented command against the root compose file."""
    proc = sandbox.run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (
        f"compose -f {_COMPOSE} up -d --wait" in sandbox.docker_calls()
    )
    assert "docker compose up -d" in proc.stdout


def test_opens_the_console_in_the_browser(sandbox: Sandbox) -> None:
    """The console URL is handed to the browser once the analyst is up."""
    proc = sandbox.run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert sandbox.opened() == ["http://localhost:8080/"]


def test_the_console_port_comes_from_compose(sandbox: Sandbox) -> None:
    """A remapped port is read back from compose, never assumed."""
    proc = sandbox.run(STUB_PORT="9090")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert sandbox.opened() == ["http://localhost:9090/"]
    assert "http://localhost:9090/" in proc.stdout


def test_a_running_analyst_is_reused_and_left_alone(
    sandbox: Sandbox,
) -> None:
    """Nothing is started or stopped when the analyst is already up."""
    proc = sandbox.run(STUB_RUNNING="1")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    calls = sandbox.docker_calls()
    assert not any("up -d" in c for c in calls), calls
    assert not any(" down" in c for c in calls), calls
    assert sandbox.opened() == ["http://localhost:8080/"]


def test_never_stops_the_analyst(sandbox: Sandbox) -> None:
    """The tour leaves the analyst running for the user to work with."""
    proc = sandbox.run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not any(" down" in c for c in sandbox.docker_calls())
    assert "docker compose down" in proc.stdout


def test_explains_how_to_take_a_radar_collection(
    sandbox: Sandbox,
) -> None:
    """The radar command and the archive it writes are both named."""
    proc = sandbox.run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "github.com/pgEdge/radar/releases" in proc.stdout
    assert "radar -d" in proc.stdout
    assert "radar-" in proc.stdout and ".zip" in proc.stdout


def test_writes_a_sample_archive_into_the_current_directory(
    sandbox: Sandbox,
) -> None:
    """Without a collection to hand, the tour writes a sample to try."""
    proc = sandbox.run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (sandbox.cwd / "radar-sample.zip").is_file()
    assert "radar-sample.zip" in proc.stdout
    calls = sandbox.docker_calls()
    assert any("make_sample_zip" in c for c in calls), calls


def test_prints_the_url_when_asked_not_to_open_a_browser(
    sandbox: Sandbox,
) -> None:
    """WALKTHROUGH_NO_BROWSER=1 prints the address instead."""
    proc = sandbox.run(WALKTHROUGH_NO_BROWSER="1")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert sandbox.opened(expected=False) == []
    assert "http://localhost:8080/" in proc.stdout


def test_a_refused_pull_points_at_the_registry_login(
    sandbox: Sandbox,
) -> None:
    """The registry is private; a denied pull gets the login command."""
    proc = sandbox.run(STUB_UP_ERROR="Error: denied: requested access")
    assert proc.returncode != 0
    assert "docker login ghcr.io" in proc.stdout + proc.stderr
    assert sandbox.opened(expected=False) == []


def test_stops_early_without_docker(tmp_path: Path) -> None:
    """Missing prerequisites are reported, and nothing else happens."""
    sandbox = Sandbox(tmp_path, docker=False)
    proc = sandbox.run()
    assert proc.returncode != 0
    assert "docker" in (proc.stdout + proc.stderr).lower()
    assert sandbox.opened(expected=False) == []


def test_the_script_is_executable_and_bash() -> None:
    """The documented invocation is `bash guide.sh`, and so is the shebang."""
    assert os.access(_GUIDE, os.X_OK)
    first = _GUIDE.read_text().splitlines()[0]
    assert first == "#!/usr/bin/env bash", first


def test_down_removes_the_containers_and_the_volumes(
    sandbox: Sandbox,
) -> None:
    """`--down` is the takedown: containers, volumes, and the sample."""
    (sandbox.cwd).mkdir(exist_ok=True)
    (sandbox.cwd / "radar-sample.zip").write_bytes(b"PK")
    proc = sandbox.run(WALKTHROUGH_ARGS="--down")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    calls = sandbox.docker_calls()
    assert f"compose -f {_COMPOSE} down -v" in calls, calls
    assert not any("up -d" in c for c in calls), calls
    assert not (sandbox.cwd / "radar-sample.zip").exists()
    assert sandbox.opened(expected=False) == []


def test_down_says_what_it_deleted(sandbox: Sandbox) -> None:
    """The user is told that every assessment and archive is gone."""
    proc = sandbox.run(WALKTHROUGH_ARGS="--down")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "assessment" in proc.stdout and "archive" in proc.stdout


def test_the_tour_names_the_takedown(sandbox: Sandbox) -> None:
    """The closing text tells the user how to take it all down."""
    proc = sandbox.run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "guide.sh --down" in proc.stdout


def test_an_unknown_argument_is_refused(sandbox: Sandbox) -> None:
    """A typo is an error, not a silent full run."""
    proc = sandbox.run(WALKTHROUGH_ARGS="--dwon")
    assert proc.returncode != 0
    assert "--down" in proc.stdout + proc.stderr
    assert sandbox.docker_calls() == []
