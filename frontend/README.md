# Frontend

Streamlit app for the CapstoneCompany IT Helpdesk: the chat, the agent queue, the admin dashboard and the knowledge base.

- `app.py`: the screens.
- `ui.py`: the look: stylesheet, animated logo, cards and badges.
- `api.py`: the client for the backend API.
- `.streamlit/config.toml`: the dark theme. Streamlit reads it from the folder you start it in, so run the app from this folder:

```
cd frontend
streamlit run app.py
```

Set `STREAM_DELAY=0` to turn off the typing effect, and `SHOW_DEMO_LOGINS=0` to hide the demo account buttons.
