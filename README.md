# Road to 21.1

A static web page that reads your own Garmin exports and tracks progress toward an injury-free half marathon.

- Runs entirely in your browser. No server, no account, no API key.
- Your data is stored in your browser (localStorage) and never leaves your device. Use **Back up** on the Data tab to save a copy.
- Add data from the Data tab: Activities CSV, a run's Laps CSV, or `garmin_runs.json` made by `tools/fetch_garmin.py`.
- Share card tab: photo + run stats + route from a GPX file, saved as a 1080x1080 PNG.

Not medical advice. The insights are rules of thumb; see a physio or doctor for pain that lingers.

## Publish on GitHub Pages
1. Create a new **public** repository on GitHub (for example `road-to-21`).
2. Upload `index.html`, the `vendor` folder, the `tools` folder, `README.md` and `.gitignore`.
3. Repository **Settings > Pages**: Source = *Deploy from a branch*, Branch = `main`, folder `/ (root)`. Save.
4. After a minute the page is at `https://<your-username>.github.io/road-to-21/`.

The repository is public, so never commit your own CSV, GPX or JSON exports or backups. `.gitignore` blocks them.

## Garmin download script (optional, runs on your computer)
`tools/fetch_garmin.py` (run `probe` first to see what Garmin returns) reads your Personal API key from the `GARMIN_PERSONAL_API_KEY` environment variable and writes `garmin_runs.json`. The key is never saved to disk and never goes into this page or the repository. It has not been tested against a live Garmin account.

## Third-party
`vendor/chart.umd.js` is Chart.js 4.4.1 (MIT licence, see `vendor/chart.js-LICENSE.md`).
