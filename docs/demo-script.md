# AutoFixAI demo video script

Length: 2:53, under the 3-minute limit. The timings below match the current video. The demo runs are recorded live on the Nebius Serverless Endpoint, and every number in the narration comes from real runs.

## Before you record

- Open the live site and run one demo so the endpoint is warm.
- Set the browser zoom to 110% and hide your bookmarks bar.
- Pre-record the terminal clip for scene 6 (see [below](#scene-6-terminal-clip)), so you don't wait on it live.
- **Never show `.env` on screen.** It contains your API keys.
- Run times vary with Token Factory latency. If a live run is slow, cut ahead while the agent works rather than waiting on screen.

---

## 1 · Hook (0:00 – 0:17)

**On screen:** a CI run with a red ✕ and the real failing pytest output from `examples/inventory-refactor`.

> "A red CI build stops a whole team. Someone has to dig through the log, reproduce it, find the regression and patch it. That's half an hour, for what's usually a two-line bug. AutoFixAI does that loop for you: red build in, verified pull request out."

## 2 · What it is (0:17 – 0:35)

**On screen:** the dashboard home page. Point at the three Nemotron tier cards, then the **Research** step in the list.

> "It's an agent built on three NVIDIA Nemotron models, all served by Nebius Token Factory. Nano triages failures and writes the PR. Super is the coding agent. Ultra only steps in when Super's fix is rejected. And when a failure points outside the repo, Tavily researches it on the web."

## 3 · Live run (0:35 – 1:16)

**On screen:** click **Inventory refactor** and narrate over the run as it happens. The run takes about 15 s.

> "This is live on Nebius Serverless Endpoints. This repo has a half-finished refactor: a field was renamed, and a pricing function's arguments were reordered, but the service layer was never updated."

*(Baseline FAIL appears.)*

> "First it reproduces the failure in an isolated copy of the repo, so the agent never touches the original."

*(The Triage card appears.)*

> "Nano classifies the failure in about a second and names the files it suspects."

*(Tool calls scroll by: read_file, edit, run_tests.)*

> "Now Super works in a tool-calling loop. It reads the code, searches, makes exact edits and reruns the tests."

*(The Verify step goes green.)*

> "When the agent says it's done, AutoFixAI doesn't take its word for it. It reruns the test suite itself. Green."

## 4 · The result (1:16 – 1:31)

**On screen:** scroll through the verified patch, then the PR write-up.

> "Here's the patch: two lines, both bugs. The second one is subtle, because swapped arguments only produce wrong prices on bulk orders. And here's the pull request Nano wrote, with the root cause, the fix and how it was verified."

## 5 · Web research with Tavily (1:31 – 2:01)

**On screen:** back on the home page, point at **Python upgrade** and click it. When the **Web research** card appears, scroll to it and point at the query and the first source.

> "Some failures aren't in the code's logic at all. This release tooling broke when Python 3.12 removed two standard library APIs. Triage spots that the fix depends on facts outside the repo, so Tavily searches the web."

*(The Web research card: Tavily's answer and its source links. Then cut ahead to the verified patch.)*

> "Tavily's answer and its sources go to the coding agent as background. Super swaps in the modern APIs, and the tests pass."

*(Scroll the PR card to its **References** section.)*

> "And the pull request cites every source Tavily retrieved, so a reviewer can check the reasoning instead of trusting it."

## 6 · Model routing and escalation (2:01 – 2:23)

**On screen:** scroll to the top of the same run and point at each row of the **Model routing** panel: Nano, Super, Tavily, Ultra. Then cut to the pre-recorded terminal clip.

> "This panel shows where the work went: Nano for the cheap structured calls, Super for the real work, one Tavily search, and Ultra idle until it's needed."

*(The terminal clip, at real speed.)*

> "When Super's attempt is rejected, Nano writes up what went wrong, the workspace is reset, and Ultra takes over. Here it is fixing the rate limiter in ten seconds."

## 7 · Guardrails and real CI (2:23 – 2:39)

**On screen:** the README's *Guardrails* section on GitHub, then [`examples/github-action/autofix.yml`](../examples/github-action/autofix.yml).

> "The agent can't touch anything outside its sandbox, can't run arbitrary commands, and can't make CI pass by editing the tests. Those edits are blocked."

> "Drop this GitHub Action into any repo, and every failed build gets a fix PR."

## 8 · Close (2:39 – 2:53)

**On screen:** the GitHub repo page, then the end card with the repo link.

> "AutoFixAI: NVIDIA Nemotron on Nebius Token Factory, with Tavily web research, deployed on Nebius Serverless. The code is open source under MIT, and the link's below."

---

## Scene 6 terminal clip

Record these from the project root:

```bash
cd backend
AUTOFIX_ESCALATE_AFTER=0 python -m autofix fix ../examples/rate-limiter
```

In PowerShell, set the variable first with `$env:AUTOFIX_ESCALATE_AFTER=0`, then run `python -m autofix fix ../examples/rate-limiter` on its own.

That setting sends the first attempt straight to Ultra. The clip shows Ultra working with tools, not a real rejection followed by escalation. The narration says escalation happens "when Super's attempt is rejected", which is accurate, but don't present the clip as a real rejection. If the clip is labelled "real time", play it at true speed.

## Editing notes

- **Scene 3** is the most important part. If the live run stalls, cut to a backup recording of the same run made beforehand.
- **Scene 5** skips ahead while Super works on the fix, so don't state a run time for it. A fix with research typically takes 30 s or more.
- Speeding up scrolling and UI footage slightly to fit the narration is fine. Never speed up footage that's labelled as real time.
- Keep your cursor still while the timeline scrolls, and use the cursor to point at each card as you mention it.
- Mention "Nebius Token Factory", "Nemotron" and "Tavily" out loud. The judging criteria look for the first two, and the Tavily prize looks for the third.
