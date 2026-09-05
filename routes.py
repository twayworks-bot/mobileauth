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
async def login_get(request: Request, msg: str = None, error: str = None):
    # If already logged in, redirect to profile
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/auth/profile", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "login.html", {"msg": msg, "error": error})

# Action: Login process
@router.post("/login")
async def login_post(request: Request, phone_number: str = Form(...), pin: str = Form(...)):
    print(f"\n[HTTP POST /auth/login] Received login submission for: phone={phone_number}")
    res = keycloak_api.login_verify_pin(phone_number, pin)
    if res["success"]:
        user = res["user"]
        response = RedirectResponse(url="/auth/profile", status_code=status.HTTP_303_SEE_OTHER)
        # Store user ID in HTTPOnly cookie for secure session management
        response.set_cookie(key="auth_session", value=user["id"], httponly=True, path="/")
        print(f"[HTTP POST /auth/login] Login success. Setting session cookie for user_id={user['id']}")
        return response
    else:
        print(f"[HTTP POST /auth/login] Login failed. Error: {res['error']}")
        return templates.TemplateResponse(request, "login.html", {
            "error": res["error"],
            "phone_number": phone_number
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
    # Check if this user is a manager/admin to display special link in profile
    user_is_mgr = keycloak_api.is_manager(user)
    return templates.TemplateResponse(request, "profile.html", {"user": user, "is_manager": user_is_mgr, "msg": msg, "error": error})

# Action: Profile update
@router.post("/profile")
async def profile_post(request: Request, name: str = Form(...), email: str = Form(...)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/auth/login?error=세션이+만료되었습니다.+다시+로그인하세요.", status_code=status.HTTP_303_SEE_OTHER)
        
    res = keycloak_api.update_profile(user["id"], name, email)
    if res["success"]:
        return RedirectResponse(url="/auth/profile?msg=프로필+정보가+성공적으로+수정되었습니다.", status_code=status.HTTP_303_SEE_OTHER)
    else:
        return templates.TemplateResponse(request, "profile.html", {
            "user": user,
            "error": res["error"]
        })

# UI: Users list (CRUD management - Manager Protected)
@router.get("/users", response_class=HTMLResponse)
async def users_get(request: Request, msg: str = None, error: str = None):
    current_user = get_current_user(request)
    if not current_user or not keycloak_api.is_manager(current_user):
        return RedirectResponse(url="/auth/login?error=사용자+관리+권한이+없습니다.+관리자+계정으로+로그인하세요.", status_code=status.HTTP_303_SEE_OTHER)
        
    users = keycloak_api.list_users()
    
    # Enrich user objects with direct is_manager flags for simple HTML rendering
    for u in users:
        u["is_manager_flag"] = keycloak_api.is_manager(u)
        
    return templates.TemplateResponse(request, "users.html", {
        "users": users, 
        "current_user": current_user, 
        "msg": msg, 
        "error": error
    })

# Action: Delete user (CRUD delete - Manager Protected)
@router.post("/users/{user_id}/delete")
async def users_delete(request: Request, user_id: str):
    current_user = get_current_user(request)
    if not current_user or not keycloak_api.is_manager(current_user):
        return RedirectResponse(url="/auth/login?error=사용자+관리+권한이+없습니다.", status_code=status.HTTP_303_SEE_OTHER)
        
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

# Action: Toggle Manager Privilege (Manager Protected)
@router.post("/users/{user_id}/toggle-manager")
async def users_toggle_manager(request: Request, user_id: str, is_mgr: str = Form(...)):
    current_user = get_current_user(request)
    if not current_user or not keycloak_api.is_manager(current_user):
        return RedirectResponse(url="/auth/login?error=관리자+권한+수정+권한이+없습니다.", status_code=status.HTTP_303_SEE_OTHER)
        
    target_state = is_mgr == "1"
    res = keycloak_api.set_user_manager_status(user_id, target_state)
    
    if res["success"]:
        print(f"[HTTP POST /auth/users/{user_id}/toggle-manager] Successfully updated manager status to {target_state}")
        return RedirectResponse(url="/auth/users?msg=사용자+관리자+권한이+변경되었습니다.", status_code=status.HTTP_303_SEE_OTHER)
    else:
        print(f"[HTTP POST /auth/users/{user_id}/toggle-manager] Failed to update manager status. Error: {res['error']}")
        return RedirectResponse(url=f"/auth/users?error={urllib.parse.quote(res['error'])}", status_code=status.HTTP_303_SEE_OTHER)
