import streamlit as st
import pandas as pd
import logging
from pyairtable import Table
import requests
import pytz
import plotly.graph_objects as go
from datetime import datetime, date, timedelta, timezone
import openai
import re
import sys # Import the sys module

# --- Set Page Config (MUST BE FIRST STREAMLIT COMMAND) ---
APP_TITLE = "Daily Macro Tracker"
st.set_page_config(layout="wide", page_title=APP_TITLE)

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
        goals_table = Table(api_key, base_id, "Goals")

        logger.info("Successfully connected to Airtable.")
        return meals_table, goals_table
    except Exception as e:
        st.error(f"Error connecting to Airtable: {e}. Please check your internet connection, API Key, and Base ID in .streamlit/secrets.toml.")
        logger.error(f"Error connecting to Airtable: {e}.")
        st.stop()

# Get the Airtable table objects at application startup
meals_table, goals_table = get_airtable_tables()


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
    from openai_api import extract_macros_from_meal
    try:
        logger.info(f"Sending meal description to OpenAI: '{meal_description}'")
        content = extract_macros_from_meal(meal_description)
        st.code(content, language="text")  # Optionally show raw response for debugging
        logger.info(f"OpenAI raw response: '{content}'")
        return parse_openai_response(content)
    except Exception as e:
        st.error(f"Error communicating with OpenAI: {e}")
        logger.error(f"Error communicating with OpenAI: {e}")
        return None, None, None, None, None, None

def parse_openai_response(response_text):
    """
    Parses the text response from OpenAI to extract meal name and macro values.
    Uses regex to find key-value pairs.
    """
    meal_name = ""
    calories = None
    protein = None
    fat = None
    cholesterol = None
    carbs = None

    meal_match = re.search(r"Meal:\s*(.*?)(?:,|$)", response_text, re.IGNORECASE)
    if meal_match:
        meal_name = meal_match.group(1).strip()

    calories_match = re.search(r"Calories:\s*(\d+)", response_text, re.IGNORECASE)
    if calories_match:
        calories = int(calories_match.group(1))

    protein_match = re.search(r"Protein:\s*(\d+)g", response_text, re.IGNORECASE)
    if protein_match:
        protein = int(protein_match.group(1))

    fat_match = re.search(r"Fat:\s*(\d+)g", response_text, re.IGNORECASE)
    if fat_match:
        fat = int(fat_match.group(1))

    cholesterol_match = re.search(r"Cholesterol:\s*(\d+)mg", response_text, re.IGNORECASE)
    if cholesterol_match:
        cholesterol = int(cholesterol_match.group(1))

    carbs_match = re.search(r"Carbs:\s*(\d+)g", response_text, re.IGNORECASE)
    if carbs_match:
        carbs = int(carbs_match.group(1))

    logger.info(f"Parsed OpenAI response: Meal='{meal_name}', Cals={calories}, Prot={protein}, Fat={fat}, Chol={cholesterol}, Carbs={carbs}")
    return meal_name, calories, protein, fat, cholesterol, carbs

### Streamlit Application Begin




### Set Your Daily Macro Goals (Read Only Sidebar)

st.sidebar.header("Daily Macro Goals")
st.sidebar.info(
    f"""
    **Calories:** 1700 kcal  
    **Protein:** 100 g  
    **Fat:** 55 g  
    **Cholesterol:** 300 mg  
    **Carbohydrates:** 220 g
    """
)

# Remove or comment out the macro_goal_form and update logic from the sidebar

# --- ChatGPT Integration Section ---
st.header("Consult Callie")
st.info("Tell me what you ate you fat fuck and i'll make you regret it.")

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


# Initialize session state for meal fields if not present
if 'meal_name_ai' not in st.session_state:
    st.session_state['meal_name_ai'] = ""
    st.session_state['meal_calories_ai'] = ""
    st.session_state['meal_protein_ai'] = ""
    st.session_state['meal_fat_ai'] = ""
    st.session_state['meal_cholesterol_ai'] = ""
    st.session_state['meal_carbs_ai'] = ""

# --- Helper Buttons for Common Meals ---
st.markdown("**Quick Add Common Meals:**")
col_quickadd1, col_quickadd2, col_quickadd3, _ = st.columns([1, 1, 1, 3])
with col_quickadd1:
    if st.button("Protein shake"):
        st.session_state['meal_name_ai'] = "Protein shake (1 scoop)"
        st.session_state['meal_calories_ai'] = "120"
        st.session_state['meal_protein_ai'] = "24"
        st.session_state['meal_fat_ai'] = "1.5"
        st.session_state['meal_cholesterol_ai'] = "55"
        st.session_state['meal_carbs_ai'] = "3"
        st.rerun()
with col_quickadd2:
    if st.button("Common Meal 2"):
        # TODO: Add other common meals later
        st.session_state['meal_name_ai'] = "Common Meal 2"
        st.session_state['meal_calories_ai'] = ""
        st.session_state['meal_protein_ai'] = ""
        st.session_state['meal_fat_ai'] = ""
        st.session_state['meal_cholesterol_ai'] = ""
        st.session_state['meal_carbs_ai'] = ""
        st.rerun()
with col_quickadd3:
    if st.button("Common Meal 3"):
        # TODO: Add other common meals later
        st.session_state['meal_name_ai'] = "Common Meal 3"
        st.session_state['meal_calories_ai'] = ""
        st.session_state['meal_protein_ai'] = ""
        st.session_state['meal_fat_ai'] = ""
        st.session_state['meal_cholesterol_ai'] = ""
        st.session_state['meal_carbs_ai'] = ""
        st.rerun()

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
                value = str(value).strip() # Ensure value is a string before stripping
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


## Daily Macro Dashboard

st.header("Daily Macro Dashboard")


selected_date_dashboard = st.date_input("View Dashboard for Date", value=get_gmt8_today())

daily_meals_df = get_meals_from_airtable(selected_date_dashboard)

total_calories_today = daily_meals_df.get('Calories (kcal)', pd.Series(dtype=float)).sum()
total_protein_today = daily_meals_df.get('Protein (g)', pd.Series(dtype=float)).sum()
total_fat_today = daily_meals_df.get('Fat (g)', pd.Series(dtype=float)).sum()
total_cholesterol_today = daily_meals_df.get('Cholesterol (mg)', pd.Series(dtype=float)).sum()
total_carbs_today = daily_meals_df.get('Carbohydrates (g)', pd.Series(dtype=float)).sum()

goals_for_display = {
    'calories': 1700,
    'protein': 100,
    'fat': 55,
    'cholesterol': 300,
    'carbs': 220
}

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


## All Logged Meals

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
    st.info("No meals have been logged yet. Use the 'Log Your Meals' section above to add your first entry!")

# --- Optional: Download Data ---
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
            record_id = update_meal_id.strip() # Assuming this is the Airtable record 'id'
            try:
                record_to_update = meals_table.get(record_id) # Attempt to fetch by actual Airtable record ID
                logger.info(f"Found record for update with ID: {record_id}")
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    st.error(f"No meal found with Meal ID {record_id}. Please ensure you are entering the correct Airtable record ID.")
                    logger.error(f"Update failed: No record found for ID {record_id}")
                else:
                    st.error(f"Error fetching meal for update: {e}")
                    logger.error(f"Error fetching meal for update with ID {record_id}: {e}")
                record_id = None # Invalidate record_id if not found

            if record_id:
                update_fields = {}
                if update_meal_name.strip():
                    update_fields['meal'] = update_meal_name.strip()
                # Use a helper for parsing and logging numeric inputs
                def parse_and_log_numeric_update(value, field_name, unit):
                    try:
                        val = float(value.strip())
                        logger.info(f"Parsed update for {field_name}: {val}{unit}")
                        return val
                    except ValueError:
                        st.error(f"{field_name} must be a number.")
                        logger.error(f"Invalid numeric input for {field_name}: '{value}'")
                        return None

                if update_calories.strip():
                    parsed_cal = parse_and_log_numeric_update(update_calories, "Calories", "kcal")
                    if parsed_cal is not None: update_fields['calories_kcal'] = parsed_cal
                if update_protein.strip():
                    parsed_prot = parse_and_log_numeric_update(update_protein, "Protein", "g")
                    if parsed_prot is not None: update_fields['protein_g'] = parsed_prot
                if update_fat.strip():
                    parsed_fat = parse_and_log_numeric_update(update_fat, "Fat", "g")
                    if parsed_fat is not None: update_fields['fat_g'] = parsed_fat
                if update_cholesterol.strip():
                    parsed_chol = parse_and_log_numeric_update(update_cholesterol, "Cholesterol", "mg")
                    if parsed_chol is not None: update_fields['cholesterol_mg'] = parsed_chol
                if update_carbs.strip():
                    parsed_carbs = parse_and_log_numeric_update(update_carbs, "Carbohydrates", "g")
                    if parsed_carbs is not None: update_fields['carbs_g'] = parsed_carbs

                # Check if there were any parsing errors for numeric fields
                if any(v is None for v in update_fields.values()):
                    st.warning("Please correct the invalid numeric inputs for update.")
                elif not update_fields:
                    st.warning("No fields to update. Please fill in at least one field other than Meal ID.")
                    logger.warning("Attempted update with no valid fields provided.")
                else:
                    try:
                        meals_table.update(record_id, update_fields)
                        st.success(f"Meal {record_id} updated!")
                        logger.info(f"Meal {record_id} successfully updated with fields: {update_fields}")
                        get_meals_from_airtable.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error updating meal: {e}")
                        logger.error(f"Error updating meal {record_id}: {e}")