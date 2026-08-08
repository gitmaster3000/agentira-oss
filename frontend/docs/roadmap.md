# Planning your work: roadmap, milestones and dependencies

This is the user guide for the planning features. No git or project-management
jargon needed — if you can describe your plan out loud, you can put it in here.

## The three roadmap views

Open a project and go to **Roadmap**. The buttons at the top switch between three
planning questions: when work happens, what it depends on, and which milestones
it serves.

### Schedule
The default. **Timeline**, **Month**, **Week**, **Day** and **Agenda** are modes
of the same schedule, so you can change the level of date detail without
switching to a different roadmap view.

The date-range picker belongs to the whole Schedule view. Your selection stays
put when you change modes: it becomes the Timeline's visible window and is
highlighted in the calendar. Calendar previous / next / today navigation moves
that same range instead of resetting to a hidden default.

Timeline shows one coloured bar per epic (or per tag), stretched across the
dates its tasks are scheduled for. A red line marks today, and small flags mark
your milestones. Underneath: every epic with its tasks, plus your milestones and
a "recently shipped" list.

If nothing has dates yet you'll see *"no scheduled work yet"* — set a start or due
date on a task and it appears.

Month, Week, Day and Agenda show tasks on the days they're scheduled for;
milestones appear as flagged all-day entries. Click any task to open it. Use the
range picker to focus every mode on a specific planning window.

Tasks with no dates aren't shown — the count of them is printed under the
calendar, so you can see what's still unscheduled instead of it quietly missing.

### Dependencies
A chart of your dependencies, read left to right: everything on the left has to
finish before the things it points to can start. Each arrow reads
**blocker → dependent task**.

- Red arrow = the earlier task isn't done, so the later one is still waiting.
- Green arrow = that link is satisfied.
- A red outline on a task means something it needs isn't finished.

Click a task to open its full page. Click an arrow to remove that link.

If the chart is empty, nothing has been linked yet — see "Saying one task waits on
another" below.

### Milestones
Your list of dated things you're aiming at: a launch, a demo, a client deadline.
Add one with **+ Add**, give it a name and a date.

Each milestone shows a progress bar. That number is **not** typed in by anyone —
it's the share of tasks linked to the milestone that are actually done, so it can't
be talked up. A milestone whose date has passed with work outstanding shows its
date in red.

You can mark a milestone **Planned**, **Hit** or **Missed** — that's your label
for the record; it doesn't change the progress number.

## On a task page

Open any task and look at the **How this fits in** panel.

The full task page has three tabs: **Plan**, **Run** and **Activity**.

**Plan** is arranged in two wide sections so the same information is easy to
scan without a long sidebar. **Overview & planning** keeps the description,
details, subtasks, dependencies and milestone together. **Collaboration &
delivery** puts the Definition of Done, Branch & PR, attachments and timestamps
in one compact row, with comments underneath — so the page only gets long when
the discussion does, never from the facts themselves.

**Run** holds everything about the agent working on the task: which agent is
assigned, how to start it, and the latest run's state and summary. **Activity**
keeps the complete read-only event history available without mixing it into the
working view.

### Breaking a task into subtasks
Under **Subtasks**, press **+** and pick an existing task in the project. It
becomes a subtask of the one you're looking at, and the parent shows a `2/5`-style
count as the children get done.

Deleting a parent task does **not** delete its subtasks — they just stop being
nested. Work never disappears because you reorganised.

Under **Part of**, you can nest the current task under a bigger one instead.

### Saying one task waits on another
- **Waits on** — things that must finish before this task can start.
- **Blocks** — things that are waiting on this task.

Add either with **+** and pick a task. Anything you add shows up in the
**Dependencies** chart, and a task that's waiting gets a *waiting* badge on the
roadmap.

You can't create a loop (A waits on B waits on A) — if you try, the panel tells
you instead of saving something impossible. Same for making a task its own
parent, or linking to a task in another project.

### Counting a task towards a milestone
Under **Counts towards**, pick a milestone. That's what feeds the milestone's
progress bar.

## Advanced / technical

<details>
<summary>What this is under the hood</summary>

- Subtasks are a `parent_id` pointer on the task; dependencies are rows in a
  `task_dependencies` table; milestones are rows in a `milestones` table with a
  `milestone_id` pointer on each task.
- The dependency graph is kept acyclic at write time — the API rejects any edge
  that would close a loop, which is what makes the left-to-right layout possible.
- "Blocked" and milestone progress are computed on read from real task statuses,
  never stored, so they can't drift from the board.
- Backend contract: `docs/task-graph.md` in the main repo.

</details>
