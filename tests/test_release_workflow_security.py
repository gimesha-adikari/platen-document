"""Fully mocked security gates for the manual SDK release workflow."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github/workflows/release.yml"
REPOSITORY = "gimesha-adikari/platen-document"
COMMIT = "ace8a33bb78595fbc704fd4ec0d319351fea61b9"
TAG_REF_OID = "b" * 40
CI_RUN_ID = 39275953887
CI_WORKFLOW_ID = 389181912
CI_JOB_NAME = "Test and Qualify Distributions"
CI_SELECT_STEP = "Select the version-required raster admission suite"
CI_WHEEL_STEP = "Qualify a clean installed wheel"
CI_CANDIDATE_STEP = "Run raster security tests against the accepted candidate wheel"
NOW = datetime(2026, 10, 19, 15, 20, tzinfo=UTC)


def _script(namespace: str) -> dict[str, object]:
    source = WORKFLOW_PATH.read_text()
    match = re.search(
        rf"(?m)^          python - <<'{namespace}'\n(.*?)^          {namespace}$",
        source,
        re.DOTALL,
    )
    assert match is not None, f"release.yml must contain the {namespace} gate script"
    code = textwrap.dedent(match.group(1))
    module: dict[str, object] = {"__name__": f"_test_{namespace.lower()}"}
    exec(compile(code, f"{WORKFLOW_PATH}:{namespace}", "exec"), module)
    return module


def _release_scripts() -> tuple[dict[str, object], dict[str, object]]:
    return _script("PY_RELEASE_PREFLIGHT"), _script("PY_PUBLICATION_GATE")


BUILD_GATE, PUBLISH_GATE = _release_scripts()


class FakeGitHub:
    """Small, deterministic GitHub REST fixture for both workflow gates."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.main_sha = COMMIT
        self.version = "0.1.9"
        self.workflows = [
            {
                "id": CI_WORKFLOW_ID,
                "name": "SDK CI",
                "path": ".github/workflows/ci.yml",
                "state": "active",
            }
        ]
        self.runs = [
            {
                "id": CI_RUN_ID,
                "workflow_id": CI_WORKFLOW_ID,
                "head_sha": COMMIT,
                "head_branch": "main",
                "status": "completed",
                "conclusion": "success",
                "updated_at": NOW.isoformat().replace("+00:00", "Z"),
            }
        ]
        self.jobs = [
            {
                "name": CI_JOB_NAME,
                "conclusion": "success",
                "steps": [
                    {"name": CI_SELECT_STEP, "conclusion": "success"},
                    {"name": CI_WHEEL_STEP, "conclusion": "success"},
                    {"name": CI_CANDIDATE_STEP, "conclusion": "skipped"},
                ],
            }
        ]
        self.tag_ref_oid = TAG_REF_OID
        self.tag_target = COMMIT
        self.tag_object_name = "v0.1.9"
        self.tag_object_type = "commit"
        self.artifact = {
            "id": 777,
            "name": "python-package-distributions-12345-1",
            "digest": "sha256:" + "a" * 64,
            "expired": False,
            "size_in_bytes": 1234,
            "workflow_run": {
                "id": 12345,
                "repository_id": 1352748673,
                "head_repository_id": 1352748673,
                "head_branch": "main",
                "head_sha": COMMIT,
            },
        }
        self.missing: set[str] = set()

    @staticmethod
    def _content(path: str, text: str) -> dict[str, str]:
        return {
            "type": "file",
            "path": path,
            "encoding": "base64",
            "content": base64.b64encode(text.encode()).decode(),
        }

    def __call__(self, path: str) -> dict[str, object]:
        self.calls.append(path)
        if path in self.missing:
            if "/git/ref/tags/" in path:
                return {"ref": path.rsplit("/", 1)[-1]}
            if "/contents/tests/test_raster_admission.py" in path:
                return {"type": "dir", "path": "tests/test_raster_admission.py"}
            return {}
        if path == f"/repos/{REPOSITORY}":
            return {"id": 1352748673, "full_name": REPOSITORY}
        if path == f"/repos/{REPOSITORY}/git/ref/heads/main":
            return {"ref": "refs/heads/main", "object": {"sha": self.main_sha, "type": "commit"}}
        if path == f"/repos/{REPOSITORY}/git/ref/tags/v0.1.9":
            return {
                "ref": "refs/tags/v0.1.9",
                "object": {"sha": self.tag_ref_oid, "type": "tag"},
            }
        if path == f"/repos/{REPOSITORY}/git/tags/{self.tag_ref_oid}":
            return {
                "tag": self.tag_object_name,
                "object": {"sha": self.tag_target, "type": self.tag_object_type},
            }
        if path == f"/repos/{REPOSITORY}/actions/workflows?per_page=100":
            return {"workflows": self.workflows}
        if path == (
            f"/repos/{REPOSITORY}/actions/workflows/{CI_WORKFLOW_ID}/runs"
            f"?head_sha={COMMIT}&branch=main&per_page=100"
        ):
            return {"workflow_runs": self.runs}
        if path == f"/repos/{REPOSITORY}/actions/runs/{CI_RUN_ID}/jobs?per_page=100":
            return {"jobs": self.jobs}
        if path == f"/repos/{REPOSITORY}/contents/pyproject.toml?ref={COMMIT}":
            return self._content("pyproject.toml", f"[project]\nversion = \"{self.version}\"\n")
        if path == f"/repos/{REPOSITORY}/contents/.github/workflows/ci.yml?ref={COMMIT}":
            return self._content(
                ".github/workflows/ci.yml",
                (ROOT / ".github/workflows/ci.yml").read_text(),
            )
        if path == f"/repos/{REPOSITORY}/contents/tests/test_raster_admission.py?ref={COMMIT}":
            return {"type": "file", "path": "tests/test_raster_admission.py"}
        if path == f"/repos/{REPOSITORY}/actions/artifacts/777":
            return self.artifact
        raise AssertionError(f"unexpected mocked GitHub API request: {path}")


def _env(**overrides: str) -> dict[str, str]:
    values = {
        "RELEASE_EVENT_NAME": "workflow_dispatch",
        "RELEASE_REF": "refs/heads/main",
        "RELEASE_EVENT_SHA": COMMIT,
        "RELEASE_ACTOR": "gimesha-adikari",
        "RELEASE_TRIGGERING_ACTOR": "gimesha-adikari",
        "GITHUB_REPOSITORY": REPOSITORY,
        "RELEASE_VERSION": "0.1.9",
        "REVIEWED_COMMIT": COMMIT,
        "GITHUB_RUN_ID": "12345",
        "GITHUB_RUN_ATTEMPT": "1",
    }
    values.update(overrides)
    return values


def _do_preflight(
    env: dict[str, str] | None = None,
    github: FakeGitHub | None = None,
    *,
    pypi_check=None,
):
    github = github or FakeGitHub()
    return BUILD_GATE["release_preflight"](
        env or _env(),
        "0.1.9",
        COMMIT,
        github,
        pypi_check=pypi_check or (lambda version, opener=None: None),
        now=NOW,
    )


def _write_artifact_bundle(tmp_path: Path, *, version: str = "0.1.9") -> dict[str, object]:
    bundle = tmp_path / "artifact"
    dist = bundle / "dist"
    dist.mkdir(parents=True)
    files = {
        f"platen_document-{version}-py3-none-any.whl": b"small mocked wheel payload",
        f"platen_document-{version}.tar.gz": b"small mocked sdist payload",
    }
    hashes = {}
    for name, payload in files.items():
        (dist / name).write_bytes(payload)
        hashes[name] = hashlib.sha256(payload).hexdigest()
    manifest = {
        "schema_version": 1,
        "repository": REPOSITORY,
        "workflow_run_id": 12345,
        "workflow_run_attempt": 1,
        "version": version,
        "reviewed_commit": COMMIT,
        "tag": f"v{version}",
        "tag_ref_oid": TAG_REF_OID,
        "artifact_name": "python-package-distributions-12345-1",
        "distributions": hashes,
    }
    (bundle / "release-manifest.json").write_text(json.dumps(manifest))
    return manifest


def _publication_env(bundle: Path, **overrides: str) -> dict[str, str]:
    values = _env()
    values.update(
        {
            "EXPECTED_ARTIFACT_ID": "777",
            "EXPECTED_ARTIFACT_DIGEST": "sha256:" + "a" * 64,
            "EXPECTED_TAG_REF_OID": TAG_REF_OID,
            "ARTIFACT_DOWNLOAD_DIR": str(bundle),
        }
    )
    values.update(overrides)
    return values


def _do_publication_preflight(
    bundle: Path,
    env: dict[str, str] | None = None,
    github: FakeGitHub | None = None,
    *,
    pypi_check=None,
):
    github = github or FakeGitHub()
    return PUBLISH_GATE["publication_preflight"](
        env or _publication_env(bundle),
        github,
        artifact_dir=bundle,
        pypi_check=pypi_check or (lambda version, opener=None: None),
    )


def test_workflow_has_only_manual_dispatch_and_required_inputs() -> None:
    text = WORKFLOW_PATH.read_text()
    lines = text.splitlines()
    on_index = lines.index("on:")
    event_names = []
    for line in lines[on_index + 1 :]:
        if line and not line.startswith(" "):
            break
        match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if match:
            event_names.append(match.group(1))
    assert event_names == ["workflow_dispatch"]
    assert re.search(r"(?m)^      version:\s*$", text)
    assert re.search(r"(?m)^      reviewed_commit:\s*$", text)
    assert text.count("required: true") >= 2
    assert not re.search(r"(?m)^\s+(?:push|release|schedule):\s*$", text)
    assert "GITHUB_REF_NAME" not in text


def test_actions_are_full_sha_pinned_and_oidc_is_publish_only() -> None:
    text = WORKFLOW_PATH.read_text()
    uses = re.findall(r"(?m)^\s+uses:\s*([^#\s]+)(?:\s+#.*)?$", text)
    assert uses
    for action in uses:
        assert re.fullmatch(r"[^@]+@[0-9a-f]{40}(?:\s+#.*)?", action), action

    build_block = text.split("  build:", 1)[1].split("  publish:", 1)[0]
    publish_block = text.split("  publish:", 1)[1]
    assert "id-token: write" not in build_block
    assert "actions: read" in build_block
    assert "id-token: write" in publish_block
    assert "actions: read" in publish_block
    assert "environment:" in publish_block and "name: pypi" in publish_block
    assert "needs: build" in publish_block


def test_all_embedded_python_blocks_are_syntactically_valid() -> None:
    text = WORKFLOW_PATH.read_text()
    for marker in ("PY_RELEASE_WHEEL", "PY_RELEASE_MANIFEST"):
        match = re.search(
            rf"(?m)^          (?:python -|cat > .*?) <<'{marker}'\n(.*?)^          {marker}$",
            text,
            re.DOTALL,
        )
        assert match is not None, f"release.yml is missing {marker}"
        compile(textwrap.dedent(match.group(1)), f"{WORKFLOW_PATH}:{marker}", "exec")


def test_shell_never_interpolates_user_inputs_and_publisher_is_last() -> None:
    text = WORKFLOW_PATH.read_text()
    script_source = "\n".join(
        re.findall(
            r"(?m)^          python - <<'[^']+'\n(.*?)^          [A-Z_]+$",
            text,
            re.DOTALL,
        )
    )
    assert "${{ inputs.version }}" not in script_source
    assert "${{ inputs.reviewed_commit }}" not in script_source
    publish_block = text.split("  publish:", 1)[1]
    assert publish_block.index("Download the exact release artifact") < publish_block.index(
        "Revalidate publication authorization and artifact"
    ) < publish_block.index("Publish with Trusted Publishing")
    assert publish_block.count("pypa/gh-action-pypi-publish@") == 1


def test_publish_condition_requires_authorized_dispatch_and_successful_build() -> None:
    text = WORKFLOW_PATH.read_text()
    publish_block = text.split("  publish:", 1)[1]
    for required in (
        "github.event_name == 'workflow_dispatch'",
        "github.ref == 'refs/heads/main'",
        "github.actor == 'gimesha-adikari'",
        "github.triggering_actor == 'gimesha-adikari'",
        "needs.build.result == 'success'",
    ):
        assert required in publish_block
    assert "if: always()" not in publish_block


@pytest.mark.parametrize(
    "overrides",
    [
        {"RELEASE_EVENT_NAME": "push"},
        {"RELEASE_EVENT_NAME": "release"},
        {"RELEASE_EVENT_NAME": "schedule"},
        {"RELEASE_REF": "refs/heads/feature/release"},
        {"RELEASE_REF": "refs/tags/v0.1.9"},
        {"RELEASE_ACTOR": "external-contributor"},
        {"RELEASE_TRIGGERING_ACTOR": "external-contributor"},
        {"RELEASE_VERSION": "0.1.8"},
        {"RELEASE_VERSION": "v0.1.9"},
        {"RELEASE_VERSION": "0.1.9;echo unsafe"},
        {"REVIEWED_COMMIT": "d" * 40},
        {"RELEASE_EVENT_SHA": "d" * 40},
        {"GITHUB_REPOSITORY": "someone-else/platen-document"},
    ],
)
def test_build_preflight_rejects_wrong_event_ref_actor_version_or_commit(overrides) -> None:
    with pytest.raises(BUILD_GATE["ReleaseGateError"]):
        _do_preflight(_env(**overrides))


def test_build_preflight_rejects_checked_out_or_current_main_mismatch() -> None:
    github = FakeGitHub()
    with pytest.raises(BUILD_GATE["ReleaseGateError"]):
        BUILD_GATE["release_preflight"](
            _env(),
            "0.1.9",
            "d" * 40,
            github,
            pypi_check=lambda version, opener=None: None,
            now=NOW,
        )

    github = FakeGitHub()
    github.main_sha = "d" * 40
    with pytest.raises(BUILD_GATE["ReleaseGateError"]):
        BUILD_GATE["release_preflight"](
            _env(),
            "0.1.9",
            COMMIT,
            github,
            pypi_check=lambda version, opener=None: None,
            now=NOW,
        )


def test_preflight_accepts_only_exact_sdk_ci_and_current_installed_wheel_suite() -> None:
    result = _do_preflight()
    assert result["version"] == "0.1.9"
    assert result["reviewed_commit"] == COMMIT
    assert result["tag"] == "v0.1.9"
    assert result["tag_ref_oid"] == TAG_REF_OID


@pytest.mark.parametrize(
    "change",
    [
        lambda gh: gh.workflows.clear(),
        lambda gh: gh.workflows.__setitem__(
            0, {"id": CI_WORKFLOW_ID, "name": "SDK CI", "path": ".github/workflows/other.yml", "state": "active"}
        ),
        lambda gh: gh.workflows.__setitem__(
            0, {"id": CI_WORKFLOW_ID, "name": "SDK CI Copy", "path": ".github/workflows/ci.yml", "state": "active"}
        ),
        lambda gh: gh.runs[0].update(head_sha="d" * 40),
        lambda gh: gh.runs[0].update(head_branch="feature/release"),
        lambda gh: gh.runs[0].update(status="in_progress"),
        lambda gh: gh.runs[0].update(conclusion="failure"),
        lambda gh: gh.runs[0].update(id="not-a-run-id"),
        lambda gh: gh.runs[0].update(updated_at=(NOW - timedelta(days=31)).isoformat()),
        lambda gh: gh.jobs[0]["steps"][1].update(conclusion="failure"),
        lambda gh: gh.jobs[0]["steps"][0].update(conclusion="failure"),
        lambda gh: gh.jobs[0]["steps"][2].update(conclusion="success"),
    ],
)
def test_preflight_rejects_missing_stale_or_wrong_ci_evidence(change) -> None:
    github = FakeGitHub()
    change(github)
    with pytest.raises(BUILD_GATE["ReleaseGateError"]):
        _do_preflight(github=github)


def test_preflight_fails_closed_if_current_raster_suite_or_file_is_missing() -> None:
    github = FakeGitHub()
    github.missing.add(f"/repos/{REPOSITORY}/contents/tests/test_raster_admission.py?ref={COMMIT}")
    with pytest.raises(BUILD_GATE["ReleaseGateError"]):
        _do_preflight(github=github)

    github = FakeGitHub()
    original = github.__call__

    def missing_ci_script(path: str):
        if path == f"/repos/{REPOSITORY}/contents/.github/workflows/ci.yml?ref={COMMIT}":
            return FakeGitHub._content(".github/workflows/ci.yml", "name: SDK CI\n")
        return original(path)

    with pytest.raises(BUILD_GATE["ReleaseGateError"]):
        BUILD_GATE["release_preflight"](
            _env(),
            "0.1.9",
            COMMIT,
            missing_ci_script,
            pypi_check=lambda version, opener=None: None,
            now=NOW,
        )


def test_preflight_fails_closed_for_missing_or_mismatched_release_tag() -> None:
    github = FakeGitHub()
    github.missing.add(f"/repos/{REPOSITORY}/git/ref/tags/v0.1.9")
    with pytest.raises(BUILD_GATE["ReleaseGateError"]):
        _do_preflight(github=github)

    github = FakeGitHub()
    github.tag_target = "d" * 40
    with pytest.raises(BUILD_GATE["ReleaseGateError"]):
        _do_preflight(github=github)

    github = FakeGitHub()
    github.tag_object_name = "v0.1.8"
    with pytest.raises(BUILD_GATE["ReleaseGateError"]):
        _do_preflight(github=github)


def test_reviewed_pyproject_version_must_match_both_local_and_remote_content() -> None:
    github = FakeGitHub()
    github.version = "0.1.8"
    with pytest.raises(BUILD_GATE["ReleaseGateError"]):
        _do_preflight(github=github)


def test_preflight_peels_nested_annotated_tags_and_records_top_level_oid() -> None:
    github = FakeGitHub()
    github.tag_object_type = "tag"
    second_oid = "d" * 40
    original = github.__call__

    def nested_tag(path: str):
        if path == f"/repos/{REPOSITORY}/git/tags/{TAG_REF_OID}":
            return {"tag": "v0.1.9", "object": {"sha": second_oid, "type": "tag"}}
        if path == f"/repos/{REPOSITORY}/git/tags/{second_oid}":
            return {"tag": "inner", "object": {"sha": COMMIT, "type": "commit"}}
        return original(path)

    result = BUILD_GATE["release_preflight"](
        _env(),
        "0.1.9",
        COMMIT,
        nested_tag,
        pypi_check=lambda version, opener=None: None,
        now=NOW,
    )
    assert result["tag_ref_oid"] == TAG_REF_OID


class _Response:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


@pytest.mark.parametrize("status", [200, 401, 429, 500, 503])
def test_pypi_anything_other_than_404_blocks(status: int) -> None:
    for script in (BUILD_GATE, PUBLISH_GATE):
        with pytest.raises(script["ReleaseGateError"]):
            script["check_pypi_absent"]("0.1.9", opener=lambda request, timeout: _Response(status))


def test_pypi_connection_failure_blocks() -> None:
    def unavailable(request, timeout):
        raise OSError("mock registry outage")

    for script in (BUILD_GATE, PUBLISH_GATE):
        with pytest.raises(script["ReleaseGateError"]):
            script["check_pypi_absent"]("0.1.9", opener=unavailable)


def test_pypi_only_404_allows_absence() -> None:
    for script in (BUILD_GATE, PUBLISH_GATE):
        script["check_pypi_absent"]("0.1.9", opener=lambda request, timeout: _Response(404))


def test_pypi_http_error_404_is_the_only_registry_error_that_allows_absence() -> None:
    def raise_status(status: int):
        def opener(request, timeout):
            raise HTTPError(request.full_url, status, "mock registry response", None, None)

        return opener

    for script in (BUILD_GATE, PUBLISH_GATE):
        script["check_pypi_absent"]("0.1.9", opener=raise_status(404))
        for status in (200, 429, 500, 503):
            with pytest.raises(script["ReleaseGateError"]):
                script["check_pypi_absent"]("0.1.9", opener=raise_status(status))


def test_build_preflight_calls_pypi_absence_check_only_after_all_gates() -> None:
    github = FakeGitHub()
    events: list[str] = []

    def api(path: str):
        events.append(path)
        return github(path)

    def pypi_check(version, opener=None):
        events.append("pypi")

    BUILD_GATE["release_preflight"](
        _env(),
        "0.1.9",
        COMMIT,
        api,
        pypi_check=pypi_check,
        now=NOW,
    )
    assert events[-1] == "pypi"
    assert any(path.startswith(f"/repos/{REPOSITORY}/actions/runs/") for path in events)


def test_publish_preflight_revalidates_main_tag_artifact_and_pypi_before_boundary(tmp_path: Path) -> None:
    bundle = tmp_path / "artifact"
    _write_artifact_bundle(tmp_path)
    github = FakeGitHub()
    events: list[str] = []

    def api(path: str):
        events.append(path)
        return github(path)

    def pypi_check(version, opener=None):
        events.append("pypi-absence-check")

    result = PUBLISH_GATE["publication_preflight"](
        _publication_env(bundle),
        api,
        artifact_dir=bundle,
        pypi_check=pypi_check,
    )
    assert result["reviewed_commit"] == COMMIT
    assert result["artifact_id"] == "777"
    assert events[-1] == "pypi-absence-check"
    assert "Publish with Trusted Publishing" in WORKFLOW_PATH.read_text()


@pytest.mark.parametrize(
    "overrides",
    [
        {"RELEASE_EVENT_NAME": "push"},
        {"RELEASE_REF": "refs/tags/v0.1.9"},
        {"RELEASE_REF": "refs/heads/release-candidate"},
        {"RELEASE_ACTOR": "external-contributor"},
        {"RELEASE_TRIGGERING_ACTOR": "external-contributor"},
        {"REVIEWED_COMMIT": "d" * 40},
        {"RELEASE_VERSION": "0.1.8"},
    ],
)
def test_publish_preflight_rejects_context_changes(tmp_path: Path, overrides) -> None:
    bundle = tmp_path / "artifact"
    _write_artifact_bundle(tmp_path)
    with pytest.raises(PUBLISH_GATE["ReleaseGateError"]):
        _do_publication_preflight(bundle, _publication_env(bundle, **overrides))


@pytest.mark.parametrize(
    "change",
    [
    lambda gh: setattr(gh, "main_sha", "d" * 40),
        lambda gh: gh.artifact.update(digest="sha256:" + "d" * 64),
        lambda gh: gh.artifact.update(id=778),
        lambda gh: gh.artifact.update(expired=True),
        lambda gh: gh.artifact.update(name="unexpected-artifact"),
        lambda gh: gh.artifact["workflow_run"].update(id=54321),
        lambda gh: gh.artifact["workflow_run"].update(head_sha="d" * 40),
        lambda gh: gh.artifact["workflow_run"].update(head_branch="feature"),
        lambda gh: setattr(gh, "tag_ref_oid", "d" * 40),
        lambda gh: setattr(gh, "tag_target", "d" * 40),
    ],
)
def test_publish_preflight_rejects_moved_tag_artifact_or_main(tmp_path: Path, change) -> None:
    bundle = tmp_path / "artifact"
    _write_artifact_bundle(tmp_path)
    github = FakeGitHub()
    change(github)
    with pytest.raises(PUBLISH_GATE["ReleaseGateError"]):
        _do_publication_preflight(bundle, github=github)


@pytest.mark.parametrize(
    "field,value",
    [
        ("workflow_run_id", 54321),
        ("workflow_run_attempt", 2),
        ("reviewed_commit", "d" * 40),
        ("version", "0.1.8"),
        ("tag_ref_oid", "d" * 40),
        ("artifact_name", "wrong-name"),
    ],
)
def test_publish_preflight_rejects_wrong_artifact_manifest_identity(
    tmp_path: Path, field: str, value
) -> None:
    bundle = tmp_path / "artifact"
    manifest = _write_artifact_bundle(tmp_path)
    manifest[field] = value
    (bundle / "release-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(PUBLISH_GATE["ReleaseGateError"]):
        _do_publication_preflight(bundle)


def test_publish_preflight_rejects_distribution_hash_or_extra_file(tmp_path: Path) -> None:
    bundle = tmp_path / "artifact"
    manifest = _write_artifact_bundle(tmp_path)
    wheel = next((bundle / "dist").glob("*.whl"))
    wheel.write_bytes(b"modified after build")
    with pytest.raises(PUBLISH_GATE["ReleaseGateError"]):
        _do_publication_preflight(bundle)

    second_root = tmp_path / "second"
    second_root.mkdir()
    _write_artifact_bundle(second_root)
    (second_root / "artifact" / "dist" / "unexpected.txt").write_text("unexpected")
    with pytest.raises(PUBLISH_GATE["ReleaseGateError"]):
        _do_publication_preflight(second_root / "artifact")


def test_publish_preflight_rejects_bad_artifact_id_digest_and_pypi_failure(tmp_path: Path) -> None:
    bundle = tmp_path / "artifact"
    _write_artifact_bundle(tmp_path)
    for env_change in (
        {"EXPECTED_ARTIFACT_ID": "not-an-id"},
        {"EXPECTED_ARTIFACT_DIGEST": "sha256:" + "d" * 64},
    ):
        with pytest.raises(PUBLISH_GATE["ReleaseGateError"]):
            _do_publication_preflight(bundle, _publication_env(bundle, **env_change))

    for status in (200, 429, 500):
        with pytest.raises(PUBLISH_GATE["ReleaseGateError"]):
            PUBLISH_GATE["publication_preflight"](
                _publication_env(bundle),
                FakeGitHub(),
                artifact_dir=bundle,
                pypi_check=lambda version, opener=None, s=status: (_ for _ in ()).throw(
                    PUBLISH_GATE["ReleaseGateError"](f"HTTP {s}")
                ),
            )


def test_rejected_ci_and_artifact_gates_prevent_real_publisher_step() -> None:
    text = WORKFLOW_PATH.read_text()
    build_block = text.split("  build:", 1)[1].split("  publish:", 1)[0]
    publish_block = text.split("  publish:", 1)[1]
    required_build_steps = (
        "Install declared package and test dependencies",
        "Run the complete SDK test suite",
        "Build wheel and source distribution",
        "Validate distribution metadata",
        "Qualify the clean installed release wheel",
    )
    positions = [build_block.index(name) for name in required_build_steps]
    assert positions == sorted(positions)
    assert publish_block.index("Revalidate publication authorization and artifact") < publish_block.index(
        "Publish with Trusted Publishing"
    )
    assert "if: always()" not in publish_block
    assert "attestations: true" in publish_block
