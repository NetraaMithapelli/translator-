# Compliance Translation Service

Backend API that translates the human-readable parts of a compliance
result (product name, status, rule descriptions, etc.) into an Indian
language, for the SIH compliance-checking project's Translate button.

## What it does

- Frontend sends a compliance JSON result + a target language code to
  this backend.
- Backend translates only the human-readable fields (e.g. `product_name`,
  `status`) and leaves every machine-readable field (`product_id`,
  numbers, timestamps) exactly as-is.
- For status codes like `NON_COMPLIANT`, the original value is kept
  unchanged and a new `status_translated` field is added next to it, so
  nothing downstream that depends on the exact status string breaks.
- Returns the translated JSON back to the frontend, along with timing
  info (how long translation took).

## Project structure

```
translator/
├── main.py                          # App entrypoint — run this to start the server
├── api.py                           # Handles the /api/translate HTTP endpoint
├── translator_service.py            # Core logic: glossary → cache → provider → merge back
├── field_mapper.py                  # Figures out which JSON fields are translatable
├── glossary.py                      # Fixed correct translations for status words
├── cache.py                         # Remembers translations already done (faster/cheaper)
├── config.py                        # Settings: supported languages, timeouts, etc.
├── models.py                        # Request/response formats
├── providers/                       # Pluggable translation backends
│   ├── libretranslate_provider.py   # Currently in use (free, self-hosted)
│   ├── bhashini_provider.py         # Government of India (pending approval)
│   ├── google_translate_provider.py # Google Cloud (needs billing account)
│   ├── mymemory_provider.py         # Free, zero-setup backup
│   └── mock_provider.py             # Fake translation, for testing only
├── tests/                           # Automated tests
├── requirements.txt                 # Python packages needed

```

## Requirements

- Python 3.10+
- Packages in `requirements.txt` (`pip install -r requirements.txt`)
- **LibreTranslate running separately** (currently the active provider) —
  install with `pip install libretranslate`

## Current setup (what's actually running right now)

- **Provider:** LibreTranslate, self-hosted locally, free, no API key
- **Working languages right now: Hindi (`hi`) and Bengali (`bn`) only.**
  LibreTranslate doesn't have models for Marathi, Tamil, Telugu,
  Gujarati, Kannada, Malayalam, Punjabi, or Odia. Requesting those will
  return an error until we switch to a provider with full coverage
  (Bhashini, once its manager approval clears, or Google Cloud).
- The architecture supports all 10 target languages and any provider —
  switching providers later is a one-line change in `.env`, no code
  changes needed.

## How to run it

You need **two things running at the same time**, in two separate
terminals:

**Terminal 1 — LibreTranslate (the translation engine):**
```powershell
libretranslate --load-only en,hi,mr,bn,ta,te,gu,kn,ml,pa
```
Wait until it prints `Running on http://127.0.0.1:5000`. Leave it open.

**Terminal 2 — the backend API:**
```powershell
cd "path\to\translator fixed"
venv\Scripts\Activate.ps1
python -m uvicorn translator.main:app --reload --port 8001
```
Wait until it prints `Application startup complete.`

## Configuration (`.env`)

Located at `translator fixed\.env` (same folder you run uvicorn from,
**not** inside the `translator\` subfolder). Key settings:

```
TRANSLATION_PROVIDER=libretranslate
LIBRETRANSLATE_URL=http://localhost:5000
REQUEST_TIMEOUT_SECONDS=20
```

To switch providers later, change `TRANSLATION_PROVIDER` to `google`,
`bhashini`, `mymemory`, or `mock`, and fill in that provider's key(s)
further down in the same file. Restart uvicorn (full stop/start, not
just `--reload`) after any `.env` change.

## Testing it manually

1. Open **http://localhost:8001/docs** in a browser
2. Click **POST /api/translate** → **Try it out**
3. Use this example (a pre-filled one also appears automatically):
```json
{
  "target_language": "hi",
  "data": {
    "product_id": "LOCAL_SNACK_002",
    "product_name": "Demo Local Snack",
    "status": "NON_COMPLIANT",
    "rules_checked": 12,
    "rules_passed": 5,
    "rules_failed": 5,
    "generated_at": "2026-09-15T12:30:00Z"
  }
}
```
4. Click **Execute** — check the response: `product_id`, numbers, and
   `generated_at` should be unchanged; `product_name` should be real
   Hindi text; `status` stays `NON_COMPLIANT` with a new
   `status_translated` field alongside it.

Check `http://localhost:8001/health` any time to confirm the server is
up and which provider it's using.

## Frontend integration

The frontend's Translate button should:

1. `POST` the compliance result JSON (as-is) plus the chosen
   `target_language` to `http://localhost:8001/api/translate`
2. On `success: true` — use the returned `data` object to display
   results. For `status`, show `status_translated` to the user but keep
   using the original `status` field for any logic/styling that depends
   on the exact value.
3. On `success: false` — show `error.message` to the user (already
   written to be safe/user-facing).
4. **For now, only offer Hindi and Bengali as language choices in the
   UI** — other languages will return an error until a fuller-coverage
   provider (Bhashini/Google) is switched on.

## Automated tests (no server needed)

```powershell
python -m unittest discover -s translator\tests
```
Runs offline against a fake provider — confirms the core logic (field
extraction, batching, caching, error handling) works correctly.

## Known limitations / next steps

- Only 2 of 10 target languages work today (LibreTranslate's coverage
  gap) — switch providers once Bhashini's manager approval clears, or
  set up Google Cloud with billing, for full coverage.
- LibreTranslate's first translation after startup is slow (model
  warm-up) — do one "throwaway" translation before a live demo so it's
  already warmed up.
