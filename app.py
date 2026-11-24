"""
GORE - AI chatbot with web search.
LLM: Groq (free tier)  |  Search: DuckDuckGo (no key needed)
Chat history is saved in the user's browser (localStorage) and sent with each
message, so the server needs no database and runs on Vercel.
The Groq API key is read ONLY from the server environment (GROQ_API_KEY) and is
never sent to the browser.
"""
import json
import os
import re
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from groq import Groq

try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

load_dotenv()

MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
HISTORY_LIMIT = 20  # how many past messages Gore remembers per reply

app = Flask(__name__)


def system_prompt():
    return f"""You are GORE, a battle-hardened war god who now serves as an AI chatbot
(a student project). Speak with a bold, epic, slightly dramatic tone, but always give
clear, correct and useful answers. Today's date is {datetime.now():%d %B %Y}.
If asked your name, say you are Gore.
You have a `web_search` tool. Use it for current events, news, prices, people, recent
facts, or anything you are unsure about. Search at most 2 times, then ALWAYS write a
final answer and cite sources as [1], [2]. For simple questions (greetings, maths,
general knowledge) answer directly without searching.
Use earlier messages in this conversation for context."""


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the internet for up-to-date information.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Search query"}},
                "required": ["query"],
            },
        },
    }
]


# ---------------------------------------------------------------- search
def web_search(query, max_results=5):
    """DuckDuckGo search: recent news + normal web results, with a retry."""
    sources, seen = [], set()

    def add(title, url, snippet, date=""):
        if url and url not in seen:
            seen.add(url)
            sources.append({"title": title, "url": url, "snippet": (f"({date[:10]}) " if date else "") + snippet})

    for _ in range(2):
        try:
            ddgs = DDGS()
            try:
                for r in ddgs.news(query, max_results=3):
                    add(r.get("title", ""), r.get("url", ""), r.get("body", ""), r.get("date", ""))
            except Exception:
                pass
            try:
                for r in ddgs.text(query, max_results=max_results):
                    add(r.get("title", ""), r.get("href", ""), r.get("body", ""))
            except Exception:
                pass
        except Exception:
            pass
        if sources:
            break
        query = " ".join(query.split()[:4])  # retry with a shorter query

    sources = sources[:7]
    text = "\n\n".join(
        f"[{i}] {s['title']}\nURL: {s['url']}\n{s['snippet']}" for i, s in enumerate(sources, 1)
    )
    return sources, text or "No results found. Answer from your own knowledge and say so."


# ---------------------------------------------------------------- llm
def clean(text):
    # some models write citations as 【1】 - turn them into [1]
    return re.sub(r"【(\d+)[^】]*】", r"[\1]", text or "").strip()


def write_answer(client, history, results_text):
    """Final answer with search results pasted in as text and NO tools available."""
    question = history[-1]["content"]
    msgs = [{"role": "system", "content": system_prompt() + "\nYou cannot call tools now. Just write the answer."}]
    msgs += history[:-1]
    msgs.append({
        "role": "user",
        "content": (f"Web search results:\n{results_text}\n\n" if results_text else "")
        + f"Using these results where relevant, answer my question. Cite sources as [1], [2].\n\nQuestion: {question}",
    })
    last_err = None
    for _ in range(3):  # retry: model occasionally tries to call a tool anyway
        try:
            resp = client.chat.completions.create(model=MODEL, messages=msgs, temperature=0.4)
            if resp.choices[0].message.content:
                return clean(resp.choices[0].message.content)
        except Exception as e:
            last_err = e
    if last_err:
        raise last_err
    return "Even the gods fall silent sometimes. Try asking again."


def ask_llm(client, history):
    """Step 1: the model decides whether to search. Step 2: write the answer."""
    messages = [{"role": "system", "content": system_prompt()}] + history
    all_sources, chunks = [], []

    for _ in range(2):  # up to 2 searches
        try:
            resp = client.chat.completions.create(
                model=MODEL, messages=messages, tools=TOOLS, tool_choice="auto", temperature=0.4
            )
        except Exception as e:
            if "tool" not in str(e).lower():
                raise
            if not all_sources:  # broken tool call: search the question directly
                sources, text = web_search(history[-1]["content"])
                all_sources += sources
                chunks.append(text)
            break

        msg = resp.choices[0].message
        if not msg.tool_calls:
            if msg.content and not all_sources:
                return clean(msg.content), []
            break

        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ],
        })
        for tc in msg.tool_calls:
            try:
                query = json.loads(tc.function.arguments).get("query") or history[-1]["content"]
            except json.JSONDecodeError:
                query = history[-1]["content"]
            sources, text = web_search(query)
            offset = len(all_sources)
            all_sources += sources
            for i in range(len(sources), 0, -1):  # keep citation numbers unique
                text = text.replace(f"[{i}]", f"[{i + offset}]")
            chunks.append(text)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": text})

    return write_answer(client, history, "\n\n".join(chunks)), all_sources


# ---------------------------------------------------------------- routes
@app.route("/")
def index():
    return render_template("index.html")


@app.post("/api/chat")
def chat():
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return jsonify({"error": "Server is missing GROQ_API_KEY. Add it to .env (local) or Vercel environment variables."}), 500

    data = request.get_json(force=True) or {}
    raw = data.get("messages") or []
    # keep only valid user/assistant messages, last HISTORY_LIMIT of them
    history = [
        {"role": m["role"], "content": str(m["content"])[:8000]}
        for m in raw
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content")
    ][-HISTORY_LIMIT:]
    if not history or history[-1]["role"] != "user":
        return jsonify({"error": "Empty message"}), 400

    try:
        answer, sources = ask_llm(Groq(api_key=key), history)
    except Exception as e:
        msg = str(e)
        if key in msg:
            msg = msg.replace(key, "***")
        return jsonify({"error": f"Groq error: {msg}"}), 500
    return jsonify({"answer": answer, "sources": sources})


if __name__ == "__main__":
    print("\n  GORE is awake. Open http://127.0.0.1:5050 in your browser\n")
    app.run(debug=True, port=5050)
