# Contributing to meshctx

We welcome contributions of all kinds — code, docs, plugins, bug reports, and ideas.

## How to Contribute

### 1. Find an Issue

- Check [GitHub Issues](https://github.com/meshctx/meshctx/issues)
- Look for `good first issue` or `help wanted` tags
- Or open a new issue to discuss your idea

### 2. Fork & Clone

```bash
git clone https://github.com/YOUR_USERNAME/meshctx.git
cd meshctx
pip install -e ".[dev]"
```

### 3. Create a Branch

```bash
git checkout -b feature/my-feature
# or: fix/my-fix, docs/my-docs, plugin/my-plugin
```

### 4. Write Code

- Follow existing code style (PEP 8)
- Add tests for new functionality
- Update docs if needed
- Run tests before committing:

```bash
pytest tests/ -v
```

### 5. Commit

```bash
git add .
git commit -m "feat: add my feature

Detailed description of what changed and why."
```

Commit message format: [Conventional Commits](https://www.conventionalcommits.org/)
- `feat:` new feature
- `fix:` bug fix
- `docs:` documentation
- `test:` tests
- `refactor:` code restructuring
- `perf:` performance improvement

### 6. Push & Pull Request

```bash
git push origin feature/my-feature
```

Then open a PR on GitHub. Fill in the template.

## Development Setup

```bash
# Clone
git clone https://github.com/meshctx/meshctx.git
cd meshctx

# Virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v --cov=src

# Run linting
flake8 src/ tests/
black --check src/ tests/
```

## Project Structure

```
meshctx/
├── src/
│   └── core/
│       ├── kernel.py           # Microkernel + event bus
│       ├── memory_hierarchy.py # L0-L4 memory
│       ├── metacognition.py    # Self-learning
│       └── orchestrator.py     # Multi-agent
├── tests/
├── docs/
├── examples/
├── .github/
│   ├── workflows/
│   │   └── ci.yml
│   ├── ISSUE_TEMPLATE/
│   └── PULL_REQUEST_TEMPLATE.md
├── README.md
├── CONTRIBUTING.md
├── LICENSE
└── pyproject.toml
```

## Code of Conduct

Be respectful. Be constructive. Be collaborative.

## Questions?

- [Discord](https://discord.gg/meshctx)
- [GitHub Discussions](https://github.com/meshctx/meshctx/discussions)
- Email: jason@meshctx.dev
