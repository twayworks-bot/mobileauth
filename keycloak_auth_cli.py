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

# Load environment variables from .env
def load_env(file_path=".env"):
    env_vars = {}
    if not os.path.exists(file_path):
        return env_vars
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                env_vars[key.strip()] = val.strip()
    return env_vars

ENV = load_env(".env")
BASE_URL = ENV.get("KEYCLOAK_BASE_URL", "https://auth.thewayworks.net").rstrip("/")
TARGET_REALM = ENV.get("KEYCLOAK_TARGET_REALM", "holyseeds")
ADMIN_TOKEN = ENV.get("KEYCLOAK_ADMIN_TOKEN")

# Setup unverified SSL context just in case
SSL_CONTEXT = ssl._create_unverified_context()
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

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
    print("[*] KEYCLOAK_ADMIN_TOKEN is expired or is a Refresh Token. Attempting dynamic exchange...")
    
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
    """Helper to make HTTP requests with the dynamically resolved active access token."""
    token = resolve_active_token()
    return request_api_direct(token, method, path, body)

# PIN Hashing helpers
def hash_pin(pin: str) -> str:
    if HAS_BCRYPT:
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(pin.encode('utf-8'), salt).decode('utf-8')
    else:
        # Fallback SHA-256 with fixed salt
        salt = "holyseeds_salt_12345"
        return hashlib.sha256((pin + salt).encode('utf-8')).hexdigest()

def verify_pin(pin: str, hashed_pin: str) -> bool:
    if HAS_BCRYPT and hashed_pin.startswith("$2"):
        try:
            return bcrypt.checkpw(pin.encode('utf-8'), hashed_pin.encode('utf-8'))
        except Exception:
            pass
    # Fallback SHA-256 comparison
    salt = "holyseeds_salt_12345"
    expected = hashlib.sha256((pin + salt).encode('utf-8')).hexdigest()
    return hashed_pin == expected


def find_user_by_phone(phone_number: str):
    """Finds a user by phoneNumber attribute and fetches full details including attributes."""
    user_id = None
    # First search via standard username (since phone is username)
    status, _, users = request_api("GET", f"/admin/realms/{TARGET_REALM}/users?username={phone_number}")
    if status == 200 and isinstance(users, list) and len(users) > 0:
        user_id = users[0].get("id")
        
    if not user_id:
        # Fallback/alternate: Search via attributes query q
        status, _, users = request_api("GET", f"/admin/realms/{TARGET_REALM}/users?q=phoneNumber:{phone_number}")
        if status == 200 and isinstance(users, list) and len(users) > 0:
            user_id = users[0].get("id")
            
    if user_id:
        # Fetch FULL user representation including attributes
        detail_status, _, full_user = request_api("GET", f"/admin/realms/{TARGET_REALM}/users/{user_id}")
        if detail_status == 200:
            return full_user
            
    return None

def step2_signup_user(phone_number, name, email, pin):
    print(f"\n[Step 2] Signing up user: {name} ({phone_number})")
    
    # Hash PIN
    hashed_pin = hash_pin(pin)
    if HAS_BCRYPT:
        print(f" -> PIN hashed successfully using bcrypt: {hashed_pin[:25]}...")
    else:
        print(f" -> PIN hashed successfully using SHA-256 fallback: {hashed_pin}")
        
    # Check if user already exists
    existing_user = find_user_by_phone(phone_number)
    if existing_user:
        user_id = existing_user.get("id")
        print(f" -> User with phone {phone_number} already exists (ID: {user_id}). Deleting to ensure clean test state...")
        del_status, _, _ = request_api("DELETE", f"/admin/realms/{TARGET_REALM}/users/{user_id}")
        if del_status == 204:
            print(" -> Existing user deleted successfully.")
        else:
            print(f" -> Warning: Failed to delete existing user (Status: {del_status})")
            
    # Create user request payload
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
    
    # Send user registration POST request
    status, headers, body = request_api("POST", f"/admin/realms/{TARGET_REALM}/users", user_payload)
    
    if status == 201:
        print(" -> [SUCCESS] User created successfully (Status: 201 Created)")
        # Retrieve user ID from Location header
        location = headers.get("Location", "")
        user_id = None
        if location:
            user_id = location.strip().split("/")[-1]
            print(f" -> Retrieved User ID from Location Header: {user_id}")
            
        # Fallback in case location header is not parsing cleanly
        if not user_id:
            usr = find_user_by_phone(phone_number)
            if usr:
                user_id = usr.get("id")
                print(f" -> Retrieved User ID from Search: {user_id}")
                
        return user_id
    else:
        print(f" -> [FAILED] User creation failed. Status: {status}, Response: {body}")
        return None

def step3_search_user_by_phone(phone_number):
    print(f"\n[Step 3] Searching user by phone number: {phone_number}")
    user = find_user_by_phone(phone_number)
    if user:
        print(" -> [SUCCESS] User found:")
        print(f"    - Full User Data: {json.dumps(user, indent=2)}")
        print(f"    - ID: {user.get('id')}")
        print(f"    - Username: {user.get('username')}")
        print(f"    - Email: {user.get('email')}")
        print(f"    - FirstName: {user.get('firstName')}")
        
        attributes = user.get("attributes", {})
        phone_attr = attributes.get("phoneNumber", [""])[0] if attributes.get("phoneNumber") else ""
        pin_attr = attributes.get("pinNumber", [""])[0] if attributes.get("pinNumber") else ""
        print(f"    - Phone Attribute: {phone_attr}")
        print(f"    - PIN Hash Attribute: {pin_attr[:25] if pin_attr else 'None'}...")
        return user
    else:
        print(" -> [FAILED] User not found.")
        return None

def step4_login_verify_pin(phone_number, entered_pin):
    print(f"\n[Step 4] Verifying PIN for login simulation. Phone: {phone_number}, PIN: {entered_pin}")
    user = find_user_by_phone(phone_number)
    if not user:
        print(" -> [FAILED] User not found.")
        return False
        
    attributes = user.get("attributes", {})
    hashed_pin = attributes.get("pinNumber", [""])[0]
    
    if not hashed_pin:
        print(" -> [FAILED] No PIN attribute found for this user.")
        return False
        
    verified = verify_pin(entered_pin, hashed_pin)
    if verified:
        print(" -> [SUCCESS] PIN verification PASSED! Login simulation successful.")
        return True
    else:
        print(" -> [FAILED] PIN verification FAILED! Invalid PIN.")
        return False

def step5_update_profile(user_id, updated_name, updated_email):
    print(f"\n[Step 5] Updating profile for User ID: {user_id}")
    
    # 1. Fetch current user first to avoid overwriting attributes/other fields
    status, _, user = request_api("GET", f"/admin/realms/{TARGET_REALM}/users/{user_id}")
    if status != 200:
        print(f" -> [FAILED] Could not retrieve user before update (Status: {status})")
        return False
        
    # 2. Modify fields
    user["firstName"] = updated_name
    user["email"] = updated_email
    
    # 3. PUT request
    put_status, _, put_body = request_api("PUT", f"/admin/realms/{TARGET_REALM}/users/{user_id}", user)
    
    if put_status in (200, 204):
        print(f" -> [SUCCESS] Profile updated successfully. Status: {put_status}")
        
        # 4. Fetch again to verify changes
        _, _, updated_user = request_api("GET", f"/admin/realms/{TARGET_REALM}/users/{user_id}")
        print(f"    - Verified Name: {updated_user.get('firstName')}")
        print(f"    - Verified Email: {updated_user.get('email')}")
        return True
    else:
        print(f" -> [FAILED] Profile update failed (Status: {put_status}), Response: {put_body}")
        return False

def step6_cleanup_test_user(user_id, phone_number):
    print(f"\n[Step 6] Cleaning up test user. User ID: {user_id}")
    
    status, _, _ = request_api("DELETE", f"/admin/realms/{TARGET_REALM}/users/{user_id}")
    if status == 204:
        print(" -> [SUCCESS] Test user deleted successfully.")
        
        # Verify the deletion
        verified_user = find_user_by_phone(phone_number)
        if not verified_user:
            print(" -> [SUCCESS] Verified user is no longer searchable in Keycloak.")
            return True
        else:
            print(" -> [FAILED] User still searchable after deletion!")
            return False
    else:
        print(f" -> [FAILED] Cleanup failed (Status: {status})")
        return False

def get_user_profile_config():
    """Fetches declarative user profile schema of the realm if supported."""
    status, _, profile = request_api("GET", f"/admin/realms/{TARGET_REALM}/users/profile")
    if status == 200:
        print("\n[DIAGNOSTIC] Successfully fetched Realm User Profile configuration!")
        attributes = profile.get("attributes", [])
        attr_names = [a.get("name") for a in attributes]
        print(f" -> Allowed User Attributes in Schema: {attr_names}")
    else:
        print(f"\n[DIAGNOSTIC] Could not fetch User Profile configuration. Status: {status}, Response: {profile}")

def main():
    if not ADMIN_TOKEN:
        print("Error: KEYCLOAK_ADMIN_TOKEN not found in .env.")
        print("Please run `generate_admin_token.py` first to generate it.")
        return

    print("=====================================================================")
    print("      Keycloak Auth & User Management Basic Verification CLI")
    print("=====================================================================")
    print(f"Base URL    : {BASE_URL}")
    print(f"Target Realm: {TARGET_REALM}")
    print(f"Bcrypt Lib  : {'Available' if HAS_BCRYPT else 'Missing (SHA-256 Fallback)'}")
    print("=====================================================================")

    # Run diagnostic first
    get_user_profile_config()

    # Test parameters
    test_phone = "01055787363"
    test_name = "inchang"
    test_email = "gluemii@gmail.com"
    test_pin = "1234"

    # Step 2: User Sign-Up
    user_id = step2_signup_user(test_phone, test_name, test_email, test_pin)
    if not user_id:
        print("\n❌ Step 2 Failed. Terminating test sequence.")
        return

    # Step 3: Search User
    user = step3_search_user_by_phone(test_phone)
    if not user:
        print("\n❌ Step 3 Failed. Terminating test sequence.")
        return

    # Step 4: Login & PIN Verification (Correct PIN)
    success = step4_login_verify_pin(test_phone, "1234")
    if not success:
        print("\n❌ Step 4 Failed (Valid PIN rejection). Terminating test sequence.")
        return

    # Step 4b: Login & PIN Verification (Incorrect PIN - expected failure)
    print("\n[Step 4b] Simulating incorrect PIN login...")
    failed_login = step4_login_verify_pin(test_phone, "9999")
    if failed_login:
        print("\n❌ Failure verification: Keycloak accepted an invalid PIN! Terminating.")
        return
    else:
        print(" -> [SUCCESS] Incorrect PIN was correctly rejected.")

    # Step 5: Update Profile
    updated_name = "inchang-updated"
    updated_email = "gluemii-updated@gmail.com"
    update_ok = step5_update_profile(user_id, updated_name, updated_email)
    if not update_ok:
        print("\n❌ Step 5 Failed. Terminating test sequence.")
        return

    # Step 6: Cleanup
    cleanup_ok = step6_cleanup_test_user(user_id, test_phone)
    if not cleanup_ok:
        print("\n❌ Step 6 Failed (User not deleted or still searchable).")
        return

    print("\n=====================================================================")
    print("🎉 All steps of the Keycloak User Verification CLI passed successfully!")
    print("=====================================================================")

if __name__ == "__main__":
    main()
