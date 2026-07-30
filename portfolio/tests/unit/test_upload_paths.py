"""Filesystem hardening on the upload path.

Client-supplied filenames were joined straight onto a directory, so `../../evil.py` wrote
outside the upload root -- an arbitrary file write. These helpers live in
`ingestion/uploads.py` rather than the router because the Streamlit UI writes to disk in
process too and needs the identical checks.
"""

import pytest

from app.config import get_settings
from app.ingestion.uploads import safe_filename, tenant_upload_dir

_VALID_TENANT = "a" * 32


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [
        ("paper.pdf", "paper.pdf"),
        ("../../../etc/passwd", "passwd"),
        ("../../evil.py", "evil.py"),
        ("subdir/paper.pdf", "paper.pdf"),
        ("/absolute/paper.pdf", "paper.pdf"),
    ],
)
def test_directory_components_are_stripped(supplied: str, expected: str) -> None:
    assert safe_filename(supplied) == expected


@pytest.mark.parametrize("supplied", [None, "", "..", ".", "/", ".hidden", "../"])
def test_unusable_filenames_are_refused(supplied: str | None) -> None:
    """`..` and `/` reduce to an empty or dot-only name -- refuse rather than invent one."""
    with pytest.raises(ValueError, match="filename"):
        safe_filename(supplied)


def test_upload_dir_is_inside_the_configured_root() -> None:
    root = get_settings().upload_dir.resolve()

    assert tenant_upload_dir(root, _VALID_TENANT).is_relative_to(root)


@pytest.mark.parametrize(
    "tenant_id",
    ["../escape", "..", "a" * 31, "a" * 33, "A" * 32, "g" * 32, "", "a/b", "a" * 16 + "/" + "b" * 15],
)
def test_malformed_tenant_ids_never_become_paths(tenant_id: str) -> None:
    """Tenant ids are server-issued, so this should be unreachable -- which is the point.
    If it ever becomes reachable, it fails loudly here instead of escaping the upload root.
    """
    with pytest.raises(ValueError, match="tenant id"):
        tenant_upload_dir(get_settings().upload_dir, tenant_id)
