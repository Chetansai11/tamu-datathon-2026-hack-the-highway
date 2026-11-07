# Rules for every agent in this repo

Several agents work on this challenge at once. You share one board, `coord.py`. Skipping it means duplicated work and overwritten files.

## Your loop

1. **Start:** `python coord.py brief`. Read the goal, what's taken, and what has failed.
2. **Claim:** `python coord.py claim --agent YOUR-NAME`. Work only on the task it gives you.
3. **Before trying an approach:** `python coord.py search "topic"`. If it failed already, don't repeat it unless you have a new idea, and say what's new.
4. **While working:** every 15 minutes or at each milestone, `python coord.py note TASK "what you learned" --agent YOUR-NAME`. This shows you're alive. Tasks silent for 45 minutes can be taken over.
5. **Finish:**
   - Worked: `python coord.py done TASK --result "measured result" --agent YOUR-NAME`
   - Didn't work: `python coord.py fail TASK --why "specific reason" --agent YOUR-NAME`
   - Waiting on a human or another task: `python coord.py block TASK --why "..." --agent YOUR-NAME`
6. Commit your work with the task ID in the message, then go back to step 2.

Use a stable name such as `claude-1`, `codex-2` or `cursor-1`, or set `COORD_AGENT`.

## Keep the shared memory useful

| When | Run |
|---|---|
| An approach worked or failed | `python coord.py tried "method" --outcome failed --why "reason" --score 0.61 --agent NAME` |
| You find work nobody listed | `python coord.py add "title" --priority 2 --files src/x.py --agent NAME` |
| A choice affects other agents | `python coord.py decide "choice" --why "reason" --agent NAME` |
| You have a result | `python coord.py score "model v3" 0.74 --metric win_rate --agent NAME` |

Be specific. "Didn't work" helps nobody. "PPO stuck at 52% vs heuristic after 2M steps: observation was missing boosts" saves someone an hour. Log failures straight away, because they're the most valuable thing here.

## Don't collide

- **Stay inside your task's `files` scope.** Tasks that share files can't run together, so set `--files` when you add one.
- **Use your own checkout if another agent is editing code here:** `python coord.py worktree YOUR-NAME` prints a private folder on the branch `agent/YOUR-NAME`. The board stays shared from every worktree.
- Merge into `main` only when your task is done and its checks pass.
- `coord/STATUS.md` is generated. Change it with `coord.py`, and put the goal in `coord/GOAL.md`.

## Python and files

- Use the shared environment: `C:\Users\asus\Desktop\MS\Datathon\.venv\Scripts\python.exe`. `coord.py` runs on any Python.
- **Don't change the shared environment without a `decide` entry.** One careless `pip install` can replace GPU PyTorch for all eight challenges. Add new packages to this repo's `requirements.txt` as well.
- Everything stays in this folder: code in `src/`, data in `data/`, outputs in `outputs/`, models in `runs/`, write-ups in `docs/`.
- API keys are in `..\..\.env`, outside this repo. Read them with `toolkit/prize_apis.py`. Never copy a key into this repo.

## Honest results

- Report measured numbers and how you measured them. Run the check before saying it passes.
- Compare to a baseline. For RL, use `toolkit/rl/arena.py`, not training reward.
- If you couldn't verify something, say so in your `done` result.
- Check `coord/GOAL.md` for the deadline. After the feature freeze, fix bugs only.

## Human-only actions

Ask the human before: pushing, submitting, publishing, paying, creating accounts, accepting terms, or signing an NDA.

The goal and rules live in `coord/GOAL.md`. **If a challenge rule conflicts with these notes, the challenge rule wins.**
