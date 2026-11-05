# Try it on your Windows PC

You need Python 3.11 or newer. Check in Command Prompt: `py --version`. If it is missing or older, install the latest from python.org and tick **Add python.exe to PATH**.

1. Open the `invoice-desk` folder in File Explorer, click the address bar, type `cmd`, press Enter. A Command Prompt opens already inside the folder.
2. Install: `py -m pip install -e .` (a minute or two the first time).
3. Start: `py -m uvicorn invoice_desk.api:app --port 8000`
4. Open http://localhost:8000 in your browser and pick **Admin**.
5. Press **Upload invoices**, then **Load 12 text samples**. They appear under **Runs**; some go to **Review queue**.
6. Try **Rules**: add a rule, press **Check impact on past invoices**, save, restore the old version.
7. Optional, for images and odd layouts: **Settings** → Google Gemini → paste a free key from aistudio.google.com/apikey → **Save and test connection**. Then on **Upload invoices** choose **AI model** and load the image samples.
8. Stop the server with Ctrl+C in the Command Prompt.

Data is kept in memory, so restarting gives you a clean demo. To keep data between runs: `set INVOICE_DESK_DB=desk.db` before step 3.

If step 2 says `pip` is not recognised, use `py -m pip` exactly as written. If port 8000 is busy, use `--port 8010` and open that port instead.
