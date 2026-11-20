"""Render the Streamlit page headless against the built marts and fail on any exception."""

from streamlit.testing.v1 import AppTest

at = AppTest.from_file("../app/app.py", default_timeout=60).run()
if at.exception:
    raise SystemExit(f"app raised: {at.exception}")
print("metrics:", ", ".join(f"{m.label}={m.value}" for m in at.metric))
