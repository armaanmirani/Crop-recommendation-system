# Terra · Crop recommendation for sustainable agriculture

A responsive hackathon app that helps farmers explore crops using soil and climate
measurements. Trains **Random Forest and XGBoost** on the Crop Recommendation
Dataset associated with Kaggle, compares both models, and optionally ranks suitable
crops using Agmarknet mandi reports (via data.gov.in or official CSV exports),
expected yields, and cultivation costs.

## Run locally

### Windows: download and double-click

Download this repository using **Code → Download ZIP** on GitHub and extract it.
With Python 3.12 for Windows x64 installed, double-click **`RUN_APP.bat`** inside the
extracted folder. It explicitly selects Python 3.12, creates a dedicated
`.venv-windows` environment, installs prebuilt dependencies, and
opens the app in your browser once the server is ready. Keep the server window open.
The trained models are included; you do not need to train them again.

If you prefer Command Prompt, open it in the extracted folder and run:

```bat
py -3.12 -m venv .venv-windows
.venv-windows\Scripts\python.exe -m pip install --upgrade pip
.venv-windows\Scripts\python.exe -m pip install --only-binary=:all: -r requirements.lock.txt
.venv-windows\Scripts\python.exe run_local.py
```

Then open `http://localhost:5000` if the browser does not open automatically.

If pandas reports a Meson / `vswhere.exe` metadata error, pip is trying to compile
it instead of using a wheel. Install [Python 3.12.10, Windows installer (64-bit)](https://www.python.org/downloads/release/python-31210/)
and use the commands above. Your other Python versions and the old `.venv` can stay;
the launcher uses a separate environment. You do not need Visual Studio to run Terra.

### Linux / cloud development

Requires Python 3.12 (tested). No GPU or Kaggle account is needed. Core crop
recommendations work without an API key; live market lookup needs a data.gov.in key.
The dataset is included. Use the existing checkout; cloud tasks already have
isolated environments and do not need another Git worktree.

```bash
cd /workspace/Crop-recommendation-system
python -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python train.py
.venv/bin/python -m pytest -q
.venv/bin/python app.py
```

On your own computer, substitute your project directory and open
`http://localhost:5000`. On Windows, replace `.venv/bin/python` with
`.venv\Scripts\python.exe`. Set `PORT` to change the server port. Flask's included
server is for development; use a production WSGI server before public deployment.

## Deploy on Render

Create a Python Web Service connected to this repository's `main` branch.
Use these exact settings:

- **Build command:** `python -m pip install -r requirements.lock.txt`
- **Start command:** `python -m gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120`
- **Environment:** `PYTHON_VERSION=3.12.10`; optionally add `DATA_GOV_API_KEY` securely.

Gunicorn is included as a Linux/macOS dependency and omitted on Windows, where
`RUN_APP.bat` starts the local development server. A `gunicorn: command not found`
error means the production server was not installed in the runtime environment;
update the build/start commands above and redeploy the latest commit.
The trained models are included, so deployment does not require retraining.

## Demo walkthrough

Click **Load rice demo**, then **Find my crops**. Both models should recommend
rice for N=90, P=42, K=43, temperature=20.9°C, humidity=82%, pH=6.5,
and rainfall=203mm. A moderate water setting shows an irrigation caution.
Switch between models to compare them. Expand **Market prices & farm estimates**
to look up mandi reports or import a CSV, then enter expected yield (kg/ha) and
total cultivation cost (₹/ha). Manual prices (₹/kg) are also supported.
Download the resulting report as JSON.

## Agmarknet / data.gov.in market prices

Agmarknet supplies the daily mandi-price reports also published by India's Open
Government Data platform. They are the same underlying source, not two independent
market feeds. The server uses resource `9ef84268-d588-465a-a308-a864a43d0070`:

- [data.gov.in dataset](https://www.data.gov.in/resource/current-daily-price-various-commodities-various-markets-mandi)
- [Agmarknet portal](https://agmarknet.gov.in/)

For live lookup, obtain your API key through your data.gov.in account and configure
**`DATA_GOV_API_KEY`** securely on the server before starting it. In Codex cloud,
enter the value in environment settings, save the settings, and publish the
environment when ready. Never enter the key into a browser field or commit it.
Only `api.data.gov.in` receives the key; it is not exposed in responses, reports,
or frontend code. Outbound HTTPS to `api.data.gov.in` is required. The portal
domains are also included in the saved cloud network requirements.

In the app, select a crop, its sale commodity, and a **state**; optionally narrow
by district, exact mandi name, or report date. Each API page requests up to 100
reports. Next-page controls expose additional records; ordering is by date within
each returned page, not a claim of exhaustive latest prices across all mandis.
No match, stale data, missing credentials, rate limits, and upstream outages are
reported explicitly. Live upstream connectivity was not validated during development:
the API returned an upstream 503 and no key was configured. Tests mock the API;
no test fixture is shipped as real market data.

For failures, the UI shows a safe diagnostic code and Render logs include
`Market lookup failed: code=... status=...`. `API_KEY_MISSING` means the secret is
absent; `UPSTREAM_HTTP_401/403` means authorization or host access was denied;
`DNS_ERROR`, `UPSTREAM_TIMEOUT`, `CONNECTION_REFUSED`, and `CONNECTION_RESET`
identify network failures. `TLS_CERTIFICATE_ERROR` requires investigation of
certificate trust, never disabling verification. Upstream HTTP 5xx codes identify
portal/service failures. Exception text, credential-bearing request URLs, and API
key values are never logged. A 503 access-log entry alone cannot identify the cause.

Select **Use price** on a report to fill its modal price into the matching crop row.
Agmarknet's modal price is a representative reported price, not guaranteed revenue.
The API's INR/quintal values are divided by 100 to get INR/kg. Original min/max/modal
values, mandi, state, district, commodity, variety, grade, date, source, and conversion
are retained. Reports older than 7 days cannot be used automatically. Current prices
are not forecasts of the price at harvest. Match the variety and sale form to your
expected yield: rice defaults to **paddy**, not processed rice. Coconut auto-import is
disabled because reports may use counts of nuts rather than mass; confirm units
and weight before entering a manual kg price.

Without an API key, import a UTF-8 CSV exported from either official portal. Confirm
the export's unit is INR/quintal and choose its source. Standard data.gov.in columns
and common Agmarknet columns (`District Name`, `Market Name`, `Min Price (Rs./Quintal)`,
`Price Date`, etc.) are accepted. For state-specific exports without a State column,
the selected state is used and clearly flagged as user-supplied. Imports are limited
to 2 MB / 5,000 rows, filtered by your selection, and validated. Uploaded files are
not independently authenticated as official exports; their source is labeled
**user-supplied CSV**. No CAPTCHA bypass or scraping is used.

Enter yields and costs separately; a price-only row does not enter profit calculations.
Selected quote references are held in memory for one hour, cleared on server restart,
and validated server-side before calculating profit. Refresh/reimport an expired quote.
Changing its price manually removes source attribution and becomes a manual estimate.
The downloadable report includes the chosen reports and financial assumptions.

## Training and evaluation

- 2,200 rows, 22 classes; 100 samples per crop. Seven soil/climate features.
- Deterministic, stratified 60% training / 20% validation / 20% test split, seed 42.
- Two fixed model configurations; select by validation macro-F1, never test accuracy.
- Refit each model on training + validation (1,760 rows) and evaluate on the same
  untouched 440-row test set. Serving uses those tested artifacts; no test-set refit.
- `models/metrics.json` contains accuracy, macro-F1, class reports, confusion matrices,
  feature importances, splits, and data checksum. `models/crop_models.joblib` is generated
  locally and included in this repository for immediate testing. Run `train.py`
  to regenerate the artifacts after data or dependency changes.
- Trees do not require scaling. GPU training is unnecessary at this dataset size.

## Market and sustainability planning

The training CSV **does not contain market prices, yield, profit, location, or
irrigation measurements**. Financial results are a separate calculation:

`estimated profit = (price/kg × expected kg/ha − cost/ha) × area in hectares`

Candidate crops need model support of at least `max(5%, 25% of the top score)`.
Only these candidates can be ranked financially; a high price cannot promote an
unsuitable crop. When there are at least two candidates and complete estimates for
every candidate, market priority blends model score relative to the top score with
min–max normalized estimated profit. Equal profits retain suitability order.
Incomplete estimates retain suitability order and show a warning. Prices are official
reported observations, user-supplied exports, or explicitly manual estimates. Yields
and costs remain user assumptions; none are fabricated or predicted by the crop models.

Water demand categories and legume rotation notes are **illustrative heuristics**,
independent of the trained models. They do not calculate irrigation volumes or
guarantee sustainability. Water availability triggers cautions; it does not change
ML predictions. Scores are not calibrated probabilities of farming success.
Dataset test accuracy does not establish field performance. Match nutrient units
and rainfall period, consider season and regional conditions, and consult local
agricultural guidance before planting. Training-range violations are flagged.

See [dataset provenance](data/README.md) for the Kaggle link, actual mirror source,
checksum, and licensing verification limitation. No synthetic samples were used.

## API

- `GET /api/health`: models loaded and service ready.
- `GET /api/metadata`: crop labels, input ranges, training and evaluation details.
- `POST /api/recommend`: validated crop shortlist and model comparison.
- `GET /api/market-status`: configured-key presence (never its value), commodity mapping.
- `GET /api/market-prices?crop=rice&state=Maharashtra`: official API lookup.
  Optional `commodity`, `district`, `market`, ISO `date`, and `offset` filters.
- `POST /api/market-import`: multipart CSV `file`, `crop`, `state`, optional filters,
  `portal` (`agmarknet` or `data_gov`), and `confirmed_unit=INR/quintal`.

To use an imported/fetched report in a recommendation, add its `quote_id` to the
matching crop's market object. The server uses the registered quote's price and
provenance even if a different `price_per_kg` is sent. Manual objects have no quote ID.

Example body:

```json
{
  "N": 90, "P": 42, "K": 43,
  "temperature": 20.9, "humidity": 82, "ph": 6.5, "rainfall": 203,
  "model": "random_forest", "water_availability": "medium",
  "area_hectares": 1, "market_weight": 0.3,
  "market": {
    "rice": {"price_per_kg": 30, "yield_kg_per_hectare": 4000, "cost_per_hectare": 50000}
  }
}
```

The API rejects missing measurements, nonfinite values, unsupported crops/models,
invalid ranges, and incomplete market rows. Inputs are processed in memory;
there is no database or external AI service. Optional price lookup calls the
official data.gov.in API. Frontend fonts are optional Google
Fonts assets with local fallback fonts; predictions work without them.
