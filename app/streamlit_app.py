"""Polished Streamlit UI for the facts-only HDFC Mutual Fund FAQ assistant."""

from __future__ import annotations

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
    "What is the expense ratio of HDFC Large Cap Fund?",
    "What is the benchmark of HDFC Flexi Cap Fund?",
    "What is the lock-in period for HDFC ELSS Tax Saver Fund?",
]


def _source_registry_notice(config: dict) -> str | None:
    """Disclose that the current prototype uses Groww pages, not official sources."""
    urls = [
        str(item.get("url", ""))
        for item in config.get("sources", {}).get("urls", [])
    ]
    if any("groww.in" in url for url in urls):
        return (
            "This prototype currently uses five Groww pages, not official "
            "HDFC AMC, SEBI or AMFI sources. Verify important details with the "
            "relevant official source."
        )
    return None


def _inject_styles() -> None:
    """Apply a responsive, Groww-inspired visual theme without changing app logic."""
    st.markdown(
        """
        <style>
        :root {
            --brand-green: #00a86b;
            --brand-green-dark: #008b58;
            --ink: #17211c;
            --muted: #718078;
            --surface: #ffffff;
            --soft-green: #effaf4;
        }
        .stApp {
            background:
                radial-gradient(ellipse at 8% 0%, rgba(0,168,107,.07), transparent 32%),
                #f7faf8;
            color: var(--ink);
        }
        [data-testid="stHeader"] { background: rgba(247,250,248,.86); }
        .block-container {
            max-width: 980px;
            padding-top: 1.25rem;
            padding-bottom: 6rem;
        }
        [data-testid="stSidebar"] {
            background: #ffffff;
            border-right: 1px solid #e7eee9;
        }
        .brand-row {
            display: flex; align-items: center; gap: 11px;
            margin: 0 0 1rem 0;
        }
        .brand-mark {
            width: 38px; height: 38px; border-radius: 12px;
            display: grid; place-items: center;
            color: white; background: var(--brand-green);
            font-size: 20px; font-weight: 800;
            box-shadow: 0 5px 14px rgba(0,168,107,.2);
        }
        .brand-name { font-size: 15px; font-weight: 750; line-height: 1.15; }
        .brand-caption { font-size: 11px; color: var(--muted); margin-top: 3px; }
        .hero {
            padding: 1.2rem 1.45rem 1.1rem;
            border: 1px solid #e4eee8;
            border-radius: 22px;
            background: linear-gradient(125deg, #ffffff 20%, #f0fbf5 100%);
            box-shadow: 0 10px 35px rgba(23,65,43,.045);
            margin-bottom: .8rem;
        }
        .eyebrow {
            color: var(--brand-green-dark); text-transform: uppercase;
            font-size: 11px; letter-spacing: .12em; font-weight: 800;
            margin-bottom: 9px;
        }
        .hero h1 {
            color: #15251c; font-size: clamp(27px, 4vw, 39px);
            line-height: 1.12; letter-spacing: -.04em;
            margin: 0 0 10px 0; font-weight: 780;
        }
        .hero p { color: #64736a; font-size: 15px; margin: 0; line-height: 1.55; }
        .trust-strip {
            display: flex; flex-wrap: wrap; gap: 8px;
            margin-top: 17px;
        }
        .trust-pill {
            font-size: 11px; color: #3e6550; background: #e7f7ed;
            border: 1px solid #d6efdf; border-radius: 999px;
            padding: 5px 10px; font-weight: 650;
        }
        .section-label {
            color: #31443a; font-size: 13px; font-weight: 750;
            margin: 1.35rem 0 .65rem 0;
        }
        div.stButton > button {
            border-radius: 13px; border: 1px solid #e0eae4;
            background: #fff; color: #263a2e;
            min-height: 54px; white-space: normal;
            text-align: left; padding: 12px 14px;
            font-size: 13px; font-weight: 600;
            box-shadow: 0 3px 12px rgba(20,60,38,.035);
            transition: border-color .15s ease, transform .15s ease;
        }
        div.stButton > button:hover {
            border-color: #8dd7ae; color: #08794f;
            transform: translateY(-1px);
        }
        div.stButton > button[kind="primary"] {
            background: var(--brand-green); border-color: var(--brand-green);
            color: white; text-align: center;
        }
        [data-testid="stChatMessage"] {
            background: #fff; border: 1px solid #e9efeb;
            border-radius: 17px; padding: 1rem 1.1rem;
            box-shadow: 0 4px 18px rgba(23,65,43,.035);
            margin-bottom: .75rem;
        }
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
            background: #eff9f3; border-color: #e0f0e6;
        }
        [data-testid="stChatInput"] {
            border-radius: 16px; border: 1px solid #dce8e0;
            box-shadow: 0 8px 28px rgba(23,65,43,.08);
            background: #fff;
        }
        [data-testid="stChatInput"]:focus-within {
            border-color: #66c995;
            box-shadow: 0 0 0 3px rgba(0,168,107,.1);
        }
        .notice {
            border: 1px solid #f0dfb3; background: #fffaf0;
            color: #74551b; border-radius: 12px;
            padding: 11px 14px; font-size: 12px; line-height: 1.5;
            margin: .55rem 0 .7rem;
        }
        .safety-note {
            color: #6d7b72; font-size: 11px; line-height: 1.5;
            padding: 12px 2px 0;
        }
        .answer-source {
            border-left: 3px solid var(--brand-green);
            background: #f3faf5; border-radius: 0 10px 10px 0;
            padding: 9px 12px; margin-top: 10px;
            font-size: 12px;
        }
        a { color: #008b58 !important; }
        @media (max-width: 640px) {
            .block-container { padding: 1rem 1rem 5rem; }
            .hero { padding: 1.25rem; border-radius: 17px; }
            [data-testid="stChatMessage"] { padding: .8rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_brand() -> None:
    st.markdown(
        """
        <div class="brand-row">
            <div class="brand-mark">G</div>
            <div>
                <div class="brand-name">Fund Facts Assistant</div>
                <div class="brand-caption">HDFC Mutual Fund information</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_source(source: dict) -> None:
    if not source:
        return
    title = source.get("title") or "Source page"
    url = source.get("url")
    fetched_at = source.get("fetched_at")
    if url:
        st.markdown(
            f'<div class="answer-source"><strong>Source</strong> · '
            f'<a href="{url}" target="_blank">{title}</a></div>',
            unsafe_allow_html=True,
        )
    if fetched_at:
        st.caption(f"Last updated from sources: retrieved on {fetched_at}")


def _render_trace(trace: dict) -> None:
    if not trace:
        return
    with st.expander("How this answer was retrieved"):
        st.caption(f"Trace ID: {trace.get('trace_id', 'not available')}")
        chunk_ids = trace.get("retrieved_chunk_ids") or []
        source_ids = trace.get("retrieved_source_ids") or []
        st.write("**Retrieved chunks**")
        st.code("\n".join(str(item) for item in chunk_ids) or "No chunks returned.")
        st.write("**Source IDs**")
        st.code("\n".join(str(item) for item in source_ids) or "No source IDs returned.")


def _render_message(message: dict, message_index: int) -> None:
    role = message.get("role", "assistant")
    with st.chat_message(role):
        st.markdown(message.get("content", ""))
        if role == "assistant":
            _render_source(message.get("source") or {})
            _render_trace(message.get("trace") or {})
            content = message.get("content", "")
            if content:
                st.download_button(
                    "Download answer",
                    data=content,
                    file_name="hdfc_fund_faq_answer.txt",
                    mime="text/plain",
                    key=f"download_answer_{message_index}",
                )


def _answer(question: str) -> None:
    """Run the existing safety and RAG flow and persist the visible conversation."""
    if contains_pii(question):
        st.warning(
            "Please remove personal or account information before asking. "
            "Never enter PAN, Aadhaar, account numbers, OTPs, email addresses, "
            "or phone numbers."
        )
        return

    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Checking the available source information…"):
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
        page_title="Fund Facts Assistant | HDFC Mutual Funds",
        page_icon="🌱",
        layout="centered",
        initial_sidebar_state="expanded",
    )
    _inject_styles()

    config = load_config()
    if "messages" not in st.session_state:
        st.session_state.messages = []

    with st.sidebar:
        _render_brand()
        st.markdown("### Your research companion")
        st.caption(
            "Get concise, source-grounded facts from the currently configured "
            "HDFC Mutual Fund pages."
        )
        st.divider()
        st.markdown("**What you can ask**")
        st.markdown(
            "- Fund expense ratios\n"
            "- Scheme benchmarks\n"
            "- Lock-in periods\n"
            "- Other facts explicitly available in the sources"
        )
        st.divider()
        st.markdown("**Built-in safeguards**")
        st.caption(
            "Facts-only responses · Personal information blocking · "
            "No buy/sell/hold recommendations"
        )
        if st.button("＋  New conversation", use_container_width=True, type="primary"):
            st.session_state.messages = []
            st.rerun()
        st.markdown(
            '<div class="safety-note">Prototype for factual information only. '
            'Not investment advice. Always verify important details in the '
            'linked source.</div>',
            unsafe_allow_html=True,
        )

    st.markdown(
        """
        <section class="hero">
            <div class="eyebrow">Simple answers · Source-backed facts</div>
            <h1>Understand your fund.<br>One question at a time.</h1>
            <p>Ask about HDFC Mutual Fund schemes and get concise answers
            grounded in the information available in the source collection.</p>
            <div class="trust-strip">
                <span class="trust-pill">✓ Facts-only assistant</span>
                <span class="trust-pill">↗ Source links included</span>
                <span class="trust-pill">⌁ No investment advice</span>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    notice = _source_registry_notice(config)
    if notice:
        st.markdown(
            f'<div class="notice"><strong>Prototype source note</strong><br>{notice}</div>',
            unsafe_allow_html=True,
        )

    if not st.session_state.messages:
        st.markdown('<div class="section-label">Start with a popular question</div>', unsafe_allow_html=True)
        cols = st.columns(3)
        for index, sample in enumerate(EXAMPLE_QUESTIONS):
            if cols[index].button(sample, key=f"starter_{index}", use_container_width=True):
                st.session_state.pending_question = sample
                st.rerun()
        st.caption("Or type your own question below. Answers are limited to facts supported by the configured sources.")
    else:
        st.markdown('<div class="section-label">Conversation</div>', unsafe_allow_html=True)
        for index, message in enumerate(st.session_state.messages):
            _render_message(message, index)

    typed_question = st.chat_input(
        "Ask a factual question about an HDFC mutual fund…",
        max_chars=1000,
    )
    pending_question = st.session_state.pop("pending_question", None)
    question = typed_question or pending_question
    if question:
        _answer(question)

    st.markdown(
        '<div class="safety-note">Please do not share PAN, Aadhaar, account numbers, '
        'OTP, email addresses or phone numbers. This assistant does not provide '
        'investment recommendations.</div>',
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
