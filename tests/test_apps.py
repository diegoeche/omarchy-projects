import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import omarchy_projects as projects


class ProjectAppsTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / "examples/projects.json").read_text())
        self.project = self.config["projects"][0]
        self.project["apps"] = [
            {"id": "chat", "name": "Chat", "desktop": "Chat Atlas.desktop"},
            {"id": "terminal", "name": "Terminal", "desktop": "terminal-atlas.desktop"},
        ]

    def test_apps_round_trip_and_can_reuse_ids_in_another_project(self):
        self.config["projects"][1]["apps"] = [dict(self.project["apps"][0], desktop="Chat Boreal.desktop")]
        self.assertEqual(projects.validate(self.config)["projects"], self.config["projects"])

    def test_malformed_apps_and_path_traversal_are_rejected(self):
        app = self.project["apps"][0]
        invalid = [None, {}, [app] * 25, [app, app],
                   [dict(app, name="bad\tname")], [dict(app, name=" " * 100 + "a")], [dict(app, id="--bad")],
                   [dict(app, desktop="../chat.desktop")], [dict(app, desktop="/tmp/chat.desktop")],
                   [dict(app, desktop="chat.desktop\nExec=bad")], [dict(app, desktop="https://invalid.test/app.desktop")],
                   [dict(app, desktop="chat.exe")], [dict(app, command="touch /tmp/injected")],
                   [app, dict(app, id="another")]]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(projects.ProjectError):
                projects.validate(dict(self.config, projects=[dict(self.project, apps=value)]))

    def test_instance_match_accepts_literal_profiles_and_rejects_malformed_values(self):
        app = dict(self.project["apps"][0], match={"class": "editor", "env": {"EDITOR_PROFILE": "~/atlas"}})
        projects.validate(dict(self.config, projects=[dict(self.project, apps=[app])]))
        for match in (None, [], {}, {"unknown": "x"}, {"class": []}, {"class": "bad\nclass"},
                      {"env": []}, {"env": {}}, {"env": {"invalid=name": "x"}},
                      {"env": {"PROFILE": "bad\nvalue"}}):
            with self.subTest(match=match), self.assertRaises(projects.ProjectError):
                projects.validate(dict(self.config, projects=[dict(self.project, apps=[dict(app, match=match)])]))

    def test_user_desktop_entry_takes_precedence_and_missing_entry_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            user, system = root / "user", root / "system"
            for directory in (user, system):
                (directory / "applications").mkdir(parents=True)
                (directory / "applications/Chat Atlas.desktop").write_text("[Desktop Entry]\nType=Application\n")
            with patch.dict(os.environ, XDG_DATA_HOME=str(user), XDG_DATA_DIRS=str(system)):
                self.assertEqual(projects.desktop_entry("Chat Atlas.desktop"), user / "applications/Chat Atlas.desktop")
                with self.assertRaises(projects.ProjectError):
                    projects.desktop_entry("missing.desktop")

    def test_launch_uses_desktop_entry_as_one_argument_without_shell(self):
        entry = Path('/tmp/quoted " path $(no)/Chat Atlas.desktop')
        with (patch.object(projects, "desktop_entry", return_value=entry),
              patch.object(projects, "app_window_match", return_value={"class": "chat"}),
              patch.object(projects, "AppEvents") as subscription,
              patch.object(projects, "project_is_selected", return_value=True),
              patch.object(projects, "matching_app_window", return_value=None),
              patch.object(projects, "call") as compositor,
              patch.object(projects.subprocess, "Popen") as spawn):
            subscription.return_value.__enter__.return_value.wait.return_value = {"address": "0x123"}
            projects.launch_project_app(self.project, "chat", {})
            self.assertEqual(spawn.call_args.args[0], ["gio", "launch", str(entry)])
            self.assertNotIn("shell", spawn.call_args.kwargs)
            compositor.assert_called_once_with("activate_app", "atlas", "0x123")
        with patch.object(projects, "desktop_entry") as lookup, patch.object(projects.subprocess, "Popen") as spawn:
            with self.assertRaises(projects.ProjectError):
                projects.launch_project_app(self.project, "unknown", {})
            lookup.assert_not_called()
            spawn.assert_not_called()

    def test_existing_instance_is_brought_to_project_without_relaunching(self):
        with (patch.object(projects, "desktop_entry", return_value=Path("/tmp/chat.desktop")),
              patch.object(projects, "app_window_match", return_value={"class": "chat"}),
              patch.object(projects, "AppEvents") as subscription,
              patch.object(projects, "project_is_selected", side_effect=[False, True]),
              patch.object(projects, "matching_app_window", return_value={"address": "0x456"}),
              patch.object(projects, "call") as compositor,
              patch.object(projects.subprocess, "Popen") as spawn):
            projects.launch_project_app(self.project, "chat", {})
            self.assertEqual(compositor.call_args_list[0].args, ("show", "atlas"))
            self.assertEqual(compositor.call_args_list[1].args, ("activate_app", "atlas", "0x456"))
            subscription.return_value.__enter__.return_value.wait.assert_called_once()
            spawn.assert_not_called()

    def test_window_matching_distinguishes_profiles_with_the_same_class(self):
        windows = [{"class": "editor", "pid": 100, "address": "0x100"},
                   {"class": "editor", "pid": 200, "address": "0x200"},
                   {"class": "other", "pid": 300, "address": "0x300"}]
        environments = {100: b"EDITOR_PROFILE=boreal\0", 200: b"EDITOR_PROFILE=atlas\0"}
        def environment(path, *_):
            return io.BytesIO(environments[int(path.parent.name)])
        with (patch.object(projects, "hyprctl", return_value=json.dumps(windows)),
              patch.object(Path, "open", autospec=True, side_effect=environment)):
            match = {"class": "editor", "env": {"EDITOR_PROFILE": "atlas"}}
            self.assertEqual(projects.matching_app_window(match)["address"], "0x200")
            self.assertIsNone(projects.matching_app_window(dict(match, env={"EDITOR_PROFILE": "missing"})))

    def test_startup_window_class_is_read_without_interpreting_desktop_commands(self):
        with tempfile.TemporaryDirectory() as temporary:
            entry = Path(temporary) / "chat.desktop"
            entry.write_text('[Desktop Entry]\nType=Application\nStartupWMClass=chat.instance\nExec=never-run %U\n')
            self.assertEqual(projects.app_window_match(self.project["apps"][0], entry), {"class": "chat.instance"})
            app = dict(self.project["apps"][0], match={"env": {"PROFILE_HOME": "~/atlas"}})
            self.assertEqual(projects.app_window_match(app, entry),
                             {"class": "chat.instance", "env": {"PROFILE_HOME": "~/atlas"}})

    def test_compositor_subscription_closes_after_timeout_or_disconnect(self):
        for failure in (socket.timeout(), b""):
            with patch.object(projects.socket, "socket") as factory:
                connection = factory.return_value
                if isinstance(failure, Exception):
                    connection.recv.side_effect = failure
                else:
                    connection.recv.return_value = failure
                with self.assertRaises(projects.ProjectError):
                    with projects.AppEvents() as events:
                        events.wait(lambda: None, 1, "fixture timed out")
                connection.close.assert_called_once()

    def test_native_menu_preserves_literal_labels_and_selects_stable_app_id(self):
        self.project["apps"][0]["name"] = '<img src="https://invalid.test/x">'
        args = argparse.Namespace(project="atlas", apps_action="menu")
        result = subprocess.CompletedProcess([], 0, self.project["apps"][0]["name"] + "\n", "")
        with patch.object(projects.subprocess, "run", return_value=result) as menu, patch.object(projects, "launch_project_app") as launch:
            projects.apps_command(args, self.config, {})
            self.assertIn("󰀻\t" + self.project["apps"][0]["name"], menu.call_args.args[0])
            launch.assert_called_once_with(self.project, "chat", {})

    def test_cancelled_or_unknown_menu_selection_never_launches_an_app(self):
        args = argparse.Namespace(project="atlas", apps_action="menu")
        for result in [subprocess.CompletedProcess([], 1, "", ""),
                       subprocess.CompletedProcess([], 0, "unknown\n", "")]:
            with patch.object(projects.subprocess, "run", return_value=result), patch.object(projects, "launch_project_app") as launch:
                projects.apps_command(args, self.config, {})
                launch.assert_not_called()

    def test_cli_lists_only_requested_project_apps_without_compositor_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            locations = projects.paths(temporary)
            locations["config"].parent.mkdir(parents=True)
            locations["config"].write_text(json.dumps(self.config))
            with patch.object(projects, "paths", return_value=locations), patch.object(projects, "hyprctl") as compositor:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(projects.main(["apps", "list", "atlas"]), 0)
                self.assertEqual(json.loads(output.getvalue()), self.project["apps"])
                compositor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
