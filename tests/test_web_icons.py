"""The app ships a subset of Bootstrap Icons; every icon it names must be in it."""

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web" / "src"
NAME = re.compile(r"\bbi-([a-z0-9]+(?:-[a-z0-9]+)*)")


def test_every_icon_used_is_in_the_shipped_subset():
    shipped = set(
        re.findall(
            r"\.bi-([a-z0-9-]+)::before", (WEB / "icons" / "bootstrap-icons-subset.css").read_text()
        )
    )
    used = {
        name
        for path in WEB.rglob("*")
        if path.suffix in {".html", ".ts", ".scss"} and "icons" not in path.relative_to(WEB).parts
        for name in NAME.findall(path.read_text())
    }
    missing = sorted(used - shipped)
    assert not missing, (
        f"Icons missing from the subset: {missing}. Run "
        "`uvx --with fonttools --with brotli python web/scripts/subset-icons.py`."
    )
    assert (WEB / "icons" / "bootstrap-icons-subset.woff2").stat().st_size < 20_000
