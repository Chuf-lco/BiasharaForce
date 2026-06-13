import json
import os
from groq import Groq
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
client = Groq()

# ==========================================
# 1. DEFINE THE TOOLS (Python Functions)
# ==========================================

def calculate_withholding_tax(amount: float) -> float:
    """Calculates 5% withholding tax for rent payments in Kenya."""
    return amount * 0.05

def save_receipt_locally(data: dict) -> str:
    """Saves the receipt data to a local text file."""
    with open("receipts.txt", "a") as file:
        file.write(json.dumps(data) + "\n")
    return "Receipt saved successfully to receipts.txt"

# ==========================================
# 2. DEFINE THE TOOLS FOR THE LLM
# ==========================================
# We must describe the tools in a format the LLM understands

tools = [
    {
        "type": "function",
        "function": {
            "name": "calculate_withholding_tax",
            "description": "Calculates the 5% Kenyan withholding tax for rent payments.",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "number",
                        "description": "The total rent amount received via M-Pesa",
                    }
                },
                "required": ["amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_receipt_locally",
            "description": "Saves the transaction and tax data as a receipt on the local machine.",
            "parameters": {
                "type": "object",
                "properties": {
                    "data": {
                        "type": "object",
                        "description": "The dictionary containing sender, amount, and tax details",
                    }
                },
                "required": ["data"],
            },
        },
    }
]

# ==========================================
# 3. THE AGENTIC LOOP
# ==========================================

mpesa_sms = "SWK23F45G confirmed. Ksh 20,000.00 received from JANE DOE 254712345678 for March Rent on 24/5/24."

system_prompt = """
You are a Kenyan Business Accounting Agent. Your job is to process M-Pesa messages.
1. First, extract the amount, sender_name, and reason for payment (if stated).
2. If the payment is for 'Rent', you MUST use the calculate_withholding_tax tool to figure out the 5% tax.
3. Finally, you MUST use the save_receipt_locally tool to save the final data (including the tax calculated).
4. Always return a human-readable summary of the transaction and tax details at the end.
5. Tax is deducted from the gross
"""

def run_agent():
    print(f"📥 Incoming SMS: {mpesa_sms}\n")
    
    # Step A: Initial call to the LLM
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": mpesa_sms}
    ]
    
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=messages,
        tools=tools,
        tool_choice="auto" # Let the LLM decide when to use tools
    )
    
    # Step B: Check if the LLM decided to use a tool
    message = response.choices[0].message
    
    if message.tool_calls:
        print("🛠️ Agent is thinking... It decided to use tools!")
        
        # We need to execute the tools and give the results back to the LLM
        messages.append(message) # Add the LLM's request to the history
        
        for tool_call in message.tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            
            print(f"-> Executing: {function_name}({function_args})")
            
            # Step C: ACTUALLY run our Python functions
            if function_name == "calculate_withholding_tax":
                result = calculate_withholding_tax(function_args["amount"])
            elif function_name == "save_receipt_locally":
                result = save_receipt_locally(function_args["data"])
            else:
                result = "Unknown function"
                
            print(f"-> Result: {result}\n")
            
            # Step D: Give the tool result back to the LLM so it can continue
            messages.append(
                {
                    "role": "tool",
                    "content": str(result),
                    "tool_call_id": tool_call.id,
                }
            )
        
        # Step E: Final call to get the human-readable summary
        final_response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages
        )
        
        print("✅ Agent Final Report:")
        print(final_response.choices[0].message.content)
        
    else:
        # If it didn't use tools, just print the text
        print("✅ Agent Response:")
        print(message.content)

if __name__ == "__main__":
    run_agent()