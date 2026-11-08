from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parents[1] / "dws"


@unittest.skipUnless(Path("/bin/bash").is_file(), "requires Bash")
class SetupLauncherTests(unittest.TestCase):
    def test_tool_lookup_failure_does_not_fall_back_to_path_or_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            uv = root / "uv"
            uv.write_text("#!/bin/bash\nexit 19\n", encoding="utf-8")
            uv.chmod(0o755)
            cli = root / "dev-workflow-standards"
            cli.write_text("#!/bin/bash\nexit 99\n", encoding="utf-8")
            cli.chmod(0o755)
            result = subprocess.run(
                [str(LAUNCHER), "--skills-update"],
                env={**os.environ, "PATH": f"{root}:/usr/bin:/bin"},
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 19, result.stderr)

    def test_resource_operations_use_only_installed_management_cli(self) -> None:
        operations = {
            "--skills-install": ["skills", "install"],
            "--skills-update": ["skills", "update"],
            "--agents-install": ["agents", "update"],
            "--agents-update": ["agents", "update"],
        }
        with tempfile.TemporaryDirectory(prefix="installed tools ") as directory:
            root = Path(directory)
            (root / "uv").write_text(
                '#!/bin/bash\n[ "$*" = "tool dir --bin" ] || exit 99\n'
                'printf "%s\\n" "${0%/*}"\n',
                encoding="utf-8",
            )
            cli = root / "dev-workflow-standards"
            cli.write_text(
                "#!/bin/bash\nprintf '%s\\0' \"$@\"\nexit 24\n", encoding="utf-8"
            )
            for executable in (root / "uv", cli):
                executable.chmod(0o755)
            for operation, expected in operations.items():
                with self.subTest(operation=operation):
                    result = subprocess.run(
                        [str(LAUNCHER), operation, "--dry-run"],
                        env={**os.environ, "PATH": f"{root}:/usr/bin:/bin"},
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 24, result.stderr)
                    self.assertEqual(
                        result.stdout.decode().split("\0")[:-1],
                        [*expected, "--dry-run"],
                    )

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
            (root / "dirname").symlink_to(shutil.which("dirname"))
            config = root / "config.toml"
            result = subprocess.run(
                [str(LAUNCHER), "--install", "--config", str(config)],
                env={**os.environ, "PATH": str(root)},
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 127)
            self.assertFalse(config.exists())
