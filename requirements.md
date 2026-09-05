# Keycloak 기반 사용자 관리 및 인증 시스템 CLI 샘플 프로그램 개발 요구 스펙 및 개발 가이드

Keycloak을 활용하여 휴대폰 번호, 이름, 이메일, PIN 번호 기반의 사용자 관리 및 인증 시스템을 구축하기 위한 **CLI 샘플 프로그램 개발 요구 스펙 및 개발 가이드**입니다.

---

### 1. 시스템 환경 및 접속 정보

* **Application Domain**: [https://holyseeds.thewayworks.net](https://holyseeds.thewayworks.net)
* **Auth UI / Service**: [https://holyseeds.thewayworks.net/auth](https://holyseeds.thewayworks.net/auth) (회원가입, 로그인, 프로필 변경)
* **Keycloak Server Domain**: [https://auth.thewayworks.net](https://auth.thewayworks.net)
* **Admin/System Realm**: `master` (`KEYCLOAK_REALM`)
* **Target Application Realm**: `holyseeds` (`KEYCLOAK_TARGET_REALM`)
* **Client Type**: Confidential Client (Backend CLI 및 Service-to-Service 통신용)

---

### 2. Keycloak 사전 설정 (Admin Console 작업)

Admin API 및 사용자 정의 필드(휴대폰 번호, PIN)를 처리하기 위한 필수 설정 항목입니다.

#### A. Target Realm (`holyseeds`) 커스텀 속성(User Attributes) 설정

Keycloak 기본 사용자 필드(Username, Email, FirstName 등) 외 추가 정보를 위해 사용자 속성을 지정합니다.

* `phoneNumber`: 휴대폰 번호 (예: `01055787363`)
* `pinNumber`: Hash 처리되어 저장될 PIN 번호

> **보안 주의사항**: Keycloak User Attribute에 PIN 번호를 평문으로 저장하면 안 됩니다. CLI 또는 Backend API 수준에서 bcrypt/Argon2 등으로 **단방향 암호화(Hashing)** 한 뒤 `pinNumber` 속성에 저장해야 합니다.

#### B. API 연동용 Client 생성 (`holyseeds` Realm 내)

* **Client ID**: `holyseeds-app-cli` (예시)
* **Client Protocol**: `openid-connect`
* **Access Type / Client Authenticator**: `Confidential` (Client Secret 발급)
* **Authentication Flow**:
  * `Standard Flow Enabled`: OFF (CLI Direct 테스트 시) 또는 ON (Web Auth Code Flow 사용 시)
  * `Direct Access Grants Enabled`: ON (아이디/패스워드 또는 custom 속성 기반 로그인 테스트 시)
  * `Service Accounts Enabled`: ON (Admin REST API 조작용)

#### C. Service Account 권한 부여

Client가 `holyseeds` Realm의 사용자 관리(User CRUD) Admin API를 호출하려면 권한이 필요합니다.

1. `holyseeds` Realm -> Clients -> `holyseeds-app-cli` -> **Service Accounts Roles** 이동
2. Client Roles 선택 -> `realm-management` 선택
3. 다음 Role 추가:
   * `manage-users`: 사용자 생성, 수정, 삭제
   * `view-users`: 사용자 조회 및 검색

---

### 3. 인증/인가 흐름 및 구현 요구사항

```
[User / CLI Client]
       │
       ├─ (1) 회원가입 ───> [Keycloak Admin REST API] ───> holyseeds Realm 사용자 생성 (Attribute: phone, pin)
       │
       ├─ (2) PIN 로그인 ──> [Auth Service API / Custom SPI] ─> phone으로 User 검색 & PIN Hash 검증 ─> Token 발급
       │
       └─ (3) 프로필 수정 ─> [Keycloak Admin/User API] ───> User Attributes 업데이트
```

#### A. 회원가입 (Sign-Up)

1. Master Realm 또는 Target Realm의 Service Account를 통해 **Admin Access Token** 발급
2. `POST /admin/realms/holyseeds/users` 호출
   * `username`: 휴대폰 번호 (`01055787363`) 또는 이메일
   * `email`: `gluemii@gmail.com`
   * `firstName`: `inchang`
   * `enabled`: `true`
   * `attributes`:
     * `phoneNumber`: `01055787363`
     * `pinNumber`: `$2a$10$...` (Hashing된 PIN)

#### B. 로그인 (Login)

* **기본 패스워드 인증 미사용 시**: Keycloak의 기본 패스워드 대신 PIN 번호를 사용하는 경우, Keycloak Custom Authenticator (SPI)를 작성하여 설치하거나, 애플리케이션 백엔드에서 사용자 검색 후 PIN Hash를 비교한 뒤 **Token Exchange / Direct Grant**로 토큰을 수급하는 방식을 선택합니다.
* **CLI 테스트 표준 방식 (Back-end Proxy 방식)**:
  1. CLI/앱이 `phoneNumber`, `pinNumber` 전송
  2. 백엔드(Service Account)가 `phoneNumber`로 Keycloak User 검색
  3. 저장된 `pinNumber` Hash와 입력값 비교
  4. 검증 성공 시, Keycloak에서 해당 사용자의 Token 발급/임시 패스워드 로그인 처리하여 Access/Refresh Token 반환

#### C. 프로필 변경 (User Profile Update)

1. 발급받은 User Access Token 또는 Service Account를 활용
2. `PUT /admin/realms/holyseeds/users/{user-id}` 호출하여 `firstName`, `email`, `attributes.phoneNumber` 등 수정

---

### 4. Keycloak CLI 테스트 환경 구현 명세 (Sample Spec)

CLI 시나리오 검증용 환경 변수 및 테스트 모듈 기능 명세입니다.

#### A. 환경 변수 (Configuration)

```env
KEYCLOAK_BASE_URL=https://auth.thewayworks.net
KEYCLOAK_REALM=master
KEYCLOAK_TARGET_REALM=holyseeds

# Master Admin 계정 (Admin API 직접 제어 시)
KEYCLOAK_ADMIN_USER=admin
KEYCLOAK_ADMIN_PASSWORD=<ADMIN_PASSWORD>

# Target Realm Client Credentials (Service Account 사용 시)
KEYCLOAK_CLIENT_ID=holyseeds-app-cli
KEYCLOAK_CLIENT_SECRET=<CLIENT_SECRET>
```

#### B. 주요 Admin API Endpoints Reference

| 기능 | HTTP Method | Endpoint Path | 비고 |
| --- | --- | --- | --- |
| **Admin Token 발급 (Master)** | `POST` | `/realms/master/protocol/openid-connect/token` | `grant_type=password`, admin 계정 사용 |
| **Client Token 발급 (Target)** | `POST` | `/realms/holyseeds/protocol/openid-connect/token` | `grant_type=client_credentials` |
| **사용자 생성** | `POST` | `/admin/realms/holyseeds/users` | Bearer Token 필요 |
| **휴대폰번호로 사용자 조회** | `GET` | `/admin/realms/holyseeds/users?q=phoneNumber:01055787363` | Bearer Token 필요 |
| **사용자 정보/프로필 수정** | `PUT` | `/admin/realms/holyseeds/users/{user-id}` | Bearer Token 필요 |
| **사용자 삭제 (테스트 초기화용)** | `DELETE` | `/admin/realms/holyseeds/users/{user-id}` | Bearer Token 필요 |

---

### 5. CLI 테스트 시나리오 시퀀스

CLI 개발 시 다음 시나리오 순서대로 함수를 작성하여 테스트를 진행합니다.

1. **`step1_get_admin_token()`**
   * Service Account (`client_credentials`)를 사용하여 `holyseeds` Realm 관리 권한이 담긴 Access Token을 획득합니다.

2. **`step2_signup_user()`**
   * 사용자 데이터 준비:
     * 이름: `inchang`
     * 이메일: `gluemii@gmail.com`
     * 휴대폰: `01055787363`
     * PIN: `1234` -> SHA-256/bcrypt 암호화
   * `POST /admin/realms/holyseeds/users`로 사용자 등록 요청을 보냅니다.

3. **`step3_search_user_by_phone()`**
   * `GET /admin/realms/holyseeds/users?q=phoneNumber:01055787363` 호출을 통해 생성된 사용자의 Keycloak `id`(UUID) 및 `attributes`를 검증합니다.

4. **`step4_login_verify_pin()`**
   * 입력된 PIN 번호와 조회된 User Attribute의 `pinNumber` Hash를 비교하여 검증 로직을 실행합니다.

5. **`step5_update_profile()`**
   * `PUT /admin/realms/holyseeds/users/{user-id}`를 호출하여 이름 또는 이메일 변경을 테스트합니다.

6. **`step6_cleanup_test_user()`**
   * 테스트 완료 후 생성했던 테스트 유저를 `DELETE` 호출로 삭제하여 깨끗한 상태를 유지합니다.
