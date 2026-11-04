"""Streamlit interface for the facts-only HDFC Mutual Fund FAQ assistant."""

from __future__ import annotations

import html
import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import load_config
from app.guardrails import contains_pii
from app.orchestrator import answer_question


EXAMPLE_QUESTIONS = [
    ("％", "Expense ratio", "What is the expense ratio of HDFC Large Cap Fund?"),
    ("▣", "Scheme benchmark", "What is the benchmark of HDFC Flexi Cap Fund?"),
    ("◷", "ELSS lock-in", "What is the lock-in period for HDFC ELSS Tax Saver Fund?"),
    ("↗", "Mid Cap facts", "What is the expense ratio of HDFC Mid Cap Fund?"),
]

COVERED_SCHEMES = [
    "HDFC Large Cap",
    "HDFC Flexi Cap",
    "HDFC ELSS Tax Saver",
    "HDFC Mid Cap",
]


def _source_registry_notice(config: dict) -> str | None:
    """Disclose that this prototype currently uses Groww pages, not official sources."""
    urls = [
        str(item.get("url", ""))
        for item in config.get("sources", {}).get("urls", [])
    ]
    if any("groww.in" in url for url in urls):
        return (
            "This prototype currently references Groww pages. They are third-party "
            "sources, not official HDFC AMC, SEBI or AMFI publications."
        )
    return None


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --page: #f7f6ff;
            --ink: #19172e;
            --muted: #686681;
            --purple: #6041e8;
            --purple-soft: #eeeaff;
            --line: #e3defb;
            --card: #ffffff;
        }
        .stApp {
            background: var(--page);
            color: var(--ink);
        }
        [data-testid="stHeader"] { background: rgba(247,246,255,.92); }
        .block-container {
            max-width: 1040px;
            padding: 1.25rem 2rem 7rem;
        }
        [data-testid="stSidebar"] {
            background: #fff;
            border-right: 1px solid var(--line);
        }
        .topbar {
            display:flex; align-items:center; justify-content:space-between;
            gap:14px; padding: 0 0 1.25rem;
            border-bottom:1px solid var(--line); margin-bottom:2.1rem;
        }
        .brand {
            display:flex; align-items:center; gap:11px;
            color:var(--ink); font-size:19px; font-weight:800;
        }
        .brand-icon {
            width:38px; height:38px; display:grid; place-items:center;
            border-radius:12px; background:var(--purple); color:#fff;
            font-size:15px; font-weight:850;
        }
        .fund-tag {
            display:inline-block; margin-left:5px; padding:6px 12px;
            border-radius:999px; background:#e8eaff; color:#344bc3;
            font-size:12px; font-weight:650;
        }
        .hero { text-align:center; padding: .5rem 0 1.2rem; }
        .hero-dots { color:var(--purple); letter-spacing:5px; font-size:22px; margin-bottom:18px; }
        .hero h1 {
            max-width:760px; margin:0 auto 14px; color:var(--ink);
            font-size:clamp(30px,4.8vw,48px); line-height:1.12;
            letter-spacing:-.045em; font-weight:820;
        }
        .hero p {
            max-width:780px; margin:0 auto; color:var(--muted);
            font-size:16px; line-height:1.6;
        }
        .source-note {
            margin: .65rem auto 1.35rem; max-width:900px;
            padding:9px 13px; border:1px solid #e8e2ff;
            border-radius:12px; background:#f0edff;
            color:#625a87; font-size:11px; text-align:center;
        }
        .section-kicker {
            color:#777391; font-size:11px; font-weight:800;
            letter-spacing:.12em; text-transform:uppercase;
            margin:1.15rem 0 .7rem;
        }
        div.stButton > button {
            width:100%; min-height:78px; white-space:normal;
            text-align:left; padding:13px 16px;
            border:1px solid var(--line); border-radius:17px;
            background:var(--card); color:var(--ink);
            box-shadow:0 5px 18px rgba(55,42,120,.035);
            transition:all .16s ease;
        }
        div.stButton > button:hover {
            border-color:#b8aaff; background:#fcfbff;
            color:var(--purple); transform:translateY(-1px);
        }
        div.stButton > button[kind="primary"] {
            background:var(--purple); color:white; border-color:var(--purple);
            text-align:center;
        }
        .prompt-icon {
            color:var(--purple); font-size:18px; font-weight:800;
            display:inline-block; width:25px;
        }
        .prompt-title { color:var(--ink); font-size:14px; font-weight:750; }
        .prompt-subtitle { color:var(--muted); font-size:12px; margin:4px 0 0 25px; }
        .coverage {
            text-align:center; color:var(--muted); font-size:12px;
            margin:1rem 0 1.3rem;
        }
        .coverage strong { color:var(--ink); font-weight:700; }
        [data-testid="stChatMessage"] {
            border:1px solid var(--line); border-radius:18px;
            background:#fff; padding:1rem 1.1rem;
            box-shadow:0 5px 18px rgba(55,42,120,.035);
            margin-bottom:.8rem;
        }
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
            background:#eeeaff; border-color:#e5dfff;
        }
        [data-testid="stChatInput"] {
            border:1px solid #d9d1fa; border-radius:999px;
            background:#fff; box-shadow:0 8px 28px rgba(65,48,150,.09);
        }
        [data-testid="stChatInput"]:focus-within {
            border-color:#9b87f3; box-shadow:0 0 0 3px rgba(96,65,232,.09);
        }
        .answer-source {
            display:inline-block; margin-top:10px; padding:8px 13px;
            border:1px solid #ddd5ff; border-radius:999px;
            background:#f3f0ff; color:#5035ca; font-size:12px;
        }
        .answer-source a { color:#5035ca !important; text-decoration:none; font-weight:700; }
        .answer-meta { color:var(--muted); font-size:11px; margin-top:8px; }
        .safety-footer {
            text-align:center; color:#777391; font-size:11px;
            padding:7px 0 0; line-height:1.5;
        }
        @media(max-width:700px) {
            .block-container { padding:1rem 1rem 6rem; }
            .topbar { margin-bottom:1.3rem; }
            .brand { font-size:16px; }
            .fund-tag { font-size:10px; padding:5px 8px; }
            .hero { padding:.2rem 0 .7rem; }
            .hero p { font-size:14px; }
            div.stButton > button { min-height:70px; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_topbar() -> None:
    left, right = st.columns([5, 1.5], vertical_alignment="center")
    with left:
        st.markdown(
            '<div class="brand"><span class="brand-icon">mf</span>'
            'Fund Facts <span class="fund-tag">HDFC Mutual Fund</span></div>',
            unsafe_allow_html=True,
        )
    with right:
        if st.button("＋  New chat", use_container_width=True):
            st.session_state.messages = []
            st.rerun()


def _render_source(source: dict) -> None:
    if not source:
        return
    title = html.escape(str(source.get("title") or "Source page"))
    url = source.get("url")
    fetched_at = source.get("fetched_at")
    if url:
        safe_url = html.escape(str(url), quote=True)
        st.markdown(
            f'<div class="answer-source"><a href="{safe_url}" target="_blank" '
            f'rel="noopener noreferrer">{title} ↗</a></div>',
            unsafe_allow_html=True,
        )
    if fetched_at:
        st.markdown(
            f'<div class="answer-meta">Last updated from sources: '
            f'{html.escape(str(fetched_at))}</div>',
            unsafe_allow_html=True,
        )


def _render_trace(trace: dict) -> None:
    if not trace:
        return
    with st.expander("View retrieval details"):
        st.caption(f"Trace ID: {trace.get('trace_id', 'not available')}")
        st.write("**Retrieved chunks**")
        st.code("\n".join(str(x) for x in trace.get("retrieved_chunk_ids", [])) or "None")
        st.write("**Source IDs**")
        st.code("\n".join(str(x) for x in trace.get("retrieved_source_ids", [])) or "None")


def _render_message(message: dict, index: int) -> None:
    role = message.get("role", "assistant")
    avatar = "You" if role == "user" else "mf"
    with st.chat_message(role, avatar=avatar):
        st.markdown(message.get("content", ""))
        if role == "assistant":
            _render_source(message.get("source") or {})
            _render_trace(message.get("trace") or {})


def _answer(question: str) -> None:
    if contains_pii(question):
        st.warning(
            "Please remove personal or account information before asking. "
            "Never enter PAN, Aadhaar, account numbers, OTPs, email addresses, "
            "or phone numbers."
        )
        return

    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user", avatar="You"):
        st.markdown(question)

    with st.chat_message("assistant", avatar="mf"):
        with st.spinner("Finding a source-backed answer…"):
            result = answer_question(question, project_root=PROJECT_ROOT)

        status = result.get("status")
        if status == "answered":
            answer = result.get("answer", "")
            st.markdown(answer)
            source = result.get("source") or {}
            _render_source(source)
            assistant_message = {
                "role": "assistant",
                "content": answer,
                "source": source,
            }
        else:
            message = result.get(
                "message",
                "I cannot verify that information from the available source content.",
            )
            if status in {
                "refused", "blocked", "clarification", "out_of_scope", "cannot_verify"
            }:
                st.info(message)
            else:
                st.error(message)
            assistant_message = {"role": "assistant", "content": message}

        if result.get("trace_id"):
            assistant_message["trace"] = {
                "trace_id": result.get("trace_id"),
                "retrieved_chunk_ids": result.get("retrieved_chunk_ids", []),
                "retrieved_source_ids": result.get("retrieved_source_ids", []),
            }
            _render_trace(assistant_message["trace"])

        st.session_state.messages.append(assistant_message)


def main() -> None:
    st.set_page_config(
        page_title="Fund Facts | HDFC Mutual Funds",
        page_icon="💜",
        layout="centered",
        initial_sidebar_state="collapsed",
    )
    _inject_styles()

    config = load_config()
    if "messages" not in st.session_state:
        st.session_state.messages = []

    _render_topbar()

    if not st.session_state.messages:
        st.markdown(
            """
            <section class="hero">
                <div class="hero-dots">● ● ●</div>
                <h1>What would you like to know<br>about your fund?</h1>
                <p>Clear, concise facts about HDFC Mutual Fund schemes, with the
                available source linked to every supported answer.</p>
            </section>
            """,
            unsafe_allow_html=True,
        )

        notice = _source_registry_notice(config)
        if notice:
            st.markdown(
                f'<div class="source-note">{html.escape(notice)}</div>',
                unsafe_allow_html=True,
            )

        st.markdown('<div class="section-kicker">Explore common questions</div>', unsafe_allow_html=True)
        for row in range(2):
            cols = st.columns(2, gap="medium")
            for col_index in range(2):
                index = row * 2 + col_index
                symbol, label, question = EXAMPLE_QUESTIONS[index]
                with cols[col_index]:
                    if st.button(
                        f"{symbol}   {label}\n\n{question}",
                        key=f"prompt_{index}",
                        use_container_width=True,
                    ):
                        st.session_state.pending_question = question
                        st.rerun()

        st.markdown(
            '<div class="coverage">Currently covers: <strong>'
            + " · ".join(COVERED_SCHEMES)
            + "</strong></div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown('<div class="section-kicker">Your conversation</div>', unsafe_allow_html=True)
        for index, message in enumerate(st.session_state.messages):
            _render_message(message, index)

    typed_question = st.chat_input(
        "Ask about expense ratio, benchmark, lock-in…",
        max_chars=1000,
    )
    pending_question = st.session_state.pop("pending_question", None)
    question = typed_question or pending_question
    if question:
        _answer(question)

    st.markdown(
        '<div class="safety-footer">Facts-only · No investment advice · '
        'Never share PAN, Aadhaar, OTP, phone, email or account details</div>',
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
