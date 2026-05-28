"""Streamlit UI for SQL Agent Chatbot with RBAC.

A conversational interface to interact with the SQL agent API.
Features:
- Chat history management
- Role-based access control (RBAC)
- Database connection configuration
- Response visualization (charts, stat cards)
- Session persistence
"""

import streamlit as st
import requests
import json
from datetime import datetime
from typing import Optional, Dict, List, Any
import base64
from io import BytesIO
from PIL import Image
import time

# Page configuration
st.set_page_config(
    page_title="SQL Agent Chatbot",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================================
# Styling
# ============================================================================

st.markdown(
    """
    <style>
    :root{--bg:#f7fafc;--card:#ffffff;--accent:#1976d2;--accent-2:#4caf50;--muted:#9aa4ae}
    .stApp { background: linear-gradient(180deg, #f3f7fb 0%, var(--bg) 100%); }
    .chat-message { padding: 0.75rem; margin-bottom: 0.5rem; border-radius: 12px; display:block; }
    .user-message { background: linear-gradient(90deg, rgba(25,118,210,0.06), rgba(25,118,210,0.03)); border: 1px solid rgba(25,118,210,0.12); color: #083c6b }
    .assistant-message { background: linear-gradient(90deg, rgba(76,175,80,0.04), rgba(76,175,80,0.02)); border: 1px solid rgba(76,175,80,0.08); color: #23492e }
    .error-message { background: #fff0f0; border: 1px solid rgba(244,67,54,0.12); color: #7a1a1a }
    .chat-container { max-width: 100%; }
    .msg-header { display:flex; gap:8px; align-items:center; margin-bottom:6px }
    .msg-avatar { width:36px; height:36px; border-radius:50%; display:inline-block; }
    .msg-meta { font-size:12px; color:var(--muted) }
    .sidebar .stButton>button{ background:var(--accent); color:white }
    .stDownloadButton>button{ background:var(--accent-2); color:white }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================================
# Session State Initialization
# ============================================================================


def init_session_state():
    """Initialize session state variables."""
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "api_url" not in st.session_state:
        st.session_state.api_url = "http://localhost:8000/chat/"
    if "connection_config" not in st.session_state:
        st.session_state.connection_config = {
            "db_type": "mssql",
            "connection_id": "9DD2E9F0-4293-4E55-8E88-6FE881E5FC89",
            "server": "(localdb)\\MSSQLLocalDB",
            "database": "AdventureWorksLT2019",
            "username": "sa",
            "password": "1234567890",
            "port": 1143,
            "pool_size": 5,
            "timeout": 30,
        }
    if "user_role" not in st.session_state:
        st.session_state.user_role = "customer"
    if "user_id" not in st.session_state:
        st.session_state.user_id = "user-001"
    if "dark_mode" not in st.session_state:
        st.session_state.dark_mode = False


init_session_state()

# ============================================================================
# Helper Functions
# ============================================================================


def format_message(role: str, content: str, timestamp: Optional[str] = None) -> str:
    """Format a message for display."""
    if timestamp:
        time_str = f"<small>{timestamp}</small>"
    else:
        time_str = ""

    if role == "user":
        return f"""
        <div class="chat-message user-message">
            <div class="msg-header">
                <div class="msg-avatar" style="background:#1976d2;color:white;display:flex;align-items:center;justify-content:center">👤</div>
                <div>
                    <div><strong>👤 You</strong> <span class="msg-meta">{time_str}</span></div>
                    <div class="msg-content">{content}</div>
                </div>
            </div>
        </div>
        """
    else:
        return f"""
        <div class="chat-message assistant-message">
            <div class="msg-header">
                <div class="msg-avatar" style="background:#4caf50;color:white;display:flex;align-items:center;justify-content:center">🤖</div>
                <div>
                    <div><strong>🤖 Assistant</strong> <span class="msg-meta">{time_str}</span></div>
                    <div class="msg-content">{content}</div>
                </div>
            </div>
        </div>
        """


def format_error(error_msg: str) -> str:
    """Format error message for display."""
    return f"""
    <div class="chat-message error-message">
        <div style="flex-grow: 1;">
            <strong>❌ Error</strong>
            <p>{error_msg}</p>
        </div>
    </div>
    """


def send_chat_request(
    user_query: str, user_role: str, connection_config: Dict
) -> Dict[str, Any]:
    """Send chat request to API and return response."""
    try:
        payload = {
            "user_id": st.session_state.user_id,
            "query": user_query,
            "user_role": user_role,
            "history": st.session_state.chat_history,
            "session_context": {
                "user_id": st.session_state.user_id,
                "user_role": user_role,
                "timestamp": datetime.now().isoformat(),
                "filters": {},
                "rbac_enforced": True,
            },
            "connection_string": connection_config,
            "model": "meta-llama/llama-4-scout-17b-16e-instruct",
        }

        response = requests.post(
            st.session_state.api_url,
            json=payload,
            timeout=60,
        )
        response.raise_for_status()

        return response.json()

    except requests.exceptions.ConnectionError:
        return {
            "success": False,
            "message": f"❌ Failed to connect to API at {st.session_state.api_url}",
        }
    except requests.exceptions.Timeout:
        return {"success": False, "message": "❌ Request timed out (60s)"}
    except requests.exceptions.HTTPError as e:
        return {
            "success": False,
            "message": f"❌ API Error ({e.response.status_code}): {e.response.text}",
        }
    except Exception as e:
        return {"success": False, "message": f"❌ Error: {str(e)}"}


def display_response_graph(graph_data: Optional[Dict]) -> None:
    """Display graph/visualization from response."""
    if not graph_data:
        return

    col1, col2 = st.columns([3, 1])

    with col1:
        st.subheader("📊 Visualization")

        # Display chart type and reasoning
        chart_type = graph_data.get("chart_type", "unknown")
        title = graph_data.get("title", "Chart")
        reasoning = graph_data.get("reasoning", "")

        st.write(f"**Chart Type:** {chart_type}")
        st.write(f"**Title:** {title}")

        if reasoning:
            with st.expander("📝 Why this chart?"):
                st.write(reasoning)

        # Display stat card value
        if chart_type == "stat_card":
            value = graph_data.get("value")
            if value is not None:
                st.metric(label=title, value=value)

        # Display PNG image
        png_bytes = graph_data.get("png_bytes")
        if png_bytes:
            try:
                # If it's a base64 string, decode it
                if isinstance(png_bytes, str):
                    image_data = base64.b64decode(png_bytes)
                else:
                    image_data = png_bytes

                image = Image.open(BytesIO(image_data))
                st.image(image, use_column_width=True)
            except Exception as e:
                st.warning(f"Could not display image: {e}")

        # Display image URL if available
        image_url = graph_data.get("image_url")
        if image_url:
            st.write(f"**Image URL:** {image_url}")


def add_to_history(role: str, content: str, attachments: Optional[Dict] = None) -> None:
    """Add message to chat history. Attachments is an optional dict (e.g. {'png_bytes': b'..', 'filename': 'chart.png'})."""
    entry = {
        "role": role,
        "content": content,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    }
    if attachments:
        entry["attachments"] = attachments
    st.session_state.chat_history.append(entry)


def clear_history() -> None:
    """Clear chat history."""
    st.session_state.chat_history = []
    st.success("✅ Chat history cleared!")


# ============================================================================
# Main UI Layout
# ============================================================================

# Header
st.title("🤖 SQL Agent Chatbot")
st.markdown("_Ask questions about your data with role-based access control_")

# Sidebar: Configuration
with st.sidebar:
    st.header("⚙️ Configuration")

    # Theme toggle
    st.session_state.dark_mode = st.checkbox(
        "🌙 Dark mode", value=st.session_state.dark_mode
    )

    with st.expander("👤 User Settings", expanded=True):
        st.session_state.user_id = st.text_input(
            "User ID",
            value=st.session_state.user_id,
            help="Unique identifier for the user",
        )

        st.session_state.user_role = st.selectbox(
            "User Role (RBAC)",
            options=["customer", "sales", "admin", "analyst", "support"],
            index=0,
            help="Role determines table access and required filters",
        )

    with st.expander("🔌 Database Connection"):
        col1, col2 = st.columns(2)

        with col1:
            st.session_state.connection_config["db_type"] = st.selectbox(
                "DB Type",
                options=["mssql", "postgresql", "mysql", "sqlite"],
                index=0,
            )
            st.session_state.connection_config["server"] = st.text_input(
                "Server",
                value=st.session_state.connection_config["server"],
            )
            st.session_state.connection_config["database"] = st.text_input(
                "Database",
                value=st.session_state.connection_config["database"],
            )

        with col2:
            st.session_state.connection_config["username"] = st.text_input(
                "Username",
                value=st.session_state.connection_config["username"],
            )
            st.session_state.connection_config["password"] = st.text_input(
                "Password",
                value=st.session_state.connection_config["password"],
                type="password",
            )
            st.session_state.connection_config["port"] = st.number_input(
                "Port",
                value=st.session_state.connection_config["port"],
                min_value=1,
                max_value=65535,
            )

    with st.expander("🔗 API Endpoint"):
        st.session_state.api_url = st.text_input(
            "API URL",
            value=st.session_state.api_url,
            help="Full URL to chat endpoint",
        )

    # Connection info
    st.markdown("---")
    st.markdown("### ℹ️ Active Session")
    st.info(f"""
        **User:** {st.session_state.user_id}  
        **Role:** {st.session_state.user_role}  
        **DB:** {st.session_state.connection_config['database']}  
        **Server:** {st.session_state.connection_config['server']}
        """)


# Inject dynamic modern styles (overrides earlier styles)
def _inject_styles(dark: bool):
    if dark:
        bg = "#0f1724"
        card = "#0b1220"
        text = "#e6eef8"
        muted = "#9aa4ae"
        accent = "#3b82f6"
        accent2 = "#10b981"
        shadow = "0 6px 18px rgba(2,6,23,0.6)"
    else:
        bg = "#f7fafc"
        card = "#ffffff"
        text = "#0f1724"
        muted = "#6b7280"
        accent = "#2563eb"
        accent2 = "#16a34a"
        shadow = "0 6px 18px rgba(15,23,36,0.08)"

    css = f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap');
    .stApp {{ background: {bg}; font-family: Inter, system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial; color: {text}; }}
    .chat-message {{ background: {card}; border-radius: 14px; padding: 12px 14px; margin: 8px 4px; box-shadow: {shadow}; max-width:78%; word-break:break-word; }}
    .user-message {{ background: linear-gradient(180deg, rgba(37,99,235,0.06), rgba(37,99,235,0.03)); border: 1px solid rgba(37,99,235,0.12); color: {text}; margin-left:auto; text-align:left }}
    .assistant-message {{ background: linear-gradient(180deg, rgba(16,163,127,0.04), rgba(16,163,127,0.02)); border: 1px solid rgba(16,163,127,0.08); color: {text}; margin-right:auto; text-align:left }}
    .chat-container {{ display:flex; flex-direction:column; gap:6px; padding-bottom:12px }}
    .msg-header {{ display:flex; gap:10px; align-items:center }}
    .msg-avatar {{ width:40px; height:40px; border-radius:10px; display:inline-flex; align-items:center; justify-content:center; font-size:18px }}
    .msg-meta {{ font-size:12px; color:{muted}; margin-left:8px }}
    .msg-content {{ margin-top:6px; font-size:14px; line-height:1.45 }}
    .sidebar .stButton>button{{ background:{accent}; color:white; border-radius:8px }}
    .stDownloadButton>button{{ background:{accent2}; color:white; border-radius:8px }}
    textarea {{ border-radius:10px }}
    .stMetric {{ background:{card}; box-shadow:{shadow}; border-radius:10px }}
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)


_inject_styles(st.session_state.dark_mode)

# Main chat area
st.markdown("---")

# Chat history display
chat_container = st.container()
with chat_container:
    st.subheader("💬 Chat History")

    if not st.session_state.chat_history:
        st.info("👋 No messages yet. Start by typing a question!")
    else:
        for i, msg in enumerate(st.session_state.chat_history):
            role = msg.get("role", "assistant")
            content = msg.get("content", "")
            timestamp = msg.get("timestamp")

            st.markdown(
                format_message(role, content, timestamp),
                unsafe_allow_html=True,
            )
            # Render attachments (images, downloads)
            attachments = msg.get("attachments")
            if attachments:
                png_bytes = attachments.get("png_bytes")
                filename = attachments.get("filename", "chart.png")
                if png_bytes:
                    try:
                        if isinstance(png_bytes, str):
                            image_data = base64.b64decode(png_bytes)
                        else:
                            image_data = png_bytes

                        image = Image.open(BytesIO(image_data))
                        st.image(image, use_column_width=True)
                        st.download_button(
                            "⬇️ Download Image",
                            data=image_data,
                            file_name=filename,
                            mime="image/png",
                        )
                    except Exception as e:
                        st.warning(f"Could not render attachment: {e}")

# Chat input area
st.markdown("---")
st.subheader("✍️ Send Message")

col1, col2 = st.columns([4, 1])

with col1:
    user_input = st.text_area(
        "Your question:",
        placeholder="Ask me anything about your data...",
        height=80,
        label_visibility="collapsed",
    )

with col2:
    col2_1, col2_2 = st.columns(2)

    with col2_1:
        send_button = st.button("📤 Send", use_container_width=True)

    with col2_2:
        clear_button = st.button("🗑️ Clear", use_container_width=True)

# Handle button actions
if clear_button:
    clear_history()
    st.rerun()

if send_button and user_input.strip():
    # Add user message to history
    timestamp = datetime.now().strftime("%H:%M:%S")
    add_to_history("user", user_input)

    # Display the message immediately
    st.markdown(
        format_message("user", user_input, timestamp),
        unsafe_allow_html=True,
    )

    # Show loading indicator
    with st.spinner("🔄 Processing your request..."):
        # Send request to API
        response = send_chat_request(
            user_query=user_input,
            user_role=st.session_state.user_role,
            connection_config=st.session_state.connection_config,
        )

    # Handle response
    if response.get("success"):
        data = response.get("data", {})
        assistant_response = data.get("response", "No response generated.")
        # Determine attachments (e.g., PNG bytes) and add assistant message to history
        graph_data = data.get("graph")
        attachments = None
        if graph_data:
            png = graph_data.get("png_bytes")
            if png:
                attachments = {
                    "png_bytes": png,
                    "filename": graph_data.get("filename", "chart.png"),
                    "title": graph_data.get("title", "chart"),
                }

        # Add assistant message (with attachments if present)
        add_to_history("assistant", assistant_response, attachments=attachments)

        # Display response (use current timestamp)
        response_ts = datetime.now().strftime("%H:%M:%S")
        st.markdown(
            format_message("assistant", assistant_response, response_ts),
            unsafe_allow_html=True,
        )

        # Display graph (visualization section) if available
        if graph_data:
            st.markdown("---")
            display_response_graph(graph_data)
            # If graph contained inline png, also render a download button below the visualization
            png_bytes = graph_data.get("png_bytes")
            if png_bytes:
                try:
                    if isinstance(png_bytes, str):
                        imgdata = base64.b64decode(png_bytes)
                    else:
                        imgdata = png_bytes
                    st.download_button(
                        "⬇️ Download Chart PNG",
                        data=imgdata,
                        file_name=graph_data.get("filename", "chart.png"),
                        mime="image/png",
                    )
                except Exception:
                    pass

        # Display session context info if available
        session_context = data.get("session_context")
        if session_context:
            with st.expander("📋 Session Context (Advanced)"):
                st.json(session_context)

        st.success("✅ Response received!")

    else:
        error_msg = response.get("message", "Unknown error occurred")
        st.markdown(format_error(error_msg), unsafe_allow_html=True)
        st.session_state.chat_history.pop()  # Remove user message if API failed

elif send_button:
    st.warning("⚠️ Please enter a message first!")

# Footer
st.markdown("---")
st.markdown(
    """
    <div style='text-align: center; color: #888; font-size: 0.8rem;'>
    <p>🔐 Powered by SQL Agent with RBAC | 🗄️ Connected to Database | 🤖 LLM-Powered</p>
    <p>Messages and settings are stored in session memory. Refresh page to reset.</p>
    </div>
    """,
    unsafe_allow_html=True,
)
