"""Prepare immutable wallpaper and palette inputs outside the animation path."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

from project_appearance import AppearanceError, resolve_look, write_json


def file_signature(paths):
    digest = hashlib.sha256()
    digest.update(b'omarchy-projects-prepared-themes-v2')
    for path in sorted(set(paths)):
        stat = path.stat()
        digest.update(str(path).encode())
        digest.update(f'{stat.st_size}:{stat.st_mtime_ns}'.encode())
    return digest.hexdigest()


def prepare_theme(theme, locations):
    package = Path(os.environ.get('OMARCHY_PATH', '/usr/share/omarchy'))
    roots = [package / 'themes' / theme, locations['home'] / '.config/omarchy/themes' / theme]
    templates = [package / 'default/themed', locations['home'] / '.config/omarchy/themed']
    inputs = [file for root in roots + templates if root.exists()
              for file in root.glob('*') if file.is_file() and file.suffix not in {'.png', '.jpg', '.webp'}]
    inputs += [package / 'bin' / name for name in ('omarchy-theme-set-templates',
               'omarchy-theme-color', 'omarchy-theme-set-glass') if (package / 'bin' / name).is_file()]
    signature = file_signature(inputs)
    cache = locations['data'] / 'prepared-themes' / signature
    if not (cache / '.complete').exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.prepare-', dir=cache.parent) as temporary:
            home = Path(temporary)
            staged = home / '.local/state/omarchy/current/next-theme'
            staged.mkdir(parents=True)
            for root in roots:
                if not root.is_dir():
                    continue
                for source in root.iterdir():
                    if source.is_file() and source.suffix.lower() not in {
                            '.png', '.jpg', '.jpeg', '.webp', '.gif', '.mp4', '.webm', '.mkv', '.mov'}:
                        shutil.copyfile(source, staged / source.name)
            custom = templates[1]
            if custom.is_dir():
                link = home / '.config/omarchy/themed'
                link.parent.mkdir(parents=True)
                link.symlink_to(custom)
            environment = dict(os.environ, HOME=str(home), OMARCHY_PATH=str(package),
                               XDG_CONFIG_HOME=str(home / '.config'), XDG_STATE_HOME=str(home / '.local/state'))
            if not (staged / 'colors.toml').exists():
                subprocess.run(['/usr/bin/omarchy-theme-colors-from-alacritty', str(staged)],
                               env=environment, check=True, capture_output=True, timeout=30)
            subprocess.run(['/usr/bin/omarchy-theme-set-templates'], env=environment,
                           check=True, capture_output=True, timeout=30)
            if not (staged / 'colors.toml').exists():
                raise AppearanceError('Theme has no palette: ' + theme)
            (staged / '.complete').write_text(signature)
            # Only generated color/config files, never wallpapers or source code.
            staged.rename(cache)
    return {'cache': str(cache), 'colors': (cache / 'colors.toml').read_text(),
            'shell': (cache / 'shell.toml').read_text() if (cache / 'shell.toml').exists() else ''}


def image_dimensions(path):
    with path.open('rb') as stream:
        head = stream.read(24)
    if head.startswith(b'\x89PNG\r\n\x1a\n') and len(head) >= 24:
        return struct.unpack('>II', head[16:24])
    return (0, 0)


def prepare_assets(config, locations, write=True):
    if not config.get('preload_wallpapers'):
        return
    assets, projects, themes = {}, [], {}
    for project in config['projects']:
        if 'appearance' not in project:
            projects.append({'id': project['id'], 'slot': project['slot'], 'asset': '', 'colors': '', 'shell': ''})
            continue
        look = resolve_look(project['appearance'], locations)
        path = Path(look['wallpaper'])
        if path.suffix.lower() in {'.mp4', '.webm', '.mkv', '.mov', '.gif'}:
            raise AppearanceError('Preloaded project motion currently supports still wallpapers only')
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        key = digest.hexdigest()
        if key not in assets:
            width, height = image_dimensions(path)
            assets[key] = {'key': key, 'path': str(path), 'width': width, 'height': height}
        if look['theme'] not in themes:
            themes[look['theme']] = prepare_theme(look['theme'], locations)
        palette = themes[look['theme']]
        projects.append({'id': project['id'], 'slot': project['slot'], 'asset': key,
                         'colors': palette['colors'], 'shell': palette['shell']})
    scene = {'version': 1, 'projects': projects, 'assets': list(assets.values()), 'themes': themes,
             'duration': config.get('workspace_transition', {}).get('duration_ms', 200),
             'style': config.get('workspace_transition', {}).get('style', 'slide')}
    target = locations['state'] / 'scene.json'
    rendered = json.dumps(scene, sort_keys=True)
    if write and (not target.exists() or json.dumps(json.loads(target.read_text()), sort_keys=True) != rendered):
        write_json(target, scene)
    return scene
