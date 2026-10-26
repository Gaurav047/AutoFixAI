# AutoFixAI demo video script

Target length: about 2:45, under the 3-minute limit. The video is built around a live run on the Nebius Serverless Endpoint, and every number in it comes from real runs.

## Before you record

- Open the live site and run one demo so the endpoint is warm.
- Set the browser zoom to 110% and hide your bookmarks bar.
- Pre-record the terminal clip for scene 5 (see [below](#scene-5-terminal-clip)), so you don't wait on it live.
- **Never show `.env` on screen.** It contains your API key.

---

## 1 · Hook (0:00 – 0:15)

**On screen:** a GitHub Actions run with a red ✕. Cut to the AutoFixAI dashboard home.

> "A red CI build stops a whole team. Someone has to dig through the log, reproduce it, find the regression and patch it. That's half an hour, for what's usually a two-line bug. AutoFixAI does that loop for you: red build in, verified pull request out."

## 2 · What it is (0:15 – 0:35)

**On screen:** the home page. Point at the three Nemotron tier cards and the five-step list.

> "It's an agent built on three NVIDIA Nemotron models, all served by Nebius Token Factory. Nano triages failures and writes the PR. Super is the coding agent. Ultra only steps in when Super's fix is rejected. Every fix is checked by actually rerunning the tests."

## 3 · Live run (0:35 – 1:35)

**On screen:** click **Inventory refactor**. Let the run play out in real time; it takes about 17 seconds. Narrate over the timeline.

> "This is live on Nebius Serverless Endpoints. This repo has a half-finished refactor: a field was renamed, and a pricing function's arguments were reordered, but the service layer was never updated."

*(Baseline FAIL appears.)*

> "First it reproduces the failure in an isolated copy of the repo, so the agent never touches the original."

*(The Triage card appears.)*

> "Nano classifies the failure in about a second and names the files it suspects."

*(Tool calls scroll by: read_file, edit, run_tests.)*

> "Now Super works in a tool-calling loop. It reads the code, searches, makes exact edits and reruns the tests."

*(The Verify step goes green.)*

> "When the agent says it's done, AutoFixAI doesn't take its word for it. It reruns the test suite itself. Green."

## 4 · The result (1:35 – 2:00)

**On screen:** scroll through the verified patch, then the PR write-up.

> "Here's the patch: two lines, both bugs. The second one is subtle, because swapped arguments only produce wrong prices on bulk orders. And here's the pull request Nano wrote, with the root cause, the fix and how it was verified. Seventeen seconds, start to finish."

## 5 · Model routing and escalation (2:00 – 2:25)

**On screen:** point at the **Model routing** panel. Then cut to the pre-recorded terminal clip, sped up 2×.

> "This panel shows where the tokens went: Nano for the cheap structured calls, Super for the real work, and Ultra sitting idle until it's needed. When Super's attempt is rejected, Nano writes up what went wrong, the workspace is reset, and Ultra takes over. Here it is fixing the rate limiter in ten seconds."

## 6 · Guardrails and real CI (2:25 – 2:45)

**On screen:** the README's *Guardrails* section, then [`examples/github-action/autofix.yml`](../examples/github-action/autofix.yml).

> "The agent can't touch anything outside its sandbox, can't run arbitrary commands, and can't make CI pass by editing the tests. Those edits are blocked. Drop this GitHub Action into any repo, and every failed build gets a fix PR."

## 7 · Close (2:45 – 2:55)

**On screen:** the GitHub repo page, then the live URL.

> "AutoFixAI: NVIDIA Nemotron on Nebius Token Factory, deployed on Nebius Serverless. The code is open source under MIT, and the link's below."

---

## Scene 5 terminal clip

Record these from the project root:

```bash
cd backend
AUTOFIX_ESCALATE_AFTER=0 python -m autofix fix ../examples/rate-limiter
```

In PowerShell, set the variable first with `$env:AUTOFIX_ESCALATE_AFTER=0`, then run `python -m autofix fix ../examples/rate-limiter` on its own.

That setting sends the first attempt straight to Ultra. The clip shows Ultra working with tools, not a real rejection followed by escalation. The narration says escalation happens "when Super's attempt is rejected", which is accurate, but don't present the clip as a real rejection.

## Tips

- Scene 3 is the most important part. If the live run stalls, cut to a backup recording of the same run made beforehand.
- Keep your cursor still while the timeline scrolls, and use the cursor to point at each card as you mention it.
- Mention "Nebius Token Factory" and "Nemotron" out loud at least twice. The judging criteria explicitly look for both.
