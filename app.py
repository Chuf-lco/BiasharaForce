import requests
from fastapi import FastAPI, Request, Response
from groq import Groq
import africastalking
from dotenv import load_dotenv
import os
import json
import sqlite3
import datetime
from fpdf import FPDF

# Load env vars
load_dotenv()

# Initialize FastAPI
app = FastAPI()

# Initialize Groq
groq_client = Groq()

# Initialize Africa's Talking
AT_USERNAME = os.getenv("AT_USERNAME")
AT_API_KEY = os.getenv("AT_API_KEY")

# Debug print to see what the server is actually reading (only prints first 5 chars for safety)
if AT_API_KEY:
    print(f"🔍 Found AT API Key starting with: {AT_API_KEY[:5]}...")
else:
    print("❌ CRITICAL: AT_API_KEY environment variable is completely missing!")

# For the cloud, we default to 'sandbox' if no username is provided
if not AT_USERNAME:
    AT_USERNAME = "sandbox"

try:
    africastalking.initialize(AT_USERNAME, AT_API_KEY)
    sms = africastalking.SMS 
    print("✅ Africa's Talking SDK Initialized Successfully!")
except Exception as e:
    print(f"❌ Could not initialize Africa's Talking: {e}")
    sms = None
# ==========================================
# 1. DATABASE SETUP
# ==========================================
def init_db():
    conn = sqlite3.connect('biasharaforce.db')
    c = conn.cursor()
    
    # Main transactions table
    c.execute('''CREATE TABLE IF NOT EXISTS transactions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 sender_phone TEXT,
                 sender_name TEXT,
                 amount REAL,
                 tax_amount REAL,
                 reason TEXT,
                 timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
                 
    # NEW: Pending actions table for Human-in-the-Loop
    c.execute('''CREATE TABLE IF NOT EXISTS pending_actions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 action_type TEXT,
                 action_data TEXT,
                 status TEXT DEFAULT 'pending',
                 timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
                 
    conn.commit()
    conn.close()

@app.on_event("startup")
async def startup_event():
    init_db()
    print("✅ Database initialized!")

# ==========================================
# 2. PYTHON FUNCTIONS (The Agent's Tools)
# ==========================================
def calculate_withholding_tax(amount: float) -> float:
    return amount * 0.05

def check_customer_history(sender_phone: str) -> str:
    conn = sqlite3.connect('biasharaforce.db')
    c = conn.cursor()
    c.execute("SELECT sender_name, amount, reason, timestamp FROM transactions WHERE sender_phone=?", (sender_phone,))
    rows = c.fetchall()
    conn.close()
    if not rows:
        return "No past transactions found for this phone number. This is a new customer."
    else:
        history = f"Found {len(rows)} past transaction(s):\n"
        for row in rows:
            history += f"- {row[0]} paid {row[1]} for {row[2]} on {row[3]}\n"
        return history

def save_transaction_to_db(sender_phone: str, sender_name: str, amount: float, tax_amount: float, reason: str) -> str:
    conn = sqlite3.connect('biasharaforce.db')
    c = conn.cursor()
    c.execute("INSERT INTO transactions (sender_phone, sender_name, amount, tax_amount, reason) VALUES (?, ?, ?, ?, ?)",
              (sender_phone, sender_name, amount, tax_amount, reason))
    conn.commit()
    conn.close()
    return "Transaction saved successfully to database."

def generate_invoice_pdf(sender_name: str, amount: float, tax_amount: float, reason: str) -> str:
    if not os.path.exists('invoices'):
        os.makedirs('invoices')
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"invoices/invoice_{sender_name.replace(' ', '_')}_{amount}_{timestamp}.pdf"
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 24)
    pdf.cell(0, 20, "BIASHARAFORCE INVOICE", ln=True, align="C")
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 10, "Powered by AI Agents", ln=True, align="C")
    pdf.ln(20)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, f"Client: {sender_name}", ln=True)
    pdf.ln(5)
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 10, f"Description: {reason}", ln=True)
    pdf.cell(0, 10, f"Subtotal: Ksh {amount:,.2f}", ln=True)
    if tax_amount > 0:
        pdf.cell(0, 10, f"Withholding Tax (5%): Ksh {tax_amount:,.2f}", ln=True)
        pdf.cell(0, 10, f"Net Payable: Ksh {amount - tax_amount:,.2f}", ln=True)
    else:
        pdf.cell(0, 10, f"Total: Ksh {amount:,.2f}", ln=True)
    pdf.output(filename)
    return f"Invoice successfully generated at {filename}"

#Audio Transcription Tool
def transcribe_audio(audio_url: str) -> str:
    """Downloads audio from a URL and transcribes it using Groq Whisper."""
    try:
        # 1. Download the audio file from WhatsApp
        # In production, this URL requires authentication, but we build the logic now
        response = requests.get(audio_url)
        audio_content = response.content
        
        # 2. Send to Groq Whisper for transcription
        # We specify 'sw' for Swahili, but Whisper is smart enough to handle English/Sheng mix
        transcription = groq_client.audio.transcriptions.create(
            file=("voice_note.ogg", audio_content),
            model="whisper-large-v3",
            response_format="text",
            language="sw" 
        )
        print(f"🎙️ Transcription: {transcription}")
        return transcription
        
    except Exception as e:
        print(f"❌ Error transcribing audio: {e}")
        return "Error: Could not transcribe audio."
    
# NEW TOOLS: Pause and Confirm Actions
def create_pending_action(action_type: str, action_data: dict) -> str:
    """Saves a dangerous action as 'pending' so the user must confirm it."""
    conn = sqlite3.connect('biasharaforce.db')
    c = conn.cursor()
    c.execute("INSERT INTO pending_actions (action_type, action_data) VALUES (?, ?)",
              (action_type, json.dumps(action_data)))
    conn.commit()
    conn.close()
    return "Action saved as pending. You MUST ask the user to confirm by replying YES."

def confirm_pending_action() -> str:
    """Executes the most recent pending action."""
    conn = sqlite3.connect('biasharaforce.db')
    c = conn.cursor()
    c.execute("SELECT id, action_type, action_data FROM pending_actions WHERE status='pending' ORDER BY timestamp DESC LIMIT 1")
    row = c.fetchone()
    
    if not row:
        conn.close()
        return "No pending actions to confirm."
        
    action_id, action_type, action_data_json = row
    action_data = json.loads(action_data_json)
    
    # Mark as confirmed
    c.execute("UPDATE pending_actions SET status='confirmed' WHERE id=?", (action_id,))
    conn.commit()
    conn.close()
    
    # Now execute the actual tools!
    if action_type == "high_value_transaction":
        save_transaction_to_db(**action_data)
        generate_invoice_pdf(
            sender_name=action_data["sender_name"],
            amount=action_data["amount"],
            tax_amount=action_data["tax_amount"],
            reason=action_data["reason"]
        )
        return "High value transaction confirmed, saved, and invoice generated!"
        
    return "Action confirmed and executed."

# ==========================================
# 3. TOOL DEFINITIONS FOR THE LLM
# ==========================================
tools = [
    {
        "type": "function",
        "function": {
            "name": "calculate_withholding_tax",
            "description": "Calculates the 5% Kenyan withholding tax for rent payments.",
            "parameters": {
                "type": "object",
                "properties": {"amount": {"type": "number", "description": "The total rent amount received"}},
                "required": ["amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_customer_history",
            "description": "Checks the database for past payments from this specific phone number.",
            "parameters": {
                "type": "object",
                "properties": {"sender_phone": {"type": "string", "description": "The phone number of the sender"}},
                "required": ["sender_phone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_transaction_to_db",
            "description": "Saves the finalized transaction details to the database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sender_phone": {"type": "string"},
                    "sender_name": {"type": "string"},
                    "amount": {"type": "number"},
                    "tax_amount": {"type": "number"},
                    "reason": {"type": "string"}
                },
                "required": ["sender_phone", "sender_name", "amount", "tax_amount", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_invoice_pdf",
            "description": "Generates a PDF invoice for the transaction and saves it locally.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sender_name": {"type": "string"},
                    "amount": {"type": "number"},
                    "tax_amount": {"type": "number"},
                    "reason": {"type": "string"}
                },
                "required": ["sender_name", "amount", "tax_amount", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_pending_action",
            "description": "Pauses a dangerous or high-value transaction and marks it as pending until the user confirms.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action_type": {"type": "string", "description": "The type of action, e.g., 'high_value_transaction'"},
                    "action_data": {"type": "object", "description": "The data needed to execute the action later"}
                },
                "required": ["action_type", "action_data"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_pending_action",
            "description": "If the user replies YES to confirm a pending action, execute it.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    }
]

# ==========================================
# 4. AGENTIC LOOP
# ==========================================
def process_mpesa_with_agent(sms_text: str, sender_phone: str) -> str:
    system_prompt = """
    You are BiasharaForce, a Kenyan Business Accounting Agent. 
    You process M-Pesa messages. 
    
    CRITICAL RULES FOR HUMAN-IN-THE-LOOP:
    - If the message is exactly 'YES' or 'NDIO', you MUST use the `confirm_pending_action` tool. Do not do anything else.
    - If the transaction amount is GREATER THAN 10,000 Ksh, OR the reason contains high-value items like 'TV', 'Laptop', or 'Car', you MUST treat this as a high-value transaction. Use `create_pending_action` and ask for confirmation.
    
    CRITICAL RULES FOR TAX:
    - ONLY call `calculate_withholding_tax` if the Reason contains the word 'Rent'. 
    - If the reason is ANYTHING ELSE (Internet, Airtime, Tomatoes, etc.), DO NOT call the tax tool. The tax is strictly 0.
    
    STANDARD WORKFLOW:
    1. Check customer history.
    2. Extract details. Apply Tax ONLY if Rent.
    3. Save to DB (tax will be 0 if not rent). Generate PDF.
    4. Reply with summary.
    
    DO NOT output code snippets. Use the tools via the API.
    """
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Phone number: {sender_phone}\nMessage: {sms_text}"}
    ]
    
    while True:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )
        
        message = response.choices[0].message
        
        if not message.tool_calls:
            return message.content
            
        messages.append(message)
        
        for tool_call in message.tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            
            print(f"🛠️ Agent is using tool: {function_name} with args: {function_args}")
            
            if function_name == "calculate_withholding_tax":
                result = calculate_withholding_tax(function_args["amount"])
            elif function_name == "check_customer_history":
                result = check_customer_history(function_args["sender_phone"])
            elif function_name == "save_transaction_to_db":
                result = save_transaction_to_db(**function_args)
            elif function_name == "generate_invoice_pdf":
                result = generate_invoice_pdf(**function_args)
            elif function_name == "create_pending_action":
                result = create_pending_action(**function_args)
            elif function_name == "confirm_pending_action":
                result = confirm_pending_action()
            else:
                result = "Unknown function"
                
            messages.append({
                "role": "tool",
                "content": str(result),
                "tool_call_id": tool_call.id,
            })

# ==========================================
# 5. AFRICA'S TALKING WEBHOOK
# ==========================================
@app.post("/whatsapp")
async def at_webhook(request: Request):
    try:
        # 1. Parse incoming form data from Africa's Talking
        form_data = await request.form()
        
        # AT sends 'text' for SMS and 'MediaUrl0' for Voice Notes
        media_url = form_data.get("MediaUrl0")
        incoming_text = form_data.get("text", "")
        sender_phone = form_data.get("from", "")
        
        incoming_msg = ""
        
        # 2. Handle Voice Notes vs Text
        if media_url:
            print(f"🎙️ Received Voice Note from {sender_phone}")
            incoming_msg = transcribe_audio(media_url)
        elif incoming_text:
            print(f"📥 Received Text from {sender_phone}: {incoming_text}")
            incoming_msg = incoming_text
        else:
            print("⚠️ Received empty message.")
            return Response(content="No message", status_code=200)

        # 3. Process the message with your Groq Agent
        if incoming_msg and "Error:" not in incoming_msg:
            agent_reply = process_mpesa_with_agent(incoming_msg, sender_phone)
            print(f"✅ AGENT REPLY GENERATED:\n{agent_reply}")
            
            # 4. ACTIVELY PUSH REPLY VIA AT SDK (Crucial for Cloud/SMS!)
            # In the cloud, returning text in the HTTP response doesn't send the SMS.
            # We must use the SDK to push the message back to the user.
            try:
                if sms: # Check if the SDK initialized properly
                    response = sms.send(agent_reply, [sender_phone])
                    print(f"📱 AT SDK Reply Sent! Response: {response}")
                else:
                    print("❌ SMS SDK not initialized. Check AT API Keys in Render Environment Variables.")
            except Exception as sms_error:
                print(f"❌ Failed to send SMS via SDK: {sms_error}")
        else:
            print(f"⚠️ Skipping agent processing. Transcription failed or message was empty.")

        # 5. Always return 200 OK immediately so AT stops retrying
        return Response(content="OK", status_code=200)

    except Exception as e:
        print(f"❌ CRITICAL ERROR IN WEBHOOK: {e}")
        # Still return 200 OK to AT even if our code crashes, so they don't spam us
        return Response(content="Server Error", status_code=200)
@app.get("/")
async def root():
    return {"message": "BiasharaForce HITL Agent is running!"}