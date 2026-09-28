#!/usr/bin/env bash
set -euo pipefail

VERSION=$(node -p "require('./package.json').version")
echo "Publishing version $VERSION"

python -m build

git tag "v${VERSION}"
git push origin "v${VERSION}"

gh release create "v${VERSION}" \
  --title "v${VERSION}" \
  --generate-notes \
  dist/*

echo "Published darth-infra v${VERSION}"
