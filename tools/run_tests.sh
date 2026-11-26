#!/bin/bash
# Run the plugin's checks and tests.
#
#   tools/run_tests.sh              unit tests + architecture check (+ QGIS integration if found)
#   tools/run_tests.sh --unit       only what needs no QGIS
#
# QGIS discovery: $QGIS_PYTHON (a QGIS-enabled interpreter, with PYTHONPATH etc.
# already set by you) or, on macOS, the newest /Applications/QGIS*.app (override
# with $QGIS_APP). Integration tests run on a scratch copy of the plugin, so
# admin.sqlite / projects/ in this folder are never touched.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
status=0
section() { printf '\n== %s\n' "$1"; }

section "unit tests (pure Python, no QGIS)"
( cd "$ROOT" && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/unit -t . ) || status=1

section "architecture (layer dependency rules)"
python3 "$ROOT/tools/check_architecture.py" "$ROOT" || status=1

[ "${1:-}" = "--unit" ] && { [ $status = 0 ] && echo "ALL GREEN" || echo "FAILURES"; exit $status; }

# ── locate a QGIS Python ─────────────────────────────────────────────────────
qgis_python=()
if [ -n "${QGIS_PYTHON:-}" ]; then
    qgis_python=("$QGIS_PYTHON")
else
    app="${QGIS_APP:-$(ls -d /Applications/QGIS*.app 2>/dev/null | sort | tail -1)}"
    if [ -n "$app" ] && [ -d "$app" ]; then
        res="$app/Contents/Resources"
        pydir="$(ls -d "$res"/python3.* 2>/dev/null | head -1)"
        exe="$(ls "$app"/Contents/MacOS/python3.[0-9]* 2>/dev/null | grep -v '\.bak$' | head -1)"
        if [ -n "$pydir" ] && [ -n "$exe" ]; then
            qgis_python=(env PYTHONHOME="$res" PYTHONPATH="$pydir:$pydir/lib-dynload:$pydir/site-packages" "$exe")
        fi
    fi
fi
if [ ${#qgis_python[@]} = 0 ]; then
    section "QGIS integration tests"; echo "   SKIPPED (no QGIS Python found; set QGIS_PYTHON or QGIS_APP)"
    [ $status = 0 ] && echo "ALL GREEN (unit only)" || echo "FAILURES"; exit $status
fi
export QT_QPA_PLATFORM=offscreen

work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
fresh() {
    rm -rf "$work/plugins" "$work/settings"; mkdir -p "$work/plugins"
    rsync -a --exclude .git --exclude __pycache__ --exclude admin.sqlite --exclude projects \
          --exclude 'metadata.db*' "$ROOT/" "$work/plugins/q_assessment_wizard/"
}
run_qgis() {   # <name> <script> [args...]
    local name="$1"; shift
    section "$name"; fresh
    local out; out="$(cd /tmp && SP="$work" PLUGROOT="$work/plugins" "${qgis_python[@]}" "$@" 2>&1)"
    local rc=$?
    echo "$out" | grep -E "^(FAIL|RESULT)|NO CRASH|Segmentation|Traceback" | sed 's/^/   /' | tail -20
    [ $rc = 0 ] || status=1
}

section "Qt6 enum scan"
( cd /tmp && "${qgis_python[@]}" "$ROOT/tools/check_qt6_enums.py" "$ROOT" 2>/dev/null | tail -1 | sed 's/^/   /' ) \
    || status=1
run_qgis "integration: core flows" "$ROOT/tests/integration/qgis_core_flows.py"
run_qgis "integration: features + i18n" "$ROOT/tests/integration/qgis_features.py"
run_qgis "integration: overlay coverage semantics" "$ROOT/tests/integration/qgis_overlay_semantics.py"
section "integration: dock drag (Qt 6 crash workaround)"; fresh
drag="$(cd /tmp && PLUGROOT="$work/plugins" VARIANT=none "${qgis_python[@]}" \
        "$ROOT/tests/integration/qgis_dock_drag.py" plugin 10 2>&1)"
if echo "$drag" | grep -q "NO CRASH" && echo "$drag" | grep -q "after unload animated: True"; then
    echo "   OK"
else
    echo "   FAIL"; echo "$drag" | grep -E "Segmentation|Traceback|Error" | head -5; status=1
fi

echo; [ $status = 0 ] && echo "ALL GREEN" || echo "FAILURES"
exit $status
