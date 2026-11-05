# Case study text (portfolio page and LinkedIn)

## Short version (LinkedIn Featured description)

Saudi e-invoice intake desk. Invoices (text, PDF, photo, Arabic or English) are read by a free built-in reader or an AI model of the user's choice (Gemini, Groq, OpenRouter, Ollama, Claude, OpenAI), checked against rules stored in a database, auto-approved when clean, and routed to a person when not. Rules are edited in the portal with a dry run and version rollback, so policy changes need no deployment. React and TypeScript front end, FastAPI back end, 95 tests, evaluation harness, MCP server. Synthetic data, not ZATCA-certified.

## Long version

**The problem.** Finance teams in Saudi Arabia receive supplier invoices in every shape: emailed PDFs, phone photos, Arabic, English, bilingual. Someone retypes them and checks the VAT number, the 15% VAT and the totals by eye. It is slow, and the checking rules live in people's heads or in code that needs a release to change.

**What I built.** A desk that takes the invoice in any format, extracts the fields, validates them against a rule set, and decides: approve, send to a person, or reject. A reviewer sees the original next to the extracted fields and can correct anything. Every decision, human or automatic, is logged.

**Decisions worth talking about.**
- *Rules are data.* Each rule is a row with a type, parameters and a severity. Admins add and edit rules in the portal; the next invoice uses them. Before saving, a dry run replays past invoices and shows how many decisions would change. Every change is a version that can be restored. For anything the 13 built-in rule types cannot express, there is a custom expression rule run by a small hand-written evaluator that allows only arithmetic, comparisons and a short list of helper functions.
- *The model proposes, the rules dispose.* The model only extracts. It never decides. Approval comes from deterministic checks, so a wrong or manipulated extraction is caught by arithmetic and format rules. The extraction prompt treats document text as data, and one of the test invoices contains an instruction aimed at the model.
- *Free by default.* A rule-based reader handles clean text and PDFs so anyone can try the product without a key. For harder files, users bring their own key for a free provider such as Gemini or Groq, kept in the browser tab only.
- *Measure honestly.* 60 synthetic invoices with an answer key. The rule-based reader gets the right decision on 80%, never auto-approves something it should not, and sends what it cannot read to a person. Images and unusual wording are its weakness, which is the case for using a model there.

**Stack.** Python, FastAPI, SQLite, provider adapters for Gemini, OpenAI-compatible APIs and Anthropic (JSON output, PDF and image input), React, TypeScript, Vite, Docker, GitHub Actions, MCP.

**Limits.** Not ZATCA-certified. Synthetic data only. AI-model accuracy figures come from whoever runs it with their own key.

## Post draft (optional, after you have run an AI model)

I built a small invoice desk for Saudi e-invoices to see how far "model proposes, rules decide" goes. Clean invoices clear automatically, doubtful ones land with a person, and finance can change the rules without a deployment. On 60 synthetic invoices, plain rules got X% right and Gemini got Y%. The interesting part was Z. Demo and code in the first comment.

(Fill X, Y and Z from your own run. Do not post numbers you have not measured.)
