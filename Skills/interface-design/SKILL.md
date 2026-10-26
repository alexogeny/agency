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
recovery step. State the concrete requirement or action directly. For example,
"Choose an existing mounted SMB share" is useful configuration guidance.
"Mount the NAS folder first. Finished copies will transfer when it is
available" gives a prerequisite and relevant state. These are examples of
purpose, not required wording or a reason to add helper text to every field.
Keep optional implementation detail in help or diagnostics.

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

## Check the actual result

Inspect the rendered interface and its relevant interactions. Read each visible
line in context: retain labels, needed state, substantive content, and actionable
help; remove the rest. Check removed controls for leftover labels, placeholder
panels, and replacement explanations. Ensure the requested actions still work
and the content, controls, and empty/error states have sensible hierarchy.
