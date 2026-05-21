# Contributing

Thanks for helping improve SCT. The project aims to stay reliable, transparent, and respectful to crawled websites.

## Local Setup

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests
```

## Development Guidelines

- Keep crawling polite: respect robots, rate limits, and site resources.
- Add tests for every bug fix or analyzer behavior change.
- Prefer deterministic local fixtures over live website tests.
- Avoid committing generated folders such as `output/`, `state/`, `logs/`, and `__pycache__/`.
- Keep default configs safe for public repositories.

## Pull Requests

Before opening a PR, run:

```bash
python -B -m compileall -q seo_crawler/seo_crawler tests
python -B -m unittest discover -s tests
```
