import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from tests.helpers import GB, MB, SLEEPY, make_project, make_settings, shell, sleepy
from wyrd.launch import PlainLauncher, SystemdLauncher, kill_group, wait_step
from wyrd.sched import estimate, run_all
from wyrd.store import Store


def systemd_ok() -> bool:
    try:
        done = subprocess.run(
            ["systemd-run", "--user", "--scope", "--quiet", "true"],
            capture_output=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


class CountingLauncher(PlainLauncher):
    def __init__(self) -> None:
        self.count = 0

    def start(self, argv: list[str], env: dict[str, str], cwd: Path, mem_cap: int,
              log_out: Path, log_err: Path) -> "subprocess.Popen[bytes]":  # fmt: skip
        self.count += 1
        return super().start(argv, env, cwd, mem_cap, log_out, log_err)


class SchedBase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = Store(self.root / "wyrd.db")
        self.lines: list[str] = []

    def go(self, designs: dict[str, int], steps: list[Any], force: bool = False,
           launcher: Any = None, **changes: Any) -> dict[str, str]:  # fmt: skip
        project = make_project(self.root, designs, steps)
        return run_all(
            project, make_settings(**changes), self.store, force,
            launcher=launcher, log=self.lines.append,
        )  # fmt: skip


class WaitStepTest(unittest.TestCase):
    def start(self, *args: str) -> "subprocess.Popen[bytes]":
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        return PlainLauncher().start([SLEEPY, *args], dict(os.environ), d, GB, d / "o", d / "e")

    def test_peak_memory(self) -> None:
        res = wait_step(self.start("0", "100", "0"), 30)
        self.assertEqual((res.exit_code, res.outcome), (0, "ok"))
        self.assertGreaterEqual(res.peak_mem_bytes, 100 * MB)
        self.assertGreater(res.wall_s, 0)

    def test_nonzero_is_fail(self) -> None:
        res = wait_step(self.start("0", "0", "3"), 30)
        self.assertEqual((res.exit_code, res.outcome), (3, "fail"))

    def test_timeout(self) -> None:
        res = wait_step(self.start("30", "0", "0"), 1)
        self.assertEqual(res.outcome, "timeout")
        self.assertLess(res.wall_s, 15)

    @unittest.skipUnless(systemd_ok(), "systemd --user scope unavailable")
    def test_systemd_peak_is_the_command(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        proc = SystemdLauncher().start(
            [SLEEPY, "0", "150", "0"], dict(os.environ), d, 4 * GB, d / "o", d / "e"
        )
        res = wait_step(proc, 60, kill_is_oom=True)
        self.assertEqual(res.outcome, "ok")
        self.assertGreaterEqual(res.peak_mem_bytes, 150 * MB)
        self.assertLess(res.peak_mem_bytes, 600 * MB)


class PlainAsSystemd(SystemdLauncher):
    """Counts starts; runs plain, but the scheduler treats a SIGKILL as an oom."""

    def __init__(self) -> None:
        self.count = 0

    def start(self, argv: list[str], env: dict[str, str], cwd: Path, mem_cap: int,
              log_out: Path, log_err: Path) -> "subprocess.Popen[bytes]":  # fmt: skip
        self.count += 1
        return PlainLauncher().start(argv, env, cwd, mem_cap, log_out, log_err)


class FakeTimer:
    """Timer stand-in: start() runs the callback at once (or raises); cancel() is recorded."""

    on_cancel: Any = None
    run_now = False
    fail_start = False

    def __init__(self, interval: float, fn: Any, args: tuple[Any, ...] = ()) -> None:
        self.fn, self.args = fn, args
        self.daemon = False

    def start(self) -> None:
        if self.fail_start:
            raise RuntimeError("boom: cannot start new thread")
        if self.run_now and self.fn.__name__ == "expire":
            self.fn(*self.args)

    def cancel(self) -> None:
        if FakeTimer.on_cancel is not None:
            FakeTimer.on_cancel()


class WaitStepHardeningTest(unittest.TestCase):
    def start(self, *argv: str) -> "subprocess.Popen[bytes]":
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        return PlainLauncher().start(list(argv), dict(os.environ), d, GB, d / "o", d / "e")

    def setUp(self) -> None:
        FakeTimer.on_cancel, FakeTimer.run_now, FakeTimer.fail_start = None, False, False

    def test_timer_start_failure_kills_group(self) -> None:
        proc = self.start(SLEEPY, "30", "0", "0")
        FakeTimer.fail_start = True
        with (
            mock.patch("wyrd.launch.threading.Timer", FakeTimer),
            self.assertRaisesRegex(RuntimeError, "boom"),
        ):
            wait_step(proc, 30)
        with self.assertRaises(ProcessLookupError):
            os.killpg(proc.pid, 0)

    def test_returncode_set_right_after_wait4(self) -> None:
        proc = self.start(sys.executable, "-c", "pass")
        seen: list[Any] = []
        FakeTimer.on_cancel = lambda: seen.append(proc.returncode)
        with mock.patch("wyrd.launch.threading.Timer", FakeTimer):
            wait_step(proc, 30)
        self.assertEqual(seen[0], 0)

    def test_exit_zero_before_timeout_is_ok(self) -> None:
        proc = self.start(sys.executable, "-c", "pass")
        os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOWAIT)  # exited, not yet reaped
        FakeTimer.run_now = True
        with mock.patch("wyrd.launch.threading.Timer", FakeTimer):
            res = wait_step(proc, 30)
        self.assertEqual((res.exit_code, res.outcome), (0, "ok"))
        kill_group(proc, signal.SIGKILL)


class RunAllTest(SchedBase):
    def test_smallest_first(self) -> None:
        got = self.go({"big": 3000, "small": 10, "mid": 500}, [sleepy()])
        self.assertEqual(set(got.values()), {"ok"})
        rows = sorted(self.store.rows(), key=lambda r: str(r["started"]))
        self.assertEqual([r["design"] for r in rows], ["small", "mid", "big"])

    def test_budget_serialises(self) -> None:
        log = self.root / "times.log"
        code = (
            "import sys,time;f=open(sys.argv[1],'a');"
            "f.write('s %f\\n'%time.time());f.flush();time.sleep(0.6);"
            "f.write('e %f\\n'%time.time())"
        )
        step = shell(sys.executable, "-c", code, str(log))
        got = self.go({"a": 1, "b": 2}, [step], jobs=2, mem_budget=GB, other_mem=int(0.8 * GB))
        self.assertEqual(set(got.values()), {"ok"})
        marks = [line.split()[0] for line in sorted(
            log.read_text().splitlines(), key=lambda s: float(s.split()[1]))]  # fmt: skip
        self.assertEqual(marks, ["s", "e", "s", "e"])

    def test_parallel_when_budget_allows(self) -> None:
        log = self.root / "times.log"
        code = (
            "import sys,time;f=open(sys.argv[1],'a');"
            "f.write('s %f\\n'%time.time());f.flush();time.sleep(0.6);"
            "f.write('e %f\\n'%time.time())"
        )
        step = shell(sys.executable, "-c", code, str(log))
        self.go({"a": 1, "b": 2}, [step], jobs=2, mem_budget=8 * GB, other_mem=GB)
        marks = [line.split()[0] for line in sorted(
            log.read_text().splitlines(), key=lambda s: float(s.split()[1]))]  # fmt: skip
        self.assertEqual(marks, ["s", "s", "e", "e"])

    def test_fail_skips_later_steps(self) -> None:
        got = self.go({"a": 1}, [sleepy(code=3), sleepy()])
        (status,) = got.values()
        self.assertEqual(status, "fail")
        with self.store._connect() as conn:
            rows = conn.execute("SELECT n, exit_code FROM steps").fetchall()
        self.assertEqual(rows, [(0, 3)])

    def test_timeout_status(self) -> None:
        got = self.go({"a": 1}, [sleepy(seconds=5)], step_timeout=1)
        self.assertEqual(list(got.values()), ["timeout"])

    def test_reuse_ok_run(self) -> None:
        first = CountingLauncher()
        self.go({"a": 1, "b": 2}, [sleepy()], launcher=first)
        self.assertEqual(first.count, 2)
        second = CountingLauncher()
        got = self.go({"a": 1, "b": 2}, [sleepy()], launcher=second)
        self.assertEqual(second.count, 0)
        self.assertEqual(set(got.values()), {"ok"})

    def test_plan_line(self) -> None:
        self.go({"a": 1}, [sleepy(0)])
        self.assertEqual(self.lines[0], "plan: 1 to run, 0 reused")
        self.lines.clear()
        self.go({"a": 1}, [sleepy(0)])
        self.assertEqual(self.lines[0], "plan: 0 to run, 1 reused")

    def test_force_reruns(self) -> None:
        self.go({"a": 1}, [sleepy()])
        again = CountingLauncher()
        self.go({"a": 1}, [sleepy()], force=True, launcher=again)
        self.assertEqual(again.count, 1)

    def test_failed_run_is_retried(self) -> None:
        self.go({"a": 1}, [sleepy(code=1)])
        again = CountingLauncher()
        self.go({"a": 1}, [sleepy(code=1)], launcher=again)
        self.assertEqual(again.count, 1)

    def test_cmd_sh_replays(self) -> None:
        got = self.go({"a": 1}, [sleepy(code=3)])
        (key,) = got
        step_dir = next((self.root / "runs").rglob("0-shell"))
        for name in ("cmd.sh", "stdout.log", "stderr.log", "time.json"):
            self.assertTrue((step_dir / name).is_file(), name)
        replay = subprocess.run(["sh", str(step_dir / "cmd.sh")], capture_output=True)
        self.assertEqual(replay.returncode, 3)
        self.assertEqual(self.store.status(key), "fail")

    def test_over_budget_is_oom_at_once(self) -> None:
        got = self.go({"a": 1}, [sleepy()], mem_budget=GB, other_mem=2 * GB)
        self.assertEqual(list(got.values()), ["oom"])

    def test_metrics_recorded(self) -> None:
        code = "import sys;open(sys.argv[1]+'/metrics.json','w').write('{\"x\": 2}')"
        self.go({"a": 1}, [shell(sys.executable, "-c", code, "{step_dir}")])
        (row,) = self.store.rows()
        self.assertEqual(row["x"], 2.0)
        self.assertEqual(row["status"], "ok")

    def test_malformed_metrics_fail_the_run(self) -> None:
        code = "import sys;open(sys.argv[1]+'/metrics.json','w').write('{bad')"
        got = self.go({"a": 1}, [shell(sys.executable, "-c", code, "{step_dir}")])
        self.assertEqual(list(got.values()), ["fail"])
        tail = next((self.root / "runs").rglob("stderr.log")).read_text()
        self.assertIn("malformed JSON", tail)

    def test_missing_program_fails(self) -> None:
        got = self.go({"a": 1}, [shell("/nonexistent/prog")])
        self.assertEqual(list(got.values()), ["fail"])

    def test_sigint_cancels(self) -> None:
        timer = threading.Timer(1.0, lambda: os.kill(os.getpid(), signal.SIGINT))
        timer.start()
        self.addCleanup(timer.cancel)
        start = time.monotonic()
        got = self.go({"a": 1, "b": 2}, [sleepy(seconds=30)], jobs=1)
        self.assertLess(time.monotonic() - start, 20)
        self.assertEqual(list(got.values()), ["cancelled"])
        self.assertEqual({r["status"] for r in self.store.rows()}, {"cancelled"})


class SigintTest(SchedBase):
    def test_killed_by_cancel_is_cancelled_not_oom(self) -> None:
        launcher = PlainAsSystemd()
        timer = threading.Timer(1.0, lambda: os.kill(os.getpid(), signal.SIGINT))
        timer.start()
        self.addCleanup(timer.cancel)
        got = self.go({"a": 1}, [sleepy(seconds=30)], launcher=launcher)
        self.assertEqual(list(got.values()), ["cancelled"])
        self.assertEqual(launcher.count, 1)
        self.assertIsNone(self.store.peak_mem("a", "", "shell"))

    def test_previous_handler_none_restored_as_default(self) -> None:
        with mock.patch("wyrd.sched.signal.signal", return_value=None) as sig:
            self.go({"a": 1}, [sleepy()])
        restored = [c.args for c in sig.call_args_list[2:]]
        self.assertEqual(
            restored, [(signal.SIGINT, signal.SIG_DFL), (signal.SIGTERM, signal.SIG_DFL)]
        )
        self.assertEqual(len(sig.call_args_list), 4)

    def test_wait_failure_marks_fail_and_kills(self) -> None:
        with mock.patch("wyrd.launch.threading.Timer", FakeTimer):
            FakeTimer.fail_start = True
            self.addCleanup(setattr, FakeTimer, "fail_start", False)
            got = self.go({"a": 1}, [sleepy(seconds=30)])
        self.assertEqual(list(got.values()), ["fail"])
        self.assertTrue(any("RuntimeError: boom" in line for line in self.lines))


DRIVER = (
    "import sys, tempfile\n"
    "from pathlib import Path\n"
    "from tests.helpers import make_project, make_settings, shell\n"
    "from wyrd.sched import run_all\n"
    "from wyrd.store import Store\n"
    "root = Path(sys.argv[1])\n"
    "step = shell('sh', '-c', 'sleep 60 & echo $! > ' + sys.argv[2] + '; wait')\n"
    "project = make_project(root, {'a': 1}, [step])\n"
    "got = run_all(project, make_settings(), Store(root / 'wyrd.db'), False, log=lambda _l: None)\n"
    "sys.exit(0 if list(got.values()) == ['ok'] else 1)\n"
)


def _alive(pid: int) -> bool:
    try:
        text = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
    except OSError:
        return False
    return "State:\tZ" not in text


class SigtermTest(unittest.TestCase):
    def test_sigterm_leaves_no_grandchild(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        pidfile = Path(tmp.name) / "grandchild.pid"
        proc = subprocess.Popen(
            [sys.executable, "-c", DRIVER, tmp.name, str(pidfile)],
            cwd=Path(__file__).parent.parent,
        )
        self.addCleanup(proc.kill)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if pidfile.is_file() and pidfile.read_text(encoding="utf-8").strip():
                break
            time.sleep(0.05)
        grandchild = int(pidfile.read_text(encoding="utf-8").strip())
        self.addCleanup(lambda: _alive(grandchild) and os.kill(grandchild, signal.SIGKILL))
        proc.send_signal(signal.SIGTERM)
        self.assertEqual(proc.wait(timeout=20), 1)
        end = time.monotonic() + 5
        while _alive(grandchild) and time.monotonic() < end:
            time.sleep(0.05)
        self.assertFalse(_alive(grandchild))


class EstimateTest(SchedBase):
    def test_history_estimate_is_clamped_to_budget(self) -> None:
        self.go({"a": 1}, [sleepy(mb=50)])
        s = make_settings(mem_budget=GB, history_factor=1000.0)
        self.assertEqual(estimate(self.store, "a", "", "shell", False, s), GB)
        got = self.go({"a": 1}, [sleepy(mb=51)], mem_budget=GB, history_factor=1000.0)
        self.assertEqual(list(got.values()), ["ok"])

    def test_defaults_and_history(self) -> None:
        s = make_settings(vpr_mem=4 * GB, other_mem=2 * GB, history_factor=1.5)
        self.assertEqual(estimate(self.store, "a", "", "vpr", True, s), 4 * GB)
        self.assertEqual(estimate(self.store, "a", "", "abc", False, s), 2 * GB)
        self.go({"a": 1}, [sleepy(mb=50)])
        peak = self.store.peak_mem("a", "", "shell")
        assert peak is not None
        self.assertEqual(estimate(self.store, "a", "", "shell", False, s), int(peak * 1.5))


@unittest.skipUnless(systemd_ok(), "systemd --user scope unavailable")
class OomTest(SchedBase):
    def test_oom_status(self) -> None:
        got = self.go(
            {"a": 1}, [sleepy(seconds=2, mb=300)],
            launcher=SystemdLauncher(), other_mem=100 * MB,
        )  # fmt: skip
        self.assertEqual(list(got.values()), ["oom"])


if __name__ == "__main__":
    unittest.main()
