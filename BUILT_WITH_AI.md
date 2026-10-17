# Built with AI

I built this in one session with Claude Code, with Sonnet 5.5 doing the writing and running of code. I told it what I wanted and answered its questions. This note only covers what happened in that session.

## How it went

- **Questions first.** Before any code, the assistant asked me about the seat buffer, how to compare vendors with different pricing models, how to rank by urgency, the repo setup, the status cut-offs, the currency and auto-renew exceptions. I did not understand two of the questions and said so. It asked again with a worked example.
- **My answer changed the design.** The first plan marked down a contract whose notice window had closed, because the money was locked in for now. I said no contract should auto-renew and that these need the strictest watching. So closed windows keep a high weight, there is an auto-renew watchlist, and there is a 13th column for approved exceptions.
- **Verifier tests first.** I asked to see the verifier test fail and then pass. The assistant wrote the five tests against a stub `verify_brief()` that accepted every claim. Four failed and one passed. The passing one was the valid-claim test, which a stub that accepts everything passes by accident. Then it wrote the real verifier and all five passed.

## What went wrong

Nothing serious, but these things happened:

- The first install of the tools ran past the command time limit and moved to the background. It finished fine.
- A `sed` edit failed on macOS because of a quoting problem. The assistant redid it with a small Python script.
- A test file used a relative import and failed to collect. It was fixed with a plain import.
- The first rule-based brief had problems that the assistant found by reading its own output. The fiscal quarter-end claim quoted "The fiscal year ends in June." instead of the quarter-end date. One line read "tool(s)". The assumption text showed costs without a dollar sign. One ask stated our policy with no evidence behind it. All four were fixed, and a test now runs the template brief for all 25 vendors through the verifier.
- Ruff flagged a few long lines. They were fixed.
- The summary total in the report adds savings per vendor. I noticed that savings in the same category can overlap, so I added a line saying the total is a rough upper sketch.

## What I have not checked

- I only ran the tests on Python 3.14, which is what was on this machine. CI is set up for 3.11 and 3.13, but it has not run, because nothing has been pushed.
- The live provider was tested only with fake HTTP clients. It has never touched the real network.
- The model step was tested only with a fake client. It has never called the real API.
- The invented vendor names were picked to sound made up. I did not search to confirm that none of them is a real product. Any match is a coincidence.

## Before you rely on it

Read the sample outputs in `examples/` yourself. The assistant wrote the design and the code from my answers. The design calls above came from me. Nobody has yet read every line of the generated briefs except the assistant that wrote them.
