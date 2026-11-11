import pytest

from fareflare.product_cli import main


def test_customer_server_requires_built_dashboard(tmp_path):
    with pytest.raises(ValueError, match="Build the dashboard"):
        main(
            [
                "--database",
                str(tmp_path / "data.sqlite3"),
                "serve",
                "--static-dir",
                str(tmp_path / "missing"),
            ]
        )
