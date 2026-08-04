import os
import sys
import json
import sqlite3
import hashlib
import hmac
import base64
import time
from typing import Optional, List, Dict, Any
from datetime import datetime, date

from fastapi import FastAPI, HTTPException, Depends, Header, Query, Response, status, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from pydantic import BaseModel, Field

# Secret key for JWT signing
JWT_SECRET = "sag_for_people_hr_crm_jwt_secret_key_2026_super_secure"

DB_FILE = os.path.join(os.path.dirname(__file__), "sag_hr.db")

# Helper functions for JWT
def base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('utf-8')

def base64url_decode(data: str) -> bytes:
    padding = '=' * (4 - (len(data) % 4))
    return base64.urlsafe_b64decode(data + padding)

def create_jwt_token(payload: dict) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_json = json.dumps(header, separators=(',', ':')).encode('utf-8')
    payload_json = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    
    header_b64 = base64url_encode(header_json)
    payload_b64 = base64url_encode(payload_json)
    
    signature_input = f"{header_b64}.{payload_b64}".encode('utf-8')
    signature = hmac.new(JWT_SECRET.encode('utf-8'), signature_input, hashlib.sha256).digest()
    signature_b64 = base64url_encode(signature)
    
    return f"{header_b64}.{payload_b64}.{signature_b64}"

def verify_jwt_token(token: str) -> Optional[dict]:
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None
        header_b64, payload_b64, signature_b64 = parts
        
        signature_input = f"{header_b64}.{payload_b64}".encode('utf-8')
        expected_sig = hmac.new(JWT_SECRET.encode('utf-8'), signature_input, hashlib.sha256).digest()
        actual_sig = base64url_decode(signature_b64)
        
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None
            
        payload_bytes = base64url_decode(payload_b64)
        payload = json.loads(payload_bytes.decode('utf-8'))
        
        if "exp" in payload and payload["exp"] < time.time():
            return None
            
        return payload
    except Exception:
        return None

def hash_pin(pin: str) -> str:
    return hashlib.sha256(f"{pin}_sag_salt_2026".encode('utf-8')).hexdigest()

# Database Helper
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # 3.1 factories
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS factories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name VARCHAR(255) NOT NULL
    );
    """)
    
    # 3.2 departments
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS departments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name VARCHAR(255) NOT NULL
    );
    """)
    
    # 3.3 users
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username_email VARCHAR(255) UNIQUE NOT NULL,
        first_name VARCHAR(255) NOT NULL,
        last_name VARCHAR(255) NOT NULL,
        phone VARCHAR(32) UNIQUE NOT NULL,
        factory_id INTEGER REFERENCES factories(id),
        department_id INTEGER REFERENCES departments(id),
        pin_hash VARCHAR(255) NOT NULL,
        status TEXT CHECK(status IN ('active', 'suspended')) DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    
    # 3.4 roles & user_roles
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS roles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code VARCHAR(50) UNIQUE NOT NULL,
        name VARCHAR(255) NOT NULL
    );
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_roles (
        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        role_id INTEGER REFERENCES roles(id) ON DELETE CASCADE,
        PRIMARY KEY (user_id, role_id)
    );
    """)
    
    # 3.5 requisitions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS requisitions (
        id VARCHAR(50) PRIMARY KEY,
        open_date DATE NOT NULL,
        plan_close_date DATE NOT NULL,
        actual_close_date DATE,
        manager_id INTEGER REFERENCES users(id),
        department_id INTEGER REFERENCES departments(id),
        title VARCHAR(255) NOT NULL,
        count INTEGER NOT NULL,
        salary VARCHAR(255),
        recruiter_id INTEGER REFERENCES users(id),
        status TEXT CHECK(status IN ('Новая заявка', 'Утверждена (В работе)', 'Выполнена (Закрыта)', 'Отклонена')) DEFAULT 'Новая заявка',
        requirements TEXT
    );
    """)
    
    # 3.6 candidates (22 fields)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        requisition_id VARCHAR(50) REFERENCES requisitions(id),
        recruiter_id INTEGER REFERENCES users(id),
        created_date DATE,
        department_id INTEGER REFERENCES departments(id),
        title VARCHAR(255),
        cand_name VARCHAR(255),
        phone VARCHAR(32),
        no_answer TEXT CHECK(no_answer IN ('Да', 'Нет')) DEFAULT 'Нет',
        rec_reject_reason VARCHAR(255),
        self_withdraw TEXT CHECK(self_withdraw IN ('Да', 'Нет')) DEFAULT 'Нет',
        test_date DATE,
        test_time TIME,
        test_score INTEGER,
        test_result TEXT CHECK(test_result IN ('Не проходил', 'Сдал', 'Не сдал')) DEFAULT 'Не проходил',
        interview_date DATE,
        interview_result VARCHAR(255),
        offer_date DATE,
        offer_result VARCHAR(255),
        general_reject_reason VARCHAR(255),
        hire_date DATE,
        hired_status TEXT CHECK(hired_status IN ('В процессе', 'Трудоустроен', 'Отказ')) DEFAULT 'В процессе',
        salary_expectation VARCHAR(255),
        comments TEXT,
        resume_path VARCHAR(550)
    );
    """)
    
    # Check if resume_path column exists in candidates
    cursor.execute("PRAGMA table_info(candidates)")
    cols = [r[1] for r in cursor.fetchall()]
    if "resume_path" not in cols:
        cursor.execute("ALTER TABLE candidates ADD COLUMN resume_path VARCHAR(550);")
    
    conn.commit()
    
    # Seed Initial Data if empty
    cursor.execute("SELECT COUNT(*) FROM factories")
    if cursor.fetchone()[0] == 0:
        seed_data(cursor, conn)
        
    conn.close()

# Uploads directory setup
UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "uploads", "resumes")
os.makedirs(UPLOADS_DIR, exist_ok=True)
uploads_parent = os.path.join(os.path.dirname(__file__), "uploads")

def seed_data(cursor, conn):
    # Factories
    cursor.executemany("INSERT INTO factories (name) VALUES (?)", [
        ("SAG",), ("TUFT",), ("Не указано",)
    ])
    
    # Departments
    cursor.executemany("INSERT INTO departments (name) VALUES (?)", [
        ("Отдел цифровизации",),
        ("Ткацкий цех №2",),
        ("Фин.отдел",),
        ("Департамент HR",),
        ("Логистика и склад",)
    ])
    
    # Roles
    roles = [
        ("admin", "Администратор"),
        ("director", "HR-Директор"),
        ("manager", "Руководитель цеха / отделы"),
        ("recruiter", "Рекрутер")
    ]
    cursor.executemany("INSERT INTO roles (code, name) VALUES (?, ?)", roles)
    
    pin1234 = hash_pin("1234")
    
    # Seed Users
    users = [
        ("admin@sag.uz", "Супер", "Админ", "+998901111111", 1, 1, pin1234, "active"),
        ("director@sag.uz", "Шахло", "Рахимова", "+998902222222", 1, 4, pin1234, "active"),
        ("manager1@sag.uz", "Алишер", "Каримов", "+998903333333", 2, 2, pin1234, "active"),
        ("manager2@sag.uz", "Жасур", "Усманов", "+998904444444", 1, 1, pin1234, "active"),
        ("recruiter1@sag.uz", "Анна", "Смирнова", "+998905555555", 1, 4, pin1234, "active"),
        ("recruiter2@sag.uz", "Бобур", "Юлдашев", "+998906666666", 1, 4, pin1234, "active"),
        ("superdir@sag.uz", "Фарход", "Ниязов", "+998907777777", 1, 3, pin1234, "active"),
    ]
    
    for u in users:
        cursor.execute("""
        INSERT INTO users (username_email, first_name, last_name, phone, factory_id, department_id, pin_hash, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, u)
        
    # User Roles mapping
    user_roles = [
        (1, 1), # admin
        (2, 2), # director
        (3, 3), # manager
        (4, 3), # manager
        (5, 4), # recruiter
        (6, 4), # recruiter
        (7, 2), (7, 3) # director + manager
    ]
    cursor.executemany("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)", user_roles)
    
    # Requisitions (numeric IDs from 101 onwards)
    reqs = [
        ("101", "2026-01-10", "2026-02-15", None, 3, 2, "Оператор ткацкого станка", 5, "4 500 000 - 6 000 000 UZS", 5, "Утверждена (В работе)", "Опыт работы от 1 года, готовность к сменному графику"),
        ("102", "2026-01-15", "2026-02-28", "2026-02-25", 4, 1, "Frontend Разработчик React", 2, "12 000 000 - 18 000 000 UZS", 6, "Выполнена (Закрыта)", "Знание React, JavaScript ES6+, HTML5/CSS3"),
        ("103", "2026-02-01", "2026-03-15", None, 3, 2, "Помощник мастера цеха", 3, "5 000 000 UZS", 5, "Утверждена (В работе)", "Техническое образование"),
        ("104", "2026-02-20", "2026-03-30", None, 4, 1, "Data Analyst / SQL Specialist", 1, "10 000 000 UZS", 6, "Утверждена (В работе)", "SQL, Python, PowerBI"),
        ("105", "2026-03-01", "2026-04-10", None, 3, 5, "Водитель погрузчика", 4, "4 000 000 UZS", None, "Новая заявка", "Права категории С, опыт от 2 лет"),
        ("106", "2026-04-05", "2026-05-15", None, 4, 3, "Бухгалтер по материалам", 2, "7 000 000 UZS", 5, "Утверждена (В работе)", "Знание 1С:Бухгалтерия 8.3"),
        ("107", "2026-05-10", "2026-06-20", None, 3, 2, "Упаковщик готовой продукции", 6, "3 500 000 UZS", None, "Новая заявка", "Внимательность, без опыта"),
        ("108", "2026-06-01", "2026-07-01", "2026-06-28", 4, 1, "DevOps Инженер", 1, "20 000 000 UZS", 6, "Выполнена (Закрыта)", "Docker, CI/CD, Linux")
    ]
    cursor.executemany("""
    INSERT INTO requisitions (id, open_date, plan_close_date, actual_close_date, manager_id, department_id, title, count, salary, recruiter_id, status, requirements)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, reqs)
    
    # Candidates (22 fields)
    cands = [
        # Bound candidates for 101
        ("101", 5, "2026-01-12", 2, "Оператор ткацкого станка", "Абдурашидов Акмаль", "+998901234567", "Нет", "", "Нет", "2026-01-14", "10:00", 85, "Сдал", "2026-01-18", "Успешно прошел", "2026-01-20", "Принято", "", "2026-01-25", "Трудоустроен", "5 500 000 UZS", "Отличное впечатление, готов выйти сразу"),
        ("101", 5, "2026-01-14", 2, "Оператор ткацкого станка", "Рустамов Джамшид", "+998902345678", "Нет", "", "Нет", "2026-01-16", "11:30", 90, "Сдал", "2026-01-20", "Рекомендован", "2026-01-22", "Принято", "", "2026-01-28", "Трудоустроен", "5 000 000 UZS", "Опыт в аналогичной сфере 3 года"),
        ("101", 5, "2026-01-18", 2, "Оператор ткацкого станка", "Исламов Темур", "+998903456789", "Нет", "Низкий балл", "Нет", "2026-01-20", "14:00", 45, "Не сдал", None, "", None, "", "Не соответствие квалификации", None, "Отказ", "6 000 000 UZS", "Тест не прошел"),
        ("101", 5, "2026-01-20", 2, "Оператор ткацкого станка", "Хасанов Сардор", "+998904567890", "Нет", "", "Нет", "2026-01-22", "15:00", 78, "Сдал", "2026-01-26", "На рассмотрении", None, "", "", None, "В процессе", "5 200 000 UZS", "Ждем решения руководителя"),
        
        # Bound candidates for 102
        ("102", 6, "2026-01-16", 1, "Frontend Разработчик React", "Абдуллаев Алишер", "+998909993997", "Нет", "", "Нет", "2026-01-19", "12:00", 95, "Сдал", "2026-01-22", "Отличные знания", "2026-01-24", "Принято", "", "2026-02-01", "Трудоустроен", "15 000 000 UZS", "Сильный кандидат"),
        ("102", 6, "2026-01-18", 1, "Frontend Разработчик React", "Ашуров Фарходжон", "+998905025870", "Нет", "", "Нет", "2026-01-21", "16:00", 88, "Сдал", "2026-01-25", "Утвержден", "2026-01-27", "Принято", "", "2026-02-10", "Трудоустроен", "16 000 000 UZS", "Трудоустроен"),
        
        # Bound candidates for 104
        ("104", 6, "2026-02-22", 1, "Data Analyst / SQL Specialist", "Отабек Рустамов", "+998957307787", "Нет", "", "Нет", "2026-02-25", "11:00", 92, "Сдал", "2026-02-28", "На согласовании", None, "", "", None, "В процессе", "10 000 000 UZS", "Техническое интервью прошел отлично"),
        
        # Unbound Candidates (General Talent Pool)
        (None, 5, "2026-02-10", None, "Мастер смены", "Музаффар Каримов", "+998994995522", "Нет", "", "Нет", None, None, None, "Не проходил", None, "", None, "", "", None, "В процессе", "8 000 000 UZS", "Резерв на должность мастера"),
        (None, 6, "2026-02-15", None, "Python Backend Developer", "Улугбек Саидов", "+998999655652", "Нет", "", "Нет", "2026-02-18", "10:30", 82, "Сдал", None, "", None, "", "", None, "В процессе", "14 000 000 UZS", "Общий резерв IT"),
        (None, 5, "2026-02-28", None, "Инженер-механик", "Сирожиддин Валиев", "+998907654321", "Да", "Не отвечает", "Нет", None, None, None, "Не проходил", None, "", None, "", "Не отвечает на звонки", None, "Отказ", "6 000 000 UZS", "3 недозвона")
    ]
    
    for c in cands:
        cursor.execute("""
        INSERT INTO candidates (
            requisition_id, recruiter_id, created_date, department_id, title, cand_name, phone,
            no_answer, rec_reject_reason, self_withdraw, test_date, test_time, test_score, test_result,
            interview_date, interview_result, offer_date, offer_result, general_reject_reason,
            hire_date, hired_status, salary_expectation, comments
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, c)
        
    conn.commit()

# Create FastAPI App
app = FastAPI(
    title="SAG for people - HR CRM Portal",
    description="Management Portal and CRM System for SAG HR Department",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=uploads_parent), name="uploads")

@app.middleware("http")
async def add_no_cache_header(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Startup hook
@app.on_event("startup")
def startup():
    init_db()
    # Migrate any existing resume filenames to use Candidate ID naming format: resume_cand_{id}.ext
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, resume_path FROM candidates WHERE resume_path IS NOT NULL")
    rows = cursor.fetchall()
    for row in rows:
        cid = row["id"]
        old_path = row["resume_path"]
        if old_path and old_path.startswith("/uploads/resumes/"):
            old_fname = os.path.basename(old_path)
            ext = os.path.splitext(old_fname)[1].lower()
            new_fname = f"resume_cand_{cid}{ext}"
            if old_fname != new_fname:
                old_disk = os.path.join(UPLOADS_DIR, old_fname)
                new_disk = os.path.join(UPLOADS_DIR, new_fname)
                if os.path.exists(old_disk):
                    if os.path.exists(new_disk):
                        try:
                            os.remove(new_disk)
                        except Exception:
                            pass
                    try:
                        os.rename(old_disk, new_disk)
                    except Exception:
                        pass
                new_rel = f"/uploads/resumes/{new_fname}"
                cursor.execute("UPDATE candidates SET resume_path = ? WHERE id = ?", (new_rel, cid))
    conn.commit()
    conn.close()

# Models
class LoginRequest(BaseModel):
    username_email: str
    pin: str

class CandidateBindRequest(BaseModel):
    requisition_id: Optional[str] = None

class RequisitionCreate(BaseModel):
    open_date: str
    plan_close_date: str
    department_id: int
    title: str
    count: int
    salary: Optional[str] = ""
    requirements: Optional[str] = ""

class RequisitionUpdate(BaseModel):
    title: Optional[str] = None
    count: Optional[int] = None
    salary: Optional[str] = None
    department_id: Optional[int] = None
    plan_close_date: Optional[str] = None
    recruiter_id: Optional[int] = None
    status: Optional[str] = None
    requirements: Optional[str] = None
    actual_close_date: Optional[str] = None

class CandidateCreate(BaseModel):
    requisition_id: Optional[str] = None
    recruiter_id: int
    cand_name: str
    phone: str
    title: Optional[str] = ""
    department_id: Optional[int] = None
    salary_expectation: Optional[str] = ""
    comments: Optional[str] = ""
    resume_path: Optional[str] = None

class CandidateUpdate(BaseModel):
    requisition_id: Optional[str] = None
    recruiter_id: Optional[int] = None
    department_id: Optional[int] = None
    title: Optional[str] = None
    cand_name: Optional[str] = None
    phone: Optional[str] = None
    no_answer: Optional[str] = "Нет"
    rec_reject_reason: Optional[str] = ""
    self_withdraw: Optional[str] = "Нет"
    test_date: Optional[str] = None
    test_time: Optional[str] = None
    test_score: Optional[int] = None
    test_result: Optional[str] = "Не проходил"
    interview_date: Optional[str] = None
    interview_result: Optional[str] = ""
    offer_date: Optional[str] = None
    offer_result: Optional[str] = ""
    general_reject_reason: Optional[str] = ""
    hire_date: Optional[str] = None
    hired_status: Optional[str] = "В процессе"
    salary_expectation: Optional[str] = ""
    comments: Optional[str] = ""
    resume_path: Optional[str] = None

class UserCreate(BaseModel):
    username_email: str
    first_name: str
    last_name: str
    phone: str
    factory_id: Optional[int] = 1
    department_id: Optional[int] = 1
    pin: str
    roles: List[str]

class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    factory_id: Optional[int] = None
    department_id: Optional[int] = None
    status: Optional[str] = None
    pin: Optional[str] = None
    roles: Optional[List[str]] = None

# Dependency to get current user from JWT token
def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization:
        raise HTTPException(status_code=401, detail="Отсутствует токен авторизации")
    
    token = authorization.replace("Bearer ", "").strip()
    payload = verify_jwt_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Недействительный или истекший токен")
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT u.*, f.name as factory_name, d.name as department_name
    FROM users u
    LEFT JOIN factories f ON u.factory_id = f.id
    LEFT JOIN departments d ON u.department_id = d.id
    WHERE u.id = ? AND u.status = 'active'
    """, (payload["user_id"],))
    user_row = cursor.fetchone()
    
    if not user_row:
        conn.close()
        raise HTTPException(status_code=401, detail="Пользователь не найден или заблокирован")
        
    cursor.execute("""
    SELECT r.code, r.name
    FROM roles r
    JOIN user_roles ur ON r.id = ur.role_id
    WHERE ur.user_id = ?
    """, (payload["user_id"],))
    role_rows = cursor.fetchall()
    conn.close()
    
    user_dict = dict(user_row)
    del user_dict["pin_hash"]
    user_dict["roles"] = [r["code"] for r in role_rows]
    user_dict["role_names"] = [r["name"] for r in role_rows]
    
    return user_dict

# API Routes

@app.post("/api/auth/login")
def login(req: LoginRequest):
    conn = get_db()
    cursor = conn.cursor()
    
    pin_h = hash_pin(req.pin)
    cursor.execute("""
    SELECT u.*, f.name as factory_name, d.name as department_name
    FROM users u
    LEFT JOIN factories f ON u.factory_id = f.id
    LEFT JOIN departments d ON u.department_id = d.id
    WHERE (u.username_email = ? OR u.phone = ?) AND u.pin_hash = ? AND u.status = 'active'
    """, (req.username_email, req.username_email, pin_h))
    
    user_row = cursor.fetchone()
    if not user_row:
        conn.close()
        raise HTTPException(status_code=400, detail="Неверный логин/Email или PIN-код")
        
    user_dict = dict(user_row)
    del user_dict["pin_hash"]
    
    cursor.execute("""
    SELECT r.code, r.name
    FROM roles r
    JOIN user_roles ur ON r.id = ur.role_id
    WHERE ur.user_id = ?
    """, (user_dict["id"],))
    role_rows = cursor.fetchall()
    conn.close()
    
    roles_list = [r["code"] for r in role_rows]
    user_dict["roles"] = roles_list
    user_dict["role_names"] = [r["name"] for r in role_rows]
    
    # Token valid for 24h
    payload = {
        "user_id": user_dict["id"],
        "email": user_dict["username_email"],
        "roles": roles_list,
        "exp": int(time.time()) + 86400
    }
    
    token = create_jwt_token(payload)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user_dict
    }

@app.get("/api/auth/me")
def get_me(current_user: dict = Depends(get_current_user)):
    return current_user

# Reference APIs
@app.get("/api/factories")
def get_factories():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM factories ORDER BY id")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/departments")
def get_departments():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM departments ORDER BY id")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/roles")
def get_roles():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM roles ORDER BY id")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/recruiters")
def get_recruiters(current_user: dict = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT DISTINCT u.id, u.first_name, u.last_name, u.username_email, u.phone
    FROM users u
    JOIN user_roles ur ON u.id = ur.user_id
    JOIN roles r ON ur.role_id = r.id
    WHERE r.code = 'recruiter' AND u.status = 'active'
    ORDER BY u.first_name ASC
    """)
    rows = cursor.fetchall()
    
    # Fallback to all active users if no recruiters found
    if not rows:
        cursor.execute("SELECT id, first_name, last_name, username_email, phone FROM users WHERE status = 'active' ORDER BY first_name ASC")
        rows = cursor.fetchall()
        
    conn.close()
    return [dict(r) for r in rows]

# Requisitions API
@app.get("/api/requisitions")
def get_requisitions(
    department_id: Optional[int] = None,
    status_filter: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    conn = get_db()
    cursor = conn.cursor()
    
    query = """
    SELECT r.*, 
           d.name as department_name,
           m.first_name || ' ' || m.last_name as manager_name,
           rec.first_name || ' ' || rec.last_name as recruiter_name,
           (SELECT COUNT(*) FROM candidates c WHERE c.requisition_id = r.id AND c.hired_status = 'Трудоустроен') as hired_count,
           (SELECT COUNT(*) FROM candidates c WHERE c.requisition_id = r.id) as total_candidates_count
    FROM requisitions r
    LEFT JOIN departments d ON r.department_id = d.id
    LEFT JOIN users m ON r.manager_id = m.id
    LEFT JOIN users rec ON r.recruiter_id = rec.id
    WHERE 1=1
    """
    params = []
    
    # RBAC filter: managers only see their department requisitions unless director/admin
    is_director_or_admin = any(role in ['admin', 'director'] for role in current_user['roles'])
    if not is_director_or_admin:
        if 'manager' in current_user['roles']:
            query += " AND r.manager_id = ?"
            params.append(current_user['id'])
        elif 'recruiter' in current_user['roles']:
            query += " AND (r.recruiter_id = ? OR r.recruiter_id IS NULL)"
            params.append(current_user['id'])
            
    if department_id:
        query += " AND r.department_id = ?"
        params.append(department_id)
        
    if status_filter:
        query += " AND r.status = ?"
        params.append(status_filter)
        
    query += " ORDER BY r.open_date DESC"
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    res = []
    for r in rows:
        item = dict(r)
        hired = item['hired_count'] or 0
        target = item['count'] or 1
        item['progress_pct'] = min(100, int((hired / target) * 100))
        res.append(item)
        
    return res

@app.post("/api/requisitions")
def create_requisition(req: RequisitionCreate, current_user: dict = Depends(get_current_user)):
    # Check permissions
    if not any(role in ['admin', 'director', 'manager'] for role in current_user['roles']):
        raise HTTPException(status_code=403, detail="Недостаточно прав для создания заявки")
        
    conn = get_db()
    cursor = conn.cursor()
    
    # Generate Numeric Requisition ID (101 onwards)
    cursor.execute("SELECT MAX(CAST(id AS INTEGER)) FROM requisitions")
    row = cursor.fetchone()
    max_id = row[0] if row and row[0] is not None else 100
    req_id = str(max_id + 1)
    
    cursor.execute("""
    INSERT INTO requisitions (id, open_date, plan_close_date, manager_id, department_id, title, count, salary, status, requirements)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Новая заявка', ?)
    """, (req_id, req.open_date, req.plan_close_date, current_user['id'], req.department_id, req.title, req.count, req.salary, req.requirements))
    
    conn.commit()
    conn.close()
    
    return {"message": "Заявка успешно создана", "id": req_id}

@app.put("/api/requisitions/{req_id}")
def update_requisition(req_id: str, data: RequisitionUpdate, current_user: dict = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM requisitions WHERE id = ?", (req_id,))
    req_row = cursor.fetchone()
    if not req_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Заявка не найдена")
        
    req_dict = dict(req_row)
    
    # Permission & Status restriction for editing requisition content
    is_content_edit = any(val is not None for val in [data.title, data.count, data.salary, data.department_id, data.plan_close_date, data.requirements])
    if is_content_edit:
        is_admin = 'admin' in current_user['roles']
        is_director = 'director' in current_user['roles']
        is_manager_owner = current_user['id'] == req_dict['manager_id']
        
        if not (is_admin or is_director or is_manager_owner):
            conn.close()
            raise HTTPException(status_code=403, detail="Редактирование заявки доступно только заявителю или Администратору")
            
        if req_dict['status'] != "Новая заявка" and not is_admin:
            conn.close()
            raise HTTPException(status_code=400, detail="Изменять заявку можно только в статусе 'Новая заявка'")
            
    updates = []
    params = []
    
    if data.title is not None:
        updates.append("title = ?")
        params.append(data.title)
    if data.count is not None:
        updates.append("count = ?")
        params.append(data.count)
    if data.salary is not None:
        updates.append("salary = ?")
        params.append(data.salary)
    if data.department_id is not None:
        updates.append("department_id = ?")
        params.append(data.department_id)
    if data.plan_close_date is not None:
        updates.append("plan_close_date = ?")
        params.append(data.plan_close_date)
    if data.recruiter_id is not None:
        updates.append("recruiter_id = ?")
        params.append(data.recruiter_id)
    if data.status is not None:
        updates.append("status = ?")
        params.append(data.status)
        if data.status == "Выполнена (Закрыта)" and not data.actual_close_date:
            updates.append("actual_close_date = ?")
            params.append(date.today().isoformat())
    if data.requirements is not None:
        updates.append("requirements = ?")
        params.append(data.requirements)
        
    if updates:
        params.append(req_id)
        cursor.execute(f"UPDATE requisitions SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
        
    conn.close()
    return {"message": "Заявка обновлена"}

# Candidates API (22 fields)
@app.get("/api/candidates")
def get_candidates(
    search: Optional[str] = None,
    requisition_id: Optional[str] = None,
    recruiter_id: Optional[int] = None,
    department_id: Optional[int] = None,
    hired_status: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    conn = get_db()
    cursor = conn.cursor()
    
    query = """
    SELECT c.*,
           d.name as department_name,
           rec.first_name || ' ' || rec.last_name as recruiter_name,
           r.title as requisition_title
    FROM candidates c
    LEFT JOIN departments d ON c.department_id = d.id
    LEFT JOIN users rec ON c.recruiter_id = rec.id
    LEFT JOIN requisitions r ON c.requisition_id = r.id
    WHERE 1=1
    """
    params = []
    
    # Recruiter only sees candidates assigned to them or unassigned unless Director/Admin
    is_director_or_admin = any(role in ['admin', 'director'] for role in current_user['roles'])
    if not is_director_or_admin and 'recruiter' in current_user['roles']:
        query += " AND (c.recruiter_id = ? OR c.recruiter_id IS NULL)"
        params.append(current_user['id'])
        
    if requisition_id:
        if requisition_id == "NONE":
            query += " AND c.requisition_id IS NULL"
        else:
            query += " AND c.requisition_id = ?"
            params.append(requisition_id)
            
    if recruiter_id:
        query += " AND c.recruiter_id = ?"
        params.append(recruiter_id)
        
    if department_id:
        query += " AND c.department_id = ?"
        params.append(department_id)
        
    if hired_status:
        query += " AND c.hired_status = ?"
        params.append(hired_status)
        
    if search:
        query += " AND (c.cand_name LIKE ? OR c.phone LIKE ? OR c.title LIKE ?)"
        s = f"%{search}%"
        params.extend([s, s, s])
        
    query += " ORDER BY c.id DESC"
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(r) for r in rows]

@app.post("/api/candidates")
def create_candidate(data: CandidateCreate, current_user: dict = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    
    req_dept_id = data.department_id
    req_title = data.title
    
    # Auto-fill department and title if bound to requisition
    if data.requisition_id:
        cursor.execute("SELECT department_id, title FROM requisitions WHERE id = ?", (data.requisition_id,))
        req_row = cursor.fetchone()
        if req_row:
            req_dept_id = req_row['department_id']
            req_title = req_row['title']
            
    created_date = date.today().isoformat()
    
    cursor.execute("""
    INSERT INTO candidates (
        requisition_id, recruiter_id, created_date, department_id, title, cand_name, phone,
        salary_expectation, comments, hired_status, resume_path
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'В процессе', ?)
    """, (data.requisition_id, data.recruiter_id or current_user['id'], created_date, req_dept_id, req_title, data.cand_name, data.phone, data.salary_expectation, data.comments, data.resume_path))
    
    cand_id = cursor.lastrowid

    # If temporary resume was attached during creation, rename to resume_cand_{cand_id}.ext
    if data.resume_path and "/uploads/resumes/resume_temp_" in data.resume_path:
        old_fname = os.path.basename(data.resume_path)
        ext = os.path.splitext(old_fname)[1].lower()
        new_fname = f"resume_cand_{cand_id}{ext}"
        old_disk = os.path.join(UPLOADS_DIR, old_fname)
        new_disk = os.path.join(UPLOADS_DIR, new_fname)
        if os.path.exists(old_disk):
            if os.path.exists(new_disk):
                try:
                    os.remove(new_disk)
                except Exception:
                    pass
            try:
                os.rename(old_disk, new_disk)
            except Exception:
                pass
            new_rel = f"/uploads/resumes/{new_fname}"
            cursor.execute("UPDATE candidates SET resume_path = ? WHERE id = ?", (new_rel, cand_id))

    conn.commit()
    conn.close()
    
    return {"message": "Соискатель добавлен в базу", "id": cand_id}

@app.post("/api/candidates/upload-resume")
async def upload_candidate_resume(
    file: UploadFile = File(...),
    cand_id: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_user)
):
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    filename = file.filename or "resume.pdf"
    
    # Enforce PDF and Word documents strictly
    ext = os.path.splitext(filename)[1].lower()
    if ext not in [".pdf", ".doc", ".docx"]:
        raise HTTPException(
            status_code=400,
            detail="Разрешены только документы в формате PDF (.pdf) и Word (.doc, .docx)"
        )
        
    if cand_id:
        unique_filename = f"resume_cand_{cand_id}{ext}"
    else:
        timestamp = int(time.time())
        unique_filename = f"resume_temp_{timestamp}{ext}"
        
    file_path = os.path.join(UPLOADS_DIR, unique_filename)
    
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)
        
    rel_path = f"/uploads/resumes/{unique_filename}"
    
    if cand_id:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE candidates SET resume_path = ? WHERE id = ?", (rel_path, cand_id))
        conn.commit()
        conn.close()
        
    return {
        "message": "Резюме успешно загружено на сервер",
        "resume_path": rel_path,
        "filename": unique_filename
    }

@app.delete("/api/candidates/{cand_id}/resume")
def delete_candidate_resume(cand_id: int, current_user: dict = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT resume_path FROM candidates WHERE id = ?", (cand_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Соискатель не найден")
        
    resume_path = row["resume_path"]
    if resume_path and resume_path.startswith("/uploads/resumes/"):
        fname = os.path.basename(resume_path)
        disk_file = os.path.join(UPLOADS_DIR, fname)
        if os.path.exists(disk_file):
            try:
                os.remove(disk_file)
            except Exception:
                pass
                
    cursor.execute("UPDATE candidates SET resume_path = NULL WHERE id = ?", (cand_id,))
    conn.commit()
    conn.close()
    return {"message": "Резюме удалено со страницы соискателя"}

@app.post("/api/candidates/{cand_id}/bind")
def bind_candidate(cand_id: int, req_bind: CandidateBindRequest, current_user: dict = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM candidates WHERE id = ?", (cand_id,))
    cand = cursor.fetchone()
    if not cand:
        conn.close()
        raise HTTPException(status_code=404, detail="Соискатель не найден")
        
    target_req_id = req_bind.requisition_id
    new_dept_id = cand['department_id']
    new_title = cand['title']
    
    if target_req_id:
        cursor.execute("SELECT department_id, title FROM requisitions WHERE id = ?", (target_req_id,))
        r_row = cursor.fetchone()
        if not r_row:
            conn.close()
            raise HTTPException(status_code=400, detail="Указанная заявка не найдена")
        new_dept_id = r_row['department_id']
        new_title = r_row['title']
    else:
        target_req_id = None
        
    cursor.execute("""
    UPDATE candidates
    SET requisition_id = ?, department_id = ?, title = ?
    WHERE id = ?
    """, (target_req_id, new_dept_id, new_title, cand_id))
    
    conn.commit()
    conn.close()
    
    return {
        "message": f"Соискатель {'привязан к ' + target_req_id if target_req_id else 'отвязан от заявки'}",
        "requisition_id": target_req_id,
        "department_id": new_dept_id,
        "title": new_title
    }

@app.put("/api/candidates/{cand_id}")
def update_candidate(cand_id: int, data: CandidateUpdate, current_user: dict = Depends(get_current_user)):
    can_edit = any(r in ['admin', 'director', 'recruiter'] for r in current_user['roles'])
    if not can_edit:
        raise HTTPException(status_code=403, detail="У руководителя отдела нет прав на изменение карточки кандидата")

    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM candidates WHERE id = ?", (cand_id,))
    cand = cursor.fetchone()
    if not cand:
        conn.close()
        raise HTTPException(status_code=404, detail="Соискатель не найден")
        
    fields = data.dict(exclude_unset=True)
    
    # If requisition_id changed, auto-update department & title
    if "requisition_id" in fields and fields["requisition_id"] != cand["requisition_id"]:
        new_req_id = fields["requisition_id"]
        if new_req_id:
            cursor.execute("SELECT department_id, title FROM requisitions WHERE id = ?", (new_req_id,))
            r_row = cursor.fetchone()
            if r_row:
                fields["department_id"] = r_row["department_id"]
                fields["title"] = r_row["title"]

    # If temporary resume was passed, rename to resume_cand_{cand_id}.ext
    if "resume_path" in fields and fields["resume_path"] and "/uploads/resumes/resume_temp_" in fields["resume_path"]:
        old_fname = os.path.basename(fields["resume_path"])
        ext = os.path.splitext(old_fname)[1].lower()
        new_fname = f"resume_cand_{cand_id}{ext}"
        old_disk = os.path.join(UPLOADS_DIR, old_fname)
        new_disk = os.path.join(UPLOADS_DIR, new_fname)
        if os.path.exists(old_disk):
            if os.path.exists(new_disk):
                try:
                    os.remove(new_disk)
                except Exception:
                    pass
            try:
                os.rename(old_disk, new_disk)
            except Exception:
                pass
            fields["resume_path"] = f"/uploads/resumes/{new_fname}"

    updates = []
    params = []
    for k, v in fields.items():
        updates.append(f"{k} = ?")
        params.append(v)
        
    if updates:
        params.append(cand_id)
        cursor.execute(f"UPDATE candidates SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
        
    conn.close()
    return {"message": "Данные соискателя обновлены"}

@app.delete("/api/candidates/{cand_id}")
def delete_candidate(cand_id: int, current_user: dict = Depends(get_current_user)):
    if not any(role in ['admin', 'director'] for role in current_user['roles']):
        raise HTTPException(status_code=403, detail="Только HR-Директор или Админ может удалять соискателей")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM candidates WHERE id = ?", (cand_id,))
    conn.commit()
    conn.close()
    return {"message": "Запись соискателя удалена"}

# CSV Export API with UTF-8 BOM (\uFEFF)
@app.get("/api/candidates/export")
def export_candidates_csv(current_user: dict = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT c.*, d.name as department_name, rec.first_name || ' ' || rec.last_name as recruiter_name
    FROM candidates c
    LEFT JOIN departments d ON c.department_id = d.id
    LEFT JOIN users rec ON c.recruiter_id = rec.id
    ORDER BY c.id ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    
    headers = [
        "ID", "Код Заявки", "Рекрутер", "Дата создания", "Отдел/Цех", "Должность",
        "ФИО соискателя", "Телефон", "Недозвон", "Причина отказа рекр.", "Самоотказ",
        "Дата теста", "Время теста", "Балл теста", "Результат теста",
        "Дата интервью", "Результат интервью", "Дата оффера", "Результат оффера",
        "Общая причина отказа", "Дата найма", "Статус трудоустройства", "ЗП ожидания", "Комментарии"
    ]
    
    lines = [",".join(f'"{h}"' for h in headers)]
    for r in rows:
        row_vals = [
            str(r["id"]),
            r["requisition_id"] or "Не привязан",
            r["recruiter_name"] or "",
            r["created_date"] or "",
            r["department_name"] or "",
            r["title"] or "",
            r["cand_name"] or "",
            r["phone"] or "",
            r["no_answer"] or "Нет",
            r["rec_reject_reason"] or "",
            r["self_withdraw"] or "Нет",
            r["test_date"] or "",
            r["test_time"] or "",
            str(r["test_score"]) if r["test_score"] is not None else "",
            r["test_result"] or "Не проходил",
            r["interview_date"] or "",
            r["interview_result"] or "",
            r["offer_date"] or "",
            r["offer_result"] or "",
            r["general_reject_reason"] or "",
            r["hire_date"] or "",
            r["hired_status"] or "В процессе",
            r["salary_expectation"] or "",
            (r["comments"] or "").replace('"', '""')
        ]
        lines.append(",".join(f'"{v}"' for v in row_vals))
        
    csv_content = "\uFEFF" + "\n".join(lines)
    
    return Response(
        content=csv_content.encode('utf-8-sig'),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=sag_candidates_export_{date.today().isoformat()}.csv"}
    )

# Executive Analytics API
@app.get("/api/analytics/executive")
def get_executive_analytics(current_user: dict = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    
    # Requisitions summary
    cursor.execute("SELECT COUNT(*) FROM requisitions")
    total_reqs = cursor.fetchone()[0]
    
    cursor.execute("SELECT SUM(count) FROM requisitions")
    total_needed = cursor.fetchone()[0] or 0
    
    cursor.execute("SELECT COUNT(*) FROM candidates WHERE hired_status = 'Трудоустроен'")
    total_hired = cursor.fetchone()[0] or 0
    
    fulfillment_pct = int((total_hired / total_needed * 100)) if total_needed > 0 else 0
    
    cursor.execute("SELECT COUNT(*) FROM candidates WHERE hired_status = 'В процессе'")
    active_funnel = cursor.fetchone()[0]
    
    # Department progress
    cursor.execute("""
    SELECT d.id, d.name as department_name,
           SUM(r.count) as total_plan,
           (SELECT COUNT(*) FROM candidates c WHERE c.department_id = d.id AND c.hired_status = 'Трудоустроен') as hired
    FROM departments d
    LEFT JOIN requisitions r ON r.department_id = d.id
    GROUP BY d.id
    """)
    dept_rows = cursor.fetchall()
    
    dept_progress = []
    for dr in dept_rows:
        plan = dr["total_plan"] or 0
        hired = dr["hired"] or 0
        pct = int((hired / plan * 100)) if plan > 0 else 0
        dept_progress.append({
            "department_id": dr["id"],
            "department_name": dr["department_name"],
            "plan": plan,
            "hired": hired,
            "percentage": pct
        })
        
    # SLA Warnings table
    cursor.execute("""
    SELECT r.id, r.title, d.name as department_name, r.open_date, r.plan_close_date, r.count,
           (SELECT COUNT(*) FROM candidates c WHERE c.requisition_id = r.id AND c.hired_status = 'Трудоустроен') as hired,
           r.status, rec.first_name || ' ' || rec.last_name as recruiter_name
    FROM requisitions r
    LEFT JOIN departments d ON r.department_id = d.id
    LEFT JOIN users rec ON r.recruiter_id = rec.id
    ORDER BY r.plan_close_date ASC
    """)
    sla_rows = cursor.fetchall()
    
    sla_indicators = []
    today = date.today()
    for sr in sla_rows:
        p_date = datetime.strptime(sr["plan_close_date"], "%Y-%m-%d").date()
        days_left = (p_date - today).days
        is_overdue = days_left < 0 and sr["status"] != "Выполнена (Закрыта)"
        
        sla_indicators.append({
            "requisition_id": sr["id"],
            "title": sr["title"],
            "department": sr["department_name"],
            "open_date": sr["open_date"],
            "plan_close_date": sr["plan_close_date"],
            "plan_count": sr["count"],
            "hired_count": sr["hired"],
            "recruiter_name": sr["recruiter_name"] or "Не назначен",
            "days_left": days_left,
            "is_overdue": is_overdue,
            "status": "Просрочена" if is_overdue else ("В норме" if days_left > 5 else "Внимания требует")
        })
        
    conn.close()
    
    return {
        "kpi": {
            "fulfillment_percentage": fulfillment_pct,
            "average_sla_days": 18,
            "active_funnel_count": active_funnel,
            "on_time_percentage": 92
        },
        "department_progress": dept_progress,
        "sla_indicators": sla_indicators
    }

# Recruiter Dashboard API
@app.get("/api/analytics/recruiters")
def get_recruiter_analytics(current_user: dict = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT u.id, u.first_name || ' ' || u.last_name as name,
           COUNT(c.id) as total_candidates,
           SUM(CASE WHEN c.hired_status = 'Трудоустроен' THEN 1 ELSE 0 END) as hired_count,
           SUM(CASE WHEN c.no_answer = 'Да' THEN 1 ELSE 0 END) as no_answer_count,
           AVG(c.test_score) as avg_score
    FROM users u
    JOIN user_roles ur ON u.id = ur.user_id
    JOIN roles r ON ur.role_id = r.id
    LEFT JOIN candidates c ON c.recruiter_id = u.id
    WHERE r.code = 'recruiter'
    GROUP BY u.id
    """)
    rows = cursor.fetchall()
    conn.close()
    
    res = []
    for r in rows:
        tot = r["total_candidates"] or 0
        hired = r["hired_count"] or 0
        conv = int((hired / tot * 100)) if tot > 0 else 0
        avg_score = round(r["avg_score"] or 0, 1)
        res.append({
            "recruiter_id": r["id"],
            "name": r["name"],
            "total_candidates": tot,
            "hired_count": hired,
            "no_answer_count": r["no_answer_count"] or 0,
            "conversion_pct": conv,
            "avg_test_score": avg_score
        })
        
    return res

# Quarterly Analytics API
@app.get("/api/analytics/quarterly")
def get_quarterly_analytics(current_user: dict = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM requisitions ORDER BY open_date ASC")
    rows = cursor.fetchall()
    
    quarters = {"Q1": [], "Q2": [], "Q3": [], "Q4": []}
    for r in rows:
        d = datetime.strptime(r["open_date"], "%Y-%m-%d")
        q_num = (d.month - 1) // 3 + 1
        q_key = f"Q{q_num}"
        quarters[q_key].append(dict(r))
        
    conn.close()
    
    summary = {}
    for q_key, reqs in quarters.items():
        cnt = len(reqs)
        total_needed = sum(item["count"] for item in reqs)
        summary[q_key] = {
            "total_requisitions": cnt,
            "total_needed": total_needed,
            "requisitions": reqs
        }
        
    return summary

# Admin Users API
@app.get("/api/admin/users")
def admin_get_users(current_user: dict = Depends(get_current_user)):
    if 'admin' not in current_user['roles']:
        raise HTTPException(status_code=403, detail="Только Администратор имеет доступ")
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT u.*, f.name as factory_name, d.name as department_name
    FROM users u
    LEFT JOIN factories f ON u.factory_id = f.id
    LEFT JOIN departments d ON u.department_id = d.id
    ORDER BY u.id ASC
    """)
    rows = cursor.fetchall()
    
    res = []
    for r in rows:
        u_dict = dict(r)
        del u_dict["pin_hash"]
        cursor.execute("""
        SELECT r.code, r.name
        FROM roles r
        JOIN user_roles ur ON r.id = ur.role_id
        WHERE ur.user_id = ?
        """, (u_dict["id"],))
        role_rows = cursor.fetchall()
        u_dict["roles"] = [ro["code"] for ro in role_rows]
        u_dict["role_names"] = [ro["name"] for ro in role_rows]
        res.append(u_dict)
        
    conn.close()
    return res

@app.post("/api/admin/users")
def admin_create_user(data: UserCreate, current_user: dict = Depends(get_current_user)):
    if 'admin' not in current_user['roles']:
        raise HTTPException(status_code=403, detail="Только Администратор имеет доступ")
        
    conn = get_db()
    cursor = conn.cursor()
    
    pin_h = hash_pin(data.pin)
    try:
        cursor.execute("""
        INSERT INTO users (username_email, first_name, last_name, phone, factory_id, department_id, pin_hash, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
        """, (data.username_email, data.first_name, data.last_name, data.phone, data.factory_id, data.department_id, pin_h))
        new_uid = cursor.lastrowid
        
        for r_code in data.roles:
            cursor.execute("SELECT id FROM roles WHERE code = ?", (r_code,))
            r_row = cursor.fetchone()
            if r_row:
                cursor.execute("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)", (new_uid, r_row['id']))
                
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Пользователь с таким Email или телефоном уже существует")
        
    conn.close()
    return {"message": "Пользователь создан", "id": new_uid}

@app.put("/api/admin/users/{user_id}")
def admin_update_user(user_id: int, data: UserUpdate, current_user: dict = Depends(get_current_user)):
    if 'admin' not in current_user['roles']:
        raise HTTPException(status_code=403, detail="Только Администратор имеет доступ")
        
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Пользователь не найден")
        
    updates = []
    params = []
    
    if data.first_name:
        updates.append("first_name = ?")
        params.append(data.first_name)
    if data.last_name:
        updates.append("last_name = ?")
        params.append(data.last_name)
    if data.phone:
        updates.append("phone = ?")
        params.append(data.phone)
    if data.factory_id:
        updates.append("factory_id = ?")
        params.append(data.factory_id)
    if data.department_id:
        updates.append("department_id = ?")
        params.append(data.department_id)
    if data.status:
        updates.append("status = ?")
        params.append(data.status)
    if data.pin:
        updates.append("pin_hash = ?")
        params.append(hash_pin(data.pin))
        
    if updates:
        params.append(user_id)
        cursor.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
        
    if data.roles is not None:
        cursor.execute("DELETE FROM user_roles WHERE user_id = ?", (user_id,))
        for r_code in data.roles:
            cursor.execute("SELECT id FROM roles WHERE code = ?", (r_code,))
            r_row = cursor.fetchone()
            if r_row:
                cursor.execute("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)", (user_id, r_row['id']))
                
    conn.commit()
    conn.close()
    return {"message": "Данные пользователя обновлены"}

# Static files hosting (supports both static/ subfolder and root repository files)
static_dir = os.path.join(os.path.dirname(__file__), "static")
root_dir = os.path.dirname(__file__)

@app.get("/static/{file_name}")
def serve_static_subfolder(file_name: str):
    p1 = os.path.join(static_dir, file_name)
    if os.path.isfile(p1):
        return FileResponse(p1)
    p2 = os.path.join(root_dir, file_name)
    if os.path.isfile(p2):
        return FileResponse(p2)
    raise HTTPException(status_code=404, detail="File not found")

@app.get("/style.css")
def serve_root_css():
    p1 = os.path.join(static_dir, "style.css")
    if os.path.isfile(p1):
        return FileResponse(p1)
    p2 = os.path.join(root_dir, "style.css")
    if os.path.isfile(p2):
        return FileResponse(p2)
    raise HTTPException(status_code=404, detail="File not found")

@app.get("/app.js")
def serve_root_js():
    p1 = os.path.join(static_dir, "app.js")
    if os.path.isfile(p1):
        return FileResponse(p1)
    p2 = os.path.join(root_dir, "app.js")
    if os.path.isfile(p2):
        return FileResponse(p2)
    raise HTTPException(status_code=404, detail="File not found")

@app.get("/")
def serve_index():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.isfile(index_file):
        return FileResponse(index_file)
    root_index = os.path.join(root_dir, "index.html")
    if os.path.isfile(root_index):
        return FileResponse(root_index)
    return HTMLResponse("<h1>SAG for people HR CRM Server Running</h1>")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
