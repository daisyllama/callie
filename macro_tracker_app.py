import streamlit as st
import pandas as pd
from datetime import datetime, date
from pyairtable import Table # Import the Airtable library

# --- Configuration ---
APP_TITLE = "Daily Macro Tracker"

# --- Set Page Config (MUST BE FIRST STREAMLIT COMMAND) ---
st.set_page_config(layout="wide", page_title=APP_TITLE)
st.title(APP_TITLE) # You can put st.title here, it's also a Streamlit command

# --- Airtable Connection ---
@st.cache_resource
def get_airtable_tables():
    """Establishes connection to Airtable and returns Table objects for meals and goals."""
    try:
        api_key = st.secrets.get("AIRTABLE_API_KEY") # Use .get() to avoid KeyError
        base_id = st.secrets.get("AIRTABLE_BASE_ID")

        # Basic check to ensure secrets are loaded
        if not api_key or not base_id:
            st.error("Airtable API Key or Base ID not found in .streamlit/secrets.toml. Please check your setup.")
            st.stop() # Stop the app if credentials are missing

        meals_table = Table(api_key, base_id, "Meals")
        goals_table = Table(api_key, base_id, "Goals")

        # st.success("Connected to Airtable successfully!") # REMOVED: Cannot be before set_page_config
        return meals_table, goals_table
    except Exception as e:
        st.error(f"Error connecting to Airtable: {e}. Please check your internet connection, API Key, and Base ID in .streamlit/secrets.toml.")
        st.stop()

# Get the Airtable table objects at application startup
# This will now run AFTER set_page_config
meals_table, goals_table = get_airtable_tables()

# --- Database Functions (now Airtable Functions) ---

def initialize_airtable_goals():
    """
    Ensures there's at least one record in the Goals table.
    If the Goals table is empty, it creates a default goal record.
    """
    try:
        existing_goals = goals_table.all(max_records=1)
        if not existing_goals:
            st.info("No macro goals found in Airtable. Setting up default goals...")
            goals_table.create({
                "Calories": 2000,
                "Carbs (g)": 250,
                "Fat (g)": 70,
                "Protein (g)": 150
            })
            st.success("Default goals have been set in Airtable!") # This is okay here, as it's after set_page_config
            get_macro_goals_from_airtable.clear()
    except Exception as e:
        st.error(f"Error checking or initializing goals in Airtable: {e}")

def save_meal_to_airtable(meal_date, meal_name, calories, carbs, fat, protein):
    """Saves a new meal entry to the Airtable 'Meals' table."""
    try:
        meals_table.create({
            "Date": meal_date.strftime("%Y-%m-%d"),
            "Meal": meal_name,
            "Calories": calories,
            "Carbs (g)": carbs,
            "Fat (g)": fat,
            "Protein (g)": protein,
        })
        # Success message shown later with st.rerun
    except Exception as e:
        st.error(f"Error adding meal to Airtable: {e}")

@st.cache_data(ttl=300) # Cache meal data for 5 minutes to reduce API calls
def get_meals_from_airtable(selected_date=None):
    """Retrieves meal data from Airtable, optionally filtered by a specific date."""
    formula = None
    if selected_date:
        # Airtable's filter formula for date matching
        formula = f"IS_SAME({{Date}}, '{selected_date.strftime('%Y-%m-%d')}')"

    try:
        # Fetch records, sorting by Date (desc) only
        # Removed ', -Created Time' as it caused an 'Unknown field name' error
        records = meals_table.all(formula=formula, sort=['-Date']) # <-- CHANGE IS HERE

        if not records:
            # Return an empty DataFrame with expected columns if no records are found
            return pd.DataFrame(columns=['ID', 'Date', 'Meal', 'Calories', 'Carbs (g)', 'Fat (g)', 'Protein (g)'])

        meals_list = []
        for record in records:
            fields = record['fields']
            meals_list.append({
                'ID': record['id'], # Airtable's unique record ID
                'Date': pd.to_datetime(fields.get('Date')).date() if fields.get('Date') else None, # Convert to date object
                'Meal': fields.get('Meal', ''),
                'Calories': fields.get('Calories', 0),
                'Carbs (g)': fields.get('Carbs (g)', 0),
                'Fat (g)': fields.get('Fat (g)', 0),
                'Protein (g)': fields.get('Protein (g)', 0)
            })

        df = pd.DataFrame(meals_list)
        # Ensure 'Date' column is explicitly date type for proper display
        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date']).dt.date
        return df
    except Exception as e:
        st.error(f"Error fetching meals from Airtable: {e}")
        return pd.DataFrame(columns=['ID', 'Date', 'Meal', 'Calories', 'Carbs (g)', 'Fat (g)', 'Protein (g)'])


@st.cache_data(ttl=300)
def get_macro_goals_from_airtable():
    """Retrieves the single macro goals record from the Airtable 'Goals' table."""
    try:
        records = goals_table.all(max_records=1)
        if records:
            fields = records[0]['fields']
            st.session_state['goals_record_id'] = records[0]['id']
            return {
                'calories': fields.get('Calories', 2000),
                'carbs': fields.get('Carbs (g)', 250),
                'fat': fields.get('Fat (g)', 70),
                'protein': fields.get('Protein (g)', 150)
            }
        else:
            return {'calories': 2000, 'carbs': 250, 'fat': 70, 'protein': 150}
    except Exception as e:
        st.error(f"Error fetching goals from Airtable: {e}")
        return {'calories': 2000, 'carbs': 250, 'fat': 70, 'protein': 150}

def update_macro_goals_in_airtable(calories, carbs, fat, protein):
    """Updates the macro goals in the Airtable 'Goals' table."""
    try:
        goals_record_id = st.session_state.get('goals_record_id')
        if not goals_record_id:
            st.error("Cannot update goals: No existing goals record ID found. Please ensure initial goals are set up in Airtable or refresh the app.")
            return

        goals_table.update(goals_record_id, {
            "Calories": calories,
            "Carbs (g)": carbs,
            "Fat (g)": fat,
            "Protein (g)": protein
        })
        st.success("Daily macro goals updated in Airtable!")
    except Exception as e:
        st.error(f"Error updating goals in Airtable: {e}")

# --- Helper Functions (General Display) ---
def display_progress(label, current, goal, unit):
    """Displays a progress bar and text for a given macro compared to its goal."""
    if goal > 0:
        percentage = (current / goal) * 100
        st.metric(label=f"{label} ({unit})", value=f"{current:.0f}/{goal:.0f}", delta=f"{percentage:.1f}%")
        st.progress(min(percentage / 100, 1.0))
    else:
        st.metric(label=f"{label} ({unit})", value=f"{current:.0f}/{goal:.0f}", delta="Goal not set")
        st.progress(0.0)



## Streamlit Application Layout

# Initialize Airtable goals on app startup
# This will now run AFTER set_page_config
initialize_airtable_goals()

# Fetch current goals from Airtable for display in sidebar and dashboard
current_macro_goals = get_macro_goals_from_airtable()



### Set Your Daily Macro Goals

st.sidebar.header("Set Your Daily Macro Goals")
with st.sidebar.form("macro_goal_form"):
    new_calories_goal = st.number_input(
        "Calories (kcal)",
        min_value=0,
        value=current_macro_goals['calories'],
        step=50
    )
    new_carbs_goal = st.number_input(
        "Carbohydrates (g)",
        min_value=0,
        value=current_macro_goals['carbs'],
        step=5
    )
    new_fat_goal = st.number_input(
        "Fat (g)",
        min_value=0,
        value=current_macro_goals['fat'],
        step=5
    )
    new_protein_goal = st.number_input(
        "Protein (g)",
        min_value=0,
        value=current_macro_goals['protein'],
        step=5
    )
    if st.form_submit_button("Update Goals"):
        update_macro_goals_in_airtable(new_calories_goal, new_carbs_goal, new_fat_goal, new_protein_goal)
        get_macro_goals_from_airtable.clear()
        st.rerun()



### Log Your Meals

st.header("Log Your Meals")

with st.form("meal_entry_form", clear_on_submit=True):
    meal_name = st.text_input("Meal Name", placeholder="e.g., Breakfast, Lunch, Snack")
    meal_date = st.date_input("Date", value=datetime.today())
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        meal_calories = st.number_input("Calories (kcal)", min_value=0, value=0)
    with col2:
        meal_carbs = st.number_input("Carbohydrates (g)", min_value=0, value=0)
    with col3:
        meal_fat = st.number_input("Fat (g)", min_value=0, value=0)
    with col4:
        meal_protein = st.number_input("Protein (g)", min_value=0, value=0)

    if st.form_submit_button("Add Meal"):
        if meal_name and meal_calories >= 0 and meal_carbs >= 0 and meal_fat >= 0 and meal_protein >= 0:
            save_meal_to_airtable(meal_date, meal_name, meal_calories, meal_carbs, meal_fat, meal_protein)
            get_meals_from_airtable.clear()
            st.rerun()
        else:
            st.error("Please ensure all meal details are filled correctly and values are non-negative.")



## Daily Macro Dashboard

st.header("Daily Macro Dashboard")

selected_date_dashboard = st.date_input("View Dashboard for Date", value=datetime.today())

daily_meals_df = get_meals_from_airtable(selected_date_dashboard)

total_calories_today = daily_meals_df['Calories'].sum()
total_carbs_today = daily_meals_df['Carbs (g)'].sum()
total_fat_today = daily_meals_df['Fat (g)'].sum()
total_protein_today = daily_meals_df['Protein (g)'].sum()

goals_for_display = get_macro_goals_from_airtable()

st.subheader(f"Progress for {selected_date_dashboard.strftime('%B %d, %Y')}")
col_dash1, col_dash2, col_dash3, col_dash4 = st.columns(4)

with col_dash1:
    display_progress("Calories", total_calories_today, goals_for_display['calories'], "kcal")
with col_dash2:
    display_progress("Carbohydrates", total_carbs_today, goals_for_display['carbs'], "g")
with col_dash3:
    display_progress("Fat", total_fat_today, goals_for_display['fat'], "g")
with col_dash4:
    display_progress("Protein", total_protein_today, goals_for_display['protein'], "g")


## All Logged Meals

st.header("All Logged Meals")
all_meals_df = get_meals_from_airtable()

if not all_meals_df.empty:
    st.dataframe(all_meals_df.drop(columns=['ID']), use_container_width=True)
else:
    st.info("No meals have been logged yet. Use the 'Log Your Meals' section above to add your first entry!")

# --- Optional: Download Data ---
if not all_meals_df.empty:
    csv = all_meals_df.drop(columns=['ID']).to_csv(index=False).encode('utf-8')
    st.download_button(
        label="Download All Meal Data as CSV",
        data=csv,
        file_name="macro_tracker_data.csv",
        mime="text/csv",
    )