from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parents[1] / "dev-agent-toolkit"


@unittest.skipUnless(Path("/bin/bash").is_file(), "requires Bash")
class SetupLauncherTests(unittest.TestCase):
    def test_uv_operations_forward_only_the_selected_command(self) -> None:
        with tempfile.TemporaryDirectory(prefix="uv launcher ") as directory:
            root = Path(directory).resolve()
            uv = root / "uv"
            uv.write_text(
                "#!/bin/bash\nprintf '%s\\0' \"$@\"\nexit 23\n", encoding="utf-8"
            )
            uv.chmod(0o755)
            install = ["tool", "install", "--managed-python"]
            server_build = [
                "build",
                "--managed-python",
                str(LAUNCHER.parent / "mcp-server"),
                "--out-dir",
                str(LAUNCHER.parent / "dist"),
            ]
            for operation, options, command in (
                ("--mcp-server-build", ["--wheel"], server_build),
                ("--uv-build", ["--wheel"], server_build),
                (
                    "--mcp-server-install",
                    ["--force", "dist with spaces/package.whl"],
                    install,
                ),
                (
                    "--uv-tool-install",
                    ["--force", "dist with spaces/package.whl"],
                    install,
                ),
                (
                    "--mcp-client-build",
                    ["--wheel"],
                    [
                        "build",
                        "--managed-python",
                        str(LAUNCHER.parent / "mcp-client"),
                        "--out-dir",
                        str(LAUNCHER.parent / "dist"),
                    ],
                ),
                (
                    "--mcp-client-install",
                    ["--force", "dist with spaces/client.whl"],
                    install,
                ),
            ):
                with self.subTest(operation=operation):
                    result = subprocess.run(
                        [str(LAUNCHER), operation, *options],
                        cwd=root,
                        env={**os.environ, "PATH": f"{root}:/usr/bin:/bin"},
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 23, result.stderr)
                    self.assertEqual(
                        result.stdout.decode().split("\0")[:-1], [*command, *options]
                    )

    def test_default_tool_install_requires_the_current_project_wheel(self) -> None:
        with tempfile.TemporaryDirectory(prefix="uv launcher ") as directory:
            root = Path(directory).resolve()
            checkout = root / "checkout with spaces"
            dist = checkout / "dist"
            dist.mkdir(parents=True)
            launcher = checkout / LAUNCHER.name
            shutil.copy2(LAUNCHER, launcher)
            uv = root / "uv"
            uv.write_text(
                "#!/bin/bash\n"
                'if [ "$1" = version ]; then\n'
                '    [[ $# -eq 4 && "$2" == --short && "$3" == --project &&\n'
                '       "$4" == "$EXPECTED_PROJECT" ]] || exit 19\n'
                '    printf "%s\\n" "$PROJECT_VERSION"\n'
                "else\n"
                '    printf "%s\\0" "$@"\n'
                "fi\n",
                encoding="utf-8",
            )
            uv.chmod(0o755)
            (dist / "dev_agent_toolkit_tools-2.3.3-py3-none-any.whl").touch()
            (dist / "dev_agent_toolkit_mcp_client-5.6.6-py3-none-any.whl").touch()
            projects = (
                (
                    "mcp-server",
                    "2.3.4rc1",
                    "dev_agent_toolkit_tools",
                    ("--mcp-server-install", "--uv-tool-install"),
                    "--mcp-server-build",
                ),
                (
                    "mcp-client",
                    "5.6.7",
                    "dev_agent_toolkit_mcp_client",
                    ("--mcp-client-install",),
                    "--mcp-client-build",
                ),
            )
            for project, version, package, install_options, build in projects:
                env = {
                    **os.environ,
                    "PATH": f"{root}:/usr/bin:/bin",
                    "EXPECTED_PROJECT": str(checkout / project),
                    "PROJECT_VERSION": version,
                }
                wheel = dist / f"{package}-{version}-py3-none-any.whl"
                for install in install_options:
                    command = [str(launcher), install]
                    with self.subTest(install=install, wheel="missing"):
                        result = subprocess.run(
                            command, cwd=root, env=env, capture_output=True, check=False
                        )
                        self.assertEqual(result.returncode, 1)
                        self.assertIn(
                            f"./dev-agent-toolkit {build}".encode(), result.stderr
                        )
                        self.assertEqual(result.stdout, b"")

                    wheel.touch()
                    for options in ([], ["--force"]):
                        with self.subTest(install=install, options=options):
                            result = subprocess.run(
                                [*command, *options],
                                cwd=root,
                                env=env,
                                capture_output=True,
                                check=False,
                            )
                            self.assertEqual(result.returncode, 0, result.stderr)
                            self.assertEqual(
                                result.stdout.decode().split("\0")[:-1],
                                [
                                    "tool",
                                    "install",
                                    "--managed-python",
                                    *options,
                                    str(wheel),
                                ],
                            )
                    wheel.unlink()

    def test_help_groups_server_and_client_commands_by_distribution(self) -> None:
        result = subprocess.run(
            [str(LAUNCHER), "--help"],
            capture_output=True,
            check=False,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        server_help, client_help = result.stdout.split(
            "dev_agent_toolkit_mcp_client（MCP Client CLI）", 1
        )
        self.assertIn("dev_agent_toolkit_tools（MCP Server）", server_help)
        self.assertIn("--mcp-server-build", server_help)
        self.assertIn("--mcp-server-install", server_help)
        self.assertIn("--mcp-client-build", client_help)
        self.assertIn("--mcp-client-install", client_help)
        self.assertIn("--codex-mcp-client-install", client_help)

    def test_codex_client_setup_installs_from_source_and_verifies_the_cli(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codex client setup ") as directory:
            root = Path(directory).resolve()
            bin_dir = root / "tool bin"
            bin_dir.mkdir()
            log = root / "calls"
            uv = root / "uv"
            uv.write_text(
                "#!/bin/bash\n"
                'if [[ "$1" == run ]]; then\n'
                '    [[ "$2" == --managed-python && "$3" == -- ]] || exit 19\n'
                "    shift 3\n"
                '    exec "$SETUP_PYTHON" "$@"\n'
                "fi\n"
                'printf "%s\\0" "$@" >> "$CALL_LOG"\n'
                'case "$1 $2" in\n'
                '    "tool install") exit "$INSTALL_STATUS" ;;\n'
                '    "tool dir") printf "%s\\n" "$TOOL_BIN" ;;\n'
                "    *) exit 19 ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            cli = bin_dir / "dev_agent_toolkit_mcp_client_cli"
            cli.write_text(
                '#!/bin/bash\nprintf "%s\\0" "${0##*/}" "$@" >> "$CALL_LOG"\n'
                'printf "usage: %s [-h]\\n" "${0##*/}"\n',
                encoding="utf-8",
            )
            for path in (uv, cli):
                path.chmod(0o755)
            codex_home = root / "codex"
            env = {
                **os.environ,
                "PATH": f"{root}:/usr/bin:/bin",
                "SETUP_PYTHON": sys.executable,
                "TOOL_BIN": str(bin_dir),
                "CALL_LOG": str(log),
                "CODEX_HOME": str(codex_home),
            }
            source = str(LAUNCHER.parent / "mcp-client")
            install = ["tool", "install", "--managed-python"]
            package = ["--reinstall-package", "dev-agent-toolkit-mcp-client", source]
            verify = ["tool", "dir", "--bin", cli.name, "--help"]
            for options, install_status, status, expected in (
                (["--help"], 0, 0, []),
                (["--dry-run"], 0, 0, []),
                ([], 0, 0, [*install, *package, *verify]),
                (["--force"], 0, 0, [*install, "--force", *package, *verify]),
                ([], 23, 1, [*install, *package]),
            ):
                with self.subTest(options=options, install_status=install_status):
                    log.write_bytes(b"")
                    result = subprocess.run(
                        [
                            "/bin/bash",
                            str(LAUNCHER),
                            "--codex-mcp-client-install",
                            *options,
                        ],
                        cwd=root,
                        env={**env, "INSTALL_STATUS": str(install_status)},
                        capture_output=True,
                        check=False,
                        encoding="utf-8",
                    )
                    self.assertEqual(result.returncode, status, result.stderr)
                    self.assertEqual(
                        log.read_bytes().decode().split("\0")[:-1], expected
                    )
                    self.assertFalse(codex_home.exists())
                    if options == ["--dry-run"]:
                        self.assertIn(source, result.stdout)
                    if expected and status == 0:
                        self.assertIn(str(cli), result.stdout)

    def test_mcp_client_uses_the_installed_cli_and_preserves_invocation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mcp client launcher ") as directory:
            root = Path(directory).resolve()
            bin_dir = root / "installed tools"
            bin_dir.mkdir()
            uv = root / "uv"
            uv.write_text(
                '#!/bin/bash\n[ "$*" = "tool dir --bin" ] || exit 99\n'
                'printf "%s\\n" "$TOOL_BIN"\n',
                encoding="utf-8",
            )
            executable = "dev_agent_toolkit_mcp_client_cli"
            decoy = root / executable
            decoy.write_text("#!/bin/bash\nexit 98\n", encoding="utf-8")
            for path in (uv, decoy):
                path.chmod(0o755)
            env = {
                **os.environ,
                "PATH": f"{root}:/usr/bin:/bin",
                "TOOL_BIN": str(bin_dir),
            }
            arguments = ["--registry", "a b/*.json", "request", "local", "tools/call"]
            command = [str(LAUNCHER), "--mcp-client", *arguments]

            missing = subprocess.run(
                command, cwd=root, env=env, capture_output=True, check=False
            )
            self.assertEqual(missing.returncode, 1)
            self.assertIn(b"--mcp-client-install", missing.stderr)
            self.assertEqual(missing.stdout, b"")

            cli = bin_dir / executable
            cli.write_text(
                '#!/bin/bash\nprintf "%s\\0" "$(pwd -P)" "$@"\nexit 24\n',
                encoding="utf-8",
            )
            cli.chmod(0o755)
            result = subprocess.run(
                command, cwd=root, env=env, capture_output=True, check=False
            )
            self.assertEqual(result.returncode, 24, result.stderr)
            self.assertEqual(
                result.stdout.decode().split("\0")[:-1], [str(root), *arguments]
            )

    def test_python_lookup_failure_does_not_fall_back_to_installed_manager(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            uv = root / "uv"
            uv.write_text("#!/bin/bash\nexit 19\n", encoding="utf-8")
            uv.chmod(0o755)
            cli = root / "dev-agent-toolkit"
            cli.write_text("#!/bin/bash\nexit 99\n", encoding="utf-8")
            cli.chmod(0o755)
            result = subprocess.run(
                [str(LAUNCHER), "--skills-update", "--dry-run"],
                env={**os.environ, "PATH": f"{root}:/usr/bin:/bin"},
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 19, result.stderr)

    def test_document_operations_run_checkout_python_without_installing_tools(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            checkout = root / "checkout with spaces"
            checkout.mkdir()
            launcher = checkout / LAUNCHER.name
            shutil.copy2(LAUNCHER, launcher)
            uv = root / "uv"
            uv.write_text(
                "#!/bin/bash\n"
                'printf "%s\\0" "$@" >> "$CALL_LOG"\n'
                'printf "%s\\n" "$DOCUMENT_PYTHON"\n',
                encoding="utf-8",
            )
            python = root / "document python"
            python.write_text(
                '#!/bin/bash\nprintf "%s\\0" "$PYTHONPATH" "$@"\nexit 24\n',
                encoding="utf-8",
            )
            for executable in (uv, python):
                executable.chmod(0o755)
            log = root / "calls"
            environment = {
                **os.environ,
                "PATH": f"{root}:/usr/bin:/bin",
                "CALL_LOG": str(log),
                "DOCUMENT_PYTHON": str(python),
            }
            for operation, command, options in (
                ("--skills-install", ["skills", "install"], ["--target", "a b/*"]),
                ("--skills-update", ["skills", "update"], ["--dry-run"]),
                ("--skills-show", ["skills", "show"], []),
                ("--agents-install", ["agents", "update"], ["--help"]),
                (
                    "--agents-update",
                    ["agents", "update"],
                    ["--source", "a b/*;$(echo x)"],
                ),
                ("--agents-show", ["agents", "show"], []),
            ):
                with self.subTest(operation=operation):
                    log.write_bytes(b"")
                    result = subprocess.run(
                        ["/bin/bash", str(launcher), operation, *options],
                        cwd=root,
                        env=environment,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 24, result.stderr)
                    self.assertEqual(
                        log.read_bytes().decode().split("\0")[:-1],
                        [
                            "python",
                            "find",
                            "--system",
                            "--no-python-downloads",
                            ">=3.11",
                        ],
                    )
                    self.assertEqual(
                        result.stdout.decode().split("\0")[:-1],
                        [
                            str(checkout / "mcp-server"),
                            "-B",
                            "-P",
                            "-S",
                            "-m",
                            "dev_agent_toolkit_tools.cli",
                            "--source-root",
                            str(checkout),
                            *command,
                            *options,
                        ],
                    )

    def test_removed_native_registration_options_are_rejected(self) -> None:
        for operation in ("--server", "--env-only"):
            with self.subTest(operation=operation):
                result = subprocess.run(
                    ["/bin/bash", str(LAUNCHER), operation],
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn(operation.encode(), result.stderr)

    def test_missing_uv_fails_before_document_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # 只提供入口定位所需命令，确保不会意外调用本机 uv。
            dirname = shutil.which("dirname")
            if dirname is None:
                self.skipTest("requires dirname")
            (root / "dirname").symlink_to(dirname)
            target = root / "skill"
            result = subprocess.run(
                [
                    "/bin/bash",
                    str(LAUNCHER),
                    "--skills-install",
                    "--target",
                    str(target),
                ],
                env={**os.environ, "PATH": str(root)},
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 127)
            self.assertFalse(target.exists())
