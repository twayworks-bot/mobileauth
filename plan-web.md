# Web UI Auth Service Development Plan (plan-web.md)

## 1. 개요 및 목표
`requirements.md`의 요구사항을 바탕으로 `https://holyseeds.thewayworks.net/auth` 하위에서 공통으로 동작할 웹 UI 기반의 인증 시스템(회원가입, 로그인, 프로필 관리, 기본 사용자 CRUD)을 구축합니다.

## 2. 로컬 테스트 NAT/Callback 이슈 분석 및 해결 전략
**이슈:** 로컬(localhost)에서 개발/테스트 시 NAT 환경으로 인해 외부 서버(`auth.thewayworks.net`)로부터 OAuth2 Callback(Redirect)을 정상적으로 수신하기 어렵거나 설정이 번거로운 문제가 있습니다.
**해결 전략 (Back-end Proxy 방식):**
- Keycloak의 기본 로그인 페이지로 리다이렉트(Standard Flow)하지 않습니다.
- FastAPI 백엔드에서 자체 HTML 폼(Jinja2)을 서빙하고, 사용자(브라우저)는 로컬 백엔드로 자격 증명(휴대폰 번호, PIN)을 POST합니다.
- **FastAPI 백엔드 서버가 Keycloak Admin API로 아웃바운드(Outbound) REST 요청을 보냅니다.**
- 아웃바운드 트래픽이므로 NAT 환경에서도 문제없이 통신이 가능하며, 인바운드 Callback 수신 포트를 열 필요가 완전히 사라집니다.

## 3. 기술 스택
- **Backend Framework**: FastAPI
- **Template Engine**: Jinja2 (HTML 렌더링)
- **Session/Security**: HTTPOnly Cookie, JWT(Keycloak Token 보관)
- **CSS/UI**: 심플한 Bootstrap 또는 순수 CSS 활용

## 4. API & UI 엔드포인트 설계 (Prefix: `/auth`)
모든 경로는 FastAPI의 `APIRouter(prefix="/auth")`를 사용하여 구성합니다.

| 엔드포인트 | Method | 역할 | Keycloak 연동 (Backend Proxy) |
| --- | --- | --- | --- |
| `/auth/signup` | GET | 회원가입 폼 화면 제공 | - |
| `/auth/signup` | POST | 폼 데이터 수신 및 가입 처리 | Admin API (`POST /users`) 활용, PIN 암호화 저장 |
| `/auth/login` | GET | 로그인 폼 화면 제공 | - |
| `/auth/login` | POST | 폼 데이터 수신 및 인증 처리 | Admin API로 사용자 검색 -> PIN 검증 -> 세션 쿠키 발급 |
| `/auth/profile` | GET | 내 프로필 조회 화면 | Admin API (`GET /users/{id}`) 로 상세 정보 렌더링 |
| `/auth/profile` | POST | 프로필 수정 요청 처리 | Admin API (`PUT /users/{id}`) 활용 |
| `/auth/users` | GET | (관리자) 유저 목록 화면 | Admin API (`GET /users`) 페이징 렌더링 |
| `/auth/users/{id}/delete`| POST | 사용자 삭제 (CRUD) | Admin API (`DELETE /users/{id}`) |
| `/auth/logout` | GET/POST| 로그아웃 및 세션 파기 | 브라우저 세션 쿠키 삭제 |

## 5. 구현 단계 (Implementation Steps)
1. **계획서 작성**: `plan-web.md`를 프로젝트 폴더에 생성합니다. (완료)
2. **웹 프로젝트 스캐폴딩**:
   - `requirements.txt`에 FastAPI, uvicorn, jinja2, python-multipart, python-jose 등 추가.
   - `main.py`에 FastAPI 앱 생성 및 `/auth` 라우터 마운트.
   - `templates/` 디렉토리에 기본 HTML 구조(login.html, signup.html 등) 생성.
3. **Keycloak API 연동 계층화 (`keycloak_api.py`)**:
   - 이전에 만든 CLI 스크립트(`keycloak_auth_cli.py`)의 로직(사용자 검색, PIN 해시 검증, 유저 생성/수정/삭제)을 재사용 가능한 서비스 클래스/함수로 분리.
4. **UI 라우터 및 세션 구현 (`routes.py`)**:
   - 쿠키 기반의 임시 세션(또는 JWT 암호화 쿠키) 적용.
   - 인증이 필요한 페이지(`profile`, `users`)에 대한 의존성 주입(Dependency) 기반 접근 제어 구현.
5. **엔드투엔드(E2E) 로컬 검증**:
   - `uvicorn main:app --reload`로 서버 실행.
   - 브라우저를 통해 `localhost:8000/auth/login` 등에 접속하여 NAT 제약 없이 가입부터 프로필 수정까지 동작함을 테스트.

## 6. 기대 효과
- **NAT 종속성 탈피**: Callback 서버 불필요, 방화벽 및 공유기 환경 제약 없이 즉시 로컬 개발 가능.
- **UI 일관성 확보**: Keycloak 테마를 커스텀할 필요 없이, 서비스(holyseeds) 자체의 고유 UI/UX 룩앤필(Look and Feel)로 인증 페이지를 완벽하게 통합.
