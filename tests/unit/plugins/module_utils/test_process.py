# Copyright: (c) 2025, Brett Maton <matonb@users.noreply.github.com>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Tests for command execution, privilege dropping and the timeout path."""

import os
import pwd
import signal
import subprocess

import pytest

from ansible_collections.matonb.step.plugins.module_utils.process import (
    CommandTimeoutError,
    _create_completed_process,
    _demotion_hook,
    _handle_command_failure,
    _validate_user_switch,
    demote_user,
    run_command,
    sanitize_output,
    strip_ansi_sequences,
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
    monkeypatch.setattr(os, "getgrouplist", lambda *_args: [5678, 27])
    monkeypatch.setattr(os, "setgroups", lambda *args: calls.append(("setgroups", args)))
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

        assert "setgroups" in [name for name, arguments in recorded_switch]

    def test_privileges_are_dropped_in_a_workable_order(self, recorded_switch):
        # Order is the whole game: setuid last, because once the uid is no
        # longer root neither setgroups nor setgid is permitted, and the
        # process would be left holding what it meant to drop.
        demote_user("stepuser")

        assert [name for name, arguments in recorded_switch] == ["setgroups", "setgid", "setuid"]

    def test_the_target_users_own_ids_are_used(self, recorded_switch):
        demote_user("stepuser")

        by_name = dict(recorded_switch)
        assert by_name["setgroups"] == ([5678, 27],)
        assert by_name["setgid"] == (5678,)
        assert by_name["setuid"] == (1234,)

    def test_an_unknown_user_is_reported_by_name(self, monkeypatch):
        def raise_key_error(name):
            raise KeyError(name)

        monkeypatch.setattr(pwd, "getpwnam", raise_key_error)

        with pytest.raises(RuntimeError, match="nosuchuser"):
            demote_user("nosuchuser")

    def test_a_refused_switch_is_reported_by_name(self, recorded_switch, monkeypatch):
        # The realistic cause is running without root, where setgid is denied.
        # The OSError alone says "Operation not permitted" and names no user.
        #
        # Built on the fixture so every id-changing call stays substituted. An
        # earlier version patched only setgid and left os.setuid real, which
        # was harmless only because setgid failed first - exactly the ordering
        # the test above exists to catch. Under ansible-test units --docker,
        # as root, that would have demoted the test runner mid-suite.
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


class TestSanitizeOutput:
    def test_colour_codes_are_removed(self):
        # step colours its output when it thinks it has a terminal. Those bytes
        # end up in module results and in the diffs modules compare, where an
        # escape sequence reads as a difference that is not one.
        assert strip_ansi_sequences("\x1b[32mok\x1b[0m") == "ok"

    def test_control_characters_are_dropped_but_layout_is_kept(self):
        # A bare \x07 in a module's JSON result is not printable and not useful;
        # newlines and tabs are how step formats output worth reading.
        assert sanitize_output("a\x07b\nc\td") == "ab\nc\td"

    def test_none_survives_as_none(self):
        # stdout is None when the stream was not captured, which is not an
        # error and must not become the string "None".
        assert sanitize_output(None) is None

    def test_strip_ansi_false_still_does_not_preserve_colour(self):
        # Worth pinning because the name promises otherwise. Skipping the ANSI
        # regex does not keep the sequence: ESC is not printable, so the filter
        # below removes it and leaves the rest as literal text. The option
        # buys mangled output rather than coloured output, and a caller
        # reaching for it to keep colour will not get it.
        assert sanitize_output("\x1b[32mok\x1b[0m", strip_ansi=False) == "[32mok[0m"


class TestDemotionHook:
    def test_no_username_means_no_hook_at_all(self):
        # Not a callable that returns None: subprocess runs whatever it is
        # given between fork and exec, and there is nothing to do here.
        assert _demotion_hook(None) is None
        assert _demotion_hook("") is None

    def test_a_username_produces_a_hook_that_drops_to_it(self, recorded_switch):
        hook = _demotion_hook("stepuser")

        # Nothing has happened yet: the hook runs in the child, after the fork.
        assert recorded_switch == []

        hook()

        assert [name for name, arguments in recorded_switch] == ["setgroups", "setgid", "setuid"]

    def test_the_lookup_happens_before_the_fork(self, recorded_switch, monkeypatch):
        # subprocess reports anything a preexec_fn raises as a bare "Exception
        # occurred in preexec_fn.", so a name resolved in the child is a name
        # whose failure the operator never sees. Resolving here means the
        # RuntimeError still says which user was wrong.
        looked_up = []
        monkeypatch.setattr(pwd, "getpwnam", lambda name: looked_up.append(name) or FakePasswd())

        _demotion_hook("stepuser")

        assert looked_up == ["stepuser"]

    def test_an_unknown_user_is_refused_before_anything_forks(self, monkeypatch):
        def raise_key_error(name):
            raise KeyError(name)

        monkeypatch.setattr(pwd, "getpwnam", raise_key_error)

        with pytest.raises(RuntimeError, match="nosuchuser"):
            _demotion_hook("nosuchuser")


class TestTheHookReachesSubprocess:
    """The wire between _demotion_hook and Popen.

    Both halves were tested in isolation and the wire between them was not, so
    deleting `preexec_fn=_demotion_hook(username)` from both call sites left
    the whole suite green - a build that never demoted at all. That is the
    defect this file exists for, so it is asserted directly.
    """

    @staticmethod
    def _captured_popen(monkeypatch):
        """Capture the kwargs run_command hands to Popen.

        Args:
            monkeypatch: pytest's monkeypatch fixture.

        Returns:
            dict: filled with the keyword arguments of the next Popen call.
        """
        captured = {}
        real_popen = subprocess.Popen

        class CapturingPopen(real_popen):
            def __init__(self, *args, **kwargs):
                captured.update(kwargs)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(subprocess, "Popen", CapturingPopen)
        return captured

    def test_a_username_reaches_popen_as_a_preexec_fn(self, recorded_switch, monkeypatch):
        captured = self._captured_popen(monkeypatch)
        monkeypatch.setattr(os, "geteuid", lambda: 0)

        run_command(["echo", "hello"], username="stepuser")

        assert captured["preexec_fn"] is not None

        # And it is the demotion, not merely some callable: run it here, where
        # the ids are substituted, and see the drop happen.
        captured["preexec_fn"]()
        assert [name for name, arguments in recorded_switch] == ["setgroups", "setgid", "setuid"]

    def test_no_username_reaches_popen_as_no_hook(self, monkeypatch):
        captured = self._captured_popen(monkeypatch)

        run_command(["echo", "hello"])

        assert captured["preexec_fn"] is None

    def test_the_timeout_path_wires_it_too(self, recorded_switch, monkeypatch):
        # Two Popen call sites, and only one of them is on the timeout path.
        captured = self._captured_popen(monkeypatch)
        monkeypatch.setattr(os, "geteuid", lambda: 0)

        run_command(["echo", "hello"], username="stepuser", timeout=10)

        assert captured["preexec_fn"] is not None
        captured["preexec_fn"]()
        assert [name for name, arguments in recorded_switch] == ["setgroups", "setgid", "setuid"]


class TestValidateUserSwitch:
    def test_a_switch_without_root_is_refused_with_advice(self, monkeypatch):
        # The failure would otherwise happen after the fork, where it surfaces
        # as an opaque subprocess error rather than as "you need become: true".
        monkeypatch.setattr(os, "geteuid", lambda: 1000)

        with pytest.raises(RuntimeError, match="become: true"):
            _validate_user_switch("stepuser")

    def test_root_may_switch(self, monkeypatch):
        monkeypatch.setattr(os, "geteuid", lambda: 0)

        assert _validate_user_switch("stepuser") is None

    def test_no_switch_is_requested_so_privileges_do_not_matter(self, monkeypatch):
        monkeypatch.setattr(os, "geteuid", lambda: 1000)

        assert _validate_user_switch(None) is None


class TestCompletedProcess:
    def test_output_is_sanitized_when_captured_as_text(self):
        result = _create_completed_process(["step"], 0, "\x1b[32mok\x1b[0m", None, text=True, strip_ansi=True)

        assert result.stdout == "ok"

    def test_stderr_is_sanitized_as_well_as_stdout(self):
        # The failure message an operator reads is built from stderr, so colour
        # left in it is colour in the module's reported error.
        result = _create_completed_process(["step"], 1, None, "\x1b[31mboom\x1b[0m", text=True, strip_ansi=True)

        assert result.stderr == "boom"

    def test_the_command_is_carried_into_the_result(self):
        result = _create_completed_process(["step", "version"], 0, "", "", text=True, strip_ansi=True)

        assert result.args == ["step", "version"]

    def test_strip_ansi_false_is_honoured(self):
        # Nothing else threads this flag all the way through, so a
        # _create_completed_process that ignored it would go unnoticed.
        result = _create_completed_process(["step"], 0, "\x1b[32mok", None, text=True, strip_ansi=False)

        assert result.stdout == "[32mok"

    def test_bytes_are_left_alone(self):
        # sanitize_output works on str. Handing it bytes would raise, so the
        # text flag has to gate it rather than merely describe it.
        result = _create_completed_process(["step"], 0, b"\x1b[32mok", None, text=False, strip_ansi=True)

        assert result.stdout == b"\x1b[32mok"


class TestHandleCommandFailure:
    def test_a_failure_reports_both_streams(self):
        # Whichever stream step used, the operator needs it: the message is all
        # they see when a module fails.
        result = subprocess.CompletedProcess(args=["step"], returncode=2, stdout="out", stderr="boom")

        with pytest.raises(RuntimeError, match="boom") as failure:
            _handle_command_failure(result, check=True, text=True)

        assert "out" in str(failure.value)
        assert "2" in str(failure.value)

    def test_check_false_lets_a_failure_through(self):
        result = subprocess.CompletedProcess(args=["step"], returncode=2, stdout="", stderr="")

        assert _handle_command_failure(result, check=False, text=True) is None

    def test_success_is_never_a_failure(self):
        result = subprocess.CompletedProcess(args=["step"], returncode=0, stdout="", stderr="")

        assert _handle_command_failure(result, check=True, text=True) is None


class TestRunCommand:
    def test_a_successful_command_returns_its_output(self):
        result = run_command(["echo", "hello"])

        assert result.returncode == 0
        assert result.stdout.strip() == "hello"

    def test_a_failure_raises_by_default(self):
        with pytest.raises(RuntimeError, match="return code 1"):
            run_command(["false"])

    def test_check_false_returns_the_failure_instead(self):
        result = run_command(["false"], check=False)

        assert result.returncode == 1

    def test_extra_environment_reaches_the_command(self):
        # step is configured through the environment - STEPPATH above all - so
        # a variable that does not arrive means a command reading the wrong CA.
        result = run_command(["sh", "-c", "echo $STEP_TEST_MARKER"], env_vars={"STEP_TEST_MARKER": "arrived"})

        assert result.stdout.strip() == "arrived"

    def test_the_inherited_environment_survives_alongside_it(self, monkeypatch):
        monkeypatch.setenv("STEP_TEST_INHERITED", "kept")

        result = run_command(["sh", "-c", "echo $STEP_TEST_INHERITED"], env_vars={"STEP_TEST_OTHER": "x"})

        assert result.stdout.strip() == "kept"

    def test_the_command_is_logged_before_it_runs(self):
        # Modules pass module.log here. Writing to stdout instead would corrupt
        # the JSON Ansible parses, so this exists and is worth keeping honest.
        logged = []

        run_command(["echo", "hello"], logger=logged.append)

        assert logged == ["Executing command: echo hello"]

    def test_a_shell_command_runs_through_the_shell(self):
        # The shell is the subject here, not an oversight.
        result = run_command("echo one && echo two", shell=True)  # noqa: S604

        assert result.stdout.split() == ["one", "two"]

    def test_strip_ansi_false_reaches_the_result(self):
        result = run_command(["printf", "\x1b[32mok"], strip_ansi=False)

        assert result.stdout == "[32mok"

    def test_output_can_be_left_as_bytes(self):
        result = run_command(["echo", "hello"], text=False)

        assert result.stdout.strip() == b"hello"

    def test_demotion_without_root_is_refused_before_forking(self):
        # Runs as an ordinary user, which is the whole point: the refusal has
        # to come from _validate_user_switch rather than from the child.
        if os.geteuid() == 0:
            pytest.skip("running as root, so the switch would be permitted")

        with pytest.raises(RuntimeError, match="requires root privileges"):
            run_command(["echo", "hello"], username="stepuser")


class TestRunWithTimeout:
    def test_a_command_within_its_timeout_is_unaffected(self):
        result = run_command(["echo", "hello"], timeout=10)

        assert result.stdout.strip() == "hello"

    def test_an_overrunning_command_times_out(self):
        # The provisioner module's whole anti-hang design rests on this: step
        # prompting for input that never comes must become a failed task rather
        # than a play that waits forever.
        with pytest.raises(CommandTimeoutError, match="timed out after"):
            run_command(["sleep", "5"], timeout=0.2)

    def test_the_timed_out_command_is_actually_killed(self, monkeypatch):
        # Raising while leaving the process running would satisfy the test
        # above and still leak a step process holding the CA's files open.
        #
        # Asserted from the signal the child died of rather than by waiting to
        # see whether it did something: -SIGKILL can only come from the kill()
        # in the timeout path, and it costs no wall clock. An earlier version
        # slept 1.5s watching for a marker file and was the slowest thing in
        # the suite by an order of magnitude.
        started = []
        real_popen = subprocess.Popen

        class CapturingPopen(real_popen):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                started.append(self)

        monkeypatch.setattr(subprocess, "Popen", CapturingPopen)

        with pytest.raises(CommandTimeoutError):
            run_command(["sleep", "5"], timeout=0.2)

        assert started[0].returncode == -signal.SIGKILL

    def test_a_failure_inside_the_timeout_still_reports_normally(self):
        with pytest.raises(RuntimeError, match="return code 1"):
            run_command(["false"], timeout=10)

    def test_check_false_applies_under_a_timeout_too(self):
        result = run_command(["false"], timeout=10, check=False)

        assert result.returncode == 1
