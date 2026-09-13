"""Query native Codex discovery without a model turn, credentials or generation."""
import json
from pathlib import Path
import select
import subprocess
import sys
import time


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if mode not in {'all', 'codex'}:
        raise SystemExit('Expected all or codex')
    process = subprocess.Popen(
        ['codex', 'app-server', '--stdio'], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )

    def request(identifier, method, params):
        process.stdin.write(json.dumps(dict(id=identifier, method=method, params=params)) + '\n')
        process.stdin.flush()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if not select.select([process.stdout], [], [], 1)[0]:
                continue
            line = process.stdout.readline()
            if not line:
                raise RuntimeError('Codex discovery process exited')
            response = json.loads(line)
            if response.get('id') == identifier:
                if 'error' in response:
                    raise RuntimeError('Codex discovery request failed')
                return response['result']
        raise TimeoutError('Codex discovery timed out')

    try:
        request(1, 'initialize', {'clientInfo': {'name': 'br_tooling_check', 'version': '1'}})
        process.stdin.write('{"method":"initialized"}\n')
        process.stdin.flush()
        data = request(2, 'skills/list', {'cwds': [str(Path.cwd())], 'forceReload': True})['data'][0]
        addy = [s for s in data['skills'] if s.get('pluginId') == 'agent-skills@agent-skills']
        higgs = [s for s in data['skills'] if s['name'].startswith('higgsfield-')]
        if len(addy) != 24 or not all(s['enabled'] for s in addy):
            raise RuntimeError('Expected 24 enabled native Addy skills')
        if any('browser-testing-with-devtools' in s['name'] for s in addy):
            raise RuntimeError('Unsupported browser skill found')
        expected = {'higgsfield-generate', 'higgsfield-brandkit',
                    'higgsfield-video-explainer', 'higgsfield-youtube-thumbnail'}
        if mode == 'all' and not expected <= {s['name'] for s in higgs if s['enabled']}:
            raise RuntimeError('Selected Higgsfield skills not discovered')
        # Check one selected skill is readable; never inject all skill bodies.
        selected = next(s for s in addy if s['name'].endswith(':code-review-and-quality'))
        if not Path(selected['path']).read_text().strip():
            raise RuntimeError('Selected skill is empty')
        print(json.dumps({'discovery': 'PASS', 'addy_enabled': len(addy),
                          'higgsfield_enabled': len(higgs), 'selected_read': selected['name'],
                          'model_turns': 0, 'generation_requests': 0}))
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


if __name__ == '__main__':
    main()
