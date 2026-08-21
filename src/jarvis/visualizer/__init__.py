"""Live visual HUD for JARVIS -- a local-only web page (opened in the
default browser from the menu bar's "Visualizar Interação" button) showing
an animated blue orb that reflects JARVIS's real state (idle/listening/
speaking) plus the text currently being heard or spoken.

Not audio-reactive (no real mic/speaker amplitude is streamed) -- the
"speaking" animation is a procedurally generated pulse/waveform, visually
alive but not literally driven by the audio samples. state.py is the
source of truth conversation.py publishes to; server.py fans it out to
however many browser tabs are open via Server-Sent Events (plain stdlib
http.server -- no new dependency, unlike WebSockets)."""
