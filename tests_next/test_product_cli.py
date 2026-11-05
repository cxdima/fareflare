import json
from unittest.mock import Mock

import pytest

from gfpt_next.product_cli import main


def test_local_invitation_is_private_single_use_and_not_overwritten(tmp_path, capsys):
    from gfpt_next.accounts import Accounts
    from gfpt_next.store import SQLiteStore
    path = tmp_path / "invite.json"
    database = tmp_path / "product.sqlite3"
    command = ["--database", str(database), "invite", str(path)]
    main(command)
    invitation = json.loads(path.read_text())
    assert invitation["url"] == "http://127.0.0.1:8001/?invite=" + invitation["token"]
    assert path.stat().st_mode & 0o777 == 0o600
    assert invitation["token"] not in capsys.readouterr().out
    accounts = Accounts(SQLiteStore(database))
    accounts.register("alice", "a very long account password", invitation["token"])
    with pytest.raises(ValueError, match="invitation|Invitation|Invite|invite"):
        accounts.register("bravo", "a very long account password", invitation["token"])
    with pytest.raises(FileExistsError):
        main(command)
    assert json.loads(path.read_text()) == invitation


def test_cloud_invitation_requires_expected_account_before_write(tmp_path, monkeypatch):
    import boto3
    client = Mock()
    client.get_caller_identity.return_value = {"Account": "222222222222"}
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: client)
    path = tmp_path / "invite.json"
    with pytest.raises(ValueError, match="AWS account"):
        main(["invite", str(path), "--table", "gfpt-next-tests", "--aws-account", "111111111111"])
    assert not path.exists()


def test_customer_server_requires_built_dashboard(tmp_path):
    with pytest.raises(ValueError, match="Build the dashboard"):
        main(["--database", str(tmp_path / "data.sqlite3"), "serve", "--static-dir", str(tmp_path / "missing")])
