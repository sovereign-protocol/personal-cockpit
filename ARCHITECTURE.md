# Architecture

Personal Cockpit is an ordinary Sovereign application with no shared topic root.
It uses ApplicationHost's late-bound facade lookup. Each source adapter targets
an explicit facade API version; missing or incompatible sources contribute no
entries. Neither Core nor source applications import Personal Cockpit.

Current source adapters are S-Kanban, S-Agreement and S-decision. A
S-decision tile shows the current stage, what is required from the local user,
assigned-person count and agenda count.
