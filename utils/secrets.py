from google.cloud import secretmanager
import os
from dotenv import load_dotenv
load_dotenv()

# Cache secrets to avoid hitting API limits on every request
_SECRET_CACHE = {}

def get_secret(secret_id, project_id=None, version_id="latest"):
    """
    Retrieves a secret from Google Cloud Secret Manager.
    """
    # Return cached value if available
    if secret_id in _SECRET_CACHE:
        return _SECRET_CACHE[secret_id]

    if not project_id:
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
        
    if not project_id:
        raise ValueError("Project ID not found. Set GOOGLE_CLOUD_PROJECT env var.")

    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"

    try:
        response = client.access_secret_version(request={"name": name})
        secret_value = response.payload.data.decode("UTF-8")
        
        # Cache the result
        _SECRET_CACHE[secret_id] = secret_value
        return secret_value
    except Exception as e:
        print(f"Error retrieving secret {secret_id}: {e}")
        return None
