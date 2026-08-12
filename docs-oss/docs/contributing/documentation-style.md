---
id: documentation-style
title: Documentation style guide
sidebar_label: Documentation style
---

# Documentation style guide

This is the abridged ruleset for Agentira's documentation. It follows established technical-writing practice — the Google developer documentation style guide, and the controlled-language principles behind Simplified Technical English — reduced to what this project actually needs.

Apply it to everything in `docs-oss/`. The [plain-language product rule](./index.md#plain-language-is-a-product-rule) applies to interface text as well.

## The one-line version

Write the shortest accurate sentence that lets the reader act. Prefer a verifiable statement over a confident one.

## Structure

**Lead with the task, not the system.** A reader arrives wanting to do something. Give them that first and the background second.

**One topic per page.** If a page needs two unrelated headings at the top level, it is two pages.

**Task-oriented headings.** Use "Connect the daemon", not "Daemon connection overview". Headings are scanned, not read.

**Front-load the paragraph.** Put the conclusion in the first sentence. Readers stop early.

**Use a table when comparing.** Three or more items with the same attributes belong in a table, not in prose.

## Sentences

**One instruction per step.** A numbered step containing "and then" should be two steps.

**Active voice, present tense.** "The daemon starts the runtime", not "the runtime is started by the daemon" or "the daemon will start the runtime".

**Second person for instructions.** "Set `FRONTEND_URL`", not "the user should set" or "we set".

**Short sentences.** Aim under 25 words. Split rather than adding a subordinate clause.

**No ambiguous pronouns.** "This is the common mistake" — what is? Repeat the noun: "Omitting `FRONTEND_URL` is the common mistake."

**One term per concept.** A run is a run everywhere. Not "job", "execution", or "episode". Synonyms read as new concepts.

## Words to avoid

| Avoid | Use | Why |
|---|---|---|
| simply, just, easy, obviously | (delete) | If it were obvious the reader would not be reading |
| please | (delete) | Instructions do not need politeness padding |
| should be able to | does, or name the condition | Hedging hides whether it was tested |
| leverage, utilise | use | |
| in order to | to | |
| a number of | the number, or several | |
| powerful, seamless, robust | (delete or substantiate) | Marketing words carry no information |

Delete "note that", "it is important to", and "as mentioned above". If it is important, the sentence already carries it.

## Accuracy

**Document what the code does, not what it should do.** If the implementation is incomplete, say so in the sentence where a reader would otherwise assume otherwise.

**Mark known gaps explicitly.** Use an admonition. Sandbox modes being unenforced is documented at the top of both sandbox pages, because a reader who misses it draws a dangerous conclusion.

**Never invent an example you have not run.** A command that does not work costs more trust than a missing example.

**Prefer the source over another document.** Documents go stale. Before documenting a tool list or a configuration variable, check the code.

## Formatting

**Code voice for anything typed or named:** commands, variables, paths, field names, tool names, outcome values.

**Fenced blocks with a language tag** for anything longer than a fragment. The language enables highlighting.

**One command per block.** No leading `$`, no interleaved output.

**Admonitions carry weight, so use them sparingly.** `:::note` for a caveat, `:::warning` for something that will cost the reader time, `:::danger` for something that will cost them safety. A page where everything is highlighted highlights nothing.

**Link on the noun**, not on "here" or "this page".

## Reference material

For a tool, endpoint, or variable reference, give every entry the same shape: name, purpose, and constraints, in the same order. Consistency matters more than prose quality — these pages are scanned for one row.

## Before you submit

- [ ] A newcomer can complete the task using only this page and its links
- [ ] Every command was run, and the output matches what is shown
- [ ] Every claim about behaviour matches current code
- [ ] Known gaps and limitations are stated, not omitted
- [ ] No banned words survived
- [ ] Headings describe tasks
- [ ] Links point at the specific page, not the section index
- [ ] `npm run build` passes in `docs-oss/`, with no broken links

## Keeping documentation current

A behaviour change without a documentation update is half-shipped. Update the affected page in the same pull request that changes the behaviour.

This is a review criterion, not a courtesy.
