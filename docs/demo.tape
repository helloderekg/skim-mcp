# VHS tape (github.com/charmbracelet/vhs) - renders docs/demo.gif for the README.
#   vhs docs/demo.tape
Output docs/demo.gif
Set FontSize 15
Set Width 1100
Set Height 620
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms

Type "python demo.py"
Enter
Sleep 6s
Type "uv run skim-meter --once"
Enter
Sleep 6s
