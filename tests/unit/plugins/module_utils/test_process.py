# Copyright: (c) 2025, Brett Maton <matonb@users.noreply.github.com>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Tests for command execution, privilege dropping and the timeout path."""

import os
import pwd

import pytest

from ansible_collections.matonb.step.plugins.module_utils.process import (
    demote_user,
)


class FakePasswd:
    """The subset of pwd.struct_passwd that demote_user reads."""

    def __init__(self, uid=1234, gid=5678, directory="/home/stepuser"):
        """Build a passwd record with the fields demote_user reads.

        Args:
            uid: The target user's uid.
            gid: The target user's primary gid.
            directory: The target user's home directory.
        """
        self.pw_uid = uid
        self.pw_gid = gid
        self.pw_dir = directory


@pytest.fixture
def recorded_switch(monkeypatch):
    """Record the privilege calls demote_user makes, without making them.

    Actually switching user needs root and is irreversible within the process,
    so the calls are recorded instead. What matters here is which ones are made
    and in what order, and that survives the substitution.

    Returns:
        list: (name, args) in the order demote_user called them.
    """
    calls = []

    monkeypatch.setattr(pwd, "getpwnam", lambda _name: FakePasswd())
    monkeypatch.setattr(os, "initgroups", lambda *args: calls.append(("initgroups", args)), raising=False)
    monkeypatch.setattr(os, "setgid", lambda *args: calls.append(("setgid", args)))
    monkeypatch.setattr(os, "setuid", lambda *args: calls.append(("setuid", args)))
    monkeypatch.setattr(os, "environ", {})

    return calls


class TestDemoteUser:
    def test_supplementary_groups_are_dropped(self, recorded_switch):
        # setgid and setuid leave the supplementary groups of the *calling*
        # process in place. Started as root - which is the only way this code
        # runs at all - the child would keep root's group memberships after the
        # switch, holding access the target user does not have. Dropping them
        # is what makes this a privilege drop rather than a uid change.
        demote_user("stepuser")

        assert "initgroups" in [name for name, _ in recorded_switch]

    def test_privileges_are_dropped_in_a_workable_order(self, recorded_switch):
        # Order is the whole game: setuid last, because once the uid is no
        # longer root neither initgroups nor setgid is permitted, and the
        # process would be left holding what it meant to drop.
        demote_user("stepuser")

        assert [name for name, _ in recorded_switch] == ["initgroups", "setgid", "setuid"]

    def test_the_target_users_own_ids_are_used(self, recorded_switch):
        demote_user("stepuser")

        by_name = dict(recorded_switch)
        assert by_name["initgroups"] == ("stepuser", 5678)
        assert by_name["setgid"] == (5678,)
        assert by_name["setuid"] == (1234,)

    def test_an_unknown_user_is_reported_by_name(self, monkeypatch):
        def raise_key_error(name):
            raise KeyError(name)

        monkeypatch.setattr(pwd, "getpwnam", raise_key_error)

        with pytest.raises(RuntimeError, match="nosuchuser"):
            demote_user("nosuchuser")

    def test_a_refused_switch_is_reported_by_name(self, monkeypatch):
        # The realistic cause is running without root, where setgid is denied.
        # The OSError alone says "Operation not permitted" and names no user.
        monkeypatch.setattr(pwd, "getpwnam", lambda _name: FakePasswd())
        monkeypatch.setattr(os, "initgroups", lambda *_args: None, raising=False)

        def deny(*_args):
            raise OSError(1, "Operation not permitted")

        monkeypatch.setattr(os, "setgid", deny)

        with pytest.raises(RuntimeError, match="stepuser"):
            demote_user("stepuser")

    def test_the_environment_describes_the_new_user(self, recorded_switch, monkeypatch):
        environment = {}
        monkeypatch.setattr(os, "environ", environment)

        demote_user("stepuser")

        # step reads HOME to find its own configuration; left pointing at
        # root's, a demoted command would read the wrong CA.
        assert environment == {
            "HOME": "/home/stepuser",
            "USER": "stepuser",
            "LOGNAME": "stepuser",
        }
