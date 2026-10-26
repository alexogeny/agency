---
name: interface-design
description: Create or change application, website, desktop, mobile, or terminal interfaces with task-appropriate layouts, working controls, and concise declarative copy. Apply whenever producing or revising UI, including small changes inside another workflow.
---

# Design the interface for its task

Apply these rules to every UI surface, including components, forms, empty
states, loading states, settings, dashboards, and generated prototypes. They
apply during implementation, not just a final copy pass. Respect the user's
explicit design, content, and stack requirements and the product's established
conventions.

## Make copy serve an action

Use professional, declarative interface language: names for destinations and
objects, verbs for actions, precise labels for controls, and concise state when
it matters. Show a useful count or status directly. Do not turn it into a
sentence about the user's relationship with the product.

Omit slogans, atmospheric taglines, motivational phrases, feature summaries,
and paragraphs explaining the app's premise. Avoid redundant subtitles,
repeated privacy reassurances, and commentary about how simple, personal,
thoughtful, quiet, or easy the experience is. Do not use filler to occupy space
or make a screen look finished. An ordinary page may need only its title,
controls, and content.

Include help when it changes the user's next action: a prerequisite, an
ambiguous choice, a meaningful consequence, a constraint, an error, or a
recovery step. State the concrete requirement or action directly. Keep optional
implementation detail in help or diagnostics.

If the user asks to remove a dial, setting, or other control, remove it and
its obsolete labels and help. Leave the space out. Do not replace the control
with prose about what it used to do, why it is gone, the absence of settings,
or the automatic/default behaviour that replaced it. Do not narrate the edit
inside the product. Implement any remaining requested controls as interactions.

Keep substantive content intact: an article's introduction, a product's actual
description, required legal text, an accessibility label, or a necessary warning
is not decorative interface copy. The test is whether the text supplies content
or information the user needs to act, rather than describing the interface to
them.

### Copy examples: do and don't

The Do column describes the intended interface; explanatory notes in that
column are instructions to the agent, not copy to render. Use actual product
state and content. When no supporting text is needed, render none; do not print
"No subtitle" or another placeholder. These examples illustrate decisions,
not phrases or features to repeat in every product.

| Situation | Do | Don't |
| --- | --- | --- |
| Video collection heading | `Videos`, followed by the collection and its controls. No subtitle. | "The videos you follow, collected in one quiet corner." |
| Useful collection counts | `8 videos · 3 channels`, if those counts help the current task; otherwise omit them. | "8 videos collected from 3 channels. Play them here, or bring your collection to the television." or "8 videos ready when you are." |
| Journal heading | `Journal`, followed by entries and the requested controls. | Add "Private. Only you can read these." or "Your dated entries across every book" beneath the heading. |
| Empty library | `No books yet` with an `Add book` action when the user can add one. | "Your next great read starts here. Build a library that's uniquely yours." |
| Destination selection | `Destination` and, when needed, "Choose an existing mounted SMB share." | "A home for your finished files, wherever inspiration takes you." |
| Unavailable destination | "NAS folder unavailable. Mount the folder to continue." when mounting is the required next action. | "We're keeping your files safe until your destination is ready." |
| Verified job progress | `Converting 3 of 8` and a progress indicator backed by the job's actual state. | "Making your videos smaller, without losing what matters." |
| Clear action | `Save draft`, `Publish`, or `Retry`, according to the action performed. | "Make it yours", "Bring it to life", or "Let's try that magic again" on those actions. |

### Removed control: leave it removed

Request: "Remove the quality dial."

- **Do:** delete the dial, its label, its helper text, and any wrapper left empty
  by the removal. Keep the remaining requested interface, such as a destination
  selector and `Convert` button. Add no replacement text.
- **Don't:** replace it with "Smaller files, with the picture preserved", "There
  are no encoding settings to choose", "We choose the best settings for you",
  a card explaining automatic quality, or a disabled version of the dial.

The same applies to any removed setting, panel, badge, or action. Do not add
an announcement or help paragraph to justify the deletion. If the remaining
workflow has a separate prerequisite or error, show that information only
where and when it is needed.

## Choose the structure from the work

Start with the user's objects, content, and frequent actions. Give those actions
the controls they need and make the content easy to scan. Choose lists, tables,
grids, editors, navigation, search, sorting, and filters for the actual workflow.
Do not turn every app into a promotional landing page or a generic dashboard.
Use real content and functional interactions to establish hierarchy; do not
compensate for missing behaviour with explanatory copy or decorative cards.

For a new web interface, default to React, Tailwind CSS, and Radix primitives.
Use an existing stack or the user's explicit choice when provided. Preserve
accessible labels, keyboard interaction, focus, and component semantics. Native
and terminal interfaces should use the appropriate platform tools; the web
default is not a reason to migrate them.

Choose typography, density, layout, and colour for the task, content, audience,
and established brand. A neutral starting palette is reasonable without a
brand; accents need a purpose. There is no prescribed pink, purple, or plum
accent, universal font, hero treatment, card system, or visual theme. Publishing,
media browsing, administration, and writing have different content and reading
needs. Treat reference examples as evidence about the task, not templates to
repeat across unrelated products.

### Layout examples: do and don't

Choose controls from the requested workflow. These comparisons are not
instructions to add all listed features or impose these layouts on other tasks.

| Task | Do | Don't |
| --- | --- | --- |
| Browse a bookshelf | Give covers, titles, and authors the main space. Put requested search, sort, and genre filters beside the collection and make them work. | Lead with a slogan, a large welcome panel, decorative statistics, and a paragraph explaining that this is a personal library. |
| Edit CMS content | Give the writing surface the main space, with clear title, draft/publish, and media controls. Use a restrained palette and compact navigation appropriate to the existing product. | Put promotional cards and feature explanations above the editor, or use prose to stand in for editing and media controls. |
| Read a news or press site | Use an editorial hierarchy: headlines, publication dates, real article leads, and links to dedicated articles. Choose typography for reading the actual material. | Reuse an app dashboard or generic marketing hero with invented mission copy and identical feature cards. |
| Choose colour and emphasis | Use the established brand, or choose accessible neutral surfaces and purposeful emphasis for the task. | Apply the same plum accent, gradient, rounded cards, and hero composition to every interface because they are a default recipe. |

## Check the actual result

Inspect the rendered interface and its relevant interactions. Read each visible
line in context: retain labels, needed state, substantive content, and actionable
help; remove the rest. Check removed controls for leftover labels, placeholder
panels, and replacement explanations. Ensure the requested actions still work
and the content, controls, and empty/error states have sensible hierarchy.
