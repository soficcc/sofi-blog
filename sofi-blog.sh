#!/usr/bin/env bash
# Starts the sofi-blog helper. The first run creates the conda environment (takes a minute).
set -e
cd "$(dirname "$0")"
ENV_NAME=sofi-blog

if ! command -v conda >/dev/null 2>&1; then
  echo "conda isn't available in this terminal. Install Miniforge (or Miniconda) and try again."
  exit 1
fi
eval "$(conda shell.bash hook)"
if ! conda env list | grep -qE "^${ENV_NAME}[[:space:]]"; then
  echo "✦ first run: creating the '${ENV_NAME}' conda environment…"
  conda env create -f environment.yml
fi
conda activate "$ENV_NAME"
if [ ! -f config.toml ]; then
  cp config.example.toml config.toml
  echo "✦ made config.toml from the example. Add your keys there when you're ready (see README)."
fi
python sofi-blog.py "$@"
