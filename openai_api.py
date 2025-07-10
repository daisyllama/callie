import openai
import os
import streamlit as st

def get_openai_client():
    api_key = None
    try:
        api_key = st.secrets["OPENAI_API_KEY"]
    except Exception:
        api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("No OpenAI API key found in Streamlit secrets or environment variable.")
    return openai.OpenAI(api_key=api_key)


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
                {"role": "system", "content": "You are a helpful assistant that estimates macro nutrient information from meal descriptions. Provide the output in a structured format. Output only the key-value pairs, no extra text. Example: Meal description: Grilled Chicken Salad 'Meal: Grilled Chicken Salad, Calories: 350kcal, Protein: 40g, Fat: 15g, Cholesterol: 80mg, Carbs: 20g'"},
                {"role": "user", "content": f"Extract macros for: {meal_description}"}
            ],
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
        raise RuntimeError(f"OpenAI API error: {e}")


if __name__ == "__main__":
    test_meal = input("Enter a meal description: ")
    try:
        result = extract_macros_from_meal(test_meal)
        print("OpenAI Macro Extraction Result:")
        print(result)
    except Exception as e:
        print(f"Error: {e}")