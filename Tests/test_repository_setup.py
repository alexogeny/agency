import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "Tools/repository-setup"
SCRATCH = Path(os.environ.get("AGENCY_TEST_SCRATCH", ROOT / ".cache/tests"))


class RepositorySetupTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.workspace = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def run_tool(self, *arguments, check=True):
        result = subprocess.run(
            [TOOL, *map(str, arguments)],
            check=False,
            text=True,
            capture_output=True,
        )
        if check and result.returncode:
            self.fail(result.stderr or result.stdout)
        return result

    def render(self, output):
        result = self.run_tool(
            "render",
            "--output",
            output,
            "--project",
            "rose-garden",
            "--repository",
            "alexogeny/rose-garden",
            "--profile",
            "python",
            "--runtime-version",
            "3.14",
            "--branch",
            "main",
            "--docs-command",
            "uv run --no-sync mkdocs build --strict",
            "--docs-output",
            "site",
            "--publish",
            "--json",
        )
        return json.loads(result.stdout)

    def test_render_builds_a_complete_hashed_bundle(self):
        output = self.workspace / "bundle"

        manifest = self.render(output)

        self.assertEqual(manifest["schema"], "agency/repository-setup-bundle/1")
        self.assertEqual(manifest["project"], "rose-garden")
        self.assertEqual(manifest["repository"], "alexogeny/rose-garden")
        self.assertEqual(manifest["profile"], "python")
        self.assertEqual(manifest["runtime_version"], "3.14")
        self.assertEqual(
            manifest["configuration"]["checks"],
            [
                {"name": "Ruff lint", "command": "uv run --no-sync ruff check ."},
                {
                    "name": "Ruff format",
                    "command": "uv run --no-sync ruff format --check .",
                },
                {"name": "Ty", "command": "uv run --no-sync ty check"},
                {"name": "Tests", "command": "uv run --no-sync pytest"},
            ],
        )
        self.assertEqual(
            manifest["configuration"]["docs"],
            {
                "command": "uv run --no-sync mkdocs build --strict",
                "output": "site",
            },
        )
        self.assertEqual(
            manifest["configuration"]["publish"],
            {"distribution": "rose-garden"},
        )
        paths = {record["path"] for record in manifest["files"]}
        self.assertIn("files/.github/workflows/ci.yml", paths)
        self.assertIn("files/.github/workflows/docs.yml", paths)
        self.assertIn("files/.github/workflows/publish.yml", paths)
        self.assertIn("github/main-ruleset.json", paths)

        ci = (output / "files/.github/workflows/ci.yml").read_text()
        self.assertIn("python-version: '3.14'", ci)
        self.assertIn("uv run --no-sync ruff check .", ci)
        self.assertIn("uv run --no-sync ruff format --check .", ci)
        self.assertIn("uv run --no-sync ty check", ci)
        self.assertIn("uv run --no-sync pytest", ci)
        self.assertNotIn("__", ci)

        ruleset = json.loads((output / "github/main-ruleset.json").read_text())
        status_rule = next(
            rule
            for rule in ruleset["rules"]
            if rule["type"] == "required_status_checks"
        )
        self.assertEqual(
            status_rule["parameters"]["required_status_checks"],
            [{"context": "checks"}],
        )

        for record in manifest["files"]:
            data = (output / record["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), record["sha256"])
        self.assertEqual(json.loads((output / "manifest.json").read_text()), manifest)

    def test_apply_is_idempotent_and_refuses_divergent_files_atomically(self):
        bundle = self.workspace / "bundle"
        self.render(bundle)
        target = self.workspace / "target"

        first = json.loads(self.run_tool("apply", bundle, target, "--json").stdout)
        second = json.loads(self.run_tool("apply", bundle, target, "--json").stdout)

        self.assertTrue(first["created"])
        self.assertFalse(first["unchanged"])
        self.assertFalse(second["created"])
        self.assertEqual(second["unchanged"], first["created"])

        collision_target = self.workspace / "collision"
        collision = collision_target / ".github/workflows/ci.yml"
        collision.parent.mkdir(parents=True)
        collision.write_text("existing\n")

        refused = self.run_tool(
            "apply", bundle, collision_target, "--json", check=False
        )

        self.assertEqual(refused.returncode, 3)
        payload = json.loads(refused.stdout)
        self.assertEqual(payload["error"], "destination conflict")
        self.assertEqual(payload["conflicts"], [".github/workflows/ci.yml"])
        self.assertEqual(collision.read_text(), "existing\n")
        self.assertFalse(
            (collision_target / ".github/ISSUE_TEMPLATE/config.yml").exists()
        )

        escaped = self.workspace / "escaped"
        escaped.mkdir()
        linked_target = self.workspace / "linked"
        linked_target.mkdir()
        (linked_target / ".github").symlink_to(escaped, target_is_directory=True)

        refused_link = self.run_tool(
            "apply", bundle, linked_target, "--json", check=False
        )

        self.assertEqual(refused_link.returncode, 3)
        link_payload = json.loads(refused_link.stdout)
        self.assertIn(".github/workflows/ci.yml", link_payload["conflicts"])
        self.assertEqual(list(escaped.iterdir()), [])

        refused_replace = self.run_tool(
            "apply",
            bundle,
            linked_target,
            "--conflict",
            "replace",
            "--json",
            check=False,
        )

        self.assertEqual(refused_replace.returncode, 3)
        replace_payload = json.loads(refused_replace.stdout)
        self.assertTrue(replace_payload["blocked"])
        self.assertTrue(
            all(
                action["action"] == "unsafe"
                for action in replace_payload["actions"]
                if action["path"].startswith(".github/")
            )
        )
        self.assertEqual(list(escaped.iterdir()), [])

        blocked_parent = self.workspace / "blocked-parent"
        blocked_parent.mkdir()
        (blocked_parent / ".github").write_text("not a directory\n")

        refused_parent = self.run_tool(
            "apply",
            bundle,
            blocked_parent,
            "--dry-run",
            "--conflict",
            "replace",
            "--json",
            check=False,
        )

        self.assertEqual(refused_parent.returncode, 3)
        parent_payload = json.loads(refused_parent.stdout)
        self.assertTrue(parent_payload["blocked"])
        self.assertTrue(
            all(action["action"] == "unsafe" for action in parent_payload["actions"])
        )
        self.assertEqual((blocked_parent / ".github").read_text(), "not a directory\n")

    def test_dry_run_reports_conflicts_and_explicit_policies_control_them(self):
        bundle = self.workspace / "bundle"
        self.render(bundle)
        target = self.workspace / "target"
        collision = target / ".github/workflows/ci.yml"
        collision.parent.mkdir(parents=True)
        collision.write_text("existing\n")

        blocked = self.run_tool(
            "apply", bundle, target, "--dry-run", "--json", check=False
        )

        self.assertEqual(blocked.returncode, 3)
        blocked_plan = json.loads(blocked.stdout)
        self.assertTrue(blocked_plan["dry_run"])
        self.assertTrue(blocked_plan["blocked"])
        ci_action = next(
            action
            for action in blocked_plan["actions"]
            if action["path"] == ".github/workflows/ci.yml"
        )
        self.assertEqual(ci_action["action"], "conflict")
        self.assertEqual(ci_action["risk"], "high")
        self.assertEqual(collision.read_text(), "existing\n")
        self.assertFalse((target / ".github/ISSUE_TEMPLATE/config.yml").exists())

        keep_plan = json.loads(
            self.run_tool(
                "apply",
                bundle,
                target,
                "--dry-run",
                "--conflict",
                "keep",
                "--json",
            ).stdout
        )
        self.assertFalse(keep_plan["blocked"])
        self.assertEqual(
            next(
                action
                for action in keep_plan["actions"]
                if action["path"] == ".github/workflows/ci.yml"
            )["action"],
            "keep",
        )
        self.assertFalse((target / ".github/ISSUE_TEMPLATE/config.yml").exists())

        kept = json.loads(
            self.run_tool(
                "apply", bundle, target, "--conflict", "keep", "--json"
            ).stdout
        )
        self.assertEqual(kept["kept"], [".github/workflows/ci.yml"])
        self.assertEqual(collision.read_text(), "existing\n")
        self.assertTrue((target / ".github/ISSUE_TEMPLATE/config.yml").is_file())

        replace_target = self.workspace / "replace"
        replace_collision = replace_target / ".github/workflows/ci.yml"
        replace_collision.parent.mkdir(parents=True)
        replace_collision.write_text("existing\n")
        replace_plan = json.loads(
            self.run_tool(
                "apply",
                bundle,
                replace_target,
                "--dry-run",
                "--conflict",
                "replace",
                "--json",
            ).stdout
        )
        replace_action = next(
            action
            for action in replace_plan["actions"]
            if action["path"] == ".github/workflows/ci.yml"
        )
        self.assertEqual(replace_action["action"], "replace")
        self.assertEqual(replace_action["risk"], "high")
        self.assertEqual(
            replace_action["current_sha256"],
            hashlib.sha256(b"existing\n").hexdigest(),
        )
        self.assertEqual(
            replace_action["proposed_sha256"],
            hashlib.sha256(
                (bundle / "files/.github/workflows/ci.yml").read_bytes()
            ).hexdigest(),
        )
        self.assertEqual(replace_collision.read_text(), "existing\n")

        replaced = json.loads(
            self.run_tool(
                "apply",
                bundle,
                replace_target,
                "--conflict",
                "replace",
                "--json",
            ).stdout
        )
        self.assertEqual(replaced["replaced"], [".github/workflows/ci.yml"])
        self.assertEqual(
            replace_collision.read_bytes(),
            (bundle / "files/.github/workflows/ci.yml").read_bytes(),
        )

    def test_component_selection_keeps_a_ci_only_request_narrow(self):
        output = self.workspace / "ci-bundle"

        manifest = json.loads(
            self.run_tool(
                "render",
                "--output",
                output,
                "--project",
                "rose-garden",
                "--repository",
                "alexogeny/rose-garden",
                "--profile",
                "python",
                "--runtime-version",
                "3.14",
                "--component",
                "ci",
                "--json",
            ).stdout
        )

        self.assertEqual(manifest["components"], ["ci"])
        self.assertEqual(
            [record["path"] for record in manifest["files"]],
            ["files/.github/workflows/ci.yml"],
        )

    def test_community_templates_follow_the_selected_profile(self):
        expectations = {
            "javascript": ("Bun and platform", "bun --version", "javascript"),
            "typescript": ("Bun and platform", "bun --version", "typescript"),
            "go": ("Go and platform", "go version", "go"),
            "rust": ("Rust and platform", "rustc -Vv", "rust"),
        }
        for profile, (label, command, language) in expectations.items():
            with self.subTest(profile=profile):
                output = self.workspace / f"community-{profile}"
                self.run_tool(
                    "render",
                    "--output",
                    output,
                    "--project",
                    f"garden-{profile}",
                    "--repository",
                    f"alexogeny/garden-{profile}",
                    "--profile",
                    profile,
                    "--runtime-version",
                    "stable",
                    "--component",
                    "community",
                )
                bug = (
                    output / "files/.github/ISSUE_TEMPLATE/bug_report.yml"
                ).read_text()
                feature = (
                    output / "files/.github/ISSUE_TEMPLATE/feature_request.yml"
                ).read_text()
                self.assertIn(f"label: {label}", bug)
                self.assertIn(f"`{command}`", bug)
                self.assertIn(f"render: {language}", bug)
                self.assertIn(f"render: {language}", feature)

    def render_profile(self, profile, runtime, *, publish=False):
        output = self.workspace / profile
        arguments = [
            "render",
            "--output",
            output,
            "--project",
            f"garden-{profile}",
            "--repository",
            f"alexogeny/garden-{profile}",
            "--profile",
            profile,
            "--runtime-version",
            runtime,
            "--component",
            "ci",
        ]
        if publish:
            arguments.extend(("--component", "publish"))
        arguments.append("--json")
        manifest = json.loads(self.run_tool(*arguments).stdout)
        ci = (output / "files/.github/workflows/ci.yml").read_text()
        return output, manifest, ci

    def test_javascript_and_typescript_profiles_use_bun_and_prettier(self):
        js_output, javascript, js_ci = self.render_profile(
            "javascript", "1.2.20", publish=True
        )
        _, typescript, ts_ci = self.render_profile("typescript", "1.2.20")

        self.assertEqual(javascript["profile"], "javascript")
        self.assertIn("oven-sh/setup-bun@v2", js_ci)
        self.assertIn("bun install --frozen-lockfile", js_ci)
        self.assertIn("bunx --no-install prettier --check .", js_ci)
        self.assertIn("bunx --no-install eslint .", js_ci)
        self.assertIn("bun test", js_ci)
        self.assertNotIn("tsc --noEmit", js_ci)

        self.assertEqual(typescript["profile"], "typescript")
        self.assertIn("bunx --no-install prettier --check .", ts_ci)
        self.assertIn("bunx --no-install tsc --noEmit", ts_ci)

        publish = (js_output / "files/.github/workflows/publish.yml").read_text()
        self.assertIn("id-token: write", publish)
        self.assertIn("npm publish --provenance", publish)
        self.assertNotIn("NPM_TOKEN", publish)

    def test_go_profile_formats_vets_and_tests_without_fake_publication(self):
        _, manifest, ci = self.render_profile("go", "1.24")

        self.assertEqual(manifest["profile"], "go")
        self.assertIn("actions/setup-go@v6", ci)
        self.assertIn("gofmt -l .", ci)
        self.assertIn("go vet ./...", ci)
        self.assertIn("go test ./...", ci)

        refused = self.run_tool(
            "render",
            "--output",
            self.workspace / "go-publish",
            "--project",
            "garden-go",
            "--repository",
            "alexogeny/garden-go",
            "--profile",
            "go",
            "--runtime-version",
            "1.24",
            "--publish",
            "--json",
            check=False,
        )
        self.assertEqual(refused.returncode, 2)
        self.assertIn(
            "Go modules are published by immutable version tags", refused.stderr
        )

    def test_rust_profile_formats_lints_tests_and_uses_trusted_publishing(self):
        output, manifest, ci = self.render_profile("rust", "stable", publish=True)

        self.assertEqual(manifest["profile"], "rust")
        self.assertIn("actions-rust-lang/setup-rust-toolchain@v1", ci)
        self.assertIn("cargo fmt --all --check", ci)
        self.assertIn("cargo clippy --all-targets --all-features", ci)
        self.assertIn("cargo test --all-features --locked", ci)

        publish = (output / "files/.github/workflows/publish.yml").read_text()
        self.assertIn("rust-lang/crates-io-auth-action@v1.0.5", publish)
        self.assertIn("cargo publish --locked", publish)


if __name__ == "__main__":
    unittest.main()
