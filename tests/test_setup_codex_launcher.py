from __future__ import annotations

import os
import shutil
import subprocess
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
            "dev_agent_toolkit_mcp_client（MCP Client）", 1
        )
        self.assertIn("dev_agent_toolkit_tools（MCP Server）", server_help)
        self.assertIn("--mcp-server-build", server_help)
        self.assertIn("--mcp-server-install", server_help)
        self.assertIn("--mcp-client-build", client_help)
        self.assertIn("--mcp-client-install", client_help)

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
            executable = "dev_agent_toolkit_mcp_client"
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

    def test_tool_lookup_failure_does_not_fall_back_to_path_or_source(self) -> None:
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

    def test_resource_operations_use_only_installed_management_cli(self) -> None:
        source = str(LAUNCHER.parent / "instructions" / "codex-global.md")
        agents = ["agents", "update", "--source", source]
        operations = (
            ("--skills-install", [], ["skills", "install"]),
            ("--skills-update", [], ["skills", "update"]),
            ("--agents-install", [], agents),
            ("--agents-update", [], agents),
            ("--agents-update", ["--source", "custom template.md"], agents),
            ("--agents-update", ["--source=custom template.md"], agents),
        )
        with tempfile.TemporaryDirectory(prefix="installed tools ") as directory:
            root = Path(directory)
            (root / "uv").write_text(
                '#!/bin/bash\n[ "$*" = "tool dir --bin" ] || exit 99\n'
                'printf "%s\\n" "${0%/*}"\n',
                encoding="utf-8",
            )
            cli = root / "dev-agent-toolkit"
            cli.write_text(
                "#!/bin/bash\nprintf '%s\\0' \"$@\"\nexit 24\n", encoding="utf-8"
            )
            for executable in (root / "uv", cli):
                executable.chmod(0o755)
            for operation, options, expected in operations:
                with self.subTest(operation=operation, options=options):
                    result = subprocess.run(
                        [str(LAUNCHER), operation, *options, "--dry-run"],
                        cwd=root,
                        env={**os.environ, "PATH": f"{root}:/usr/bin:/bin"},
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 24, result.stderr)
                    self.assertEqual(
                        result.stdout.decode().split("\0")[:-1],
                        [*expected, *options, "--dry-run"],
                    )

    def test_resource_write_refreshes_tool_before_running_installed_cli(self) -> None:
        with tempfile.TemporaryDirectory(prefix="refresh tools ") as directory:
            root = Path(directory)
            uv = root / "uv"
            uv.write_text(
                "#!/bin/bash\n"
                'printf "%s\\0" "$@" >> "$CALL_LOG"\n'
                'if [[ "$2" == install ]]; then\n'
                '    printf "build output\\n"\n'
                '    exit "$INSTALL_STATUS"\n'
                "fi\n"
                'printf "%s\\n" "${0%/*}"\n',
                encoding="utf-8",
            )
            cli = root / "dev-agent-toolkit"
            cli.write_text('#!/bin/bash\nprintf "%s\\0" "$@"\n', encoding="utf-8")
            for executable in (uv, cli):
                executable.chmod(0o755)
            log = root / "calls"
            environment = {
                **os.environ,
                "PATH": f"{root}:/usr/bin:/bin",
                "CALL_LOG": str(log),
            }
            refresh = [
                "tool",
                "install",
                "--managed-python",
                "--reinstall-package",
                "dev-agent-toolkit-tools",
                str(LAUNCHER.parent / "mcp-server"),
            ]
            lookup = ["tool", "dir", "--bin"]
            skills = ["skills", "update"]
            agents = [
                "agents",
                "update",
                "--source",
                str(LAUNCHER.parent / "instructions" / "codex-global.md"),
            ]
            for operation, options, status, uv_args, cli_args in (
                ("--skills-update", [], 0, [*refresh, *lookup], skills),
                ("--agents-update", [], 0, [*refresh, *lookup], agents),
                ("--skills-update", [], 19, refresh, []),
                ("--skills-update", ["--dry"], 0, lookup, [*skills, "--dry"]),
                ("--skills-update", ["--help"], 0, lookup, [*skills, "--help"]),
            ):
                with self.subTest(operation=operation, options=options, status=status):
                    log.write_bytes(b"")
                    result = subprocess.run(
                        [str(LAUNCHER), operation, *options],
                        cwd=root,
                        env={**environment, "INSTALL_STATUS": str(status)},
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, status, result.stderr)
                    self.assertEqual(
                        log.read_bytes().decode().split("\0")[:-1], uv_args
                    )
                    self.assertEqual(result.stdout.decode().split("\0")[:-1], cli_args)

    def test_explicit_mcp_operations_select_install_or_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            uv = root / "uv"
            uv.write_text("#!/bin/bash\nprintf '%s\\0' \"$@\"\n", encoding="utf-8")
            uv.chmod(0o755)
            for operation, flags in (
                ("--mcp-install", ["--install"]),
                ("--mcp-update", ["--install", "--force"]),
            ):
                with self.subTest(operation=operation):
                    result = subprocess.run(
                        [str(LAUNCHER), operation, "--dry-run"],
                        cwd=LAUNCHER.parent,
                        env={**os.environ, "PATH": f"{root}:/usr/bin:/bin"},
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(
                        result.stdout.decode().split("\0")[:-1],
                        [
                            "run",
                            "--managed-python",
                            "--",
                            str(LAUNCHER.parent / "scripts" / "setup-codex-mcp.py"),
                            *flags,
                            "--dry-run",
                        ],
                    )

    def test_launch_from_other_directory_preserves_arguments_and_exit_status(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout = root / "checkout with spaces"
            checkout.mkdir()
            launcher = checkout / LAUNCHER.name
            shutil.copy2(LAUNCHER, launcher)
            uv = root / "uv"
            uv.write_text(
                "#!/bin/bash\nprintf '%s\\0' \"$@\"\nexit 23\n", encoding="utf-8"
            )
            uv.chmod(0o755)
            arguments = ["--install", "--force", "--config", "a b/*;$(echo x)", ""]
            result = subprocess.run(
                [str(launcher), *arguments],
                cwd=root,
                env={**os.environ, "PATH": f"{root}:/usr/bin:/bin"},
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 23, result.stderr)
            self.assertEqual(
                result.stdout.decode().split("\0")[:-1],
                [
                    "run",
                    "--managed-python",
                    "--",
                    str(checkout.resolve() / "scripts" / "setup-codex-mcp.py"),
                    *arguments,
                ],
            )

    def test_missing_uv_fails_before_python_or_config_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # 只提供入口定位所需命令，确保不会意外调用本机 uv。
            dirname = shutil.which("dirname")
            if dirname is None:
                self.skipTest("requires dirname")
            (root / "dirname").symlink_to(dirname)
            config = root / "config.toml"
            result = subprocess.run(
                [str(LAUNCHER), "--install", "--config", str(config)],
                env={**os.environ, "PATH": str(root)},
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 127)
            self.assertFalse(config.exists())
