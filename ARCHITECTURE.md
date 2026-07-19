# Architecture

Personal Cockpit is an ordinary Sovereign application with no shared topic root.
It uses ApplicationHost's late-bound facade lookup. Each source adapter targets
an explicit facade API version; missing or incompatible sources contribute no
entries. Neither Core nor source applications import Personal Cockpit.
