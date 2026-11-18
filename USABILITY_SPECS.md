# Exercise 4: Usability specs (Admit Pal, Group 15)

## 1. Context
Product: an AI admissions assistant that estimates a first-time MBA applicant's chance of an interview invite at each school and builds a balanced Dream / Target / Likely list.
User: a first-time, often international or first-generation applicant with no consultant and no prior on which schools fit.

## 2. Scenario 1 (specification: intent, storyboard frames 4 and 5)
- Trigger: the user taps Check my fit with 2+ schools and no Likely school, or with only Dream schools.
- What can go wrong: with no prior, the user picks famous names and builds a list that ends the cycle with no offer, even though every estimate is right.
- Design intervention: suggestions show each school's fit and the gap to its median; a list check opens before results.
- What the user sees: a mix bar (for example 5 Dream, 0 Target, 0 Likely), one line on the risk, three pre-ticked better-matched schools with tier and median gap.
- What the user can do: add them, untick any, keep the list as it is, or go back and edit.
- What to log: list check triggered (kind, counts, suggestions) and outcome (accepted, overridden or edit, number added).

## 3. Scenario 2 (verification, storyboard frames 7 and 8)
- Trigger: the AI scores a school where fewer than 40 past applicants resemble the user (thin data, for example international plus nonprofit).
- What can go wrong: over-reliance; the user counts a confident-looking Likely as a safety school and loses a cycle.
- Design intervention: show a range, a Low confidence badge, cap the tier at Target, explain "Why this number" with drivers and the evidence count, and require a check before relying on it.
- What the user sees: "~69%, could be anywhere from 53% to 85%", "Held at Target", "Only 35 past applicants with profiles like yours".
- What the user can do: confirm their details, then count it as a Target or ask an expert to review; or edit their details.
- What to log: low confidence flag per school (chance, range, support, capped), verification check shown, and outcome (target, review or edit).

## 4. Simulated responses
Both cases live in `simulated_responses.json` under `scenarios` (copy, thresholds, multipliers and Test mode presets). Per-school `support` counts drive Scenario 2.

## 5. How to trigger each case
Open the prototype and use **Test mode** in the log panel (on phones, tap Log):
- Scenario 1: loads Priya with five Dream schools selected; tap Check my fit.
- Scenario 2: loads Ananya's thin-data profile and list; tap the orange banner or any Low confidence school.
The happy path is unchanged: Get started, answer four questions, Check my fit, pick a balanced set, open a school.

## Addendum: outcome nudge (data loop)
- Trigger: the user has a school list and some schools have no result logged.
- What the user sees: "Heard back from a school?" with progress (for example 1 of 7 updated) on Home, My list and each school page.
- What the user gets back: a result below the estimate lowers their estimates and suggests safer Round 2 schools; a result above it raises them and suggests aiming higher.
- What to log: Outcome reported (training label) with the predicted chance, tier and support; Personal recalibration; Shared to live trackers.
- Test mode: Scenario 3, results season.
