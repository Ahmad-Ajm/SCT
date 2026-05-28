# Lighthouse import example

1. Run Lighthouse and save JSON here (or in `external_data/lighthouse/`):
   ```bash
   lighthouse https://example.com/ --output=json \
     --output-path=./external_data/lighthouse/home.json --quiet --chrome-flags="--headless"
   ```
2. Enable in `config.yaml`:
   ```yaml
   integrations:
     lighthouse:
       enabled: true
       folder: "./external_data/lighthouse"
   ```
3. Run SCT. Output: `lighthouse_import.csv` with performance/accessibility/best-practices/seo (0–100).

Both Lighthouse CLI JSON and PageSpeed Insights API JSON (with `lighthouseResult`) are supported.
