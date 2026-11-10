"""Ephemeral local browser fixture: actual portal, no AWS, Google requests or worker."""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import uvicorn  # noqa: E402

from fareflare.accounts import Accounts  # noqa: E402
from fareflare.portal import create_portal  # noqa: E402
from fareflare.product_config import ProductConfig  # noqa: E402
from fareflare.public_quotes import supported_target  # noqa: E402
from fareflare.service import MonitoringService  # noqa: E402
from fareflare.store import SQLiteStore  # noqa: E402

with tempfile.TemporaryDirectory(prefix="fareflare-browser-") as directory:
    store = SQLiteStore(Path(directory) / "test.sqlite3")
    config = ProductConfig(public_url="http://127.0.0.1:8007")
    invitations = [Accounts(store, config).create_invite()["token"] for _ in range(6)]
    fixture = ROOT / "web" / "artifacts" / "portal-fixture.json"
    fixture.parent.mkdir(exist_ok=True)
    fixture.write_text(
        json.dumps({"invites": invitations[:3], "preferences_invites": invitations[3:]})
    )
    fixture.chmod(0o600)
    service = MonitoringService(store, capability_check=supported_target)
    app = create_portal(service, config, static_dir=ROOT / "web" / "dist")
    uvicorn.run(app, host="127.0.0.1", port=8007, access_log=False)
