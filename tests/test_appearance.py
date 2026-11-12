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

    def test_all_projects_can_keep_the_colorful_variant_in_config(self):
        with patch.object(project, 'paths', return_value=self.locations), patch.object(project, 'reload_config'):
            project.main(['appearance', 'generate', '--all', '--variant', 'colorful'])
        saved = project.load_config(self.locations['config'])
        self.assertEqual([row['appearance']['aether_variant'] for row in saved['projects']], ['colorful'] * 3)
        for mode in ('--apply', 'colorful; touch /tmp/x', 1):
            with self.assertRaises(ValueError):
                appearance.validate_appearance(dict(saved['projects'][0]['appearance'], aether_variant=mode))

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
            if command[:3] == ['hyprctl', '-j', 'getoption']:
                return '{"bool":false}'
            if command[:2] == ['hyprctl', 'eval']:
                return 'ok\n'
            if command[:3] == ['omarchy', 'theme', 'set']:
                (self.current / 'theme.name').write_text(command[3])
        with patch.object(appearance, 'run', side_effect=run):
            appearance.apply_look({'theme': 'new-theme', 'wallpaper': str(self.source)}, self.locations)
        theme = next(call for call in commands if call[0][:3] == ['omarchy', 'theme', 'set'])
        self.assertEqual(theme[0], ['omarchy', 'theme', 'set', 'new-theme'])
        self.assertEqual(theme[1]['env']['OMARCHY_THEME_SKIP_BACKGROUND'], '1')
        self.assertEqual(theme[1]['env']['PATH'].split(os.pathsep)[0], str(self.locations['data'] / 'theme-bin'))
        self.assertEqual((self.current / 'background').resolve(), self.source)

    def test_scoped_theme_helper_applies_colors_without_reloading_compositor(self):
        fake_bin = self.locations['home'] / 'fake-bin'
        fake_bin.mkdir()
        call = self.locations['home'] / 'hyprctl-call'
        command = fake_bin / 'hyprctl'
        command.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$TEST_CALL"\nprintf "ok\\n"\n')
        command.chmod(0o755)
        environment = dict(os.environ, PATH=str(fake_bin) + os.pathsep + os.environ['PATH'], TEST_CALL=str(call))
        subprocess.run(['bash', str(ROOT / 'theme-bin/omarchy-restart-hyprctl')],
                       env=environment, check=True)
        args = call.read_text().splitlines()
        self.assertEqual(args[0], 'eval')
        self.assertIn('/current/theme/hyprland.lua', args[1])
        self.assertNotIn('reload', args)

    def test_autoreload_is_restored_when_theme_command_fails(self):
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            return '{"bool":false}' if '-j' in command else 'ok\n'
        with patch.object(appearance, 'run', side_effect=run):
            with self.assertRaises(RuntimeError):
                with appearance.pause_theme_autoreload():
                    raise RuntimeError('failed retint')
        self.assertIn('disable_autoreload = true', calls[1][-1])
        self.assertIn('disable_autoreload = false', calls[-1][-1])

    def test_existing_disabled_autoreload_setting_is_preserved(self):
        with patch.object(appearance, 'run', return_value='{"bool":true}') as run:
            with appearance.pause_theme_autoreload():
                pass
        self.assertEqual(run.call_count, 1)

    def test_managed_wallpaper_only_updates_link_without_resetting_renderer(self):
        other = self.source.with_name('other.png')
        other.write_bytes(b'fixture')
        with patch.object(appearance, 'run') as run:
            appearance.apply_look({'theme': 'old-theme', 'wallpaper': str(other)}, self.locations,
                                  renderer={'project': 'atlas', 'cache': '/fixture'})
        run.assert_not_called()
        self.assertEqual((self.current / 'background').resolve(), other)

    def test_managed_theme_forwards_prepared_cache_and_full_application_retint(self):
        def run(command, **kwargs):
            if '-j' in command:
                return '{"bool":true}'
            if command[:3] == ['omarchy', 'theme', 'set']:
                (self.current / 'theme.name').write_text(command[3])
            return 'ok\n'
        with patch.object(appearance, 'run', side_effect=run) as calls:
            appearance.apply_look({'theme': 'new-theme', 'wallpaper': str(self.source)}, self.locations,
                                  renderer={'project': 'atlas', 'cache': '/fixture'})
        theme = next(call for call in calls.call_args_list if call.args[0][:3] == ['omarchy', 'theme', 'set'])
        self.assertEqual(theme.kwargs['env']['OMARCHY_PROJECTS_TEMPLATE_CACHE'], '/fixture')
        self.assertEqual(theme.kwargs['env']['OMARCHY_PROJECTS_TARGET'], 'atlas')
        self.assertEqual(theme.kwargs['env']['OMARCHY_PROJECTS_RENDERER'], '1')


if __name__ == '__main__':
    unittest.main()
