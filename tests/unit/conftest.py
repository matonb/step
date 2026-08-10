# Copyright: (c) 2025, Brett Maton <matonb@users.noreply.github.com>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Make the collection importable when pytest is run directly.

Modules import their shared code as
``ansible_collections.matonb.smallstep.plugins.module_utils.*``, which only resolves
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

It also provides the ``run_module`` fixture, which executes a module as its own
process the way Ansible does. That belongs here rather than in a test module
because it depends on the ``sys.path`` entry arranged above, and because both
module test files need it.
"""

import json
import os
import pathlib
import subprocess
import sys

import pytest

COLLECTION = ("matonb", "smallstep")
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


@pytest.fixture
def run_module():
    """Execute a module as its own process, the way Ansible invokes one.

    Ansible runs a module as a subprocess with ``ANSIBLE_MODULE_ARGS`` on stdin.
    Driving it that way rather than calling the functions inside it is what pins
    the behaviour that lives in ``main()`` - the part no test of the individual
    functions can reach.

    The child inherits this process's environment but *not* its ``sys.path``,
    which is where ``_ensure_collection_importable`` made the collection
    resolvable, so ``PYTHONPATH`` is handed over explicitly rather than
    recomputed. Only entries that actually carry an ``ansible_collections``
    directory are passed: exporting the whole path would also export pytest's
    insertion of the test's own directory, letting it shadow stdlib imports in
    the child. ``ansible`` itself comes from the interpreter's own
    site-packages.

    Returns:
        callable: ``(module, params, extra_env=None) -> dict``, the module's
            parsed result. ``params`` becomes ``ANSIBLE_MODULE_ARGS``, and
            ``extra_env`` is merged into the child's environment last, for a
            test that needs to stub a binary onto ``PATH``.
    """

    def _run(module, params, extra_env=None):
        args = json.dumps({"ANSIBLE_MODULE_ARGS": params})
        collection_paths = [
            path for path in sys.path if path and os.path.isdir(os.path.join(path, "ansible_collections"))
        ]
        completed = subprocess.run(
            [sys.executable, module.__file__],
            input=args,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "PYTHONPATH": os.pathsep.join(collection_paths), **(extra_env or {})},
        )
        if not completed.stdout:
            # Without this the failure surfaces as a JSONDecodeError and the real
            # traceback, which is on stderr, is thrown away.
            raise AssertionError(f"module produced no result (exit {completed.returncode}):\n{completed.stderr}")
        return json.loads(completed.stdout)

    return _run
