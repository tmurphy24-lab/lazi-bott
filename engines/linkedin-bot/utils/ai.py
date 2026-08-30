from dotenv import load_dotenv
import os
import openai
from pprint import pprint

# Load .env file
load_dotenv()
# Access the variables
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
# PATCHED by linkedin-autopilot: read base_url from env so Poolside/Google/etc. work
OPENAI_API_BASE_URL = os.getenv('OPENAI_API_BASE_URL')

if OPENAI_API_BASE_URL:
    client = openai.OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_API_BASE_URL)
else:
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
def chatgpt(prompt:str, model='gpt-4-turbo-preview', max_tokens=None):
    try:
        # select model from ['gpt-3.5-turbo', 'gpt-4', 'gpt-4-turbo-preview', 'gpt-4-32k', 'gpt-4-1106-preview']
        completion = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens, #4000
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        response = completion.choices[0].message.content
        return response
    
    except openai.RateLimitError as e:
        print(f"\nOpenAI RateLimitError: {e}")
        print(f"Exiting application...")
        exit()