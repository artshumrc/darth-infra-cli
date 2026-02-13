#!/usr/bin/env bash
set -euo pipefail

# Install changesets and its changelog plugin into a temp location
npm install --no-save @changesets/cli @changesets/changelog-github

# Bump version via changesets
npx changeset version

# Clean up node artifacts so they don't get committed
rm -rf node_modules package-lock.json

# Sync version from package.json into pyproject.toml
python3 -c "
import json, re, pathlib
version = json.loads(pathlib.Path('package.json').read_text())['version']
pyproject = pathlib.Path('pyproject.toml')
content = pyproject.read_text()
content = re.sub(r'version\s*=\s*\"[^\"]+\"', f'version = \"{version}\"', content, count=1)
pyproject.write_text(content)
print(f'Synced pyproject.toml to version {version}')
"
