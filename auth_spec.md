# Keycloak 기반 멀티 서비스 인증 프록시 API 스펙 및 연동 개발 가이드 (auth_spec.md)

본 문서는 중앙 집중형 Keycloak 인증 서버를 래핑한 **통합 인증 프록시 서비스(FastAPI Auth Proxy, 예: `https://holyseeds.thewayworks.net/auth`)**를 활용하여, 다양한 독립 서브 애플리케이션(Booking, Bus, Planning 등)에서 로그인, 사용자 등급(`manager` 등급 & `developer` 등급) 검증, 그리고 **로컬 개발 환경(`http://localhost:*`)에서의 직접 인증 검증(Direct Verification)**을 구현하기 위한 **공통 API 명세서 및 개발 지원 가이드**입니다.

---

## 1. 시스템 아키텍처 및 인증 흐름 개요

전체 시스템은 **사용자 브라우저**, **독립 서브 애플리케이션(배포 서버 또는 로컬 개발 PC)**, **중앙 인증 프록시 서버(`holyseeds.thewayworks.net/auth`)**, 그리고 **Keycloak 인증 서버(`auth.thewayworks.net`)**로 구성됩니다.

```text
+--------------------+        (1) 비로그인 / 권한 미달 시 리다이렉트   +----------------------------+
|                    | ----------------------------------------------> |                            |
|   사용자 브라우저  |                                                 |     중앙 인증 프록시 서버  |
|                    | <---------------------------------------------- |  (FastAPI: /auth/*)        |
+--------------------+   (4) 인증 성공 후 콜백 (쿠키 또는 로컬 토큰)   +----------------------------+
  |                ^                                                          |               ^
  | (2) 앱 접속    | (5) 권한별 화면/API 응답                                 |               |
  v                |                                                          v               |
+--------------------+   (3) 실시간 세션 & manager/developer 등급 검증 +----------------------------+
| 독립 서브 서비스   | ----------------------------------------------> |                            |
| (운영 서버 또는    |   GET /auth/api/verify-session                  |     Keycloak Admin API     |
|  로컬 localhost)   |   또는 /auth/api/dev/verify-session (로컬 개발) |     (holyseeds Realm)      |
+--------------------+ <---------------------------------------------- +----------------------------+
```

---

## 2. 이원화된 사용자 권한 등급 체계 (`manager` & `developer` Flag)

인증 프록시는 모든 사용자에 대해 **관리자 등급(`manager`)**과 **개발자 등급(`developer`)** 두 가지 축의 권한 플래그(`"0"` ~ `"2"`)를 관리하고 검증 API 응답으로 반환합니다. 서브 애플리케이션은 두 플래그를 조합하여 세밀한 접근 제어(RBAC)를 수행할 수 있습니다.

### 2.1. 관리자 등급 (`manager` attribute: `"0"` ~ `"2"`)
| Flag 값 | 표준 명칭 (`manager_role`) | Boolean 필드 | `require_role` 식별자 | 권한 설명 및 활용 기준 |
| :---: | :---: | :--- | :--- | :--- |
| **`"0"`** | **`user`** | `is_manager: false`<br>`is_super: false` | `user` | 일반 회원. 기본 서비스 이용 및 본인 프로필/PIN 관리 |
| **`"1"`** | **`admin`** | `is_manager: true`<br>`is_super: false` | `manager`, `admin`, `role:manager`, `role:admin` | 서브 서비스(Booking, Bus 등)의 비즈니스 관리자 메뉴 접근 허용 |
| **`"2"`** | **`super`** | `is_manager: true`<br>`is_super: true` | `super`, `super_admin`, `role:super` | 최고 관리자. 중앙 사용자 권한 관리(`/auth/users`) 및 전체 서비스 최상위 통제 권한 (`is_manager`도 상위 호환으로 `true`) |

### 2.2. 개발자 등급 (`developer` attribute: `"0"` ~ `"2"`)
| Flag 값 | 표준 명칭 (`developer_role`) | Boolean 필드 | `require_role` 식별자 | 권한 설명 및 활용 기준 |
| :---: | :---: | :--- | :--- | :--- |
| **`"0"`** | **`user`** | `is_developer: false`<br>`is_dev_leader: false` | - | 일반 사용자(비개발자). 개발자 전용 메뉴 및 **로컬 개발 예외 인증 API 사용 불가** |
| **`"1"`** | **`developer`** | `is_developer: true`<br>`is_dev_leader: false` | `developer`, `role:developer` | 일반 개발자. 앱 내 디버그/테스트 기능 접근 및 **로컬 개발 시 공개 인증앱 Direct Verification 예외 API 사용 허용** |
| **`"2"`** | **`dev-leader`** | `is_developer: true`<br>`is_dev_leader: true` | `dev-leader`, `dev_leader`, `role:dev-leader` | 개발 리더 (`developer`의 모든 권한 포함 + 개발 리더 전용 시스템 설정/배포 관리 권한) |

---

## 3. 표준 HTTP 인터페이스 및 API 상세 규격

### 3.1. 통합 로그인 게이트웨이 (`GET / POST /auth/login`)
비로그인 사용자이거나 특정 권한(`manager`, `super`, `developer`, `dev-leader` 등)이 부족한 사용자를 로그인 화면으로 유도할 때 호출합니다.

* **URL**: `/auth/login`
* **Method**: `GET` (로그인 화면 렌더링), `POST` (자격 증명 제출 및 검증)
* **Query / Form Parameters**:

| 파라미터명 | 타입 | 필수 | 설명 | 예시 값 |
| :--- | :--- | :---: | :--- | :--- |
| `redirect` | String | 권장 | 로그인 및 권한 검증 완료 후 이동할 콜백 URL | `/reserve/admin`, `http://localhost:5000/auth/callback` |
| `require_role` | String | 선택 | 로그인 시점에 검증할 필수 권한 등급 (`manager`, `super`, `developer`, `dev-leader`, 또는 커스텀 속성명) | `manager`, `developer`, `dev-leader`, `bus_admin` |
| `dev_mode` | String | 선택 | 로컬 개발 브릿지 모드 활성화 (`"1"` 또는 `"true"`). `redirect`가 `localhost`/`127.0.0.1`일 때 쿼리로 `session_id`와 `dev_token`을 전달받음 (`developer >= 1` 계정만 허용) | `1` |
| `error` | String | 선택 | 로그인 화면 상단 경고 박스에 표시할 안내 메시지 | `개발자+권한이+필요합니다.` |
| `msg` | String | 선택 | 로그인 화면 상단 알림 박스에 표시할 성공/안내 메시지 | `로그아웃+되었습니다.` |

---

### 3.2. 통합 세션 및 권한 검증 API (`GET /auth/api/verify-session`)
서브 애플리케이션 백엔드에서 현재 사용자의 세션 유효성, 관리자 등급(`manager`), 개발자 등급(`developer`), 그리고 특정 요구 권한(`require_role`) 충족 여부를 실시간으로 확인할 때 호출합니다.

* **URL**: `/auth/api/verify-session`
* **Method**: `GET`
* **세션 전달 방식 (우선순위 순 지원)**:
  1. `dev_token` Query 파라미터 (`?dev_token=...`) 또는 `X-Dev-Token` 헤더
  2. `Authorization: Bearer <session_id 또는 dev_token>` 헤더
  3. `session_id` Query 파라미터 (`?session_id=...`) 또는 `X-Auth-Session` 헤더
  4. 브라우저 쿠키의 `auth_session` 값
* **Query Parameters**:

| 파라미터명 | 위치 | 타입 | 필수 | 설명 |
| :--- | :--- | :--- | :---: | :--- |
| `session_id` | Query / Header / Cookie | String | 선택 | 사용자의 세션 UUID (`auth_session` 쿠키 값) |
| `dev_token` | Query / Header | String | 선택 | HMAC-SHA256으로 서명된 단기 개발 토큰 |
| `require_role` | Query | String | 선택 | 검증할 요구 권한 (`user`, `manager`, `admin`, `super`, `developer`, `dev-leader`, 또는 서비스별 커스텀 role) |

* **Response (`200 OK` - 인증 성공 시)**:
  ```json
  {
    "valid": true,
    "role_flag": "1",
    "manager_flag": "1",
    "manager_role": "admin",
    "is_manager": true,
    "is_super": false,
    "developer_flag": "2",
    "developer_role": "dev-leader",
    "is_developer": true,
    "is_dev_leader": true,
    "roles": [
      "user",
      "manager",
      "admin",
      "developer",
      "dev-leader",
      "dev_leader"
    ],
    "has_required_role": true,
    "user": {
      "id": "e44d3204-1f1d-400a-b33c-3965fc71295c",
      "username": "01012345678",
      "name": "홍길동",
      "email": "gildong@thewayworks.net"
    }
  }
  ```
* **Response (`200 OK` - 세션 무효 또는 미로그인 시)**:
  ```json
  {
    "valid": false,
    "is_manager": false,
    "is_super": false,
    "is_developer": false,
    "is_dev_leader": false,
    "role_flag": "0",
    "developer_flag": "0",
    "developer_role": "user",
    "error": "No session ID or dev_token provided",
    "has_required_role": false
  }
  ```

---

## 4. 로컬 개발 환경을 위한 외부 공개 인증앱 직접 호출(Direct Call) 예외 API 스펙

### 4.1. 배경 및 해결 원리
개발자가 로컬 PC(예: `http://localhost:5000`)에서 신규 서브 앱을 개발할 때, 외부에 배포된 중앙 인증앱(예: `https://holyseeds.thewayworks.net/auth`)을 연동하면 다음 문제가 발생합니다:
1. **쿠키 도메인 불일치**: `holyseeds.thewayworks.net`에서 발급된 `auth_session` 쿠키는 브라우저 보안 정책상 `http://localhost:5000`으로 전송되지 않습니다.
2. **외부 -> 로컬 인바운드 콜백 불가**: 외부 클라우드 서버는 개발자 공유기 내부의 `http://localhost:5000`을 직접 호출할 수 없습니다.

이를 해결하기 위해 본 인증 시스템은 **개발자 등급(`developer` flag == `"1"` 또는 `"2"`) 계정으로 제한된 로컬 개발 전용 예외 API 및 세션 전달 브릿지**를 제공합니다. 로컬 앱은 외부 공개 인증앱 URL로부터 인증 세션 정보(`session_id` 및 서명된 `dev_token`)를 그대로 받아서 공개 인증앱에 직접 Outbound Call을 보내 인증 Verification을 완료할 수 있습니다.

```text
[로컬 개발 시나리오 A: 브라우저 리다이렉트 브릿지 + Direct Verification]
1. 로컬 앱(http://localhost:5000) 접속 -> 미인증 감지
2. 브라우저를 https://holyseeds.thewayworks.net/auth/login?redirect=http://localhost:5000/auth/callback&dev_mode=1 로 이동
3. 공개 인증앱이 로그인 검증 + 사용자의 developer 등급(>=1) 확인 + redirect가 localhost인지 확인
4. 브라우저를 http://localhost:5000/auth/callback?session_id=<UUID>&dev_token=<서명토큰> 으로 303 리다이렉트
5. 로컬 앱(/auth/callback)이 받은 dev_token(또는 session_id)을 로컬 쿠키에 저장
6. 로컬 앱이 https://holyseeds.thewayworks.net/auth/api/dev/verify-session 에 직접 Call 하여 인증 Verification 완료!

[로컬 개발 시나리오 B: 리다이렉트조차 없이 로컬 앱에서 공개 인증앱으로 Direct Login & Verify]
1. 로컬 앱/CLI가 POST https://holyseeds.thewayworks.net/auth/api/dev/direct-login 호출 (phone_number, pin)
2. 공개 인증앱이 developer 등급(>=1) 확인 후 session_id + dev_token + 권한 정보 즉시 JSON 반환
3. 이후 로컬 앱은 GET/POST https://holyseeds.thewayworks.net/auth/api/dev/verify-session 으로 직접 검증 수행!
```

---

### 4.2. 예외 API 1: 로컬 개발용 Direct 로그인 및 세션 발급 (`POST /auth/api/dev/direct-login`)
콜백 리다이렉트 없이 로컬 앱에서 외부 공개 인증앱으로 자격 증명을 직접 호출하여 인증 세션 정보를 받아오는 예외 API입니다.

* **URL**: `https://holyseeds.thewayworks.net/auth/api/dev/direct-login`
* **Method**: `POST` (`application/json` 또는 `application/x-www-form-urlencoded`, CORS 지원)
* **Headers**:
  * `Content-Type: application/json`
  * `X-Dev-Api-Key: <LOCAL_DEV_API_KEY>` *(서버 `.env`에 `LOCAL_DEV_API_KEY`가 설정된 경우에만 필수)*
* **Request Body**:
  ```json
  {
    "phone_number": "01012345678",
    "pin": "1234",
    "require_role": "developer"
  }
  ```
* **보안 검증 규칙**:
  * 전화번호/PIN이 일치하더라도 해당 계정의 `developer` flag가 `"0"`(일반 user)이면 **`403 Forbidden`**을 반환하여 차단합니다. 오직 `developer`(`"1"`) 또는 `dev-leader`(`"2"`)만 호출 가능합니다.
* **Response (`200 OK`)**:
  ```json
  {
    "valid": true,
    "dev_mode": true,
    "session_id": "e44d3204-1f1d-400a-b33c-3965fc71295c",
    "dev_token": "ZTQ0ZDMyMDQtMWYxZC00MDBhLWIzM2MtMzk2NWZjNzEyOTVj.1795245000.8f3b2c...",
    "expires_in": 3600,
    "role_flag": "1",
    "manager_flag": "1",
    "manager_role": "admin",
    "is_manager": true,
    "is_super": false,
    "developer_flag": "1",
    "developer_role": "developer",
    "is_developer": true,
    "is_dev_leader": false,
    "roles": ["user", "manager", "admin", "developer"],
    "has_required_role": true,
    "user": {
      "id": "e44d3204-1f1d-400a-b33c-3965fc71295c",
      "username": "01012345678",
      "name": "홍길동",
      "email": "gildong@thewayworks.net"
    }
  }
  ```

---

### 4.3. 예외 API 2: 로컬 앱 -> 공개 인증앱 직접 호출 세션 검증 (`GET / POST /auth/api/dev/verify-session`)
로컬 앱이 보유한 인증 세션 정보(`session_id` 또는 `dev_token`)를 외부에 공개된 인증앱 URL에 직접 전송하여 인증 Verification을 수행하는 예외 API입니다.

* **URL**: `https://holyseeds.thewayworks.net/auth/api/dev/verify-session`
* **Method**: `GET` 또는 `POST` (로컬 SPA/프론트엔드 직접 호출을 위한 `OPTIONS` CORS Preflight 포함)
* **세션 정보 전달 방법 (택 1)**:
  1. **Query Parameter**: `?dev_token=<토큰>&require_role=developer` 또는 `?session_id=<UUID>&require_role=manager`
  2. **Authorization Header**: `Authorization: Bearer <dev_token 또는 session_id>`
  3. **Custom Header**: `X-Dev-Token: <dev_token>` 또는 `X-Auth-Session: <session_id>`
  4. **POST JSON Body**: `{"dev_token": "...", "session_id": "...", "require_role": "developer"}`
* **보안 검증 규칙**:
  * 조회된 세션 소유자의 `developer` flag가 `"1"`(`developer`) 또는 `"2"`(`dev-leader`)인 경우에만 `200 OK`와 함께 `valid: true`를 반환합니다. 일반 사용자(`developer_flag == "0"`)의 `session_id`가 유출되어 이 예외 API로 호출되더라도 **`403 Forbidden`**으로 거부됩니다.
* **Response (`200 OK`)**:
  ```json
  {
    "valid": true,
    "verification_mode": "direct_dev_call",
    "token_source": "dev_token",
    "role_flag": "0",
    "manager_flag": "0",
    "manager_role": "user",
    "is_manager": false,
    "is_super": false,
    "developer_flag": "2",
    "developer_role": "dev-leader",
    "is_developer": true,
    "is_dev_leader": true,
    "roles": ["user", "developer", "dev-leader", "dev_leader"],
    "has_required_role": true,
    "user": {
      "id": "e44d3204-1f1d-400a-b33c-3965fc71295c",
      "username": "01012345678",
      "name": "홍길동",
      "email": "gildong@thewayworks.net"
    }
  }
  ```

---

## 5. 로컬 개발 예외 API 보안 통제 가이드 (Security Control Guidelines)

로컬 개발 편의를 위해 외부 공개 인증앱에 직접 세션 검증을 허용할 때는 다음 **5단계 보안 통제 원칙**을 반드시 준수하여 운영해야 합니다. 본 시스템에는 이 5가지 통제 장치가 기본 구현되어 있습니다.

### 5.1. 개발자 등급(`developer >= 1`) 기반 권한 게이트 (Role-Based Gatekeeping)
* **원칙**: 로컬 예외 API(`/auth/api/dev/direct-login`, `/auth/api/dev/verify-session`, 그리고 `localhost`로의 세션 쿼리 리다이렉트)는 오직 `developer` 속성이 `"1"`(`developer`) 또는 `"2"`(`dev-leader`)로 부여된 계정만 사용할 수 있습니다.
* **운영 가이드**: 최고 관리자(`Super`, `manager="2"`)는 `/auth/users` 대시보드에서 실제 개발을 수행하는 인원에게만 `developer (1)` 또는 `dev-leader (2)` 등급을 부여하고, 개발이 종료되거나 퇴사/보직 변경 시 즉시 `일반 user (0)`으로 회수하십시오.

### 5.2. Localhost Loopback 전용 Redirect 화이트리스트 (Open Redirect 원천 차단)
* **원칙**: `/auth/login?redirect=...&dev_mode=1`을 통해 URL 쿼리 파라미터로 `session_id`와 `dev_token`을 전달하는 기능은 정규식 `^https?://(localhost|127\.0\.0\.1)(:\d+)?(/.*)?$`에 일치하는 로컬 루프백 주소로만 허용됩니다.
* **효과**: 외부 공격자가 피싱 링크(`https://holyseeds.thewayworks.net/auth/login?redirect=https://evil.com&dev_mode=1`)를 유포하더라도, 인증 서버가 로컬호스트가 아님을 감지하여 세션 토큰 전달 및 리다이렉트를 즉시 차단합니다.

### 5.3. HMAC-SHA256 서명 및 만료 시간(TTL)이 적용된 `dev_token` 사용 권장
* **원칙**: 로컬 개발 시 영구적인 사용자 UUID(`session_id`)를 직접 URL이나 설정 파일에 하드코딩하는 대신, 서버 비밀키(`DEV_AUTH_SECRET`)로 HMAC-SHA256 서명되고 만료 시각(기본 1시간, `DEV_TOKEN_TTL_SECONDS=3600`)이 내장된 `dev_token`을 우선 사용하십시오.
* **확인 방법**: 개발자 계정으로 로그인 후 `https://holyseeds.thewayworks.net/auth/profile` 하단의 **[로컬 개발자 전용 Direct Verification 토큰]** 박스에서 1시간 유효한 `dev_token`을 즉시 복사하여 로컬 테스트에 사용할 수 있습니다.

### 5.4. 환경 변수 마스터 스위치 및 이중 잠금 API Key (`ALLOW_LOCAL_DEV_AUTH`, `LOCAL_DEV_API_KEY`)
* **마스터 스위치**: 로컬 개발 기간이 끝나거나 보안 감사 기간에는 공개 인증 서버의 `.env`에서 `ALLOW_LOCAL_DEV_AUTH=false`로 설정하여 모든 로컬 개발 예외 API를 즉시 비활성화할 수 있습니다.
* **이중 잠금 (Dual-Lock)**: 사내 개발팀만 로컬 예외 API를 호출하도록 더욱 강력히 통제하려면 서버 `.env`에 `LOCAL_DEV_API_KEY=사내비밀키`를 설정하십시오. 이 값이 설정되면 로컬 앱이 `X-Dev-Api-Key` 헤더(또는 `dev_api_key` 파라미터)를 함께 보내야만 예외 API가 응답합니다.

### 5.5. 감사 로그 모니터링 (`[DEV-AUTH AUDIT]`)
* 모든 로컬 예외 인증 요청(승인 및 거부 모두)은 서버 표준 출력 로그에 `[DEV-AUTH AUDIT]` 태그와 함께 사용자 전화번호, 개발자 등급, 클라이언트 IP가 기록됩니다. 비정상적인 반복 실패 로그가 발생하는지 주기적으로 점검하십시오.

---

## 6. 다른 애플리케이션 연동 개발 샘플 코드 (Implementation Samples)

다른 서브 애플리케이션(예: 로컬 `http://localhost:5000`에서 개발 중이며 배포 시 `https://holyseeds.thewayworks.net/booking`으로 운영되는 FastAPI 웹 앱)에서 본 인증 시스템을 연동하는 **표준 구현 템플릿**입니다.

### 6.1. [Python / FastAPI] 운영 환경 & 로컬 개발 환경 통합 인증 연동 샘플

아래 코드는 로컬에서 실행 중일 때도 공개 인증앱(`https://holyseeds.thewayworks.net/auth`)으로부터 직접 세션(`session_id` / `dev_token`)을 받아 Verification을 수행하고, `manager` 등급 및 `developer` 등급에 따라 라우트 권한을 제어하는 완벽한 예제입니다.

```python
import os
import urllib.request
import urllib.parse
import json
from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import RedirectResponse

app = FastAPI(title="Sub-Service App (Local & Prod Compatible)")

# 공개 인증 서버 주소 (로컬 개발 시에도 외부 공개 인증앱을 직접 바라보도록 설정 가능)
PUBLIC_AUTH_BASE_URL = os.getenv("AUTH_BASE_URL", "https://holyseeds.thewayworks.net").rstrip("/")
LOCAL_APP_BASE_URL = os.getenv("LOCAL_APP_BASE_URL", "http://localhost:5000").rstrip("/")
IS_LOCAL_DEV = "localhost" in LOCAL_APP_BASE_URL or "127.0.0.1" in LOCAL_APP_BASE_URL
LOCAL_DEV_API_KEY = os.getenv("LOCAL_DEV_API_KEY", "")


def call_public_auth_verify(token_or_session: str, require_role: str = None) -> dict:
    """
    공개 인증앱(holyseeds.thewayworks.net/auth)에 직접 Call하여 인증 세션 및 권한(manager/developer)을 검증합니다.
    - 로컬 개발 모드일 때는 /auth/api/dev/verify-session 호출
    - 운영 모드일 때는 /auth/api/verify-session 호출
    """
    if not token_or_session:
        return {"valid": False, "error": "No session token"}

    endpoint = "/auth/api/dev/verify-session" if IS_LOCAL_DEV else "/auth/api/verify-session"
    params = {}
    if require_role:
        params["require_role"] = require_role

    query_str = f"?{urllib.parse.urlencode(params)}" if params else ""
    url = f"{PUBLIC_AUTH_BASE_URL}{endpoint}{query_str}"

    headers = {
        "Authorization": f"Bearer {token_or_session}",
        "User-Agent": "Mozilla/5.0 (Holyseeds-SubApp-Client)"
    }
    if LOCAL_DEV_API_KEY:
        headers["X-Dev-Api-Key"] = LOCAL_DEV_API_KEY

    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"valid": False, "error": str(e)}


# 1) 로컬 개발용 콜백 수신 엔드포인트 (공개 인증앱에서 로그인 후 session_id & dev_token을 받아 로컬 쿠키에 저장)
@app.get("/auth/callback")
async def local_auth_callback(session_id: str = None, dev_token: str = None, next_url: str = "/"):
    token_to_store = dev_token or session_id
    if not token_to_store:
        return RedirectResponse(url=f"{PUBLIC_AUTH_BASE_URL}/auth/login?error=세션+토큰이+전달되지+않았습니다.")

    response = RedirectResponse(url=next_url, status_code=status.HTTP_303_SEE_OTHER)
    # 로컬 도메인(localhost)에 auth_session 쿠키로 저장하여 이후 모든 요청에서 사용
    response.set_cookie(key="auth_session", value=token_to_store, httponly=True, path="/")
    return response


# 2) 공통 인증 검증 의존성 함수 (Dependency)
def require_auth(require_role: str = None):
    def _dependency(request: Request) -> dict:
        # 쿠키, Authorization 헤더, 또는 쿼리의 dev_token/session_id 추출
        token = (
            request.cookies.get("auth_session")
            or request.headers.get("x-dev-token")
            or request.query_params.get("dev_token")
            or request.query_params.get("session_id")
        )
        result = call_public_auth_verify(token, require_role=require_role)

        if not result.get("valid") or (require_role and not result.get("has_required_role")):
            # 미인증 또는 권한 미달 시 공개 인증앱 로그인 화면으로 리다이렉트 URL 생성
            if IS_LOCAL_DEV:
                callback_url = f"{LOCAL_APP_BASE_URL}/auth/callback?next_url={urllib.parse.quote(str(request.url.path))}"
                login_url = (
                    f"{PUBLIC_AUTH_BASE_URL}/auth/login"
                    f"?redirect={urllib.parse.quote(callback_url)}"
                    f"&dev_mode=1"
                )
            else:
                login_url = f"{PUBLIC_AUTH_BASE_URL}/auth/login?redirect={urllib.parse.quote(str(request.url.path))}"

            if require_role:
                login_url += f"&require_role={urllib.parse.quote(require_role)}"

            raise HTTPException(
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                headers={"Location": login_url}
            )
        return result
    return _dependency


# 3) 권한별 라우트 활용 예시
@app.get("/my-dashboard")
async def user_dashboard(auth_data: dict = Depends(require_auth())):
    """일반 로그인 사용자 누구나 접근 가능"""
    return {
        "message": f"환영합니다, {auth_data['user']['name']}님!",
        "manager_role": auth_data["manager_role"],       # "user" | "admin" | "super"
        "developer_role": auth_data["developer_role"],   # "user" | "developer" | "dev-leader"
    }

@app.get("/admin/rooms")
async def admin_only_route(auth_data: dict = Depends(require_auth("manager"))):
    """관리자 등급(manager=1 또는 super=2)만 접근 가능"""
    return {"message": "관리자 전용 룸 관리 화면입니다.", "user": auth_data["user"]}

@app.get("/dev/debug-console")
async def developer_only_route(auth_data: dict = Depends(require_auth("developer"))):
    """개발자 등급(developer=1 또는 dev-leader=2)만 접근 가능"""
    return {
        "message": "개발자 전용 디버그 콘솔입니다.",
        "developer_flag": auth_data["developer_flag"],
        "developer_role": auth_data["developer_role"],
        "is_dev_leader": auth_data["is_dev_leader"]
    }

@app.get("/dev/architecture-config")
async def dev_leader_only_route(auth_data: dict = Depends(require_auth("dev-leader"))):
    """개발 리더(dev-leader=2)만 접근 가능"""
    return {"message": "개발 리더(dev-leader) 전용 설정 화면입니다."}
```

---

### 6.2. [cURL / CLI / 프론트엔드] 콜백 없이 공개 인증앱 직접 호출(Direct Call) 샘플

로컬에서 웹 브라우저 리다이렉트 없이 백엔드 스크립트나 Postman, 프론트엔드에서 공개 인증앱에 직접 로그인하고 세션을 검증하는 예시입니다.

#### ① 공개 인증앱에 직접 로그인하여 `dev_token` 및 `session_id` 발급받기
```bash
curl -X POST "https://holyseeds.thewayworks.net/auth/api/dev/direct-login" \
     -H "Content-Type: application/json" \
     -d '{"phone_number": "01055787363", "pin": "1234"}'
```

#### ② 발급받은 `dev_token` (또는 `session_id`)으로 공개 인증앱에 직접 Verification Call 보내기
```bash
# 방법 A: Authorization Bearer 헤더로 직접 호출 (권장)
curl -X GET "https://holyseeds.thewayworks.net/auth/api/dev/verify-session?require_role=developer" \
     -H "Authorization: Bearer <발급받은_dev_token_또는_session_id>"

# 방법 B: Query 파라미터로 직접 호출
curl -X GET "https://holyseeds.thewayworks.net/auth/api/dev/verify-session?dev_token=<발급받은_dev_token>&require_role=dev-leader"
```
