from __future__ import annotations

import io
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from oz_workflows import docker_agent
from oz_workflows.docker_agent import (
    DockerAgentError,
    DockerAgentRun,
    DockerAgentTimeout,
    _apply_system_event,
    _build_docker_argv,
    _format_argv_for_log,
    _ingest_stdout_line,
    _read_output_json,
    resolve_triage_image,
    run_agent_in_docker,
)


class BuildDockerArgvTest(unittest.TestCase):
    """Argv construction contract for ``_build_docker_argv``.

    The helper emits exactly one argv shape; we assert every piece of
    that shape in a single grouped test so a cosmetic rename has a
    single place to update instead of several.
    """

    def _argv(self, **overrides: object) -> list[str]:
        defaults: dict[str, object] = {
            "image": "oz-for-oss-triage",
            "repo_dir": Path("/tmp/repo"),
            "output_dir": Path("/tmp/output"),
            "prompt": "PROMPT_BODY",
            "skill_name": "triage-issue",
            "title": "Triage issue #1",
            "model": None,
        }
        defaults.update(overrides)
        return _build_docker_argv(**defaults)  # type: ignore[arg-type]

    def test_argv_contract(self) -> None:
        """Every flag and mount the workflow depends on appears in the argv."""
        argv = self._argv()

        # Docker boilerplate.
        self.assertEqual(argv[:3], ["docker", "run", "--rm"])

        # Env forwarding: bare ``-e NAME`` form so secret values are
        # never inlined on the command line.
        for name in ("WARP_API_KEY", "WARP_API_BASE_URL"):
            with self.subTest(env=name):
                self.assertIn(name, argv)
        for part in argv:
            self.assertFalse(
                part.startswith("WARP_API_KEY="),
                msg=f"API key must never be inlined, got part={part!r}",
            )

        # Mounts: repo must be read-only, output must be writable.
        self.assertIn("/tmp/repo:/mnt/repo:ro", argv)
        self.assertIn("/tmp/output:/mnt/output", argv)

        # Inner ``oz agent run`` flags.
        for flag, expected in (
            ("--skill", "triage-issue"),
            ("--cwd", "/mnt/repo"),
            ("--prompt", "PROMPT_BODY"),
            ("--output-format", "json"),
        ):
            with self.subTest(flag=flag):
                idx = argv.index(flag)
                self.assertEqual(argv[idx + 1], expected)
        self.assertIn("--share", argv)

    def test_model_flag_optional(self) -> None:
        """``--model`` appears only when the caller passes one."""
        self.assertNotIn("--model", self._argv())
        argv = self._argv(model="claude-4-5-sonnet")
        idx = argv.index("--model")
        self.assertEqual(argv[idx + 1], "claude-4-5-sonnet")


class ApplySystemEventTest(unittest.TestCase):
    """``_apply_system_event`` returns True iff a tracked field changed."""

    def test_event_parsing_table(self) -> None:
        cases = [
            (
                "run_started_populates_run_id",
                {
                    "type": "system",
                    "event_type": "run_started",
                    "run_id": "abc-123",
                    "run_url": "https://warp.dev/run",
                },
                "run_id",
                "abc-123",
                True,
            ),
            (
                "shared_session_established_populates_session_link",
                {
                    "type": "system",
                    "event_type": "shared_session_established",
                    "join_url": "https://app.warp.dev/x",
                },
                "session_link",
                "https://app.warp.dev/x",
                True,
            ),
            (
                "conversation_started_populates_conversation_id",
                {
                    "type": "system",
                    "event_type": "conversation_started",
                    "conversation_id": "conv-7",
                },
                "conversation_id",
                "conv-7",
                True,
            ),
            (
                "unknown_event_ignored",
                {"type": "system", "event_type": "future_event", "value": "?"},
                None,
                None,
                False,
            ),
        ]
        for label, event, attr, expected, expected_changed in cases:
            with self.subTest(label=label):
                run = DockerAgentRun()
                changed = _apply_system_event(event, run=run)
                self.assertEqual(changed, expected_changed)
                if attr is None:
                    self.assertEqual(run, DockerAgentRun())
                else:
                    self.assertEqual(getattr(run, attr), expected)

    def test_repeat_event_does_not_report_change(self) -> None:
        """Applying the same ``run_started`` payload twice only reports a change once.

        Guards against a chatty CLI re-emitting the same event mid-run:
        the callback should fire on the first transition, not every time
        the JSON line happens to reappear.
        """
        run = DockerAgentRun()
        payload = {"type": "system", "event_type": "run_started", "run_id": "r", "run_url": "u"}
        self.assertTrue(_apply_system_event(payload, run=run))
        self.assertFalse(_apply_system_event(payload, run=run))


class IngestStdoutLineTest(unittest.TestCase):
    """JSON event parsing + callback throttling for streaming stdout."""

    def test_fires_on_event_only_for_tracked_state_changes(self) -> None:
        """``on_event`` is invoked once per *distinct* tracked field change.

        Feeds a realistic stream: one ``run_started``, one
        ``shared_session_established``, one repeat of the same
        ``run_started`` (no-op), and one noisy ``type="agent"`` line.
        The callback must fire exactly twice.
        """
        run = DockerAgentRun()
        observed: list[tuple[str, str]] = []

        def _on_event(current: DockerAgentRun) -> None:
            observed.append((current.run_id, current.session_link))

        run_started = json.dumps(
            {"type": "system", "event_type": "run_started", "run_id": "r1", "run_url": "u"}
        )
        session_established = json.dumps(
            {"type": "system", "event_type": "shared_session_established", "join_url": "link"}
        )
        agent_text = json.dumps({"type": "agent", "text": "reasoning..."})

        _ingest_stdout_line(run_started, run=run, on_event=_on_event)
        _ingest_stdout_line(session_established, run=run, on_event=_on_event)
        # Repeat should not fire the callback again (idempotent state).
        _ingest_stdout_line(run_started, run=run, on_event=_on_event)
        # Non-system events should not fire the callback at all.
        _ingest_stdout_line(agent_text, run=run, on_event=_on_event)

        self.assertEqual(observed, [("r1", ""), ("r1", "link")])
        self.assertEqual(run.run_id, "r1")
        self.assertEqual(run.session_link, "link")

    def test_ignores_non_json_and_non_system_lines(self) -> None:
        """Garbage lines + non-system event types never mutate *run*."""
        run = DockerAgentRun()
        _ingest_stdout_line("[INFO] spinning up container", run=run, on_event=None)
        _ingest_stdout_line("   \n", run=run, on_event=None)
        _ingest_stdout_line("null", run=run, on_event=None)
        _ingest_stdout_line(
            json.dumps({"type": "tool_call", "tool": "run_command"}),
            run=run,
            on_event=None,
        )
        self.assertEqual(run, DockerAgentRun())

    def test_callback_exception_does_not_propagate(self) -> None:
        """A raising ``on_event`` must not bubble out to the stdout drain."""
        run = DockerAgentRun()

        def _on_event(_: DockerAgentRun) -> None:
            raise RuntimeError("boom")

        _ingest_stdout_line(
            json.dumps(
                {"type": "system", "event_type": "run_started", "run_id": "r1", "run_url": "u"}
            ),
            run=run,
            on_event=_on_event,
        )
        self.assertEqual(run.run_id, "r1")


class FormatArgvForLogTest(unittest.TestCase):
    def test_masks_prompt_and_passes_the_rest_through(self) -> None:
        """Prompt value is replaced; every other arg survives verbatim."""
        argv = [
            "docker",
            "run",
            "-e",
            "WARP_API_KEY",
            "--prompt",
            "SECRET PROMPT CONTENT",
            "image",
            "agent",
            "run",
            "--share",
        ]
        self.assertEqual(
            _format_argv_for_log(argv),
            "docker run -e WARP_API_KEY --prompt <prompt bytes> image agent run --share",
        )


class ResolveTriageImageTest(unittest.TestCase):
    def test_image_resolution_table(self) -> None:
        cases = [
            ("respects_env_override", {"TRIAGE_IMAGE": "my-custom-triage"}, "my-custom-triage"),
            ("defaults_when_env_unset", {}, "oz-for-oss-triage"),
        ]
        for label, env_overrides, expected in cases:
            with self.subTest(label=label):
                with patch.dict(os.environ, env_overrides, clear=False):
                    if "TRIAGE_IMAGE" not in env_overrides:
                        os.environ.pop("TRIAGE_IMAGE", None)
                    self.assertEqual(resolve_triage_image(), expected)


class _FakeProcess:
    """Stand-in for :class:`subprocess.Popen` returns.

    stderr is ``None`` because production code now uses
    ``stderr=subprocess.STDOUT`` -- stderr is merged into stdout.
    """

    def __init__(self, stdout_lines: list[str], returncode: int = 0) -> None:
        self.stdout = io.StringIO("".join(stdout_lines))
        self.stderr = None
        self.returncode = returncode
        self.killed = False

    def kill(self) -> None:
        self.killed = True

    def wait(self) -> int:
        return self.returncode


class ReadOutputJsonTest(unittest.TestCase):
    """The internal ``_read_output_json`` helper used before tempdir cleanup."""

    def test_reads_and_parses_json(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "triage_result.json"
            path.write_text(json.dumps({"summary": "ok"}), encoding="utf-8")
            self.assertEqual(_read_output_json(path), {"summary": "ok"})

    def test_raises_when_file_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            with self.assertRaises(DockerAgentError):
                _read_output_json(Path(tmp) / "triage_result.json")

    def test_raises_when_not_json_object(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "triage_result.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaises(DockerAgentError):
                _read_output_json(path)


class RunAgentInDockerTest(unittest.TestCase):
    """Drive the full helper with a fake Popen to cover wiring + error paths.

    The fake ``tempfile.mkdtemp`` captures the output directory path so we
    can (a) pre-populate the expected result file, and (b) assert the
    directory is cleaned up by ``run_agent_in_docker``'s ``finally`` block.
    """

    def _stdout_lines(self) -> list[str]:
        return [
            json.dumps({"type": "system", "event_type": "run_started", "run_id": "oz-run-42", "run_url": "https://warp/run"}) + "\n",
            json.dumps({"type": "system", "event_type": "shared_session_established", "join_url": "https://warp/session"}) + "\n",
            json.dumps({"type": "agent", "text": "reasoning..."}) + "\n",
            json.dumps({"type": "skill_invoked", "name": "triage-issue"}) + "\n",
        ]

    def _run(
        self,
        *,
        stdout_lines: list[str],
        returncode: int = 0,
        write_output: bool = True,
        output_payload: dict | None = None,
    ) -> tuple[DockerAgentRun, list[DockerAgentRun], Path]:
        """Drive ``run_agent_in_docker`` against a fake subprocess.

        Returns the final ``DockerAgentRun``, the list of ``on_event``
        observations, and the path to the captured output dir so callers
        can assert cleanup behavior.
        """
        observed: list[DockerAgentRun] = []

        def _on_event(current: DockerAgentRun) -> None:
            observed.append(
                DockerAgentRun(
                    run_id=current.run_id,
                    session_link=current.session_link,
                    conversation_id=current.conversation_id,
                    output=dict(current.output),
                    exit_code=current.exit_code,
                )
            )

        output_dirs: list[Path] = []
        real_mkdtemp = docker_agent.tempfile.mkdtemp

        def _capturing_mkdtemp(*args: object, **kwargs: object) -> str:
            path = real_mkdtemp(*args, **kwargs)  # type: ignore[arg-type]
            output_dirs.append(Path(path))
            if write_output:
                payload = output_payload if output_payload is not None else {"summary": "ok"}
                (Path(path) / "triage_result.json").write_text(
                    json.dumps(payload), encoding="utf-8"
                )
            return path

        fake_proc = _FakeProcess(stdout_lines, returncode=returncode)
        with TemporaryDirectory() as repo_dir:
            with patch.object(docker_agent.tempfile, "mkdtemp", side_effect=_capturing_mkdtemp):
                with patch.object(docker_agent.subprocess, "Popen", return_value=fake_proc) as popen:
                    with patch.object(docker_agent.threading, "Timer") as timer_cls:
                        timer_cls.return_value = MagicMock()
                        run = run_agent_in_docker(
                            prompt="hello",
                            skill_name="triage-issue",
                            title="test",
                            image="oz-for-oss-triage",
                            repo_dir=repo_dir,
                            output_filename="triage_result.json",
                            on_event=_on_event,
                        )
                        self.assertTrue(popen.called)
        self.assertEqual(len(output_dirs), 1, "helper should mkdtemp exactly once")
        return run, observed, output_dirs[0]

    def test_happy_path_populates_output_and_cleans_up(self) -> None:
        run, observed, output_dir = self._run(
            stdout_lines=self._stdout_lines(),
            output_payload={"summary": "triaged", "labels": ["bug"]},
        )
        self.assertEqual(run.run_id, "oz-run-42")
        self.assertEqual(run.session_link, "https://warp/session")
        self.assertEqual(run.exit_code, 0)
        self.assertEqual(run.output, {"summary": "triaged", "labels": ["bug"]})
        # Cleanup always fires in the helper's ``finally`` block.
        self.assertFalse(output_dir.exists())
        # on_event fires only on state-changing system events.
        self.assertEqual(
            [(r.run_id, r.session_link) for r in observed],
            [("oz-run-42", ""), ("oz-run-42", "https://warp/session")],
        )

    def test_raises_on_nonzero_exit_and_still_cleans_up(self) -> None:
        output_dirs: list[Path] = []
        real_mkdtemp = docker_agent.tempfile.mkdtemp

        def _capturing_mkdtemp(*args: object, **kwargs: object) -> str:
            path = real_mkdtemp(*args, **kwargs)  # type: ignore[arg-type]
            output_dirs.append(Path(path))
            return path

        fake_proc = _FakeProcess(
            [
                json.dumps({"type": "system", "event_type": "run_started", "run_id": "r", "run_url": "u"}) + "\n",
            ],
            returncode=1,
        )
        with TemporaryDirectory() as repo_dir:
            with patch.object(docker_agent.tempfile, "mkdtemp", side_effect=_capturing_mkdtemp):
                with patch.object(docker_agent.subprocess, "Popen", return_value=fake_proc):
                    with patch.object(docker_agent.threading, "Timer") as timer_cls:
                        timer_cls.return_value = MagicMock()
                        with self.assertRaises(DockerAgentError):
                            run_agent_in_docker(
                                prompt="hello",
                                skill_name="triage-issue",
                                title="test",
                                image="oz-for-oss-triage",
                                repo_dir=repo_dir,
                                output_filename="triage_result.json",
                            )
        self.assertEqual(len(output_dirs), 1)
        self.assertFalse(output_dirs[0].exists())

    def test_raises_when_output_file_missing(self) -> None:
        """A successful container that forgets to write the result still errors cleanly."""
        with self.assertRaises(DockerAgentError):
            self._run(
                stdout_lines=self._stdout_lines(),
                write_output=False,
            )

    def test_missing_repo_dir_raises(self) -> None:
        with self.assertRaises(DockerAgentError):
            run_agent_in_docker(
                prompt="hello",
                skill_name="triage-issue",
                title="test",
                image="oz-for-oss-triage",
                repo_dir="/definitely/not/here",
                output_filename="triage_result.json",
            )

    def test_timeout_raises_and_cleans_up(self) -> None:
        """When the Timer fires before the process completes, we raise + clean up."""

        fake_proc = _FakeProcess([], returncode=0)

        def _timer_cls(_timeout: float, callback):  # type: ignore[no-untyped-def]
            timer = MagicMock()
            timer.start.side_effect = callback  # fire immediately
            return timer

        output_dirs: list[Path] = []
        real_mkdtemp = docker_agent.tempfile.mkdtemp

        def _capturing_mkdtemp(*args: object, **kwargs: object) -> str:
            path = real_mkdtemp(*args, **kwargs)  # type: ignore[arg-type]
            output_dirs.append(Path(path))
            return path

        with TemporaryDirectory() as repo_dir:
            with patch.object(docker_agent.tempfile, "mkdtemp", side_effect=_capturing_mkdtemp):
                with patch.object(docker_agent.subprocess, "Popen", return_value=fake_proc):
                    with patch.object(docker_agent.threading, "Timer", side_effect=_timer_cls):
                        with self.assertRaises(DockerAgentTimeout):
                            run_agent_in_docker(
                                prompt="hello",
                                skill_name="triage-issue",
                                title="test",
                                image="oz-for-oss-triage",
                                repo_dir=repo_dir,
                                output_filename="triage_result.json",
                                timeout_seconds=1,
                            )
        self.assertTrue(fake_proc.killed)
        self.assertEqual(len(output_dirs), 1)
        self.assertFalse(output_dirs[0].exists())


if __name__ == "__main__":
    unittest.main()
