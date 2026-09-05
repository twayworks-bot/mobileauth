import os
import urllib.request
import urllib.parse
import urllib.error
import json
import ssl
import hashlib

try:
    import bcrypt
    HAS_BCRYPT = True
except ImportError:
    HAS_BCRYPT = False

# Setup unverified SSL context just in case
SSL_CONTEXT = ssl._create_unverified_context()
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Load environment variables
def load_env(file_path=".env"):
    env_vars = {}
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    env_vars[key.strip()] = val.strip()
    
    # Overlay system environment variables for docker compatibility
    for k, v in os.environ.items():
        if k.startswith("KEYCLOAK_"):
            env_vars[k] = v
    return env_vars

ENV = load_env(".env")
BASE_URL = ENV.get("KEYCLOAK_BASE_URL", "https://auth.thewayworks.net").rstrip("/")
TARGET_REALM = ENV.get("KEYCLOAK_TARGET_REALM", "holyseeds")
ADMIN_TOKEN = ENV.get("KEYCLOAK_ADMIN_TOKEN")

ACTIVE_ACCESS_TOKEN = None

def request_api_direct(token, method, path, body=None):
    """Helper to make HTTP requests with a specific token directly (avoids recursion)."""
    url = f"{BASE_URL}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT
    }
    
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
        
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req, context=SSL_CONTEXT) as response:
            status = response.status
            headers_res = dict(response.info())
            res_body = response.read().decode("utf-8")
            
            res_data = None
            if res_body:
                try:
                    res_data = json.loads(res_body)
                except Exception:
                    res_data = res_body
            return status, headers_res, res_data
            
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        try:
            err_data = json.loads(err_body)
        except Exception:
            err_data = err_body
        return e.code, dict(e.headers), err_data
    except Exception as e:
        return None, {}, str(e)

def resolve_active_token():
    """Resolves a valid access token. Exchanges offline refresh token if access token is expired."""
    global ACTIVE_ACCESS_TOKEN
    if ACTIVE_ACCESS_TOKEN:
        return ACTIVE_ACCESS_TOKEN
        
    if not ADMIN_TOKEN:
        return None
        
    # 1. Check if ADMIN_TOKEN is valid directly as an Access Token
    status, _, _ = request_api_direct(ADMIN_TOKEN, "GET", f"/admin/realms/{TARGET_REALM}/users/profile")
    if status == 200:
        ACTIVE_ACCESS_TOKEN = ADMIN_TOKEN
        return ACTIVE_ACCESS_TOKEN
        
    # 2. If expired/unauthorized (401), treat ADMIN_TOKEN as an Offline Refresh Token and exchange it!
    token_url = f"/realms/master/protocol/openid-connect/token"
    print("[*] KeycloakAPI: KEYCLOAK_ADMIN_TOKEN is expired or is a Refresh Token. Attempting dynamic exchange...")
    
    exchange_payload = {
        "grant_type": "refresh_token",
        "client_id": "admin-cli",
        "refresh_token": ADMIN_TOKEN
    }
    encoded_payload = urllib.parse.urlencode(exchange_payload).encode("utf-8")
    
    req_exchange = urllib.request.Request(
        f"{BASE_URL}{token_url}",
        data=encoded_payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": USER_AGENT
        }
    )
    
    try:
        with urllib.request.urlopen(req_exchange, context=SSL_CONTEXT) as response:
            res_json = json.loads(response.read().decode("utf-8"))
            new_access_token = res_json.get("access_token")
            if new_access_token:
                print(" -> [SUCCESS] Exchanged long-lived offline token for a fresh short-lived Access Token!")
                ACTIVE_ACCESS_TOKEN = new_access_token
                return ACTIVE_ACCESS_TOKEN
    except Exception as e:
        print(f" -> [FAILED] Token exchange failed: {e}")
        
    # Fallback to configured token if exchange fails
    ACTIVE_ACCESS_TOKEN = ADMIN_TOKEN
    return ACTIVE_ACCESS_TOKEN

def request_api(method, path, body=None):
    """Helper to make HTTP requests with the dynamically resolved active access token. Automatically retries once on 401 by refreshing token."""
    global ACTIVE_ACCESS_TOKEN
    token = resolve_active_token()
    status, headers, res_data = request_api_direct(token, method, path, body)
    
    # Self-healing on token expiration (401 Unauthorized):
    # If the request returns 401, our cached ACTIVE_ACCESS_TOKEN is likely expired.
    # We clear the global cache, resolve a fresh active token, and retry the request once.
    if status == 401:
        print("[*] KeycloakAPI: Cached ACTIVE_ACCESS_TOKEN returned 401 Unauthorized (likely expired). Clearing cache and retrying...")
        ACTIVE_ACCESS_TOKEN = None
        token = resolve_active_token()
        status, headers, res_data = request_api_direct(token, method, path, body)
        
    return status, headers, res_data

# PIN Hashing helpers
def hash_pin(pin: str) -> str:
    if HAS_BCRYPT:
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(pin.encode('utf-8'), salt).decode('utf-8')
    else:
        salt = "holyseeds_salt_12345"
        return hashlib.sha256((pin + salt).encode('utf-8')).hexdigest()

def verify_pin_hash(pin: str, hashed_pin: str) -> bool:
    if HAS_BCRYPT and hashed_pin.startswith("$2"):
        try:
            return bcrypt.checkpw(pin.encode('utf-8'), hashed_pin.encode('utf-8'))
        except Exception:
            pass
    salt = "holyseeds_salt_12345"
    expected = hashlib.sha256((pin + salt).encode('utf-8')).hexdigest()
    return hashed_pin == expected


# --- Keycloak User Operations ---

def find_user_by_phone(phone_number: str):
    """Finds a user by phoneNumber attribute and fetches full details including attributes."""
    user_id = None
    # 1. Search via username (username = phone_number)
    status, _, users = request_api("GET", f"/admin/realms/{TARGET_REALM}/users?username={phone_number}")
    if status == 200 and isinstance(users, list) and len(users) > 0:
        user_id = users[0].get("id")
        
    if not user_id:
        # 2. Fallback: Search via attributes query q
        status, _, users = request_api("GET", f"/admin/realms/{TARGET_REALM}/users?q=phoneNumber:{phone_number}")
        if status == 200 and isinstance(users, list) and len(users) > 0:
            user_id = users[0].get("id")
            
    if user_id:
        # Fetch FULL user representation including attributes
        detail_status, _, full_user = request_api("GET", f"/admin/realms/{TARGET_REALM}/users/{user_id}")
        if detail_status == 200:
            return full_user
            
    return None

def find_user_by_id(user_id: str):
    """Fetches full user representation by ID."""
    status, _, user = request_api("GET", f"/admin/realms/{TARGET_REALM}/users/{user_id}")
    if status == 200:
        return user
    return None

def list_users(first=0, max_users=100):
    """Lists all users in the target realm with attributes."""
    # Note: List API may return partial profiles depending on Keycloak settings.
    # To be safe, we list and then can fetch full details, but for general listing, listing is sufficient.
    status, _, users = request_api("GET", f"/admin/realms/{TARGET_REALM}/users?first={first}&max={max_users}")
    if status == 200 and isinstance(users, list):
        return users
    return []

def signup_user(phone_number, name, email, pin):
    """Signs up a new user with phone_number, name, email, and pin in attributes."""
    print(f"\n[SIGNUP] Attempting registration for: phone={phone_number}, name={name}, email={email}")
    
    # Pre-check if already exists
    existing = find_user_by_phone(phone_number)
    if existing:
        print(f"[SIGNUP WARNING] Registration rejected: Phone number '{phone_number}' already exists in Keycloak (ID: {existing.get('id')}).")
        return {"success": False, "error": "이미 동일한 전화번호로 등록된 사용자가 존재합니다."}
        
    hashed_pin = hash_pin(pin)
    user_payload = {
        "username": phone_number,
        "email": email,
        "firstName": name,
        "enabled": True,
        "emailVerified": True,
        "attributes": {
            "phoneNumber": [phone_number],
            "pinNumber": [hashed_pin]
        }
    }
    
    status, headers, body = request_api("POST", f"/admin/realms/{TARGET_REALM}/users", user_payload)
    if status == 201:
        location = headers.get("Location", "")
        user_id = location.strip().split("/")[-1] if location else None
        if not user_id:
            usr = find_user_by_phone(phone_number)
            user_id = usr.get("id") if usr else None
        print(f"[SIGNUP SUCCESS] Successfully registered user in Keycloak. User ID: {user_id}")
        return {"success": True, "user_id": user_id}
    else:
        print(f"[SIGNUP FAILED] Keycloak rejected user creation. Status: {status}")
        print(f" -> Response Body: {json.dumps(body) if isinstance(body, dict) else str(body)}")
        err_msg = body.get("errorMessage") if isinstance(body, dict) else str(body)
        return {"success": False, "error": f"사용자 생성에 실패했습니다. (응답: {err_msg})"}

def login_verify_pin(phone_number, entered_pin):
    """Verifies a user by phone_number and pin, returning the user if validated."""
    print(f"\n[LOGIN] Attempting login verification for: phone={phone_number}")
    user = find_user_by_phone(phone_number)
    if not user:
        print(f"[LOGIN FAILED] Verification failed: Phone number '{phone_number}' not found in Keycloak.")
        return {"success": False, "error": "등록되지 않은 전화번호입니다."}
        
    attributes = user.get("attributes", {})
    hashed_pin = attributes.get("pinNumber", [""])[0] if attributes.get("pinNumber") else ""
    
    if not hashed_pin:
        print(f"[LOGIN FAILED] Verification failed: User '{phone_number}' does not have a hashed pin attribute set.")
        return {"success": False, "error": "계정에 설정된 PIN 정보가 없습니다."}
        
    if verify_pin_hash(entered_pin, hashed_pin):
        print(f"[LOGIN SUCCESS] Login verified successfully for: phone={phone_number} (ID: {user.get('id')})")
        return {"success": True, "user": user}
    else:
        print(f"[LOGIN FAILED] Verification failed: Invalid PIN entered for phone={phone_number}.")
        return {"success": False, "error": "PIN 번호가 올바르지 않습니다."}

def update_profile(user_id, name, email, phone_number=None):
    """Updates a user's standard fields and optionally attributes."""
    user = find_user_by_id(user_id)
    if not user:
        return {"success": False, "error": "사용자를 찾을 수 없습니다."}
        
    # Modify fields
    user["firstName"] = name
    user["email"] = email
    
    if phone_number:
        if "attributes" not in user:
            user["attributes"] = {}
        user["attributes"]["phoneNumber"] = [phone_number]
        # Also update username if phone number is the username
        user["username"] = phone_number
        
    status, _, body = request_api("PUT", f"/admin/realms/{TARGET_REALM}/users/{user_id}", user)
    if status in (200, 204):
        return {"success": True}
    else:
        err_msg = body.get("errorMessage") if isinstance(body, dict) else str(body)
        return {"success": False, "error": f"프로필 수정을 실패했습니다. (응답: {err_msg})"}

def delete_user(user_id):
    """Deletes a user from Keycloak."""
    status, _, _ = request_api("DELETE", f"/admin/realms/{TARGET_REALM}/users/{user_id}")
    if status == 204:
        return {"success": True}
    return {"success": False, "error": f"사용자 삭제에 실패했습니다. (Status: {status})"}

def is_manager(user: dict) -> bool:
    """Checks if a user is an administrator (manager flag == "1" or bootstrap number)."""
    if not user:
        return False
    # Bootstrap: Phone number 01055787363 is always manager by default
    if user.get("username") == "01055787363":
        return True
    attributes = user.get("attributes", {})
    manager_flag = attributes.get("manager", [""])[0] if attributes.get("manager") else ""
    return manager_flag == "1"

def set_user_manager_status(user_id: str, is_mgr: bool):
    """Sets a user's manager attribute to "1" or "0"."""
    user = find_user_by_id(user_id)
    if not user:
        return {"success": False, "error": "사용자를 찾을 수 없습니다."}
        
    if "attributes" not in user:
        user["attributes"] = {}
        
    user["attributes"]["manager"] = ["1" if is_mgr else "0"]
    
    status, _, body = request_api("PUT", f"/admin/realms/{TARGET_REALM}/users/{user_id}", user)
    if status in (200, 204):
        return {"success": True}
    else:
        err_msg = body.get("errorMessage") if isinstance(body, dict) else str(body)
        return {"success": False, "error": f"관리자 권한 변경에 실패했습니다. (응답: {err_msg})"}
