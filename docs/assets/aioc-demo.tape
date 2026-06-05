# aioc demo — probe a real OpenAI-compatible server and render the report.
#
# Render with:
#   vhs docs/assets/aioc-demo.tape
#
# Demo target is api.openai.com (unauth Phase A only — every endpoint
# returns 401 on an empty body, which the prober grades PASS because
# the route exists). Picks a public-reachable target so re-renders
# don't depend on a local server.

Output docs/assets/aioc-demo.gif

Set Theme "Catppuccin Mocha"
Set FontFamily "JetBrainsMono Nerd Font"
Set FontSize 14
Set Width 1100
Set Height 780
Set Padding 20
Set TypingSpeed 30ms
Set PlaybackSpeed 1.0
Set Margin 10
Set MarginFill "#1e1e2e"

Hide
Type "clear"
Enter
Show

Type "aioc --version"
Enter
Sleep 800ms

Type "# the catalog (truncated):"
Enter
Type "aioc spec | head -12"
Enter
Sleep 2500ms

Type "clear"
Enter
Sleep 200ms

Type "# probe api.openai.com — unauth, Phase A only"
Enter
Type "aioc probe https://api.openai.com --skip-phase-b --name openai --report report.json"
Enter
Sleep 5000ms

Type "# render the report — 30-row catalog, colored status"
Enter
Type "aioc render report.json --limit 12"
Enter
Sleep 5000ms
