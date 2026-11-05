# Putting it online for free

Two parts: the code on GitHub, and a live demo anyone can click. Both are free.

## 1. GitHub

1. On github.com press **New repository**. Name it `invoice-desk`, keep it **Public**, do not add a README.
2. In Command Prompt, inside the unzipped `invoice-desk` folder:
   ```
   git init
   git add .
   git commit -m "Add invoice-desk"
   git branch -M main
   git remote add origin https://github.com/Necromancer14/invoice-desk.git
   git push -u origin main
   ```
3. On the repo page click the gear next to **About** and add topics: `fastapi`, `react`, `typescript`, `claude`, `llm`, `human-in-the-loop`, `invoice-processing`, `mcp`.
4. The **Actions** tab will run the tests and the portal build automatically. A green tick is worth showing.

## 2. Live demo on Hugging Face Spaces (free)

1. Create a free account at huggingface.co.
2. **New Space** → name `invoice-desk` → SDK **Docker** → hardware **CPU basic (free)** → **Public**.
3. Copy these into the Space repo (it is a git repo like any other): the whole project folder contents. The `Dockerfile` already uses port 7860.
   ```
   git remote add space https://huggingface.co/spaces/<your-hf-name>/invoice-desk
   git push space main
   ```
   If it asks for a password, use a **write access token** from huggingface.co/settings/tokens.
4. Add this to the top of the Space's `README.md` (Spaces reads it for settings):
   ```
   ---
   title: invoice-desk
   sdk: docker
   app_port: 7860
   ---
   ```
5. Wait for the build (a few minutes). Open the Space URL, pick a role, press **Upload invoices** then **Load 12 text samples**.
6. Put the Space URL in the GitHub repo's **Website** field and in your LinkedIn Featured section.

Free Spaces go to sleep when idle and restart on the next visit; the data resets each time, which is fine for a demo.

## What visitors can do without a key

Everything with the built-in reader: upload, review, edit rules, simulate, roll back, evaluation, audit log. To use an AI model they pick a provider in Settings (Google Gemini and Groq have free keys) and paste their own key, which stays in their tab.

## Keep your own key safe

Never put an API key in the repo, in a public Space variable, or in a screenshot. To ship a recorded AI run with the project, run the Evaluation page locally with your own key, save the JSON it returns to `data/recorded/evaluation_ai.json`, and the page will show it labelled as a recorded run.

## Before you publish

- This project is yours and unrelated to Oz. Do not add anything from your work, and check your contract if you are unsure.
- Run an AI model once yourself (Gemini's free key is enough) so you can speak to real numbers.
- Read the code. You should be able to explain every file in an interview.
