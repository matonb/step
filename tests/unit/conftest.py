# Copyright: (c) 2025, Brett Maton <matonb@users.noreply.github.com>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Make the collection importable when pytest is run directly.

Modules import their shared code as
``ansible_collections.matonb.step.plugins.module_utils.*``, which only resolves
when the collection sits in an ``ansible_collections/<namespace>/<name>``
directory. ``ansible-test units`` arranges that itself; a developer running
``pytest tests/unit`` from a clone does not, because the clone is usually named
after the repository rather than the collection.

This builds that layout as a symlink *inside the checkout* and puts it on
``sys.path``. Keeping it in the checkout rather than the shared temp directory
matters: a predictable path under ``/tmp`` can be pre-created by anything else
on the host, and this code adds it to ``sys.path``, so tests would import and
execute whatever is there. It also keeps two checkouts from repointing each
other's link.
"""

import pathlib
import sys

COLLECTION = ("matonb", "step")
CACHE_DIR = ".pytest-collection-root"


def _already_importable(repo_root: pathlib.Path) -> bool:
    """Whether this checkout is importable as the collection already.

    Args:
        repo_root: The repository root.

    Returns:
        bool: True when the collection resolves to this checkout.
    """
    try:
        module = __import__("ansible_collections.{}.{}".format(*COLLECTION), fromlist=["__file__"])
    except ImportError:
        return False

    # Importable from *somewhere* is not good enough; a different copy on
    # sys.path would silently be the thing under test.
    location = getattr(module, "__file__", None) or (module.__path__[0] if module.__path__ else "")
    return repo_root in pathlib.Path(location).resolve().parents or pathlib.Path(location).resolve() == repo_root


def _ensure_collection_importable() -> None:
    """Put an ansible_collections tree for this checkout on sys.path."""
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    if _already_importable(repo_root):
        return

    tree = repo_root / CACHE_DIR
    link = tree.joinpath("ansible_collections", *COLLECTION)
    link.parent.mkdir(parents=True, exist_ok=True)

    if link.is_symlink() and link.resolve() != repo_root:
        link.unlink()
    if not link.exists():
        try:
            link.symlink_to(repo_root, target_is_directory=True)
        except FileExistsError:
            # Another xdist worker won the race, which is fine.
            pass

    sys.path.insert(0, str(tree))


_ensure_collection_importable()
