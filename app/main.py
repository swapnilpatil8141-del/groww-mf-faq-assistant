"""Application entry point.

Phase 1 scaffold only. Pipeline functionality will be implemented in later phases.
"""

from app.config import load_config


def main() -> None:
    config = load_config()
    source_urls = config.get("sources", {}).get("urls", [])
    print("Groww Mutual Fund Facts-Only FAQ Assistant")
    print(f"Configuration loaded successfully. Approved sources: {len(source_urls)}")


if __name__ == "__main__":
    main()
