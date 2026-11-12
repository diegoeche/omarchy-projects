import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import omarchy_projects as project
import project_appearance as appearance


class AppearanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.locations = project.paths(self.temporary.name)
        self.locations["state"].mkdir(parents=True)
        self.current = self.locations["home"] / '.local/state/omarchy/current'
        self.current.mkdir(parents=True)
        self.source = self.locations["home"] / 'background with " quotes.png'
        self.source.write_bytes(b'wallpaper fixture')
        (self.current / 'background').symlink_to(self.source)
        (self.current / 'theme.name').write_text('old-theme\n')
        for name in ('old-theme', 'new-theme'):
            (self.locations["home"] / '.config/omarchy/themes' / name).mkdir(parents=True)
        self.config = project.validate(json.loads((ROOT / 'examples/projects.json').read_text()))
        for row in self.config['projects']:
            row['appearance'] = {'theme': 'new-theme', 'wallpaper': str(self.source)}
        self.locations['config'].parent.mkdir(parents=True, exist_ok=True)
        self.locations['config'].write_text(json.dumps(self.config))

    def request(self, ident):
        appearance.write_json(self.locations['state'] / 'appearance-request.json', {'project': ident})

    def test_config_round_trips_optional_looks_and_rejects_invalid_values(self):
        self.assertEqual(project.validate(self.config), self.config)
        for value in ({'theme': '../bad', 'wallpaper': 'ok'},
                      {'theme': 'good', 'wallpaper': 'bad\npath'}, {'theme': 'good'}):
            self.config['projects'][0]['appearance'] = value
            with self.assertRaises(ValueError):
                project.validate(self.config)

    def test_snapshot_survives_source_wallpaper_replacement(self):
        look = appearance.snapshot_look('atlas', appearance.current_look(self.locations), self.locations)
        self.source.write_bytes(b'a different Aether wallpaper')
        self.assertEqual(Path(look['wallpaper']).read_bytes(), b'wallpaper fixture')
        self.assertNotEqual(look['wallpaper'], str(self.source))

    def test_workspace_reload_does_not_undo_manual_aether_edits(self):
        self.request('atlas')
        with patch.object(appearance, 'apply_look') as apply:
            appearance.apply_requested(self.locations, project.load_config)
            (self.current / 'theme.name').write_text('manually-selected-theme')
            appearance.apply_requested(self.locations, project.load_config)
            self.assertEqual(apply.call_count, 1)

    def test_new_configuration_on_same_project_gets_applied(self):
        self.request('atlas')
        with patch.object(appearance, 'apply_look') as apply:
            appearance.apply_requested(self.locations, project.load_config)
            self.config['projects'][0]['appearance']['theme'] = 'old-theme'
            self.locations['config'].write_text(json.dumps(self.config))
            appearance.apply_requested(self.locations, project.load_config)
            self.assertEqual(apply.call_count, 2)

    def test_worker_converges_after_project_changes_during_theme_application(self):
        self.request('atlas')
        applied = []
        def apply(look, locations):
            applied.append(look['theme'])
            if len(applied) == 1:
                self.config['projects'][2]['appearance']['theme'] = 'old-theme'
                self.locations['config'].write_text(json.dumps(self.config))
                self.request('personal')
        with patch.object(appearance, 'apply_look', side_effect=apply):
            appearance.apply_requested(self.locations, project.load_config)
        self.assertEqual(applied, ['new-theme', 'old-theme'])
        saved = json.loads((self.locations['state'] / 'appearance-applied.json').read_text())
        self.assertEqual(saved['project'], 'personal')

    def test_missing_wallpaper_does_not_modify_theme_or_links(self):
        self.config['projects'][0]['appearance']['wallpaper'] = str(self.source) + '.missing'
        self.locations['config'].write_text(json.dumps(self.config))
        self.request('atlas')
        with patch.object(appearance, 'run') as run:
            with self.assertRaises(OSError):
                appearance.apply_requested(self.locations, project.load_config)
            run.assert_not_called()
        self.assertEqual((self.current / 'background').resolve(), self.source)

    def test_theme_command_is_skipped_when_only_wallpaper_changes(self):
        other = self.locations['home'] / "other's wallpaper.png"
        other.write_bytes(b'other fixture')
        with patch.object(appearance, 'run') as run:
            appearance.apply_look({'theme': 'old-theme', 'wallpaper': str(other)}, self.locations)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], ['omarchy', 'shell', 'background', 'setInstant', str(other)])

    def test_generated_worker_command_quotes_paths(self):
        locations = dict(self.locations, data=Path('/tmp/a path; $literal'))
        compiled = project.compile_config(self.config, locations)
        self.assertIn('appearance_request_file', compiled)
        self.assertIn("'/tmp/a path; $literal/omarchy_projects.py'", compiled)

    def test_palette_change_uses_omarchy_and_keeps_the_requested_wallpaper(self):
        commands = []
        def run(command, **kwargs):
            commands.append((command, kwargs))
            if command[:3] == ['omarchy', 'theme', 'set']:
                (self.current / 'theme.name').write_text(command[3])
        with patch.object(appearance, 'run', side_effect=run):
            appearance.apply_look({'theme': 'new-theme', 'wallpaper': str(self.source)}, self.locations)
        self.assertEqual(commands[0][0], ['omarchy', 'theme', 'set', 'new-theme'])
        self.assertEqual(commands[0][1]['env']['OMARCHY_THEME_SKIP_BACKGROUND'], '1')
        self.assertEqual((self.current / 'background').resolve(), self.source)


if __name__ == '__main__':
    unittest.main()
