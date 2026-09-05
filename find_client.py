import os
import urllib.request
import urllib.parse
import urllib.error
import json
import ssl

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

def main():
    env = load_env(".env")
    base_url = env.get("KEYCLOAK_BASE_URL", "https://auth.thewayworks.net").rstrip("/")
    realm = env.get("KEYCLOAK_TARGET_REALM", "holyseeds")
    token = env.get("KEYCLOAK_ADMIN_TOKEN")
    
    if not token:
        print("Error: KEYCLOAK_ADMIN_TOKEN not found in .env.")
        return
        
    url = f"{base_url}/admin/realms/{realm}/clients"
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    
    req = urllib.request.Request(url, headers=headers, method="GET")
    context = ssl._create_unverified_context()
    
    try:
        with urllib.request.urlopen(req, context=context) as response:
            clients = json.loads(response.read().decode("utf-8"))
            print("Successfully retrieved clients.")
            for c in clients:
                client_id = c.get("clientId")
                uuid = c.get("id")
                service_accounts_enabled = c.get("serviceAccountsEnabled")
                print(f" -> Client ID: {client_id}, UUID: {uuid}, ServiceAccountsEnabled: {service_accounts_enabled}")
                
                if client_id == "holyseeds-app-cli":
                    # Let's try to get its secret
                    secret_url = f"{base_url}/admin/realms/{realm}/clients/{uuid}/client-secret"
                    req_secret = urllib.request.Request(secret_url, headers=headers, method="GET")
                    try:
                        with urllib.request.urlopen(req_secret, context=context) as res_sec:
                            sec_data = json.loads(res_sec.read().decode("utf-8"))
                            print(f"    - Found client secret: {sec_data.get('value')}")
                    except Exception as e_sec:
                        print(f"    - Could not retrieve secret: {e_sec}")
                        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
