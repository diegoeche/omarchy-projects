import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import project_assets as assets
from omarchy_projects import paths


class AssetTests(unittest.TestCase):
    def test_aether_colorful_is_prepared_without_apply_and_reused_until_inputs_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            locations = paths(temporary)
            look = {'theme': 'fixture', 'wallpaper': '/synthetic/wallpaper.png', 'aether_variant': 'colorful'}
            calls = []
            def generate(command, **kwargs):
                calls.append(command)
                output = Path(command[command.index('--output') + 1])
                (output / 'colors.toml').write_text('background = "#010203"\naccent = "#456789"\n')
                return subprocess.CompletedProcess(command, 0, '', '')
            with patch.object(assets.shutil, 'which', return_value=sys.executable), patch.object(assets.subprocess, 'run', side_effect=generate):
                first = assets.prepare_aether_theme('atlas', look, 'a'*64, locations)
                self.assertEqual(assets.prepare_aether_theme('atlas', look, 'a'*64, locations), first)
                self.assertEqual(len(calls), 1)
                self.assertIn('--no-apply', calls[0])
                self.assertEqual(calls[0][calls[0].index('--extract-mode') + 1], 'colorful')
                target = locations['home'] / '.config/omarchy/themes' / first['theme']
                self.assertEqual((target / 'colors.toml').read_text(), 'background = "#010203"\naccent = "#456789"\n')
                self.assertEqual(json.loads((target / '.aether.json').read_text())['variant'], 'colorful')
                second = assets.prepare_aether_theme('atlas', look, 'b'*64, locations)
                third = assets.prepare_aether_theme('atlas', dict(look, aether_variant='pastel'), 'b'*64, locations)
                self.assertNotEqual(first['theme'], second['theme'])
                self.assertNotEqual(second['theme'], third['theme'])
                self.assertEqual(len(calls), 3)

    def test_missing_optional_aether_fails_without_creating_theme(self):
        with tempfile.TemporaryDirectory() as temporary:
            locations = paths(temporary)
            with patch.object(assets.shutil, 'which', return_value=None):
                with self.assertRaisesRegex(ValueError, 'not installed'):
                    assets.prepare_aether_theme('atlas', {'aether_variant': 'colorful'}, 'a'*64, locations)
            self.assertFalse((locations['home'] / '.config/omarchy/themes').exists())

    def test_generated_theme_is_saved_in_profile_and_used_by_shell_palette(self):
        with tempfile.TemporaryDirectory() as temporary:
            locations = paths(temporary)
            (locations['home'] / '.config/omarchy/themes/fixture').mkdir(parents=True)
            image = locations['home'] / 'wallpaper.png'
            image.write_bytes(b'synthetic wallpaper')
            config = {'preload_wallpapers': True, 'projects': [{'id': 'atlas', 'slot': 1,
                'appearance': {'theme': 'fixture', 'wallpaper': str(image), 'aether_variant': 'colorful'}}]}
            def generate(command, **kwargs):
                output = Path(command[command.index('--output') + 1])
                (output / 'colors.toml').write_text('background = "#010203"\n')
                return subprocess.CompletedProcess(command, 0, '', '')
            with patch.object(assets.shutil, 'which', return_value=sys.executable), patch.object(assets.subprocess, 'run', side_effect=generate) as calls, patch.object(assets, 'prepare_theme', return_value={'cache': '/fixture', 'colors': 'generated palette', 'shell': ''}):
                scene = assets.prepare_assets(config, locations)
                name = config['projects'][0]['appearance']['theme']
                self.assertIn('colorful', name)
                self.assertEqual(config['projects'][0]['appearance']['aether_variant'], 'colorful')
                self.assertEqual(scene['themes'][name]['colors'], scene['projects'][0]['colors'])
                assets.prepare_assets(config, locations)
                self.assertEqual(calls.call_count, 1)

    def test_content_deduplication_and_unchanged_manifest_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            locations = paths(temporary)
            theme = locations['home'] / '.config/omarchy/themes/fixture'
            theme.mkdir(parents=True)
            source = locations['home'] / 'one.png'
            source.write_bytes(b'synthetic image')
            other = source.with_name('copy.png')
            shutil.copyfile(source, other)
            projects = [{'id': name, 'slot': index + 1,
                         'appearance': {'theme': 'fixture', 'wallpaper': str(path)}}
                        for index, (name, path) in enumerate([('atlas', source), ('boreal', other)])]
            config = {'preload_wallpapers': True, 'projects': projects}
            with patch.object(assets, 'prepare_theme', return_value={'cache': '/fixture', 'colors': '', 'shell': ''}) as prepare:
                scene = assets.prepare_assets(config, locations)
                self.assertEqual(len(scene['assets']), 1)
                self.assertEqual(prepare.call_count, 1)
                manifest = locations['state'] / 'scene.json'
                first = manifest.stat().st_mtime_ns
                assets.prepare_assets(config, locations)
                self.assertEqual(manifest.stat().st_mtime_ns, first)

    def test_preparation_preserves_theme_overrides_and_invalidates_changed_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            locations = paths(temporary)
            package = Path(temporary) / 'package'
            theme = package / 'themes/fixture'
            theme.mkdir(parents=True)
            (theme / 'colors.toml').write_text('background = "#000000"\n')
            (theme / 'shell.toml').write_text('[bar]\nbackground = "#123456"\n')
            (theme / 'shell.menu.toml').write_text('[menu]\nbackground = "#abcdef"\n')
            (theme / 'hyprland.lua').write_text('-- custom border settings\n')
            with patch.dict(os.environ, OMARCHY_PATH=str(package)), patch.object(assets.subprocess, 'run') as run:
                first = assets.prepare_theme('fixture', locations)
                second = assets.prepare_theme('fixture', locations)
                self.assertEqual(first, second)
                self.assertEqual(run.call_count, 1)
                self.assertEqual((Path(first['cache']) / 'hyprland.lua').read_text(), '-- custom border settings\n')
                self.assertTrue((Path(first['cache']) / 'shell.menu.toml').is_file())
                (theme / 'colors.toml').write_text('background = "#111111"\n')
                third = assets.prepare_theme('fixture', locations)
                self.assertNotEqual(first['cache'], third['cache'])

    @unittest.skipUnless(shutil.which('node'), 'Node needed only for pure JavaScript checks')
    def test_motion_math_palette_endpoints_and_manifest_validation(self):
        subprocess.run(['node', str(ROOT / 'tests/motion_test.cjs')], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
