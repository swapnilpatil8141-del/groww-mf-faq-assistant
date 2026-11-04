
"""Streamlit chat UI for the facts-only HDFC Mutual Fund FAQ assistant."""

from __future__ import annotations

import streamlit as st
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from app.config import PROJECT_ROOT, load_config
from app.guardrails import contains_pii
from app.orchestrator import answer_question


EXAMPLE_QUESTIONS = [
    "What is the expense ratio of HDFC Large Cap Fund?",
    "What is the lock-in period for HDFC ELSS Tax Saver Fund?",
    "What is the minimum SIP amount for HDFC Mid Cap Fund?",
]


def _source_registry_notice(config: dict) -> str | None:
    """Explain the known source-policy mismatch instead of implying Groww is official."""

    urls = [
        str(item.get("url", ""))
        for item in config.get("sources", {}).get("urls", [])
    ]

    if any("groww.in" in url for url in urls):
        return (
            "Source limitation: this prototype currently uses the five configured "
            "Groww pages. The architecture document specifies official HDFC/SEBI/AMFI "
            "sources, so these third-party pages should not be represented as official "
            "AMC or regulator sources. Resolve the source registry before production use."
        )

    return None


def _render_download_button(message: dict, message_index: int) -> None:
    """Offer assistant responses as plain text that can be opened in Notepad."""

    content = message.get("content", "")

    if message.get("role") == "assistant" and content:
        st.download_button(
            "Download response (.txt)",
            data=content,
            file_name="hdfc_faq_response.txt",
            mime="text/plain",
            key=f"download_response_{message_index}",
        )


def _render_message(message: dict, message_index: int) -> None:
    """Render a chat message, its citation, timestamp and retrieval details."""

    role = message.get("role", "assistant")

    with st.chat_message(role):
        st.markdown(message.get("content", ""))
        _render_download_button(message, message_index)

        # Display the verified source link.
        source = message.get("source")

        if source:
            title = source.get("title") or "Source page"
            url = source.get("url")

            if url:
                st.markdown(f"**Source:** [{title}]({url})")

            fetched_at = source.get("fetched_at")

            if fetched_at:
                st.caption(
                    f"Last updated from sources: retrieved on {fetched_at}"
                )

        # Display retrieval trace information.
        trace = message.get("trace")

        if trace:
            with st.expander("Retrieval details"):
                st.caption(
                    f"Trace ID: {trace.get('trace_id', 'not available')}"
                )

                chunk_ids = trace.get("retrieved_chunk_ids") or []

                st.write("**Retrieved chunk IDs**")

                st.code(
                    "\n".join(str(item) for item in chunk_ids)
                    or "No chunks returned."
                )

                source_ids = trace.get("retrieved_source_ids") or []

                st.write("**Retrieved source IDs**")

                st.code(
                    "\n".join(str(item) for item in source_ids)
                    or "No source IDs returned."
                )


def main() -> None:
    """Run the Streamlit application."""

    st.set_page_config(
        page_title="HDFC Mutual Fund FAQ Assistant",
        page_icon="💬",
        layout="centered",
    )

    st.markdown(
        """
        <style>
        .block-container {
            max-width: 900px;
            padding-top: 2rem;
        }

        .app-subtitle {
            color: #6b7280;
            margin-top: -0.5rem;
        }

        .disclaimer {
            border: 1px solid rgba(128,128,128,.35);
            border-radius: 10px;
            padding: 12px 14px;
            font-size: .9rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.title("HDFC Mutual Fund FAQ Assistant")

    st.markdown(
        '<p class="app-subtitle">'
        "Ask factual questions about the HDFC Mutual Fund pages "
        "in the current source collection."
        "</p>",
        unsafe_allow_html=True,
    )

    config = load_config()

    notice = _source_registry_notice(config)

    if notice:
        st.warning(notice)

    st.markdown(
        '<div class="disclaimer">'
        "<strong>Facts-only.</strong> No investment advice. "
        "Do not enter personal or account information."
        "</div>",
        unsafe_allow_html=True,
    )

    st.write("")

    # Initialize session state.
    if "messages" not in st.session_state:
        st.session_state.messages = []

    if "pending_question" not in st.session_state:
        st.session_state.pending_question = None

    # Example questions.
    st.markdown("**Try asking**")

    sample_columns = st.columns(3)

    for index, sample in enumerate(EXAMPLE_QUESTIONS):
        if sample_columns[index].button(
            sample,
            key=f"sample_question_{index}",
            use_container_width=True,
        ):
            st.session_state.pending_question = sample

    # Display previous messages.
    for message_index, message in enumerate(st.session_state.messages):
        _render_message(message, message_index)

    # Accept user question.
    typed_question = st.chat_input(
        "Ask a factual question about an HDFC mutual fund...",
        max_chars=1000,
    )

    question = typed_question or st.session_state.pending_question

    st.session_state.pending_question = None

    if question:

        # Block PII before storing the question or passing it to retrieval.
        if contains_pii(question):
            with st.chat_message("assistant"):
                st.warning(
                    "Please remove personal or account information and submit "
                    "your question again. Do not enter PAN, Aadhaar, account "
                    "numbers, OTPs, email addresses, or phone numbers."
                )

            return

        # Store and display the user question.
        st.session_state.messages.append(
            {
                "role": "user",
                "content": question,
            }
        )

        with st.chat_message("user"):
            st.markdown(question)

        # Generate the assistant response.
        with st.chat_message("assistant"):

            with st.spinner("Checking the source collection..."):
                result = answer_question(
                    question,
                    project_root=PROJECT_ROOT,
                )

            status = result.get("status")

            if status == "answered":

                st.markdown(result["answer"])

                source = result.get("source") or {}

                if source.get("url"):
                    st.markdown(
                        f"**Source:** "
                        f"[{source.get('title') or 'Source page'}]"
                        f"({source['url']})"
                    )

                fetched_at = source.get("fetched_at")

                if fetched_at:
                    st.caption(
                        f"Last updated from sources: retrieved on {fetched_at}"
                    )

                assistant_message = {
                    "role": "assistant",
                    "content": result["answer"],
                    "source": source,
                }

            elif status in {
                "refused",
                "blocked",
                "clarification",
                "out_of_scope",
                "cannot_verify",
            }:

                st.info(
                    result.get(
                        "message",
                        "I cannot verify that information from the available source content.",
                    )
                )

                assistant_message = {
                    "role": "assistant",
                    "content": result.get(
                        "message",
                        "I cannot verify that information from the available source content.",
                    ),
                }

            else:

                st.error(
                    result.get(
                        "message",
                        "The assistant is temporarily unavailable. "
                        "Please try again later.",
                    )
                )

                assistant_message = {
                    "role": "assistant",
                    "content": result.get(
                        "message",
                        "The assistant is temporarily unavailable. "
                        "Please try again later.",
                    ),
                }

            # Attach retrieval trace for all responses that have one.
            if result.get("trace_id"):
                assistant_message["trace"] = {
                    "trace_id": result.get("trace_id"),
                    "retrieved_chunk_ids": result.get(
                        "retrieved_chunk_ids", []
                    ),
                    "retrieved_source_ids": result.get(
                        "retrieved_source_ids", []
                    ),
                }

            assistant_message_index = len(st.session_state.messages)
            st.session_state.messages.append(assistant_message)
            _render_download_button(assistant_message, assistant_message_index)


if __name__ == "__main__":
    main()
