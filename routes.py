from fastapi import APIRouter, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
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

# UI: Login page
@router.get("/login", response_class=HTMLResponse)
async def login_get(request: Request, msg: str = None, error: str = None, redirect: str = None):
    # If already logged in, redirect to profile
    user = get_current_user(request)
    if user:
        url = redirect if redirect else "/auth/profile"
        return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "login.html", {"msg": msg, "error": error, "redirect": redirect})

# Action: Login process
@router.post("/login")
async def login_post(request: Request, phone_number: str = Form(...), pin: str = Form(...), redirect: str = Form(None)):
    print(f"\n[HTTP POST /auth/login] Received login submission for: phone={phone_number}")
    res = keycloak_api.login_verify_pin(phone_number, pin)
    if res["success"]:
        user = res["user"]
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
            "redirect": redirect
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
    
    return templates.TemplateResponse(request, "profile.html", {
        "user": user,
        "role_flag": role_flag,
        "is_manager": user_is_mgr,
        "is_super": user_is_super,
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

    cur_p = (current_pin or "").strip()
    new_p = (new_pin or "").strip()
    cnf_p = (confirm_pin or "").strip()
    
    pin_changed = False
    
    # Check if PIN change was attempted
    if cur_p or new_p or cnf_p:
        if not cur_p:
            return templates.TemplateResponse(request, "profile.html", {
                "user": user, "role_flag": role_flag, "is_manager": user_is_mgr, "is_super": user_is_super,
                "error": "PIN 번호를 변경하려면 현재 PIN 번호를 입력해야 합니다."
            })
        if not new_p:
            return templates.TemplateResponse(request, "profile.html", {
                "user": user, "role_flag": role_flag, "is_manager": user_is_mgr, "is_super": user_is_super,
                "error": "새로운 PIN 번호를 입력해 주세요."
            })
        if not cnf_p:
            return templates.TemplateResponse(request, "profile.html", {
                "user": user, "role_flag": role_flag, "is_manager": user_is_mgr, "is_super": user_is_super,
                "error": "새 PIN 번호 확인을 입력해 주세요."
            })
        if new_p != cnf_p:
            return templates.TemplateResponse(request, "profile.html", {
                "user": user, "role_flag": role_flag, "is_manager": user_is_mgr, "is_super": user_is_super,
                "error": "새 PIN 번호와 확인 번호가 일치하지 않습니다."
            })
        if len(new_p) < 4:
            return templates.TemplateResponse(request, "profile.html", {
                "user": user, "role_flag": role_flag, "is_manager": user_is_mgr, "is_super": user_is_super,
                "error": "새 PIN 번호는 최소 4자리 이상이어야 합니다."
            })
            
        # Verify current PIN against user's stored hash
        if not keycloak_api.verify_user_pin(user, cur_p):
            return templates.TemplateResponse(request, "profile.html", {
                "user": user, "role_flag": role_flag, "is_manager": user_is_mgr, "is_super": user_is_super,
                "error": "현재 PIN 번호가 일치하지 않습니다."
            })
            
        pin_res = keycloak_api.update_pin(user["id"], new_p)
        if not pin_res["success"]:
            return templates.TemplateResponse(request, "profile.html", {
                "user": user, "role_flag": role_flag, "is_manager": user_is_mgr, "is_super": user_is_super,
                "error": pin_res["error"]
            })
        pin_changed = True

    # Update basic profile info (name, email)
    res = keycloak_api.update_profile(user["id"], name, email)
    if res["success"]:
        msg = "프로필 정보 및 PIN 번호가 성공적으로 변경되었습니다." if pin_changed else "프로필 정보가 성공적으로 수정되었습니다."
        return RedirectResponse(url=f"/auth/profile?msg={urllib.parse.quote(msg)}", status_code=status.HTTP_303_SEE_OTHER)
    else:
        return templates.TemplateResponse(request, "profile.html", {
            "user": user,
            "role_flag": role_flag,
            "is_manager": user_is_mgr,
            "is_super": user_is_super,
            "error": res["error"]
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
    
    # Enrich user objects with role flags for HTML rendering
    for u in users:
        u_flag = keycloak_api.get_user_role_flag(u)
        u["role_flag"] = u_flag
        u["is_manager_flag"] = (u_flag in ("1", "2"))
        u["is_super_flag"] = (u_flag == "2")
        
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


# API Action: Verify Session (called by other services like booking3)
@router.get("/api/verify-session")
async def verify_session(request: Request, session_id: str = None, require_role: str = None):
    if not session_id:
        session_id = request.cookies.get("auth_session")
    if not session_id:
        return {"valid": False, "is_manager": False, "is_super": False, "error": "No session ID provided", "has_required_role": False}
    
    user = keycloak_api.find_user_by_id(session_id)
    if not user:
        return {"valid": False, "is_manager": False, "is_super": False, "error": "User not found", "has_required_role": False}
    
    role_flag = keycloak_api.get_user_role_flag(user)
    is_mgr = keycloak_api.is_manager(user)
    is_spr = keycloak_api.is_super(user)
    
    roles = ["user"]
    if is_mgr:
        roles.extend(["manager", "admin"])
    if is_spr:
        roles.extend(["super", "super_admin"])
        
    has_required_role = True
    if require_role:
        if require_role in ("super", "super_admin", "role:super"):
            has_required_role = is_spr
        elif require_role in ("manager", "admin", "role:manager", "role:admin"):
            has_required_role = is_mgr
        else:
            attributes = user.get("attributes", {})
            has_required_role = attributes.get(require_role, ["0"])[0] == "1"
            
    return {
        "valid": True,
        "is_manager": is_mgr,
        "is_super": is_spr,
        "role_flag": role_flag,
        "roles": roles,
        "has_required_role": has_required_role,
        "user": {
            "id": user.get("id"),
            "username": user.get("username"),
            "name": user.get("firstName"),
            "email": user.get("email")
        }
    }
