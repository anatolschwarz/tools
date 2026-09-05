I want you to set up a /handover slash command (or skill, or saved prompt, whichever fits how I use Claude) that I'll run at the end of every working session.

When triggered, it should:

1. Survey what actually happened this session: run git status, git log since the session started, check for uncommitted changes, look at any tasks I marked done vs. in-flight.

2. Identify what's load-bearing for the next session: decisions made, constraints discovered, things half-finished, footguns I hit. Ignore pure execution noise.

3. If I keep persistent memory or notes files, update only the entries that future-me will need. Don't log the daily activity.

4. If there are uncommitted changes worth committing, ask before doing it.

5. Print a structured handover note at the end with four sections:

   - What shipped this session (commits, deploys)
   - What's still in flight (with enough context for a cold reader)
   - Watch-outs (gotchas, surprising state, broken assumptions)
   - Open questions for me

The whole point is to filter aggressively. Most of a session is forgettable execution; the 5% worth carrying forward is what I want to preserve. The handover should be short enough that the next session reads it in under 30 seconds.

As a rule of thumb, report session state from verifiable evidence: repository state, tool output, task state, or conversation history. Do not invent missing state. If you need to infer something that is not directly verified, label it clearly as an inference.

Before you create anything, ask me where to install the file, what trigger word I want, and whether I have an existing memory/notes setup you should integrate with.
