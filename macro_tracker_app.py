import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta, timezone
import pytz
from pyairtable import Table # Import the Airtable library
import logging
import plotly.graph_objects as go
from streamlit_oauth import OAuth2Component
import requests


# --- Set Page Config (MUST BE FIRST STREAMLIT COMMAND) ---
APP_TITLE = "Daily Macro Tracker"
st.set_page_config(layout="wide", page_title=APP_TITLE)
st.title(APP_TITLE) # You can put st.title here, it's also a Streamlit command

# Set up logging to file
logging.basicConfig(
    filename='app.log',
    level=logging.ERROR,  # Change to logging.INFO for more details
    format='%(asctime)s %(levelname)s:%(message)s'
)

# Set up your Google OAuth credentials in Streamlit secrets
client_id = st.secrets["GOOGLE_CLIENT_ID"]
client_secret = st.secrets["GOOGLE_CLIENT_SECRET"]
redirect_uri = st.secrets["GOOGLE_REDIRECT_URI"]
st.info(f"Redirect URI: {redirect_uri}")

oauth2 = OAuth2Component(
    client_id=client_id,
    client_secret=client_secret,
    authorize_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
    token_endpoint="https://oauth2.googleapis.com/token",
    revoke_token_endpoint="https://oauth2.googleapis.com/revoke"
)

# --- Google OAuth Login/Logout Logic ---
if "user_email" not in st.session_state:
    result = oauth2.authorize_button(
        "Login with Google",
        redirect_uri=redirect_uri,
        scope="openid email profile", 
        key="google_login"
    )
    if result and "token" in result:
        access_token = result["token"]["access_token"]
        userinfo_response = requests.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        user_info = userinfo_response.json()
        st.session_state["user_email"] = user_info["email"]
        st.success(f"Logged in as {user_info['email']}")
        st.rerun()
    else:
        st.stop()
else:
    st.success(f"Logged in as {st.session_state['user_email']}")
    if st.button("Logout"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

# --- Airtable Connection ---
@st.cache_resource
def get_airtable_tables():
    """Establishes connection to Airtable and returns Table objects for meals and goals."""
    try:
        api_key = st.secrets.get("AIRTABLE_API_KEY") # Use .get() to avoid KeyError
        base_id = st.secrets.get("AIRTABLE_BASE_ID")

        # Basic check to ensure secrets are loaded
        if not api_key or not base_id:
            st.error("Airtable API Key or Base ID not found. Check .streamlit/secrets.toml if local or app settings in https://share.streamlit.io/.")
            logging.error("Airtable API Key or Base ID not found. Check .streamlit/secrets.toml if local or app settings in https://share.streamlit.io/.")
            st.stop() # Stop the app if credentials are missing

        meals_table = Table(api_key, base_id, "Meals")
        goals_table = Table(api_key, base_id, "Goals")

        # st.success("Connected to Airtable successfully!") # REMOVED: Cannot be before set_page_config
        return meals_table, goals_table
    except Exception as e:
        st.error(f"Error connecting to Airtable: {e}. . Check .streamlit/secrets.toml if local or app settings in https://share.streamlit.io/")
        logging.error(f"Error connecting to Airtable: {e}. . Check .streamlit/secrets.toml if local or app settings in https://share.streamlit.io/")
        st.stop()

# Get the Airtable table objects at application startup
# This will now run AFTER set_page_config
meals_table, goals_table = get_airtable_tables()

# --- Database Functions (now Airtable Functions) ---

def initialise_airtable_goals():
    """
    Ensures there's at least one record in the Goals table for the current user.
    If not, it creates a default goal record for that user.
    """
    try:
        user_email = st.session_state.get("user_email", "demo@example.com")
        existing_goals = goals_table.all(formula=f"{{user_email}} = '{user_email}'", max_records=1)
        if not existing_goals:
            st.info("No macro goals found in Airtable for this user. Setting up default goals...")
            goals_table.create({
                "calories_kcal": 2000,
                "protein_g": 150,
                "carbs_g": 250,
                "fat_g": 70,
                "user_email": user_email
            })
            st.success("Default goals have been set in Airtable!")
            get_macro_goals_from_airtable.clear()
    except Exception as e:
        st.error(f"Error checking or initialising goals in Airtable: {e}")
        logging.error(f"Error checking or initialising goals in Airtable: {e}")

def save_meal_to_airtable(meal_date, meal_name, calories, protein, carbs, fat):
    """Saves a new meal entry to the Airtable 'Meals' table."""
    try:
        meals_table.create({
            "date": meal_date.strftime("%Y-%m-%d"),
            "meal": meal_name,
            "calories_kcal": calories,
            "protein_g": protein,
            "carbs_g": carbs,
            "fat_g": fat,
            "user_email": st.session_state.get("user_email", "demo@example.com")
        })
        # Success message shown later with st.rerun
    except Exception as e:
        st.error(f"Error adding meal to Airtable: {e}")
        logging.error(f"Error adding meal to Airtable: {e}")

@st.cache_data(ttl=300)
def get_meals_from_airtable(selected_date=None):
    """Retrieves meal data from Airtable, optionally filtered by a specific date."""
    user_email = st.session_state.get("user_email", "demo@example.com")
    if selected_date:
        formula = f"AND({{user_email}} = '{user_email}', IS_SAME({{date}}, '{selected_date.strftime('%Y-%m-%d')}'))"
    else:
        formula = f"{{user_email}} = '{user_email}'"
    try:
        records = meals_table.all(formula=formula, sort=['-date'])
        if not records:
            return pd.DataFrame(columns=['date', 'meal', 'calories_kcal', 'protein_g', 'carbs_g', 'fat_g'])

        meals_list = []
        for record in records:
            fields = record['fields']
            meals_list.append({
                'Date': pd.to_datetime(fields.get('date')).date() if fields.get('date') else None,
                'Meal': fields.get('meal', ''),
                'Calories (kcal)': fields.get('calories_kcal', 0),
                'Protein (g)': fields.get('protein_g', 0),
                'Carbs (g)': fields.get('carbs_g', 0),
                'Fat (g)': fields.get('fat_g', 0)
            })

        df = pd.DataFrame(meals_list)
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date']).dt.date
        # Reorder columns for display
        display_cols = ['Date', 'Meal', 'Calories (kcal)', 'Protein (g)', 'Carbs (g)', 'Fat (g)']
        df = df[[col for col in display_cols if col in df.columns]]
        return df
    except Exception as e:
        st.error(f"Error fetching meals from Airtable: {e}")
        logging.error(f"Error fetching meals from Airtable: {e}")
        return pd.DataFrame(columns=['Date', 'Meal', 'Calories (kcal)', 'Protein (g)', 'Carbs (g)', 'Fat (g)'])


@st.cache_data(ttl=300)
def get_macro_goals_from_airtable():
    """Retrieves the single macro goals record from the Airtable 'Goals' table."""
    user_email = st.session_state.get("user_email", "demo@example.com")
    try:
        records = goals_table.all(formula=f"{{user_email}} = '{user_email}'", max_records=1)
        if records:
            fields = records[0]['fields']
            st.session_state['goals_record_id'] = records[0]['id']
            return {
                'calories': fields.get('calories_kcal', 2000),
                'protein': fields.get('protein_g', 150),
                'carbs': fields.get('carbs_g', 250),
                'fat': fields.get('fat_g', 70)
            }
        else:
            return {'calories': 2000, 'protein': 150, 'carbs': 250, 'fat': 70}
    except Exception as e:
        st.error(f"Error fetching goals from Airtable: {e}")
        logging.error(f"Error fetching goals from Airtable: {e}")
        return {'calories': 2000, 'protein': 150, 'carbs': 250, 'fat': 70}

def update_macro_goals_in_airtable(calories, protein, carbs, fat):
    """Updates the macro goals in the Airtable 'Goals' table."""
    try:
        goals_record_id = st.session_state.get('goals_record_id')
        if not goals_record_id:
            st.error("Cannot update goals: No existing goals record ID found. Please ensure initial goals are set up in Airtable or refresh the app.")
            return

        goals_table.update(goals_record_id, {
            "calories_kcal": calories,
            "protein_g": protein,
            "carbs_g": carbs,
            "fat_g": fat
        })
        st.success("Daily macro goals updated in Airtable!")
    except Exception as e:
        st.error(f"Error updating goals in Airtable: {e}")
        logging.error(f"Error updating goals in Airtable: {e}")


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


## Streamlit Application Layout

# Initialize Airtable goals on app startup
# This will now run AFTER set_page_config
initialise_airtable_goals()

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
        update_macro_goals_in_airtable(new_calories_goal, new_protein_goal, new_carbs_goal, new_fat_goal)
        get_macro_goals_from_airtable.clear()
        st.rerun()


### Log Your Meals

st.header("Log Your Meals")

with st.form("meal_entry_form", clear_on_submit=True):
    meal_name = st.text_input("Meal Name", placeholder="e.g., Chonky Chicken Salad")
    meal_date = st.date_input("Date", value=get_gmt8_today())
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        meal_calories = st.text_input("Calories (kcal)", value="", placeholder="e.g. 350")
    with col2:
        meal_protein = st.text_input("Protein (g)", value="", placeholder="e.g. 25")
    with col3:
        meal_carbs = st.text_input("Carbohydrates (g)", value="", placeholder="e.g. 40")
    with col4:
        meal_fat = st.text_input("Fat (g)", value="", placeholder="e.g. 10")

    if st.form_submit_button("Add Meal"):
        valid = True
        error_msgs = []
        if not meal_name:
            valid = False
            error_msgs.append("Meal name is required.")
        def parse_number(value, label):
            try:
                value = value.strip()
                if value == '':
                    raise ValueError
                value = float(value)
                if value < 0:
                    raise ValueError
                return value
            except Exception:
                error_msgs.append(f"{label} must be a non-negative number.")
                return None
        meal_calories_val = parse_number(meal_calories, "Calories (kcal)")
        meal_protein_val = parse_number(meal_protein, "Protein (g)")
        meal_carbs_val = parse_number(meal_carbs, "Carbohydrates (g)")
        meal_fat_val = parse_number(meal_fat, "Fat (g)")
        for label, value in [
            ("Calories (kcal)", meal_calories_val),
            ("Protein (g)", meal_protein_val),
            ("Carbohydrates (g)", meal_carbs_val),
            ("Fat (g)", meal_fat_val)
        ]:
            if value is None or value < 0:
                valid = False
        if valid:
            save_meal_to_airtable(
                meal_date,
                meal_name,
                meal_calories_val,
                meal_protein_val,
                meal_carbs_val,
                meal_fat_val
            )
            get_meals_from_airtable.clear()
            st.rerun()
        else:
            for msg in error_msgs:
                st.error(msg)


## Daily Macro Dashboard

st.header("Daily Macro Dashboard")
if st.button("🔄 Refresh Dashboard"):
    get_meals_from_airtable.clear()
    get_macro_goals_from_airtable.clear()
    st.rerun()

selected_date_dashboard = st.date_input("View Dashboard for Date", value=get_gmt8_today())

daily_meals_df = get_meals_from_airtable(selected_date_dashboard)

# Added defensive checks to ensure columns exist before summing, else 0.
total_calories_today = daily_meals_df['Calories (kcal)'].sum() if 'Calories (kcal)' in daily_meals_df.columns else 0
total_carbs_today = daily_meals_df['Carbs (g)'].sum() if 'Carbs (g)' in daily_meals_df.columns else 0
total_fat_today = daily_meals_df['Fat (g)'].sum() if 'Fat (g)' in daily_meals_df.columns else 0
total_protein_today = daily_meals_df['Protein (g)'].sum() if 'Protein (g)' in daily_meals_df.columns else 0

goals_for_display = get_macro_goals_from_airtable()

st.subheader(f"Progress for {selected_date_dashboard.strftime('%B %d, %Y')}")
col_dash1, col_dash2, col_dash3, col_dash4 = st.columns(4)

with col_dash1:
    fig = plot_gauge("Calories", total_calories_today, goals_for_display['calories'], "kcal")
    if fig:
        st.plotly_chart(fig, use_container_width=True)
with col_dash2:
    fig = plot_gauge("Protein", total_protein_today, goals_for_display['protein'], "g")
    if fig:
        st.plotly_chart(fig, use_container_width=True)
with col_dash3:
    fig = plot_gauge("Carbohydrates", total_carbs_today, goals_for_display['carbs'], "g")
    if fig:
        st.plotly_chart(fig, use_container_width=True)
with col_dash4:
    fig = plot_gauge("Fat", total_fat_today, goals_for_display['fat'], "g")
    if fig:
        st.plotly_chart(fig, use_container_width=True)


## All Logged Meals

st.header("All Logged Meals")
all_meals_df = get_meals_from_airtable()

if not all_meals_df.empty:
    st.dataframe(all_meals_df, use_container_width=True)
else:
    st.info("No meals have been logged yet. Use the 'Log Your Meals' section above to add your first entry!")

# --- Optional: Download Data ---
if not all_meals_df.empty:
    st.download_button(
        label="Download All Meal Data as CSV",
        data=all_meals_df.drop(columns=['ID'], errors='ignore').to_csv(index=False).encode('utf-8'),
        file_name="macro_tracker_data.csv",
        mime="text/csv",
    )