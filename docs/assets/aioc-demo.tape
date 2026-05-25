# aioc demo — probe a real llama.cpp build and read the report.
#
# Render with:
#   vhs docs/assets/aioc-demo.tape
#
# Assumes an OpenAI-compatible server reachable at http://127.0.0.1:8080.
# Generated against the ht-llama.cpp fork on lithium (HT-compat 1.0;
# /v1/reranking + /v1/chat/completions[omni] wired up).

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

Type "# probe llama.cpp + HT-compat extensions"
Enter
Type "aioc probe http://127.0.0.1:8080 --profile ht --skip-phase-b --name ht-llama.cpp --report report.json"
Enter
Sleep 2500ms

Type "# render the report"
Enter
Type "aioc render report.json"
Enter
Sleep 5000ms
