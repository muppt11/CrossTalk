# CrossTalk

CrossTalk is a Streamlit MVP that compares the README files of 2 to 10 public GitHub repositories and scores each pair on how composable (buildable together) or redundant (competing) they are.

## Run locally

1. Install Python 3.10 or newer.
2. Create and activate a virtual environment:

	```powershell
	py -m venv .venv
	.\.venv\Scripts\Activate.ps1
	```

3. Install dependencies:

	```powershell
	python -m pip install -r requirements.txt
	```

4. Configure your API keys. The app reads them from Streamlit secrets:

	```powershell
	Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml
	# Edit .streamlit\secrets.toml and replace the placeholder key(s).
	```

	Or set them for the current PowerShell session:

	```powershell
	$env:OPENAI_API_KEY = "your-api-key"
	$env:GITHUB_TOKEN = "your-github-token"
	```

	Both are optional. `OPENAI_API_KEY` unlocks semantic analysis (see below). `GITHUB_TOKEN`
	is free — a classic personal access token with no scopes needed for public repos — and
	raises the GitHub API rate limit from 60 requests/hour to 5,000/hour.

5. Start the app. The main frontend is a plain HTML/CSS/JS site (in `web/`) served by a small Starlette API (`server.py`); no Node.js or build step is needed:

	```powershell
	python -m uvicorn server:app --port 8600 --reload
	```

	Then open http://127.0.0.1:8600. The original Streamlit version (`app.py`) still works and shares the same analysis code: `streamlit run app.py`.

Pick two to ten projects from the search results (or type `owner/repo`) to analyze them together. The Streamlit version takes one `owner/repo` per line instead. CrossTalk reads up to 2,500 characters from each README through the GitHub API; GitHub authentication is optional (see above).

Use **Search GitHub** in the app to discover real public projects by capability or tool name, such as `authentication middleware`, `project management`, `vector database`, or `API gateway`. Select results to add them to the analysis list, then review the repository descriptions, stars, and languages before running the comparison.

An OpenAI key is optional. Without one, CrossTalk scores every project pair on two independent axes computed locally (per-batch TF-IDF similarity plus a capability-adjacency map — no data leaves your machine):

- **Composability** — rewards *different-but-adjacent* capability areas (e.g. an authentication library and an API framework). High composability means "build these together."
- **Redundancy** — rewards *matching* capability areas and shared README language. High redundancy means "these compete — pick one as the base."

With `OPENAI_API_KEY`, it uses `gpt-4o-mini` for semantic analysis and richer explanations instead. Either way, the report is designed to identify useful relationships: a project that can be extended, wrapped, adapted, or combined with another project, not just projects that are duplicates.

## Connect GitHub (sign in and see your own repositories)

The web version has a **Connect GitHub** button that signs you in with GitHub so you can browse your own repositories, including private ones, and analyze them. It needs a one-time setup, because GitHub requires every app that offers sign-in to be registered:

1. On GitHub go to **Settings → Developer settings → OAuth Apps → New OAuth App**.
2. Set **Homepage URL** to `http://127.0.0.1:8600` and **Authorization callback URL** to `http://127.0.0.1:8600/auth/callback` (use `127.0.0.1`, not `localhost`).
3. Click **Register application**, copy the **Client ID**, then click **Generate a new client secret** and copy it.
4. Provide both values as environment variables, or in `.streamlit/secrets.toml` (see `.streamlit/secrets.toml.example`):

	```powershell
	$env:GITHUB_CLIENT_ID = "your-client-id"
	$env:GITHUB_CLIENT_SECRET = "your-client-secret"
	```

5. Restart the server and click **Connect GitHub**.

How it works and what to know:

- **Private repos need the broad `repo` permission.** GitHub has no read-only private-repo scope for OAuth apps, so approving sign-in grants CrossTalk read/write access to your private repositories. It only reads READMEs and repository lists, but you can revoke it any time under GitHub **Settings → Applications**.
- **Your token never reaches the browser.** It is held in server memory; the browser only gets an opaque session cookie (`HttpOnly`, `SameSite=Lax`). Restarting the server signs you out.
- **Private READMEs never go to OpenAI.** While you are signed in, analysis always uses the local scoring, even if `OPENAI_API_KEY` is set.
- Signed-in requests also use your own GitHub rate limit (5,000 requests/hour).
- This is built for running locally. Hosting it publicly for multiple users would need a persistent session store and an `https` `PUBLIC_BASE_URL` (set that variable and update the OAuth App's callback URL to match).