# SeeArt

SeeArt is a small local-first web app that tracks current and upcoming exhibitions for configured museums and galleries.

It intentionally avoids copying exhibition descriptions. Each card links to the source exhibition page.

## Run Locally

```bash
SEEART_ADMIN_TOKEN=<your-local-refresh-token> python3 app.py
```

Then open:

```text
http://127.0.0.1:8000
```

## Refresh Data

For local development, refresh from the command line:

```bash
python3 -m seeart.scraper
```

Or visit:

```text
http://127.0.0.1:8000/admin
```

Enter the same token you set in `SEEART_ADMIN_TOKEN`. The hosted GitHub Pages site does not publish or use this admin page.

For the hosted website, use GitHub Actions:

1. Go to the repository's Actions tab.
2. Select `Refresh and deploy SeeArt`.
3. Click `Run workflow`.
4. Leave the branch as `main` and confirm.

The `pages-build-deployment` entries are GitHub's internal Pages deployment records. You do not run those directly.

## Add Venues, Tabs, Or Cities

Edit:

```text
config/venues.json
```

Each venue belongs to a city and tab. Later cities can be added by adding more venue entries with a new `city` value.

## Data Cache

Scraped data is written to:

```text
data/exhibitions.json
```

The app serves cached data so public visitors do not trigger scrapes.

Proxied card images are cached under:

```text
data/image-cache/
```

That folder is ignored by git and can be safely regenerated.

## Free GitHub Hosting

This repo is set up for GitHub Pages through `.github/workflows/refresh-and-deploy.yml`.

The workflow:

1. Runs `python -m seeart.scraper`.
2. Preserves the last deployed cache for venues that block scraping during a refresh.
3. Builds a static site from `static/` plus the refreshed `data/exhibitions.json`.
4. Deploys that static site to GitHub Pages.

It runs weekly on Monday at 13:00 UTC, which is around 9am New York time during daylight saving time and 8am during standard time. It can also be run manually from the GitHub Actions tab.

The static GitHub Pages version reads `data/exhibitions.json` directly. The local Python server still uses `/api/exhibitions` and `/api/image`.

For the first deployment, enable GitHub Pages in the repository settings:

1. Go to Settings -> Pages.
2. Set Source to GitHub Actions.
3. Save, then run the `Refresh and deploy SeeArt` workflow manually or push another commit.
