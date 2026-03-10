import openai
import os
import streamlit as st
import re
import json


class OpenAIMacroError(RuntimeError):
    """Domain-specific error for macro extraction failures."""


def get_openai_client():
    api_key = None
    try:
        api_key = st.secrets["OPENAI_API_KEY"]
    except Exception:
        api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("No OpenAI API key found in Streamlit secrets or environment variable.")
    return openai.OpenAI(api_key=api_key)


def parse_openai_macro_response(response_text):
    """Parses OpenAI text into a macro tuple expected by the app."""
    meal_name = ""
    calories = None
    protein = None
    fat = None
    cholesterol = None
    carbs = None

    def to_int_from_maybe_unit(value):
        if value is None:
            return None
        text = str(value).strip()
        match = re.search(r"(\d+)", text)
        return int(match.group(1)) if match else None

    # First, try JSON payloads like:
    # {"Meal":"Chicken Rice","Calories":"400kcal",...}
    try:
        parsed_json = json.loads(response_text)
        if isinstance(parsed_json, dict):
            meal_name = str(parsed_json.get("Meal") or parsed_json.get("meal") or "").strip()
            calories = to_int_from_maybe_unit(parsed_json.get("Calories") or parsed_json.get("calories"))
            protein = to_int_from_maybe_unit(parsed_json.get("Protein") or parsed_json.get("protein"))
            fat = to_int_from_maybe_unit(parsed_json.get("Fat") or parsed_json.get("fat"))
            cholesterol = to_int_from_maybe_unit(parsed_json.get("Cholesterol") or parsed_json.get("cholesterol"))
            carbs = to_int_from_maybe_unit(parsed_json.get("Carbs") or parsed_json.get("carbs"))
            return meal_name, calories, protein, fat, cholesterol, carbs
    except Exception:
        pass

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

    return meal_name, calories, protein, fat, cholesterol, carbs


def _map_openai_error(err):
    """Converts OpenAI SDK errors into concise user-facing messages."""
    err_str = str(err)
    status_code = getattr(err, "status_code", None)

    if status_code == 429 or "insufficient_quota" in err_str:
        return "OpenAI quota exceeded. Please check billing/plan and try again later."
    if status_code == 401:
        return "OpenAI API key is invalid or missing permissions."
    if status_code == 403:
        return "OpenAI access denied for this project/model."
    if "RateLimit" in err.__class__.__name__:
        return "OpenAI rate limit hit. Please wait and retry."

    return f"OpenAI API error: {err}"


def extract_macros_from_meal(meal_description, model="gpt-3.5-turbo", temperature=0.1, max_tokens=150):
    """
    Calls OpenAI API to extract macros from a meal description.
    Returns the raw response text (for troubleshooting) and the parsed macro values.
    """
    client = get_openai_client()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You estimate meal macros. Return ONLY valid JSON with exactly these keys: "
                        "Meal, Calories, Protein, Fat, Cholesterol, Carbs. "
                        "Values should be strings with units, e.g. \"400kcal\", \"25g\", \"70mg\". "
                        "No markdown, no explanations, no extra keys."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Extract macros for this meal description and return strict JSON only: "
                        f"{meal_description}"
                    ),
                }
            ],
            response_format={"type": "json_object"},
            temperature=temperature,
            max_tokens=max_tokens
        )
        content = response.choices[0].message.content.strip()
        # Troubleshooting log: print raw response to Streamlit and stdout
        print(f"[OpenAI API RAW RESPONSE]: {content}")
        try:
            st.code(content, language="text")
        except Exception:
            pass
        return content
    except Exception as e:
        raise OpenAIMacroError(_map_openai_error(e)) from e


def get_macros_from_meal_description(meal_description, model="gpt-4o-mini", temperature=0.1, max_tokens=150):
    """Single call used by app code: returns parsed macro tuple."""
    content = extract_macros_from_meal(
        meal_description=meal_description,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return parse_openai_macro_response(content)


if __name__ == "__main__":
    test_meal = input("Enter a meal description: ")
    try:
        raw = extract_macros_from_meal(test_meal)
        parsed = parse_openai_macro_response(raw)
        print("OpenAI raw response:")
        print(raw)
        print("Parsed macro tuple:")
        print(parsed)
    except Exception as e:
        print(f"Error: {e}")