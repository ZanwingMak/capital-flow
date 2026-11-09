"""Validate tag/version and join independently verified native release artifacts."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

PLATFORMS = {
    'macOS-arm64': ({'Flowdesk-macOS-arm64.zip', 'Flowdesk-macOS-arm64.dmg'}, set()),
    'Windows-amd64': ({'Flowdesk-Windows-amd64.zip'}, {'Flowdesk-Windows-amd64-Setup.exe'}),
}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check_tag(tag):
    version = json.loads(Path(__file__).with_name('mygo.json').read_text(encoding='utf-8'))['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version) or tag != f'v{version}':
        raise ValueError(f'Release tag must equal stable application version v{version}: {tag}')
    print(f'Validated release tag {tag}')


def assemble(source, output):
    # Validate the entire input before writing any publishable output.
    verified = {}
    for platform, (required, optional) in PLATFORMS.items():
        directory = source / f'Flowdesk-{platform}'
        sums = directory / 'SHA256SUMS.txt'
        expected = {}
        for line in sums.read_text(encoding='utf-8').splitlines():
            match = re.fullmatch(r'([a-f0-9]{64})  ([A-Za-z0-9.-]+)', line)
            if not match:
                raise ValueError(f'Invalid checksum line: {sums.name}')
            checksum, name = match.groups()
            if name in expected or name not in required | optional:
                raise ValueError(f'Duplicate or unexpected release file: {name}')
            expected[name] = checksum
        actual = {path.name for path in directory.iterdir()}
        if not required <= expected.keys() or actual != set(expected) | {'SHA256SUMS.txt'}:
            raise ValueError(f'Missing or unexpected {platform} artifacts')
        for name, checksum in expected.items():
            path = directory / name
            if path.is_symlink() or not path.is_file() or digest(path) != checksum:
                raise ValueError(f'Checksum mismatch or invalid artifact: {name}')
            verified[name] = (path, checksum)
    output.mkdir(parents=True, exist_ok=False)
    for name, (path, _) in sorted(verified.items()):
        shutil.copy2(path, output / name)
    (output / 'SHA256SUMS.txt').write_text(''.join(
        f'{checksum}  {name}\n' for name, (_, checksum) in sorted(verified.items())), encoding='utf-8')
    print(f'Assembled {len(verified)} verified native assets and one SHA256SUMS.txt')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-tag', required=True)
    parser.add_argument('--artifacts', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    check_tag(args.check_tag)
    if bool(args.artifacts) != bool(args.output):
        parser.error('--artifacts and --output must be supplied together')
    if args.artifacts:
        assemble(args.artifacts, args.output)


if __name__ == '__main__':
    main()
