import json
import keycloak_api

def main():
    realm = keycloak_api.TARGET_REALM
    print(f"Target Realm: {realm}")
    
    # Fetch current schema
    status, _, profile = keycloak_api.request_api("GET", f"/admin/realms/{realm}/users/profile")
    if status != 200:
        print(f"Error fetching User Profile configuration. Status: {status}, Response: {profile}")
        return
        
    print("Successfully retrieved User Profile configuration.")
    
    attributes = profile.get("attributes", [])
    existing_attrs = {attr.get("name") for attr in attributes}
    
    updated = False
    default_permissions = {
        "view": ["admin", "user"],
        "edit": ["admin", "user"]
    }
    
    if "phoneNumber" not in existing_attrs:
        print(" -> Adding 'phoneNumber' to profile schema...")
        attributes.append({
            "name": "phoneNumber",
            "displayName": "Phone Number",
            "permissions": default_permissions
        })
        updated = True
    else:
        print(" -> 'phoneNumber' already exists in profile schema.")
        
    if "pinNumber" not in existing_attrs:
        print(" -> Adding 'pinNumber' to profile schema...")
        attributes.append({
            "name": "pinNumber",
            "displayName": "PIN Number",
            "permissions": default_permissions
        })
        updated = True
    else:
        print(" -> 'pinNumber' already exists in profile schema.")

    if "manager" not in existing_attrs:
        print(" -> Adding 'manager' to profile schema...")
        attributes.append({
            "name": "manager",
            "displayName": "Manager Flag (1=Admin)",
            "permissions": default_permissions
        })
        updated = True
    else:
        print(" -> 'manager' already exists in profile schema.")
        
    if updated:
        profile["attributes"] = attributes
        
        # PUT updated schema back
        put_status, _, put_body = keycloak_api.request_api("PUT", f"/admin/realms/{realm}/users/profile", profile)
        print(f"Schema update response status: {put_status}")
        if put_status in (200, 204):
            print("✅ User Profile configuration updated successfully in Keycloak!")
        else:
            print(f"⚠️ Unexpected status when updating: {put_status}, Response: {put_body}")
    else:
        print("✅ All custom attributes (including 'manager') already exist in the schema. No update needed.")

if __name__ == "__main__":
    main()
