# Keycloak 기반 전화번호 & PIN 공통 인증 시스템 (Web UI, CLI & Local Dev Proxy)

이 프로젝트는 중앙 집중형 Keycloak 서버(`holyseeds` Realm)를 연동하여 **휴대폰 번호, 이름, 이메일, 단방향 해싱(bcrypt/SHA-256)된 PIN 번호**를 기반으로 사용자를 관리하고 인증하는 **통합 인증 프록시 시스템(FastAPI Auth Proxy) 및 웹 UI 서비스**입니다.

다양한 독립 서브 애플리케이션(Booking, Bus, Planning 등)이 자체 로그인/권한 관리 시스템을 중복 구축하지 않도록 일관된 SSO(Single Sign-On) 로그인 게이트웨이와 실시간 세션/권한 검증 API를 제공합니다. 특히 **이원화된 3단계 권한 등급 체계(`manager` 등급 + `developer` 등급)**와 **로컬 개발 시 외부 콜백 제약 없이 공개 인증앱(`holyseeds.thewayworks.net/auth`)에 직접 세션을 검증할 수 있는 로컬 개발 예외 API**를 내장하고 있습니다.

> 📌 **타 애플리케이션 연동 개발 가이드**: 본 인증 시스템의 API를 호출하여 로그인 및 권한 검증을 구현하려는 다른 애플리케이션 개발자는 [**`auth_spec.md`**](file:///C:/Dev/python/keycloak/auth_spec.md)에 수록된 상세 API 규격, 로컬 개발 예외 연동 스펙, 보안 통제 가이드 및 언어/프레임워크별 활용 샘플 코드를 참조하시기 바랍니다.

---

## 🎯 프로젝트 목적 및 핵심 아키텍처

### 1. 백엔드 프록시(Back-end Proxy) 방식의 통합 인증 게이트웨이
- 브라우저를 Keycloak 기본 테마 로그인 창으로 리다이렉트(Standard OIDC Flow)하는 대신, 서비스 고유의 깔끔한 웹 UI(FastAPI + Jinja2)에서 휴대폰 번호와 PIN을 입력받고 백엔드가 Keycloak Admin REST API와 아웃바운드 통신하여 검증을 완료합니다.
- 모든 서브 서비스는 `/auth/login`으로 비로그인/권한 미달 사용자를 유도하고, `/auth/api/verify-session`을 통해 실시간으로 사용자 정보 및 권한 등급을 검증합니다.

### 2. 무만료 오프라인 토큰 및 자가 치유 (Passwordless Self-Healing)
- `.env`에 평문 어드민 비밀번호를 남겨두지 않기 위해 **오프라인 리프레시 토큰(`scope=offline_access`)** 기술을 적용했습니다.
- 최초 1회 [`generate_admin_token.py`](file:///C:/Dev/python/keycloak/generate_admin_token.py) 실행으로 반영구 토큰을 획득하면 `.env`에서 비밀번호가 자동 파기되며, 런타임에 Access Token이 만료(401)될 때마다 [`keycloak_api.py`](file:///C:/Dev/python/keycloak/keycloak_api.py)가 스스로 토큰을 재교환하여 무중단 운영을 보장합니다.

### 3. Keycloak 선언적 유저 프로필 스키마 자동 구성
- Keycloak Target Realm(`holyseeds`)의 Declarative User Profile 제약으로 인해 커스텀 속성이 누락되는 문제를 방지하기 위해, [`configure_keycloak_schema.py`](file:///C:/Dev/python/keycloak/configure_keycloak_schema.py)가 REST API(`GET/PUT /admin/realms/holyseeds/users/profile`)를 호출하여 다음 4가지 핵심 커스텀 속성을 자동 등록합니다:
  - `phoneNumber`: 사용자 휴대폰 번호 (로그인 ID와 동일)
  - `pinNumber`: bcrypt/SHA-256 단방향 해싱된 PIN 번호
  - `manager`: 관리자 등급 플래그 (`"0"` ~ `"2"`)
  - `developer`: 개발자 등급 플래그 (`"0"` ~ `"2"`)

### 4. 이원화된 3단계 사용자 등급 체계 (`manager` & `developer` Flag)
사용자의 비즈니스 운영 권한(**관리자 등급**)과 시스템 개발/디버깅 권한(**개발자 등급**)을 독립적으로 부여하고 조합할 수 있도록 2개의 3단계(`0` ~ `2`) Flag를 운영합니다.

#### ① 관리자 등급 (`manager` attribute: `0` ~ `2`)
| 등급 값 (`role_flag`) | 명칭 (`manager_role`) | 판정 플래그 | 권한 및 역할 범위 |
| :---: | :---: | :--- | :--- |
| **`"0"`** | **`user`** (일반 회원) | `is_manager=False`, `is_super=False` | 본인 프로필 조회/수정, 암호(PIN) 변경, 일반 서브 서비스 이용 |
| **`"1"`** | **`admin`** (일반 관리자) | `is_manager=True`, `is_super=False` | 독립 서브 서비스(Booking, Bus 등)의 비즈니스 관리자 기능 수행 (단, 중앙 사용자 권한 관리 `/auth/users`는 접근 불가) |
| **`"2"`** | **`super`** (최고 관리자) | `is_manager=True`, `is_super=True` | 중앙 사용자 권한 관리 대시보드(`/auth/users`) 접근, 전체 사용자의 `manager` 및 `developer` 등급 부여/회수, 회원 삭제 전용 |

#### ② 개발자 등급 (`developer` attribute: `0` ~ `2`) — *신규*
| 등급 값 (`developer_flag`) | 명칭 (`developer_role`) | 판정 플래그 | 권한 및 역할 범위 |
| :---: | :---: | :--- | :--- |
| **`"0"`** | **`user`** (일반 사용자) | `is_developer=False`, `is_dev_leader=False` | 비개발자 일반 사용자. 로컬 개발 예외 인증 API 및 개발자 전용 기능 접근 불가 |
| **`"1"`** | **`developer`** (일반 개발자) | `is_developer=True`, `is_dev_leader=False` | 서브 애플리케이션 개발자 권한, **로컬 개발용 외부 인증앱 직접 호출(Direct Verification) 예외 API 사용 허용**, 앱 내 개발자 전용 기능 접근 |
| **`"2"`** | **`dev-leader`** (개발 리더) | `is_developer=True`, `is_dev_leader=True` | 리드 개발자 권한 (`developer`의 모든 권한 포함 + 앱 내 `dev-leader` 전용 고급 설정/아키텍처 관리 권한) |

> 🔒 **부트스트랩 최고 계정 보호**: 최상위 계정(`01055787363`)은 항상 `manager="2"`(`super`) 및 `developer="2"`(`dev-leader`)로 자동 판정 및 보호되며, 웹 UI나 API를 통한 권한 강등 및 계정 삭제가 원천 차단됩니다.

### 5. 로컬 개발 환경을 위한 외부 공개 인증앱 직접 호출(Direct Verification) 지원
로컬 PC(`http://localhost:5000` 등)에서 서브 앱을 개발할 때 외부에 배포된 중앙 인증앱(`https://holyseeds.thewayworks.net/auth`)과 도메인이 달라 쿠키가 전달되지 않거나 외부에서 로컬 Callback URL을 호출할 수 없는 제약을 해결하기 위해 **개발자(`developer >= 1`) 전용 로컬 예외 연동 메커니즘**을 제공합니다:
1. **Localhost 세션 브릿지 리다이렉트 (`/auth/login?redirect=http://localhost:5000/callback&dev_mode=1`)**: 로그인한 사용자가 `developer`(`1`) 또는 `dev-leader`(`2`)이고 `redirect` 대상이 `localhost`/`127.0.0.1`인 경우에 한해, 콜백 URL 쿼리에 `?session_id=<UUID>&dev_token=<HMAC서명토큰>`을 전달합니다.
2. **Callback 없는 Direct 로그인 API (`POST /auth/api/dev/direct-login`)**: 로컬 앱이 공개 인증앱으로 전화번호와 PIN을 직접 전송하여 `session_id`, `dev_token` 및 권한 플래그를 즉시 발급받습니다 (`developer >= 1` 필수).
3. **공개 인증앱 Direct Verification API (`GET/POST /auth/api/dev/verify-session`)**: 로컬 앱이 보유한 `session_id` 또는 `dev_token`을 Query, Header(`Authorization: Bearer`, `X-Auth-Session`, `X-Dev-Token`), 또는 Body에 담아 공개 인증앱에 직접 Call하면 즉시 인증 및 권한(`manager`/`developer`) 검증 결과를 반환합니다.

---

## 📁 프로젝트 디렉토리 및 주요 파일 구성

```text
C:\Dev\python\keycloak\
├── main.py                         # FastAPI ASGI 서버 엔트리 포인트 (기본 포트: 5000)
├── routes.py                       # /auth 하위 웹 UI 라우터, 세션 검증 API 및 로컬 개발 예외 API
├── keycloak_api.py                 # 자가 갱신 토큰, 사용자 CRUD, PIN 해싱, manager/developer 등급 및 dev_token 엔진
├── generate_admin_token.py         # 최초 1회 오프라인 토큰 발급 및 .env 내 평문 비밀번호 자동 파기 스크립트
├── configure_keycloak_schema.py    # Keycloak Declarative User Profile 스키마 자동 등록 (phoneNumber, pinNumber, manager, developer)
├── keycloak_auth_cli.py            # CLI 단독 6단계 E2E 시나리오 검증기 (가입 -> 검색 -> PIN검증 -> 수정 -> 삭제)
├── templates/                      # Jinja2 웹 UI 템플릿
│   ├── login.html                  # 전화번호 & PIN 로그인 화면 (redirect, require_role, dev_mode 히든 필드 및 👁️ 토글 지원)
│   ├── signup.html                 # 신규 회원가입 화면
│   ├── profile.html                # 내 프로필 화면 (manager/developer 등급 뱃지, PIN 변경 검증, 개발자용 dev_token 표시)
│   └── users.html                  # Super(2) 전용 사용자 관리 대시보드 (manager 0~2 및 developer 0~2 드롭다운 제어, 삭제)
├── README.md                       # 프로젝트 목적, 사용법, 구현 기능 상세 가이드 (본 문서)
├── auth_spec.md                    # 타 애플리케이션 연동 개발을 위한 API SPEC, 로컬 개발 예외 API, 보안 가이드 및 코드 샘플
└── notes/                          # 프로젝트 요구사항, 계획, 이력, 산출물 기록 관리 디렉토리
    ├── requirement.md              # 초기부터 현재까지의 모든 누적 요구사항 마스터 문서
    ├── history.md                  # 매 개발 요구사항 및 처리 요약 이력
    ├── req_YYYYMMDDHHmm.md         # 각 시점별 사용자 원본 요구사항 및 계획 요약
    ├── plan_YYYYMMDDHHmm.md        # 각 시점별 상세 개발 계획서
    └── result_YYYYMMDDHHmm.md      # 각 시점별 산출물 생성 및 검증 결과 기록
```

---

## 📋 문서 및 산출물 기록 유지 규칙 (`notes/` 운영 표준)

본 프로젝트의 모든 코드 개발 및 처리 요청사항은 지속적인 이력 추적을 위해 아래 규칙을 엄격히 준수하여 기록을 유지합니다:

1. **계획 수립 (`notes/plan_YYYYMMDDHHmm.md`)**: 요구사항 지시 시 첫째로 상세 개발 계획을 수립하여 타임스탬프 기반 파일에 기록합니다.
2. **이력 요약 (`notes/history.md`)**: 매번 개발 요구사항과 처리 결과 요약을 누적 기록합니다.
3. **원본 요구사항 (`notes/req_YYYYMMDDHHmm.md`)**: 사용자의 원본 요구사항 원문과 계획 기록을 보존합니다.
4. **산출물 기록 (`notes/result_YYYYMMDDHHmm.md`)**: 코드, 스키마, 문서 등 모든 산출물 생성 및 테스트 결과를 기록합니다.
5. **누적 요구사항 (`notes/requirement.md`)**: 프로젝트의 모든 요구사항을 빠짐없이 누적하여 기록합니다.
6. **루트 가이드 문서 (`README.md`, `auth_spec.md`)**: 프로젝트 설명과 사용법은 `README.md`에, 타 앱 연동 개발용 API 스펙과 활용 샘플은 `auth_spec.md`에 최신 상태로 유지합니다.

---

## 🚀 설치, 설정 및 구동 가이드

### 1단계: 패키지 설치 및 `.env` 환경 변수 설정
```bash
pip install -r requirements.txt
```
프로젝트 루트의 `.env` 파일에 Keycloak 접속 정보 및 로컬 개발 예외 API 보안 옵션을 설정합니다:
```env
KEYCLOAK_BASE_URL=https://auth.thewayworks.net
KEYCLOAK_REALM=master
KEYCLOAK_TARGET_REALM=holyseeds

# 최초 토큰 발급 시에만 사용 (2단계 실행 후 파일에서 자동 삭제됨)
KEYCLOAK_ADMIN_USER=admin
KEYCLOAK_ADMIN_PASSWORD=your_admin_password
KEYCLOAK_ADMIN_TOKEN=

# 로컬 개발 예외 인증 API 통제 설정 (선택)
ALLOW_LOCAL_DEV_AUTH=true          # 로컬 개발 예외 API 활성화 여부 (true / false)
LOCAL_DEV_API_KEY=                 # 설정 시 X-Dev-Api-Key 헤더 검증 강제 (미설정 시 developer 등급으로만 통제)
DEV_TOKEN_TTL_SECONDS=3600         # 서명된 dev_token 유효기간 (초, 기본 1시간)
```

### 2단계: 무만료 오프라인 토큰 생성 및 패스워드 파기
```bash
python generate_admin_token.py
```
* `.env`에 반영구 오프라인 토큰(`KEYCLOAK_ADMIN_TOKEN`)이 기록되고 `KEYCLOAK_ADMIN_PASSWORD` 줄은 즉시 삭제됩니다.

### 3단계: Keycloak 커스텀 속성 스키마 자동 구성
```bash
python configure_keycloak_schema.py
```
* `holyseeds` Realm의 User Profile 스키마에 `phoneNumber`, `pinNumber`, `manager`, `developer` 속성을 자동 등록합니다.

### 4단계: CLI 단독 E2E 연동 테스트
```bash
python keycloak_auth_cli.py
```

### 5단계: 통합 인증 웹 서버 구동
```bash
python main.py
# 또는
uvicorn main:app --host 0.0.0.0 --port 5000 --reload
```
구동 후 주요 접속 경로:
- **로그인 게이트웨이**: `http://localhost:5000/auth/login` (루트 `/` 또는 `/auth` 접속 시 자동 리다이렉트)
- **신규 회원가입**: `http://localhost:5000/auth/signup`
- **내 프로필 및 PIN 변경 / 개발자 토큰 확인**: `http://localhost:5000/auth/profile`
- **사용자 권한 관리 대시보드 (`Super` 전용)**: `http://localhost:5000/auth/users`
- **세션 검증 API**: `http://localhost:5000/auth/api/verify-session`
- **로컬 개발용 예외 Direct 로그인 API**: `POST http://localhost:5000/auth/api/dev/direct-login`
- **로컬 개발용 예외 Direct 세션 검증 API**: `GET/POST http://localhost:5000/auth/api/dev/verify-session`

---

## 🛠️ 주요 구현 기능 요약

1. **회원가입 및 전화번호/PIN 로그인**:
   - 휴대폰 번호를 ID(`username` 및 `attributes.phoneNumber`)로 사용하며, PIN 번호는 `bcrypt`(미설치 시 Salted SHA-256)로 단방향 해싱하여 `attributes.pinNumber`에 안전하게 저장합니다.
   - 로그인 시 `redirect` 및 `require_role` 파라미터를 지원하여 권한 충족 여부를 즉시 검사하고 대상 서비스로 리다이렉트합니다.
2. **내 프로필 관리 및 암호(PIN) 변경**:
   - 로그인한 사용자의 관리자 등급(`user`/`admin`/`super`)과 개발자 등급(`user`/`developer`/`dev-leader`)을 시각적 뱃지로 표시합니다.
   - 현재 PIN 검증, 새 PIN 및 확인 PIN 실시간 일치/자리수(4자리 이상) 검증, 비밀번호 보기/숨기기(👁️) 토글을 제공합니다.
   - 개발자 등급(`developer` 또는 `dev-leader`) 계정으로 로그인한 경우, 로컬 개발 시 외부 공개 인증앱에 즉시 붙여넣어 검증할 수 있는 **서명된 `dev_token`**을 프로필 화면에서 바로 확인할 수 있습니다.
3. **최고 관리자(`Super`) 전용 사용자 권한 거버넌스 (`/auth/users`)**:
   - `manager` 등급이 `2`(`super`)인 최고 관리자만 접근 가능하며, 일반 관리자(`1`)나 일반 회원(`0`)의 접근을 엄격히 차단합니다.
   - 전체 사용자의 **관리자 등급(`0`: 일반 user, `1`: admin, `2`: super)**과 **개발자 등급(`0`: 일반 user, `1`: developer, `2`: dev-leader)**을 각각 드롭다운으로 실시간 변경하고 계정을 삭제할 수 있습니다.
