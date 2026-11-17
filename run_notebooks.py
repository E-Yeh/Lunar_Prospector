"""Export SELENE.ipynb into application modules and run Streamlit."""
import argparse
import ast
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
MODULES = ('app', 'core', 'rasters', 'test_app')

def export_notebooks(root=ROOT):
    """Export marked cells in order; validate every module before writing any."""
    root = Path(root).resolve()
    notebook = json.loads((root / 'SELENE.ipynb').read_text(encoding='utf-8-sig'))
    parts = {name: [] for name in MODULES}
    for index, cell in enumerate(notebook.get('cells', []), 1):
        if cell.get('cell_type') != 'code':
            continue
        source = cell.get('source', [])
        source = source if isinstance(source, str) else ''.join(source)
        if not source.strip():
            continue
        tags = cell.get('metadata', {}).get('tags', [])
        targets = [tag[7:] for tag in tags if tag.startswith('export:')]
        if 'notebook-only' in tags:
            if targets:
                raise ValueError(f'Cell {index} cannot be both notebook-only and exported.')
            continue
        if len(targets) != 1 or targets[0] not in MODULES:
            raise ValueError(f'Cell {index} needs exactly one export:module tag, or notebook-only.')
        name = targets[0]
        if source.splitlines()[0] != f'# export: {name}.py':
            raise ValueError(f'Cell {index}: visible export marker must match export:{name} tag.')
        try:
            ast.parse(source, filename=f'SELENE.ipynb cell {index}')
        except SyntaxError as error:
            raise ValueError(f'SELENE.ipynb cell {index}: use standard Python, not notebook magics. {error}') from error
        parts[name].append(f'# SELENE.ipynb cell {index}\n{source}\n')
    sources = {}
    for name, chunks in parts.items():
        if not chunks:
            raise ValueError(f'SELENE.ipynb has no code for {name}.py')
        sources[name] = '# GENERATED FROM SELENE.ipynb. Edit the notebook, not this file.\n' + '\n'.join(chunks)
        compile(sources[name], f'{name}.py', 'exec')
    for name, source in sources.items():
        target = root / f'{name}.py'
        temporary = target.with_suffix('.tmp')
        temporary.write_text(source, encoding='utf-8')
        temporary.replace(target)
    return root

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8503)
    parser.add_argument('--check', action='store_true', help='Validate and export without starting a server.')
    parser.add_argument('--test', action='store_true', help='Run notebook-exported tests; may download real source data.')
    args = parser.parse_args()
    runtime = export_notebooks()
    if args.check:
        print(f'Validated SELENE.ipynb and exported {len(MODULES)} modules to {runtime}')
        return 0
    environment = os.environ.copy()
    environment['SELENE_DATA_DIR'] = str(ROOT / '.data')
    if args.test:
        command = [sys.executable, '-m', 'unittest', 'discover', '-s', str(runtime), '-v']
    else:
        if not 1 <= args.port <= 65535:
            parser.error('--port must be between 1 and 65535')
        command = [sys.executable, '-m', 'streamlit', 'run', str(runtime / 'app.py'),
                   '--server.address', '127.0.0.1', '--server.headless', 'true',
                   '--server.port', str(args.port), '--browser.gatherUsageStats', 'false']
        print(f'Notebook source exported. Open http://127.0.0.1:{args.port}', flush=True)
    # Run from the project root so Streamlit loads the project's theme configuration.
    process = subprocess.Popen(command, cwd=ROOT, env=environment)
    try:
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        return process.wait()

if __name__ == '__main__':
    raise SystemExit(main())
