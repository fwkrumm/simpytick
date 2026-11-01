# SimPyTick

Simple Python Tick: periodic events using a spawn-isolated process or a thread.
Requires Python 3.10 or later. Runtime dependencies: `psutil` and `coloredlogs`.

## Release Status

Releases before `1.0.0` are testing versions and may introduce breaking changes
without a major version increment. Semantic versioning will begin with `1.0.0`.

## Installation

```shell
pip install SimPyTick
```

From a checkout of this package:

```shell
uv pip install .
```

## Usage

```python
from simpytick.timer import TimedEvent


def main():
	with TimedEvent(s=0.01, n=100, backend="thread") as ticks:
		for tick in ticks:
			print(tick)


if __name__ == "__main__":
	main()
```

`TimedEvent(s, n, compensation=True, logger=None, backend="process")` uses a
finite, positive period `s` and an integer count `n`. Booleans are not accepted
as periods or counts. `n=-1` runs indefinitely; `n=0` yields no ticks. Invalid
arguments raise `TypeError` or `ValueError` before any worker is created. Exiting the
context terminates and joins the process, or signals and joins the thread.
The first tick is emitted immediately; subsequent ticks use the given interval.

The default process backend uses multiprocessing's `spawn` context. Keep process
creation behind `if __name__ == "__main__":` in an importable script. Both backends
retain normal OS priority; the package does not request real-time scheduling or
require priority-changing privileges. Failed startup cleans up any started worker
and its status connections. Use `backend="thread"` to
avoid child creation after libraries start threads or open pollers.

Background failures raise `RuntimeError` during iteration or normal context exit,
even without a logger. Reported exceptions include their type and a bounded message;
abrupt exits without completion are also errors. Health-check waits are capped at
100 ms, subject to OS scheduling. Application exceptions remain primary during
cleanup. Normal completion with collapsed event signals still ends iteration early.

The low-level API keeps its positional arguments and validates `n` and `s` using
the same rules:

```python
import threading
from simpytick.timer import timer

event = threading.Event()
timer(3, 0.01, event, False, None)
```

`timer(n, s, event, enable_compensation=True, logger_level=None, *,
stop_event=None)` sets the supplied event. Consumers clear it after each tick;
multiple unconsumed signals can collapse into one. This low-level call blocks
until completion. The first tick fires immediately. With compensation enabled,
a persistent monotonic schedule corrects accumulated drift by shortening waits,
including zero waits to catch up after missed deadlines. With compensation
disabled, each tick is followed by a fixed interval wait. This is not a hard
real-time scheduler, and slow consumers may miss ticks. Compensation no longer
restricts the number of decimal places in the period; this does not guarantee
that the operating system can achieve very short intervals.

## Sleep

```python
import threading
import simpytick

simpytick.sleep(0.01)

stop = threading.Event()
interrupted = simpytick.sleep(1.0, stop_event=stop, check_interval=0.01)
```

`simpytick.sleep(seconds, *, stop_event=None, check_interval=0.01)` returns
`True` if cancelled and `False` when the wait completes. Another thread can
request cancellation with `stop.set()`. Without a stop event it uses a single
`time.sleep()` call; otherwise it sleeps in chunks, checking the stop flag
between them. `seconds` must be finite and nonnegative; `check_interval` must
be finite and positive.

An active sleep cannot be interrupted. Cancellation latency depends on the
chunk size and OS scheduling, so `check_interval` is not a guaranteed bound.
Monotonic deadlines account for chunk overhead without busy-waiting. Separate
calls do not share a schedule or compensate for work between calls; use
`sleep_2` or `TimedEvent` for periodic drift compensation. Exact wake-up times are not
guaranteed.

### Compensated Sleep

```python
import time
from simpytick import sleep_2

sleep = sleep_2()
for _ in range(100):
	sleep(0.01)
	print(time.time())
```

Create the callable once outside the loop. It runs in the calling thread, with
no background thread or process. Its monotonic schedule starts on the first
call; subsequent calls advance the deadline by the supplied seconds, accounting
for work and oversleep between calls. Overdue deadlines produce zero waits
until caught up. Use a separate instance for each loop; instances are not
thread-safe.

Calls accept the same `stop_event` and `check_interval` keyword arguments and
return the same cancellation flag as `simpytick.sleep()`. Cancellation resets the
schedule; `sleep.reset()` also makes the next call start a new schedule. Exact
wake-up times and immediate cancellation are not guaranteed.

## Migration Scope

`SimPyTickLogger` adapts standard named loggers and supports the custom `iinfo()`
and `idebug()` methods, handler and level access, and adapter caching. Imports do
not change the global logger class or register level names; explicit
`get_logger()` calls register custom levels and configure output. The package
installs a `NullHandler` for application-controlled logging. By default, file
output goes to `simpytickLogs` under the system temporary directory.

Tests cover timer APIs, lifecycle and worker failures, logger import isolation,
and matching runtime and distribution versions. Spawn-worker tests exercise
actual processes without mocking priority setup.

Distribution name: `SimPyTick`. Import namespace: `simpytick`. Initial
standalone version: `0.0.1`. Original BSD-3-Clause license and attribution remain.

## Development

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run
from this repository's root. Python 3.14 matches the mandatory CI lint runtime:

```shell
uv venv --python 3.14
uv pip install -e . -r requirements-dev.txt
```

No environment activation is needed for `uv run`. The editable install makes
local source changes available without reinstalling. Run the CI unit check
(including coverage) and lint check:

```shell
uv run python .github/scripts/run_checks.py unit
uv run python .github/scripts/run_checks.py lint
```

Run a single test module while iterating, then build and validate distributions:

```shell
uv run python -m unittest tests.test_sleep
uv build
uvx twine check dist/*
```

Contributor and agent context is in [AGENTS.md](AGENTS.md). Add regression tests
for behavior changes; test and lint before opening a pull request. Worker changes
must also pass the spawned-process tests in the full unit suite.

`requirements-dev.txt` includes `-r requirements.txt` and adds development-only
`pylint==4.0.10` and `coverage>=7.10,<8`; these tools are not published as runtime
dependencies. CI reports coverage without a minimum. Pylint keeps its default
fail-under of 10, with no disabled messages or explicit custom threshold.

`requirements.txt` contains runtime-only dependencies and mirrors
`pyproject.toml` project dependencies. The workflows use it before tests, build,
and publication preflight; the requirements guard test detects drift, so update
both files together. PDM's declared build backend supplies `uv build` build
dependencies, while the generated wheel and source-distribution metadata causes
pip installs to resolve runtime dependencies automatically. The requirements
file is included in source distributions. `MANIFEST.in` is unnecessary; source
distributions also include tests and workflows. No protobuf generation or
parent-project build hook is used.

## CI and Publication

The workflows assume this directory is the root of its own GitHub repository.
While nested in the original repository, GitHub does not discover these workflows.

- `test.yml`: mandatory Python 3.10-3.14 tests on `ubuntu-latest`,
	`windows-latest`, `macos-latest`, `ubuntu-22.04-arm`, and `ubuntu-24.04-arm`,
	plus nonblocking `3.x` probes on the same five runners; coverage run/report
	has no minimum.
- `pylint.yml`: Python 3.14 / Ubuntu, Pylint 4.0.10, `--jobs=1 simpytick tests`.
- `build.yml`: additional Ubuntu / Python 3.14 preflight, wheel/sdist build,
	Twine checks, isolated installed-artifact smoke tests, and artifact upload.
- `weekly-latest-python.yml`: Monday at 12:00 UTC and manual runs; nonblocking
	`3.x` unit probes on the same five runners and Ubuntu lint with latest Pylint.
- `verify-workflows.yml`: reference-equivalent actionlint syntax/expression
	checks and zizmor security audit.
- `pypi_publish.yml`: pushes to `master`, not GitHub Release publication. A read-only
	build job runs preflight tests, build, Twine and wheel/sdist smoke checks, then
	uploads validated artifacts. Its dependent `pypi-release` environment job
	publishes them using OIDC with `skip-existing: true`, `print-hash: false`, and
	`attestations: true`, without stored API tokens.

After publication succeeds, an annotated `v<version>` tag is created from
`simpytick/_version.py`. An existing tag on the same commit is an idempotent
no-op; a tag on a different commit is never moved and causes failure. Set the
version constant manually before a new release. No automatic version bump or
semantic-version inference from commits or tags occurs; tags are output, not
the version source. PDM reads the same file for distribution metadata, and
`simpytick.__version__` imports it at runtime.

Before publishing, configure the PyPI project `SimPyTick` with a trusted
publisher matching your GitHub owner/repository, workflow `pypi_publish.yml`, and
environment `pypi-release`. Keep the workflow filename to preserve that identity
and retain the environment URL `https://pypi.org/project/SimPyTick/`. Confirm PyPI
name availability and select an unpublished version before pushing. Skipping
existing files supports retries, not replacement of published artifacts.

There is no full-matrix mandatory CI `needs` barrier before publishing, matching
the reference. Require supported-version tests, lint, build and workflow audit
checks through `master` branch protection; configure environment reviewers and
allowed branches. Do not require floating `3.x` probes as support guarantees.
See [.github/CI.md](.github/CI.md) for CI ownership, reference differences,
and justified deviations.

# Todos

## AI Findings

Remaining Medium/Low findings from the pre-publication review. High-severity
findings were addressed separately; these items remain open.

- [ ] **Medium - Tick delivery and overrun accounting (review #7):** Define whether
	delivery coalesces, skips, or guarantees ticks. Reconcile the exactly-`n` example
	with missed signals, implement accurate `overrun_count` and sequence accounting,
	and test consumers that span several periods. Avoid an unbounded queue.
- [ ] **Medium - Context lifecycle (review #8):** Reject repeated/nested entry or
	implement a fully reset lifecycle. Define iteration outside an active context;
	test re-entry, nested entry, and reuse after thread shutdown.
- [ ] **Medium - Scheduling scalability (review #9):** Define catch-up/skip policy
	and bound catch-up bursts. Benchmark CPU use, jitter, startup, and shutdown over
	increasing timer counts; assess chunked cancellation wakeups and worker-per-timer
	overhead before making high-precision or scalability claims.
- [ ] **Medium - Log-file path safety (review #10):** Separate logger identity from
	filenames, validate filenames, and use an application-owned directory. Make file
	output opt-in and address path traversal and shared-temporary-directory symlinks.
- [ ] **Medium - Log retention and writers (review #11):** Use a stable log basename
	so retention works across daily restarts. Give rotation a single owner for
	multiprocess use, such as a `QueueListener`; test retention and concurrent writers.
- [ ] **Medium - Release gates (review #12):** Make publication depend on the full
	supported OS/Python test matrix and validated distributions for the release
	commit. Check the release tag against the distribution version.
- [ ] **Medium - Dependency and supply-chain validation (review #13):** Commit a
	development lockfile, lock release tooling, test minimum and current runtime
	dependencies, add scheduled advisory audits, and pin the publishing action to a
	verified commit SHA. Reassess the now-unused `psutil` dependency after removing
	automatic priority changes.
- [ ] **Low - Packaged development output (review #14):** Exclude or remove
	`simpytick/results.txt` from distributions. Keep reproducible benchmark methods and
	meaningful results outside the import package, and inspect wheel/sdist contents.