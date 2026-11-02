import html
import io
import json
import os
import re
import secrets
import threading
import time
import uuid
import zipfile
from datetime import datetime
from typing import Any, List

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

try:
    import fitz
except ImportError:
    fitz = None

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None


app = FastAPI(title="Mahajan IT Printing Hub Portal")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploaded_files")
ORDERS_FILE = os.path.join(BASE_DIR, "orders.json")
MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_FILES = 10
DUPLICATE_FILE_MESSAGE = "একই নামে একাধিক ফাইল আপলোড করা যাবে না।"
FILE_LIMIT_MESSAGE = "একসাথে ১০টার বেশি ফাইল ও ২০০ এমবির বেশি ফাইল আপলোড করা যাবে না।"
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "password123")

os.makedirs(UPLOAD_DIR, exist_ok=True)
if not os.path.exists(ORDERS_FILE):
    with open(ORDERS_FILE, "w", encoding="utf-8") as orders_file:
        json.dump([], orders_file)

PRINT_RATES = {
    "A4": {
        65: {"bw_single": 1.20, "bw_double": 1.40, "color_single": 1.50, "color_double": 1.70},
        70: {"bw_single": 1.30, "bw_double": 1.50, "color_single": 1.60, "color_double": 1.80},
        80: {"bw_single": 1.50, "bw_double": 1.70, "color_single": 1.80, "color_double": 2.00},
        100: {"bw_single": 1.50, "bw_double": 1.80, "color_single": 2.00, "color_double": 2.20},
    },
    "Legal": {
        70: {"bw_single": 1.50, "bw_double": 1.80, "color_single": 2.00, "color_double": 2.20},
        80: {"bw_single": 1.80, "bw_double": 2.00, "color_single": 2.20, "color_double": 2.50},
        100: {"bw_single": 2.10, "bw_double": 2.20, "color_single": 2.40, "color_double": 2.70},
    },
}
BINDING_RATES = {"pinning": 0, "hardcover": 150, "pvc": 25}
DELIVERY_RATES = {"pickup": 0, "dhaka": 60, "outside_dhaka": 120}
ALLOWED_SIZES = set(PRINT_RATES)
ALLOWED_COLOR_TYPES = {"bw", "color"}
ALLOWED_SIDES = {"single", "double"}
ALLOWED_BINDINGS = set(BINDING_RATES) | {"spiral", "none", "staple"}
ALLOWED_DELIVERY = set(DELIVERY_RATES)
ALLOWED_PAYMENT_METHODS = {"bkash", "nagad", "rocket", "cellfin", "cod"}
ORDER_STATUSES = [
    "PENDING/VERIFICATION",
    "Printing in Progress",
    "Binding & Finishing",
    "Ready for Pickup",
    "Delivered",
]
LEGACY_STATUS_MAP = {
    "received": "PENDING/VERIFICATION",
    "order received": "PENDING/VERIFICATION",
}
temp_file_store: dict[str, dict[str, Any]] = {}
admin_security = HTTPBasic(realm="Mahajan IT Printing Hub Admin")
checkout_attempts: dict[str, list[float]] = {}
checkout_lock = threading.Lock()
orders_lock = threading.Lock()
PHONE_PATTERN = re.compile(r"^01[3-9]\d{8}$")
TRX_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{3,63}$")


def read_orders() -> list[dict[str, Any]]:
    try:
        with open(ORDERS_FILE, "r", encoding="utf-8") as orders_file:
            data = json.load(orders_file)
        if not isinstance(data, list):
            return []
        changed = False
        for order in data:
            current_status = order.get("status", "PENDING/VERIFICATION")
            normalized_status = LEGACY_STATUS_MAP.get(current_status, current_status)
            if normalized_status not in ORDER_STATUSES:
                normalized_status = "PENDING/VERIFICATION"
            if order.get("status") != normalized_status:
                order["status"] = normalized_status
                changed = True
        if changed:
            write_orders(data)
        return data
    except (OSError, json.JSONDecodeError):
        return []


def write_orders(orders: list[dict[str, Any]]) -> None:
    with open(ORDERS_FILE, "w", encoding="utf-8") as orders_file:
        json.dump(orders, orders_file, ensure_ascii=False, indent=2)


def require_admin(credentials: HTTPBasicCredentials = Depends(admin_security)) -> str:
    username_ok = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    password_ok = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect admin username or password.",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def sorted_orders() -> list[dict[str, Any]]:
    return sorted(
        read_orders(),
        key=lambda order: str(order.get("timestamp", "")),
        reverse=True,
    )


def count_pdf_pages(contents: bytes) -> int:
    if fitz is not None:
        try:
            document = fitz.open(stream=contents, filetype="pdf")
            page_count = document.page_count
            document.close()
            return page_count
        except Exception:
            pass
    if PdfReader is not None:
        try:
            return len(PdfReader(io.BytesIO(contents)).pages)
        except Exception:
            pass
    raise HTTPException(status_code=400, detail="অবৈধ বা ক্ষতিগ্রস্ত PDF ফাইল।")


def validate_options(
    paper_size: str, color_type: str, print_side: str, gsm: int, binding: str, delivery_option: str
) -> None:
    if paper_size not in ALLOWED_SIZES:
        raise HTTPException(status_code=400, detail="A4 অথবা Legal সাইজ নির্বাচন করুন।")
    if color_type not in ALLOWED_COLOR_TYPES or print_side not in ALLOWED_SIDES:
        raise HTTPException(status_code=400, detail="প্রিন্ট মোডের তথ্য সঠিক নয়।")
    if gsm not in PRINT_RATES[paper_size]:
        raise HTTPException(status_code=400, detail="এই paper size-এর জন্য GSM অপশন সঠিক নয়।")
    if binding not in ALLOWED_BINDINGS:
        raise HTTPException(status_code=400, detail="বাইন্ডিং অপশন সঠিক নয়।")
    if delivery_option not in ALLOWED_DELIVERY:
        raise HTTPException(status_code=400, detail="ডেলিভারি অপশন সঠিক নয়।")


def validate_upload_batch(files: List[UploadFile]) -> None:
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=413, detail=FILE_LIMIT_MESSAGE)

    file_names = [os.path.basename(item.filename or "").casefold() for item in files]
    if len(file_names) != len(set(file_names)):
        raise HTTPException(status_code=400, detail=DUPLICATE_FILE_MESSAGE)


def spiral_binding_cost(page_count: int) -> int:
    if page_count <= 100:
        return 70
    if page_count <= 200:
        return 100
    return 180


def calculate_binding_cost(binding: str, page_count: int) -> int:
    if binding in {"none", "staple", "pinning"}:
        return 0
    if binding == "spiral":
        return spiral_binding_cost(page_count)
    return BINDING_RATES[binding]


def enforce_checkout_rate_limit(client_ip: str) -> None:
    now = time.monotonic()
    with checkout_lock:
        recent = [attempt for attempt in checkout_attempts.get(client_ip, []) if now - attempt < 300]
        if len(recent) >= 5:
            raise HTTPException(status_code=429, detail="Too many payment submissions. Try again in a few minutes.")
        recent.append(now)
        checkout_attempts[client_ip] = recent


def validate_customer_fields(phone: str, trx_id: str, payment_method: str) -> tuple[str, str]:
    normalized_phone = re.sub(r"[\s-]", "", phone)
    normalized_trx_id = trx_id.strip()
    if not PHONE_PATTERN.fullmatch(normalized_phone):
        raise HTTPException(status_code=400, detail="সঠিক বাংলাদেশি মোবাইল নম্বর দিন।")
    if payment_method != "cod" and not TRX_ID_PATTERN.fullmatch(normalized_trx_id):
        raise HTTPException(status_code=400, detail="TrxID-তে 4-64টি অক্ষর, সংখ্যা, dot, dash বা underscore ব্যবহার করুন।")
    return normalized_phone, normalized_trx_id


@app.post("/api/calculate")
async def calculate_price(
    files: List[UploadFile] = File(...),
    paper_size: str = Form("A4"),
    color_type: str = Form("bw"),
    print_side: str = Form("single"),
    gsm: int = Form(80),
    binding: str = Form("pinning"),
    delivery_option: str = Form("pickup"),
    copies: int = Form(1),
):
    if not files:
        raise HTTPException(status_code=400, detail="কমপক্ষে একটি PDF ফাইল আপলোড করুন।")
    validate_upload_batch(files)
    if copies < 1 or copies > 100:
        raise HTTPException(status_code=400, detail="Copies 1 থেকে 100-এর মধ্যে হতে হবে।")
    if any(not item.filename or not item.filename.lower().endswith(".pdf") for item in files):
        raise HTTPException(status_code=400, detail="শুধুমাত্র PDF ফাইল আপলোড করুন।")

    validate_options(paper_size, color_type, print_side, gsm, binding, delivery_option)
    uploaded_file_data = []
    combined_size = 0
    total_pages = 0
    for uploaded_file in files:
        contents = await uploaded_file.read()
        combined_size += len(contents)
        if combined_size > MAX_FILE_BYTES:
            break
        page_count = count_pdf_pages(contents)
        total_pages += page_count
        uploaded_file_data.append({
            "file_name": os.path.basename(uploaded_file.filename),
            "contents": contents,
            "page_count": page_count,
            "size_bytes": len(contents),
        })

    if combined_size > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail=FILE_LIMIT_MESSAGE)
    if total_pages < 1:
        raise HTTPException(status_code=400, detail="PDF ফাইলগুলোতে কোনো পেজ পাওয়া যায়নি।")

    rate_key = f"{color_type}_{print_side}"
    unit_price = PRINT_RATES[paper_size][gsm][rate_key]
    total_sheets = (total_pages + 1) // 2 if print_side == "double" else total_pages
    print_cost = total_pages * unit_price * copies
    binding = {"none": "pinning", "staple": "pinning"}.get(binding, binding)
    binding_cost_for_order = calculate_binding_cost(binding, total_pages)
    delivery_cost = DELIVERY_RATES[delivery_option]
    grand_total = print_cost + binding_cost_for_order + delivery_cost

    session_id = str(uuid.uuid4())
    temp_file_store[session_id] = {
        "files": uploaded_file_data,
        "details": {
            "paper_size": paper_size,
            "color_type": color_type,
            "print_side": print_side,
            "gsm": gsm,
            "binding": binding,
            "delivery_option": delivery_option,
            "page_count": total_pages,
            "total_sheets": total_sheets,
            "copies": copies,
            "file_count": len(uploaded_file_data),
            "print_cost": round(print_cost, 2),
            "binding_cost": round(binding_cost_for_order, 2),
            "delivery_cost": round(delivery_cost, 2),
            "grand_total": round(grand_total, 2),
        },
    }

    return {
        "status": "success",
        "session_id": session_id,
        "files": [
            {
                "file_name": item["file_name"],
                "page_count": item["page_count"],
                "size_bytes": item["size_bytes"],
            }
            for item in uploaded_file_data
        ],
        **temp_file_store[session_id]["details"],
    }


@app.post("/api/checkout")
async def process_checkout(
    request: Request,
    session_id: str = Form(""),
    customer_name: str = Form(...),
    customer_phone: str = Form(...),
    address: str = Form(...),
    area: str = Form(""),
    instructions: str = Form(""),
    payment_method: str = Form(...),
    trx_id: str = Form(""),
    amount: float = Form(...),
):
    enforce_checkout_rate_limit(request.client.host if request.client else "unknown")
    customer_name = customer_name.strip()
    customer_phone = customer_phone.strip()
    address = address.strip()
    if not customer_name or not customer_phone or not address:
        raise HTTPException(status_code=400, detail="নাম, ফোন নম্বর এবং বিস্তারিত ঠিকানা দিন।")
    if payment_method not in ALLOWED_PAYMENT_METHODS:
        raise HTTPException(status_code=400, detail="Payment method সঠিক নয়।")
    if session_id not in temp_file_store:
        raise HTTPException(status_code=400, detail="অর্ডার সেশনটি পাওয়া যায়নি। PDF আবার আপলোড করুন।")

    customer_phone, trx_id = validate_customer_fields(customer_phone, trx_id, payment_method)

    session_data = temp_file_store[session_id]
    expected_amount = float(session_data["details"]["grand_total"])
    if abs(float(amount) - expected_amount) > 0.01:
        raise HTTPException(status_code=400, detail="অর্ডারের মোট বিল পরিবর্তিত হয়েছে। আবার হিসাব করুন।")

    with orders_lock:
        existing_trx_ids = {str(item.get("trx_id", "")).casefold() for item in read_orders() if item.get("trx_id")}
        if trx_id and trx_id.casefold() in existing_trx_ids:
            raise HTTPException(status_code=409, detail="এই TrxID ইতিমধ্যে ব্যবহার করা হয়েছে।")

        order_id = f"MJ-{uuid.uuid4().hex[:6].upper()}"
        saved_filenames = []
        for file_index, uploaded_file in enumerate(session_data["files"], start=1):
            saved_filename = f"{order_id}_{file_index}_{uploaded_file['file_name']}"
            with open(os.path.join(UPLOAD_DIR, saved_filename), "wb") as saved_file:
                saved_file.write(uploaded_file["contents"])
            saved_filenames.append(saved_filename)

        order_entry = {
            "order_id": order_id,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "customer_name": customer_name,
            "customer_phone": customer_phone,
            "address": address,
            "area": area.strip(),
            "instructions": instructions.strip(),
            "payment_method": payment_method,
            "trx_id": trx_id,
            "amount": expected_amount,
            "status": "PENDING/VERIFICATION",
            "file_name": saved_filenames[0],
            "file_names": saved_filenames,
            "details": {
                **session_data["details"],
                "files": [
                    {
                        "file_name": uploaded_file["file_name"],
                        "page_count": uploaded_file["page_count"],
                    }
                    for uploaded_file in session_data["files"]
                ],
            },
        }
        orders = read_orders()
        orders.insert(0, order_entry)
        write_orders(orders)
        temp_file_store.pop(session_id, None)

    return {
        "status": "success",
        "order_id": order_id,
        "amount": expected_amount,
        "message": f"ধন্যবাদ {customer_name}! আপনার অর্ডারটি সফলভাবে গ্রহণ করা হয়েছে।",
    }


@app.get("/api/orders/track/{order_id}")
@app.get("/api/track/{order_id}")
async def track_order(order_id: str):
    order = next((item for item in read_orders() if item.get("order_id") == order_id.strip().upper()), None)
    if not order:
        raise HTTPException(status_code=404, detail="এই Order ID-এর কোনো অর্ডার পাওয়া যায়নি।")
    return {
        "status": "success",
        "order_id": order["order_id"],
        "status_code": order.get("status", "PENDING/VERIFICATION"),
        "status_label": order.get("status", "PENDING/VERIFICATION"),
        "timestamp": order.get("timestamp"),
        "amount": order.get("amount", 0),
        "customer_name": order.get("customer_name", ""),
        "paper_size": order.get("details", {}).get("paper_size"),
        "page_count": order.get("details", {}).get("page_count"),
    }


class OrderStatusUpdate(BaseModel):
    order_id: str
    status: str


class StatusPayload(BaseModel):
    status: str


def normalize_status(value: str) -> str:
    aliases = {
        "received": "PENDING/VERIFICATION",
        "printing": "Printing in Progress",
        "completed": "Ready for Pickup",
        "delivered": "Delivered",
    }
    return aliases.get(value.strip().lower(), value.strip())


def save_order_status(order_id: str, requested_status: str) -> dict[str, str]:
    if requested_status not in ORDER_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid order status.")

    orders = read_orders()
    order = next((item for item in orders if item.get("order_id") == order_id), None)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")

    order["status"] = requested_status
    order["status_updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    write_orders(orders)
    return {
        "status": "success",
        "order_id": order_id,
        "order_status": requested_status,
        "updated_at": order["status_updated_at"],
    }


@app.post("/api/admin/order/{order_id}/status")
async def update_order_status(
    order_id: str,
    payload: StatusPayload,
    _: str = Depends(require_admin),
):
    return save_order_status(order_id.strip().upper(), normalize_status(payload.status))


@app.post("/api/admin/orders/update-status")
async def update_order_status_legacy(
    payload: OrderStatusUpdate,
    _: str = Depends(require_admin),
):
    return save_order_status(payload.order_id.strip().upper(), normalize_status(payload.status))


@app.get("/api/admin/orders")
async def admin_orders(_: str = Depends(require_admin)):
    return {"status": "success", "orders": sorted_orders()}


def get_order_file_records(order: dict[str, Any]) -> list[dict[str, str]]:
    stored_names = order.get("file_names") or ([order.get("file_name")] if order.get("file_name") else [])
    stored_names = [os.path.basename(name) for name in stored_names if name and name != "N/A"]
    original_files = (order.get("details") or {}).get("files") or []
    records = []
    for file_index, stored_name in enumerate(stored_names):
        original_name = ""
        if file_index < len(original_files) and isinstance(original_files[file_index], dict):
            original_name = os.path.basename(original_files[file_index].get("file_name") or "")
        records.append({"stored_name": stored_name, "original_name": original_name or stored_name})
    return records


@app.get("/admin/orders/{order_id}/file/{file_index}")
@app.get("/admin/orders/{order_id}/download-file/{file_index}")
async def download_order_file(order_id: str, file_index: int, _: str = Depends(require_admin)):
    normalized_order_id = order_id.strip().upper()
    order = next((item for item in read_orders() if item.get("order_id") == normalized_order_id), None)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    file_records = get_order_file_records(order)
    if file_index < 0 or file_index >= len(file_records):
        raise HTTPException(status_code=404, detail="File not found for this order")

    file_record = file_records[file_index]
    file_path = os.path.join(UPLOAD_DIR, file_record["stored_name"])
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=file_path, filename=file_record["original_name"], media_type="application/pdf")


@app.get("/admin/orders/{order_id}/download-zip")
async def download_order_zip(order_id: str, _: str = Depends(require_admin)):
    normalized_order_id = order_id.strip().upper()
    order = next((item for item in read_orders() if item.get("order_id") == normalized_order_id), None)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    file_records = get_order_file_records(order)
    if not file_records:
        raise HTTPException(status_code=404, detail="No files found for this order")
    if len(file_records) <= 1:
        raise HTTPException(status_code=400, detail="ZIP download requires more than one file")

    file_paths = [os.path.join(UPLOAD_DIR, record["stored_name"]) for record in file_records]
    if any(not os.path.isfile(file_path) for file_path in file_paths):
        raise HTTPException(status_code=404, detail="One or more order files are missing")

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for file_path, record in zip(file_paths, file_records):
            zip_file.write(file_path, arcname=record["original_name"])
    archive.seek(0)
    safe_customer_name = re.sub(r"\s+", "_", str(order.get("customer_name", "Customer")).strip())
    safe_customer_name = re.sub(r"[^A-Za-z0-9_-]", "", safe_customer_name) or "Customer"
    safe_order_id = re.sub(r"[^A-Za-z0-9_-]", "", normalized_order_id) or "Order"
    download_name = f"{safe_customer_name}_{safe_order_id}.zip"
    return StreamingResponse(
        iter([archive.getvalue()]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )


@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(_: str = Depends(require_admin)):
    with open(os.path.join(BASE_DIR, "static", "admin.html"), "r", encoding="utf-8") as admin_file:
        return HTMLResponse(content=admin_file.read())


@app.get("/api/admin/download/{filename}")
async def admin_download_file(filename: str, _: str = Depends(require_admin)):
    safe_name = os.path.basename(filename)
    file_path = os.path.join(UPLOAD_DIR, safe_name)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=file_path, filename=safe_name, media_type="application/pdf")


@app.get("/download/{file_name}")
async def download_file(file_name: str, _: str = Depends(require_admin)):
    safe_name = os.path.basename(file_name)
    file_path = os.path.join(UPLOAD_DIR, safe_name)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=file_path, filename=safe_name, media_type="application/pdf")


app.mount("/", StaticFiles(directory=os.path.join(BASE_DIR, "static"), html=True), name="static")
