from fastapi import FastAPI, Request, Response
import requests
from groq import Groq
#from africastalking.AfricasTalkingGateway import AfricasTalkingGatewayException
import africastalking
from dotenv import load_dotenv
import os
import json

# Load env vars
load_dotenv()

# Initialize FastAPI
app = FastAPI()

# Initialize Groq
groq_client = Groq()

# Initialize Africa's Talking
AT_USERNAME = os.getenv("AT_USERNAME")
AT_API_KEY = os.getenv("AT_API_KEY")

africastalking.initialize(AT_USERNAME, AT_API_KEY)
# We use the SMS class because AT routes sandbox WhatsApp messages through here for testing
sms = africastalking.SMS 

# ==========================================
# 1. YOUR AGENT LOGIC 
# ==========================================
def calculate_withholding_tax(amount: float) -> float:
    return amount * 0.05

def save_receipt_locally(data: dict) -> str:
    with open("receipts.txt", "a") as file:
        file.write(json.dumps(data) + "\n")
    return "Receipt saved successfully"

tools = [
    {
        "type": "function",
        "function": {
            "name": "calculate_withholding_tax",
            "description": "Calculates the 5% Kenyan withholding tax for rent payments.",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": { "type": "number", "description": "The total rent amount received" }
                },
                "required": ["amount"],
            },
        },
    }
]

def process_mpesa_with_agent(sms_text: str) -> str:
    system_prompt = """
    You are a Kenyan Business Accounting Agent. Your job is to process M-Pesa messages.
    You have access to ONLY the following tool: calculate_withholding_tax.
    Do NOT invent or call tools that are not listed. 

    Instructions:
    1. Read the M-Pesa message.
    2. If the reason for payment includes the word 'Rent', you MUST call the calculate_withholding_tax tool with the amount.
    3. If it is NOT for rent, do NOT use any tools. Just output a summary of the transaction.
    4. Always return a clean, SMS-friendly summary of the transaction and any calculated tax. Use emojis.
    """
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": sms_text}
    ]
    
    response = groq_client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=messages,
        tools=tools,
        tool_choice="auto"
    )
    
    message = response.choices[0].message
    
    if message.tool_calls:
        messages.append(message)
        for tool_call in message.tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            
            if function_name == "calculate_withholding_tax":
                result = calculate_withholding_tax(function_args["amount"])
                messages.append({"role": "tool", "content": str(result), "tool_call_id": tool_call.id})
        
        final_response = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages
        )
        return final_response.choices[0].message.content
    else:
        return message.content

# ==========================================
# 2. AFRICA'S TALKING WEBHOOK
# ==========================================
@app.post("/whatsapp")
async def at_webhook(request: Request):
    """Handles incoming messages from Africa's Talking"""
    try:
        form_data = await request.form()
        
        # AT sends the message text and sender phone in this format
        incoming_msg = form_data.get("text", "")
        sender_phone = form_data.get("from", "")
        
        if not incoming_msg:
            return Response(content="No message", status_code=200)

        print(f"📥 Received AT message from {sender_phone}: {incoming_msg}")
        
        # Send the message to our Groq Agent
        agent_reply = process_mpesa_with_agent(incoming_msg)
        
        print(f"✅ SUCCESS! AGENT REPLY GENERATED:\n{agent_reply}")
        
        # SIMPLIFIED REPLY: Just return the text directly!
        # Africa's Talking will automatically send this string back to the simulator.
        return Response(content=agent_reply, media_type="text/plain")

    except Exception as e:
        print(f"❌ CRITICAL ERROR IN WEBHOOK: {e}")
        return Response(content="Server Error", status_code=500)

@app.get("/")
async def root():
    return {"message": "BiasharaForce AT Agent is running!"}