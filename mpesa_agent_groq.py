import json
import os
from groq import Groq
from dotenv import load_dotenv

# 1. Initialize the Groq client 

load_dotenv()

# (It automatically reads the GROQ_API_KEY from your environment variables)
client = Groq()

# 2. Realistic Kenyan M-Pesa SMS data
mpesa_sms = "SWK23F45G confirmed. Ksh 5,500.00 received from JOHN DOE 254712345678 on 24/5/24 at 10:30 AM. New M-PESA balance is Ksh 12,300.00."

# 3. The System Prompt
# Notice we explicitly tell it to output JSON and nothing else.
system_prompt = """
You are a data extraction assistant for Kenyan M-Pesa transactions. 
Extract the following details from the user's message:
- amount (must be a float)
- sender_name (string)
- sender_phone (string)
- date (string)

Return the result strictly as a JSON object. Do not include any other text.
"""

def extract_mpesa_data(sms_text):
    try:
        # 4. Make the API call to Groq
        chat_completion = client.chat.completions.create(
            # Using Llama 3 8B on Groq - it's incredibly fast and great at this task!
            model="llama-3.1-8b-instant",
            
            # Forces the model to output valid JSON
            response_format={ "type": "json_object" },
            
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": sms_text}
            ]
        )

        # 5. Extract the response and parse it as JSON
        raw_output = chat_completion.choices[0].message.content
        parsed_data = json.loads(raw_output)
        
        return parsed_data

    except Exception as e:
        print(f"An error occurred: {e}")
        return None

# Run the script
if __name__ == "__main__":
    print("Processing M-Pesa SMS via Groq (Llama 3)...")
    result = extract_mpesa_data(mpesa_sms)
    
    if result:
        print("\n✅ Successfully Extracted Data:")
        # Print it nicely with indentations
        print(json.dumps(result, indent=4))