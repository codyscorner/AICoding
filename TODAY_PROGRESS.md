# AI Coding — Daily Progress Tracker

---

## How to Use This File
- Update **Session Date** and **Current Branch** at the start of each day
- Add tasks to the priority list and check them off as you go
- Update the **Task Log** with a brief note when each task is done
- Commit this file at the end of every task so new context windows stay in sync

---

## Session Date: —
## Current Branch: master (clean)

---

## Priority List

*(Add tasks here at the start of each session)*

---

## Task Log

*(Add completed task notes here during the session)*

---

## How to Pick Up in a New Context Window

1. Read this file
2. Run `git status` and `git log --oneline -5` to confirm current state
3. Pick the next unchecked item from the priority list
4. Create a new branch: `git checkout -b feature/<project-name>-<description>`
5. Do the work, commit, push, PR to master
6. Check the item off and update the Task Log before switching context
