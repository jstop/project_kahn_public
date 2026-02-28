"""Quick smoke test: send a minimal request to each API provider using the
models expected by the Osmio tournament."""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

def test_anthropic():
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    resp = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=32,
        messages=[{"role": "user", "content": "Say 'hello' and nothing else."}],
    )
    text = resp.content[0].text.strip()
    print(f"  Anthropic (claude-sonnet-4-20250514): '{text}'")
    return True

def test_openai():
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = client.chat.completions.create(
        model="gpt-5.2",
        max_completion_tokens=32,
        messages=[{"role": "user", "content": "Say 'hello' and nothing else."}],
    )
    text = resp.choices[0].message.content.strip()
    print(f"  OpenAI (gpt-5.2):                    '{text}'")
    return True

def test_google():
    import google.generativeai as genai
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel("gemini-3-flash-preview")
    resp = model.generate_content("Say 'hello' and nothing else.")
    text = resp.text.strip()
    print(f"  Google (gemini-3-flash-preview):      '{text}'")
    return True

if __name__ == "__main__":
    tests = [
        ("Anthropic", test_anthropic),
        ("OpenAI", test_openai),
        ("Google", test_google),
    ]
    results = {}
    for name, fn in tests:
        try:
            fn()
            results[name] = "PASS"
        except Exception as e:
            print(f"  {name}: FAILED - {e}")
            results[name] = "FAIL"

    print()
    for name, status in results.items():
        print(f"  {name}: {status}")
    print()
    print("All keys working!" if all(v == "PASS" for v in results.values()) else "Some keys failed - check above.")
    sys.exit(0 if all(v == "PASS" for v in results.values()) else 1)
