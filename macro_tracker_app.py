import streamlit as st
import pandas as pd
import logging
from pyairtable import Table
import requests
import pytz
import plotly.graph_objects as go
from datetime import datetime, date, timedelta, timezone
import openai
import sys # Import the sys module

# --- Set Page Config (MUST BE FIRST STREAMLIT COMMAND) ---
APP_TITLE = "Daily Macro Tracker"
st.set_page_config(
    layout="wide", 
    page_title=APP_TITLE,
    initial_sidebar_state="expanded"
    )

st.title(APP_TITLE)

# --- Set up logging to standard output ---
# Get the root logger
logger = logging.getLogger()
logger.setLevel(logging.INFO) # Change to DEBUG to see more logs

# Remove any existing handlers to prevent duplicate logs if this code runs multiple times
if logger.handlers:
    for handler in logger.handlers:
        logger.removeHandler(handler)

# Create a StreamHandler to output to sys.stdout
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# You can also set specific loggers for your modules if needed
logging.info("Application started and logging configured to standard output.")


# --- OpenAI API Initialization ---
@st.cache_resource
def get_openai_client():
    """Initializes and returns the OpenAI client."""
    try:
        openai_api_key = st.secrets.get("OPENAI_API_KEY")
        if not openai_api_key:
            st.error("OpenAI API Key not found. Check .streamlit/secrets.toml if local or app settings in https://share.streamlit.io/.")
            logger.error("OpenAI API Key not found.")
            st.stop()
        return openai.OpenAI(api_key=openai_api_key)
    except Exception as e:
        st.error(f"Error initializing OpenAI client: {e}")
        logger.error(f"Error initializing OpenAI client: {e}")
        st.stop()

# --- Airtable Connection ---
@st.cache_resource
def get_airtable_tables():
    """Establishes connection to Airtable and returns Table objects for meals and goals."""
    try:
        api_key = st.secrets.get("AIRTABLE_API_KEY")
        base_id = st.secrets.get("AIRTABLE_BASE_ID")

        # Basic check to ensure secrets are loaded
        if not api_key or not base_id:
            st.error("Airtable API Key or Base ID not found. Check .streamlit/secrets.toml if local or app settings in https://share.streamlit.io/.")
            logger.error("Airtable API Key or Base ID not found.")
            st.stop()

        meals_table = Table(api_key, base_id, "Meals")
        preset_meals_table = Table(api_key, base_id, "preset_meals")
        goals_table = Table(api_key, base_id, "Goals")

        logger.info("Successfully connected to Airtable.")
        return meals_table, preset_meals_table, goals_table
    except Exception as e:
        st.error(f"Error connecting to Airtable: {e}. Please check your internet connection, API Key, and Base ID in .streamlit/secrets.toml.")
        logger.error(f"Error connecting to Airtable: {e}.")
        st.stop()

# Get the Airtable table objects at application startup
meals_table, preset_meals_table, goals_table = get_airtable_tables()


# --- Database Functions (now Airtable Functions) ---
def save_meal_to_airtable(meal_date, meal_name, calories, protein, fat, cholesterol, carbs):
    """Saves a new meal entry to the Airtable 'Meals' table."""
    try:
        calories = 0 if calories is None else calories
        protein = 0 if protein is None else protein
        fat = 0 if fat is None else fat
        cholesterol = 0 if cholesterol is None else cholesterol
        carbs = 0 if carbs is None else carbs
        meals_table.create({
            "date": meal_date.strftime("%Y-%m-%d"),
            "meal": meal_name,
            "calories_kcal": calories,
            "protein_g": protein,
            "fat_g": fat,
            "cholesterol_mg": cholesterol,
            "carbs_g": carbs
        })
        logger.info(f"Meal '{meal_name}' for {meal_date.strftime('%Y-%m-%d')} saved to Airtable.")
    except Exception as e:
        st.error(f"Error adding meal to Airtable: {e}")
        logger.error(f"Error adding meal to Airtable: {e}")

@st.cache_data(ttl=300)
def get_meals_from_airtable(selected_date=None):
    """Retrieves meal data from Airtable, optionally filtered by a specific date."""
    formula = None
    if selected_date:
        formula = f"IS_SAME({{date}}, '{selected_date.strftime('%Y-%m-%d')}')"
        logger.info(f"Fetching meals from Airtable for date: {selected_date.strftime('%Y-%m-%d')} with formula: {formula}")
    else:
        logger.info("Fetching all meals from Airtable.")

    try:
        records = meals_table.all(formula=formula, sort=['-date'])
        if not records:
            logger.info("No meal records found in Airtable for the given criteria.")
            return pd.DataFrame(columns=['Meal ID', 'Date', 'Meal', 'Calories (kcal)', 'Protein (g)', 'Fat (g)', 'Cholesterol (mg)', 'Carbohydrates (g)'])

        meals_list = []
        for record in records:
            fields = record['fields']
            meals_list.append({
                'Meal ID': fields.get('meal_id', ''),
                'Date': pd.to_datetime(fields.get('date')).date() if fields.get('date') else None,
                'Meal': fields.get('meal', ''),
                'Calories (kcal)': fields.get('calories_kcal', 0),
                'Protein (g)': fields.get('protein_g', 0),
                'Fat (g)': fields.get('fat_g', 0),
                'Cholesterol (mg)': fields.get('cholesterol_mg', 0),
                'Carbohydrates (g)': fields.get('carbs_g', 0)
            })

        df = pd.DataFrame(meals_list)
        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date']).dt.date
        display_cols = ['Meal ID', 'Date', 'Meal', 'Calories (kcal)', 'Protein (g)', 'Fat (g)', 'Cholesterol (mg)', 'Carbohydrates (g)']
        df = df[[col for col in display_cols if col in df.columns]]
        logger.info(f"Successfully fetched {len(df)} meal records from Airtable.")
        return df
    except Exception as e:
        st.error(f"Error fetching meals from Airtable: {e}")
        logger.error(f"Error fetching meals from Airtable: {e}")
        return pd.DataFrame(columns=['Meal ID', 'Date', 'Meal', 'Calories (kcal)', 'Protein (g)', 'Fat (g)', 'Cholesterol (mg)', 'Carbohydrates (g)'])


@st.cache_data(ttl=300)
def get_top_preset_meals(limit=3):
    """Fetches top preset meals from Airtable."""
    try:
        records = preset_meals_table.all(sort=['meal_id'], max_records=limit)

        preset_meals = []
        for record in records:
            fields = record.get('fields', {})
            preset_meals.append({
                'meal': fields.get('meal', ''),
                'calories_kcal': fields.get('calories_kcal'),
                'protein_f': fields.get('protein_f'),
                'carbs_g': fields.get('carbs_g')
            })

        logger.info(f"Fetched {len(preset_meals)} preset meals.")
        return preset_meals
    except Exception as e:
        logger.error(f"Error fetching preset meals: {e}")
        st.error(f"Error fetching preset meals: {e}")
        return []


@st.cache_data(ttl=300)
def get_top_preset_meal_records(limit=3):
    """Fetches top preset meals with Airtable record IDs for editing."""
    try:
        records = preset_meals_table.all(sort=['meal_id'], max_records=limit)
        result = []
        for record in records:
            fields = record.get('fields', {})
            result.append({
                'record_id': record.get('id'),
                'meal_id': fields.get('meal_id'),
                'meal': fields.get('meal', ''),
                'calories_kcal': fields.get('calories_kcal'),
                'protein_f': fields.get('protein_f'),
                'carbs_g': fields.get('carbs_g')
            })

        logger.info(f"Fetched {len(result)} editable preset meal records.")
        return result
    except Exception as e:
        logger.error(f"Error fetching editable preset meal records: {e}")
        st.error(f"Error fetching editable preset meals: {e}")
        return []


@st.cache_data(ttl=300)
def get_goals_from_airtable():
    """Fetches macro goals from Airtable Goals table (single-row config)."""
    try:
        records = goals_table.all(max_records=1)
        if not records:
            return None, None

        record = records[0]
        fields = record.get('fields', {})

        loaded_goals = {
            'calories': fields.get('calories_kcal', fields.get('calories')),
            'protein': fields.get('protein_g', fields.get('protein')),
            'fat': fields.get('fat_g', fields.get('fat')),
            'cholesterol': fields.get('cholesterol_mg', fields.get('cholesterol')),
            'carbs': fields.get('carbs_g', fields.get('carbs')),
        }
        return record.get('id'), loaded_goals
    except Exception as e:
        logger.error(f"Error fetching goals from Airtable: {e}")
        return None, None


def save_goals_to_airtable(updated_goals):
    """Upserts macro goals to Airtable Goals table."""
    goal_fields = {
        'calories_kcal': float(updated_goals['calories']),
        'protein_g': float(updated_goals['protein']),
        'fat_g': float(updated_goals['fat']),
        'cholesterol_mg': float(updated_goals['cholesterol']),
        'carbs_g': float(updated_goals['carbs']),
    }

    try:
        record_id, _ = get_goals_from_airtable()
        if record_id:
            goals_table.update(record_id, goal_fields)
        else:
            goals_table.create(goal_fields)
        get_goals_from_airtable.clear()
    except Exception as e:
        raise RuntimeError(f"Failed to save goals to Airtable: {e}") from e


@st.cache_data(ttl=300)


def display_progress(label, current, goal, unit):
    """Displays a progress bar and text for a given macro compared to its goal."""
    if goal > 0:
        percentage = (current / goal) * 100
        st.metric(label=f"{label} ({unit})", value=f"{current:.0f}/{goal:.0f}", delta=f"{percentage:.1f}%")
        st.progress(min(percentage / 100, 1.0))
    else:
        st.metric(label=f"{label} ({unit})", value=f"{current:.0f}/{goal:.0f}", delta="Goal not set")
        st.progress(0.0)

def plot_gauge(label, value, goal, unit):
    percent = min(value / goal * 100 if goal else 0, 100)
    fig = go.Figure(go.Indicator(
        mode = "gauge+number",
        value = value,
        number = {'suffix': f' {unit}'},
        domain = {'x': [0, 1], 'y': [0, 1]},
        title = {'text': f"{label} ({goal} {unit})"},
        gauge = {
            'axis': {'range': [0, goal]},
            'bar': {'color': "#00bfff"},
            'bgcolor': "white",
            'steps': [
                {'range': [0, goal], 'color': '#e6f7ff'}
            ],
            'threshold': {
                'line': {'color': "red", 'width': 4},
                'thickness': 0.75,
                'value': goal
            }
        }
    ))
    return fig


def get_gmt8_today():
    tz = pytz.timezone('Asia/Singapore')  # GMT+8
    return datetime.now(tz).date()

# --- OpenAI Integration Functions ---
def get_macros_from_openai(meal_description):
    """
    Sends a meal description to OpenAI GPT and extracts macro information.
    The prompt is designed to encourage a JSON-like output for easier parsing.
    """
    from openai_api import get_macros_from_meal_description
    try:
        logger.info(f"Sending meal description to OpenAI: '{meal_description}'")
        return get_macros_from_meal_description(meal_description)
    except Exception as e:
        st.error(f"Error communicating with OpenAI: {e}")
        logger.error(f"Error communicating with OpenAI: {e}")
        return None, None, None, None, None, None


################################################################

### Streamlit Application Begin

DEFAULT_GOALS = {
    'calories': 1700,
    'protein': 100,
    'fat': 55,
    'cholesterol': 300,
    'carbs': 220
}

if 'goals_for_display' not in st.session_state:
    goal_record_id, airtable_goals = get_goals_from_airtable()
    if airtable_goals:
        hydrated_goals = DEFAULT_GOALS.copy()
        for key, value in airtable_goals.items():
            if value is not None:
                hydrated_goals[key] = value
        st.session_state['goals_for_display'] = hydrated_goals
        st.session_state['goals_record_id'] = goal_record_id
    else:
        st.session_state['goals_for_display'] = DEFAULT_GOALS.copy()
        st.session_state['goals_record_id'] = None

if 'meal_name_ai' not in st.session_state:
    st.session_state['meal_name_ai'] = ""
    st.session_state['meal_calories_ai'] = ""
    st.session_state['meal_protein_ai'] = ""
    st.session_state['meal_fat_ai'] = ""
    st.session_state['meal_cholesterol_ai'] = ""
    st.session_state['meal_carbs_ai'] = ""

goals_for_display = st.session_state['goals_for_display']

st.sidebar.header("Daily Macro Goals")
st.sidebar.info(
    f"""
    **Calories:** {goals_for_display['calories']} kcal  
    **Protein:** {goals_for_display['protein']} g  
    **Fat:** {goals_for_display['fat']} g  
    **Cholesterol:** {goals_for_display['cholesterol']} mg  
    **Carbohydrates:** {goals_for_display['carbs']} g
    """
)
st.sidebar.divider()

nav_options = ["Daily Macro Dashboard", "Log Your Meals", "Update Profile"]
if "current_page" not in st.session_state:
    st.session_state["current_page"] = "Daily Macro Dashboard"

st.sidebar.markdown("### Navigation")
for idx, option in enumerate(nav_options):
    button_type = "primary" if st.session_state["current_page"] == option else "secondary"
    if st.sidebar.button(option, key=f"nav_btn_{idx}", type=button_type, use_container_width=True):
        st.session_state["current_page"] = option
        st.rerun()

page = st.session_state["current_page"]


def render_common_meals_editor():
    st.subheader("Update Common Meals")
    preset_records = get_top_preset_meal_records(limit=3)
    slot_records = preset_records + [None] * (3 - len(preset_records))

    slot_labels = []
    for i in range(3):
        record = slot_records[i]
        if record:
            slot_labels.append(f"Slot {i + 1}: {record.get('meal') or 'Unnamed Meal'}")
        else:
            slot_labels.append(f"Slot {i + 1}: None")

    selected_slot_label = st.selectbox(
        "Select a slot to edit",
        options=slot_labels,
        key="profile_preset_slot_selector",
    )
    selected_slot_index = slot_labels.index(selected_slot_label)
    selected_slot_record = slot_records[selected_slot_index]

    with st.form("manage_common_meal_form_main"):
        meal_name_value = "" if not selected_slot_record else str(selected_slot_record.get('meal') or "")
        calories_value = "" if not selected_slot_record or selected_slot_record.get('calories_kcal') is None else str(selected_slot_record.get('calories_kcal'))
        protein_value = "" if not selected_slot_record or selected_slot_record.get('protein_f') is None else str(selected_slot_record.get('protein_f'))
        carbs_value = "" if not selected_slot_record or selected_slot_record.get('carbs_g') is None else str(selected_slot_record.get('carbs_g'))

        edit_meal_name = st.text_input("Meal", value=meal_name_value)
        edit_calories = st.text_input("Calories (kcal)", value=calories_value)
        edit_protein = st.text_input("Protein (g)", value=protein_value)
        edit_carbs = st.text_input("Carbohydrates (g)", value=carbs_value)

        action_col1, action_col2 = st.columns(2)
        with action_col1:
            save_common_meal = st.form_submit_button("Save Common Meal")
        with action_col2:
            delete_common_meal = st.form_submit_button("Delete Selected")

        if delete_common_meal:
            if selected_slot_record and selected_slot_record.get('record_id'):
                try:
                    preset_meals_table.delete(selected_slot_record['record_id'])
                    st.success("Common meal deleted.")
                    get_top_preset_meals.clear()
                    get_top_preset_meal_records.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Error deleting common meal: {e}")
            else:
                st.warning("Selected slot is already empty.")

        elif save_common_meal:
            errors = []
            meal_name_clean = edit_meal_name.strip()

            def parse_optional_non_negative(value, label):
                text = str(value).strip()
                if text == "":
                    return None
                try:
                    parsed = float(text)
                    if parsed < 0:
                        raise ValueError
                    return parsed
                except Exception:
                    errors.append(f"{label} must be a non-negative number.")
                    return None

            if not meal_name_clean:
                errors.append("Meal name is required.")

            calories_val = parse_optional_non_negative(edit_calories, "Calories (kcal)")
            protein_val = parse_optional_non_negative(edit_protein, "Protein (g)")
            carbs_val = parse_optional_non_negative(edit_carbs, "Carbohydrates (g)")

            for msg in errors:
                st.error(msg)

            if not errors:
                save_fields = {
                    'meal': meal_name_clean,
                    'calories_kcal': calories_val,
                    'protein_f': protein_val,
                    'carbs_g': carbs_val,
                }

                try:
                    if selected_slot_record and selected_slot_record.get('record_id'):
                        preset_meals_table.update(selected_slot_record['record_id'], save_fields)
                        st.success("Common meal updated.")
                    else:
                        if len(preset_records) >= 3:
                            st.error("You already have 3 common meals.")
                        else:
                            preset_meals_table.create(save_fields)
                            st.success("Common meal added.")

                    get_top_preset_meals.clear()
                    get_top_preset_meal_records.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Error saving common meal: {e}")


if page == "Log Your Meals":
    st.header("Consult Callie")
    st.info("Describe your meal.")

    with st.form("ai_meal_entry_form", clear_on_submit=True):
        ai_meal_description = st.text_area("Describe your meal", height=100)
        process_ai_meal_button = st.form_submit_button("Fill me with shame.")

        if process_ai_meal_button and ai_meal_description:
            with st.spinner("Shaming..."):
                meal_name_ai, calories_ai, protein_ai, fat_ai, cholesterol_ai, carbs_ai = get_macros_from_openai(ai_meal_description)

            if meal_name_ai is not None:
                st.session_state['meal_name_ai'] = meal_name_ai
                st.session_state['meal_calories_ai'] = calories_ai if calories_ai is not None else ""
                st.session_state['meal_protein_ai'] = protein_ai if protein_ai is not None else ""
                st.session_state['meal_fat_ai'] = fat_ai if fat_ai is not None else ""
                st.session_state['meal_cholesterol_ai'] = cholesterol_ai if cholesterol_ai is not None else ""
                st.session_state['meal_carbs_ai'] = carbs_ai if carbs_ai is not None else ""
                st.success("Look at your macros! Are you happy now?")
            else:
                st.error("Error. Please try a different description or enter manually.")
        elif process_ai_meal_button and not ai_meal_description:
            st.warning("Enter a meal you dumb fuck.")

    st.header("Log Your Meals")
    st.markdown("**Quick Add Common Meals:**")
    top_preset_meals = get_top_preset_meals(limit=3)

    if top_preset_meals:
        quickadd_cols = st.columns([1, 1, 1, 3])
        for idx, preset in enumerate(top_preset_meals[:3]):
            with quickadd_cols[idx]:
                button_key = f"quick_add_preset_{idx}"
                button_label = preset.get('meal') or f"Preset {idx + 1}"
                if st.button(button_label, key=button_key):
                    st.session_state['meal_name_ai'] = preset.get('meal', '')
                    st.session_state['meal_calories_ai'] = "" if preset.get('calories_kcal') is None else str(preset.get('calories_kcal'))
                    st.session_state['meal_protein_ai'] = "" if preset.get('protein_f') is None else str(preset.get('protein_f'))
                    st.session_state['meal_fat_ai'] = ""
                    st.session_state['meal_cholesterol_ai'] = ""
                    st.session_state['meal_carbs_ai'] = "" if preset.get('carbs_g') is None else str(preset.get('carbs_g'))
                    st.rerun()
    else:
        st.caption("No preset meals found.")

    with st.form("meal_entry_form", clear_on_submit=True):
        meal_name = st.text_input("Meal Name", value=st.session_state['meal_name_ai'], placeholder="e.g., Chonky Chicken Salad")
        meal_date = st.date_input("Date", value=get_gmt8_today())
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            meal_calories = st.text_input("Calories (kcal)", value=str(st.session_state['meal_calories_ai']), placeholder="e.g. 350")
        with col2:
            meal_protein = st.text_input("Protein (g)", value=str(st.session_state['meal_protein_ai']), placeholder="e.g. 25")
        with col3:
            meal_fat = st.text_input("Fat (g)", value=str(st.session_state['meal_fat_ai']), placeholder="e.g. 10")
        with col4:
            meal_cholesterol = st.text_input("Cholesterol (mg)", value=str(st.session_state['meal_cholesterol_ai']), placeholder="e.g. 50")
        with col5:
            meal_carbs = st.text_input("Carbohydrates (g)", value=str(st.session_state['meal_carbs_ai']), placeholder="e.g. 40")

        if st.form_submit_button("Add Meal"):
            valid = True
            error_msgs = []
            if not meal_name:
                valid = False
                error_msgs.append("Meal name is required.")

            def parse_number(value, label):
                try:
                    value = str(value).strip()
                    if value == '':
                        return 0
                    parsed_value = float(value)
                    if parsed_value < 0:
                        raise ValueError
                    return parsed_value
                except Exception:
                    error_msgs.append(f"{label} must be a non-negative number.")
                    return None

            meal_calories_val = parse_number(meal_calories, "Calories (kcal)")
            meal_protein_val = parse_number(meal_protein, "Protein (g)")
            meal_fat_val = parse_number(meal_fat, "Fat (g)")
            meal_cholesterol_val = parse_number(meal_cholesterol, "Cholesterol (mg)")
            meal_carbs_val = parse_number(meal_carbs, "Carbohydrates (g)")

            if any(v is None for v in [meal_calories_val, meal_protein_val, meal_fat_val, meal_cholesterol_val, meal_carbs_val]):
                valid = False

            if valid:
                save_meal_to_airtable(
                    meal_date,
                    meal_name,
                    meal_calories_val,
                    meal_protein_val,
                    meal_fat_val,
                    meal_cholesterol_val,
                    meal_carbs_val
                )
                get_meals_from_airtable.clear()
                st.session_state['meal_name_ai'] = ""
                st.session_state['meal_calories_ai'] = ""
                st.session_state['meal_protein_ai'] = ""
                st.session_state['meal_fat_ai'] = ""
                st.session_state['meal_cholesterol_ai'] = ""
                st.session_state['meal_carbs_ai'] = ""
                st.success("Meal added successfully!")
                st.rerun()
            else:
                for msg in error_msgs:
                    st.error(msg)

elif page == "Update Profile":
    st.header("Update Profile")
    st.caption("Update your macro goals and common meals.")

    with st.form("update_goals_form"):
        st.subheader("Update Macro Goals")
        goal_col1, goal_col2, goal_col3, goal_col4, goal_col5 = st.columns(5)
        with goal_col1:
            updated_calories = st.number_input("Calories (kcal)", min_value=0.0, value=float(goals_for_display['calories']), step=10.0)
        with goal_col2:
            updated_protein = st.number_input("Protein (g)", min_value=0.0, value=float(goals_for_display['protein']), step=1.0)
        with goal_col3:
            updated_fat = st.number_input("Fat (g)", min_value=0.0, value=float(goals_for_display['fat']), step=1.0)
        with goal_col4:
            updated_cholesterol = st.number_input("Cholesterol (mg)", min_value=0.0, value=float(goals_for_display['cholesterol']), step=10.0)
        with goal_col5:
            updated_carbs = st.number_input("Carbohydrates (g)", min_value=0.0, value=float(goals_for_display['carbs']), step=1.0)

        save_goals = st.form_submit_button("Save Macro Goals")
        if save_goals:
            updated_goals = {
                'calories': updated_calories,
                'protein': updated_protein,
                'fat': updated_fat,
                'cholesterol': updated_cholesterol,
                'carbs': updated_carbs,
            }
            try:
                save_goals_to_airtable(updated_goals)
                st.session_state['goals_for_display'] = updated_goals
                st.success("Macro goals updated and saved to Airtable.")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    st.divider()
    render_common_meals_editor()

else:
    st.header("Daily Macro Dashboard")
    selected_date_dashboard = st.date_input("View Dashboard for Date", value=get_gmt8_today())
    daily_meals_df = get_meals_from_airtable(selected_date_dashboard)

    total_calories_today = daily_meals_df.get('Calories (kcal)', pd.Series(dtype=float)).sum()
    total_protein_today = daily_meals_df.get('Protein (g)', pd.Series(dtype=float)).sum()
    total_fat_today = daily_meals_df.get('Fat (g)', pd.Series(dtype=float)).sum()
    total_cholesterol_today = daily_meals_df.get('Cholesterol (mg)', pd.Series(dtype=float)).sum()
    total_carbs_today = daily_meals_df.get('Carbohydrates (g)', pd.Series(dtype=float)).sum()

    st.subheader(f"Progress for {selected_date_dashboard.strftime('%B %d, %Y')}")
    macro_summaries = [
        ("Calories", total_calories_today, goals_for_display['calories'], "kcal"),
        ("Protein", total_protein_today, goals_for_display['protein'], "g"),
        ("Fat", total_fat_today, goals_for_display['fat'], "g"),
        ("Cholesterol", total_cholesterol_today, goals_for_display['cholesterol'], "mg"),
        ("Carbohydrates", total_carbs_today, goals_for_display['carbs'], "g"),
    ]
    gauge_cols = st.columns(len(macro_summaries))
    for idx, (label, intake, goal, unit) in enumerate(macro_summaries):
        fig = plot_gauge(label, intake, goal, unit)
        if fig:
            gauge_cols[idx].plotly_chart(fig, use_container_width=True)
            remaining = goal - intake
            exceeded = intake > goal
            if exceeded:
                gauge_cols[idx].markdown(f"""
                    <div style='text-align:center;margin-top:-6.5em;line-height:1;'>
                        <span style='color:red;font-weight:bold;font-size:1.5em;'>+{abs(remaining):.0f} {unit} over</span>
                    </div>
                """, unsafe_allow_html=True)
            else:
                gauge_cols[idx].markdown(f"""
                    <div style='text-align:center;margin-top:-6.5em;line-height:1;'>
                        <span style='color:green;font-weight:bold;font-size:1.5em;'>{remaining:.0f} {unit} left</span>
                    </div>
                """, unsafe_allow_html=True)

    st.header("All Logged Meals")
    all_meals_df = get_meals_from_airtable()

    expected_cols = ['Meal ID', 'Date', 'Meal', 'Calories (kcal)', 'Protein (g)', 'Fat (g)', 'Cholesterol (mg)', 'Carbohydrates (g)']
    for col in expected_cols:
        if col not in all_meals_df.columns:
            all_meals_df[col] = pd.Series(dtype='object')
    all_meals_df = all_meals_df[expected_cols]

    if not all_meals_df.empty:
        all_meals_df['Meal ID'] = all_meals_df['Meal ID'].astype(str)
        all_meals_df = all_meals_df.sort_values(by=['Date', 'Meal ID'], ascending=[False, False])

    if not all_meals_df.empty:
        st.dataframe(all_meals_df, use_container_width=True)
    else:
        st.info("No meals have been logged yet. Use the 'Log Your Meals' page to add your first entry.")

    if not all_meals_df.empty:
        st.download_button(
            label="Download All Meal Data as CSV",
            data=all_meals_df.to_csv(index=False).encode('utf-8'),
            file_name="macro_tracker_data.csv",
            mime="text/csv",
        )

    st.header("Update a Logged Meal")
    with st.form("update_meal_form", clear_on_submit=True):
        update_meal_id = st.text_input("Meal ID (required)", value="", placeholder="Enter Meal ID from the table above")
        update_meal_name = st.text_input("Meal Name", value="", placeholder="Leave blank to keep unchanged")
        row3_col1, row3_col2, row3_col3, row3_col4, row3_col5 = st.columns(5)
        with row3_col1:
            update_calories = st.text_input("Calories (kcal)", value="", placeholder="Leave blank to keep unchanged")
        with row3_col2:
            update_protein = st.text_input("Protein (g)", value="", placeholder="Leave blank to keep unchanged")
        with row3_col3:
            update_fat = st.text_input("Fat (g)", value="", placeholder="Leave blank to keep unchanged")
        with row3_col4:
            update_cholesterol = st.text_input("Cholesterol (mg)", value="", placeholder="Leave blank to keep unchanged")
        with row3_col5:
            update_carbs = st.text_input("Carbohydrates (g)", value="", placeholder="Leave blank to keep unchanged")
        update_btn = st.form_submit_button("Update Meal")

        if update_btn:
            if not update_meal_id.strip():
                st.error("Meal ID is required.")
            else:
                records = meals_table.all(formula=f"{{meal_id}} = {update_meal_id.strip()}", max_records=1)
                if not records:
                    st.error(f"No meal found with Meal ID {update_meal_id.strip()}.")
                else:
                    record_id = records[0]['id']
                    update_fields = {}
                    if update_meal_name.strip():
                        update_fields['meal'] = update_meal_name.strip()
                    if update_calories.strip():
                        try:
                            update_fields['calories_kcal'] = float(update_calories.strip())
                        except Exception:
                            st.error("Calories must be a number.")
                    if update_protein.strip():
                        try:
                            update_fields['protein_g'] = float(update_protein.strip())
                        except Exception:
                            st.error("Protein must be a number.")
                    if update_fat.strip():
                        try:
                            update_fields['fat_g'] = float(update_fat.strip())
                        except Exception:
                            st.error("Fat must be a number.")
                    if update_cholesterol.strip():
                        try:
                            update_fields['cholesterol_mg'] = float(update_cholesterol.strip())
                        except Exception:
                            st.error("Cholesterol must be a number.")
                    if update_carbs.strip():
                        try:
                            update_fields['carbs_g'] = float(update_carbs.strip())
                        except Exception:
                            st.error("Carbohydrates must be a number.")
                    if not update_fields:
                        st.warning("No fields to update.")
                    else:
                        try:
                            meals_table.update(record_id, update_fields)
                            st.success(f"Meal {update_meal_id.strip()} updated!")
                            get_meals_from_airtable.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error updating meal: {e}")


