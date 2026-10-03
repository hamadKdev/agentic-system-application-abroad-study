from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client
from dotenv import load_dotenv
import os
import httpx
import uuid
from fastapi import FastAPI
load_dotenv()
import httpx
app = FastAPI()

@app.get("/")
def home():
    return {"message": "AdmitCrew Backend Running"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# SUPABASE
# =========================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)

# =========================
# N8N WEBHOOKS
# =========================

LEAD_AGENT_WEBHOOK = os.getenv("LEAD_AGENT_WEBHOOK")
UNIVERSITY_AGENT_WEBHOOK = os.getenv("UNIVERSITY_AGENT_WEBHOOK")
DOCUMENT_AGENT_WEBHOOK = os.getenv("DOCUMENT_AGENT_WEBHOOK")
FOLLOWUP_AGENT_WEBHOOK = os.getenv("FOLLOWUP_AGENT_WEBHOOK")


# =========================
# MODELS
# =========================

class SignupRequest(BaseModel):
    name: str
    email: str
    password: str
    role: str = "student"


class LoginRequest(BaseModel):
    email: str
    password: str


class ChatRequest(BaseModel):
    phone: str
    message: str


class LeadRequest(BaseModel):
    name: str
    phone: str
    country: str | None = None
    marks: float | None = None
    ielts: float | None = None
    budget: str | None = None


# =========================
# HOME
# =========================

@app.get("/")
def home():
    return {
        "message": "AdmitCrew Backend is running"
    }


# =========================
# AUTH
# =========================

@app.post("/auth/signup")
def signup(data: SignupRequest):

    existing = (
        supabase
        .table("users")
        .select("*")
        .eq("email", data.email)
        .execute()
    )

    if existing.data:
        raise HTTPException(
            status_code=400,
            detail="Email already exists"
        )

    result = (
        supabase
        .table("users")
        .insert({
            "name": data.name,
            "email": data.email,
            "password": data.password,
            "role": data.role
        })
        .execute()
    )

    return {
        "message": "Signup successful",
        "user": result.data
    }


@app.post("/auth/login")
def login(data: LoginRequest):

    result = (
        supabase
        .table("users")
        .select("*")
        .eq("email", data.email)
        .eq("password", data.password)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    return {
        "message": "Login successful",
        "user": result.data[0]
    }


# =========================
# LEADS
# =========================

@app.post("/leads")
def create_lead(data: LeadRequest):

    # Check duplicate phone
    existing = (
        supabase
        .table("leads")
        .select("*")
        .eq("phone", data.phone)
        .execute()
    )

    if existing.data:
        return {
            "message": "Lead already exists",
            "lead": existing.data[0]
        }

    result = (
        supabase
        .table("leads")
        .insert({
            "name": data.name,
            "phone": data.phone,
            "country": data.country,
            "marks": data.marks,
            "ielts": data.ielts,
            "budget": data.budget,
            "stage": "New"
        })
        .execute()
    )

    return {
        "message": "Lead created",
        "lead": result.data
    }


@app.get("/leads")
def get_leads():

    result = (
        supabase
        .table("leads")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )

    return result.data


@app.get("/leads/{lead_id}")
def get_lead(lead_id: str):

    result = (
        supabase
        .table("leads")
        .select("*")
        .eq("id", lead_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=404,
            detail="Lead not found"
        )

    return result.data[0]


# =========================
# STUDENT CHAT
# =========================

@app.post("/chat")
async def chat(data: ChatRequest):

    # Find lead using phone
    lead_result = (
        supabase
        .table("leads")
        .select("*")
        .eq("phone", data.phone)
        .execute()
    )

    lead = lead_result.data[0] if lead_result.data else None

    # Save student message
    message_data = {
        "phone": data.phone,
        "message": data.message,
        "sender": "student"
    }

    if lead:
        message_data["lead_id"] = lead["id"]

    supabase.table("chat_messages").insert(
        message_data
    ).execute()

    # Send to Lead/Manager Agent
    payload = {
        "phone": data.phone,
        "message": data.message,
        "lead": lead
    }

    async with httpx.AsyncClient() as client:

        response = await client.post(
            LEAD_AGENT_WEBHOOK,
            json=payload,
            timeout=60
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=500,
            detail="AI agent error"
        )

    ai_response = response.json()

    # Save AI response
    ai_message = ai_response.get(
        "message",
        "Sorry, I could not process your request."
    )

    response_data = {
        "phone": data.phone,
        "message": ai_message,
        "sender": "ai"
    }

    if lead:
        response_data["lead_id"] = lead["id"]

    supabase.table("chat_messages").insert(
        response_data
    ).execute()

    return {
        "message": ai_message
    }


# =========================
# CHAT HISTORY
# =========================

@app.get("/chat/{lead_id}")
def chat_history(lead_id: str):

    result = (
        supabase
        .table("chat_messages")
        .select("*")
        .eq("lead_id", lead_id)
        .order("created_at")
        .execute()
    )

    return result.data


# =========================
# UNIVERSITIES
# =========================

@app.get("/universities")
def get_universities():

    result = (
        supabase
        .table("universities")
        .select("*")
        .execute()
    )

    return result.data


@app.get("/programs")
def get_programs():

    result = (
        supabase
        .table("programs")
        .select("*")
        .execute()
    )

    return result.data


# =========================
# UNIVERSITY AGENT
# =========================

@app.post("/agents/university")
async def university_agent(data: dict):

    async with httpx.AsyncClient() as client:

        response = await client.post(
            UNIVERSITY_AGENT_WEBHOOK,
            json=data,
            timeout=60
        )

    return response.json()


# =========================
# DOCUMENT UPLOAD
# =========================

@app.post("/agents/document")
async def document_agent(data: dict):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            DOCUMENT_AGENT_WEBHOOK,
            json=data
        )

    print("N8N STATUS:", response.status_code)
    print("N8N RESPONSE:", response.text)

    if response.status_code != 200:
        return {
            "success": False,
            "status_code": response.status_code,
            "n8n_response": response.text
        }

    try:
        return response.json()
    except Exception:
        return {
            "success": True,
            "n8n_response": response.text
        }
    

@app.post("/documents/upload")
async def upload_document(
    lead_id: str,
    file: UploadFile = File(...)
):

    allowed = [
        "application/pdf",
        "image/jpeg",
        "image/png"
    ]

    if file.content_type not in allowed:
        raise HTTPException(
            status_code=400,
            detail="Only PDF, JPG and PNG files are allowed"
        )

    file_content = await file.read()

    file_name = (
        f"{uuid.uuid4()}_{file.filename}"
    )

    # Upload to Supabase Storage
    storage_path = f"{lead_id}/{file_name}"

    supabase.storage \
        .from_("documents") \
        .upload(
            storage_path,
            file_content,
            {
                "content-type": file.content_type
            }
        )

    # Save document record
    result = (
        supabase
        .table("documents")
        .insert({
            "lead_id": lead_id,
            "file_name": file.filename,
            "file_path": storage_path,
            "status": "Pending"
        })
        .execute()
    )

    document = result.data[0]

    # Send document information to n8n
    payload = {
        "document_id": document["id"],
        "lead_id": lead_id,
        "file_name": file.filename,
        "file_path": storage_path
    }

    async with httpx.AsyncClient() as client:

        await client.post(
            DOCUMENT_AGENT_WEBHOOK,
            json=payload,
            timeout=60
        )

    return {
        "message": "Document uploaded",
        "document": document
    }


# =========================
# DOCUMENT RESULTS
# =========================

@app.get("/documents/{lead_id}")
def get_documents(lead_id: str):

    result = (
        supabase
        .table("documents")
        .select("*")
        .eq("lead_id", lead_id)
        .execute()
    )

    return result.data


# =========================
# FOLLOW-UP
# =========================

@app.post("/agents/followup")
async def run_followup(data: dict):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            FOLLOWUP_AGENT_WEBHOOK,
            json=data
        )

    print("N8N STATUS:", response.status_code)
    print("N8N RESPONSE:", response.text)

    if response.status_code != 200:
        return {
            "success": False,
            "status_code": response.status_code,
            "n8n_response": response.text
        }

    try:
        return response.json()
    except Exception:
        return {
            "success": True,
            "n8n_response": response.text
        }
    

# =========================
# APPROVALS
# =========================

@app.get("/approvals")
def get_approvals():

    result = (
        supabase
        .table("approvals")
        .select("*")
        .eq("status", "Pending")
        .execute()
    )

    return result.data


@app.post("/approvals/{approval_id}/approve")
async def approve_message(approval_id: str):

    result = (
        supabase
        .table("approvals")
        .select("*")
        .eq("id", approval_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=404,
            detail="Approval not found"
        )

    approval = result.data[0]

    if approval["status"] != "Pending":
        raise HTTPException(
            status_code=400,
            detail="Approval already processed"
        )

    # Update approval
    supabase.table("approvals").update({
        "status": "Approved"
    }).eq(
        "id", approval_id
    ).execute()

    return {
        "message": "Message approved",
        "approval_id": approval_id
    }


@app.post("/approvals/{approval_id}/reject")
def reject_message(approval_id: str):

    result = (
        supabase
        .table("approvals")
        .update({
            "status": "Rejected"
        })
        .eq("id", approval_id)
        .execute()
    )

    return {
        "message": "Message rejected",
        "data": result.data
    }


# =========================
# ESCALATIONS
# =========================

@app.get("/escalations")
def get_escalations():

    result = (
        supabase
        .table("escalations")
        .select("*")
        .eq("status", "Pending")
        .execute()
    )

    return result.data


@app.post("/escalations/{escalation_id}/reply")
def reply_escalation(
    escalation_id: str,
    data: dict
):

    result = (
        supabase
        .table("escalations")
        .update({
            "staff_reply": data.get("reply"),
            "status": "Resolved"
        })
        .eq("id", escalation_id)
        .execute()
    )

    return {
        "message": "Escalation resolved",
        "data": result.data
    }