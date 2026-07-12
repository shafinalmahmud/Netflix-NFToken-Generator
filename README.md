# Netflix NFToken Generator + ChatGPT Session Token Generator

A collection of Python scripts that generate authentication tokens from valid session cookies.

- **Netflix NFToken** — generates a Netflix auto-login (`nftoken`) link
- **ChatGPT Session Token** — retrieves a ChatGPT session/access token

Each script reads the cookie from its respective input file, sends the required request, and prints the result in the console.

## Discord

- Discord server: https://discord.gg/DYJFE9nu5X

## Features (Netflix)

- Simple local script with no extra UI
- Reads cookie from `input.txt`
- Auto-creates `input.txt` if it is missing
- Supports raw cookie string, Netscape cookie format, and JSON cookie input
- Prints the full Netflix `nftoken` link in console
- Includes inline comments explaining each step of the flow

## Features (ChatGPT)

- Standalone module mirroring the Netflix architecture
- Reads cookie from `chatgpt_input.txt`
- Auto-creates `chatgpt_input.txt` if it is missing
- Supports raw cookie string, Netscape cookie format, and JSON cookie input
- Retrieves session info (user, expiry, access token) from ChatGPT
- Falls back across multiple domains (`chatgpt.com`, `chat.openai.com`, `openai.com`)

## Requirements

Install the required module:

```bash
pip install requests
```

## Quick Start — Netflix

1. Clone the repo:

```bash
git clone https://github.com/harshitkamboj/Netflix-NFToken-Generator.git
cd Netflix-NFToken-Generator
```

2. Install requirements:

```bash
pip install requests
```

3. Run the script once:

```bash
python nf-token-generator.py
```

4. If `input.txt` does not exist, the script will create it automatically
5. Paste your Netflix cookie into `input.txt`
6. Run again:

```bash
python nf-token-generator.py
```

7. The console will print:

```text
https://www.netflix.com/?nftoken=...
```

## Quick Start — ChatGPT

1. Run the script once:

```bash
python chatgpt-token-generator.py
```

2. If `chatgpt_input.txt` does not exist, the script will create it automatically
3. Export your ChatGPT cookie (see input examples below) and paste into `chatgpt_input.txt`
4. Run again:

```bash
python chatgpt-token-generator.py
```

5. The console will print your session info, expiry, and access token

## Input Examples

### Raw Cookie String

For Netflix:
```text
NetflixId=xxx; SecureNetflixId=xxx; nfvdid=xxx
```

For ChatGPT:
```text
__Secure-next-auth.session-token=eyJ...; __Host-next-auth.csrf-token=xxx
```

### Netscape Cookie Format

```text
.netflix.com	TRUE	/	TRUE	1234567890	NetflixId	xxx
.netflix.com	TRUE	/	TRUE	1234567890	SecureNetflixId	xxx
.netflix.com	TRUE	/	TRUE	1234567890	nfvdid	xxx
```

ChatGPT (Netscape example):
```text
.chatgpt.com	TRUE	/	TRUE	1760000000	__Secure-next-auth.session-token	eyJ...
.chatgpt.com	TRUE	/	TRUE	1760000000	__Host-next-auth.csrf-token	xxx
```

### JSON Format

Netflix:
```json
{
  "NetflixId": "xxx",
  "SecureNetflixId": "xxx",
  "nfvdid": "xxx"
}
```

ChatGPT:
```json
{
  "__Secure-next-auth.session-token": "eyJ...",
  "__Host-next-auth.csrf-token": "xxx"
}
```

Or as a JSON array (from Cookie-Editor export):
```json
[
  {"name": "__Secure-next-auth.session-token", "value": "eyJ...", "domain": ".chatgpt.com"},
  {"name": "__Host-next-auth.csrf-token", "value": "xxx", "domain": ".chatgpt.com"}
]
```

## How It Works — Netflix

1. The script reads cookie data from `input.txt`
2. It extracts the required Netflix session cookies
3. It builds the `Cookie` header
4. It sends a request to Netflix's `createAutoLoginToken` operation
5. It reads the returned token from the response
6. It prints the final Netflix login link using `?nftoken=...`

## How It Works — ChatGPT

1. The script reads cookie data from `chatgpt_input.txt`
2. It extracts the `__Secure-next-auth.session-token` cookie
3. It builds the `Cookie` header with all recognised cookies
4. It sends a GET request to `https://chatgpt.com/api/auth/session`
5. If that fails, it falls back to `chat.openai.com` and `openai.com`
6. It reads the returned user info, expiry, and access token
7. It prints the session details in the console

## Files

```text
nf-token-generator.py         # Netflix token generator
chatgpt-token-generator.py    # ChatGPT session token generator
input.txt                     # Netflix cookie input file
chatgpt_input.txt             # ChatGPT cookie input file
README.md                     # project guide
```

## Notes

- Use only cookies/accounts you are authorized to test
- A valid session cookie is required for each service
- If the cookie is invalid or expired, the API will return an error
- For ChatGPT: export your cookie while logged in at **https://chatgpt.com**
- Supported cookie formats: raw string, Netscape format, JSON objects, JSON arrays

## Contact

- GitHub: https://github.com/harshitkamboj
- Repository: https://github.com/harshitkamboj/Netflix-NFToken-Generator
- Website: https://harshitkamboj.in
- Discord username: `illuminatis69`
- Discord server: https://discord.gg/DYJFE9nu5X

## Disclaimer

Educational use only. Use only on accounts and cookies you are authorized to test.
