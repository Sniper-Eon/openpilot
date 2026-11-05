# Navigation model test branch

User decision 2026-11-05: branch from Sniper-Eon/openpilot codex/egpu-jetlink-navassist, use Mac M4 inference through Jetlink, and migrate AGNOS to 19.9 using the C3/C3XL image protections from the user xpilot fork. This explicit test-branch choice supersedes the workspace default location for this task.

Keep Chinese UI, navigation and engagement repairs. No raw logs, credentials or model binaries in Git. Preserve native controls and Jetlink timeout/fallback rules. No device install, flash or activation is implied by source preparation.

Before implementation list failure cases and run a check that fails on the baseline. Record source checks, Mac replay, device build, activation and road validation separately. Consult upstream onemiless/xpilot AGENTS.md and relevant XPILOT.md/API rules when porting xpilot functionality; never assume a newer API exists here.
