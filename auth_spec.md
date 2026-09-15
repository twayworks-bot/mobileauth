# Keycloak 기반 멀티 서비스 로그인 프록시 연동 스펙 (auth_spec.md)

본 문서는 중앙 집중형 Keycloak 인증 서버를 프록시 백엔드(FastAPI Auth Proxy)로 래핑하여, 다양한 독립 서브 서비스(Booking, Bus, Planning 등)에 대해 일관된 SSO(Single Sign-On) 로그인 게이트웨이 및 세션 검증 환경을 제공하기 위한 **공통 연동 프로그래밍 스펙**을 정의합니다.

---

## 1. 시스템 아키텍처 개요

전체 시스템은 **사용자 브라우저**, **독립 서브 서비스(예: Booking, Bus, Planning)**, **중앙 인증 프록시 서버(FastAPI Auth)**, 그리고 **Keycloak 인증 서버**로 구성됩니다.

```
+--------------------+        (1) 권한 미달 / 비로그인 시         +----------------------+
|                    | --------------------------------------> |                      |
|  사용자 브라우저   |                                         |  중앙 인증 프록시   |
|                    | <-------------------------------------- |     (FastAPI)        |
+--------------------+      (4) 인증 성공 후 콜백 리다이렉트   +----------------------+
  |                ^                                                    |            ^
  | (2) API 요청   | (5) 검증 성공                                       |            |
  v                |                                                    v            |
+--------------------+          (3) 실시간 세션 및 권한 검증           +----------------------+
|  독립 서브 서비스  | --------------------------------------> |                      |
|  (Booking/Bus/etc) | <-------------------------------------- |   Keycloak Admin API |
+--------------------+               회원 정보 및 역할 반환            +----------------------+
```

1. **로그인 게이트웨이 통합**: 서브 서비스들은 자체 로그인 화면을 구현하지 않고, 모든 인증 및 로그인 처리를 중앙 `/auth/login` 경로에 위임합니다.
2. **콜백 및 오류 정보 전달**: 비로그인 상태이거나 권한이 미달된 사용자를 로그인 페이지로 유도할 때, 원래 진입하고자 했던 목적지 주소(`redirect`)와 사유 에러 메시지(`error`)를 파라미터로 함께 실어 보냅니다.
3. **공통 세션 검증**: 로그인 완료 후 서브 서비스의 백엔드는 브라우저 쿠키 또는 세션 토큰을 기반으로 프록시 서버의 검증 API(`/auth/api/verify-session`)를 호출하여 사용자의 권한 여부를 확인합니다.

---

## 2. HTTP 인터페이스 상세 규격

### 2.1. 로그인 게이트웨이 엔드포인트
인증되지 않은 사용자나 권한 조건이 맞지 않는 사용자를 공통 로그인 화면으로 유도할 때 호출하는 엔드포인트입니다.

*   **URL**: `/auth/login`
*   **Method**: `GET`
*   **Query Parameters**:

| 파라미터명 | 타입 | 필수 여부 | 설명 | 예시 값 |
| :--- | :--- | :---: | :--- | :--- |
| `redirect` | String | **필수** | 로그인 및 권한 검증 성공 시 사용자를 리다이렉트(콜백)시킬 목적지 URL 주소 | `/reserve/admin/rooms`, `/bus/admin` |
| `error` | String | 선택 | 로그인 화면 상단에 붉은색 경고 박스로 사용자에게 보여줄 안내 메시지 (인코딩 필요) | `관리자+권한이+필요한+페이지입니다.` |
| `require_role` | String | 선택 | 해당 콜백 주소 진입 시 충족해야 하는 권한 식별자 (프록시단에서 검증 가능) | `manager`, `role:bus_admin`, `role:planning_admin` |

*   **동작 흐름**:
    1. 사용자가 `GET /auth/login?error=...&redirect=...` 요청.
    2. 프록시는 로그인 폼 화면을 제공하며, `redirect` 주소와 `require_role` 정보를 히든 필드(`input type="hidden"`) 또는 세션에 보관합니다.
    3. 사용자가 로그인(휴대폰 번호, PIN) 성공 시, 프록시는 `require_role` 검증을 수행하고 통과 시 `redirect` 주소로 `303 See Other` 리다이렉션을 발생시킵니다.

---

### 2.2. 백엔드 세션 검증 API
독립 서브 서비스의 백엔드에서 현재 요청을 보낸 브라우저 사용자의 로그인 상태 및 특정 권한 부합 여부를 실시간으로 판별할 때 호출하는 API입니다.

*   **URL**: `/auth/api/verify-session`
*   **Method**: `GET`
*   **Request Parameters**:

| 파라미터명 | 위치 | 타입 | 필수 여부 | 설명 |
| :--- | :--- | :--- | :---: | :--- |
| `session_id` | Query / Cookie | String | 선택 | 세션 키(쿠키의 `auth_session` 값). 생략 시 프록시가 직접 쿠키에서 읽어옴 |
| `require_role`| Query | String | 선택 | 검사하려는 특정 권한 등급 및 플래그 |

*   **Response (JSON)**:
    *   **인증 및 권한 통과 시 (`200 OK`)**:
        ```json
        {
          "valid": true,
          "is_manager": true,
          "user": {
            "id": "e44d3204-1f1d-400a-b33c-3965fc71295c",
            "username": "01012345678",
            "name": "홍길동",
            "email": "gildong@thewayworks.net"
          },
          "roles": ["manager", "bus_admin"],
          "has_required_role": true
        }
        ```
    *   **검증 실패 시 (세션 만료 또는 권한 미달) (`200 OK` 또는 `401 Unauthorized`)**:
        ```json
        {
          "valid": false,
          "is_manager": false,
          "error": "세션이 존재하지 않거나 해당 메뉴의 접근 권한이 없습니다.",
          "has_required_role": false
        }
        ```

---

## 3. 3대 핵심 사용자 인증 방식 및 스펙

서브 서비스들이 요구하는 진입 장벽 및 중앙 통제 수준에 따라 아래 4가지 인증 등급을 표준 규격화하여 관리합니다.

### 3.0) 패턴 0: 최고 관리자 권한 인증 (Super Admin Authentication / flag = "2")
가장 높은 최상위 통제 권한으로, 중앙 사용자 권한 관리(User CRUD: `/auth/users`), 사용자별 권한 등급 부여/회수, 사용자 삭제 등 **전체 사용자 권한 거버넌스 기능**에 필수적으로 요구됩니다.

*   **Keycloak DB 데이터 설계**:
    *   사용자의 Keycloak Attributes 내 `manager` 필드 값이 `"2"`로 설정된 계정.
    *   부트스트랩 개발자 계정(`01055787363`)은 상시 Super Admin(flag=2)으로 자동 승격/보호됩니다.
*   **호출 및 검증**:
    *   `/auth/users` (CRUD 대시보드 진입 및 권한 변경): `is_super` 검증 강제. 일반 관리자(flag=1)나 일반 회원은 접근 불가하며 프로필 페이지로 리다이렉트됩니다.
    *   API 세션 검증: `GET /auth/api/verify-session?require_role=super` 호출 시 `is_super: true` 확인.

---

### 3.1) 패턴 1: 일반 관리자 권한 인증 (Admin / Manager Authentication / flag = "1")
각 서브 서비스(예: Booking 룸 관리, Bus 노선 및 배차 관리 등)의 관리자 기능에 적용되며, 비즈니스 관리 권한을 제공하지만 **사용자 권한 관리(CRUD) 기능은 수행할 수 없습니다.**

*   **Keycloak DB 데이터 설계**:
    *   사용자의 Keycloak Attributes 내 `manager` 필드 값이 `"1"`인 계정 (Super Admin인 `"2"`도 상위 호환으로 포함).
*   **호출 및 흐름**:
    1. 서브 서비스(Booking)는 `/reserve/admin/rooms` 접속자에 대해 `/auth/api/verify-session?require_role=manager` 호출.
    2. `is_manager`가 `false`인 경우, 곧바로 프록시 로그인 페이지로 바운스:
       `https://auth.thewayworks.net/auth/login?error=관리자+권한이+필요한+페이지입니다.&redirect=/reserve/admin/rooms&require_role=manager`

---

### 3.2) 패턴 2: 일반 사용자 인증 (General User Authentication / flag = "0")
단순 회원 전용 기능(내 예약 확인, 프로필 편집, PIN 번호 변경, 대시보드 조회 등)에 적용되며, Keycloak에 등록되고 세션만 유효하면 누구나 접근 가능한 권한입니다.

*   **Keycloak DB 데이터 설계**:
    *   `manager` 속성이 `"0"`이거나 미설정된 상태.
    *   내 프로필 관리(`/auth/profile`)에서 이름/이메일 수정 및 암호(PIN 번호) 변경이 가능합니다.
*   **호출 및 흐름**:
    1. 서브 서비스(Bus)는 `/bus/my-tickets` 접속자에 대해 `/auth/api/verify-session`만 호출하여 `valid: true` 검사.
    2. 세션이 없을 경우 로그인으로 바운스:
       `https://auth.thewayworks.net/auth/login?error=로그인이+필요합니다.&redirect=/bus/my-tickets`

---

### 3.3) 패턴 3: 특정 권한 Flag 인증 (Specific Permission / Role Flag Authentication)
멀티 테넌트 서비스 운영 시, 서비스별 개별 관리자 또는 특수 권한(예: 버스 관리자, 일정 플래닝 편집자)을 독립적으로 분배할 때 활용합니다.

*   **Keycloak DB 데이터 설계**:
    *   **방법 A (Attributes 속성 확장)**:
        *   사용자 속성에 개별 서비스 권한 키를 생성합니다.
        *   예: `bus_admin = ["1"]`, `planning_admin = ["1"]`
    *   **방법 B (멀티 밸류 공통 권한 필드)**:
        *   사용자 속성에 `allowed_services` 필드를 배열 형태로 선언합니다.
        *   예: `allowed_services = ["bus_manager", "planning_editor"]`
*   **호출 및 흐름 (예: 버스 관리자 접근 시)**:
    1. 서브 서비스(Bus 어드민)는 `/bus/admin` 진입 시 세션 검증 API에 대상 역할을 지정하여 호출:
       `GET /auth/api/verify-session?require_role=bus_admin`
    2. 프록시는 Keycloak에서 해당 사용자의 attributes를 받아 `bus_admin` 값이 `"1"`인지 판단하여 `has_required_role` 결과를 내려줍니다.
    3. 권한 불일치 시, 아래 주소로 유도하여 사전에 차단하거나 로그인 전환을 요구합니다:
       `https://auth.thewayworks.net/auth/login?error=버스+관리자+권한이+없습니다.&redirect=/bus/admin&require_role=role:bus_admin`

---

## 4. 시퀀스 흐름도 (Authentication Proxy Sequence)

아래 다이어그램은 **패턴 3(특정 권한 Flag 인증)**을 기반으로 타 서브 서비스가 공통 프록시 로그인을 경유하는 전체 트랜잭션 흐름을 나타냅니다.

```
[브라우저]                [서브 서비스 백엔드]          [FastAPI Auth Proxy]          [Keycloak]
   |                           |                             |                             |
   | (1) GET /bus/admin        |                             |                             |
   |-------------------------->|                             |                             |
   |                           | (2) API 호출: verify-session|                             |
   |                           |---------------------------->|                             |
   |                           |                             | (3) 유저 데이터 조회        |
   |                           |                             |---------------------------->|
   |                           |                             |<----------------------------|
   |                           |<----------------------------|                             |
   |                           |   [결과: invalid 또는 권한X] |                             |
   | (4) 302 Redirect          |                             |                             |
   |     (/auth/login?redirect=/bus/admin&require_role=bus_admin)                          |
   |<--------------------------|                             |                             |
   |                           |                             |                             |
   | (5) GET /auth/login (페이지 로드)                        |                             |
   |-------------------------------------------------------->|                             |
   |<--------------------------------------------------------|                             |
   |                                                         |                             |
   | (6) POST /auth/login (아이디/PIN 제출)                   |                             |
   |-------------------------------------------------------->|                             |
   |                                                         | (7) 자격 증명 & PIN 검증    |
   |                                                         |---------------------------->|
   |                                                         |<----------------------------|
   |                                                         |                             |
   |                                                         | (8) require_role 충족 여부 체크
   |                                                         |     (속성 bus_admin == "1") |
   |                                                         |                             |
   | (9) 303 Redirect / Set-Cookie (auth_session)            |                             |
   |     (Target: /bus/admin)                                |                             |
   |<--------------------------------------------------------|                             |
   |                                                         |                             |
   | (10) GET /bus/admin (재요청, 쿠키 전송)                   |                             |
   |-------------------------->|                             |                             |
   |                           | (11) API 호출: verify-session (쿠키 전달)                  |
   |                           |---------------------------->|                             |
   |                           |                             | (12) 세션 체크 & 권한 확인  |
   |                           |                             |---------------------------->|
   |                           |                             |<----------------------------|
   |                           |<----------------------------|                             |
   |                           |   [결과: valid / 통과]       |                             |
   | (13) 200 OK (어드민 화면)   |                             |                             |
   |<--------------------------|                             |                             |
```

---

## 5. 추가 인증 스펙 검토 및 고도화 로드맵 (TO-BE)

현재의 국소적 쿠키 동기화 및 동기식 백채널 검증 방식을 넘어, 향후 엔터프라이즈 멀티 테넌트 아키텍처로 확장하기 위해 추가적으로 설계 및 적용해야 할 **TO-BE 상세 규격**입니다.

### 5.1. 표준 OAuth2 / OIDC Authorization Code Flow로의 전환
*   **배경**: 현재 프록시는 단일 도메인 및 쿠키 공유를 전제로 설계되어, 서로 다른 도메인(예: `booking.com`, `busservice.co.kr`) 간에는 세션 공유가 어렵습니다.
*   **TO-BE 스펙**:
    *   서브 서비스들을 Keycloak에 각각의 **Client**로 독립 등록합니다.
    *   로그인 시 브라우저가 직접 Keycloak 인증창 또는 통합 SSO 폼으로 가며, 표준 인증 코드(`code`)를 발급받은 뒤 서브 서비스 백엔드가 `grant_type=authorization_code`를 사용하여 직접 **Access Token / Refresh Token / ID Token**을 교환받아 보관합니다.

### 5.2. 클라이언트 로컬 JWT 자율 검증 (JWKS 캐싱 활용)
*   **배경**: 사용자의 모든 API 요청마다 서브 서비스 백엔드가 통합 프록시 `/verify-session` API를 동기적으로 호출하면, 트래픽 폭증 시 프록시 서버에 심각한 병목이 유발됩니다.
*   **TO-BE 스펙**:
    *   Keycloak에서 발급하는 토큰은 비대칭 키(RS256)로 서명된 표준 JWT입니다.
    *   각 서브 서비스 백엔드는 Keycloak의 JWKS 엔드포인트(예: `/realms/{realm}/protocol/openid-connect/certs`)에서 공개키 목록을 한 번 다운로드하여 메모리에 캐싱합니다.
    *   이후 모든 세션 검증은 프록시 서버를 거칠 필요 없이, **로컬 백엔드에서 자체적으로 JWT 서명과 만료 기간을 해독하고 자율 판정**합니다. (동기적 네트워크 오버헤드 0% 실현)

### 5.3. Open Redirect (피싱 사이트 유도) 방지 화이트리스트 도입
*   **배경**: 공격자가 악의적으로 파라미터에 `redirect=https://evil-phishing-site.com`를 실어 보내면, 로그인 성공 후 해당 불법 사이트로 리다이렉트되어 사용자 자격 증명 탈취용 피싱에 무방비 노출됩니다.
*   **TO-BE 스펙**:
    *   중앙 인증 프록시 서버 및 Keycloak 설정에 허용할 콜백 도메인 정규식 패턴을 화이트리스트로 관리합니다.
    *   예: `allowed_redirect_uris = ["https://*.thewayworks.net/**", "http://localhost:8000/**"]`
    *   `/auth/login` 접근 시 `redirect` 파라미터가 해당 화이트리스트 규칙에 정합하지 않는 경우 `400 Bad Request` 에러를 발생시켜 리다이렉션을 즉시 차단합니다.

### 5.4. 클라이언트 롤(Client-Roles) 매핑 및 세부 RBAC 표준 구현
*   **배경**: 사용자 Attributes에 임의의 `bus_admin`, `planning_admin`과 같은 텍스트 속성을 주입하는 방식은 관리자가 늘어나거나 권한 구조가 고도화될 때(예: 읽기 권한, 쓰기 권한 분리) 대응하기 곤란합니다.
*   **TO-BE 스펙**:
    *   Keycloak의 클라이언트 롤 기능을 사용하여 `bus-service` 클라이언트에 `role:admin`, `role:editor`, `role:viewer` 권한을 생성합니다.
    *   사용자가 로그인을 완료하면 JWT 토큰의 `resource_access` 구역 내에 각 서비스 전용 클라이언트 역할이 주입됩니다.
        ```json
        "resource_access": {
          "bus-service": {
            "roles": ["role:admin"]
          },
          "planning-service": {
            "roles": ["role:viewer"]
          }
        }
        ```
    *   서브 서비스 백엔드는 주입된 클라이언트 롤 정보를 직접 활용하여 더욱 안전하고 유연한 역할 기반 접근 제어(RBAC)를 실현합니다.

### 5.5. Single Sign-Out (통합 로그아웃 동기화)
*   **배경**: 하나의 서브 서비스에서 로그아웃을 눌러 로컬 쿠키를 삭제하더라도, 다른 서브 서비스나 Keycloak 세션에는 로그인이 그대로 남아있는 싱크 불일치가 발생합니다.
*   **TO-BE 스펙**:
    *   **Keycloak Backchannel Logout**을 구성하여 사용자가 중앙 `/auth/logout`을 호출할 때 연동 중인 모든 활성 서브 서비스의 백엔드 세션 무효화 엔드포인트로 로그아웃 트리거 토큰을 전송하여 모든 브라우저 탭의 세션을 동시에 안전하게 폭파시킵니다.
