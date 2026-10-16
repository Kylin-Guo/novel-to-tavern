Agent Review Report — Novel-to-Tavern
- Review date: 2026-10-17
- Repository: https://github.com/Kylin-Guo/novel-to-tavern
- Review scope: public repository README, architecture/data-model/format compatibility docs, implementation plan, run report, Tavo checklist, third-party notices, and visible generated export.
- Review method: static review of the public GitHub snapshot. A local git clone could not be completed in this environment because outbound DNS/network access to GitHub was unavailable. I did not execute the repository's test suite. Treat implementation-level findings below as documentation/code-view findings, not a locally reproduced test result.
Executive summary
This repository has a strong and unusually disciplined foundation for a personal tool that converts a novel into a SillyTavern/Tavo multi-character world-simulator card. The staged pipeline, evidence-backed facts, deterministic source-location calculation, conservative entity resolution, non-destructive run directories, provider abstraction, serializer boundary, and explicit format-compatibility research are all good decisions. The current architecture is much better than a single mega-prompt that tries to summarize a novel and directly emit final JSON.
However, there are important gaps between the project's stated promise and what is actually demonstrated. The most important are:
1. The README overstates spoiler prevention. The full plot is present in a triggerable lorebook entry, and the known-limitations section admits that spoiler control relies on prompt-level time discipline. A model prompt is not a hard information-access boundary.
2. The evidence metric is easy to misread. A 100% exact quote-location rate proves that quotes can be found in the source, not that the extracted claims are semantically entailed, complete, or correctly attributed. Zero manual-review items across a large novel should not be treated as proof of correctness.
3. Tavo validation status is inconsistent across documents. README/RUN_REPORT describe successful import, while docs/TAVO_IMPORT_CHECKLIST.md says the checklist has not been executed and still contains a different fixture filename and four-entry expectations. Reconcile the record and distinguish import success from runtime lorebook-trigger success.
4. The checked-in example export needs an explicit rights and repository-hygiene decision. The repository exposes exports/天之炽/world_simulator_v2.json, while the run report says the generated derivative was not committed. The public repo should not contain a novel-derived card unless the maintainer has the relevant rights/permission and intends to publish it. Prefer an original/public-domain fixture.
5. Knowledge-boundary inference is too weak for a “no future leaks” promise. present_at_event and subject_of_fact are useful hints, but being present at an event does not prove a character perceived every fact, and many characters learn things later via dialogue, documents, rumors, surveillance, or inference.
6. The “start at any chapter” promise needs a stronger, explicit mode contract. A card containing the whole plot can still leak future information even if timeline data marks validity. Clarify the exact guarantees of each mode and test prompt-context behavior, not only JSON structure.
7. The extraction quality process needs semantic evaluation and calibrated review. Schema validity and quote lookup are necessary but insufficient. Add precision-oriented tests, required review thresholds, and an evaluation report.
Recommendation: keep the current project and its lightweight CLI architecture. Do not replace it with a larger application. Focus next on truth-in-advertising, Tavo runtime validation, spoiler-mode semantics, semantic quality evaluation, and sample-artifact hygiene before adding new input formats or features.
What is already good and should be preserved
1. Clear scope
The repository explicitly avoids becoming a new chat client, web app, database/vector-store platform, or card-decoration framework. That matches the product goal: produce files to import into an existing Tavern/Tavo client. Keep this constraint.
2. Staged, restartable pipeline
The five stages (ingest, extract, resolve, timeline, export) are a sound decomposition. Independent stages, per-run outputs, checkpoints/caching, and default non-overwrite behavior make long-running API jobs safer and easier to debug.
3. Evidence is represented as data, not prose-only citations
Requiring model-produced short quotes and having code locate the quote in the original text is a strong foundation. Do not accept model-invented line numbers. Keep source offsets/chapter IDs stable and preserve the original text read-only.
4. Internal schema is separate from Tavern output schema
The data model correctly distinguishes canonical facts, beliefs, rumors, inferences, user-added material, reconstructed material, contradictions, and unknowns. The serializer boundary is important because internal provenance fields should not leak into SillyTavern's output format.
5. Conservative entity resolution
Do not merge entities based only on fuzzy name similarity. Preserve ambiguous candidates for review and make merges traceable/undoable. This is especially important for aliases, titles, same-name characters, translations, and identity reveals.
6. Format compatibility work
The field-level research into Character Card V2 and world-info behavior is valuable. Keep version anchors, references to source code, and explicit caveats for unknown Tavo behavior. Do not treat valid JSON as proof of client behavior.
7. Operational safety
Environment-variable credentials, redacted logs, no hard-coded provider, provider metadata, secret scanning, run isolation, and no-overwrite defaults are good choices. Preserve these in future refactors.
8. Testability without paid API calls
The file provider and offline fixtures are valuable for testing the whole pipeline without consuming API credits. Keep deterministic tests for parsing, validation, source mapping, and export independent of live model output.
Findings and recommendations
Priority definitions:
- P0: fix before claiming the feature is reliable or publishing a release.
- P1: high-value correctness/quality improvement for the next iteration.
- P2: useful improvement after core correctness is established.
P0-1 — Reconcile Tavo import/test status and docs
Evidence: README says the generated card was imported into Tavo and the embedded worldbook was recognized. docs/RUN_REPORT.md says import succeeded but trigger hits, constant-entry behavior, spoiler discipline, and actual token usage remain unverified. docs/TAVO_IMPORT_CHECKLIST.md still says the checklist has not been executed, uses minimal_world_simulator_v2.json in one step while other documents say world_simulator_v2.json, and includes a four-entry fixture expectation while the run report describes 180 entries (and another checklist note refers to 664 entries).
Action:
- Establish a single source of truth for validation status.
- Record exactly which file/version was imported, on which Tavo version/build, and which behaviors were observed.
- Separate validation levels:
  1. JSON parses;
  2. card imports;
  3. embedded lorebook is imported/enabled;
  4. constant entries are injected;
  5. keyword triggers work;
  6. aliases trigger;
  7. irrelevant messages do not over-trigger;
  8. starting-point spoiler behavior is correct;
  9. context/token size is acceptable.
- Keep the four-entry sample as a tiny compatibility fixture, but label it explicitly as a fixture. Do not mix fixture expectations with full novel output counts.
- Ensure the checklist's filename matches the actual artifact.
- Do not mark a test complete unless there is a recorded result. Screenshots are optional; exact observations are required.
Acceptance: README, RUN_REPORT, and TAVO_IMPORT_CHECKLIST agree and distinguish “imported successfully” from “runtime behavior verified”.
P0-2 — Make spoiler guarantees truthful and strengthen the model
Evidence: README says the tool produces files so users can start at any chapter “without later plot/secrets leaking”. The run report says the complete chapter-by-chapter plot is inside a triggerable lorebook entry and spoiler prevention depends on the core prompt's time discipline. The README's known limitations also acknowledge this.
Problem: If the entire plot is present in the same model-visible card/worldbook, prompt instructions are not an access-control boundary. A model may retrieve or reveal later plot details when the entry triggers, when the user asks about the plot, or when it treats the text as relevant. valid_from_chapter in internal data does not itself guarantee that the serialized Tavern client filters that content at runtime.
Action:
- Define explicit modes:
  - canon_full: full-source reference available; not guaranteed spoiler-free.
  - start_at_chapter_N: export only the facts/entries valid and knowable at N, or use a tested runtime-safe filtering mechanism.
  - after_ending: full canon available after the original ending.
  - branch/freeform: original canon used as reference, but branch events are clearly marked as new.
- Prefer generating a start-point-specific card/worldbook artifact for strict no-spoiler play. Do not rely only on an instruction to “ignore future chapters”.
- If retaining one full card with a chapter selector, label it as best-effort spoiler discipline, not a guarantee, unless Tavo's actual prompt assembly proves future data is absent.
- Make sure chapter-by-chapter plot summaries do not enter active context for an earlier start unless the specific summaries are filtered.
- Add adversarial tests: start at chapter 1 and ask about the final villain, secret identity, ending, and late character death; inspect actual injected context where possible.
Acceptance: Product copy describes guarantees accurately. A strict spoiler-free mode passes tests showing future facts are not present in the model-visible context, not merely tests of internal JSON metadata.
P0-3 — Review checked-in novel-derived export and repository hygiene
Evidence: The public repository contains exports/天之炽/world_simulator_v2.json; the README links to it as an example, while docs/RUN_REPORT.md says the generated derivative was not submitted to the repository. The repository also states that exported cards may be derivative works and are not covered by the code's MIT license.
Action:
- Decide whether the checked-in export is authorized for public redistribution.
- If there is no clear permission, remove it from the current tree and replace it with a fully original fixture or a public-domain work whose status is verified for the relevant jurisdiction.
- Check whether other novel-derived files are tracked, including worldbooks, timeline, run reports, quotes, prompts, and generated artifacts.
- If the export was committed in prior history, remember that deleting it in a later commit does not remove it from Git history; decide whether history cleanup is needed before broader distribution.
- Ensure actual input novels, quoted evidence, raw LLM responses, and run outputs remain ignored by Git unless explicitly authorized.
- Avoid using a copyrighted work as a downloadable public demo even if the source novel itself is not committed.
Acceptance: Public examples are original/authorized; README and run report accurately describe what is in Git.
P1-1 — Treat exact quote matching as source-location validation, not semantic proof
Evidence: The run report highlights 5,746/5,746 quotes located (100%) and zero manual-review items. The method validates quote presence and maps it to source offsets/lines.
Problem: A quote can exist while failing to support the generated claim. A valid quote might be assigned to the wrong character, interpreted incorrectly, omit a negation, describe a belief rather than objective truth, or support only part of a compound fact. Quote-location success is not extraction precision or recall.
Action:
- Rename the metric to quote_location_success_rate or similarly precise wording.
- Report separate metrics:
  - quote-location success;
  - schema-valid extraction rate;
  - semantic entailment pass rate;
  - entity attribution accuracy;
  - contradiction/temporal consistency rate;
  - entity merge precision;
  - manual-review count and review resolution rate.
- Add a semantic support check that receives the source quote plus claim and classifies entailed, partially_supported, contradicted, or insufficient_evidence. It must not replace source-location validation.
- Require manual review for high-impact facts (identity, death, secret, relationship status, power/ability limits, timeline pivots), even if the quote is locatable.
- Do not interpret “0 needs_review” as inherently good; if every model output is confidently accepted, the review policy may be too permissive.
- Sample accepted facts per chapter and report sample size, method, and error rate. If possible, use a small hand-labeled gold fixture to estimate precision/recall.
Acceptance: The report clearly separates traceability from semantic correctness and no longer implies 100% quote location means 100% fact accuracy.
P1-2 — Improve knowledge-boundary modeling
Evidence: Current plan describes knowledge sources primarily as present_at_event and subject_of_fact.
Problem: Attendance does not imply awareness. A character may be present but unable to see/hear a secret; a fact's subject does not necessarily know the fact; conversely, characters may learn facts through letters, reports, rumors, witnesses, inference, or later conversations.
Action:
- Represent knowledge as a separate record, e.g.:
  - character_id
  - fact_id
  - knowledge_status: knows, suspects, believes, heard_rumor, does_not_know, unknown
  - acquired_at_chapter
  - acquisition_method: witnessed, told_by, read_document, rumor, inferred, author_explicit
  - source_refs
  - confidence
- present_at_event should create a candidate for knowledge, not accepted knowledge by default.
- Keep reader revelation time distinct from in-world acquisition time.
- Track secret disclosure separately from the event where the secret originally existed.
- When the source does not establish whether a character knows something, leave it unknown instead of silently assigning knowledge.
- Distinguish the source's omniscient narration from information available to each character.
Acceptance: Tests cover an unseen event, a secret conversation, a written letter, a rumor, a false belief, and a later revelation.
P1-3 — Define what “start at any chapter” means in the exported artifact
Evidence: The plan offers a user-selectable beginning/end start and permits “start at chapter N”, while also producing beginning/after-ending worldbook variants. The current world simulator card includes the full plotline entry.
Action:
- Decide whether arbitrary chapter N is a runtime option or an export-time option.
- If export-time, expose --start-chapter N and generate a filtered artifact set.
- If runtime, document exactly how the start chapter is passed and prove that all chapter-sensitive entries are filtered before prompt assembly. Standard static Tavern card JSON alone may not enforce per-chat dynamic filtering.
- Generate a start_state.json or equivalent manifest that states current chapter, facts active, facts hidden, characters' knowledge, and relevant relationship states.
- Add a report listing how many facts/entries were included and excluded at the chosen start point.
- Clarify what “chapter before chapter 1” and “after the final chapter” mean, including whether the protagonist is alive, which relationships have resolved, and whether branch events begin as new content.
Acceptance: A user can select a chapter and the exported active data matches that chapter; tests verify no future plot entry is injected.
P1-4 — Evaluate worldbook design for trigger reliability and context budget
Evidence: The plan generates an entry for every entity and uses name/alias/title triggers; token estimates are rough (CJK ~1 char per token); three entries are always on.
Risks:
- A large number of entries can still make the card unwieldy.
- Very common aliases or generic terms can cause false-positive triggers.
- Full names, aliases, titles, homonyms, and generic words have different trigger precision.
- A 1-character-to-1-token CJK estimate can be inaccurate depending on tokenizer/model.
- A 25k-character plot entry can be difficult to retrieve consistently and may be too broad a trigger.
Action:
- Report entry count by category, total character count, rough token estimate, and worst-case always-on budget.
- Add trigger test fixtures for full name, alias, title, homonym, substring, unrelated chat, and character name mentioned in a negation/quotation.
- Avoid adding overly generic keys without review; support explicit trigger allow/deny notes.
- Split long plot summaries into chapter/arc entries with narrow triggers or prefer start-point-specific artifacts.
- Keep a conservative budget for constant entries and make it configurable.
- If feasible, add tokenizer-based counts as an optional feature keyed to a configured model; retain the current rough estimate as explicitly approximate.
Acceptance: Audit report includes trigger precision test results and a budget estimate with its methodology clearly stated.
P1-5 — Add an end-to-end evaluation set that measures usefulness, not only structure
Evidence: The repository advertises 289 offline tests and schema/serialization checks. Those are valuable but cannot alone establish that the generated world is good to roleplay.
Action:
- Add a small original, self-authored novel fixture with:
  - multiple characters and aliases;
  - same-name/different-person cases;
  - identity/secret reveal at a later chapter;
  - relationship change;
  - unreliable narrator/rumor;
  - time jump;
  - a character who misses an event;
  - contradictory statements that are later resolved;
  - a fact known to the reader but not a character.
- Add expected facts, relationships, knowledge states, timeline order, and trigger outcomes.
- Track precision and recall for a curated set of facts; a smaller reliable benchmark is better than a large unmeasured run.
- Add “golden export” tests that compare semantic properties, not fragile whole-file byte-for-byte outputs.
- Add regression tests for prompt/schema version changes and cache invalidation.
- Separate deterministic unit tests from live-model acceptance tests. Report which was actually run.
Acceptance: A release report states both code test results and a small measured quality result from the gold fixture.
P1-6 — Improve run provenance and reproducibility
Evidence: The export manifest records source hash, prompt/model metadata, output hashes, and validation results, which is good.
Action:
- Record exact provider/model identifier, API compatibility mode, relevant generation parameters, prompt template hash, schema version, package version, parser version, and start mode.
- Never record secrets or full authorization headers.
- Preserve raw LLM responses locally only when the user explicitly opts in; they may contain copyrighted text or sensitive material.
- Make cache invalidation depend on all semantically relevant inputs, including source normalization version, prompt version, schema version, and model configuration.
- Make reports explicit when results come from file/precomputed responses versus live API calls.
Acceptance: Re-running with the same source, configuration, prompt version, and precomputed responses yields reproducible internal data and a comparable report.
P1-7 — Keep canonical facts, runtime summaries, and branch additions separate
Evidence: The data model already separates content_canonical and content_runtime, and has user_added/reconstructed fact types.
Action:
- Preserve that separation through every stage; do not flatten all data into a single free-form paragraph before export.
- Ensure user-added branch facts never overwrite canon facts.
- Add branch event IDs and links to the canon facts/events they diverge from.
- Make exports indicate whether the selected mode is canon, branch, or freeform.
- For post-ending play, treat new events as branch events and do not rewrite original events.
Acceptance: A user can alter a plot event without corrupting the original canon data, and can export the same canon again later.
P2-1 — Add incremental update support after core quality is proven
Action:
- Detect unchanged chapters by hash and reuse cached extraction.
- If a chapter changes, invalidate that chapter and dependent entity/timeline/worldbook aggregates only.
- Keep a dependency graph or simple stage manifests rather than rebuilding everything.
- Provide a safe resume and explicit clean-run command; never silently delete a previous successful run.
- Add a diff report between runs: new/changed/removed facts, relationships, conflicts, and entries.
P2-2 — Consider separate NPC cards only after the world-simulator card works well
The current priority should remain one multi-character simulator card with embedded worldbook, plus a standalone worldbook and timeline/audit files. Individual NPC card exports can be added later, sharing the same canonical data instead of running separate extraction prompts.
P2-3 — Improve documentation and release discipline
- Add a status badge/table: unit tests, live API tests, Tavo import, Tavo trigger behavior, spoiler test.
- Mark every claim as implemented, automatically tested, manually tested, or planned.
- Avoid calling a behavior “supported” merely because a field exists in JSON.
- Document limitations and exact tested versions near the claim, not only in a distant checklist.
- Include a “known limitations” section in each release.
Specific documentation inconsistencies to fix
1. README claims a Tavo import succeeded; TAVO_IMPORT_CHECKLIST still says no Tavo test has been run. Reconcile.
2. The run report says generated novel-derived output was not committed, but a novel-derived card is visible under exports/天之炽/. Reconcile and review rights.
3. README/run report mention 180 card entries / 179 standalone entries, while checklist text refers to 664 and a four-entry sample. Label full-run output and fixture separately.
4. The checklist refers to minimal_world_simulator_v2.json in one step; other documentation uses world_simulator_v2.json.
5. README says “from any chapter” and “without future plot leaking”, while the implementation notes that the complete plot exists in the card and spoiler control is prompt-level. Weaken the promise or implement strict filtered exports.
6. The run report says no manual-review items, but it also says only sampled checks were performed. Explain the difference between source-location failures and semantic review; do not report zero review as a quality guarantee.
7. Make the Tavo checklist accurately reflect what is confirmed: import success is not equivalent to trigger behavior, constant-entry behavior, token budget, or no-spoiler correctness.
Suggested implementation order
Milestone A — Correct the record (small, immediate)
- Reconcile Tavo status and file names.
- Fix README guarantees and metrics terminology.
- Review/remove unauthorized novel-derived public export or replace it with original fixture.
- Ensure all docs agree on counts and validation status.
Milestone B — Strict start-point exports
- Add an explicit start chapter/mode to export.
- Filter future facts and plot summaries before serialization.
- Include included/excluded counts in the audit report.
- Add adversarial leakage tests.
Milestone C — Semantic quality gates
- Add semantic support checks for extracted facts.
- Introduce review thresholds for high-impact facts.
- Build a small gold fixture and report precision/recall or manually reviewed error rate.
Milestone D — Better knowledge graph
- Replace event-participation-as-knowledge with explicit acquisition records.
- Add rumor, belief, inferred knowledge, document-based knowledge, and uncertain knowledge states.
- Test non-obvious knowledge boundaries.
Milestone E — Tavo runtime acceptance
- Complete the checklist with real observed results.
- Confirm keyword triggers, aliases, constant entries, entry order, and context/token budget.
- Keep results version-specific.
Do not expand to EPUB/PDF, vector search, GUI, or individual-card generation until Milestones A–E are complete.
Repository name recommendation
Current name: novel-to-tavern
This is already a strong functional name: it is understandable, searchable, and describes the conversion direction. The current Python package/CLI branding (novel_to_tavern, n2t) is also consistent enough. Do not rename merely for the sake of renaming. Renaming the GitHub repository later can redirect GitHub URLs, but package names, import paths, documentation links, badges, clone commands, and user scripts still need deliberate updates.
If the maintainer still wants a shorter name, preferred order:
1. Novel2Tavern — clearest compact variant; communicates the same scope.
2. NovelLore — shorter and brandable, but less explicit that the output is Tavern-compatible.
3. LoreWeaver — attractive brand, but generic and less discoverable.
4. Book2Tavern — concise, but may imply all book formats are supported when current input is TXT/Markdown.
Recommendation: keep novel-to-tavern until the CLI and file format stabilize. If you do rename, use Novel2Tavern for the repository/project display name only after checking that no conflicting repository/package exists, while retaining a clear n2t CLI alias and a migration note. Do not rename Python import paths just for branding unless there is a compelling reason.
Instructions for the implementing Agent
1. Read this report and inspect the current code before editing.
2. Do not rewrite the architecture or introduce a web UI/database/vector store.
3. Do not blindly trust the README; verify each finding against the current checkout.
4. Start with Milestone A. Produce a short plan and identify files to edit before changing them.
5. Preserve backward compatibility of output filenames and CLI unless the change is explicitly documented.
6. Add tests with every behavior change.
7. Never delete existing run data or generated outputs without explicit confirmation.
8. Do not add copyrighted novel text or derived card output to public fixtures without authorization.
9. Update README, RUN_REPORT, TAVO_IMPORT_CHECKLIST, and quality documentation together whenever validation status changes.
10. After changes, run the complete offline test suite and report the exact command/result. If network or live API tests are not run, say so.
11. Do not claim Tavo runtime behavior is validated until it has actually been observed.
12. End with a summary of changed files, tests, remaining risks, and a prioritized next step.
Sources reviewed
- Repository README: https://github.com/Kylin-Guo/novel-to-tavern
- Architecture/data model: https://github.com/Kylin-Guo/novel-to-tavern/blob/master/docs/DATA_MODEL.md
- Format compatibility: https://github.com/Kylin-Guo/novel-to-tavern/blob/master/docs/FORMAT_COMPATIBILITY.md
- Implementation plan: https://github.com/Kylin-Guo/novel-to-tavern/blob/master/docs/IMPLEMENTATION_PLAN.md
- Current plan: https://github.com/Kylin-Guo/novel-to-tavern/blob/master/docs/PLAN.md
- Run report: https://github.com/Kylin-Guo/novel-to-tavern/blob/master/docs/RUN_REPORT.md
- Tavo import checklist: https://github.com/Kylin-Guo/novel-to-tavern/blob/master/docs/TAVO_IMPORT_CHECKLIST.md
- Third-party notices: https://github.com/Kylin-Guo/novel-to-tavern/blob/master/docs/THIRD_PARTY_NOTICES.md
- Public example export: https://github.com/Kylin-Guo/novel-to-tavern/blob/master/exports/%E5%A4%A9%E4%B9%8B%E7%82%BD/world_simulator_v2.json
