"""Release aggregation refuses partial or tampered platform artifacts."""
from pathlib import Path
import tempfile
import unittest

from desktop.prepare_release import PLATFORMS, assemble, check_tag, digest


class ReleaseTests(unittest.TestCase):
    def fixture(self, root, installer=False):
        source = root / 'input'
        for platform, (required, optional) in PLATFORMS.items():
            directory = source / f'Flowdesk-{platform}'
            directory.mkdir(parents=True)
            names = required | (optional if installer else set())
            for name in names:
                (directory / name).write_bytes(b'synthetic release checksum fixture')
            (directory / 'SHA256SUMS.txt').write_text(''.join(
                f'{digest(directory / name)}  {name}\n' for name in sorted(names)), encoding='utf-8')
        return source

    def test_both_platforms_join_with_and_without_nsis(self):
        for installer in (False, True):
            with self.subTest(installer=installer), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = self.fixture(root, installer)
                output = root / 'output'
                assemble(source, output)
                sums = (output / 'SHA256SUMS.txt').read_text().splitlines()
                self.assertEqual(len(sums), 4 if installer else 3)
                for line in sums:
                    checksum, name = line.split('  ')
                    self.assertEqual(digest(output / name), checksum)

    def test_partial_tampered_unlisted_and_traversal_input_fail_before_output(self):
        for failure in ('missing-platform', 'tampered', 'unlisted', 'traversal', 'missing-dmg'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = self.fixture(root)
                mac = source / 'Flowdesk-macOS-arm64'
                if failure == 'missing-platform':
                    (source / 'Flowdesk-Windows-amd64/SHA256SUMS.txt').unlink()
                elif failure == 'tampered':
                    (mac / 'Flowdesk-macOS-arm64.zip').write_bytes(b'tampered')
                elif failure == 'unlisted':
                    (mac / 'unknown.exe').write_bytes(b'unlisted')
                elif failure == 'missing-dmg':
                    (mac / 'Flowdesk-macOS-arm64.dmg').unlink()
                else:
                    (mac / 'SHA256SUMS.txt').write_text('0' * 64 + '  ../outside.zip\n')
                with self.assertRaises((ValueError, FileNotFoundError)):
                    assemble(source, root / 'output')
                self.assertFalse((root / 'output').exists())

    def test_tag_matches_stable_application_version(self):
        import json
        version = json.loads((Path(__file__).resolve().parents[1] / 'desktop/mygo.json').read_text())['version']
        check_tag(f'v{version}')
        for tag in (version, 'v999.999.999', f'v{version}-rc1'):
            with self.assertRaises(ValueError):
                check_tag(tag)
