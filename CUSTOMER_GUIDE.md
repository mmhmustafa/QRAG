# Customer Questionnaire Assistant — Setup and User Guide

This application answers customer questionnaires (security, compliance, RFP) using only your approved internal documents. Every answer cites its source evidence; questions your documentation cannot answer are marked **Needs Manual Input** instead of being invented.

It runs entirely on your own machine. Your documents, questionnaires, and answers never leave it — the only outbound traffic is to the AI provider you configure.

---

## 1. What you need

- A Windows PC (8 GB RAM or more recommended)
- [Python 3.11 or newer](https://www.python.org/downloads/) — tick "Add python.exe to PATH" during installation
- [Node.js 20 or newer](https://nodejs.org/)
- An AI provider API key. [OpenRouter](https://openrouter.ai/) is recommended to start: one key gives access to many models, including free ones.

## 2. One-time setup

Open PowerShell in the application folder and run:

```powershell
Copy-Item .env.example .env
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
npm install --prefix frontend
```

## 3. Start the application

Double-click **`start-production.cmd`** (or run it from PowerShell). It builds the interface once, then opens two windows — the backend (port 8000) and the frontend (port 3000). Keep both open while working.

Open **http://localhost:3000** in your browser and bookmark it.

To stop, close both server windows.

## 4. First-time configuration

Work top to bottom; each step takes a minute.

### a. Create your organization
Go to **Customers** → enter your organization name → **Create customer** → **Open workspace**. All documents, questionnaires, and settings are isolated per customer workspace.

### b. Connect your AI provider
Go to **Settings**:
1. Choose your **AI Provider** (e.g. `openrouter`) and paste your API key.
2. Pick a **Chat Model** (with OpenRouter, use **Fetch Chat Models** and choose one — free models work).
3. Pick an **Embedding Provider** and **Embedding Model** the same way.
4. Click **Test AI Connection** and **Test Embedding Connection** — both must show Connected.
5. **Save**.

Keys are stored locally and never shown again in the interface.

### c. Upload your knowledge documents
Go to **Knowledge base**:
1. Set the **Category** before uploading — it matters: Products and Security documents outrank Company or Marketing material when evidence conflicts.
2. Optionally set **Knowledge Collections** (e.g. "Product Alpha", "Security") to group documents; questionnaires choose which collections to search.
3. Drag in your PDF/DOCX/XLSX/CSV/TXT files (max 25 MB each) and upload.
4. Wait until every document shows **indexed**.
5. Use **Test Retrieval** at the bottom to ask a sample question and confirm the right documents come back.

### d. Upload a questionnaire
Go to **Questionnaires**:
1. Select the Knowledge Collections the answers should be grounded in.
2. Upload the questionnaire file. The app reports how many questions it found — **check this matches the document** (it warns if numbered questions could not be extracted).
3. Click **Review & generate**, then **Generate Answers**.

### e. Generate and review
Generation runs in the background with live progress (current question, percentage, time remaining). You can navigate away, cancel, or resume — completed answers are never lost.

When it finishes, every question has a status:

| Status | Meaning | What to do |
|---|---|---|
| **Ready to Approve** | Strong evidence, verified against sources | Skim and approve (or **Approve All Ready**) |
| **Check Suggested Answer** | Good draft, evidence worth confirming | Read, edit if needed, approve |
| **Needs Manual Input** | Documentation doesn't cover it | Write the answer yourself |
| **Failed** | A technical error (e.g. provider outage) | Click **Retry failed questions** |

Review tips:
- Click the status chips to filter; click a number in the strip to jump to that question.
- **Focus Review** steps through one question at a time — `A` approve, `E` edit, arrow keys to move.
- Expand **Evidence** on any card to see exactly which document passages support the answer; click **Open Source** to view the original page.
- Mark your best reusable answers as **Golden** — future questionnaires reuse approved answers automatically when the evidence still holds.

### f. Export
**Export ▾ → Export customer copy** produces a clean spreadsheet with only questions and approved answers (it warns if any would be blank). **Export with internal evidence** is your internal review copy with sources and confidence.

## 5. Day-to-day notes

- **Backups**: every backend start snapshots the database to the `backups\` folder (last 10 kept). The database holds all your approved answers — to restore, stop the app and copy a snapshot back over `questionnaire.db`.
- **Interrupted generation** (e.g. PC restarted): the questionnaire shows *Interrupted* — open it and click **Resume remaining questions**.
- **Changed embedding settings?** Documents must be re-indexed; the app shows a warning banner with a **Re-index All Documents** button.
- **Starting fresh**: **Delete all** on the Knowledge base page removes every document for the workspace.
- **Regenerate All never touches approved answers** unless you explicitly choose "Regenerate all incl. approved".

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| "returned an empty response" failures | The AI provider is overloaded or rate-limited; **Retry failed questions**, or pick a different model in Settings |
| Fewer questions extracted than the file contains | The upload notice shows both counts; check the file's formatting or contact your administrator |
| Answers cite the wrong documents | Use **Test Retrieval** on the Knowledge base page to inspect what search returns; check documents are indexed and in the right collections |
| Everything says Needs Manual Input | Usually the embedding model changed without re-indexing, or the questionnaire's collections don't match the documents' collections |
| Page shows an API error | Confirm the backend window is still running; restart via `start-production.cmd` |

## 7. Security notes

- There is **no login** — the application trusts whoever uses this machine. Do not expose it to a network or the internet.
- Your AI provider keys and all answer data live in `questionnaire.db` and `backups\` — include them in your normal disk backup/encryption, and don't share those files.
- Uploaded source files are stored under `data\uploads\`.
