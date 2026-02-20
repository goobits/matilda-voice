#!/usr/bin/env python3
"""Unified test runner for Matilda Voice.

Runs unit tests (free/fast), integration tests (may need API keys), and e2e tests.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tomllib
from pathlib import Path
import venv


def _get_version() -> str:
    try:
        with open(Path(__file__).resolve().parents[1] / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        return str(data["project"]["version"])
    except Exception:
        return "unknown"


VERSION = _get_version()

REPO_ROOT = Path(__file__).resolve().parents[1]


def _test_env_python() -> Path:
    return REPO_ROOT / ".artifacts" / "test" / "test-env" / "bin" / "python"


def _ensure_test_env() -> None:
    """Ensure we run tests in a pinned, isolated env.

    This avoids leaking whatever pytest plugins happen to be installed globally,
    and keeps CI/dev output warning-free (without filtering warnings away).
    """
    if os.environ.get("MATILDA_VOICE_TEST_ENV") == "1":
        return

    py = _test_env_python()
    env_dir = py.parent.parent

    if not py.exists():
        env_dir.mkdir(parents=True, exist_ok=True)
        venv.EnvBuilder(with_pip=True, clear=False).create(env_dir)

    env = os.environ.copy()
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"

    # Note: Voice depends on `matilda-transport`, which isn't published to PyPI.
    transport_dir = REPO_ROOT.parent / "matilda-transport"
    if transport_dir.is_dir():
        subprocess.run(
            [str(py), "-m", "pip", "install", "-q", "--disable-pip-version-check", "-e", str(transport_dir)],
            env=env,
            check=False,
        )
    subprocess.run(
        [str(py), "-m", "pip", "install", "-q", "--disable-pip-version-check", "-e", ".[dev]"],
        cwd=str(REPO_ROOT),
        env=env,
        check=False,
    )

    os.environ["MATILDA_VOICE_TEST_ENV"] = "1"
    os.execv(str(py), [str(py), str(Path(__file__).resolve()), *sys.argv[1:]])


def show_examples():
    """Show comprehensive usage examples."""
    examples = """
🧪 MATILDA VOICE TEST RUNNER

BASIC USAGE:
  ./test.py                                    # Run unit tests (default)
  ./test.py unit                               # Run unit tests explicitly
  ./test.py integration                        # Run integration tests
  ./test.py e2e                                # Run end-to-end tests
  ./test.py all                                # Run all test types

OPTIONS:
  ./test.py --coverage                         # Generate coverage report
  ./test.py -c                                 # Short form for coverage
  ./test.py --verbose                          # Verbose output
  ./test.py --sequential                       # Force sequential test execution
  ./test.py --parallel                         # Run tests in parallel (auto workers)
  ./test.py --parallel 4                       # Run tests with 4 workers
  ./test.py --test test_edge                   # Run specific test pattern
  ./test.py --markers "not slow"               # Filter by markers
  ./test.py --force                            # Skip confirmation prompts

EXAMPLES:
  ./test.py unit --coverage --verbose          # Unit tests with coverage
  ./test.py unit --parallel                    # Fast parallel unit tests
  ./test.py integration --force                # Integration tests, no prompt
  ./test.py e2e --force                        # E2E tests, no prompt
  ./test.py all --force                        # All tests, no prompts

COST INFORMATION:
  - Unit tests: FREE (uses mocked API calls)
  - Integration tests: May require API keys (ElevenLabs, OpenAI, Google)
  - E2E tests: Requires network and provider access

API KEYS (for integration/e2e):
  - OPENAI_API_KEY
  - ELEVENLABS_API_KEY
  - GOOGLE_API_KEY or GOOGLE_CLOUD_API_KEY
"""
    print(examples)


def check_api_keys():
    """Check for available API keys and print status."""
    keys_found = []

    if os.environ.get("OPENAI_API_KEY"):
        print("✅ OpenAI API key found")
        keys_found.append("OpenAI")

    if os.environ.get("ELEVENLABS_API_KEY"):
        print("✅ ElevenLabs API key found")
        keys_found.append("ElevenLabs")

    if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GOOGLE_CLOUD_API_KEY"):
        print("✅ Google API key found")
        keys_found.append("Google")

    if not keys_found:
        print("⚠️  No API keys found")
        print("Some tests may be skipped. Set one or more of:")
        print("  - OPENAI_API_KEY")
        print("  - ELEVENLABS_API_KEY")
        print("  - GOOGLE_API_KEY")
        return False
    return True


def check_virtual_env():
    """Check if running in a virtual environment."""
    if os.environ.get("VIRTUAL_ENV"):
        venv_name = os.path.basename(os.environ["VIRTUAL_ENV"])
        print(f"✅ Virtual environment: {venv_name}")
    elif os.path.exists(".venv"):
        print("💡 Virtual environment available but not activated")
        print("   Consider running: source .venv/bin/activate")


def check_xdist():
    """Check if pytest-xdist is available."""
    import importlib.util

    return importlib.util.find_spec("xdist") is not None


def build_pytest_cmd(args, test_type):
    """Build the pytest command based on arguments and test type."""
    cmd = [sys.executable, "-m", "pytest"]

    # Test path or pattern
    if args.test:
        cmd.extend(["tests/", "-k", args.test])
    elif test_type == "unit":
        cmd.append("tests/unit/")
    elif test_type == "integration":
        cmd.append("tests/integration/")
    elif test_type == "e2e":
        cmd.extend(["tests/e2e/", "-m", "e2e"])
    else:
        cmd.append("tests/")

    # Markers
    if args.markers:
        cmd.extend(["-m", args.markers])

    # Verbose
    if args.verbose:
        cmd.append("-v")

    # Coverage
    if args.coverage:
        cmd.extend(["--cov=matilda_voice", "--cov-report=term-missing", "--cov-report=html:.temp/htmlcov"])
        print("📊 Coverage report will be generated in .temp/htmlcov/")

    # Parallel execution
    if args.parallel != "off":
        if check_xdist():
            workers = "auto" if args.parallel == "auto" else args.parallel
            cmd.extend(["-n", workers])
            print(f"🚀 Running tests in parallel ({workers} workers)")
        else:
            print("⚠️  pytest-xdist not installed, running sequentially")
            print("   Install with: pip install pytest-xdist")

    # Common options
    cmd.extend(["--tb=short", "--durations=10"])

    return cmd


def run_tests(cmd):
    """Run pytest with the given command."""
    print(f"Running: {' '.join(cmd)}")
    print()
    result = subprocess.run(cmd)
    return result.returncode


def run_unit_tests(args):
    """Run unit tests."""
    print("🧪 Running Unit Tests")
    print("=" * 40)
    print()

    cmd = build_pytest_cmd(args, "unit")
    exit_code = run_tests(cmd)

    print()
    if exit_code == 0:
        print("✅ Unit tests passed!")
        if args.coverage:
            print("📊 Coverage report: .temp/htmlcov/index.html")
    else:
        print(f"❌ Unit tests failed (exit code: {exit_code})")

    return exit_code


def run_integration_tests(args):
    """Run integration tests."""
    print("🧪 Running Integration Tests")
    print("=" * 40)
    print()

    check_api_keys()
    print()

    print("⚠️  These tests may make real API calls if keys are configured")
    print()

    if not args.force:
        try:
            response = input("Continue with integration tests? [y/N]: ").strip().lower()
            if response != "y":
                print("Integration tests cancelled.")
                return 0
        except (EOFError, KeyboardInterrupt):
            print("\nIntegration tests cancelled.")
            return 0

    print()
    cmd = build_pytest_cmd(args, "integration")
    exit_code = run_tests(cmd)

    print()
    if exit_code == 0:
        print("✅ Integration tests passed!")
    else:
        print(f"❌ Integration tests failed (exit code: {exit_code})")

    return exit_code


def run_e2e_tests(args):
    """Run end-to-end tests."""
    print("🧪 Running E2E Tests")
    print("=" * 40)
    print()

    check_api_keys()
    print()

    print("⚠️  E2E tests require network access and provider availability")
    print()

    if not args.force:
        try:
            response = input("Continue with e2e tests? [y/N]: ").strip().lower()
            if response != "y":
                print("E2E tests cancelled.")
                return 0
        except (EOFError, KeyboardInterrupt):
            print("\nE2E tests cancelled.")
            return 0

    print()
    cmd = build_pytest_cmd(args, "e2e")
    exit_code = run_tests(cmd)

    print()
    if exit_code == 0:
        print("✅ E2E tests passed!")
    else:
        print(f"❌ E2E tests failed (exit code: {exit_code})")

    return exit_code


def main():
    """Main entry point."""
    _ensure_test_env()

    # Custom help
    if len(sys.argv) == 2 and sys.argv[1] in ["-h", "--help"]:
        show_examples()
        return 0

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "command",
        nargs="?",
        default="unit",
        choices=["unit", "integration", "e2e", "all", "help"],
        help="Test type to run",
    )
    parser.add_argument("--coverage", "-c", action="store_true", help="Generate coverage report")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose test output")
    parser.add_argument("--sequential", action="store_true", help="Force sequential execution")
    parser.add_argument(
        "--parallel",
        "-p",
        nargs="?",
        const="auto",
        default="off",
        help="Run tests in parallel (N workers, default: auto)",
    )
    parser.add_argument("--test", "-t", help="Run specific test file or pattern")
    parser.add_argument("--markers", "-m", help="Run tests matching marker expression")
    parser.add_argument("--force", "-f", action="store_true", help="Skip confirmation prompts")
    parser.add_argument("--version", action="store_true", help="Show version")

    args = parser.parse_args()

    if args.sequential:
        args.parallel = "off"

    if args.version:
        print(f"Matilda Voice Test Runner v{VERSION}")
        return 0

    if args.command == "help":
        show_examples()
        return 0

    print(f"🧪 Matilda Voice Test Runner v{VERSION}")
    print("=" * 40)
    print()

    check_virtual_env()
    print()

    # Check pytest is available
    import importlib.util

    if importlib.util.find_spec("pytest") is None:
        print("❌ pytest not found!")
        print("Install with: pip install pytest pytest-asyncio pytest-cov")
        return 1

    if args.command == "unit":
        return run_unit_tests(args)
    elif args.command == "integration":
        return run_integration_tests(args)
    elif args.command == "e2e":
        return run_e2e_tests(args)
    elif args.command == "all":
        print("Running all test types...")
        print()

        exit_code = run_unit_tests(args)
        if exit_code != 0:
            print()
            print("❌ Unit tests failed! Skipping remaining tests.")
            return exit_code

        print()
        args.force = True  # Skip prompts for subsequent tests

        exit_code = run_integration_tests(args)
        if exit_code != 0:
            print()
            print("❌ Integration tests failed! Skipping e2e tests.")
            return exit_code

        print()
        exit_code = run_e2e_tests(args)

        if exit_code == 0:
            print()
            print("🎉 All tests passed!")

        return exit_code

    return 0


if __name__ == "__main__":
    sys.exit(main())
