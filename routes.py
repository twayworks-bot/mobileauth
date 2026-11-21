from fastapi import APIRouter, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import urllib.parse
import keycloak_api

# Setup Router
router = APIRouter(prefix="/auth")

# Setup Templates
templates = Jinja2Templates(directory="templates")

# Helper to get the logged in user from cookie session
def get_current_user(request: Request):
    user_id = request.cookies.get("auth_session")
    if not user_id:
        return None
    user = keycloak_api.find_user_by_id(user_id)
    return user

def build_local_dev_callback_url(redirect_url: str, user_id: str) -> str:
    """Appends session_id and signed dev_token to a validated localhost callback URL."""
    dev_token = keycloak_api.generate_dev_token(user_id)
    parsed = urllib.parse.urlparse(redirect_url)
    query_params = dict(urllib.parse.parse_qsl(parsed.query))
    query_params["session_id"] = user_id
    query_params["dev_token"] = dev_token
    new_query = urllib.parse.urlencode(query_params)
    return urllib.parse.urlunparse((
        parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment
    ))

def build_cors_headers(request: Request) -> dict:
    """Builds CORS headers allowing localhost / 127.0.0.1 origins for local developer direct API calls."""
    origin = request.headers.get("origin", "")
    allow_origin = "*"
    if origin and keycloak_api.is_local_dev_redirect_url(origin):
        allow_origin = origin
    return {
        "Access-Control-Allow-Origin": allow_origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Auth-Session, X-Dev-Token, X-Dev-Api-Key"
    }

def check_dev_api_key_if_configured(request: Request) -> tuple[bool, str]:
    """Checks if LOCAL_DEV_API_KEY is configured and matches X-Dev-Api-Key header or query param."""
    if not keycloak_api.ALLOW_LOCAL_DEV_AUTH:
        return False, "로컬 개발 예외 인증 기능이 서버 설정(ALLOW_LOCAL_DEV_AUTH=false)에 의해 비활성화되어 있습니다."
    if keycloak_api.LOCAL_DEV_API_KEY:
        provided_key = request.headers.get("x-dev-api-key") or request.query_params.get("dev_api_key") or ""
        if provided_key != keycloak_api.LOCAL_DEV_API_KEY:
            return False, "유효한 로컬 개발 API 키(X-Dev-Api-Key)가 필요합니다."
    return True, ""

# UI: Login page
@router.get("/login", response_class=HTMLResponse)
async def login_get(
    request: Request,
    msg: str = None,
    error: str = None,
    redirect: str = None,
    require_role: str = None,
    dev_mode: str = None
):
    # If already logged in, verify required role and redirect
    user = get_current_user(request)
    if user:
        if require_role and not keycloak_api.check_user_required_role(user, require_role):
            return templates.TemplateResponse(request, "login.html", {
                "msg": msg,
                "error": error or f"현재 로그인된 계정은 요구되는 권한({require_role})을 가지고 있지 않습니다.",
                "redirect": redirect,
                "require_role": require_role,
                "dev_mode": dev_mode
            })

        is_local_redirect = keycloak_api.is_local_dev_redirect_url(redirect)
        wants_dev_bridge = (dev_mode in ("1", "true", "yes")) or is_local_redirect

        if wants_dev_bridge and redirect:
            if not keycloak_api.ALLOW_LOCAL_DEV_AUTH:
                return templates.TemplateResponse(request, "login.html", {
                    "error": "로컬 개발 예외 인증 기능이 비활성화되어 있습니다.",
                    "redirect": redirect, "require_role": require_role, "dev_mode": dev_mode
                })
            if not is_local_redirect:
                return templates.TemplateResponse(request, "login.html", {
                    "error": "보안 경고: 로컬 개발 세션 전달(dev_mode)은 localhost 또는 127.0.0.1 주소로만 허용됩니다.",
                    "redirect": redirect, "require_role": require_role, "dev_mode": dev_mode
                })
            if not keycloak_api.is_developer(user):
                return templates.TemplateResponse(request, "login.html", {
                    "error": "로컬 개발 예외 연동은 개발자 등급(developer: 1 또는 dev-leader: 2) 계정만 사용할 수 있습니다.",
                    "redirect": redirect, "require_role": require_role, "dev_mode": dev_mode
                })
            target_url = build_local_dev_callback_url(redirect, user["id"])
            print(f"[DEV-AUTH AUDIT] Direct Localhost Bridge Redirect for logged-in developer={user.get('username')} (dev_flag={keycloak_api.get_user_developer_flag(user)}) -> {redirect}")
            return RedirectResponse(url=target_url, status_code=status.HTTP_303_SEE_OTHER)

        url = redirect if redirect else "/auth/profile"
        return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(request, "login.html", {
        "msg": msg,
        "error": error,
        "redirect": redirect,
        "require_role": require_role,
        "dev_mode": dev_mode
    })

# Action: Login process
@router.post("/login")
async def login_post(
    request: Request,
    phone_number: str = Form(...),
    pin: str = Form(...),
    redirect: str = Form(None),
    require_role: str = Form(None),
    dev_mode: str = Form(None)
):
    print(f"\n[HTTP POST /auth/login] Received login submission for: phone={phone_number}")
    res = keycloak_api.login_verify_pin(phone_number, pin)
    if res["success"]:
        user = res["user"]

        # 1. Verify required role if specified (e.g., manager, super, developer, dev-leader)
        if require_role and not keycloak_api.check_user_required_role(user, require_role):
            print(f"[HTTP POST /auth/login] Role check failed for user={phone_number}, require_role={require_role}")
            return templates.TemplateResponse(request, "login.html", {
                "error": f"해당 서비스 접근에 필요한 권한({require_role})이 없습니다.",
                "phone_number": phone_number,
                "redirect": redirect,
                "require_role": require_role,
                "dev_mode": dev_mode
            })

        # 2. Check if this is a local development callback redirect (localhost / 127.0.0.1 or dev_mode=1)
        is_local_redirect = keycloak_api.is_local_dev_redirect_url(redirect)
        wants_dev_bridge = (dev_mode in ("1", "true", "yes")) or is_local_redirect

        if wants_dev_bridge and redirect:
            if not keycloak_api.ALLOW_LOCAL_DEV_AUTH:
                return templates.TemplateResponse(request, "login.html", {
                    "error": "로컬 개발 예외 인증 기능이 서버 설정에 의해 비활성화되어 있습니다.",
                    "phone_number": phone_number, "redirect": redirect, "require_role": require_role, "dev_mode": dev_mode
                })
            if not is_local_redirect:
                return templates.TemplateResponse(request, "login.html", {
                    "error": "보안 경고: 로컬 개발 세션 전달(dev_mode)은 localhost 또는 127.0.0.1 콜백 주소로만 허용됩니다.",
                    "phone_number": phone_number, "redirect": redirect, "require_role": require_role, "dev_mode": dev_mode
                })
            if not keycloak_api.is_developer(user):
                print(f"[DEV-AUTH AUDIT] Blocked non-developer user={phone_number} from localhost session bridge redirect.")
                return templates.TemplateResponse(request, "login.html", {
                    "error": "로컬 개발 예외 인증은 개발자 등급(developer: 1 또는 dev-leader: 2) 계정만 허용됩니다.",
                    "phone_number": phone_number, "redirect": redirect, "require_role": require_role, "dev_mode": dev_mode
                })
            url = build_local_dev_callback_url(redirect, user["id"])
            print(f"[DEV-AUTH AUDIT] Localhost Session Bridge issued for developer={phone_number} (dev_flag={keycloak_api.get_user_developer_flag(user)}) -> {redirect}")
        else:
            url = redirect if redirect else "/auth/profile"

        response = RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)
        # Store user ID in HTTPOnly cookie for secure session management
        response.set_cookie(key="auth_session", value=user["id"], httponly=True, path="/")
        print(f"[HTTP POST /auth/login] Login success. Setting session cookie for user_id={user['id']}")
        return response
    else:
        print(f"[HTTP POST /auth/login] Login failed. Error: {res['error']}")
        return templates.TemplateResponse(request, "login.html", {
            "error": res["error"],
            "phone_number": phone_number,
            "redirect": redirect,
            "require_role": require_role,
            "dev_mode": dev_mode
        })

# Action: Logout
@router.get("/logout")
async def logout(request: Request):
    response = RedirectResponse(url="/auth/login?msg=로그아웃+되었습니다.", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(key="auth_session", path="/")
    return response

# UI: Signup page
@router.get("/signup", response_class=HTMLResponse)
async def signup_get(request: Request, error: str = None):
    return templates.TemplateResponse(request, "signup.html", {"error": error})

# Action: Signup process
@router.post("/signup")
async def signup_post(request: Request, phone_number: str = Form(...), name: str = Form(...), email: str = Form(...), pin: str = Form(...)):
    print(f"\n[HTTP POST /auth/signup] Received signup request for: phone={phone_number}, name={name}, email={email}")
    res = keycloak_api.signup_user(phone_number, name, email, pin)
    if res["success"]:
        print(f"[HTTP POST /auth/signup] Signup success for user phone={phone_number}")
        return RedirectResponse(url="/auth/login?msg=회원가입이+완료되었습니다.+로그인+해+주세요.", status_code=status.HTTP_303_SEE_OTHER)
    else:
        print(f"[HTTP POST /auth/signup] Signup failed. Error: {res['error']}")
        return templates.TemplateResponse(request, "signup.html", {
            "error": res["error"],
            "phone_number": phone_number,
            "name": name,
            "email": email
        })

# UI: Profile page (Authentication Protected)
@router.get("/profile", response_class=HTMLResponse)
async def profile_get(request: Request, msg: str = None, error: str = None):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/auth/login?error=로그인이+필요한+페이지입니다.", status_code=status.HTTP_303_SEE_OTHER)
    
    role_flag = keycloak_api.get_user_role_flag(user)
    user_is_mgr = keycloak_api.is_manager(user)
    user_is_super = keycloak_api.is_super(user)
    dev_flag = keycloak_api.get_user_developer_flag(user)
    dev_role = keycloak_api.get_developer_role_name(dev_flag)
    user_is_dev = keycloak_api.is_developer(user)
    user_is_dev_leader = keycloak_api.is_dev_leader(user)
    dev_token = keycloak_api.generate_dev_token(user["id"]) if user_is_dev else None
    
    return templates.TemplateResponse(request, "profile.html", {
        "user": user,
        "role_flag": role_flag,
        "is_manager": user_is_mgr,
        "is_super": user_is_super,
        "developer_flag": dev_flag,
        "developer_role": dev_role,
        "is_developer": user_is_dev,
        "is_dev_leader": user_is_dev_leader,
        "dev_token": dev_token,
        "msg": msg,
        "error": error
    })

# Action: Profile update (Name, Email, and optional PIN update)
@router.post("/profile")
async def profile_post(
    request: Request, 
    name: str = Form(...), 
    email: str = Form(...),
    current_pin: str = Form(None),
    new_pin: str = Form(None),
    confirm_pin: str = Form(None)
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/auth/login?error=세션이+만료되었습니다.+다시+로그인하세요.", status_code=status.HTTP_303_SEE_OTHER)
        
    role_flag = keycloak_api.get_user_role_flag(user)
    user_is_mgr = keycloak_api.is_manager(user)
    user_is_super = keycloak_api.is_super(user)
    dev_flag = keycloak_api.get_user_developer_flag(user)
    dev_role = keycloak_api.get_developer_role_name(dev_flag)
    user_is_dev = keycloak_api.is_developer(user)
    user_is_dev_leader = keycloak_api.is_dev_leader(user)
    dev_token = keycloak_api.generate_dev_token(user["id"]) if user_is_dev else None

    base_ctx = {
        "user": user,
        "role_flag": role_flag,
        "is_manager": user_is_mgr,
        "is_super": user_is_super,
        "developer_flag": dev_flag,
        "developer_role": dev_role,
        "is_developer": user_is_dev,
        "is_dev_leader": user_is_dev_leader,
        "dev_token": dev_token
    }

    cur_p = (current_pin or "").strip()
    new_p = (new_pin or "").strip()
    cnf_p = (confirm_pin or "").strip()
    
    pin_changed = False
    
    # Check if PIN change was attempted
    if cur_p or new_p or cnf_p:
        if not cur_p:
            return templates.TemplateResponse(request, "profile.html", {
                **base_ctx, "error": "PIN 번호를 변경하려면 현재 PIN 번호를 입력해야 합니다."
            })
        if not new_p:
            return templates.TemplateResponse(request, "profile.html", {
                **base_ctx, "error": "새로운 PIN 번호를 입력해 주세요."
            })
        if not cnf_p:
            return templates.TemplateResponse(request, "profile.html", {
                **base_ctx, "error": "새 PIN 번호 확인을 입력해 주세요."
            })
        if new_p != cnf_p:
            return templates.TemplateResponse(request, "profile.html", {
                **base_ctx, "error": "새 PIN 번호와 확인 번호가 일치하지 않습니다."
            })
        if len(new_p) < 4:
            return templates.TemplateResponse(request, "profile.html", {
                **base_ctx, "error": "새 PIN 번호는 최소 4자리 이상이어야 합니다."
            })
            
        # Verify current PIN against user's stored hash
        if not keycloak_api.verify_user_pin(user, cur_p):
            return templates.TemplateResponse(request, "profile.html", {
                **base_ctx, "error": "현재 PIN 번호가 일치하지 않습니다."
            })
            
        pin_res = keycloak_api.update_pin(user["id"], new_p)
        if not pin_res["success"]:
            return templates.TemplateResponse(request, "profile.html", {
                **base_ctx, "error": pin_res["error"]
            })
        pin_changed = True

    # Update basic profile info (name, email)
    res = keycloak_api.update_profile(user["id"], name, email)
    if res["success"]:
        msg = "프로필 정보 및 PIN 번호가 성공적으로 변경되었습니다." if pin_changed else "프로필 정보가 성공적으로 수정되었습니다."
        return RedirectResponse(url=f"/auth/profile?msg={urllib.parse.quote(msg)}", status_code=status.HTTP_303_SEE_OTHER)
    else:
        return templates.TemplateResponse(request, "profile.html", {
            **base_ctx, "error": res["error"]
        })

# UI: Users list (CRUD management - Super Protected: flag=2)
@router.get("/users", response_class=HTMLResponse)
async def users_get(request: Request, msg: str = None, error: str = None):
    current_user = get_current_user(request)
    if not current_user:
        return RedirectResponse(url="/auth/login?error=로그인이+필요한+페이지입니다.", status_code=status.HTTP_303_SEE_OTHER)
        
    # Separation: Only Super Admin (flag=2) can access user permission management
    if not keycloak_api.is_super(current_user):
        return RedirectResponse(url="/auth/profile?error=사용자+권한+관리(CRUD)는+최고+관리자(Super)+전용+기능입니다.", status_code=status.HTTP_303_SEE_OTHER)
        
    users = keycloak_api.list_users()
    
    # Enrich user objects with role flags (both manager and developer) for HTML rendering
    for u in users:
        u_flag = keycloak_api.get_user_role_flag(u)
        u["role_flag"] = u_flag
        u["is_manager_flag"] = (u_flag in ("1", "2"))
        u["is_super_flag"] = (u_flag == "2")

        d_flag = keycloak_api.get_user_developer_flag(u)
        u["developer_flag"] = d_flag
        u["developer_role"] = keycloak_api.get_developer_role_name(d_flag)
        u["is_developer_flag"] = (d_flag in ("1", "2"))
        u["is_dev_leader_flag"] = (d_flag == "2")
        
    return templates.TemplateResponse(request, "users.html", {
        "users": users, 
        "current_user": current_user, 
        "msg": msg, 
        "error": error
    })

# Action: Delete user (CRUD delete - Super Protected: flag=2)
@router.post("/users/{user_id}/delete")
async def users_delete(request: Request, user_id: str):
    current_user = get_current_user(request)
    if not current_user or not keycloak_api.is_super(current_user):
        return RedirectResponse(url="/auth/login?error=사용자+삭제+권한이+없습니다.+최고+관리자(Super)+계정으로+로그인하세요.", status_code=status.HTTP_303_SEE_OTHER)
        
    target_user = keycloak_api.find_user_by_id(user_id)
    if target_user and target_user.get("username") == "01055787363":
        return RedirectResponse(url=f"/auth/users?error={urllib.parse.quote('최상위 개발자 계정은 삭제할 수 없습니다.')}", status_code=status.HTTP_303_SEE_OTHER)

    session_user_id = request.cookies.get("auth_session")
    res = keycloak_api.delete_user(user_id)
    if res["success"]:
        # If user deleted themselves, clear session cookie and redirect to login
        if session_user_id == user_id:
            response = RedirectResponse(url="/auth/login?msg=회원+탈퇴가+완료되었습니다.", status_code=status.HTTP_303_SEE_OTHER)
            response.delete_cookie(key="auth_session", path="/")
            return response
        return RedirectResponse(url="/auth/users?msg=사용자가+성공적으로+삭제되었습니다.", status_code=status.HTTP_303_SEE_OTHER)
    else:
        return RedirectResponse(url=f"/auth/users?error={urllib.parse.quote(res['error'])}", status_code=status.HTTP_303_SEE_OTHER)

# Action: Set User Role (Super Protected: flag=2)
@router.post("/users/{user_id}/set-role")
async def users_set_role(request: Request, user_id: str, role: str = Form(...)):
    current_user = get_current_user(request)
    if not current_user or not keycloak_api.is_super(current_user):
        return RedirectResponse(url="/auth/login?error=사용자+권한+수정+권한이+없습니다.+최고+관리자(Super)+계정으로+로그인하세요.", status_code=status.HTTP_303_SEE_OTHER)
        
    if role not in ("0", "1", "2"):
        return RedirectResponse(url=f"/auth/users?error={urllib.parse.quote('유효하지 않은 권한 등급 플래그입니다.')}", status_code=status.HTTP_303_SEE_OTHER)
        
    res = keycloak_api.set_user_role(user_id, role)
    if res["success"]:
        role_names = {"0": "일반회원 (0)", "1": "관리자 (1)", "2": "슈퍼관리자 (2)"}
        name = role_names.get(role, role)
        print(f"[HTTP POST /auth/users/{user_id}/set-role] Successfully updated role to {name}")
        return RedirectResponse(url=f"/auth/users?msg={urllib.parse.quote(f'사용자 권한이 [{name}]로 변경되었습니다.')}", status_code=status.HTTP_303_SEE_OTHER)
    else:
        print(f"[HTTP POST /auth/users/{user_id}/set-role] Failed to update role. Error: {res['error']}")
        return RedirectResponse(url=f"/auth/users?error={urllib.parse.quote(res['error'])}", status_code=status.HTTP_303_SEE_OTHER)

# Action: Toggle Manager Privilege (Backward compatibility)
@router.post("/users/{user_id}/toggle-manager")
async def users_toggle_manager(request: Request, user_id: str, is_mgr: str = Form(...)):
    current_user = get_current_user(request)
    if not current_user or not keycloak_api.is_super(current_user):
        return RedirectResponse(url="/auth/login?error=사용자+권한+수정+권한이+없습니다.", status_code=status.HTTP_303_SEE_OTHER)
        
    target_role = "1" if is_mgr == "1" else "0"
    res = keycloak_api.set_user_role(user_id, target_role)
    
    if res["success"]:
        return RedirectResponse(url="/auth/users?msg=사용자+관리자+권한이+변경되었습니다.", status_code=status.HTTP_303_SEE_OTHER)
    else:
        return RedirectResponse(url=f"/auth/users?error={urllib.parse.quote(res['error'])}", status_code=status.HTTP_303_SEE_OTHER)


# Action: Set User Developer Role (Super Protected: manager flag=2)
@router.post("/users/{user_id}/set-developer")
async def users_set_developer(request: Request, user_id: str, developer: str = Form(...)):
    current_user = get_current_user(request)
    if not current_user or not keycloak_api.is_super(current_user):
        return RedirectResponse(url="/auth/login?error=개발자+권한+수정+권한이+없습니다.+최고+관리자(Super)+계정으로+로그인하세요.", status_code=status.HTTP_303_SEE_OTHER)
        
    if developer not in ("0", "1", "2"):
        return RedirectResponse(url=f"/auth/users?error={urllib.parse.quote('유효하지 않은 개발자 등급 플래그입니다.')}", status_code=status.HTTP_303_SEE_OTHER)
        
    res = keycloak_api.set_user_developer_role(user_id, developer)
    if res["success"]:
        dev_names = {"0": "일반 user (0)", "1": "developer (1)", "2": "dev-leader (2)"}
        name = dev_names.get(developer, developer)
        print(f"[HTTP POST /auth/users/{user_id}/set-developer] Successfully updated developer role to {name}")
        return RedirectResponse(url=f"/auth/users?msg={urllib.parse.quote(f'사용자 개발자 등급이 [{name}]로 변경되었습니다.')}", status_code=status.HTTP_303_SEE_OTHER)
    else:
        print(f"[HTTP POST /auth/users/{user_id}/set-developer] Failed to update developer role. Error: {res['error']}")
        return RedirectResponse(url=f"/auth/users?error={urllib.parse.quote(res['error'])}", status_code=status.HTTP_303_SEE_OTHER)


def _extract_session_or_dev_token(request: Request, session_id: str = None, dev_token: str = None, body_data: dict = None) -> tuple[str, str, str]:
    """
    Extracts session_id or dev_token from Query, Headers (Authorization: Bearer / X-Auth-Session / X-Dev-Token),
    JSON Body, or Cookie.
    Returns (resolved_user_id, token_type, error_message)
    """
    body_data = body_data or {}

    # 1. Check explicit dev_token first
    raw_dev_token = (
        dev_token
        or body_data.get("dev_token")
        or request.headers.get("x-dev-token")
    )

    # 2. Check Authorization Bearer header (can be either dev_token or session_id)
    auth_header = request.headers.get("authorization", "")
    bearer_val = ""
    if auth_header.lower().startswith("bearer "):
        bearer_val = auth_header[7:].strip()

    if not raw_dev_token and bearer_val and "." in bearer_val:
        raw_dev_token = bearer_val

    if raw_dev_token:
        verify_res = keycloak_api.verify_dev_token(raw_dev_token)
        if not verify_res["valid"]:
            return None, "dev_token", verify_res["error"]
        return verify_res["user_id"], "dev_token", ""

    # 3. Check session_id from query, body, X-Auth-Session header, Bearer header, or Cookie
    raw_session_id = (
        session_id
        or body_data.get("session_id")
        or request.headers.get("x-auth-session")
        or bearer_val
        or request.cookies.get("auth_session")
    )
    if raw_session_id:
        # If someone passed a signed dev_token in session_id parameter, support it seamlessly
        if "." in raw_session_id:
            verify_res = keycloak_api.verify_dev_token(raw_session_id)
            if not verify_res["valid"]:
                return None, "dev_token", verify_res["error"]
            return verify_res["user_id"], "dev_token", ""
        return raw_session_id.strip(), "session_id", ""

    return None, "none", "No session ID or dev_token provided"


# API Action: Verify Session (called by sub-services in production & local development)
@router.get("/api/verify-session")
async def verify_session(request: Request, session_id: str = None, dev_token: str = None, require_role: str = None):
    resolved_user_id, _, err_msg = _extract_session_or_dev_token(request, session_id=session_id, dev_token=dev_token)
    if not resolved_user_id:
        return {
            "valid": False,
            "is_manager": False,
            "is_super": False,
            "is_developer": False,
            "is_dev_leader": False,
            "role_flag": "0",
            "developer_flag": "0",
            "developer_role": "user",
            "error": err_msg,
            "has_required_role": False
        }
    
    user = keycloak_api.find_user_by_id(resolved_user_id)
    if not user:
        return {
            "valid": False,
            "is_manager": False,
            "is_super": False,
            "is_developer": False,
            "is_dev_leader": False,
            "role_flag": "0",
            "developer_flag": "0",
            "developer_role": "user",
            "error": "User not found",
            "has_required_role": False
        }
    
    return keycloak_api.build_user_auth_context(user, require_role=require_role)


# --- Local Development Exception APIs (Direct Call without Inbound Callback) ---

@router.options("/api/dev/direct-login")
@router.options("/api/dev/verify-session")
async def dev_api_cors_preflight(request: Request):
    """Handles CORS preflight requests from local frontend/backend development environments."""
    return JSONResponse(content={"ok": True}, headers=build_cors_headers(request))


@router.post("/api/dev/direct-login")
async def dev_direct_login(request: Request):
    """
    Exception API for Local Development:
    Allows a local app (e.g. http://localhost:5000) to directly authenticate against the public auth server
    and receive session_id + signed dev_token without needing an external inbound callback.
    Strictly gated to accounts with developer flag >= 1 (developer or dev-leader).
    """
    cors_headers = build_cors_headers(request)
    allowed, key_err = check_dev_api_key_if_configured(request)
    if not allowed:
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"valid": False, "error": key_err}, headers=cors_headers)

    # Parse JSON or Form body
    phone_number = None
    pin = None
    require_role = None
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            phone_number = body.get("phone_number")
            pin = body.get("pin")
            require_role = body.get("require_role")
        except Exception:
            pass
    if not phone_number or not pin:
        try:
            form = await request.form()
            phone_number = phone_number or form.get("phone_number")
            pin = pin or form.get("pin")
            require_role = require_role or form.get("require_role")
        except Exception:
            pass

    if not phone_number or not pin:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"valid": False, "error": "phone_number와 pin 파라미터가 필요합니다."},
            headers=cors_headers
        )

    res = keycloak_api.login_verify_pin(phone_number, pin)
    if not res["success"]:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"valid": False, "error": res["error"]},
            headers=cors_headers
        )

    user = res["user"]
    client_ip = request.client.host if request.client else "unknown"

    # Security Control: Only developer (1) or dev-leader (2) can use the local dev direct login exception API
    if not keycloak_api.is_developer(user):
        print(f"[DEV-AUTH AUDIT] DENIED direct-login for non-developer user={phone_number}, ip={client_ip}")
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "valid": False,
                "is_developer": False,
                "developer_flag": "0",
                "developer_role": "user",
                "error": "로컬 개발 예외 API(/auth/api/dev/direct-login)는 개발자 등급(developer: 1 또는 dev-leader: 2) 계정만 사용할 수 있습니다."
            },
            headers=cors_headers
        )

    auth_ctx = keycloak_api.build_user_auth_context(user, require_role=require_role)
    dev_token = keycloak_api.generate_dev_token(user["id"])

    print(f"[DEV-AUTH AUDIT] SUCCESS direct-login for developer={phone_number} (dev_role={auth_ctx['developer_role']}), ip={client_ip}")
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            **auth_ctx,
            "dev_mode": True,
            "session_id": user["id"],
            "dev_token": dev_token,
            "expires_in": keycloak_api.DEV_TOKEN_TTL_SECONDS
        },
        headers=cors_headers
    )


@router.get("/api/dev/verify-session")
@router.post("/api/dev/verify-session")
async def dev_verify_session(request: Request, session_id: str = None, dev_token: str = None, require_role: str = None):
    """
    Exception Verification API for Local Development:
    Allows a local application (e.g. http://localhost:5000) holding a session_id or dev_token
    from the public auth server (e.g. holyseeds.thewayworks.net/auth) to directly call and verify
    the session and retrieve both manager (0~2) and developer (0~2) flags.
    Supports GET (query/headers) and POST (JSON body/headers).
    """
    cors_headers = build_cors_headers(request)
    allowed, key_err = check_dev_api_key_if_configured(request)
    if not allowed:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"valid": False, "error": key_err, "has_required_role": False},
            headers=cors_headers
        )

    body_data = {}
    if request.method == "POST":
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                body_data = await request.json()
            except Exception:
                body_data = {}
        else:
            try:
                form = await request.form()
                body_data = dict(form)
            except Exception:
                body_data = {}

    req_role = require_role or body_data.get("require_role")
    resolved_user_id, token_source, err_msg = _extract_session_or_dev_token(
        request, session_id=session_id, dev_token=dev_token, body_data=body_data
    )

    if not resolved_user_id:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "valid": False,
                "verification_mode": "direct_dev_call",
                "is_manager": False,
                "is_super": False,
                "is_developer": False,
                "is_dev_leader": False,
                "role_flag": "0",
                "developer_flag": "0",
                "developer_role": "user",
                "error": err_msg,
                "has_required_role": False
            },
            headers=cors_headers
        )

    user = keycloak_api.find_user_by_id(resolved_user_id)
    if not user:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "valid": False,
                "verification_mode": "direct_dev_call",
                "is_manager": False,
                "is_super": False,
                "is_developer": False,
                "is_dev_leader": False,
                "role_flag": "0",
                "developer_flag": "0",
                "developer_role": "user",
                "error": "User not found",
                "has_required_role": False
            },
            headers=cors_headers
        )

    client_ip = request.client.host if request.client else "unknown"

    # Security Gate: Direct local dev verification requires the session owner to be a developer (flag 1 or 2)
    if not keycloak_api.is_developer(user):
        print(f"[DEV-AUTH AUDIT] DENIED dev/verify-session for non-developer user={user.get('username')}, ip={client_ip}")
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "valid": False,
                "verification_mode": "direct_dev_call",
                "is_manager": keycloak_api.is_manager(user),
                "is_super": keycloak_api.is_super(user),
                "is_developer": False,
                "is_dev_leader": False,
                "role_flag": keycloak_api.get_user_role_flag(user),
                "developer_flag": "0",
                "developer_role": "user",
                "error": "로컬 개발 직접 검증 예외 API(/auth/api/dev/verify-session)는 개발자 등급(developer: 1 또는 dev-leader: 2) 계정 세션만 허용됩니다.",
                "has_required_role": False
            },
            headers=cors_headers
        )

    auth_ctx = keycloak_api.build_user_auth_context(user, require_role=req_role)
    print(f"[DEV-AUTH AUDIT] Verified direct session for developer={user.get('username')} (dev_role={auth_ctx['developer_role']}, token_source={token_source}), ip={client_ip}")

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            **auth_ctx,
            "verification_mode": "direct_dev_call",
            "token_source": token_source
        },
        headers=cors_headers
    )
