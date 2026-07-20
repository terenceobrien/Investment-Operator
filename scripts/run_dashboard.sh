#!/usr/bin/env bash
# Launch the regime explorer dashboard.
#
# Loads .env, then runs Streamlit pointing at the dashboard file.
# Default port 8501.

set -e
cd "$(dirname "$0")/.."

if [ -x venv/bin/python ]; then
    STREAMLIT_CMD=(venv/bin/python -m streamlit)
elif command -v streamlit &> /dev/null; then
    STREAMLIT_CMD=(streamlit)
else
    echo "Streamlit not found. Install with: pip install streamlit plotly"
    exit 1
fi

if [ -f .env ]; then
    set -o allexport
    source .env
    set +o allexport
fi

"${STREAMLIT_CMD[@]}" run dashboard/regime_explorer.py "$@"
