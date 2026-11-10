"""The lock-file guard: a pin that the installed lock does not match must fail the build."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("check_locks", ROOT / "scripts/check_locks.py")
assert spec and spec.loader
check_locks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_locks)


def project(
    tmp_path, runtime, runtime_lock, dev="-r requirements.txt\npytest==9.2.0\n", dev_lock=None
):
    (tmp_path / "requirements.txt").write_text(runtime)
    (tmp_path / "requirements.lock").write_text(runtime_lock)
    (tmp_path / "requirements-dev.txt").write_text(dev)
    (tmp_path / "requirements-dev.lock").write_text(
        dev_lock
        if dev_lock is not None
        else runtime_lock + "pytest==9.2.0 \\\n    --hash=sha256:aa\n"
    )
    return check_locks.problems(tmp_path)


def test_the_repository_lock_files_match_their_pins():
    assert check_locks.problems() == []


def test_matching_pins_pass_whatever_the_spelling_of_the_name(tmp_path):
    lock = (
        "typing-extensions==4.16.0 \\\n    --hash=sha256:aa\nmoto==5.2.5 \\\n    --hash=sha256:bb\n"
    )
    assert (
        project(tmp_path, "# runtime\nTyping_Extensions==4.16.0\nmoto[dynamodb]==5.2.5\n", lock)
        == []
    )


def test_a_bumped_pin_with_a_stale_lock_is_reported_for_each_file(tmp_path):
    issues = project(tmp_path, "boto3==1.43.126\n", "boto3==1.34.162 \\\n    --hash=sha256:aa\n")
    assert issues == [
        "requirements.txt pins boto3==1.43.126, but requirements.lock has boto3==1.34.162",
        "requirements-dev.txt pins boto3==1.43.126, but requirements-dev.lock has boto3==1.34.162",
    ]


def test_a_pin_missing_from_the_lock_is_reported(tmp_path):
    issues = project(tmp_path, "httpx==0.28.1\n", "", dev_lock="httpx==0.28.1\n")
    assert issues == [
        "requirements.txt pins httpx==0.28.1, but requirements.lock has no such package",
        "requirements-dev.txt pins pytest==9.2.0, but requirements-dev.lock has no such package",
    ]
