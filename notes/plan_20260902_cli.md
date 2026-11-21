# Keycloak Authentication and User Management Integration Plan

## Objective
Set up Keycloak Admin Token in `.env` based on user credentials and implement a basic verification CLI to test the user management flow (Sign-up, Search, PIN Verification, Update, and Deletion) in the `holyseeds` realm.

## Key Files & Context
- `.env`: Contains Keycloak configuration and credentials.
- `requirements.md`: Defines the test scenarios and configuration requirements.
- `plan.md` & `history.md`: Documentation files to be created in the workspace.
- `generate_admin_token.py`: Script to authenticate and update `.env`.
- `keycloak_auth_cli.py`: The main CLI verification script.

## Implementation Steps
1. **Initialize Documentation**
   - Create `plan.md` in the workspace root with this plan's content.
   - Create `history.md` in the workspace root to track execution logs.

2. **Environment & Token Setup**
   - Write a python script `generate_admin_token.py` to read `KEYCLOAK_ADMIN_USER` and `KEYCLOAK_ADMIN_PASSWORD` from `.env`.
   - Call the Keycloak token endpoint (`POST /realms/master/protocol/openid-connect/token` with `grant_type=password` and `client_id=admin-cli`).
   - Extract the `access_token` and update `.env`: insert `KEYCLOAK_ADMIN_TOKEN=<token>` and remove the `KEYCLOAK_ADMIN_PASSWORD` line.
   - (*Note: Since access tokens expire, this script should be re-run if testing is resumed later, or the token generation logic can be manually invoked when needed.*)

3. **Develop Verification CLI**
   - Create `keycloak_auth_cli.py` to implement the `requirements.md` scenarios.
   - Load `KEYCLOAK_ADMIN_TOKEN` from `.env` and configure headers for API requests to the `holyseeds` realm.
   - Implement the following steps using the `requests` library (and `bcrypt` for hashing):
     - `step2_signup_user()`: Create a test user with a hashed PIN number (`bcrypt`) and phone number in attributes.
     - `step3_search_user_by_phone()`: Query `/admin/realms/holyseeds/users?q=phoneNumber:01055787363` to fetch the user ID.
     - `step4_login_verify_pin()`: Compare an input PIN with the stored hashed PIN attribute.
     - `step5_update_profile()`: Update the user's name or email via `PUT`.
     - `step6_cleanup_test_user()`: Delete the created test user via `DELETE` to ensure a clean state.

## Verification & Testing
- Run `python generate_admin_token.py` and inspect `.env` to confirm the password is removed and the token is present.
- Run `python keycloak_auth_cli.py` and observe the console output for successful execution of all steps.
- Append the results to `history.md`.
