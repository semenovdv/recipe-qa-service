Take-Home Assignment: Recipe Q&A Service

Build a small service that answers questions about recipes from a public corpus. Users ask questions in natural language. Examples: "What's a vegetarian dinner I can make in under 30 minutes?" "How do I make carbonara?" The service must:

• Give answers that come only from the corpus.
• Give citations (recipe titles and URLs) with each answer.
• Refuse questions that the corpus cannot answer. Refuse politely.

This assignment shows how we work. How you design, decide, specify, verify, and ship is more important to us than the code.

Build the service as a production service, not as a demo. Apply current best practices for code quality, security, CI/CD, and operations. Full production grade is not possible in a few hours. If you stop before production grade, write this in the README. Write what is necessary to close the gap.

AI coding agents (Claude Code, Cursor, etc.) are permitted, and we recommend them. We use them each day. You stay responsible for each line and each decision.

Time budget: 6 to 8 hours of focused work. Do not add unnecessary polish. Cut scope consciously and record what you cut. If the core functions end to end and you have time, you can add more features. Extra features are a bonus. They are not a replacement for the core.

Stack

• Backend: Python or TypeScript. We prefer Python.
• Frontend: TypeScript. This is mandatory. See the UI section below.
• Other choices (framework, vector store, LLM provider) are yours. Give your reasons in an ADR.

The Corpus

Get 40 to 60 recipes from the Wikibooks Cookbook (https://en.wikibooks.org/wiki/Cookbook) through the MediaWiki API. Select some categories, for example: soups, desserts, vegetarian dishes. Make sure that the corpus has variety: different cuisines, dishes that overlap, and different levels of structure. Commit your ingestion script. We must be able to build the corpus again from only the script.

What to Build

1. POST /ask - receives a question and returns a structured JSON response. See the contract below.
2. A minimal web UI (TypeScript): one page. The user types a question. The page shows the answer, the citations, and refusals. The UI must function. We do not grade its appearance.

Response contract

Each response must be machine-readable. The eval harness examines each response against this contract. Define the full schema in SPEC.md. The minimum schema is:

{
  "answer": "string | null",
  "citations": [{ "title": "...", "url": "..." }],
  "refused": false,
  "refusal_reason": "out_of_corpus | out_of_domain | safety | null"
}


A refusal that is only polite text in answer is not sufficient. A refusal must be detectable without analysis of natural language.

Functional requirements

• Base each answer on the recipes that the service retrieves. Do not let the model answer from its memory.
• Obey the constraints in a question (time, diet, ingredient).
• Refuse questions that are out of the corpus or out of the domain. Use the machine-readable refusal.
• Be careful with questions about allergies or safety, for example: "Is this nut-free?" Decide what "careful" means. Record your decision.

Deployment (mandatory)

A repository that operates only on your computer is not sufficient. Deploy the service and make it available:

• Give a public URL for the UI and for the API. We will use both.
• Give us a way to see how the service operates at the container level. Options: an invitation to your hosting dashboard, or access to logs and container status. Select one option and record it in the README.
• We prefer infrastructure as code. Commit the files that define the deployment (Terraform, Pulumi, render.yaml, fly.toml, docker-compose plus a CI pipeline, etc.). A new deployment from the repository must be possible without manual steps in a UI.
• Obey basic production rules: keep secrets in the environment, not in the repository. Make the builds reproducible (we prefer Docker). Make sure that the deploy procedure is safe to do two times.

Cheap or free tiers are sufficient. We examine practices, not infrastructure costs.

Deliverables

1. SPEC.md - write this before you write code. Write the behavior specification: the API contract with the full response schema, the acceptance criteria, the edge cases (an empty question, an out-of-domain question, recipes that disagree about the same dish, allergy questions), and the non-functional targets (latency budget, cost for 1,000 questions). If a part of this assignment is not clear, ask us, or record your assumption in SPEC.md. Hidden hardcoded behavior is the only incorrect option.

2. ADRs (2 or 3). Write Architecture Decision Records for your important choices. Possible topics: chunking strategy (a recipe as one unit, or ingredients and steps as different parts), retrieval method (lexical, embeddings, or hybrid; metadata filters for constraints), model selection, refusal policy, caching, deployment target. Each ADR must contain: the alternatives that you examined, the criteria, the trade-offs (with real cost and latency numbers where possible), and the conditions that make the decision invalid.

3. Eval harness. Make a golden set of 12 to 15 questions. Give each question its expected properties: the service retrieves the correct source; the service refuses where necessary; the service obeys the constraint. Make a script that runs the full set automatically and reports the results. The script must examine each response against the JSON contract. This is your proof that the service operates correctly. Manual tests of some questions are not sufficient.

4. Tests and a granular commit history. Write automated tests for the logic that does not use the LLM: ingestion, retrieval, filters, API contract. Commit in small steps. For a part of the functions, commit the test before the implementation.

5. README.md with a Cost & Latency section and a Deployment section.

• How to run the service locally (we prefer Docker). Where the service is deployed, why you selected that provider, and how a new deployment operates.
• The cost of one question and of 1,000 questions. The models that you selected, and why. The conditions that cause a change to a cheaper or a more capable model.
• The current bottleneck, and what you will optimize next.
• One paragraph: a bad answer occurs in production. How do you find the cause? What do you log or trace to make this possible?

6. AI usage notes - files, not summaries. Commit the instructions that you gave to your agents: CLAUDE.md or rule files, important prompts, and spec files. Add short notes about what you accepted and what you wrote again. This is not a trick question. We want to see your workflow.

What We Evaluate

1. SPEC.md - Can you change an unclear request into requirements that we can verify, before you build?
2. ADRs - Do you know why, not only what? Can you think about trade-offs?
3. Eval harness - Do you measure the quality of the LLM pipeline?
4. Tests and history - Engineering discipline, also when an agent writes the code.
5. Cost and latency notes - Do you think as an owner, not only as a builder?
6. Deployment - Does the service operate for us, end to end? Are the deployment practices correct (IaC, secrets, reproducibility)?

We do not grade UI polish or the quantity of code. Extra features get credit only on a core that is complete, deployed, and evaluated. Production-grade practices have an effect on each criterion above.

Follow-Up Session

If we continue, we will examine your solution together. You will defend one or two of your ADRs. Then we will give you a new requirement, live. We will examine how you do it: spec and evals first, code second.

Submission

Give us access to a private Git repository (share access with us) that contains all deliverables. Add the deployed URL and the container-level access described above.