import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import omarchy_projects as project


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / "examples/projects.json").read_text())

    def test_invalid_slots_ids_and_duplicate_mappings(self):
        for change in (dict(slot=0), dict(slot=True), dict(id='a"); error("injected'), dict(name="bad\nname")):
            with self.subTest(change=change):
                value = dict(self.config, projects=[dict(self.config["projects"][0], **change)])
                with self.assertRaises(project.ProjectError):
                    project.validate(value)
        self.config["projects"][1]["slot"] = 1
        with self.assertRaises(project.ProjectError):
            project.validate(self.config)

    def test_lua_serialization_round_trip(self):
        value = 'München " \\ \n123 <img src="https://invalid.test/x"> $(touch /tmp/not-a-command)'
        script = "io.write(" + project.lua(value) + ")"
        result = subprocess.run(["lua", "-"], input=script, capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout, value)

    def test_invalid_workspace_transition_is_rejected_without_type_errors(self):
        for transition in (True, {'style': [], 'duration_ms': 200},
                           {'style': 'slide', 'duration_ms': True},
                           {'style': 'slide', 'duration_ms': 800}):
            with self.subTest(transition=transition):
                with self.assertRaises(project.ProjectError):
                    project.validate(dict(self.config, workspace_transition=transition))

    def test_generated_lua_handles_markup_as_plain_data(self):
        self.config["projects"][0]["name"] = '<img src="https://invalid.test/x">'
        config = project.validate(self.config)
        with tempfile.TemporaryDirectory() as temp:
            generated = project.compile_config(config, project.paths(temp))
            result = subprocess.run(["lua", "-"], input="local config = (function()\n" + generated
                                    + "end)(); io.write(config.projects[1].name)", text=True,
                                    capture_output=True, check=True)
            self.assertEqual(result.stdout, config["projects"][0]["name"])

    def test_atomic_write_preserves_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            target, link = Path(temp) / "target", Path(temp) / "link"
            target.write_text("old")
            link.symlink_to(target)
            project.atomic_write(link, "new")
            self.assertTrue(link.is_symlink())
            self.assertEqual(target.read_text(), "new")

    def test_hyprctl_lua_errors_fail_even_with_exit_zero(self):
        with patch("omarchy_projects.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "Runtime error in lua: failed", "")):
            with self.assertRaises(project.ProjectError):
                project.hyprctl("eval", "bad()")

    def test_unknown_project_does_not_contact_compositor(self):
        with tempfile.TemporaryDirectory() as temp:
            locations = project.paths(temp)
            locations["config"].parent.mkdir(parents=True)
            locations["config"].write_text(json.dumps(self.config))
            with patch("omarchy_projects.paths", return_value=locations), patch("omarchy_projects.hyprctl") as call:
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(project.main(["switch", "unknown"]), 1)
                call.assert_not_called()

    def test_reload_restores_previous_generation_on_config_error(self):
        with tempfile.TemporaryDirectory() as temp:
            locations = project.paths(temp)
            locations["config"].parent.mkdir(parents=True)
            locations["config"].write_text(json.dumps(self.config))
            locations["state"].mkdir(parents=True)
            compiled = locations["state"] / "config.lua"
            compiled.write_text("return {previous=true}\n")
            with patch("omarchy_projects.hyprctl", side_effect=["ok", "some config error", "ok"]):
                with self.assertRaises(project.ProjectError):
                    project.reload_config(locations)
            self.assertEqual(compiled.read_text(), "return {previous=true}\n")


if __name__ == "__main__":
    unittest.main()
