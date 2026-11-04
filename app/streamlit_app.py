"""Dark fintech-style Streamlit interface for the facts-only HDFC Mutual Fund FAQ assistant."""

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


PROMPTS = [
    ("Expense ratio", "What is the expense ratio of HDFC Large Cap Fund?"),
    ("Scheme benchmark", "What is the benchmark of HDFC Flexi Cap Fund?"),
    ("ELSS lock-in", "What is the lock-in period for HDFC ELSS Tax Saver Fund?"),
    ("Mid Cap facts", "What is the expense ratio of HDFC Mid Cap Fund?"),
]
SCHEMES = ["HDFC Large Cap", "HDFC Flexi Cap", "HDFC ELSS Tax Saver", "HDFC Mid Cap"]


def _source_registry_notice(config: dict) -> str | None:
    urls = [
        str(item.get("url", ""))
        for item in config.get("sources", {}).get("urls", [])
    ]
    if any("groww.in" in url for url in urls):
        return (
            "Source note: this prototype currently references Groww pages. "
            "They are third-party sources, not official HDFC AMC, SEBI or AMFI publications."
        )
    return None


def _styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --bg:#101715; --panel:#18221f; --panel2:#1d2b26;
            --line:rgba(91,226,168,.22); --green:#48e6a0;
            --green2:#10b981; --text:#edf7f1; --muted:#9aada4;
        }
        .stApp {
            background:
              radial-gradient(ellipse at 53% 38%, rgba(17,112,77,.24), transparent 42%),
              radial-gradient(ellipse at 92% 5%, rgba(30,95,70,.13), transparent 32%),
              var(--bg);
            color:var(--text);
        }
        /* Remove Streamlit's floating Share/star/edit toolbar from the product canvas. */
        [data-testid="stToolbar"],
        [data-testid="stHeaderActionElements"] {
            display:none !important;
        }
        [data-testid="stHeader"] {
            height:0 !important;
            min-height:0 !important;
            background:transparent !important;
            border:0 !important;
            box-shadow:none !important;
        }
        [data-testid="stDecoration"] {display:none !important;}

        /* Turn Streamlit's fixed chat dock into a seamless part of the dark workspace. */
        [data-testid="stBottom"],
        [data-testid="stBottom"] > div,
        [data-testid="stBottom"] [data-testid="stBottomBlockContainer"],
        .stChatFloatingInputContainer {
            background:linear-gradient(180deg,rgba(16,23,21,.94),#101715 35%) !important;
            border:0 !important;
            box-shadow:none !important;
        }
        [data-testid="stBottom"] {
            border-top:1px solid rgba(91,226,168,.16) !important;
            padding:10px 0 12px !important;
        }
        [data-testid="stBottom"] [data-testid="stBottomBlockContainer"] {
            padding-top:8px !important;
            padding-bottom:8px !important;
        }
        .stChatFloatingInputContainer {
            padding:0 1.5rem !important;
        }
        [data-testid="stBottom"] [data-testid="stChatInput"],
        .stChatFloatingInputContainer [data-testid="stChatInput"] {
            max-width:1120px !important;
            margin:0 auto !important;
            background:linear-gradient(145deg,#1b2a24,#17231e) !important;
            border:1px solid rgba(72,230,160,.42) !important;
            border-radius:18px !important;
            box-shadow:0 10px 38px rgba(0,0,0,.34),0 0 24px rgba(32,190,123,.07) !important;
        }
        [data-testid="stBottom"] [data-testid="stChatInput"]:focus-within {
            border-color:#48e6a0 !important;
            box-shadow:0 0 0 2px rgba(72,230,160,.12),0 12px 38px rgba(0,0,0,.38) !important;
        }
        [data-testid="stBottom"] [data-testid="stChatInput"] textarea {
            color:#f1faf4 !important;
            caret-color:#48e6a0;
        }
        [data-testid="stBottom"] [data-testid="stChatInput"] textarea::placeholder {
            color:#91a69b !important;
        }
        .block-container {max-width:1500px; padding:1.4rem 2rem 7rem;}
        [data-testid="stSidebar"] {
            background:linear-gradient(180deg,#141e1b,#111916);
            border-right:1px solid var(--line);
        }
        [data-testid="stSidebar"] > div {padding-top:1.2rem;}
        [data-testid="stSidebar"] * {color:var(--text);}
        .brand {display:flex; align-items:center; gap:11px; margin:0 0 2rem;}
        .brand-mark {
            width:39px;height:39px;border-radius:13px;display:grid;place-items:center;
            background:linear-gradient(145deg,#1ecb83,#08764f);color:#061c12;
            font-weight:900;font-size:14px;box-shadow:0 0 24px rgba(55,230,157,.2);
        }
        .brand-name {font-size:18px;font-weight:800;letter-spacing:-.03em;color:#f1fff7;}
        .brand-sub {font-size:10px;color:#8ba398;margin-top:2px;}
        .side-label {font-size:10px;letter-spacing:.16em;text-transform:uppercase;
            color:#789187;margin:1.5rem 0 .55rem;font-weight:800;}
        .side-note {font-size:12px;line-height:1.65;color:#91a69b;}
        .topline {display:flex;justify-content:space-between;align-items:center;
            padding:.15rem 0 1.1rem;border-bottom:1px solid rgba(125,165,145,.13);
            margin-bottom:2.2rem;}
        .workspace-tag {color:#9fb4a9;font-size:11px;letter-spacing:.12em;
            text-transform:uppercase;font-weight:750;}
        .status-pill {display:inline-flex;align-items:center;gap:7px;
            border:1px solid rgba(72,230,160,.25);background:rgba(28,112,77,.16);
            color:#7df0b8;border-radius:999px;padding:7px 11px;font-size:10px;font-weight:750;}
        .status-dot {width:6px;height:6px;border-radius:50%;background:#48e6a0;
            box-shadow:0 0 9px #48e6a0;}
        .hero {text-align:center;padding:2.4rem 0 1.2rem;}
        .hero-kicker {color:#58e7a7;font-size:10px;letter-spacing:.2em;
            font-weight:850;text-transform:uppercase;margin-bottom:1.2rem;}
        .hero h1 {color:#f0f8f3;font-size:clamp(32px,4.3vw,52px);
            line-height:1.12;letter-spacing:-.055em;font-weight:820;
            max-width:820px;margin:0 auto 15px;}
        .hero p {color:#9cafa5;color:#9cafa5; font-size:15px;line-height:1.7;
            max-width:720px;margin:0 auto;}
        .prompt-hint {color:#6f8d80;text-align:center;font-size:10px;
            letter-spacing:.16em;text-transform:uppercase;font-weight:800;
            margin:1.9rem 0 .8rem;}
        div.stButton > button {
            min-height:55px;width:100%;white-space:normal;text-align:left;
            border:1px solid rgba(103,163,133,.2);border-radius:12px;
            background:rgba(24,36,31,.78);color:#dcece3;padding:11px 14px;
            font-size:12px;box-shadow:0 5px 22px rgba(0,0,0,.12);
            transition:all .16s ease;
        }
        div.stButton > button:hover {
            border-color:rgba(72,230,160,.62);background:rgba(31,66,49,.82);
            color:#8cf3bd;transform:translateY(-1px);
        }
        div.stButton > button[kind="primary"] {
            background:linear-gradient(135deg,#54efaa,#19bd7c);
            color:#092116;border:0;font-weight:800;text-align:center;
        }
        .panel {
            background:linear-gradient(145deg,rgba(27,42,36,.9),rgba(19,29,25,.88));
            border:1px solid rgba(99,167,132,.2);border-radius:16px;
            padding:16px 17px;margin-bottom:13px;
            box-shadow:0 12px 32px rgba(0,0,0,.13);
        }
        .panel-title {font-size:12px;font-weight:800;color:#e5f4eb;margin-bottom:12px;}
        .scheme-row {font-size:11px;color:#b4c8bd;padding:8px 0;
            border-bottom:1px solid rgba(130,165,145,.1);}
        .scheme-row:last-child {border-bottom:0;}
        .scheme-dot {color:#4de5a1;margin-right:8px;}
        .mini-copy {font-size:11px;line-height:1.65;color:#91a69b;}
        [data-testid="stChatMessage"] {
            background:rgba(25,38,32,.92);border:1px solid rgba(103,163,133,.18);
            border-radius:16px;padding:1rem 1.1rem;margin-bottom:.8rem;
        }
        [data-testid="stChatMessage"] p {color:#e4f0e9;}
        [data-testid="stChatInput"] {
            border:1px solid rgba(72,230,160,.35);border-radius:17px;
            background:#1a2822;box-shadow:0 10px 35px rgba(0,0,0,.24);
        }
        [data-testid="stChatInput"]:focus-within {
            border-color:#48e6a0;box-shadow:0 0 0 2px rgba(72,230,160,.1);
        }
        [data-testid="stChatInput"] textarea {color:#f1faf4;}
        .source-link {display:inline-block;margin-top:10px;padding:7px 11px;
            border:1px solid rgba(72,230,160,.25);border-radius:8px;
            background:rgba(25,112,75,.15);font-size:11px;}
        .source-link a {color:#75edb4!important;text-decoration:none;font-weight:750;}
        .meta {color:#839b8e;font-size:10px;margin-top:7px;}
        .footer {text-align:center;color:#71877c;font-size:10px;
            padding:1rem 0 .3rem;line-height:1.6;}
        [data-testid="stExpander"] {border:1px solid rgba(103,163,133,.18);
            border-radius:10px;background:rgba(22,33,28,.65);}
        @media(max-width:850px) {
            .block-container {padding:1rem 1rem 5rem;}
            .hero {padding:1.5rem 0 .7rem;}
            .topline {margin-bottom:1.1rem;}
        }
        </style>
        """.replace("#9cafa5;color:#9cafa5;", "#9cafa5;"),
        unsafe_allow_html=True,
    )


def _render_sidebar() -> None:
    with st.sidebar:
        st.markdown(
            '<div class="brand"><div class="brand-mark">mf</div><div>'
            '<div class="brand-name">Fund Facts</div>'
            '<div class="brand-sub">HDFC Mutual Fund Research</div></div></div>',
            unsafe_allow_html=True,
        )
        if st.button("＋   New conversation", use_container_width=True, type="primary"):
            st.session_state.messages = []
            st.rerun()
        st.markdown('<div class="side-label">Workspace</div>', unsafe_allow_html=True)
        st.markdown('<div class="side-note">Your focused space for source-backed mutual fund facts.</div>', unsafe_allow_html=True)
        st.markdown('<div class="side-label">Covered schemes</div>', unsafe_allow_html=True)
        for scheme in SCHEMES:
            st.markdown(
                f'<div class="scheme-row"><span class="scheme-dot">●</span>{html.escape(scheme)}</div>',
                unsafe_allow_html=True,
            )
        st.markdown('<div class="side-label">Guardrails</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="side-note">Facts-only answers<br>No buy / sell / hold advice'
            '<br>Personal information blocking<br>Source links where available</div>',
            unsafe_allow_html=True,
        )
        st.markdown('<div class="side-label">Session</div>', unsafe_allow_html=True)
        st.markdown('<div class="side-note">Conversation history is available in this active session.</div>', unsafe_allow_html=True)


def _render_source(source: dict) -> None:
    if not source:
        return
    title = html.escape(str(source.get("title") or "Source page"))
    url = source.get("url")
    fetched_at = source.get("fetched_at")
    if url:
        safe_url = html.escape(str(url), quote=True)
        st.markdown(
            f'<div class="source-link"><a href="{safe_url}" target="_blank" '
            f'rel="noopener noreferrer">{title} ↗</a></div>',
            unsafe_allow_html=True,
        )
    if fetched_at:
        st.markdown(
            f'<div class="meta">Last updated from sources: {html.escape(str(fetched_at))}</div>',
            unsafe_allow_html=True,
        )


def _render_trace(trace: dict) -> None:
    if not trace:
        return
    with st.expander("Inspect retrieval details"):
        st.caption(f"Trace ID: {trace.get('trace_id', 'not available')}")
        st.write("Retrieved chunks")
        st.code("\n".join(str(x) for x in trace.get("retrieved_chunk_ids", [])) or "None")
        st.write("Retrieved source IDs")
        st.code("\n".join(str(x) for x in trace.get("retrieved_source_ids", [])) or "None")


def _render_history() -> None:
    for message in st.session_state.messages:
        role = message.get("role", "assistant")
        with st.chat_message(role, avatar="You" if role == "user" else "mf"):
            st.markdown(message.get("content", ""))
            if role == "assistant":
                _render_source(message.get("source") or {})
                _render_trace(message.get("trace") or {})


def _answer(question: str) -> None:
    if contains_pii(question):
        st.warning(
            "Please remove personal or account information before asking. "
            "Never enter PAN, Aadhaar, account numbers, OTPs, email addresses or phone numbers."
        )
        return

    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user", avatar="You"):
        st.markdown(question)

    with st.chat_message("assistant", avatar="mf"):
        with st.spinner("Searching the configured source collection…"):
            result = answer_question(question, project_root=PROJECT_ROOT)

        if result.get("status") == "answered":
            answer = result.get("answer", "")
            st.markdown(answer)
            source = result.get("source") or {}
            _render_source(source)
            saved = {"role": "assistant", "content": answer, "source": source}
        else:
            message = result.get(
                "message",
                "I cannot verify that information from the available source content.",
            )
            if result.get("status") in {
                "refused", "blocked", "clarification", "out_of_scope", "cannot_verify"
            }:
                st.info(message)
            else:
                st.error(message)
            saved = {"role": "assistant", "content": message}

        if result.get("trace_id"):
            saved["trace"] = {
                "trace_id": result.get("trace_id"),
                "retrieved_chunk_ids": result.get("retrieved_chunk_ids", []),
                "retrieved_source_ids": result.get("retrieved_source_ids", []),
            }
            _render_trace(saved["trace"])
        st.session_state.messages.append(saved)


def main() -> None:
    st.set_page_config(
        page_title="Fund Facts | HDFC Mutual Funds",
        page_icon="🌿",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _styles()
    config = load_config()
    if "messages" not in st.session_state:
        st.session_state.messages = []

    _render_sidebar()

    main_col, info_col = st.columns([3.7, 1.05], gap="large")
    with main_col:
        st.markdown(
            '<div class="topline"><div class="workspace-tag">Fund research workspace</div>'
            '<div class="status-pill"><span class="status-dot"></span>FACTS-ONLY MODE</div></div>',
            unsafe_allow_html=True,
        )

        if not st.session_state.messages:
            st.markdown(
                """
                <section class="hero">
                    <div class="hero-kicker">✦ Source-backed mutual fund information</div>
                    <h1>Ready for fund insights?<br>Ask anything.</h1>
                    <p>Get concise answers about the configured HDFC Mutual Fund schemes,
                    grounded in the information available in the source collection.</p>
                </section>
                """,
                unsafe_allow_html=True,
            )
            st.markdown('<div class="prompt-hint">Start with a suggested question</div>', unsafe_allow_html=True)
            for row in range(2):
                cols = st.columns(2, gap="small")
                for col_index in range(2):
                    label, question = PROMPTS[row * 2 + col_index]
                    with cols[col_index]:
                        if st.button(f"↗   {label}\n{question}", key=f"prompt_{row}_{col_index}"):
                            st.session_state.pending_question = question
                            st.rerun()
        else:
            st.markdown('<div class="prompt-hint">Conversation</div>', unsafe_allow_html=True)
            _render_history()

    with info_col:
        st.markdown(
            '<div class="panel"><div class="panel-title">◈  Covered schemes</div>'
            + "".join(
                f'<div class="scheme-row"><span class="scheme-dot">●</span>{html.escape(s)}</div>'
                for s in SCHEMES
            )
            + '</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="panel"><div class="panel-title">✓  Assistant guardrails</div>'
            '<div class="mini-copy">Facts-only responses<br><br>No investment recommendations'
            '<br><br>Personal information blocking<br><br>Source-grounded answers</div></div>',
            unsafe_allow_html=True,
        )
        notice = _source_registry_notice(config)
        if notice:
            st.markdown(
                '<div class="panel"><div class="panel-title">ⓘ  Source transparency</div>'
                f'<div class="mini-copy">{html.escape(notice)}</div></div>',
                unsafe_allow_html=True,
            )

    typed = st.chat_input("Ask a factual question about an HDFC mutual fund…", max_chars=1000)
    pending = st.session_state.pop("pending_question", None)
    question = typed or pending
    if question:
        _answer(question)
        st.rerun()

    st.markdown(
        '<div class="footer">Facts-only · No investment advice · Never share PAN, Aadhaar, OTP, '
        'phone, email or account details</div>',
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
