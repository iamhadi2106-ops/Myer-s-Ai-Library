# HH Library

A small Python project. This repository contains helper scripts and data used for the HH Library project.

## Quickstart

- Create a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate  # on Windows: .venv\Scripts\Activate.ps1
```

- Install dependencies:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

- Run the environment check:

```bash
python check_env.py
```

## Files added
- `check_env.py` — environment checker
- `app.py` — project entrypoint (if applicable)

## GitHub
This repo includes a basic GitHub Actions workflow in `.github/workflows/python-ci.yml` to run on pushes and pull requests.

## License
This project is available under the MIT License. See `LICENSE` for details.
