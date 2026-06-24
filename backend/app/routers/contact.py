from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

from app.services.email import send_async
from app.services.system_log import app_log

router = APIRouter(prefix="/contact", tags=["contact"])

OWNER_EMAIL = "pdwiens@gmail.com"
FROM = "Upset Alert <info@upsetalert.ca>"


class ContactRequest(BaseModel):
    name: str
    email: EmailStr
    subject: str
    body: str


@router.post("")
async def send_contact(req: ContactRequest):
    if not req.name.strip() or not req.subject.strip() or not req.body.strip():
        raise HTTPException(status_code=422, detail="All fields are required.")

    html = f"""
    <div style="font-family:sans-serif;max-width:560px;margin:0 auto;padding:32px 24px">
      <p style="margin:0 0 8px;font-size:14px;color:#888">
        Message from <strong>{req.name}</strong> ({req.email}) via upsetalert.ca
      </p>
      <hr style="border:none;border-top:1px solid #e5e7eb;margin:12px 0 20px">
      <p style="font-size:15px;color:#111;white-space:pre-wrap;line-height:1.65">{req.body}</p>
    </div>
    """

    await send_async({
        "from": FROM,
        "to": [OWNER_EMAIL],
        "reply_to": req.email,
        "subject": f"[Upset Alert] {req.subject}",
        "html": html,
    })

    await app_log(
        "info", "contact",
        f"Contact form submission from {req.name} ({req.email}): {req.subject}",
        {"name": req.name, "email": req.email, "subject": req.subject},
    )

    return {"ok": True}
