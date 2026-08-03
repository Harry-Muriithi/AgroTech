# ═══════════════════════════════════════════════════════════
#  AGROTECH BACKEND  —  main.py
#  This is the brain of the app.
#  Run it with:  uvicorn main:app --reload --port 8000
# ═══════════════════════════════════════════════════════════

# ── IMPORTS ──────────────────────────────────────────────
# These are Python libraries we need. Like tools in a toolbox.
from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
import logging, time
from collections import defaultdict
from fastapi.middleware.cors import CORSMiddleware   # allows frontend to talk to backend
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from pydantic import BaseModel
from typing import Optional, List
import tensorflow as tf
import numpy as np
from PIL import Image
import pickle
import io, os, uuid, hashlib, secrets
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.units import inch


# ═══════════════════════════════════════════════════════════
#  DATABASE SETUP
#  SQLite = a simple database saved as a single file.
#  No need to install MySQL or PostgreSQL.
#  The file "agrotech.db" is created automatically.
# ═══════════════════════════════════════════════════════════

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))  # folder where main.py lives

# Where the database lives.
# On Render (no persistent disk on the free tier), we point to a hosted
# Postgres database via the DATABASE_URL env var (e.g. from Supabase or Neon)
# so farmer accounts SURVIVE restarts and redeploys.
# Locally, or if DATABASE_URL isn't set, we fall back to a local SQLite file
# exactly as before (handy for quick local testing).
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    # Some providers give a URL starting with "postgres://" — SQLAlchemy needs
    # the "postgresql://" form, so normalize it if needed.
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
else:
    DB_DIR = os.getenv("DB_DIR", BASE_DIR)
    os.makedirs(DB_DIR, exist_ok=True)
    DATABASE_URL = f"sqlite:///{os.path.join(DB_DIR, 'agrotech.db')}"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base         = declarative_base()


# ── DATABASE TABLES ───────────────────────────────────────
# Each class below = one table in the database.
# Think of each class as a spreadsheet sheet.

class Farmer(Base):
    """
    The farmers table.
    One row = one registered farmer.
    """
    __tablename__ = "farmers"
    id            = Column(Integer, primary_key=True, index=True)
    name          = Column(String, nullable=False)
    phone         = Column(String, unique=True, index=True, nullable=False)
    email         = Column(String, unique=True, index=True, nullable=True)  # optional
    password_hash = Column(String, nullable=False)    # NEVER store plain passwords!
    county        = Column(String, default="Kenya")
    farm_size     = Column(Float,  default=0)         # in acres
    farm_scale    = Column(String, default="small")   # 'small' or 'large'
    registered_at = Column(DateTime, default=datetime.utcnow)
    # NOTE: the old single 'token' column has been replaced by the
    # auth_tokens table below, which supports multiple simultaneous
    # sessions (e.g. phone + laptop logged in at the same time).

    # Password reset fields
    reset_code     = Column(String, nullable=True)    # 6-digit code sent via email
    reset_expires  = Column(DateTime, nullable=True)  # code expiry time


    # Links to other tables (one farmer has many scans, tasks etc.)
    scans      = relationship("Scan",          back_populates="farmer", cascade="all, delete")
    tasks      = relationship("Task",          back_populates="farmer", cascade="all, delete")
    inventory  = relationship("InventoryItem", back_populates="farmer", cascade="all, delete")
    profits    = relationship("ProfitRecord",  back_populates="farmer", cascade="all, delete")
    balance_items = relationship("BalanceItem", back_populates="farmer", cascade="all, delete")
    crops      = relationship("Crop",          back_populates="farmer", cascade="all, delete")
    auth_tokens   = relationship("AuthToken",   back_populates="farmer", cascade="all, delete")


class Scan(Base):
    """
    The scans table.
    One row = one photo analysed by the AI.
    """
    __tablename__ = "scans"
    id         = Column(Integer, primary_key=True, index=True)
    farmer_id  = Column(Integer, ForeignKey("farmers.id"), nullable=False)
    plant      = Column(String)           # e.g. "Tomato"
    disease    = Column(String)           # e.g. "Early blight"
    confidence = Column(Float)            # e.g. 94.5
    status     = Column(String)           # "healthy" or "diseased"
    severity   = Column(String)
    treatment  = Column(Text)
    chemical   = Column(Text)
    prevention = Column(Text)
    pdf_file   = Column(String)           # filename of the PDF report
    scanned_at = Column(DateTime, default=datetime.utcnow)
    farmer     = relationship("Farmer", back_populates="scans")


class Task(Base):
    """
    The tasks table — farm schedule.
    One row = one farming task (spray, water, harvest etc.)
    """
    __tablename__ = "tasks"
    id             = Column(Integer, primary_key=True, index=True)
    farmer_id      = Column(Integer, ForeignKey("farmers.id"), nullable=False)
    title          = Column(String, nullable=False)
    description    = Column(String, default="")
    crop_name      = Column(String, default="")
    task_type      = Column(String, default="general")  # spray|fertilize|water|harvest|inspect
    scheduled_date = Column(String)    # stored as "YYYY-MM-DD"
    done           = Column(Boolean, default=False)
    created_at     = Column(DateTime, default=datetime.utcnow)
    farmer         = relationship("Farmer", back_populates="tasks")


class InventoryItem(Base):
    """
    The inventory table.
    One row = one farm supply item (fertilizer, pesticide etc.)
    """
    __tablename__ = "inventory"
    id        = Column(Integer, primary_key=True, index=True)
    farmer_id = Column(Integer, ForeignKey("farmers.id"), nullable=False)
    name      = Column(String, nullable=False)
    category  = Column(String, default="Other")
    quantity  = Column(Float,  default=0)
    unit      = Column(String, default="kg")
    low_at    = Column(Float,  default=2)     # alert threshold
    cost      = Column(Float,  default=0)
    supplier  = Column(String, default="")
    added_at  = Column(DateTime, default=datetime.utcnow)
    farmer    = relationship("Farmer", back_populates="inventory")


class ProfitRecord(Base):
    """
    The profit_records table.
    One row = one income or expense entry.
    """
    __tablename__ = "profit_records"
    id          = Column(Integer, primary_key=True, index=True)
    farmer_id   = Column(Integer, ForeignKey("farmers.id"), nullable=False)
    type        = Column(String)     # "income" or "expense"
    amount      = Column(Float)
    category    = Column(String)
    description = Column(String, default="")
    crop        = Column(String, default="")
    date        = Column(String)     # "YYYY-MM-DD"
    created_at  = Column(DateTime, default=datetime.utcnow)
    farmer      = relationship("Farmer", back_populates="profits")


class AuthToken(Base):
    """
    The auth_tokens table.
    One row = one active login session. A farmer can have several rows
    at once (phone + laptop, etc.) — logging in on a new device creates
    a NEW row instead of overwriting the old one, so other sessions stay
    logged in.
    """
    __tablename__ = "auth_tokens"
    id          = Column(Integer, primary_key=True, index=True)
    farmer_id   = Column(Integer, ForeignKey("farmers.id"), nullable=False)
    token       = Column(String, unique=True, index=True, nullable=False)
    device_info = Column(String, default="")
    created_at  = Column(DateTime, default=datetime.utcnow)
    last_used   = Column(DateTime, default=datetime.utcnow)
    farmer      = relationship("Farmer", back_populates="auth_tokens")


class BalanceItem(Base):
    """
    The balance_items table.
    One row = one thing the farmer owns (asset) or owes (liability).
    Powers a simple balance sheet: Net Worth = Assets - Liabilities.
    """
    __tablename__ = "balance_items"
    id          = Column(Integer, primary_key=True, index=True)
    farmer_id   = Column(Integer, ForeignKey("farmers.id"), nullable=False)
    kind        = Column(String)     # "asset" or "liability"
    name        = Column(String)     # e.g. "Cash on hand", "Loan from SACCO"
    value       = Column(Float)
    notes       = Column(String, default="")
    created_at  = Column(DateTime, default=datetime.utcnow)
    farmer      = relationship("Farmer", back_populates="balance_items")


class Crop(Base):
    """
    The crops table.
    One row = one crop the farmer is growing.
    """
    __tablename__ = "crops"
    id           = Column(Integer, primary_key=True, index=True)
    farmer_id    = Column(Integer, ForeignKey("farmers.id"), nullable=False)
    name         = Column(String, nullable=False)
    crop_type    = Column(String, default="")
    plant_date   = Column(String)             # "YYYY-MM-DD"
    harvest_days = Column(Integer, default=90)
    field        = Column(String, default="Main Field")
    area         = Column(Float,  default=0)  # acres
    notes        = Column(String, default="")
    created_at   = Column(DateTime, default=datetime.utcnow)
    farmer       = relationship("Farmer", back_populates="crops")


# Create all tables in the database (runs on startup)
# If the table already exists, it is skipped — safe to run every time
Base.metadata.create_all(bind=engine)


def get_db():
    """
    Opens a database connection for one request, then closes it.
    FastAPI calls this automatically for every endpoint that needs the DB.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
#  REQUEST/RESPONSE SCHEMAS (Pydantic)
#  These define what data the API accepts and returns.
#  Like a form — specifies which fields are required.
# ═══════════════════════════════════════════════════════════

class RegisterRequest(BaseModel):
    name:      str
    phone:     str
    email:     Optional[str]   = None   # optional - used for password reset
    password:  str
    county:    Optional[str]   = "Kenya"
    farm_size: Optional[float] = 0

class LoginRequest(BaseModel):
    identifier: str   # can be phone OR email
    password:   str

class UpdateProfileRequest(BaseModel):
    name:      Optional[str]   = None
    county:    Optional[str]   = None
    farm_size: Optional[float] = None
    email:     Optional[str]   = None

class TaskRequest(BaseModel):
    title:          str
    description:    Optional[str] = ""
    crop_name:      Optional[str] = ""
    task_type:      Optional[str] = "general"
    scheduled_date: str

class TaskUpdateRequest(BaseModel):
    title:          Optional[str]  = None
    description:    Optional[str]  = None
    crop_name:      Optional[str]  = None
    task_type:      Optional[str]  = None
    scheduled_date: Optional[str]  = None
    done:           Optional[bool] = None

class InventoryRequest(BaseModel):
    name:     str
    category: str
    quantity: float
    unit:     str
    low_at:   Optional[float] = 2
    cost:     Optional[float] = 0
    supplier: Optional[str]   = ""

class InventoryUpdateRequest(BaseModel):
    quantity: float

class ProfitRequest(BaseModel):
    type:        str    # "income" or "expense"
    amount:      float
    category:    str
    description: Optional[str] = ""
    crop:        Optional[str] = ""
    date:        str

class BalanceItemRequest(BaseModel):
    kind:  str    # "asset" or "liability"
    name:  str
    value: float
    notes: Optional[str] = ""

class CropRequest(BaseModel):
    name:         str
    crop_type:    Optional[str] = ""
    plant_date:   str
    harvest_days: Optional[int]   = 90
    field:        Optional[str]   = "Main Field"
    area:         Optional[float] = 0
    notes:        Optional[str]   = ""


# ═══════════════════════════════════════════════════════════
#  AUTH HELPERS
#  Small utility functions for login security
# ═══════════════════════════════════════════════════════════

security = HTTPBearer(auto_error=False)

def hash_password(password: str) -> str:
    """
    Converts a plain password into a scrambled hash.
    e.g. "mypassword123" → "a8f5f167f44f..."
    We NEVER store the real password — only the hash.
    When someone logs in, we hash their input and compare hashes.
    """
    return hashlib.sha256(password.encode()).hexdigest()

def make_token() -> str:
    """
    Creates a random secret token (64 random characters).
    Given to the farmer after login. Acts like a temporary key.
    """
    return secrets.token_hex(32)

def get_current_farmer(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> "Farmer":
    """
    Reads the token from the request header and finds the farmer.
    Every protected endpoint uses this to know WHO is asking.
    If token is wrong/missing → returns 401 Unauthorized error.
    Looks up the auth_tokens table (not a single column on Farmer),
    so multiple devices can be logged in at once without kicking
    each other out.
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Not logged in. Please log in first.")
    token_row = db.query(AuthToken).filter(AuthToken.token == credentials.credentials).first()
    if not token_row:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    token_row.last_used = datetime.utcnow()
    db.commit()
    farmer = db.query(Farmer).filter(Farmer.id == token_row.farmer_id).first()
    if not farmer:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    return farmer

def get_optional_farmer(
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer(auto_error=False)),
    db: Session = Depends(get_db)
) -> Optional["Farmer"]:
    """
    Like get_current_farmer but does NOT fail if not logged in.
    Used for the scan endpoint — works for both guests and logged-in farmers.
    """
    if not credentials:
        return None
    token_row = db.query(AuthToken).filter(AuthToken.token == credentials.credentials).first()
    if not token_row:
        return None
    return db.query(Farmer).filter(Farmer.id == token_row.farmer_id).first()

def get_farm_scale(farm_size: float) -> str:
    """
    Automatically sets farmer tier based on farm size.
    Under 5 acres = small (100 scans/day after free period)
    5+ acres      = large (unlimited scans after free period)
    """
    return "large" if farm_size >= 5 else "small"

def is_free_period(registered_at: datetime) -> bool:
    """
    Returns True if the farmer is still within their 30-day free period.
    """
    return (datetime.utcnow() - registered_at).days < 30


# ═══════════════════════════════════════════════════════════
#  FASTAPI APP
#  This creates the actual web server.
# ═══════════════════════════════════════════════════════════

app = FastAPI(
    title="AgroTech AI API",
    version="1.0.0",
    description="Smart Farming Platform for Kenyan Farmers"
)

# CORS = Cross-Origin Resource Sharing
# This allows your frontend (port 3000) to talk to the backend (port 8000).
# Without this, the browser blocks all requests between different ports.
# Only allow our own frontend + local development to call the API.
ALLOWED_ORIGINS = [
    "https://agrotech-kenya.netlify.app",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Logging ───────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger("agrotech")

# ── Security headers on every response ────────────────────
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

# ── Simple in-memory rate limiter ─────────────────────────
# Tracks recent request timestamps per client IP per bucket.
# NOTE: resets on redeploy and is per-process — fine for this scale.
_rate_hits = defaultdict(list)
def rate_limit(request: Request, bucket: str, max_calls: int, window_sec: int):
    ip = (request.client.host if request.client else "unknown")
    key = bucket + ":" + ip
    now = time.time()
    hits = [t for t in _rate_hits[key] if now - t < window_sec]
    if len(hits) >= max_calls:
        raise HTTPException(status_code=429,
            detail="Too many attempts. Please wait a minute and try again.")
    hits.append(now)
    _rate_hits[key] = hits

# ── Catch-all error handlers (nothing fails silently) ─────
@app.exception_handler(StarletteHTTPException)
async def http_exc_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

@app.exception_handler(Exception)
async def unhandled_exc_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500,
        content={"detail": "Something went wrong on our end. Please try again shortly."})


# ═══════════════════════════════════════════════════════════
#  LOAD THE AI MODEL
#  Runs once when the server starts.
#  The model stays loaded in memory — ready to analyse photos instantly.
# ═══════════════════════════════════════════════════════════

print("\n🌿 AgroTech Backend starting up...")

MODEL_PATH  = os.path.join(BASE_DIR, "plant_model.h5")
LABELS_PATH = os.path.join(BASE_DIR, "class_labels.pkl")

try:
    model = tf.keras.models.load_model(MODEL_PATH)
    with open(LABELS_PATH, "rb") as f:
        class_indices = pickle.load(f)
    # Flip the dictionary: {name: index} → {index: name}
    # So we can look up a name by its number
    labels = {v: k for k, v in class_indices.items()}
    MODEL_LOADED = True
    print(f"✅ AI Model loaded — {len(labels)} disease classes ready")
except Exception as e:
    print(f"⚠️  Model not found: {e}")
    print("   Place plant_model.h5 and class_labels.pkl in the backend folder")
    model       = None
    labels      = {}
    MODEL_LOADED = False


# ═══════════════════════════════════════════════════════════
#  DISEASE TREATMENT DATABASE
#  For each disease the AI detects, this gives:
#  - What signs to look for
#  - How to treat it
#  - Which chemicals and their Kenyan prices
#  - How to prevent it next season
# ═══════════════════════════════════════════════════════════

DISEASE_DB = {
    # ── KEY FORMAT ──────────────────────────────────────────
    # The key is matched against the disease name from the AI.
    # e.g. if AI returns "Tomato___Early_blight", we look for "early_blight"

    "healthy": {
        "status": "healthy", "severity": "None",
        "signs": "No disease detected. Your crop looks healthy!",
        "treatment": "Your plant is healthy. Keep up the good work.",
        "chemical": "No treatment needed.",
        "prevention": "Continue regular watering, proper spacing, and crop rotation.",
        "organic": "Use compost tea and neem oil sprays as prevention."
    },
    "early_blight": {
        "status": "diseased", "severity": "Moderate — act within 3-5 days",
        "signs": "Dark brown spots with yellow rings (bullseye pattern) on older lower leaves. Spreads upward.",
        "treatment": "Remove infected lower leaves immediately. Spray Mancozeb 80WP (2g per litre of water) every 7-10 days. Water only at the base of plants, never from above.",
        "chemical": "Mancozeb 80WP — KES 250-400/kg\nRidomil Gold MZ — KES 600-900/pack",
        "prevention": "Rotate crops every season. Remove plant debris after harvest. Space plants 60cm apart.",
        "organic": "Neem oil (5ml per litre) weekly. Copper oxychloride as organic option."
    },
    "late_blight": {
        "status": "diseased", "severity": "CRITICAL — destroys crop in 3-5 days",
        "signs": "Water-soaked grey-green patches turning brown and oily. White mould on leaf undersides in humid conditions.",
        "treatment": "URGENT — act within 24 hours. Remove and BURN (do not compost) all infected material. Apply Ridomil Gold MZ immediately and every 5 days.",
        "chemical": "Ridomil Gold MZ — KES 600-900/pack\nEquation Pro — KES 800-1,200/pack\nCopper Hydroxide (Kocide) — KES 400-600/kg",
        "prevention": "Plant resistant varieties. Never use overhead irrigation. Improve field drainage.",
        "organic": "Bordeaux Mixture spray. Remove lower leaves to improve air circulation."
    },
    "bacterial_spot": {
        "status": "diseased", "severity": "Moderate — spreads by water splash",
        "signs": "Small water-soaked spots with yellow halos on leaves and fruit. Spots on fruit raise then crack open.",
        "treatment": "Remove infected leaves. Apply Copper Hydroxide every 7 days. Never work in the field when plants are wet.",
        "chemical": "Copper Hydroxide (Kocide) — KES 400-600/kg\nBordeaux Mixture — KES 200-350/kg",
        "prevention": "Use certified disease-free seeds. Disinfect pruning tools with bleach. Never water from above.",
        "organic": "Copper oxychloride spray. Apple cider vinegar (2 tablespoons per litre)."
    },
    "powdery_mildew": {
        "status": "diseased", "severity": "Low to Moderate",
        "signs": "White powdery coating on leaves and stems. Leaves curl and yellow. Young shoots may be distorted.",
        "treatment": "Spray Sulphur-based fungicide or Copper Oxychloride. Prune crowded plants to improve airflow.",
        "chemical": "Sulphur fungicide — KES 200-350\nCopper Oxychloride — KES 300-500/kg",
        "prevention": "Plant resistant varieties. Avoid excess nitrogen fertilizer. Space plants well apart.",
        "organic": "Milk spray (1 part milk : 9 parts water). Baking soda spray. Neem oil weekly."
    },
    "black_rot": {
        "status": "diseased", "severity": "High — spreads rapidly in warm wet weather",
        "signs": "V-shaped yellow lesions starting from leaf margins. Black veins visible. Leaves wilt.",
        "treatment": "Remove and destroy infected plants. Apply Copper-based fungicide every 7 days. Do not compost infected material.",
        "chemical": "Copper Hydroxide — KES 400-600/kg\nBordeaux Mixture — KES 200-350/kg",
        "prevention": "Use certified seeds. Rotate crops minimum 3 years. Avoid working when plants are wet.",
        "organic": "Copper oxychloride. Remove and burn infected material."
    },
    "leaf_scorch": {
        "status": "diseased", "severity": "Moderate",
        "signs": "Scorched brown edges on leaves. Dead tissue spreads from leaf margin inward.",
        "treatment": "Improve irrigation consistency — avoid drought stress. Apply balanced fertilizer. Remove severely affected leaves.",
        "chemical": "Foliar potassium spray — KES 300-500\nCopper Oxychloride as protective spray",
        "prevention": "Consistent watering schedule. Avoid drought. Mulch around plant base to retain moisture.",
        "organic": "Compost mulch. Seaweed extract foliar spray."
    },
    "leaf_mold": {
        "status": "diseased", "severity": "Moderate — common in greenhouses",
        "signs": "Yellow patches on upper surface of leaves. Olive-green fuzzy mould on undersides. Leaves curl and drop.",
        "treatment": "Prune crowded plants. Remove mouldy leaves. Spray Mancozeb or Copper Oxychloride every 7 days.",
        "chemical": "Mancozeb 80WP — KES 250-400/kg\nCopper Oxychloride — KES 300-500/kg",
        "prevention": "Avoid overcrowding. Keep humidity below 85%. Water only in the morning.",
        "organic": "Neem oil spray. Baking soda solution (1 tablespoon per litre)."
    },
    "septoria_leaf_spot": {
        "status": "diseased", "severity": "Moderate",
        "signs": "Small circular spots with dark borders and grey/tan centres. Tiny black dots visible inside spots.",
        "treatment": "Remove lower infected leaves. Apply Mancozeb or Copper fungicide every 7-10 days.",
        "chemical": "Mancozeb 80WP — KES 250-400/kg\nCopper Oxychloride — KES 300-500/kg",
        "prevention": "Remove crop debris after harvest. Avoid overhead watering. Proper plant spacing.",
        "organic": "Copper-based organic sprays. Remove infected leaves promptly."
    },
    "spider_mites": {
        "status": "diseased", "severity": "Moderate — worsens in dry hot weather",
        "signs": "Fine webbing on leaves. Tiny yellow or white stippling dots on upper leaf surface. Leaves look dusty.",
        "treatment": "Spray Abamectin or Acaricide. Increase humidity. Remove heavily infested leaves.",
        "chemical": "Abamectin — KES 400-700\nPropargite Acaricide — KES 500-800",
        "prevention": "Avoid over-fertilizing with nitrogen. Keep plants well watered. Remove weeds regularly.",
        "organic": "Neem oil spray. Insecticidal soap. Strong water jet to dislodge mites."
    },
    "target_spot": {
        "status": "diseased", "severity": "Moderate",
        "signs": "Circular spots with concentric rings (target/bullseye pattern). Yellow halo around each spot.",
        "treatment": "Remove infected leaves. Apply Chlorothalonil or Mancozeb every 7 days.",
        "chemical": "Chlorothalonil — KES 350-600\nMancozeb 80WP — KES 250-400/kg",
        "prevention": "Proper plant spacing. Avoid overcrowding. Remove crop debris after harvest.",
        "organic": "Neem oil spray. Baking soda solution."
    },
    "mosaic_virus": {
        "status": "diseased", "severity": "High — no chemical cure available",
        "signs": "Mottled yellow-green mosaic pattern on leaves. Leaves may curl, pucker, or be distorted.",
        "treatment": "No chemical cure exists. Remove and DESTROY infected plants immediately. Control aphid insects that spread the virus.",
        "chemical": "Imidacloprid — KES 500-800 (kills aphid vectors)\nNo direct antiviral chemical available",
        "prevention": "Use certified virus-free seeds. Control aphids strictly. Remove weeds. Disinfect tools between plants.",
        "organic": "Neem oil to repel aphids. Reflective mulch. Remove infected plants immediately."
    },
    "apple_scab": {
        "status": "diseased", "severity": "Moderate",
        "signs": "Olive-green or brown scab-like lesions on leaves and fruit. Fruit may crack or deform.",
        "treatment": "Apply Captan or Mancozeb fungicide preventively before rain. Remove fallen leaves.",
        "chemical": "Captan — KES 400-700/kg\nMancozeb 80WP — KES 250-400/kg",
        "prevention": "Plant resistant varieties. Remove fallen leaves. Prune for good airflow.",
        "organic": "Copper-based sprays. Remove infected leaves and fruit."
    },
    "cercospora": {
        "status": "diseased", "severity": "Moderate",
        "signs": "Grey leaf spots with dark borders. Tan or grey centres. Common in maize/corn.",
        "treatment": "Apply Mancozeb or Propiconazole. Remove infected lower leaves.",
        "chemical": "Mancozeb 80WP — KES 250-400/kg\nPropiconazole — KES 400-700",
        "prevention": "Plant resistant varieties. Crop rotation. Avoid overhead irrigation.",
        "organic": "Neem oil spray. Remove infected leaves."
    },
    "common_rust": {
        "status": "diseased", "severity": "Moderate",
        "signs": "Orange-brown powdery pustules on both surfaces of leaves. Leaves yellow and may die early.",
        "treatment": "Spray Mancozeb or Tebuconazole fungicide. Remove severely infected plants.",
        "chemical": "Mancozeb 80WP — KES 250-400/kg\nTebuconazole — KES 400-700",
        "prevention": "Plant resistant varieties. Avoid overcrowding. Crop rotation.",
        "organic": "Neem oil weekly. Remove infected leaves promptly."
    },
    "northern_leaf_blight": {
        "status": "diseased", "severity": "Moderate to High",
        "signs": "Long grey-green cigar-shaped lesions on maize leaves. Lesions turn tan with dark borders.",
        "treatment": "Apply Mancozeb or Azoxystrobin at first sign. Remove infected lower leaves.",
        "chemical": "Mancozeb 80WP — KES 250-400/kg\nAzoxystrobin — KES 600-900",
        "prevention": "Plant resistant maize varieties. Crop rotation. Remove crop debris.",
        "organic": "Copper-based sprays. Remove infected material."
    },
    "haunglongbing": {
        "status": "diseased", "severity": "CRITICAL — incurable, kills tree eventually",
        "signs": "Yellow shoots on one side of tree (called blotchy mottle). Fruit small, lopsided, bitter.",
        "treatment": "No cure. Remove and destroy infected trees to protect neighbours. Control psyllid insects that spread it.",
        "chemical": "Imidacloprid — KES 500-800 (kills psyllid vector)\nNo cure for the disease itself",
        "prevention": "Use certified disease-free seedlings. Control psyllid insects. Inspect new plants carefully.",
        "organic": "Neem oil to control psyllids. Remove infected trees."
    },
    "esca": {
        "status": "diseased", "severity": "High — chronic wood disease",
        "signs": "Tiger-stripe pattern on grape leaves. Sudden wilting of shoots. Dark streaking in wood when cut.",
        "treatment": "Remove and destroy infected wood. Apply wound sealant after pruning. No effective chemical cure.",
        "chemical": "Wound sealants/protectants — KES 300-500",
        "prevention": "Prune in dry weather. Seal all pruning wounds. Avoid mechanical damage.",
        "organic": "Trichoderma-based biocontrol. Proper pruning hygiene."
    },
    "default": {
        "status": "diseased", "severity": "Moderate",
        "signs": "Visible symptoms detected on the leaf. Check surrounding plants for spread.",
        "treatment": "Remove visibly infected leaves. Apply broad-spectrum fungicide every 7 days.",
        "chemical": "Mancozeb 80WP (2g per litre) — KES 250-400/kg\nCopper Oxychloride — KES 300-500/kg",
        "prevention": "Proper spacing, avoid overhead watering, remove infected leaves, rotate crops.",
        "organic": "Neem oil spray (5ml per litre). Remove and burn infected material."
    }
}


def get_disease_info(disease_name: str) -> dict:
    """
    Finds treatment info for a detected disease.
    disease_name comes from the AI like: "Early_blight" or "Spider_mites Two-spotted_spider_mite"
    We convert it to lowercase and search the dictionary.
    """
    name_lower = disease_name.lower().replace(" ", "_")
    for key in DISEASE_DB:
        if key != "default" and key in name_lower:
            return DISEASE_DB[key]
    # If no match found, use the default (generic treatment advice)
    return DISEASE_DB["default"]


# ═══════════════════════════════════════════════════════════
#  IMAGE PROCESSING HELPERS
# ═══════════════════════════════════════════════════════════

def is_leaf_image(image: Image.Image) -> tuple:
    """
    Checks if the uploaded photo actually contains a plant leaf.
    Rejects: dark photos, skin/hand photos, objects (not plants).
    Returns: (True, "ok") or (False, "reason why rejected")
    """
    img_rgb = image.convert("RGB").resize((150, 150))
    pixels  = np.array(img_rgb, dtype=float)
    r, g, b = pixels[:,:,0], pixels[:,:,1], pixels[:,:,2]
    total   = 150 * 150

    # Reject photos that look like skin (hand holding leaf wrong way)
    skin_mask = (r>150)&(r<255)&(g>90)&(g<200)&(b>60)&(b<180)&(r-b>20)&(r-g>5)&(r-g<80)
    if np.sum(skin_mask)/total > 0.30:
        return False, "This looks like a photo of a hand, not a plant leaf. Please photograph the leaf directly."

    # Check for plant colours (green, yellow-green, brown = diseased leaf)
    strict_green = (g>r)&(g>b)&(g>45)&(g-r>8)&(g-b>5)&(g<230)
    yellow_green = (g>100)&(r>80)&(b<120)&(g+r>b*2.5)&(abs(r.astype(float)-g.astype(float))<60)
    brown_mask   = (r>80)&(r<200)&(g>40)&(g<160)&(b<100)&(r>g)&(g>b)&(r-b>25)
    plant_ratio  = (np.sum(strict_green) + np.sum(yellow_green)*0.6 + np.sum(brown_mask)*0.4) / total

    # Reject pure grey/white/blank images
    grey_mask = (abs(r-g)<18)&(abs(g-b)<18)&(abs(r-b)<18)
    if np.sum(grey_mask)/total > 0.65 and plant_ratio < 0.12:
        return False, "No plant material detected. Please photograph a crop leaf."

    # Reject very dark photos
    if np.mean((r+g+b)/3) < 25:
        return False, "Photo is too dark. Move to better lighting and try again."

    if plant_ratio >= 0.10:
        return True, "ok"

    return False, "No leaf detected. Please take a clear close-up photo of a crop leaf."


def preprocess_image(image: Image.Image) -> np.ndarray:
    """
    Prepares the image for the AI model.
    - Resize to 160x160 pixels (what the model was trained on)
    - Convert pixels from 0-255 range to 0-1 range (normalise)
    - Add a batch dimension (model expects arrays of images)
    """
    img = image.convert("RGB").resize((160, 160))
    arr = np.array(img) / 255.0          # 0-255 → 0-1
    return np.expand_dims(arr, axis=0)   # shape: (160,160,3) → (1,160,160,3)


# ═══════════════════════════════════════════════════════════
#  PDF REPORT GENERATOR
#  Creates a professional PDF for each scan result.
#  Saved to the "reports" folder inside backend.
# ═══════════════════════════════════════════════════════════

PDF_FOLDER = os.path.join(BASE_DIR, "reports")
os.makedirs(PDF_FOLDER, exist_ok=True)   # create folder if it doesn't exist


def generate_pdf_report(disease_name, confidence, plant_name, info, farmer_name="Farmer"):
    """
    Builds a PDF scan report using ReportLab library.
    Returns the filename (not the full path).
    """
    report_id = str(uuid.uuid4())[:8].upper()   # e.g. "A3F7B2C1"
    filename  = f"AgroTech_Report_{report_id}.pdf"
    filepath  = os.path.join(PDF_FOLDER, filename)

    doc    = SimpleDocTemplate(filepath, pagesize=A4,
                               rightMargin=inch, leftMargin=inch,
                               topMargin=inch, bottomMargin=inch)
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('Title', parent=styles['Heading1'],
                                 fontSize=20, textColor=colors.HexColor('#1B4332'), spaceAfter=4)
    h_style     = ParagraphStyle('H', parent=styles['Heading2'],
                                 fontSize=12, textColor=colors.HexColor('#1B4332'),
                                 spaceBefore=14, spaceAfter=4)
    b_style     = ParagraphStyle('B', parent=styles['Normal'],
                                 fontSize=10, textColor=colors.HexColor('#2D3D2D'), leading=16)
    f_style     = ParagraphStyle('F', parent=styles['Normal'],
                                 fontSize=9, textColor=colors.grey)

    story = []
    story.append(Paragraph("AgroTech AI Scan Report", title_style))
    story.append(Paragraph(
        f"Farmer: <b>{farmer_name}</b>  |  Report ID: <b>{report_id}</b>  |  "
        f"Date: <b>{datetime.now().strftime('%d %B %Y, %I:%M %p')}</b>",
        styles['Normal']))
    story.append(Spacer(1, 16))

    is_diseased  = info['status'] == 'diseased'
    status_color = colors.HexColor('#D32F2F') if is_diseased else colors.HexColor('#1B5E20')
    status_label = "DISEASED — Action Required" if is_diseased else "HEALTHY"
    status_bg    = colors.HexColor('#FFEBEE') if is_diseased else colors.HexColor('#E8F5E9')

    result_data = [
        ["DIAGNOSIS RESULT", ""],
        ["Plant / Crop",       plant_name.replace("_", " ").title()],
        ["Condition Detected", disease_name.replace("_", " ").title()],
        ["AI Confidence",      f"{confidence:.1f}%"],
        ["Severity",           info['severity']],
        ["Status",             status_label],
    ]
    tbl = Table(result_data, colWidths=[2.5*inch, 4*inch])
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1B4332')),
        ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
        ('FONTSIZE',   (0,0), (-1,0), 13),
        ('SPAN',       (0,0), (-1,0)),
        ('ALIGN',      (0,0), (-1,0), 'CENTER'),
        ('BACKGROUND', (0,5), (-1,5), status_bg),
        ('TEXTCOLOR',  (0,5), (-1,5), status_color),
        ('FONTNAME',   (0,5), (-1,5), 'Helvetica-Bold'),
        ('GRID',       (0,0), (-1,-1), 0.5, colors.HexColor('#CCDDCC')),
        ('FONTSIZE',   (0,1), (-1,-1), 11),
        ('PADDING',    (0,0), (-1,-1), 8),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 16))

    sections = [
        ("Signs to Look For",                "signs"),
        ("How to Treat",                     "treatment"),
        ("Recommended Chemicals and Prices", "chemical"),
        ("Prevention for Next Season",       "prevention"),
        ("Organic and Home Remedies",        "organic"),
    ] if is_diseased else [
        ("Crop Status",        "treatment"),
        ("Prevention Tips",    "prevention"),
        ("Organic Boosters",   "organic"),
    ]

    for heading, key in sections:
        story.append(Paragraph(heading, h_style))
        story.append(Paragraph(info.get(key, "—"), b_style))

    story.append(Spacer(1, 24))
    story.append(Paragraph(
        "Generated by AgroTech AI Platform. For professional advice, "
        "contact your local agricultural extension officer.",
        f_style))

    doc.build(story)
    return filename


def generate_financial_report_pdf(farmer_name, income_records, expense_records, assets, liabilities):
    """
    Builds a downloadable financial report PDF: Profit & Loss statement
    plus a simple Balance Sheet. Designed to be presentable enough for
    grant applications, loan requests, or cooperative membership.
    Returns the filename (not the full path).
    """
    report_id = str(uuid.uuid4())[:8].upper()
    filename  = f"AgroTech_Financial_Report_{report_id}.pdf"
    filepath  = os.path.join(PDF_FOLDER, filename)

    doc    = SimpleDocTemplate(filepath, pagesize=A4,
                               rightMargin=inch, leftMargin=inch,
                               topMargin=inch, bottomMargin=inch)
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('Title', parent=styles['Heading1'],
                                 fontSize=20, textColor=colors.HexColor('#1B4332'), spaceAfter=4)
    h_style     = ParagraphStyle('H', parent=styles['Heading2'],
                                 fontSize=13, textColor=colors.HexColor('#1B4332'),
                                 spaceBefore=18, spaceAfter=6)
    f_style     = ParagraphStyle('F', parent=styles['Normal'],
                                 fontSize=9, textColor=colors.grey)

    story = []
    story.append(Paragraph("AgroTech Financial Report", title_style))
    story.append(Paragraph(
        f"Farmer: <b>{farmer_name}</b>  |  Report ID: <b>{report_id}</b>  |  "
        f"Generated: <b>{datetime.now().strftime('%d %B %Y, %I:%M %p')}</b>",
        styles['Normal']))
    story.append(Spacer(1, 16))

    # ── PROFIT & LOSS STATEMENT ─────────────────────────
    total_income  = sum(r.amount for r in income_records)
    total_expense = sum(r.amount for r in expense_records)
    net_profit    = total_income - total_expense

    story.append(Paragraph("Profit &amp; Loss Statement", h_style))
    pl_data = [["", "Amount (KES)"]]
    pl_data.append(["Total Income", f"{total_income:,.2f}"])
    pl_data.append(["Total Expenses", f"{total_expense:,.2f}"])
    pl_data.append(["Net Profit / Loss", f"{net_profit:,.2f}"])

    pl_tbl = Table(pl_data, colWidths=[3.5*inch, 2.5*inch])
    pl_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1B4332')),
        ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
        ('ALIGN',      (1,0), (1,-1), 'RIGHT'),
        ('GRID',       (0,0), (-1,-1), 0.5, colors.HexColor('#CCDDCC')),
        ('FONTSIZE',   (0,0), (-1,-1), 10),
        ('PADDING',    (0,0), (-1,-1), 8),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#E8F5E9')),
        ('FONTNAME',   (0,-1), (-1,-1), 'Helvetica-Bold'),
    ]))
    story.append(pl_tbl)

    # Income breakdown by category
    if income_records:
        story.append(Spacer(1, 10))
        story.append(Paragraph("Income by Category", ParagraphStyle('h4', fontSize=10, textColor=colors.HexColor('#1B4332'), spaceAfter=4)))
        income_by_cat = {}
        for r in income_records:
            income_by_cat[r.category] = income_by_cat.get(r.category, 0) + r.amount
        cat_data = [[cat, f"{amt:,.2f}"] for cat, amt in sorted(income_by_cat.items(), key=lambda x:-x[1])]
        cat_tbl = Table([["Category","Amount (KES)"]] + cat_data, colWidths=[3.5*inch, 2.5*inch])
        cat_tbl.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#DDEEDD')),
            ('ALIGN', (1,0), (1,-1), 'RIGHT'),
            ('GRID', (0,0), (-1,-1), 0.4, colors.HexColor('#DDDDDD')),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('PADDING', (0,0), (-1,-1), 6),
        ]))
        story.append(cat_tbl)

    # Expense breakdown by category
    if expense_records:
        story.append(Spacer(1, 10))
        story.append(Paragraph("Expenses by Category", ParagraphStyle('h4', fontSize=10, textColor=colors.HexColor('#1B4332'), spaceAfter=4)))
        expense_by_cat = {}
        for r in expense_records:
            expense_by_cat[r.category] = expense_by_cat.get(r.category, 0) + r.amount
        cat_data = [[cat, f"{amt:,.2f}"] for cat, amt in sorted(expense_by_cat.items(), key=lambda x:-x[1])]
        cat_tbl = Table([["Category","Amount (KES)"]] + cat_data, colWidths=[3.5*inch, 2.5*inch])
        cat_tbl.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#FFE0E0')),
            ('ALIGN', (1,0), (1,-1), 'RIGHT'),
            ('GRID', (0,0), (-1,-1), 0.4, colors.HexColor('#DDDDDD')),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('PADDING', (0,0), (-1,-1), 6),
        ]))
        story.append(cat_tbl)

    # ── SIMPLE BALANCE SHEET ─────────────────────────────
    total_assets      = sum(a.value for a in assets)
    total_liabilities = sum(l.value for l in liabilities)
    net_worth         = total_assets - total_liabilities

    story.append(Paragraph("Simple Balance Sheet", h_style))

    bs_rows = [["ASSETS", "Value (KES)"]]
    if assets:
        for a in assets:
            bs_rows.append([a.name, f"{a.value:,.2f}"])
    else:
        bs_rows.append(["No assets recorded", "0.00"])
    bs_rows.append(["Total Assets", f"{total_assets:,.2f}"])

    assets_tbl = Table(bs_rows, colWidths=[3.5*inch, 2.5*inch])
    assets_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1B4332')),
        ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('GRID', (0,0), (-1,-1), 0.4, colors.HexColor('#DDDDDD')),
        ('FONTSIZE', (0,0), (-1,-1), 9.5),
        ('PADDING', (0,0), (-1,-1), 7),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#E8F5E9')),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
    ]))
    story.append(assets_tbl)
    story.append(Spacer(1, 10))

    li_rows = [["LIABILITIES", "Value (KES)"]]
    if liabilities:
        for l in liabilities:
            li_rows.append([l.name, f"{l.value:,.2f}"])
    else:
        li_rows.append(["No liabilities recorded", "0.00"])
    li_rows.append(["Total Liabilities", f"{total_liabilities:,.2f}"])

    li_tbl = Table(li_rows, colWidths=[3.5*inch, 2.5*inch])
    li_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1B4332')),
        ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('GRID', (0,0), (-1,-1), 0.4, colors.HexColor('#DDDDDD')),
        ('FONTSIZE', (0,0), (-1,-1), 9.5),
        ('PADDING', (0,0), (-1,-1), 7),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#FFEBEE')),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
    ]))
    story.append(li_tbl)
    story.append(Spacer(1, 10))

    nw_tbl = Table([["NET WORTH (Assets − Liabilities)", f"KES {net_worth:,.2f}"]], colWidths=[3.5*inch, 2.5*inch])
    nw_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#1B4332')),
        ('TEXTCOLOR',  (0,0), (-1,-1), colors.white),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('FONTSIZE', (0,0), (-1,-1), 11),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
        ('PADDING', (0,0), (-1,-1), 9),
    ]))
    story.append(nw_tbl)

    story.append(Spacer(1, 24))
    story.append(Paragraph(
        "Generated by AgroTech AI Platform. This is a self-reported financial summary "
        "prepared by the farmer and has not been independently audited.",
        f_style))

    doc.build(story)
    return filename


# ═══════════════════════════════════════════════════════════
#  HELPER: Convert farmer DB object → dictionary for JSON
# ═══════════════════════════════════════════════════════════

def farmer_to_dict(farmer: Farmer) -> dict:
    days_since    = (datetime.utcnow() - farmer.registered_at).days
    free_period   = days_since < 30
    free_days_left = max(0, 30 - days_since)
    return {
        "id":             farmer.id,
        "name":           farmer.name,
        "phone":          farmer.phone,
        "email":          farmer.email,
        "county":         farmer.county,
        "farmSize":       farmer.farm_size,
        "farmScale":      farmer.farm_scale,
        "registeredAt":   farmer.registered_at.isoformat(),
        "freePeriod":     free_period,
        "freeDaysLeft":   free_days_left,
        "freePeriodEndsAt": (farmer.registered_at + timedelta(days=30)).isoformat(),
    }


# ═══════════════════════════════════════════════════════════
#  API ENDPOINTS
#
#  An endpoint = one URL that does one job.
#  The frontend calls these URLs to get data or send data.
#
#  Format:
#    @app.get("/url")    = reading data (GET request)
#    @app.post("/url")   = sending new data (POST request)
#    @app.put("/url")    = updating existing data (PUT request)
#    @app.delete("/url") = deleting data (DELETE request)
# ═══════════════════════════════════════════════════════════


# ── ROOT / HEALTH CHECK ───────────────────────────────────
@app.get("/")
def home():
    """ Test that the server is running. Open http://localhost:8000 """
    return {
        "message":      "AgroTech AI Backend is running!",
        "model_loaded": MODEL_LOADED,
        "classes":      len(labels),
        "docs":         "Visit /docs to see all endpoints"
    }

@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": MODEL_LOADED, "classes": len(labels)}


# ── AUTH ENDPOINTS ────────────────────────────────────────

@app.post("/auth/register")
def register(req: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    rate_limit(request, "register", max_calls=5, window_sec=60)
    """
    Creates a new farmer account.
    Called when a farmer clicks "Create My Farm Account".
    """
    # Check if phone number is already registered
    existing = db.query(Farmer).filter(Farmer.phone == req.phone).first()
    if existing:
        raise HTTPException(status_code=400, detail="This phone number is already registered.")

    # Check if email is already registered (only if email was provided)
    email = (req.email or "").strip().lower() or None
    if email:
        existing_email = db.query(Farmer).filter(Farmer.email == email).first()
        if existing_email:
            raise HTTPException(status_code=400, detail="This email is already registered.")

    scale  = get_farm_scale(req.farm_size or 0)
    farmer = Farmer(
        name          = req.name,
        phone         = req.phone,
        email         = email,
        password_hash = hash_password(req.password),
        county        = req.county or "Kenya",
        farm_size     = req.farm_size or 0,
        farm_scale    = scale
    )
    db.add(farmer)
    db.commit()
    db.refresh(farmer)

    token = make_token()
    db.add(AuthToken(
        farmer_id=farmer.id, token=token,
        device_info=request.headers.get("user-agent", "")[:200]
    ))
    db.commit()
    return {"success": True, "token": token, "user": farmer_to_dict(farmer)}


@app.post("/auth/login")
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    rate_limit(request, "login", max_calls=8, window_sec=60)
    """
    Checks phone OR email + password, returns a token if correct.
    Called when farmer clicks "Login to AgroTech".
    The 'identifier' field can be a phone number or an email address.
    """
    identifier = req.identifier.strip().lower()

    # Try matching by phone first, then by email
    farmer = db.query(Farmer).filter(Farmer.phone == req.identifier.strip()).first()
    if not farmer:
        farmer = db.query(Farmer).filter(Farmer.email == identifier).first()

    if not farmer or farmer.password_hash != hash_password(req.password):
        raise HTTPException(status_code=401, detail="Wrong phone/email or password.")

    # Create a NEW session row instead of overwriting any existing one —
    # this is what lets a farmer stay logged in on their phone AND laptop
    # at the same time, without one login kicking the other out.
    token = make_token()
    db.add(AuthToken(
        farmer_id=farmer.id, token=token,
        device_info=request.headers.get("user-agent", "")[:200]
    ))
    db.commit()
    return {"success": True, "token": token, "user": farmer_to_dict(farmer)}


@app.post("/auth/logout")
def logout(farmer: Farmer = Depends(get_current_farmer),
           credentials: HTTPAuthorizationCredentials = Depends(security),
           db: Session = Depends(get_db)):
    """
    Logs out ONLY the current device/session — other devices where this
    farmer is logged in stay logged in.
    """
    db.query(AuthToken).filter(AuthToken.token == credentials.credentials).delete()
    db.commit()
    return {"success": True}


@app.post("/auth/logout-all")
def logout_all_devices(farmer: Farmer = Depends(get_current_farmer), db: Session = Depends(get_db)):
    """
    Logs out EVERY device this farmer is signed in on — useful if they
    suspect someone else has access, or just want a clean slate.
    """
    db.query(AuthToken).filter(AuthToken.farmer_id == farmer.id).delete()
    db.commit()
    return {"success": True}


@app.get("/auth/me")
def get_me(farmer: Farmer = Depends(get_current_farmer)):
    """ Returns the currently logged-in farmer's profile. """
    return farmer_to_dict(farmer)


@app.put("/auth/profile")
def update_profile(
    req:    UpdateProfileRequest,
    farmer: Farmer  = Depends(get_current_farmer),
    db:     Session = Depends(get_db)
):
    """ Updates farmer's name, county, farm size, or email. """
    if req.name      is not None: farmer.name      = req.name
    if req.county    is not None: farmer.county    = req.county
    if req.farm_size is not None:
        farmer.farm_size  = req.farm_size
        farmer.farm_scale = get_farm_scale(req.farm_size)

    # Update email — check it's not already taken by another farmer
    if req.email is not None:
        new_email = req.email.strip().lower() if req.email else None
        if new_email:
            existing = db.query(Farmer).filter(
                Farmer.email == new_email,
                Farmer.id != farmer.id
            ).first()
            if existing:
                raise HTTPException(status_code=400,
                    detail="This email is already used by another account.")
        farmer.email = new_email

    db.commit()
    return {"success": True, "user": farmer_to_dict(farmer)}


# ── SCAN / AI ENDPOINTS ───────────────────────────────────

@app.post("/predict")
async def predict(
    request: Request,
    file:   UploadFile       = File(...),
    db:     Session          = Depends(get_db),
    farmer: Optional[Farmer] = Depends(get_optional_farmer)
):
    rate_limit(request, "predict", max_calls=20, window_sec=60)
    """
    THE MAIN AI ENDPOINT.
    Farmer uploads a photo → AI analyses it → returns disease info.

    Steps:
    1. Read the uploaded image file
    2. Check it's actually a leaf photo
    3. Resize and normalise for the model
    4. Run the model → get prediction
    5. Check confidence is high enough
    6. Look up treatment info
    7. Generate PDF report
    8. Save scan to database (if logged in)
    9. Return all results
    """
    if not MODEL_LOADED:
        raise HTTPException(status_code=503,
            detail="AI model not loaded. Please ensure plant_model.h5 is in the backend folder.")

    # Read image bytes from the upload
    try:
        contents = await file.read()
        image    = Image.open(io.BytesIO(contents))
    except Exception:
        raise HTTPException(status_code=400,
            detail="Invalid image file. Please upload a JPG or PNG photo.")

    # Check it's a leaf
    valid, reason = is_leaf_image(image)
    if not valid:
        raise HTTPException(status_code=422, detail=f"Photo rejected: {reason}")

    # Run the AI model
    processed       = preprocess_image(image)
    predictions     = model.predict(processed, verbose=0)
    predicted_index = int(np.argmax(predictions[0]))
    confidence      = float(np.max(predictions[0])) * 100

    # Get TOP 3 predictions for possible disease suggestions
    top3_indices = predictions[0].argsort()[-3:][::-1]
    top3 = [
        {
            "label": labels[i].replace("___", " — ").replace("_", " "),
            "confidence": round(float(predictions[0][i]) * 100, 1)
        }
        for i in top3_indices
    ]

    # Reject if confidence is too low (blurry/dark photo)
    if confidence < 60.0:
        raise HTTPException(status_code=422,
            detail=f"Photo not clear enough ({confidence:.1f}% confidence). "
                   f"Take a closer, well-lit photo of the leaf.")

    # Get the class name — e.g. "Tomato___Early_blight"
    disease_label = labels[predicted_index]

    # Split into plant name and disease name
    parts      = disease_label.split("___")
    plant_name = parts[0] if len(parts) > 1 else "Unknown"
    condition  = parts[1] if len(parts) > 1 else disease_label

    # ── UNKNOWN CROP DETECTION ────────────────────────────────────
    # The model is trained on specific crops only:
    # Tomato, Potato, Apple, Corn, Grape, Pepper, etc.
    # If a farmer scans a pumpkin, mango, avocado etc., the model
    # still forces it into the nearest trained class — which is WRONG.
    #
    # We detect this by checking:
    # 1. If confidence is below 85% → uncertain, show possible diseases only
    # 2. If all top-3 predictions are from DIFFERENT crops → crop is unknown
    #
    KNOWN_CROPS = {
        "tomato", "potato", "apple", "corn", "maize", "grape",
        "pepper", "cherry", "peach", "strawberry", "squash",
        "raspberry", "soybean", "blueberry", "orange", "rice", "wheat"
    }

    # Check if top 3 predictions disagree on the crop (sign of unknown crop)
    top3_crops = set()
    for i in top3_indices:
        lbl = labels[i].split("___")[0].lower().replace("_", " ")
        top3_crops.add(lbl)

    crop_is_known = plant_name.lower().replace("_", " ") in KNOWN_CROPS
    predictions_disagree = len(top3_crops) >= 3  # all top3 are different crops
    confidence_uncertain = confidence < 85.0

    # If crop looks unknown OR model is very uncertain
    if not crop_is_known or (predictions_disagree and confidence_uncertain):
        # Return "unknown crop" with possible disease suggestions
        possible = [t["label"] for t in top3]
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown crop detected — this crop is not in our training database. "
                f"The AI cannot give a reliable diagnosis. "
                f"Possible disease patterns detected: {', '.join(possible)}. "
                f"Please consult your local agricultural extension officer for this crop."
            )
        )

    # If confidence is between 60-85% — uncertain prediction
    if confidence < 85.0:
        possible = [t["label"] for t in top3]
        raise HTTPException(
            status_code=422,
            detail=(
                f"Low confidence prediction ({confidence:.1f}%) — the AI is not certain enough. "
                f"Possible diseases detected: {', '.join(possible)}. "
                f"Try a clearer, closer photo in good lighting."
            )
        )

    # ── HIGH CONFIDENCE KNOWN CROP ────────────────────────────────
    # Only reach here if: confidence >= 85% AND crop is in training set

    # Look up treatment info
    info = get_disease_info(condition)

    # Generate PDF report
    pdf_filename = generate_pdf_report(
        condition, confidence, plant_name, info,
        farmer.name if farmer else "Guest"
    )

    # Save to database if farmer is logged in
    if farmer:
        scan = Scan(
            farmer_id  = farmer.id,
            plant      = plant_name.replace("_", " "),
            disease    = condition.replace("_", " "),
            confidence = round(confidence, 1),
            status     = info["status"],
            severity   = info["severity"],
            treatment  = info["treatment"],
            chemical   = info["chemical"],
            prevention = info["prevention"],
            pdf_file   = pdf_filename,
        )
        db.add(scan)
        db.commit()

    # Return the full result to the frontend
    return {
        "success":    True,
        "plant":      plant_name.replace("_", " "),
        "disease":    condition.replace("_", " "),
        "confidence": round(confidence, 1),
        "status":     info["status"],
        "severity":   info["severity"],
        "signs":      info.get("signs", ""),
        "treatment":  info["treatment"],
        "chemical":   info["chemical"],
        "prevention": info["prevention"],
        "organic":    info.get("organic", ""),
        "pdf_report": pdf_filename
    }


@app.get("/scans")
def get_scans(farmer: Farmer = Depends(get_current_farmer), db: Session = Depends(get_db)):
    """ Returns all scans for the logged-in farmer, newest first. """
    scans = db.query(Scan)\
               .filter(Scan.farmer_id == farmer.id)\
               .order_by(Scan.scanned_at.desc()).all()
    return [{
        "id": s.id, "plant": s.plant, "disease": s.disease,
        "confidence": s.confidence, "status": s.status, "severity": s.severity,
        "treatment": s.treatment, "chemical": s.chemical, "prevention": s.prevention,
        "pdf": s.pdf_file, "date": s.scanned_at.isoformat()
    } for s in scans]


@app.delete("/scans/{scan_id}")
def delete_scan(scan_id: int, farmer: Farmer = Depends(get_current_farmer),
                db: Session = Depends(get_db)):
    scan = db.query(Scan).filter(Scan.id == scan_id, Scan.farmer_id == farmer.id).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found.")
    db.delete(scan)
    db.commit()
    return {"success": True}


@app.get("/download/{filename}")
def download_report(filename: str):
    """ Serves a PDF report file for download. """
    filepath = os.path.join(PDF_FOLDER, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Report not found.")
    return FileResponse(filepath, media_type="application/pdf", filename=filename)


# ── TASKS / FARM SCHEDULE ─────────────────────────────────

@app.get("/tasks")
def get_tasks(farmer: Farmer = Depends(get_current_farmer), db: Session = Depends(get_db)):
    tasks = db.query(Task)\
               .filter(Task.farmer_id == farmer.id)\
               .order_by(Task.scheduled_date).all()
    today = datetime.utcnow().date().isoformat()
    return [{
        "id": t.id, "title": t.title, "description": t.description,
        "cropName": t.crop_name, "taskType": t.task_type,
        "scheduledDate": t.scheduled_date, "done": t.done,
        "overdue": (not t.done and t.scheduled_date < today),
        "createdAt": t.created_at.isoformat()
    } for t in tasks]


@app.post("/tasks")
def create_task(req: TaskRequest, farmer: Farmer = Depends(get_current_farmer),
                db: Session = Depends(get_db)):
    task = Task(
        farmer_id      = farmer.id,
        title          = req.title,
        description    = req.description,
        crop_name      = req.crop_name,
        task_type      = req.task_type,
        scheduled_date = req.scheduled_date
    )
    db.add(task); db.commit(); db.refresh(task)
    return {"success": True, "id": task.id}


@app.put("/tasks/{task_id}")
def update_task(task_id: int, req: TaskUpdateRequest,
                farmer: Farmer = Depends(get_current_farmer),
                db: Session    = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id, Task.farmer_id == farmer.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    if req.title          is not None: task.title          = req.title
    if req.description    is not None: task.description    = req.description
    if req.crop_name      is not None: task.crop_name      = req.crop_name
    if req.task_type      is not None: task.task_type      = req.task_type
    if req.scheduled_date is not None: task.scheduled_date = req.scheduled_date
    if req.done           is not None: task.done           = req.done
    db.commit()
    return {"success": True}


@app.delete("/tasks/{task_id}")
def delete_task(task_id: int, farmer: Farmer = Depends(get_current_farmer),
                db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id, Task.farmer_id == farmer.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    db.delete(task); db.commit()
    return {"success": True}


# ── INVENTORY ─────────────────────────────────────────────

@app.get("/inventory")
def get_inventory(farmer: Farmer = Depends(get_current_farmer), db: Session = Depends(get_db)):
    items = db.query(InventoryItem).filter(InventoryItem.farmer_id == farmer.id).all()
    return [{
        "id": i.id, "name": i.name, "category": i.category,
        "quantity": i.quantity, "unit": i.unit, "lowAt": i.low_at,
        "cost": i.cost, "supplier": i.supplier,
        "isLow": i.quantity <= i.low_at and i.quantity > 0,
        "isOut": i.quantity == 0,
        "addedAt": i.added_at.isoformat()
    } for i in items]


@app.post("/inventory")
def add_inventory(req: InventoryRequest, farmer: Farmer = Depends(get_current_farmer),
                  db: Session = Depends(get_db)):
    item = InventoryItem(
        farmer_id = farmer.id, name=req.name, category=req.category,
        quantity=req.quantity, unit=req.unit, low_at=req.low_at,
        cost=req.cost, supplier=req.supplier
    )
    db.add(item); db.commit(); db.refresh(item)
    return {"success": True, "id": item.id}


@app.put("/inventory/{item_id}")
def update_inventory(item_id: int, req: InventoryUpdateRequest,
                     farmer: Farmer = Depends(get_current_farmer),
                     db: Session    = Depends(get_db)):
    item = db.query(InventoryItem).filter(
        InventoryItem.id == item_id, InventoryItem.farmer_id == farmer.id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")
    item.quantity = max(0, req.quantity)
    db.commit()
    return {"success": True}


@app.delete("/inventory/{item_id}")
def delete_inventory(item_id: int, farmer: Farmer = Depends(get_current_farmer),
                     db: Session = Depends(get_db)):
    item = db.query(InventoryItem).filter(
        InventoryItem.id == item_id, InventoryItem.farmer_id == farmer.id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")
    db.delete(item); db.commit()
    return {"success": True}


# ── PROFIT & HARVEST ──────────────────────────────────────

@app.get("/profit")
def get_profit(farmer: Farmer = Depends(get_current_farmer), db: Session = Depends(get_db)):
    records = db.query(ProfitRecord)\
                .filter(ProfitRecord.farmer_id == farmer.id)\
                .order_by(ProfitRecord.created_at.desc()).all()
    return [{
        "id": r.id, "type": r.type, "amount": r.amount,
        "category": r.category, "description": r.description,
        "crop": r.crop, "date": r.date,
        "createdAt": r.created_at.isoformat()
    } for r in records]


@app.post("/profit")
def add_profit(req: ProfitRequest, farmer: Farmer = Depends(get_current_farmer),
               db: Session = Depends(get_db)):
    record = ProfitRecord(
        farmer_id=farmer.id, type=req.type, amount=req.amount,
        category=req.category, description=req.description,
        crop=req.crop, date=req.date
    )
    db.add(record); db.commit(); db.refresh(record)
    return {"success": True, "id": record.id}


@app.delete("/profit/{record_id}")
def delete_profit(record_id: int, farmer: Farmer = Depends(get_current_farmer),
                  db: Session = Depends(get_db)):
    record = db.query(ProfitRecord).filter(
        ProfitRecord.id == record_id, ProfitRecord.farmer_id == farmer.id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found.")
    db.delete(record); db.commit()
    return {"success": True}


# ── SIMPLE BOOKKEEPING: BALANCE SHEET ────────────────────────
# Assets = things the farmer owns (cash on hand, inventory value, equipment)
# Liabilities = things the farmer owes (loans, unpaid supplier bills)
# Net Worth = Assets - Liabilities

@app.get("/balance-sheet")
def get_balance_sheet(farmer: Farmer = Depends(get_current_farmer), db: Session = Depends(get_db)):
    items = db.query(BalanceItem)\
              .filter(BalanceItem.farmer_id == farmer.id)\
              .order_by(BalanceItem.created_at.desc()).all()
    return [{
        "id": i.id, "kind": i.kind, "name": i.name,
        "value": i.value, "notes": i.notes,
        "createdAt": i.created_at.isoformat()
    } for i in items]


@app.post("/balance-sheet")
def add_balance_item(req: BalanceItemRequest, farmer: Farmer = Depends(get_current_farmer),
                      db: Session = Depends(get_db)):
    if req.kind not in ("asset", "liability"):
        raise HTTPException(status_code=400, detail="kind must be 'asset' or 'liability'.")
    item = BalanceItem(
        farmer_id=farmer.id, kind=req.kind, name=req.name,
        value=req.value, notes=req.notes
    )
    db.add(item); db.commit(); db.refresh(item)
    return {"success": True, "id": item.id}


@app.delete("/balance-sheet/{item_id}")
def delete_balance_item(item_id: int, farmer: Farmer = Depends(get_current_farmer),
                         db: Session = Depends(get_db)):
    item = db.query(BalanceItem).filter(
        BalanceItem.id == item_id, BalanceItem.farmer_id == farmer.id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")
    db.delete(item); db.commit()
    return {"success": True}


@app.get("/financial-report")
def get_financial_report(farmer: Farmer = Depends(get_current_farmer), db: Session = Depends(get_db)):
    """
    Generates a downloadable PDF financial report (P&L + Balance Sheet)
    covering ALL of the farmer's recorded transactions and balance items.
    Farmers can use this document for grant applications, loan requests,
    or cooperative membership.
    """
    records    = db.query(ProfitRecord).filter(ProfitRecord.farmer_id == farmer.id).all()
    income     = [r for r in records if r.type == "income"]
    expense    = [r for r in records if r.type == "expense"]
    items      = db.query(BalanceItem).filter(BalanceItem.farmer_id == farmer.id).all()
    assets     = [i for i in items if i.kind == "asset"]
    liabilities= [i for i in items if i.kind == "liability"]

    filename = generate_financial_report_pdf(farmer.name, income, expense, assets, liabilities)
    return {"success": True, "filename": filename, "downloadUrl": f"/download/{filename}"}


# ── CROPS ─────────────────────────────────────────────────

@app.get("/crops")
def get_crops(farmer: Farmer = Depends(get_current_farmer), db: Session = Depends(get_db)):
    crops = db.query(Crop).filter(Crop.farmer_id == farmer.id).all()
    return [{
        "id": c.id, "name": c.name, "cropType": c.crop_type,
        "plantDate": c.plant_date, "harvestDays": c.harvest_days,
        "field": c.field, "area": c.area,
        "notes": c.notes or "",
        "createdAt": c.created_at.isoformat()
    } for c in crops]


@app.post("/crops")
def add_crop(req: CropRequest, farmer: Farmer = Depends(get_current_farmer),
             db: Session = Depends(get_db)):
    crop = Crop(
        farmer_id=farmer.id, name=req.name, crop_type=req.crop_type,
        plant_date=req.plant_date, harvest_days=req.harvest_days,
        field=req.field, area=req.area, notes=req.notes or ""
    )
    db.add(crop); db.commit(); db.refresh(crop)
    return {"success": True, "id": crop.id}


@app.delete("/crops/{crop_id}")
def delete_crop(crop_id: int, farmer: Farmer = Depends(get_current_farmer),
                db: Session = Depends(get_db)):
    crop = db.query(Crop).filter(Crop.id == crop_id, Crop.farmer_id == farmer.id).first()
    if not crop:
        raise HTTPException(status_code=404, detail="Crop not found.")
    db.delete(crop); db.commit()
    return {"success": True}


# ── STATS (for dashboard) ─────────────────────────────────

@app.get("/stats")
def get_stats(farmer: Farmer = Depends(get_current_farmer), db: Session = Depends(get_db)):
    """
    Returns a summary of everything for the dashboard:
    scan counts, inventory alerts, profit totals, task counts.
    """
    from collections import defaultdict

    scans     = db.query(Scan).filter(Scan.farmer_id == farmer.id).all()
    inventory = db.query(InventoryItem).filter(InventoryItem.farmer_id == farmer.id).all()
    profits   = db.query(ProfitRecord).filter(ProfitRecord.farmer_id == farmer.id).all()
    tasks     = db.query(Task).filter(Task.farmer_id == farmer.id).all()

    today = datetime.utcnow().date().isoformat()

    # Scans per day for the chart (last 7 days)
    daily_scans: dict = defaultdict(int)
    for s in scans:
        day = s.scanned_at.strftime("%Y-%m-%d")
        daily_scans[day] += 1

    scan_chart = []
    for i in range(6, -1, -1):
        d   = (datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d")
        lbl = (datetime.utcnow() - timedelta(days=i)).strftime("%d %b")
        scan_chart.append({"date": d, "label": lbl, "count": daily_scans.get(d, 0)})

    # Top diseases detected
    disease_counts: dict = defaultdict(int)
    for s in scans:
        if s.status == "diseased":
            disease_counts[s.disease] += 1
    top_diseases = sorted(disease_counts.items(), key=lambda x: -x[1])[:5]

    return {
        "scans": {
            "total":       len(scans),
            "healthy":     sum(1 for s in scans if s.status == "healthy"),
            "diseased":    sum(1 for s in scans if s.status == "diseased"),
            "chart":       scan_chart,
            "topDiseases": [{"name": d, "count": c} for d, c in top_diseases]
        },
        "inventory": {
            "total":    len(inventory),
            "lowStock": sum(1 for i in inventory if i.quantity <= i.low_at and i.quantity > 0),
            "outOfStock": sum(1 for i in inventory if i.quantity == 0)
        },
        "profit": {
            "totalIncome":  sum(r.amount for r in profits if r.type == "income"),
            "totalExpense": sum(r.amount for r in profits if r.type == "expense"),
            "netProfit":    sum(r.amount for r in profits if r.type == "income") -
                            sum(r.amount for r in profits if r.type == "expense")
        },
        "tasks": {
            "total":   len(tasks),
            "pending": sum(1 for t in tasks if not t.done),
            "overdue": sum(1 for t in tasks if not t.done and t.scheduled_date < today),
            "done":    sum(1 for t in tasks if t.done)
        },
        "farmer": {
            "freePeriod":   is_free_period(farmer.registered_at),
            "freeDaysLeft": max(0, 30 - (datetime.utcnow() - farmer.registered_at).days),
            "farmScale":    farmer.farm_scale
        }
    }


# ── GEMINI CHAT PROXY ─────────────────────────────────────
# This endpoint receives a message from the frontend
# and forwards it to Google Gemini API.
# We do this on the backend to avoid CORS browser errors.
# CORS error = browser blocks direct calls to external APIs from localhost.

import urllib.request as urlreq

class ChatRequest(BaseModel):
    message:       str
    history:       Optional[list] = []
    system_prompt: Optional[str]  = ""
    gemini_key:    str

@app.post("/chat")
async def chat(req: ChatRequest, farmer: Farmer = Depends(get_current_farmer)):
    """
    Forwards a message to Google Gemini AI and returns the reply.
    The farmer sends their question, we pass it to Gemini, return the answer.
    """
    try:
        # Build the conversation history for Gemini
        contents = []

        # Add previous messages (so AI remembers context)
        for msg in req.history:
            contents.append(msg)

        # Add the new message
        contents.append({
            "role": "user",
            "parts": [{"text": req.message}]
        })

        # Build the request body for Gemini
        body = {
            "system_instruction": {
                "parts": [{"text": req.system_prompt}]
            },
            "contents": contents,
            "generationConfig": {
                "temperature":     0.7,
                "maxOutputTokens": 600,
                "topP":            0.8
            }
        }

        # Gemini API URL
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={req.gemini_key}"

        # Make the HTTP request to Gemini
        import json as json_lib
        body_bytes = json_lib.dumps(body).encode("utf-8")
        request    = urlreq.Request(
            url,
            data    = body_bytes,
            headers = {"Content-Type": "application/json"},
            method  = "POST"
        )

        with urlreq.urlopen(request, timeout=30) as response:
            result = json_lib.loads(response.read().decode("utf-8"))

        # Extract the reply text
        reply = result["candidates"][0]["content"]["parts"][0]["text"]
        return {"success": True, "reply": reply}

    except urlreq.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else str(e)
        raise HTTPException(
            status_code=502,
            detail=f"Gemini API error {e.code}: {error_body[:200]}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"AI connection failed: {str(e)}"
        )


# ═══════════════════════════════════════════════════════════
#  FORGOT PASSWORD SYSTEM
#  Uses Gmail SMTP (free) to send a 6-digit reset code to the
#  farmer's email address. The code expires after 15 minutes.
# ═══════════════════════════════════════════════════════════

import smtplib
import random
import json
import urllib.request
import urllib.error
from email.mime.text import MIMEText

# ── EMAIL SETTINGS (Brevo HTTP API — works on Railway) ───────
# Railway BLOCKS outbound SMTP ports, so we send email over a normal
# HTTPS request (port 443) using Brevo's API instead. Emails can still
# show your Gmail address as the sender (verify it in Brevo first).
#
# Set these in Railway Variables:
#   BREVO_API_KEY    = your Brevo API key (starts with "xkeysib-...")
#   EMAIL_FROM       = harunmuriithi542@gmail.com   (verified sender in Brevo)
#   EMAIL_FROM_NAME  = AgroTech Kenya
BREVO_API_KEY   = os.getenv("BREVO_API_KEY", "")
EMAIL_FROM      = os.getenv("EMAIL_FROM", "harunmuriithi542@gmail.com")
EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "AgroTech Kenya")


def _send_email(to_email: str, subject: str, body: str) -> bool:
    """
    Sends an email through the Brevo HTTP API over HTTPS (port 443).
    Returns True on success, False on failure. Works on Railway because
    it does NOT use SMTP (which Railway blocks).
    """
    if not BREVO_API_KEY:
        logger.error("BREVO_API_KEY is not set — cannot send email to %s", to_email)
        return False

    payload = json.dumps({
        "sender": {"name": EMAIL_FROM_NAME, "email": EMAIL_FROM},
        "to": [{"email": to_email}],
        "subject": subject,
        "textContent": body,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=payload,
        method="POST",
        headers={
            "api-key": BREVO_API_KEY,
            "content-type": "application/json",
            "accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            logger.info("Email sent to %s (HTTP %s)", to_email, resp.status)
            return True
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode("utf-8", "ignore")[:300]
        logger.error("Failed to send email to %s: HTTP %s %s", to_email, e.code, body_txt)
        return False
    except Exception as e:
        logger.error("Failed to send email to %s: %s", to_email, e)
        return False


def send_reset_email(to_email: str, code: str, name: str):
    """Sends a 6-digit password-reset code to the farmer's email."""
    subject = "AgroTech — Your Password Reset Code"
    body = f"""Hello {name},

You requested to reset your AgroTech password.

Your verification code is:

    {code}

This code expires in 15 minutes.

If you did not request this, you can safely ignore this email.

— AgroTech Team
Smart Farming Platform · Kenya
"""
    _send_email(to_email, subject, body)


@app.get("/test-email")
def test_email(to: str, secret: str = ""):
    """
    Quick check that email sending works.
    Visit:  /test-email?to=YOUR_EMAIL&secret=YOUR_SECRET
    Set TEST_EMAIL_SECRET in Railway Variables to enable it.
    Returns {"sent": true} on success — the Logs tab shows full details.
    """
    expected = os.getenv("TEST_EMAIL_SECRET", "")
    if not expected or secret != expected:
        raise HTTPException(status_code=403, detail="Forbidden")
    ok = _send_email(
        to,
        "AgroTech — Test Email",
        "This is a test email from AgroTech. If you received it, email sending works correctly!"
    )
    return {"sent": ok, "to": to}


class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    email:        str
    code:         str
    new_password: str


@app.post("/auth/forgot-password")
def forgot_password(req: ForgotPasswordRequest, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    rate_limit(request, "forgot", max_calls=4, window_sec=60)
    """
    Step 1 of password reset.
    Farmer enters their email. We check if it exists and send a code.
    We now return a clear error if the email is not registered,
    so the farmer knows to check their spelling or use a different email.
    """
    email = req.email.strip().lower()
    farmer = db.query(Farmer).filter(Farmer.email == email).first()

    # If email not found — tell the farmer clearly
    if not farmer:
        raise HTTPException(
            status_code=404,
            detail="No account found with this email address. "
                   "Please check your spelling, or register a new account."
        )

    # If farmer registered without adding an email
    if not farmer.email:
        raise HTTPException(
            status_code=400,
            detail="This account has no email address saved. "
                   "Please contact support to reset your password."
        )

    # Generate a random 6-digit code
    code = str(random.randint(100000, 999999))

    farmer.reset_code    = code
    farmer.reset_expires = datetime.utcnow() + timedelta(minutes=15)
    db.commit()

    # Send the email in the BACKGROUND so the app responds instantly.
    # The farmer no longer waits for Gmail's SMTP server to finish.
    background.add_task(send_reset_email, farmer.email, code, farmer.name)

    return {
        "success": True,
        "message": "Reset code sent! Check your email inbox and spam folder."
    }


@app.post("/auth/reset-password")
def reset_password(req: ResetPasswordRequest, db: Session = Depends(get_db)):
    """
    Step 2 of password reset.
    Farmer enters the 6-digit code from their email + a new password.
    If the code is correct and not expired, the password is updated.
    """
    email = req.email.strip().lower()
    farmer = db.query(Farmer).filter(Farmer.email == email).first()

    if not farmer or not farmer.reset_code:
        raise HTTPException(status_code=400, detail="Invalid or expired reset code.")

    if farmer.reset_code != req.code.strip():
        raise HTTPException(status_code=400, detail="Incorrect reset code. Please check and try again.")

    if not farmer.reset_expires or datetime.utcnow() > farmer.reset_expires:
        raise HTTPException(status_code=400, detail="This reset code has expired. Please request a new one.")

    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters.")

    # Update password and clear the reset code (one-time use)
    farmer.password_hash = hash_password(req.new_password)
    farmer.reset_code     = None
    farmer.reset_expires  = None
    db.commit()

    return {"success": True, "message": "Password updated successfully! You can now log in with your new password."}


# ═══════════════════════════════════════════════════════════
#  ADMIN DASHBOARD ENDPOINTS
#  Only accounts whose email is listed in ADMIN_EMAILS can use
#  these. Set ADMIN_EMAILS in Railway Variables (comma-separated).
# ═══════════════════════════════════════════════════════════
import collections as _collections

import hashlib as _hashlib

# ── ADMIN CREDENTIALS ────────────────────────────────────
# A DEDICATED admin username + password, completely separate
# from farmer accounts. You choose them yourself in Railway
# Variables (so you can see/set the password):
#   ADMIN_USERNAME = admin
#   ADMIN_PASSWORD = (a strong password you pick)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")


def _expected_admin_token() -> str:
    """A stable token derived from the admin credentials (no DB needed)."""
    raw = "agroadmin:" + ADMIN_USERNAME + ":" + ADMIN_PASSWORD
    return _hashlib.sha256(raw.encode()).hexdigest()

# Free-trial length in days (matches the app's 30-day trial).
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "30"))


def _trial_days_left(registered_at):
    """Days remaining in the trial. Zero or negative = already expired."""
    if not registered_at:
        return TRIAL_DAYS
    used = (datetime.utcnow() - registered_at).days
    return TRIAL_DAYS - used


def _trial_status(days_left):
    if days_left <= 0:  return "expired"
    if days_left <= 7:  return "expiring"
    return "active"


class AdminLoginRequest(BaseModel):
    username: str
    password: str


@app.post("/admin/login")
def admin_login(req: AdminLoginRequest, request: Request):
    """Dedicated admin login — separate from farmer accounts."""
    rate_limit(request, "admin_login", max_calls=10, window_sec=60)
    if not ADMIN_USERNAME or not ADMIN_PASSWORD:
        raise HTTPException(status_code=503,
            detail="Admin login is not set up yet. Add ADMIN_USERNAME and ADMIN_PASSWORD in Railway.")
    if req.username.strip() == ADMIN_USERNAME and req.password == ADMIN_PASSWORD:
        return {"success": True, "token": _expected_admin_token()}
    raise HTTPException(status_code=401, detail="Wrong admin username or password.")


def require_admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Protects admin endpoints using the dedicated admin token."""
    if not ADMIN_PASSWORD:
        raise HTTPException(status_code=503, detail="Admin login is not configured.")
    if not credentials or credentials.credentials != _expected_admin_token():
        raise HTTPException(status_code=401, detail="Admin authentication required.")
    return True


@app.get("/admin/overview")
def admin_overview(_admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    """High-level numbers for the admin dashboard."""
    now         = datetime.utcnow()
    today_start = datetime(now.year, now.month, now.day)
    week_ago    = now - timedelta(days=7)
    month_ago   = now - timedelta(days=30)

    total_farmers = db.query(Farmer).count()
    total_scans   = db.query(Scan).count()
    total_tasks   = db.query(Task).count()
    total_items   = db.query(InventoryItem).count()
    total_crops   = db.query(Crop).count()

    small = db.query(Farmer).filter(Farmer.farm_scale == "small").count()
    large = db.query(Farmer).filter(Farmer.farm_scale == "large").count()

    signups_today = db.query(Farmer).filter(Farmer.registered_at >= today_start).count()
    signups_week  = db.query(Farmer).filter(Farmer.registered_at >= week_ago).count()
    signups_month = db.query(Farmer).filter(Farmer.registered_at >= month_ago).count()

    healthy  = db.query(Scan).filter(Scan.status == "healthy").count()
    diseased = total_scans - healthy

    # Trial status counts (computed from each farmer's registration date)
    trial_active = trial_expiring = trial_expired = 0
    for (reg,) in db.query(Farmer.registered_at).all():
        st = _trial_status(_trial_days_left(reg))
        if   st == "expired":  trial_expired  += 1
        elif st == "expiring": trial_expiring += 1
        else:                  trial_active   += 1

    rows    = db.query(Scan.disease).filter(Scan.status != "healthy").all()
    counter = _collections.Counter([r[0] for r in rows if r[0]])
    top_diseases = [{"disease": d, "count": c} for d, c in counter.most_common(8)]

    recent = (db.query(Scan, Farmer.name)
                .join(Farmer, Scan.farmer_id == Farmer.id)
                .order_by(Scan.scanned_at.desc())
                .limit(10).all())
    recent_scans = [{
        "farmer":     name,
        "plant":      s.plant,
        "disease":    s.disease,
        "confidence": round(s.confidence or 0, 1),
        "status":     s.status,
        "date":       s.scanned_at.strftime("%Y-%m-%d %H:%M") if s.scanned_at else ""
    } for s, name in recent]

    return {
        "totals":      {"farmers": total_farmers, "scans": total_scans,
                        "tasks": total_tasks, "inventory": total_items, "crops": total_crops},
        "scale":       {"small": small, "large": large},
        "signups":     {"today": signups_today, "week": signups_week, "month": signups_month},
        "scan_health": {"healthy": healthy, "diseased": diseased},
        "trials":      {"active": trial_active, "expiring": trial_expiring, "expired": trial_expired},
        "top_diseases": top_diseases,
        "recent_scans": recent_scans,
    }


@app.get("/admin/farmers")
def admin_farmers(_admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    """Full list of farmers (no passwords/tokens exposed)."""
    farmers = db.query(Farmer).order_by(Farmer.registered_at.desc()).all()
    out = []
    for f in farmers:
        scan_count = db.query(Scan).filter(Scan.farmer_id == f.id).count()
        days_left  = _trial_days_left(f.registered_at)
        out.append({
            "id":           f.id,
            "name":         f.name,
            "phone":        f.phone,
            "email":        f.email,
            "county":       f.county,
            "scale":        f.farm_scale,
            "farm_size":    f.farm_size,
            "scans":        scan_count,
            "registered":   f.registered_at.strftime("%Y-%m-%d") if f.registered_at else "",
            "days_left":    days_left,
            "trial_status": _trial_status(days_left),
        })
    return out
