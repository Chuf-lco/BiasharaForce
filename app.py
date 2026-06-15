from fastapi import FastAPI, Request, Response
from groq import Groq
import africastalking
from dotenv import load_dotenv
import os
import json
import sqlite3
from fpdf import FPDF
import datetime

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
sms = africastalking.SMS 

# ==========================================
# 1. DATABASE SETUP
# ==========================================
def init_db():
    conn = sqlite3.connect('biasharaforce.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS transactions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 sender_phone TEXT,
                 sender_name TEXT,
                 amount REAL,
                 tax_amount REAL,
                 reason TEXT,
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

    #Add a timestamp to the filename to ensure uniqueness
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")  
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
    }
]

# ==========================================
# 4. AGENTIC LOOP
# ==========================================
def process_mpesa_with_agent(sms_text: str, sender_phone: str) -> str:
    system_prompt = """
    You are BiasharaForce, a Kenyan Business Accounting Agent. 
    You process M-Pesa messages. You must follow these steps in order using your tools. 
    YOU MUST USE EVERY TOOL LISTED BELOW. DO NOT SKIP ANY STEPS.
    
    1. Extract the sender's Name, Phone, Amount, and Reason from the message text.
    2. Use the check_customer_history tool using the extracted Phone number.
    3. If the Reason contains 'Rent', use the calculate_withholding_tax tool. Otherwise, tax is 0.
    4. Use the save_transaction_to_db tool using the extracted details.
    5. Use the generate_invoice_pdf tool using the extracted details.
    6. Finally, reply to the user with an SMS summary. Greet them by Name. If the history tool found past transactions, say "Welcome back!". If not, say "Welcome!".
    
    Do not output any text to the user until ALL tool steps are completely finished.
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
        form_data = await request.form()
        incoming_msg = form_data.get("text", "")
        sender_phone = form_data.get("from", "")
        
        if not incoming_msg:
            return Response(content="No message", status_code=200)

        print(f"📥 Received AT message from {sender_phone}: {incoming_msg}")
        
        agent_reply = process_mpesa_with_agent(incoming_msg, sender_phone)
        
        print(f"✅ SUCCESS! AGENT REPLY GENERATED:\n{agent_reply}")
        
        return Response(content=agent_reply, media_type="text/plain")

    except Exception as e:
        print(f"❌ CRITICAL ERROR IN WEBHOOK: {e}")
        return Response(content="Server Error", status_code=500)

@app.get("/")
async def root():
    return {"message": "BiasharaForce DB + PDF Agent is running!"}