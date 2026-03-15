import openai
import os
import streamlit as st
import re
import json

OLLAMA_BASE_URL = "http://localhost:11434/v1"

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_OLLAMA_MODEL = "llama3:latest"
DEFAULT_TEMPERATURE = 0.1
DEFAULT_MAX_TOKENS = 200
DEFAULT_OLLAMA_THINK = "none"
REASONING_ONLY_ERROR_FRAGMENT = "only reasoning and no final JSON answer"


class OpenAIMacroError(RuntimeError):
    """Domain-specific error for macro extraction failures."""


def _resolve_value(value, default):
    return default if value is None else value


def get_openai_client():
    api_key = None
    try:
        api_key = st.secrets["OPENAI_API_KEY"]
    except Exception:
        api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("No OpenAI API key found in Streamlit secrets or environment variable.")
    return openai.OpenAI(api_key=api_key)


def get_ollama_client():
    """Returns an OpenAI-compatible client pointed at the local Ollama server."""
    return openai.OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")


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


def _build_macro_messages(meal_description):
    return [
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
    ]


def _extract_content_from_response(response):
    message = response.choices[0].message
    content = (message.content or "").strip()
    reasoning = getattr(message, "reasoning", "") or ""
    finish_reason = getattr(response.choices[0], "finish_reason", None)

    if not content and reasoning and finish_reason == "length":
        raise OpenAIMacroError(
            "The model returned only reasoning and no final JSON answer. "
            "Try reducing prompt complexity, increasing max_tokens, or switching models."
        )

    if not content:
        raise OpenAIMacroError(
            f"The model returned an empty response. finish_reason={finish_reason!r}"
        )

    return content


def extract_macros_from_openai(meal_description, model=None, temperature=None, max_tokens=None):
    """Calls paid OpenAI API and returns raw model text for macro extraction."""
    model = _resolve_value(model, DEFAULT_OPENAI_MODEL)
    temperature = _resolve_value(temperature, DEFAULT_TEMPERATURE)
    max_tokens = _resolve_value(max_tokens, DEFAULT_MAX_TOKENS)

    client = get_openai_client()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=_build_macro_messages(meal_description),
            response_format={"type": "json_object"},
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = _extract_content_from_response(response)
        print(f"[OpenAI API RAW RESPONSE]: {content}")
        try:
            st.code(content, language="text")
        except Exception:
            pass
        return content
    except Exception as e:
        raise OpenAIMacroError(_map_openai_error(e)) from e


def extract_macros_from_ollama(meal_description, model=None, temperature=None, max_tokens=None, think=None):
    """Calls local Ollama OpenAI-compatible API and returns raw model text."""
    model = _resolve_value(model, DEFAULT_OLLAMA_MODEL)
    temperature = _resolve_value(temperature, DEFAULT_TEMPERATURE)
    max_tokens = _resolve_value(max_tokens, DEFAULT_MAX_TOKENS)
    think = _resolve_value(think, DEFAULT_OLLAMA_THINK)

    client = get_ollama_client()
    attempts = [(think, max_tokens)]
    if think != "none":
        attempts.append(("none", max(max_tokens, 800)))
    attempts.append(("none", max(max_tokens * 2, 1200)))

    attempted = set()
    last_error = None

    for attempt_think, attempt_max_tokens in attempts:
        key = (attempt_think, attempt_max_tokens)
        if key in attempted:
            continue
        attempted.add(key)

        try:
            response = client.chat.completions.create(
                model=model,
                messages=_build_macro_messages(meal_description),
                response_format={"type": "json_object"},
                temperature=temperature,
                max_tokens=attempt_max_tokens,
                extra_body={"think": attempt_think},
            )
            content = _extract_content_from_response(response)
            print(f"[Ollama API RAW RESPONSE]: {content}")
            try:
                st.code(content, language="text")
            except Exception:
                pass
            return content
        except OpenAIMacroError as e:
            last_error = e
            if REASONING_ONLY_ERROR_FRAGMENT in str(e):
                continue
            raise
        except Exception as e:
            raise OpenAIMacroError(_map_openai_error(e)) from e

    raise last_error if last_error else OpenAIMacroError("Ollama returned no usable response.")


def get_macros_from_meal_description(
    meal_description,
    model=None,
    temperature=None,
    max_tokens=None,
    use_local=False,
    local_model=None,
    think=None,
):
    """Single call used by app code: returns parsed macro tuple.

    Set use_local=True to route the request to the locally hosted Ollama model
    (local_model) instead of the paid OpenAI API.
    """
    model = _resolve_value(model, DEFAULT_OPENAI_MODEL)
    local_model = _resolve_value(local_model, DEFAULT_OLLAMA_MODEL)
    temperature = _resolve_value(temperature, DEFAULT_TEMPERATURE)
    max_tokens = _resolve_value(max_tokens, DEFAULT_MAX_TOKENS)
    think = _resolve_value(think, DEFAULT_OLLAMA_THINK)

    if use_local:
        content = extract_macros_from_ollama(
            meal_description=meal_description,
            model=local_model,
            temperature=temperature,
            max_tokens=max_tokens,
            think=think,
        )
    else:
        content = extract_macros_from_openai(
            meal_description=meal_description,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    return parse_openai_macro_response(content)


if __name__ == "__main__":
    test_meal = input("Enter a meal description: ")
    try:
        raw = extract_macros_from_openai(test_meal)
        parsed = parse_openai_macro_response(raw)
        print("OpenAI raw response:")
        print(raw)
        print("Parsed macro tuple:")
        print(parsed)
    except Exception as e:
        print(f"Error: {e}")