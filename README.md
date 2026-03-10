# Callie - Daily Macro Tracker

A Streamlit app for tracking daily meals, visualizing macro progress, and using AI-assisted meal parsing.

## Features

- Daily macro dashboard with gauge charts for calories, protein, fat, cholesterol, and carbs.
- Meal logging form with validation for numeric macro inputs.
- AI-assisted meal parsing in `Consult Callie` (OpenAI) to prefill meal fields.
- Quick-add buttons from Airtable `preset_meals` (top 3 common meals).
- Sidebar navigation with active tab highlighting:
	- `Daily Macro Dashboard`
	- `Log Your Meals`
	- `Update Profile`
- `Update Profile` page to:
	- Update macro goals (saved to Airtable `Goals` table)
	- Manage 3 common meal slots (add/update/delete)
- Meal history table and CSV export.
- Update existing logged meals by `meal_id`.

## App Navigation

- `Daily Macro Goals` is always shown at the top of the left sidebar.
- Use the sidebar button tabs (not radio buttons) to switch pages.
- `Daily Macro Dashboard` is the default landing page.

## Airtable Tables

### `Meals`

Expected fields:

- `meal_id` (autonumber)
- `date`
- `meal`
- `calories_kcal`
- `protein_g`
- `fat_g`
- `cholesterol_mg`
- `carbs_g`

### `preset_meals`

Expected fields:

- `meal_id` (autonumber)
- `meal`
- `calories_kcal`
- `protein_f`
- `carbs_g`

Note: The app fetches the top 3 rows from `preset_meals`, sorted by `meal_id`.

### `Goals`

Expected fields (recommended):

- `calories_kcal`
- `protein_g`
- `fat_g`
- `cholesterol_mg`
- `carbs_g`

The app reads the first record in `Goals` for dashboard/sidebar targets and updates that record when you save goals in `Update Profile`.
If no record exists, the app creates one on first save.

## Setup

1. Create and activate a Python environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create `.streamlit/secrets.toml` with at least:

```toml
AIRTABLE_API_KEY="your_airtable_api_key"
AIRTABLE_BASE_ID="your_airtable_base_id"
OPENAI_API_KEY="your_openai_api_key"
```

## Run

```bash
streamlit run macro_tracker_app.py
```

## Test OpenAI (IDE)

Use these commands in the VS Code terminal from the project root.

1. End-to-end OpenAI test (API call + parse):

```bash
python openai_api.py
```

Enter a meal description when prompted. Expected output includes:

- `OpenAI raw response:`
- `Parsed macro tuple:`

2. Parser-only test (no API call):

```bash
python -c "from openai_api import parse_openai_macro_response; s='{\"Meal\":\"Chicken Rice\",\"Calories\":\"400kcal\",\"Protein\":\"25g\",\"Fat\":\"10g\",\"Cholesterol\":\"70mg\",\"Carbs\":\"50g\"}'; print(parse_openai_macro_response(s))"
```

Expected tuple:

```text
('Chicken Rice', 400, 25, 10, 70, 50)
```

3. Check model access for your API key:

```bash
python -c "from openai_api import get_openai_client; c=get_openai_client(); print([m.id for m in c.models.list().data][:30])"
```

### Common OpenAI Errors

- `insufficient_quota` or `429`: billing/quota issue in your OpenAI project.
- `model_not_found`: model name is not available to your API key/project.
- `api_key client option must be set`: your key is not being loaded in that command context.

## OpenAI Model Used

- Current default model: `gpt-4o-mini`
- Configured in: `openai_api.py` inside `get_macros_from_meal_description(..., model="gpt-4o-mini", ...)`

If you want to switch models, update that default model argument to one available in your OpenAI project.

## Notes

- Macro goals are loaded from Airtable `Goals` into session state at startup, then persisted back to Airtable on save.
- Quick-add preset macros map to calories, protein, and carbs; fat/cholesterol stay blank unless manually entered.