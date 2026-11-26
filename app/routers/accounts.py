"""Account management for admins: list users and create new ones.

POST /users creates an account with an employee ID, name, email, role and starting password.
Both endpoints are admin only. The password is hashed before it is stored, and it is never
returned or written to the audit log. The new user can sign in at once through POST /auth/login."""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import ROLES, User
from app.db.security import hash_password
from app.db.session import get_session
from app.deps import require_roles
from app.routers.auth import password_problem
from app.tools.executor import audit

router = APIRouter(tags=["accounts"])

EMPLOYEE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{2,19}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class NewUser(BaseModel):
    employee_id: str = Field(min_length=3, max_length=20)
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=255)
    role: str
    password: str = Field(min_length=1, max_length=200)


def user_out(user: User) -> dict:
    return {
        "employee_id": user.employee_id, "name": user.name, "email": user.email, "role": user.role,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.get("/users")
def list_users(admin: User = Depends(require_roles("admin")), session=Depends(get_session)):
    users = session.scalars(select(User).order_by(User.employee_id)).all()
    return [user_out(u) for u in users]


@router.post("/users", status_code=201)
def create_user(body: NewUser, admin: User = Depends(require_roles("admin")), session=Depends(get_session)):
    employee_id = body.employee_id.strip()
    name = body.name.strip()
    email = body.email.strip().lower()

    if not EMPLOYEE_ID_PATTERN.match(employee_id):
        raise HTTPException(status_code=400, detail="Employee ID: use 3 to 20 letters, numbers or hyphens.")
    if not name:
        raise HTTPException(status_code=400, detail="Enter a name.")
    if not EMAIL_PATTERN.match(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if body.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"Role must be one of: {', '.join(ROLES)}.")
    problem = password_problem(body.password, employee_id)
    if problem:
        raise HTTPException(status_code=400, detail=problem)

    if session.scalar(select(User).where(User.employee_id == employee_id)):
        raise HTTPException(status_code=409, detail="That employee ID is already in use.")
    if session.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="That email address is already in use.")

    user = User(employee_id=employee_id, name=name, email=email, role=body.role,
                password_hash=hash_password(body.password))
    session.add(user)
    try:
        session.flush()   # assigns user.id for the audit entry
        audit(session, admin.id, "user.created", "user", user.id)
        session.commit()
    except IntegrityError:   # two admins submitted the same ID or email at the same moment
        session.rollback()
        raise HTTPException(status_code=409, detail="That employee ID or email address is already in use.")
    return user_out(user)
