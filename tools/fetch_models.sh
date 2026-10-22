#!/usr/bin/env bash
# Downloads the free, Apache-2.0 licensed Kokoro-82M ONNX text-to-speech model (CPU, no GPU needed).
# Source: https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)/models"
mkdir -p "$DIR"
BASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
for f in kokoro-v1.0.onnx voices-v1.0.bin; do
  if [ ! -s "$DIR/$f" ]; then
    echo "Downloading $f ..."
    curl -L --fail --retry 4 -o "$DIR/$f" "$BASE/$f"
  fi
done
echo "Verifying checksums"
(cd "$DIR" && sha256sum -c <<'SUMS'
7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5  kokoro-v1.0.onnx
bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d  voices-v1.0.bin
SUMS
)
echo "Models ready in $DIR"
