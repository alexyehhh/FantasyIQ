"""The AI Analyst (Milestone 9): a Gemini tool-calling loop over app/services/.

`tools.py` wraps existing services as tool calls the model can make; `agent.py` runs the
loop and logs every call; `prompts.py` holds the system prompt. Never a second implementation
of business logic here, per AGENTS.md #2 — only wrapping and explaining what the services say.
"""
