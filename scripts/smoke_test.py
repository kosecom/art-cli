"""Opt-in native VectorCraft save/export/reopen smoke test; never overwrites files."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import xml.etree.ElementTree as ET
import zlib


def png_pixels(path):
    data = path.read_bytes()
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('Invalid PNG signature')
    offset = 8
    compressed = bytearray()
    header = None
    while offset < len(data):
        length = struct.unpack('>I', data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        chunk = data[offset + 8:offset + 8 + length]
        crc = struct.unpack('>I', data[offset + 8 + length:offset + 12 + length])[0]
        if zlib.crc32(kind + chunk) & 0xffffffff != crc:
            raise ValueError('PNG CRC mismatch')
        if kind == b'IHDR':
            header = chunk
        if kind == b'IDAT':
            compressed.extend(chunk)
        offset += length + 12
        if kind == b'IEND':
            break
    if header is None or not compressed:
        raise ValueError('Incomplete PNG')
    return header, zlib.decompress(compressed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True, help='New absolute output directory')
    args = parser.parse_args()
    if not args.home.is_absolute() or not args.out.is_absolute():
        parser.error('home and out must be absolute paths')
    installed = args.home / 'plugins/art-cli'
    if not (installed / 'art_cli/api.py').is_file():
        parser.error('Install ART-CLI into this home first')
    args.out.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(installed))
    from art_cli.api import dispatch
    def call(operation, arguments):
        result = dispatch(operation, arguments, home=args.home)
        if not result.get('ok') or any(s['result'].get('isError') for s in result.get('steps', [])):
            raise RuntimeError(json.dumps(result))
        return result
    def step(tool, arguments):
        return {'app': 'vectorcraft', 'tool': tool, 'arguments': arguments}
    native = args.out / 'smoke.vectorcraft'
    svg = args.out / 'smoke.svg'
    png = args.out / 'smoke.png'
    reopened = args.out / 'smoke-reopened.png'
    result = call('batch', {'steps': [
        step('run_command', {'command': 'file.new', 'params': {'name': 'ART-CLI smoke test', 'width': 640, 'height': 320, 'units': 'Pixels', 'backgroundContents': 'white', 'colorMode': 'rgb'}}),
        step('draw_path', {'d': 'M120 240 V80 H160 L240 180 V80 H280 V240 H240 L160 140 V240 Z', 'fill': '#142A38', 'stroke': 'none'}),
        step('draw_path', {'d': 'M340 80 H380 L460 240 H420 Z', 'fill': '#00BFA6', 'stroke': 'none'}),
        step('save_file', {'path': str(native)}),
        step('export', {'path': str(svg), 'format': 'svg'}),
        step('export', {'path': str(png), 'format': 'png'}),
    ]})
    if json.loads(native.read_text(encoding='utf-8')).get('format') != 'vectorcraft':
        raise ValueError('Not a native VectorCraft document')
    if not ET.parse(svg).getroot().tag.endswith('svg'):
        raise ValueError('Invalid SVG')
    call('batch', {'steps': [step('open_file', {'path': str(native)}), step('inspect_document', {}), step('export', {'path': str(reopened), 'format': 'png'})]})
    first = png_pixels(png)
    if first != png_pixels(reopened):
        raise ValueError('Fresh reopen PNG pixels differ')
    report = {'ok': True, 'platform': result['platform'], 'app': 'vectorcraft',
              'fresh_reopen_png_match': True, 'size': struct.unpack('>II', first[0][:8]),
              'files': [{'name': p.name, 'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in (native, svg, png, reopened)]}
    (args.out / 'verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
