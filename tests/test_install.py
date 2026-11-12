import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from omarchy_projects import ProjectError, paths
spec = importlib.util.spec_from_file_location("installer", ROOT / "scripts/install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.locations = paths(self.temp.name)
        self.locations["hypr"].parent.mkdir(parents=True)
        self.locations["hypr"].write_text('-- existing user code\nprint("keep")\n')
        self.locations["shell"].parent.mkdir(parents=True)
        self.shell = {"version": 1, "bar": {"layout": {"left": [
            {"id": "omarchy.menu"}, {"id": "omarchy.workspaces", "custom": 1}],
            "right": [{"id": "omarchy.clock"}]}}, "idle": {"lock": 300}}
        self.locations["shell"].write_text(json.dumps(self.shell))

    def test_install_upgrade_uninstall_preserve_unrelated_changes_and_symlinks(self):
        real = Path(self.temp.name) / "dotfile.lua"
        self.locations["hypr"].rename(real)
        self.locations["hypr"].symlink_to(real)
        installer.install(self.locations, no_reload=True)
        installer.install(self.locations, no_reload=True)
        self.assertTrue(self.locations["hypr"].is_symlink())
        self.assertEqual(real.read_text().count(installer.START), 1)
        real.write_text(real.read_text() + '-- added after installation\n')
        shell = json.loads(self.locations["shell"].read_text())
        shell["idle"]["lock"] = 600
        self.locations["shell"].write_text(json.dumps(shell))
        installer.install(self.locations, no_reload=True, uninstall=True)
        self.assertNotIn(installer.START, real.read_text())
        self.assertIn('-- added after installation', real.read_text())
        restored = json.loads(self.locations["shell"].read_text())
        self.assertEqual(restored["bar"], self.shell["bar"])
        self.assertEqual(restored["idle"]["lock"], 600)
        self.assertTrue(self.locations["config"].exists())
        self.assertFalse(self.locations["bin"].exists())

    def test_failed_reload_rolls_back_all_installed_files(self):
        original_hypr = self.locations["hypr"].read_text()
        original_shell = self.locations["shell"].read_text()
        with patch.object(installer, "hyprctl", side_effect=["", "ok", "bad config", "ok"]):
            with self.assertRaises(ProjectError):
                installer.install(self.locations)
        self.assertEqual(self.locations["hypr"].read_text(), original_hypr)
        self.assertEqual(self.locations["shell"].read_text(), original_shell)
        self.assertFalse(self.locations["bin"].exists())
        self.assertFalse(self.locations["config"].exists())

    def test_invalid_config_leaves_user_files_untouched(self):
        bad = Path(self.temp.name) / "bad.json"
        bad.write_text('{"version":1,"projects":[]}')
        before = self.locations["hypr"].read_text()
        with self.assertRaises(ProjectError):
            installer.install(self.locations, bad, no_reload=True)
        self.assertEqual(self.locations["hypr"].read_text(), before)
        self.assertFalse(self.locations["bin"].exists())

    def test_failed_uninstall_restores_executable_permissions(self):
        installer.install(self.locations, no_reload=True)
        with patch.object(installer, "hyprctl", side_effect=["", "ok", "bad config", "ok"]):
            with self.assertRaises(ProjectError):
                installer.install(self.locations, uninstall=True)
        self.assertEqual(self.locations["bin"].stat().st_mode & 0o777, 0o755)
        self.assertIn(installer.START, self.locations["hypr"].read_text())

    def test_clone_widget_is_restored_after_removal(self):
        clone = self.locations["plugin"].parent / "someone.workspaces/manifest.json"
        clone.parent.mkdir(parents=True)
        clone.write_text(json.dumps({"id": "someone.workspaces", "omarchy": {"clonedFrom": "omarchy.workspaces"}}))
        self.shell["bar"]["layout"]["left"][1] = {"id": "someone.workspaces"}
        self.locations["shell"].write_text(json.dumps(self.shell))
        installer.install(self.locations, no_reload=True)
        installer.install(self.locations, no_reload=True, uninstall=True)
        self.assertEqual(json.loads(self.locations["shell"].read_text()), self.shell)

    def test_preloaded_background_upgrade_and_removal_restore_stock(self):
        config = Path(self.temp.name) / 'private.json'
        config.write_text(json.dumps({'version': 1, 'preload_wallpapers': True,
                                     'projects': [{'id': 'atlas', 'name': 'Atlas', 'slot': 1}]}))
        for _ in range(2):
            installer.install(self.locations, config_path=config, no_reload=True)
        shell = json.loads(self.locations['shell'].read_text())
        self.assertIn({'id': installer.BACKGROUND}, shell['plugins'])
        self.assertIn('omarchy.background', shell['disabledPlugins'])
        self.assertTrue((self.locations['background_plugin'] / 'ProjectScene.qml').is_file())
        self.assertEqual((self.locations['data'] / 'theme-bin/omarchy-shell').stat().st_mode & 0o777, 0o755)
        shell['idle']['lock'] = 900
        self.locations['shell'].write_text(json.dumps(shell))
        installer.install(self.locations, uninstall=True, no_reload=True)
        shell = json.loads(self.locations['shell'].read_text())
        self.assertNotIn('omarchy.background', shell.get('disabledPlugins', []))
        self.assertNotIn({'id': installer.BACKGROUND}, shell['plugins'])
        self.assertEqual(shell['idle']['lock'], 900)
        self.assertFalse((self.locations['background_plugin'] / 'Background.qml').exists())

    def test_background_removal_keeps_previously_disabled_stock_disabled(self):
        record = {}
        shell = {'disabledPlugins': ['omarchy.background', 'other.plugin']}
        installer.enable_background(shell, record)
        installer.remove_background(shell, record)
        self.assertEqual(shell['disabledPlugins'], ['omarchy.background', 'other.plugin'])

    def test_uninstall_restores_workspace_widget_if_project_widget_was_moved(self):
        installer.install(self.locations, no_reload=True)
        shell = json.loads(self.locations["shell"].read_text())
        row = shell["bar"]["layout"]["left"].pop()
        shell["bar"]["layout"]["right"].append(row)
        self.locations["shell"].write_text(json.dumps(shell))
        installer.install(self.locations, no_reload=True, uninstall=True)
        rows = json.loads(self.locations["shell"].read_text())["bar"]["layout"]["right"]
        self.assertEqual(rows[-1], {"id": "omarchy.workspaces", "custom": 1})


if __name__ == "__main__":
    unittest.main()
