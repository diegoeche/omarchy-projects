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
