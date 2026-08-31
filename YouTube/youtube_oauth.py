from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]
CLIENT_FILE = "credentials/client_secret.json"
TOKEN_FILE = "tokens/youtube_token.json"

print("\n=== GTA / BR / YouTube ===\n")

if not os.path.exists(CLIENT_FILE):
    print("ERRO: credenciais não encontradas.")
    raise SystemExit(1)

os.makedirs("tokens", exist_ok=True)

flow = InstalledAppFlow.from_client_secrets_file(
    CLIENT_FILE,
    SCOPES
)

print("Credenciais oficiais do Google carregadas.")
print("Abrindo a autorização do Google...\n")

creds = flow.run_local_server(
    host="127.0.0.1",
    port=0,
    open_browser=False
)

with open(TOKEN_FILE, "w") as f:
    f.write(creds.to_json())

youtube = build("youtube", "v3", credentials=creds)

response = youtube.channels().list(
    part="snippet",
    mine=True
).execute()

if response.get("items"):
    channel = response["items"][0]["snippet"]

    print("\n================================")
    print("YOUTUBE CONECTADO COM SUCESSO!")
    print("Canal:", channel["title"])
    print("================================\n")
else:
    print("\nOAuth concluído, mas nenhum canal foi encontrado.")
