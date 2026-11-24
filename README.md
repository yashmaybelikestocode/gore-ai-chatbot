# GORE - The War God Chatbot

An AI chatbot (student project) that:
- **Searches the web** with DuckDuckGo (no key needed) and shows its sources.
- **Remembers your chats**: history is saved in your browser and listed in the sidebar; Gore uses earlier messages of a chat as context.
- Uses a **free Groq API key** (model `openai/gpt-oss-120b`). No Claude/OpenAI key.
- **Keeps the API key hidden**: the key lives only on the server (`.env` locally, Environment Variables on Vercel) and is never sent to the browser.

## Run locally

```bash
cd "ai chatbot"
pip3 install -r requirements.txt
cp .env.example .env      # put your Groq key in .env
python3 app.py
```
Open http://127.0.0.1:5050

## Deploy on Vercel

```bash
npm i -g vercel
vercel login
vercel                         # first deploy (accept defaults)
vercel env add GROQ_API_KEY    # paste the key, choose Production + Preview
vercel --prod                  # deploy again so the key is used
```

## Changing the API key

- **Local:** edit `GROQ_API_KEY` in `.env` and restart.
- **Vercel:** Project → Settings → Environment Variables → edit `GROQ_API_KEY` → Redeploy.

Free key: https://console.groq.com/keys

## Files

| File | Purpose |
|---|---|
| `app.py` | Flask backend: Groq calls, web search tool |
| `templates/index.html` | Chat UI + browser-side chat history |
| `requirements.txt` | Python packages |
| `.env.example` | Template for your API key |
| `.vercelignore` | Keeps `.env` and local files out of the deployment |
