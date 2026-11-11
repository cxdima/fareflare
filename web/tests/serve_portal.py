"""Ephemeral local browser fixture: actual portal, no AWS, Google requests or worker."""

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import uvicorn  # noqa: E402

from fareflare.accounts import Accounts  # noqa: E402
from fareflare.mailer import FileMailer  # noqa: E402
from fareflare.portal import create_portal  # noqa: E402
from fareflare.product_config import ProductConfig  # noqa: E402
from fareflare.public_quotes import supported_target  # noqa: E402
from fareflare.service import MonitoringService  # noqa: E402
from fareflare.store import SQLiteStore  # noqa: E402

with tempfile.TemporaryDirectory(prefix="fareflare-browser-") as directory:
    store = SQLiteStore(Path(directory) / "test.sqlite3")
    config = ProductConfig(public_url="http://127.0.0.1:8007")
    # Account email lands here as files, so a test can open a reset or confirmation link.
    outbox = ROOT / "web" / "artifacts" / "outbox"
    shutil.rmtree(outbox, ignore_errors=True)
    accounts = Accounts(store, config, mailer=FileMailer(outbox))
    service = MonitoringService(store, capability_check=supported_target)
    app = create_portal(
        service,
        config,
        accounts,
        static_dir=ROOT / "web" / "dist",
        # Each browser test signs in several times; the production limit is per real visitor.
        auth_attempts_per_minute=120,
    )
    uvicorn.run(app, host="127.0.0.1", port=8007, access_log=False)
